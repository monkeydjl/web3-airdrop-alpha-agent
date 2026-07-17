from dataclasses import replace

import pytest

from app.opportunity.calibration import decision_metrics, map_outcomes
from tests.opportunity.test_calibration_outcomes import sample

LABELS = ("FARM", "WATCH", "IGNORE")
CLASSES = ("POSITIVE", "NEUTRAL", "NEGATIVE")


def economic_sample(label, realized_class, project_id):
    economics = {
        "POSITIVE": {"reward_received_usd": 16.0, "actual_hard_cost_usd": 5.0, "claim_cost_usd": 1.0},
        "NEUTRAL": {"reward_received_usd": 6.0, "actual_hard_cost_usd": 5.0, "claim_cost_usd": 1.0},
        "NEGATIVE": {"reward_received_usd": 1.0, "actual_hard_cost_usd": 5.0, "claim_cost_usd": 1.0},
    }
    return sample(public_label=label, project_id=project_id, **economics[realized_class])


def test_decision_metrics_emit_fixed_full_matrix_and_farm_ignore_scores():
    samples = tuple(
        economic_sample(label, realized_class, f"{label}-{realized_class}")
        for label in LABELS
        for realized_class in CLASSES
    )
    outcomes = tuple(map_outcomes(item)[0] for item in samples)

    metrics = decision_metrics(samples, outcomes, view="cohort_weighted")

    assert tuple(metrics["confusion_matrix"]) == LABELS
    assert all(tuple(metrics["confusion_matrix"][label]) == CLASSES for label in LABELS)
    assert all(
        metrics["confusion_matrix"][label][realized_class] == 1.0 for label in LABELS for realized_class in CLASSES
    )
    assert metrics["farm_precision"] == pytest.approx(1 / 3)
    assert metrics["farm_recall"] == pytest.approx(1 / 3)
    assert metrics["ignore_precision"] == pytest.approx(1 / 3)
    assert metrics["ignore_recall"] == pytest.approx(1 / 3)
    assert "accuracy" not in metrics


def test_decision_metrics_report_utility_rates_and_adjacent_separation():
    samples = (
        economic_sample("FARM", "POSITIVE", "farm"),
        economic_sample("WATCH", "NEUTRAL", "watch"),
        economic_sample("IGNORE", "NEGATIVE", "ignore"),
    )
    outcomes = tuple(map_outcomes(item)[0] for item in samples)

    metrics = decision_metrics(samples, outcomes, view="cohort_weighted")

    assert metrics["utility_by_label"]["FARM"] == {"mean_net": 10.0, "median_net": 10.0}
    assert metrics["utility_by_label"]["WATCH"] == {"mean_net": 0.0, "median_net": 0.0}
    assert metrics["utility_by_label"]["IGNORE"] == {"mean_net": -5.0, "median_net": -5.0}
    assert metrics["rates_by_label"]["FARM"]["positive_rate"] == 1.0
    assert metrics["rates_by_label"]["WATCH"]["neutral_rate"] == 1.0
    assert metrics["rates_by_label"]["IGNORE"]["negative_rate"] == 1.0
    assert metrics["rates_by_label"]["IGNORE"]["downside_rate"] == 1.0
    assert metrics["adjacent_utility_separation"] == {"farm_minus_watch": 10.0, "watch_minus_ignore": 5.0}


def test_decision_metrics_report_eligibility_and_survival_failure_rates():
    ineligible = replace(
        economic_sample("FARM", "NEGATIVE", "ineligible"),
        eligibility_result="ineligible",
        reward_received_usd=0.0,
    )
    disqualified = replace(
        economic_sample("FARM", "NEGATIVE", "disqualified"),
        survival_result="disqualified",
        reward_received_usd=0.0,
    )
    samples = (ineligible, disqualified)

    metrics = decision_metrics(samples, tuple(map_outcomes(item)[0] for item in samples), view="cohort_weighted")

    assert metrics["rates_by_label"]["FARM"]["ineligible_rate"] == pytest.approx(0.5)
    assert metrics["rates_by_label"]["FARM"]["disqualified_rate"] == pytest.approx(0.5)


def test_decision_metrics_exclude_incomplete_and_contradictory_economics():
    valid = economic_sample("FARM", "POSITIVE", "valid")
    incomplete = replace(valid, project_id="incomplete", claim_cost_usd=None)
    contradictory = replace(valid, project_id="contradictory", eligibility_result="ineligible")
    samples = (valid, incomplete, contradictory)
    outcomes = tuple(map_outcomes(item)[0] for item in samples)

    metrics = decision_metrics(samples, outcomes, view="cohort_weighted")

    assert metrics["sample_count"] == 1
    assert metrics["project_count"] == 1
    assert metrics["confusion_matrix"]["FARM"]["POSITIVE"] == 1.0


def test_decision_metrics_rederive_outcomes_before_admitting_samples():
    incomplete = replace(economic_sample("FARM", "POSITIVE", "incomplete"), claim_cost_usd=None)
    contradictory = replace(
        economic_sample("FARM", "POSITIVE", "contradictory"),
        eligibility_result="ineligible",
    )
    forged_complete = map_outcomes(economic_sample("FARM", "POSITIVE", "forged"))[0]

    metrics = decision_metrics(
        (incomplete, contradictory),
        (forged_complete, forged_complete),
        view="cohort_weighted",
    )

    assert metrics["sample_count"] == 0


def test_missing_decision_denominators_are_null_not_zero_and_watch_is_not_judged():
    metrics = decision_metrics((), (), view="project_equal")

    assert metrics["farm_precision"] is None
    assert metrics["farm_recall"] is None
    assert metrics["ignore_precision"] is None
    assert metrics["ignore_recall"] is None
    assert metrics["utility_by_label"]["WATCH"] == {"mean_net": None, "median_net": None}
    assert all(value is None for value in metrics["rates_by_label"]["WATCH"].values())
    assert metrics["adjacent_utility_separation"] == {"farm_minus_watch": None, "watch_minus_ignore": None}
    assert "watch_precision" not in metrics
    assert "watch_recall" not in metrics
    assert "accuracy" not in metrics


def test_decision_metrics_use_project_equal_weights():
    samples = (
        economic_sample("FARM", "POSITIVE", "project-a"),
        economic_sample("FARM", "POSITIVE", "project-a"),
        economic_sample("FARM", "NEGATIVE", "project-b"),
    )
    outcomes = tuple(map_outcomes(item)[0] for item in samples)

    metrics = decision_metrics(samples, outcomes, view="project_equal")

    assert metrics["farm_precision"] == pytest.approx(0.5)
    assert metrics["rates_by_label"]["FARM"]["positive_rate"] == pytest.approx(0.5)
    assert metrics["utility_by_label"]["FARM"]["mean_net"] == pytest.approx(2.5)


def test_decision_metrics_reject_mismatched_sequences_and_unknown_views():
    with pytest.raises(ValueError, match="equal lengths"):
        decision_metrics((economic_sample("FARM", "POSITIVE", "project-a"),), (), view="cohort_weighted")

    with pytest.raises(ValueError, match="unsupported view"):
        decision_metrics((), (), view="unknown")
