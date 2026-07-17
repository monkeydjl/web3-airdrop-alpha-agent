from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import tempfile
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .advice import build_suggestions, cluster_bootstrap_interval, gate_state, segment_key
from .metrics import decision_metrics, economic_metrics, probability_metrics
from .models import (
    CALIBRATION_LABELS,
    CALIBRATION_STATUSES,
    CALIBRATION_WALLET_BANDS,
    BinaryObservation,
    CalibrationDataset,
    CalibrationSample,
    NumericObservation,
    OutcomeValues,
)
from .outcomes import map_outcomes, maturity_state

SCHEMA = "opportunity-calibration-v1"
WINDOWS = (90, 180)
VIEWS = ("cohort_weighted", "project_equal")
BOOTSTRAP_REPLICATES = 1000
LOADER_QUALITY_KEYS = (
    "invalid_project_id",
    "missing_linkage",
    "mismatched_project",
    "unsupported_version",
    "missing_or_invalid_cohort",
    "malformed_assessment_json",
    "invalid_timestamp",
    "duplicate_pair",
)
PROBABILITY_FIELDS = (
    ("event", "event_probability"),
    ("eligibility", "eligibility_probability"),
    ("survival", "survival_probability"),
    ("reward", "reward_probability"),
)
ECONOMIC_FIELDS = (
    ("net_reward", "net_reward", "realized_net_usd"),
    ("hard_cost", "hard_cost", "actual_hard_cost_usd"),
    ("total_time", "total_time_hours", "actual_time_hours"),
)
FIXED_SEGMENTS = (
    *(f"label:{value}" for value in CALIBRATION_LABELS),
    *(f"status:{value}" for value in CALIBRATION_STATUSES),
    *(f"wallet:{value}" for value in CALIBRATION_WALLET_BANDS),
)


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain(child) for key, child in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(child) for child in value]
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("report numbers must be finite")
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"unsupported report value: {type(value).__name__}")


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(_plain(value), ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()


def canonical_report_json(report: Mapping[str, Any]) -> bytes:
    """Serialize a finalized calibration report to stable UTF-8 JSON."""
    report_id = report.get("metadata", {}).get("report_id")
    if not isinstance(report_id, str) or not report_id:
        raise ValueError("report must contain a finalized report_id")
    return _canonical_bytes(report)


def _observations(
    samples: Sequence[CalibrationSample], outcomes: Sequence[OutcomeValues], concerns: Sequence[tuple[str, ...]]
) -> tuple[dict[str, tuple[BinaryObservation, ...]], dict[str, tuple[NumericObservation, ...]]]:
    probability: dict[str, list[BinaryObservation]] = {name: [] for name, _ in PROBABILITY_FIELDS}
    economic: dict[str, list[NumericObservation]] = {name: [] for name, _, _ in ECONOMIC_FIELDS}
    for sample, outcome, sample_concerns in zip(samples, outcomes, concerns, strict=True):
        for name, prediction_name in PROBABILITY_FIELDS:
            actual = getattr(outcome, name)
            if actual is not None:
                probability[name].append(
                    BinaryObservation(sample.project_id, getattr(sample, prediction_name).base, actual)
                )
        for name, prediction_name, actual_name in ECONOMIC_FIELDS:
            actual = getattr(outcome, actual_name)
            if actual is not None and (name != "net_reward" or not sample_concerns):
                prediction = getattr(sample, prediction_name)
                economic[name].append(
                    NumericObservation(sample.project_id, prediction.low, prediction.base, prediction.high, actual)
                )
    return (
        {name: tuple(values) for name, values in probability.items()},
        {name: tuple(values) for name, values in economic.items()},
    )


def _probability_evidence(
    records: Sequence[BinaryObservation], view: str, denominator: int, seed: int, *, segmented: bool
) -> dict[str, Any]:
    result = dict(probability_metrics(records, view=view, coverage_denominator=denominator))
    result["observed_gap"] = result["bias"]
    result["ci95"] = cluster_bootstrap_interval(
        records,
        lambda resample: probability_metrics(resample, view=view, coverage_denominator=len(resample))["bias"],
        seed=seed,
        replicates=BOOTSTRAP_REPLICATES,
    )
    result["gate"] = gate_state(result["sample_count"], result["project_count"], segmented=segmented)
    return result


def _economic_evidence(
    records: Sequence[NumericObservation], view: str, seed: int, *, segmented: bool
) -> dict[str, Any]:
    result = dict(economic_metrics(records, view=view))
    result["observed_gap"] = result["mean_signed_error"]
    result["ci95"] = cluster_bootstrap_interval(
        records,
        lambda resample: economic_metrics(resample, view=view)["mean_signed_error"],
        seed=seed,
        replicates=BOOTSTRAP_REPLICATES,
    )
    result["gate"] = gate_state(result["sample_count"], result["project_count"], segmented=segmented)
    return result


def _decision_view(
    samples: Sequence[CalibrationSample],
    outcomes: Sequence[OutcomeValues],
    *,
    view: str,
    seed: int,
    segmented: bool,
) -> dict[str, Any]:
    result = _plain(decision_metrics(samples, outcomes, view=view))
    eligible = tuple(
        (sample, outcome)
        for sample, outcome in zip(samples, outcomes, strict=True)
        if outcome.realized_net_usd is not None and outcome.realized_class is not None
    )
    for label, utility in result["utility_by_label"].items():
        records = tuple((sample, outcome) for sample, outcome in eligible if sample.public_label == label)
        utility["mean_net_ci95"] = cluster_bootstrap_interval(
            tuple({"project_id": sample.project_id, "net": outcome.realized_net_usd} for sample, outcome in records),
            lambda rows: sum(row["net"] for row in rows) / len(rows),
            seed=seed,
            replicates=BOOTSTRAP_REPLICATES,
        )
    for name, observed_gap in result["adjacent_utility_separation"].items():
        interval = None
        adjacent_labels = ("FARM", "WATCH") if name == "farm_minus_watch" else ("WATCH", "IGNORE")
        labels_by_project: dict[str, set[str]] = {}
        for sample, _ in eligible:
            labels_by_project.setdefault(sample.project_id, set()).add(sample.public_label)
        bootstrap_is_defined = len(labels_by_project) >= 2 and all(
            set(adjacent_labels) <= labels for labels in labels_by_project.values()
        )
        if observed_gap is not None and bootstrap_is_defined:
            interval = cluster_bootstrap_interval(
                tuple(
                    {"project_id": sample.project_id, "sample": sample, "outcome": outcome}
                    for sample, outcome in eligible
                ),
                lambda rows, separation=name: decision_metrics(
                    tuple(row["sample"] for row in rows),
                    tuple(row["outcome"] for row in rows),
                    view=view,
                )["adjacent_utility_separation"][separation],
                seed=seed,
                replicates=BOOTSTRAP_REPLICATES,
            )
        result["adjacent_utility_separation"][name] = {
            "observed_gap": observed_gap,
            "ci95": interval,
            "sample_count": result["sample_count"],
            "project_count": result["project_count"],
            "gate": gate_state(result["sample_count"], result["project_count"], segmented=segmented),
        }
    result["gate"] = gate_state(result["sample_count"], result["project_count"], segmented=segmented)
    return result


def _scope_report(
    samples: Sequence[CalibrationSample],
    outcomes: Sequence[OutcomeValues],
    concerns: Sequence[tuple[str, ...]],
    *,
    scope: str,
    window: str,
    model_version: str,
    profile_version: str,
    seed: int,
) -> dict[str, Any]:
    probability, economic = _observations(samples, outcomes, concerns)
    segmented = scope != "overall"
    views: dict[str, Any] = {}
    for view in VIEWS:
        views[view] = {
            "probability": {
                name: _probability_evidence(records, view, len(samples), seed, segmented=segmented)
                for name, records in probability.items()
            },
            "economic": {
                name: _economic_evidence(records, view, seed, segmented=segmented) for name, records in economic.items()
            },
            "decision": _decision_view(samples, outcomes, view=view, seed=seed, segmented=segmented),
        }
    advice_contract = {
        "scope": scope,
        "window": window,
        "model_version": model_version,
        "profile_version": profile_version,
        "project_equal": {
            "probability": views["project_equal"]["probability"],
            "economic": views["project_equal"]["economic"],
            "decision": {
                name: evidence
                for name, evidence in views["project_equal"]["decision"]["adjacent_utility_separation"].items()
                if evidence["ci95"] is not None
            },
        },
    }
    return {
        "scope": scope,
        "sample_count": len(samples),
        "project_count": len({sample.project_id for sample in samples}),
        "gate": gate_state(len(samples), len({sample.project_id for sample in samples}), segmented=segmented),
        **views,
        "suggestions": _plain(build_suggestions(advice_contract)),
    }


def _window_report(
    samples: Sequence[CalibrationSample],
    *,
    days: int,
    as_of: datetime,
    model_version: str,
    profile_version: str,
    seed: int,
) -> tuple[dict[str, Any], dict[str, int]]:
    states = tuple(maturity_state(sample, as_of=as_of, window_days=days) for sample in samples)
    state_counts = Counter(states)
    mature = tuple(sample for sample, state in zip(samples, states, strict=True) if state == "mature")
    mapped = tuple(map_outcomes(sample) for sample in mature)
    outcomes = tuple(item[0] for item in mapped)
    concerns = tuple(item[1] for item in mapped)
    resolved = {name: sum(getattr(outcome, name) is not None for outcome in outcomes) for name, _ in PROBABILITY_FIELDS}
    unresolved = {name: len(mature) - count for name, count in resolved.items()}
    resolved.update(
        {
            name: sum(
                not concern and getattr(outcome, actual_name) is not None
                for outcome, concern in zip(outcomes, concerns, strict=True)
            )
            for name, _, actual_name in ECONOMIC_FIELDS
        }
    )
    unresolved.update({name: len(mature) - resolved[name] for name, _, _ in ECONOMIC_FIELDS})
    window_name = f"{days}d"
    overall = _scope_report(
        mature,
        outcomes,
        concerns,
        scope="overall",
        window=window_name,
        model_version=model_version,
        profile_version=profile_version,
        seed=seed,
    )
    segments = {}
    for fixed_scope in FIXED_SEGMENTS:
        indexes = tuple(
            index
            for index, sample in enumerate(mature)
            if any(segment_key(sample, segment_type) == fixed_scope for segment_type in ("label", "status", "wallet"))
        )
        segments[fixed_scope] = _scope_report(
            tuple(mature[index] for index in indexes),
            tuple(outcomes[index] for index in indexes),
            tuple(concerns[index] for index in indexes),
            scope=fixed_scope,
            window=window_name,
            model_version=model_version,
            profile_version=profile_version,
            seed=seed,
        )
    return (
        {
            "mature_sample_count": len(mature),
            "mature_project_count": len({sample.project_id for sample in mature}),
            "gate": overall["gate"],
            **{view: overall[view] for view in VIEWS},
            "segments": segments,
            "suggestions": overall["suggestions"],
            "quality": {
                "resolved": resolved,
                "unresolved": unresolved,
                "contradictory_outcomes": sum(bool(value) for value in concerns),
            },
        },
        {
            state: state_counts[state]
            for state in ("mature", "immature", "outcome_before_assessment", "outcome_after_as_of")
        },
    )


def _iso_utc(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def build_calibration_report(
    dataset: CalibrationDataset, *, as_of: datetime, seed: int = 20260717
) -> Mapping[str, Any]:
    """Build deterministic aggregate calibration views for fixed 90/180-day windows."""
    samples = tuple(sorted(dataset.samples, key=lambda item: (item.project_id, item.assessment_id, item.cohort_id)))
    model_versions = {sample.model_version for sample in samples}
    profile_versions = {sample.profile_version for sample in samples}
    if len(model_versions) > 1 or len(profile_versions) > 1:
        raise ValueError("calibration dataset must contain one model and profile version")
    model_version = next(iter(model_versions), "unknown")
    profile_version = next(iter(profile_versions), "unknown")
    windows = {}
    maturity = {}
    for days in WINDOWS:
        windows[f"{days}d"], maturity[f"{days}d"] = _window_report(
            samples,
            days=days,
            as_of=as_of,
            model_version=model_version,
            profile_version=profile_version,
            seed=seed,
        )
    report = {
        "metadata": {
            "schema": SCHEMA,
            "model_version": model_version,
            "profile_version": profile_version,
            "as_of": _iso_utc(as_of),
            "windows": list(WINDOWS),
            "bootstrap_seed": seed,
            "bootstrap_replicates": BOOTSTRAP_REPLICATES,
            "database_backend": dataset.backend,
        },
        "data_quality": {
            "linked_sample_count": len(samples),
            "loader": {key: int(dataset.quality.get(key, 0)) for key in LOADER_QUALITY_KEYS},
            "maturity": maturity,
        },
        "windows": windows,
    }
    digest = hashlib.sha256(_canonical_bytes(report)).hexdigest()
    report["metadata"]["report_id"] = digest
    return _plain(report)


def _format_number(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return format(value, ".6g")
    return str(value)


def render_markdown(report: Mapping[str, Any]) -> str:
    """Render finalized report fields without recalculating metrics."""
    metadata = report["metadata"]
    lines = [
        "# Opportunity Calibration Report",
        "",
        f"- Report ID: `{metadata['report_id']}`",
        f"- Schema: `{metadata['schema']}`",
        f"- As of: `{metadata['as_of']}`",
        f"- Model/Profile: `{metadata['model_version']}` / `{metadata['profile_version']}`",
        f"- Bootstrap: {metadata['bootstrap_replicates']} project-cluster replicates (seed {metadata['bootstrap_seed']})",
        "",
    ]
    for window_name in ("90d", "180d"):
        window = report["windows"][window_name]
        lines.extend(
            [
                f"## {window_name}",
                "",
                f"Mature samples: {window['mature_sample_count']}; projects: {window['mature_project_count']}; gate: `{window['gate']}`.",
                "",
                "| View | Dimension | Samples | Coverage | Bias | CI95 | Gate |",
                "|---|---|---:|---:|---:|---|---|",
            ]
        )
        for view in VIEWS:
            for dimension in (name for name, _ in PROBABILITY_FIELDS):
                metric = window[view]["probability"][dimension]
                interval = metric["ci95"]
                ci = "n/a" if interval is None else f"[{_format_number(interval[0])}, {_format_number(interval[1])}]"
                lines.append(
                    f"| {view} | {dimension} | {metric['sample_count']} | {_format_number(metric['coverage'])} | "
                    f"{_format_number(metric['observed_gap'])} | {ci} | {metric['gate']} |"
                )
        lines.extend(["", f"Suggestions: {len(window['suggestions'])}.", ""])
    return "\n".join(lines).rstrip() + "\n"


def _temporary_path(output_dir: Path, suffix: str) -> Path:
    descriptor, name = tempfile.mkstemp(prefix=".opportunity-calibration-", suffix=suffix, dir=output_dir)
    os.close(descriptor)
    return Path(name)


def _write_bytes(path: Path, content: bytes) -> None:
    with path.open("wb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


def write_report_pair(report: Mapping[str, Any], output_dir: str | Path) -> tuple[Path, Path]:
    """Publish matching JSON/Markdown files, rolling back any partial replacement."""
    json_content = canonical_report_json(report)
    markdown_content = render_markdown(report).encode()
    destination = Path(output_dir)
    if destination.exists() and not destination.is_dir():
        raise NotADirectoryError(destination)
    destination.mkdir(parents=True, exist_ok=True)
    report_id = report["metadata"]["report_id"]
    json_path = destination / f"opportunity-calibration-{report_id}.json"
    markdown_path = destination / f"opportunity-calibration-{report_id}.md"
    temporary: list[Path] = []
    backups: dict[Path, Path] = {}
    published: list[Path] = []
    try:
        json_temp = _temporary_path(destination, ".json.tmp")
        markdown_temp = _temporary_path(destination, ".md.tmp")
        temporary.extend((json_temp, markdown_temp))
        _write_bytes(json_temp, json_content)
        _write_bytes(markdown_temp, markdown_content)
        for final in (json_path, markdown_path):
            if final.exists():
                backup = _temporary_path(destination, f".{final.suffix.removeprefix('.')}.backup.tmp")
                shutil.copyfile(final, backup)
                backups[final] = backup
                temporary.append(backup)
        for source, final in ((json_temp, json_path), (markdown_temp, markdown_path)):
            source.replace(final)
            published.append(final)
        return json_path, markdown_path
    except Exception:
        rollback_failed = False
        for final in reversed(published):
            try:
                backup = backups.get(final)
                if backup is not None and backup.exists():
                    backup.replace(final)
                else:
                    final.unlink(missing_ok=True)
            except OSError:
                rollback_failed = True
        if rollback_failed:
            for final in (json_path, markdown_path):
                final.unlink(missing_ok=True)
        raise
    finally:
        for path in temporary:
            path.unlink(missing_ok=True)
