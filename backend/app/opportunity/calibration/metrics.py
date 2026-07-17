from collections import Counter
from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Any

from .models import BinaryObservation, CalibrationSample
from .outcomes import map_outcomes

_PROBABILITY_DIMENSIONS = (
    ("event", "event_probability"),
    ("eligibility", "eligibility_probability"),
    ("survival", "survival_probability"),
    ("reward", "reward_probability"),
)


def _weighted_mean(values: Sequence[float], weights: Sequence[float]) -> float:
    return sum(value * weight for value, weight in zip(values, weights, strict=True)) / sum(weights)


def sample_weights(
    observations: Sequence[BinaryObservation],
    view: str,
) -> tuple[float, ...]:
    if view == "cohort_weighted":
        return tuple(1.0 for _ in observations)
    if view == "project_equal":
        project_counts = Counter(observation.project_id for observation in observations)
        return tuple(1 / project_counts[observation.project_id] for observation in observations)
    raise ValueError(f"unsupported view: {view}")


def build_probability_observations(
    samples: Sequence[CalibrationSample],
) -> Mapping[str, tuple[BinaryObservation, ...]]:
    observations: dict[str, list[BinaryObservation]] = {dimension: [] for dimension, _ in _PROBABILITY_DIMENSIONS}
    for sample in samples:
        outcomes, _ = map_outcomes(sample)
        for dimension, prediction_field in _PROBABILITY_DIMENSIONS:
            prediction = getattr(sample, prediction_field, None)
            actual = getattr(outcomes, dimension)
            if prediction is not None and actual is not None:
                observations[dimension].append(
                    BinaryObservation(
                        project_id=sample.project_id,
                        predicted=prediction.base,
                        actual=actual,
                    )
                )
    return MappingProxyType({dimension: tuple(values) for dimension, values in observations.items()})


def probability_metrics(
    observations: Sequence[BinaryObservation],
    *,
    view: str,
    coverage_denominator: int,
) -> Mapping[str, Any]:
    coverage_count = len(observations)
    if coverage_denominator < 0 or coverage_denominator < coverage_count:
        raise ValueError("coverage_denominator must be non-negative and at least coverage_count")

    weights = sample_weights(observations, view)
    project_count = len({observation.project_id for observation in observations})
    reliability_bins: list[Mapping[str, Any]] = []
    for index in range(10):
        members = tuple(
            member_index
            for member_index, observation in enumerate(observations)
            if min(int(observation.predicted * 10), 9) == index
        )
        bin_weights = tuple(weights[member_index] for member_index in members)
        reliability_bins.append(
            MappingProxyType(
                {
                    "lower": index / 10,
                    "upper": (index + 1) / 10,
                    "sample_count": len(members),
                    "weight": sum(bin_weights),
                    "mean_prediction": (
                        None
                        if not members
                        else _weighted_mean(
                            tuple(observations[item].predicted for item in members),
                            bin_weights,
                        )
                    ),
                    "observed_rate": (
                        None
                        if not members
                        else _weighted_mean(
                            tuple(float(observations[item].actual) for item in members),
                            bin_weights,
                        )
                    ),
                }
            )
        )

    empty_scores = {
        "observed_rate": None,
        "mean_prediction": None,
        "brier": None,
        "climatology_brier": None,
        "skill": None,
        "bias": None,
        "ece": None,
        "sharpness": None,
    }
    if not observations:
        return MappingProxyType(
            {
                "sample_count": 0,
                "project_count": 0,
                "coverage_count": coverage_count,
                "coverage_denominator": coverage_denominator,
                "coverage": None if coverage_denominator == 0 else 0.0,
                **empty_scores,
                "reliability_bins": tuple(reliability_bins),
            }
        )

    predictions = tuple(observation.predicted for observation in observations)
    actuals = tuple(float(observation.actual) for observation in observations)
    observed_rate = _weighted_mean(actuals, weights)
    mean_prediction = _weighted_mean(predictions, weights)
    brier = _weighted_mean(
        tuple((predicted - actual) ** 2 for predicted, actual in zip(predictions, actuals, strict=True)),
        weights,
    )
    climatology_brier = _weighted_mean(
        tuple((observed_rate - actual) ** 2 for actual in actuals),
        weights,
    )
    ece = sum(
        item["weight"] * abs(item["mean_prediction"] - item["observed_rate"])
        for item in reliability_bins
        if item["sample_count"]
    ) / sum(weights)

    return MappingProxyType(
        {
            "sample_count": len(observations),
            "project_count": project_count,
            "coverage_count": coverage_count,
            "coverage_denominator": coverage_denominator,
            "coverage": coverage_count / coverage_denominator,
            "observed_rate": observed_rate,
            "mean_prediction": mean_prediction,
            "brier": brier,
            "climatology_brier": climatology_brier,
            "skill": None if climatology_brier == 0 else 1 - brier / climatology_brier,
            "bias": observed_rate - mean_prediction,
            "ece": ece,
            "sharpness": _weighted_mean(
                tuple((predicted - mean_prediction) ** 2 for predicted in predictions),
                weights,
            ),
            "reliability_bins": tuple(reliability_bins),
        }
    )
