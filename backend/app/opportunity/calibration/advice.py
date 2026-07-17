import math
import random
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from types import MappingProxyType
from typing import Any

from .models import CALIBRATION_LABELS, CALIBRATION_STATUSES, CalibrationSample


def _project_id(record: Any) -> str:
    if isinstance(record, Mapping):
        return str(record["project_id"])
    return str(record.project_id)


def _nearest_rank_index(size: int, percentile: float) -> int:
    return max(0, math.ceil(percentile * size) - 1)


def cluster_bootstrap_interval(
    records: Sequence[Any],
    statistic: Callable[[tuple[Any, ...]], float],
    *,
    seed: int,
    replicates: int = 1000,
) -> tuple[float, float] | None:
    if type(replicates) is not int or replicates <= 0:
        raise ValueError("replicates must be a positive integer")

    clusters: dict[str, list[Any]] = defaultdict(list)
    for record in records:
        clusters[_project_id(record)].append(record)
    projects = sorted(clusters)
    if len(projects) < 2:
        return None

    generator = random.Random(seed)  # noqa: S311 - reproducibility, not security
    values = []
    for _ in range(replicates):
        selected = generator.choices(projects, k=len(projects))
        resample = tuple(record for project in selected for record in clusters[project])
        value = float(statistic(resample))
        if not math.isfinite(value):
            raise ValueError("bootstrap statistic must be finite")
        values.append(value)
    values.sort()
    return values[_nearest_rank_index(replicates, 0.025)], values[_nearest_rank_index(replicates, 0.975)]


def gate_state(sample_count: int, project_count: int, *, segmented: bool = False) -> str:
    if sample_count < 30:
        return "data_quality_only"
    if segmented:
        return "advisory" if project_count >= 10 else "descriptive"
    return "advisory" if sample_count >= 100 and project_count >= 30 else "descriptive"


def segment_key(sample: CalibrationSample, segment_type: str) -> str | None:
    if segment_type == "label":
        return sample.public_label if sample.public_label in CALIBRATION_LABELS else None
    if segment_type == "status":
        return sample.status if sample.status in CALIBRATION_STATUSES else None
    if segment_type == "wallet":
        if sample.wallet_count < 1:
            return None
        if sample.wallet_count <= 2:
            return "1-2"
        if sample.wallet_count <= 10:
            return "3-10"
        return "11+"
    return None


def _crosses_or_touches_zero(interval: Sequence[float]) -> bool:
    return interval[0] <= 0 <= interval[1]


def _base_suggestion(
    report: Mapping[str, Any],
    evidence: Mapping[str, Any],
    *,
    target: str,
    direction: str,
    reason_code: str,
    explanation: str,
) -> Mapping[str, Any]:
    return MappingProxyType(
        {
            "scope": report["scope"],
            "target": target,
            "direction": direction,
            "observed_gap": evidence["observed_gap"],
            "ci95": tuple(evidence["ci95"]),
            "sample_count": evidence["sample_count"],
            "project_count": evidence["project_count"],
            "window": report["window"],
            "model_version": report["model_version"],
            "profile_version": report["profile_version"],
            "reason_code": reason_code,
            "explanation": explanation,
            "evidence": MappingProxyType(
                {
                    "view": "project_equal",
                    "observed_gap": evidence["observed_gap"],
                    "ci95": tuple(evidence["ci95"]),
                }
            ),
            "evidence_view": "project_equal",
            "auto_apply": False,
        }
    )


def build_suggestions(window_report: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    if window_report.get("gate") != "advisory":
        return ()

    project_equal = window_report.get("project_equal", {})
    suggestions = []
    for dimension, evidence in project_equal.get("probability", {}).items():
        if (
            gate_state(
                evidence["sample_count"],
                evidence["project_count"],
                segmented=window_report["scope"] != "overall",
            )
            != "advisory"
        ):
            continue
        low, high = evidence["ci95"]
        if low > 0:
            direction, reason = "increase", "PROBABILITY_BIAS_POSITIVE"
        elif high < 0:
            direction, reason = "decrease", "PROBABILITY_BIAS_NEGATIVE"
        else:
            continue
        suggestions.append(
            _base_suggestion(
                window_report,
                evidence,
                target=f"probability:{dimension}",
                direction=direction,
                reason_code=reason,
                explanation=f"Project-equal {dimension} calibration bias CI excludes zero.",
            )
        )

    for estimate, evidence in project_equal.get("economic", {}).items():
        if (
            gate_state(
                evidence["sample_count"],
                evidence["project_count"],
                segmented=window_report["scope"] != "overall",
            )
            != "advisory"
        ):
            continue
        low, high = evidence["ci95"]
        if low > 0:
            direction, reason = "increase", "ECONOMIC_SIGNED_ERROR_POSITIVE"
        elif high < 0:
            direction, reason = "decrease", "ECONOMIC_SIGNED_ERROR_NEGATIVE"
        else:
            continue
        suggestions.append(
            _base_suggestion(
                window_report,
                evidence,
                target=f"economic:{estimate}",
                direction=direction,
                reason_code=reason,
                explanation=f"Project-equal {estimate} signed-error CI excludes zero.",
            )
        )

    decision_targets = {
        "farm_minus_watch": "FARM-WATCH",
        "watch_minus_ignore": "WATCH-IGNORE",
    }
    for separation, evidence in project_equal.get("decision", {}).items():
        if separation not in decision_targets:
            continue
        if (
            gate_state(
                evidence["sample_count"],
                evidence["project_count"],
                segmented=window_report["scope"] != "overall",
            )
            != "advisory"
        ):
            continue
        interval = evidence["ci95"]
        if evidence["observed_gap"] > 0 and not _crosses_or_touches_zero(interval):
            continue
        family = decision_targets[separation]
        suggestions.append(
            _base_suggestion(
                window_report,
                evidence,
                target=f"decision_threshold_family:{family}",
                direction="review",
                reason_code="DECISION_SEPARATION_UNCERTAIN",
                explanation=f"Project-equal {family} utility separation is non-positive or its CI includes zero; human review is required.",
            )
        )

    return tuple(sorted(suggestions, key=lambda item: (item["scope"], item["target"], item["reason_code"])))
