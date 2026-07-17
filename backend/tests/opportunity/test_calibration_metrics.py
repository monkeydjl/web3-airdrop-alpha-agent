from dataclasses import replace
from types import MappingProxyType

import pytest

from app.opportunity.calibration import (
    BinaryObservation,
    probability_metrics,
    sample_weights,
)
from tests.opportunity.test_calibration_outcomes import sample


def observation(predicted, actual, project_id="project-1"):
    return BinaryObservation(project_id=project_id, predicted=predicted, actual=actual)


def test_probability_metrics_match_hand_calculated_scores():
    observations = tuple(
        observation(predicted, actual) for predicted, actual in ((0.1, 0), (0.7, 1), (0.8, 1), (0.4, 0))
    )

    metrics = probability_metrics(observations, view="cohort_weighted")

    assert metrics["sample_count"] == 4
    assert metrics["project_count"] == 1
    assert metrics["observed_rate"] == pytest.approx(0.5)
    assert metrics["mean_prediction"] == pytest.approx(0.5)
    assert metrics["brier"] == pytest.approx((0.01 + 0.09 + 0.04 + 0.16) / 4)
    assert metrics["climatology_brier"] == pytest.approx(0.25)
    assert metrics["skill"] == pytest.approx(0.7)
    assert metrics["bias"] == pytest.approx(0.0)
    assert metrics["ece"] == pytest.approx(0.25)
    assert metrics["sharpness"] == pytest.approx(0.075)


def test_probability_metrics_use_fixed_ten_bins_with_explicit_boundaries():
    metrics = probability_metrics(
        (observation(0.0, 0), observation(0.1, 1), observation(1.0, 1)),
        view="cohort_weighted",
    )

    bins = metrics["reliability_bins"]
    assert len(bins) == 10
    assert [(item["lower"], item["upper"]) for item in bins] == [(index / 10, (index + 1) / 10) for index in range(10)]
    assert [item["sample_count"] for item in bins] == [1, 1, 0, 0, 0, 0, 0, 0, 0, 1]
    assert bins[0]["mean_prediction"] == 0.0
    assert bins[1]["mean_prediction"] == 0.1
    assert bins[-1]["mean_prediction"] == 1.0
    assert bins[2]["observed_rate"] is None


def test_probability_metrics_return_null_scores_for_empty_data():
    metrics = probability_metrics((), view="project_equal")

    assert metrics["sample_count"] == 0
    assert metrics["project_count"] == 0
    assert all(
        metrics[name] is None
        for name in (
            "observed_rate",
            "mean_prediction",
            "brier",
            "climatology_brier",
            "skill",
            "bias",
            "ece",
            "sharpness",
        )
    )
    assert len(metrics["reliability_bins"]) == 10
    assert all(item["sample_count"] == 0 for item in metrics["reliability_bins"])


def test_probability_metrics_return_null_skill_for_constant_outcomes():
    metrics = probability_metrics(
        (observation(0.2, 1), observation(0.8, 1)),
        view="cohort_weighted",
    )

    assert metrics["climatology_brier"] == 0.0
    assert metrics["skill"] is None


def test_sample_weights_equalize_projects_without_expanding_samples():
    observations = (
        *(observation(0.9, 1, "project-a") for _ in range(9)),
        observation(0.1, 0, "project-b"),
    )

    assert sample_weights(observations, "cohort_weighted") == (1.0,) * 10
    assert sample_weights(observations, "project_equal") == (1 / 9,) * 9 + (1.0,)
    assert sum(sample_weights(observations[:9], "project_equal")) == pytest.approx(1.0)
    assert sum(sample_weights(observations, "project_equal")[:9]) == pytest.approx(
        sum(sample_weights(observations, "project_equal")[9:])
    )


def test_project_equal_metrics_use_weights_for_scores_ece_and_sharpness():
    observations = (
        *(observation(0.9, 1, "project-a") for _ in range(9)),
        observation(0.2, 0, "project-b"),
    )

    metrics = probability_metrics(observations, view="project_equal")

    assert metrics["observed_rate"] == pytest.approx(0.5)
    assert metrics["mean_prediction"] == pytest.approx(0.55)
    assert metrics["brier"] == pytest.approx(0.025)
    assert metrics["climatology_brier"] == pytest.approx(0.25)
    assert metrics["skill"] == pytest.approx(0.9)
    assert metrics["bias"] == pytest.approx(0.05)
    assert metrics["ece"] == pytest.approx(0.15)
    assert metrics["sharpness"] == pytest.approx(0.1225)
    assert metrics["reliability_bins"][2]["weight"] == pytest.approx(1.0)
    assert metrics["reliability_bins"][9]["weight"] == pytest.approx(1.0)


def test_sample_weights_reject_unknown_view_even_when_empty():
    with pytest.raises(ValueError, match="unsupported view"):
        sample_weights((), "unknown")


def test_observation_builder_is_dimension_independent_and_immutable():
    from app.opportunity.calibration import build_probability_observations

    value = sample(eligibility_result=None, survival_result="disqualified")

    observations = build_probability_observations((value,))

    assert isinstance(observations, MappingProxyType)
    assert tuple(observations) == ("event", "eligibility", "survival", "reward")
    assert observations["event"] == (observation(0.7, 1),)
    assert observations["eligibility"] == ()
    assert observations["survival"] == (observation(0.8, 0),)
    assert observations["reward"] == ()


def test_observation_builder_uses_each_base_prediction():
    from app.opportunity.calibration import build_probability_observations

    value = replace(sample(), reward_received_usd=0.0)

    observations = build_probability_observations((value,))

    assert {name: values[0].predicted for name, values in observations.items()} == {
        "event": 0.7,
        "eligibility": 0.6,
        "survival": 0.8,
        "reward": 0.4,
    }
