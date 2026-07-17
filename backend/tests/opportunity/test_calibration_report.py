import hashlib
import json
import math
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.opportunity.calibration import (
    CalibrationDataset,
    build_calibration_report,
    canonical_report_json,
    render_markdown,
    write_report_pair,
)
from app.opportunity.calibration import report as report_module
from tests.opportunity.test_calibration_outcomes import sample

AS_OF = datetime(2026, 7, 18, tzinfo=UTC)


def aged_sample(days: int, number: int, **updates):
    observed_at = AS_OF - timedelta(days=number)
    values = {
        "project_id": f"private-project-{number}",
        "assessment_id": f"private-assessment-{number}",
        "cohort_id": f"private-cohort-{number}",
        "scored_at": observed_at - timedelta(days=days),
        "outcome_observed_at": observed_at,
    }
    values.update(updates)
    return replace(sample(), **values)


def dataset(samples):
    return CalibrationDataset(
        samples=tuple(samples),
        quality={"missing_linkage": 2, "duplicate_pair": 1},
        backend="sqlite",
    )


def walk(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from walk(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from walk(child)
    else:
        yield value


def test_builds_nested_windows_views_fixed_segments_and_quality_counts():
    samples = (
        aged_sample(89, 1),
        aged_sample(90, 2, eligibility_result=None),
        aged_sample(179, 3, survival_result=None),
        aged_sample(180, 4, outcome=None, reward_received_usd=None),
    )

    report = build_calibration_report(dataset(samples), as_of=AS_OF)

    assert report["metadata"] == {
        "schema": "opportunity-calibration-v1",
        "model_version": "opportunity-v2.0",
        "profile_version": "low-cost-curated-multiwallet-v1",
        "as_of": "2026-07-18T00:00:00Z",
        "windows": [90, 180],
        "bootstrap_seed": 20260717,
        "bootstrap_replicates": 1000,
        "database_backend": "sqlite",
        "report_id": report["metadata"]["report_id"],
    }
    assert set(report["windows"]) == {"90d", "180d"}
    assert report["windows"]["90d"]["mature_sample_count"] == 3
    assert report["windows"]["180d"]["mature_sample_count"] == 1
    assert report["data_quality"]["maturity"]["90d"] == {
        "mature": 3,
        "immature": 1,
        "outcome_before_assessment": 0,
        "outcome_after_as_of": 0,
    }
    assert report["data_quality"]["maturity"]["180d"] == {
        "mature": 1,
        "immature": 3,
        "outcome_before_assessment": 0,
        "outcome_after_as_of": 0,
    }
    assert report["data_quality"]["loader"]["duplicate_pair"] == 1
    assert report["data_quality"]["loader"]["missing_linkage"] == 2
    assert report["data_quality"]["loader"]["invalid_timestamp"] == 0

    ninety = report["windows"]["90d"]
    assert all(view in ninety for view in ("cohort_weighted", "project_equal"))
    assert set(ninety["segments"]) == {
        "label:FARM",
        "label:WATCH",
        "label:IGNORE",
        "status:ACTIONABLE",
        "status:MONITOR",
        "status:INSUFFICIENT_EVIDENCE",
        "status:NOT_FIT",
        "status:BLOCKED",
        "wallet:1-2",
        "wallet:3-10",
        "wallet:11+",
    }
    assert ninety["gate"] == "data_quality_only"
    assert ninety["suggestions"] == []
    assert ninety["quality"]["resolved"]["eligibility"] == 2
    assert ninety["quality"]["unresolved"]["eligibility"] == 1
    assert ninety["quality"]["resolved"]["survival"] == 2
    assert ninety["quality"]["unresolved"]["survival"] == 1


def test_integration_probability_coverage_denominator_is_all_mature_linked_samples():
    samples = (
        aged_sample(90, 1),
        aged_sample(90, 2, eligibility_result=None),
        aged_sample(90, 3, eligibility_result=None, survival_result=None),
    )

    report = build_calibration_report(dataset(samples), as_of=AS_OF)

    for view in ("cohort_weighted", "project_equal"):
        probability = report["windows"]["90d"][view]["probability"]
        assert probability["event"]["coverage_denominator"] == 3
        assert probability["eligibility"]["coverage_denominator"] == 3
        assert probability["eligibility"]["coverage_count"] == 1
        assert probability["survival"]["coverage_denominator"] == 3
        assert probability["survival"]["coverage_count"] == 2
        assert probability["reward"]["coverage_denominator"] == 3

        segment_probability = report["windows"]["90d"]["segments"]["label:FARM"][view]["probability"]
        assert segment_probability["reward"]["coverage_denominator"] == 3


def test_rejects_duplicate_report_identity_keys_regardless_of_input_order():
    first = aged_sample(180, 1)
    duplicate = replace(first, reward_received_usd=999)

    for samples in ((first, duplicate), (duplicate, first)):
        with pytest.raises(ValueError, match="duplicate calibration sample identity"):
            build_calibration_report(dataset(samples), as_of=AS_OF)


def test_report_id_hashes_canonical_report_without_report_id():
    report = build_calibration_report(dataset((aged_sample(180, 1),)), as_of=AS_OF)
    unhashed = json.loads(json.dumps(report))
    report_id = unhashed["metadata"].pop("report_id")

    canonical = (
        json.dumps(unhashed, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()
    expected = hashlib.sha256(canonical).hexdigest()

    assert report_id == expected
    assert canonical_report_json(report).endswith(b"\n")


def test_report_json_and_markdown_are_order_independent_private_and_finite():
    sensitive = (
        "project-secret-123",
        "assessment-secret-456",
        "cohort-secret-789",
        "user-secret-abc",
        "https://private.example/alpha",
        "operator private note",
        "private disqualification reason",
    )
    samples = (
        aged_sample(180, 1, project_id=sensitive[0], assessment_id=sensitive[1], cohort_id=sensitive[2]),
        aged_sample(180, 2, public_label="WATCH", status="MONITOR", wallet_count=1),
    )

    first = build_calibration_report(dataset(samples), as_of=AS_OF)
    second = build_calibration_report(dataset(reversed(samples)), as_of=AS_OF)
    first_json = canonical_report_json(first)

    assert first_json == canonical_report_json(second)
    assert render_markdown(first) == render_markdown(second)
    assert first_json.endswith(b"\n")
    assert b"NaN" not in first_json and b"Infinity" not in first_json
    assert json.loads(first_json)["metadata"]["report_id"] == first["metadata"]["report_id"]
    serialized_values = tuple(str(value) for value in walk(first))
    assert all(secret not in value for secret in sensitive for value in serialized_values)
    assert all(not isinstance(value, float) or math.isfinite(value) for value in walk(first))


def test_write_report_pair_publishes_matching_files(tmp_path):
    report = build_calibration_report(dataset((aged_sample(180, 1),)), as_of=AS_OF)

    json_path, markdown_path = write_report_pair(report, tmp_path)

    report_id = report["metadata"]["report_id"]
    assert json_path.name == f"opportunity-calibration-{report_id}.json"
    assert markdown_path.name == f"opportunity-calibration-{report_id}.md"
    assert json_path.read_bytes() == canonical_report_json(report)
    assert markdown_path.read_text(encoding="utf-8") == render_markdown(report)
    assert sorted(path.name for path in tmp_path.iterdir()) == sorted((json_path.name, markdown_path.name))


def test_write_report_pair_render_failure_leaves_no_files(tmp_path, monkeypatch):
    report = build_calibration_report(dataset((aged_sample(180, 1),)), as_of=AS_OF)

    def fail_render(_report):
        raise RuntimeError("render failed")

    monkeypatch.setattr("app.opportunity.calibration.report.render_markdown", fail_render)

    with pytest.raises(RuntimeError, match="render failed"):
        write_report_pair(report, tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_write_report_pair_second_replace_failure_restores_existing_pair(tmp_path, monkeypatch):
    report = build_calibration_report(dataset((aged_sample(180, 1),)), as_of=AS_OF)
    report_id = report["metadata"]["report_id"]
    json_path = tmp_path / f"opportunity-calibration-{report_id}.json"
    markdown_path = tmp_path / f"opportunity-calibration-{report_id}.md"
    json_path.write_bytes(b"old-json")
    markdown_path.write_text("old-markdown", encoding="utf-8")
    original_replace = Path.replace
    final_replaces = 0

    def fail_second_final_replace(source, target):
        nonlocal final_replaces
        if Path(target) in (json_path, markdown_path) and ".tmp" in source.name:
            final_replaces += 1
            if final_replaces == 2:
                raise OSError("second replace failed")
        return original_replace(source, target)

    monkeypatch.setattr(Path, "replace", fail_second_final_replace)

    with pytest.raises(OSError, match="second replace failed"):
        write_report_pair(report, tmp_path)
    assert json_path.read_bytes() == b"old-json"
    assert markdown_path.read_text(encoding="utf-8") == "old-markdown"
    assert sorted(path.name for path in tmp_path.iterdir()) == sorted((json_path.name, markdown_path.name))


def test_write_report_pair_second_replace_failure_removes_new_pair(tmp_path, monkeypatch):
    report = build_calibration_report(dataset((aged_sample(180, 1),)), as_of=AS_OF)
    original_replace = Path.replace
    calls = 0

    def fail_second_publish(source, target):
        nonlocal calls
        if ".tmp" in source.name and ".backup.tmp" not in source.name:
            calls += 1
            if calls == 2:
                raise OSError("second publish failed")
        return original_replace(source, target)

    monkeypatch.setattr(Path, "replace", fail_second_publish)

    with pytest.raises(OSError, match="second publish failed"):
        write_report_pair(report, tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_failed_restore_retains_old_backup_and_removes_new_final(tmp_path, monkeypatch):
    report = build_calibration_report(dataset((aged_sample(180, 1),)), as_of=AS_OF)
    report_id = report["metadata"]["report_id"]
    json_path = tmp_path / f"opportunity-calibration-{report_id}.json"
    markdown_path = tmp_path / f"opportunity-calibration-{report_id}.md"
    json_path.write_bytes(b"old-json")
    markdown_path.write_bytes(b"old-markdown")
    original_replace = Path.replace
    publishes = 0

    def fail_publish_and_restore(source, target):
        nonlocal publishes
        if ".backup.tmp" in source.name and Path(target) == json_path:
            raise OSError("restore failed")
        if ".tmp" in source.name and ".backup.tmp" not in source.name:
            publishes += 1
            if publishes == 2:
                raise OSError("publish failed")
        return original_replace(source, target)

    monkeypatch.setattr(Path, "replace", fail_publish_and_restore)

    with pytest.raises(RuntimeError, match="rollback failed") as failure:
        write_report_pair(report, tmp_path)
    assert len(str(failure.value)) < 512
    assert not json_path.exists()
    assert markdown_path.read_bytes() == b"old-markdown"
    backups = tuple(tmp_path.glob("*.backup.tmp"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == b"old-json"


def test_project_equal_probability_bootstrap_uses_project_summaries(monkeypatch):
    records = (
        report_module.BinaryObservation("large", 0.0, 1),
        report_module.BinaryObservation("large", 0.0, 0),
        report_module.BinaryObservation("small", 0.0, 1),
    )
    monkeypatch.setattr(report_module, "BOOTSTRAP_REPLICATES", 20)

    evidence = report_module._probability_evidence(records, "project_equal", 3, 7, segmented=False)

    assert evidence["observed_gap"] == pytest.approx(0.75)
    assert evidence["ci95"] == pytest.approx((0.5, 1.0))


def test_project_equal_economic_bootstrap_preserves_project_draw_multiplicity(monkeypatch):
    records = (
        report_module.NumericObservation("large", 0.0, 0.0, 0.0, 0.0),
        report_module.NumericObservation("large", 0.0, 0.0, 0.0, 0.0),
        report_module.NumericObservation("small", 0.0, 0.0, 0.0, 9.0),
    )

    def duplicate_first_draw(projects, statistic, **_options):
        assert tuple(record.project_id for record in projects) == ("large", "small")
        value = statistic((projects[0], projects[0], projects[1]))
        return value, value

    monkeypatch.setattr(report_module, "cluster_bootstrap_interval", duplicate_first_draw)

    evidence = report_module._economic_evidence(records, "project_equal", 7, segmented=False)

    assert evidence["observed_gap"] == pytest.approx(4.5)
    assert evidence["ci95"] == pytest.approx((3.0, 3.0))


def test_adjacent_ci_is_stratified_by_label_without_shared_projects(monkeypatch):
    samples = (
        aged_sample(180, 1, project_id="farm-a", public_label="FARM", reward_received_usd=12),
        aged_sample(180, 2, project_id="farm-b", public_label="FARM", reward_received_usd=10),
        aged_sample(180, 3, project_id="watch-a", public_label="WATCH", reward_received_usd=5),
        aged_sample(180, 4, project_id="watch-b", public_label="WATCH", reward_received_usd=3),
    )
    mapped = tuple(report_module.map_sample(item) for item in samples)
    monkeypatch.setattr(report_module, "BOOTSTRAP_REPLICATES", 20)

    decision = report_module._decision_view(mapped, view="project_equal", seed=11, segmented=False)
    separation = decision["adjacent_utility_separation"]["farm_minus_watch"]

    assert separation["ci95"] is not None
    assert separation["sample_count"] == 4
    assert separation["project_count"] == 4


def test_decision_dimensions_have_their_own_counts_and_gates(monkeypatch):
    samples = tuple(
        aged_sample(
            180,
            number,
            project_id=f"p-{number}",
            public_label="FARM" if number <= 30 else "WATCH",
        )
        for number in range(1, 33)
    )
    mapped = tuple(report_module.map_sample(item) for item in samples)
    monkeypatch.setattr(report_module, "BOOTSTRAP_REPLICATES", 10)

    decision = report_module._decision_view(mapped, view="project_equal", seed=3, segmented=False)

    assert decision["utility_by_label"]["FARM"]["sample_count"] == 30
    assert decision["utility_by_label"]["WATCH"]["sample_count"] == 2
    assert decision["utility_by_label"]["WATCH"]["gate"] == "data_quality_only"
    adjacent = decision["adjacent_utility_separation"]["farm_minus_watch"]
    assert adjacent["sample_count"] == 32
    assert adjacent["project_count"] == 32


def test_project_equal_decision_median_uses_project_label_means(monkeypatch):
    samples = (
        aged_sample(180, 1, project_id="large", public_label="FARM", reward_received_usd=6),
        aged_sample(180, 2, project_id="large", public_label="FARM", reward_received_usd=6),
        aged_sample(180, 3, project_id="large", public_label="FARM", reward_received_usd=18),
        aged_sample(180, 4, project_id="small", public_label="FARM", reward_received_usd=16),
    )
    monkeypatch.setattr(report_module, "BOOTSTRAP_REPLICATES", 10)

    first = report_module._decision_view(
        tuple(report_module.map_sample(item) for item in samples), view="project_equal", seed=3, segmented=False
    )
    second = report_module._decision_view(
        tuple(report_module.map_sample(item) for item in reversed(samples)),
        view="project_equal",
        seed=3,
        segmented=False,
    )

    assert first["utility_by_label"]["FARM"]["median_net"] == pytest.approx(7.0)
    assert second["utility_by_label"]["FARM"]["median_net"] == pytest.approx(7.0)


def test_quality_predicates_keep_cost_and_time_when_reward_is_contradictory():
    contradictory = aged_sample(
        180,
        1,
        outcome="not_airdropped",
        reward_received_usd=10,
        actual_hard_cost_usd=2,
        actual_time_minutes=120,
    )

    report = build_calibration_report(dataset((contradictory,)), as_of=AS_OF)
    quality = report["windows"]["180d"]["quality"]

    assert quality["resolved"]["reward"] == 0
    assert quality["resolved"]["net_reward"] == 0
    assert quality["resolved"]["hard_cost"] == 1
    assert quality["resolved"]["total_time"] == 1


def test_report_maps_each_mature_sample_once_per_window(monkeypatch):
    calls = 0
    original = report_module.map_sample

    def counting_map(sample):
        nonlocal calls
        calls += 1
        return original(sample)

    monkeypatch.setattr(report_module, "map_sample", counting_map)

    build_calibration_report(dataset((aged_sample(180, 1), aged_sample(180, 2))), as_of=AS_OF)

    assert calls == 4
