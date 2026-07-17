import math

import pytest

from app.opportunity.calibration import NumericObservation, economic_metrics


def numeric(project_id, low, base, high, actual):
    return NumericObservation(project_id, low, base, high, actual)


def test_economic_metrics_match_hand_calculated_errors_and_intervals():
    metrics = economic_metrics(
        (
            numeric("project-a", 10, 20, 30, 25),
            numeric("project-b", 0, 10, 20, -5),
        ),
        view="cohort_weighted",
    )

    assert metrics["sample_count"] == 2
    assert metrics["project_count"] == 2
    assert metrics["mae"] == pytest.approx(10)
    assert metrics["mean_signed_error"] == pytest.approx(-5)
    assert metrics["median_signed_error"] == pytest.approx(-15)
    assert metrics["rmse"] == pytest.approx(math.sqrt((25 + 225) / 2))
    assert metrics["interval_coverage"] == pytest.approx(0.5)
    assert metrics["mean_interval_width"] == pytest.approx(20)
    assert metrics["mean_actual"] == pytest.approx(10)
    assert metrics["median_actual"] == pytest.approx(-5)
    assert metrics["downside_rate"] == pytest.approx(0.5)
    assert metrics["positive_rate"] == pytest.approx(0.5)


def test_economic_interval_coverage_includes_both_boundaries():
    metrics = economic_metrics(
        (
            numeric("project-a", 10, 20, 30, 10),
            numeric("project-b", 0, 10, 20, 20),
        ),
        view="cohort_weighted",
    )

    assert metrics["interval_coverage"] == 1.0


def test_economic_metrics_use_weights_without_expanding_samples():
    observations = (
        numeric("project-a", 0, 0, 20, 10),
        numeric("project-a", 0, 0, 20, 10),
        numeric("project-b", -20, 0, 0, -10),
    )

    metrics = economic_metrics(observations, view="project_equal")

    assert metrics["sample_count"] == 3
    assert metrics["project_count"] == 2
    assert metrics["mean_actual"] == pytest.approx(0)
    assert metrics["median_actual"] == pytest.approx(-10)
    assert metrics["mae"] == pytest.approx(10)


def test_empty_economic_metrics_return_counts_and_null_values():
    metrics = economic_metrics((), view="project_equal")

    assert metrics["sample_count"] == 0
    assert metrics["project_count"] == 0
    assert all(value is None for name, value in metrics.items() if name not in {"sample_count", "project_count"})


@pytest.mark.parametrize("field", ("low", "base", "high", "actual"))
@pytest.mark.parametrize("value", (float("nan"), float("inf"), float("-inf")))
def test_numeric_observation_rejects_non_finite_inputs(field, value):
    values = {"low": 0.0, "base": 1.0, "high": 2.0, "actual": 1.0}
    values[field] = value

    with pytest.raises(ValueError, match="finite"):
        numeric("project-a", **values)


def test_numeric_observation_requires_ordered_prediction_range():
    with pytest.raises(ValueError, match="low <= base <= high"):
        numeric("project-a", 2, 1, 3, 1)
