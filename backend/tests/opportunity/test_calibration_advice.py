from dataclasses import replace

import pytest

from app.opportunity.calibration import (
    build_suggestions,
    cluster_bootstrap_interval,
    gate_state,
    segment_key,
)
from tests.opportunity.test_calibration_outcomes import sample


def test_cluster_bootstrap_is_deterministic_and_keeps_project_cohorts_together():
    records = (
        {"project_id": "b", "value": 10},
        {"project_id": "a", "value": 1},
        {"project_id": "b", "value": 20},
        {"project_id": "c", "value": 100},
        {"project_id": "a", "value": 2},
    )
    seen_cluster_sizes = []

    def statistic(resample):
        counts = {project: sum(row["project_id"] == project for row in resample) for project in "abc"}
        seen_cluster_sizes.append(counts)
        assert counts["a"] % 2 == 0
        assert counts["b"] % 2 == 0
        return sum(row["value"] for row in resample) / len(resample)

    first = cluster_bootstrap_interval(records, statistic, seed=20260717, replicates=100)
    second = cluster_bootstrap_interval(records, statistic, seed=20260717, replicates=100)

    assert first == second
    assert first == pytest.approx((6.0, 57.5))
    assert seen_cluster_sizes


def test_cluster_bootstrap_defaults_to_one_thousand_replicates():
    calls = 0

    def statistic(records):
        nonlocal calls
        calls += 1
        return float(len(records))

    cluster_bootstrap_interval(
        ({"project_id": "a"}, {"project_id": "b"}),
        statistic,
        seed=20260717,
    )

    assert calls == 1000


def test_cluster_bootstrap_requires_two_projects():
    assert cluster_bootstrap_interval(({"project_id": "a"}, {"project_id": "a"}), len, seed=1) is None


@pytest.mark.parametrize(
    ("sample_count", "project_count", "expected"),
    (
        (29, 30, "data_quality_only"),
        (30, 30, "descriptive"),
        (99, 30, "descriptive"),
        (100, 29, "descriptive"),
        (100, 30, "advisory"),
    ),
)
def test_overall_gate_boundaries(sample_count, project_count, expected):
    assert gate_state(sample_count, project_count) == expected


@pytest.mark.parametrize(
    ("sample_count", "project_count", "expected"),
    ((29, 10, "data_quality_only"), (30, 9, "descriptive"), (30, 10, "advisory")),
)
def test_segment_gate_boundaries(sample_count, project_count, expected):
    assert gate_state(sample_count, project_count, segmented=True) == expected


@pytest.mark.parametrize("wallet_count, expected", ((1, "1-2"), (2, "1-2"), (3, "3-10"), (10, "3-10"), (11, "11+")))
def test_wallet_segments_are_fixed(wallet_count, expected):
    assert segment_key(replace(sample(), wallet_count=wallet_count), "wallet") == expected


@pytest.mark.parametrize("status", ("ACTIONABLE", "MONITOR", "INSUFFICIENT_EVIDENCE", "NOT_FIT", "BLOCKED"))
def test_status_segments_are_fixed(status):
    assert segment_key(replace(sample(), status=status), "status") == status


@pytest.mark.parametrize("label", ("FARM", "WATCH", "IGNORE"))
def test_label_segments_are_fixed(label):
    assert segment_key(replace(sample(), public_label=label), "label") == label


@pytest.mark.parametrize(
    ("sample_value", "segment_type"),
    (
        (replace(sample(), status="custom"), "status"),
        (replace(sample(), public_label="custom"), "label"),
        (sample(), "project_id"),
    ),
)
def test_unknown_or_identifier_segments_are_excluded(sample_value, segment_type):
    assert segment_key(sample_value, segment_type) is None


def advisory_report(gate="advisory"):
    evidence = {
        "probability": {
            "event": {"observed_gap": 0.12, "ci95": (0.03, 0.2), "sample_count": 120, "project_count": 40},
            "reward": {"observed_gap": 0.04, "ci95": (-0.01, 0.1), "sample_count": 115, "project_count": 39},
        },
        "economic": {
            "net_reward": {"observed_gap": -18.0, "ci95": (-30.0, -4.0), "sample_count": 110, "project_count": 35}
        },
        "decision": {
            "farm_minus_watch": {"observed_gap": 2.0, "ci95": (-3.0, 8.0), "sample_count": 105, "project_count": 34}
        },
    }
    return {
        "gate": gate,
        "scope": "overall",
        "window": "90d",
        "model_version": "opportunity-v2.0",
        "profile_version": "low-cost-curated-multiwallet-v1",
        "project_equal": evidence,
        "cohort_weighted": {
            "probability": {
                "event": {"observed_gap": -0.9, "ci95": (-1.0, -0.8), "sample_count": 999, "project_count": 40}
            }
        },
    }


def test_suggestions_use_only_project_equal_significant_evidence_and_are_sorted():
    suggestions = build_suggestions(advisory_report())

    assert [(item["target"], item["direction"]) for item in suggestions] == [
        ("decision_threshold_family:FARM-WATCH", "review"),
        ("economic:net_reward", "decrease"),
        ("probability:event", "increase"),
    ]
    assert all(item["auto_apply"] is False for item in suggestions)
    assert all(
        set(item)
        == {
            "scope",
            "target",
            "direction",
            "observed_gap",
            "ci95",
            "sample_count",
            "project_count",
            "window",
            "model_version",
            "profile_version",
            "reason_code",
            "explanation",
            "evidence",
            "evidence_view",
            "auto_apply",
        }
        for item in suggestions
    )
    assert {item["reason_code"] for item in suggestions} == {
        "DECISION_SEPARATION_UNCERTAIN",
        "ECONOMIC_SIGNED_ERROR_NEGATIVE",
        "PROBABILITY_BIAS_POSITIVE",
    }
    assert all(item["evidence_view"] == "project_equal" for item in suggestions)
    assert all(item["evidence"]["view"] == "project_equal" for item in suggestions)
    decision = suggestions[0]
    assert not any("replacement" in key or "threshold_value" in key for key in decision)


@pytest.mark.parametrize("gate", ("descriptive", "data_quality_only"))
def test_non_advisory_reports_never_produce_suggestions(gate):
    assert build_suggestions(advisory_report(gate)) == ()


def test_segment_suggestions_require_the_segment_advisory_gate():
    report = advisory_report()
    report["scope"] = "segment:wallet:1-2"
    report["gate"] = "descriptive"
    assert build_suggestions(report) == ()


def test_each_suggestion_must_pass_its_own_project_equal_gate():
    report = advisory_report()
    report["project_equal"]["probability"]["event"]["sample_count"] = 99

    assert all(item["target"] != "probability:event" for item in build_suggestions(report))
