import math
from collections import Counter
from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Any, cast

from .models import BinaryObservation, CalibrationSample, NumericObservation, OutcomeValues
from .outcomes import map_outcomes

_PROBABILITY_DIMENSIONS = (
    ("event", "event_probability"),
    ("eligibility", "eligibility_probability"),
    ("survival", "survival_probability"),
    ("reward", "reward_probability"),
)
_DECISION_LABELS = ("FARM", "WATCH", "IGNORE")
_REALIZED_CLASSES = ("POSITIVE", "NEUTRAL", "NEGATIVE")


def _weighted_mean(values: Sequence[float], weights: Sequence[float]) -> float:
    return sum(value * weight for value, weight in zip(values, weights, strict=True)) / sum(weights)


def _weighted_median(values: Sequence[float], weights: Sequence[float]) -> float:
    ordered = sorted(zip(values, weights, strict=True))
    midpoint = sum(weights) / 2
    cumulative = 0.0
    for value, weight in ordered:
        cumulative += weight
        if cumulative >= midpoint:
            return value
    raise ValueError("weighted median requires values")


def sample_weights(
    observations: Sequence[BinaryObservation] | Sequence[NumericObservation] | Sequence[CalibrationSample],
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
    if type(coverage_denominator) is not int or coverage_denominator < 0 or coverage_denominator < coverage_count:
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


def economic_metrics(
    observations: Sequence[NumericObservation],
    *,
    view: str,
) -> Mapping[str, Any]:
    weights = sample_weights(observations, view)
    empty_scores = {
        "mae": None,
        "mean_signed_error": None,
        "median_signed_error": None,
        "rmse": None,
        "interval_coverage": None,
        "mean_interval_width": None,
        "mean_actual": None,
        "median_actual": None,
        "downside_rate": None,
        "positive_rate": None,
    }
    if not observations:
        return MappingProxyType({"sample_count": 0, "project_count": 0, **empty_scores})

    actuals = tuple(observation.actual for observation in observations)
    signed_errors = tuple(observation.actual - observation.base for observation in observations)
    return MappingProxyType(
        {
            "sample_count": len(observations),
            "project_count": len({observation.project_id for observation in observations}),
            "mae": _weighted_mean(tuple(abs(error) for error in signed_errors), weights),
            "mean_signed_error": _weighted_mean(signed_errors, weights),
            "median_signed_error": _weighted_median(signed_errors, weights),
            "rmse": math.sqrt(_weighted_mean(tuple(error**2 for error in signed_errors), weights)),
            "interval_coverage": _weighted_mean(
                tuple(float(observation.low <= observation.actual <= observation.high) for observation in observations),
                weights,
            ),
            "mean_interval_width": _weighted_mean(
                tuple(observation.high - observation.low for observation in observations),
                weights,
            ),
            "mean_actual": _weighted_mean(actuals, weights),
            "median_actual": _weighted_median(actuals, weights),
            "downside_rate": _weighted_mean(tuple(float(actual < 0) for actual in actuals), weights),
            "positive_rate": _weighted_mean(tuple(float(actual > 0) for actual in actuals), weights),
        }
    )


def _safe_ratio(numerator: float, denominator: float) -> float | None:
    return None if denominator == 0 else numerator / denominator


def decision_metrics(
    samples: Sequence[CalibrationSample],
    outcomes: Sequence[OutcomeValues],
    *,
    view: str,
    mapped: bool = False,
) -> Mapping[str, Any]:
    if len(samples) != len(outcomes):
        raise ValueError("samples and outcomes must have equal lengths")

    eligible_records = []
    for sample, supplied_outcome in zip(samples, outcomes, strict=True):
        derived_outcome, concerns = (supplied_outcome, ()) if mapped else map_outcomes(sample)
        if (
            not concerns
            and supplied_outcome == derived_outcome
            and sample.public_label in _DECISION_LABELS
            and derived_outcome.realized_class in _REALIZED_CLASSES
            and derived_outcome.realized_net_usd is not None
        ):
            eligible_records.append((sample, derived_outcome))
    eligible = tuple(eligible_records)
    if any(not math.isfinite(cast(float, outcome.realized_net_usd)) for _, outcome in eligible):
        raise ValueError("realized net values must be finite")

    eligible_samples = tuple(sample for sample, _ in eligible)
    weights = sample_weights(eligible_samples, view)
    matrix = {label: {realized_class: 0.0 for realized_class in _REALIZED_CLASSES} for label in _DECISION_LABELS}
    for (sample, outcome), weight in zip(eligible, weights, strict=True):
        matrix[sample.public_label][cast(str, outcome.realized_class)] += weight

    label_weights = {label: sum(matrix[label].values()) for label in _DECISION_LABELS}
    class_weights = {
        realized_class: sum(matrix[label][realized_class] for label in _DECISION_LABELS)
        for realized_class in _REALIZED_CLASSES
    }
    utility: dict[str, Mapping[str, float | None]] = {}
    rates: dict[str, Mapping[str, float | None]] = {}
    for label in _DECISION_LABELS:
        members = tuple(index for index, (sample, _) in enumerate(eligible) if sample.public_label == label)
        member_weights = tuple(weights[index] for index in members)
        nets = tuple(cast(float, eligible[index][1].realized_net_usd) for index in members)
        denominator = sum(member_weights)
        utility[label] = MappingProxyType(
            {
                "mean_net": None if not members else _weighted_mean(nets, member_weights),
                "median_net": None if not members else _weighted_median(nets, member_weights),
            }
        )
        rates[label] = MappingProxyType(
            {
                "positive_rate": _safe_ratio(matrix[label]["POSITIVE"], denominator),
                "neutral_rate": _safe_ratio(matrix[label]["NEUTRAL"], denominator),
                "negative_rate": _safe_ratio(matrix[label]["NEGATIVE"], denominator),
                "ineligible_rate": _safe_ratio(
                    sum(weights[index] for index in members if eligible[index][0].eligibility_result == "ineligible"),
                    denominator,
                ),
                "disqualified_rate": _safe_ratio(
                    sum(weights[index] for index in members if eligible[index][0].survival_result == "disqualified"),
                    denominator,
                ),
                "downside_rate": _safe_ratio(
                    sum(weights[index] for index in members if cast(float, eligible[index][1].realized_net_usd) < 0),
                    denominator,
                ),
            }
        )

    farm_mean = utility["FARM"]["mean_net"]
    watch_mean = utility["WATCH"]["mean_net"]
    ignore_mean = utility["IGNORE"]["mean_net"]
    return MappingProxyType(
        {
            "sample_count": len(eligible),
            "project_count": len({sample.project_id for sample in eligible_samples}),
            "confusion_matrix": MappingProxyType(
                {label: MappingProxyType(matrix[label]) for label in _DECISION_LABELS}
            ),
            "farm_precision": _safe_ratio(matrix["FARM"]["POSITIVE"], label_weights["FARM"]),
            "farm_recall": _safe_ratio(matrix["FARM"]["POSITIVE"], class_weights["POSITIVE"]),
            "ignore_precision": _safe_ratio(matrix["IGNORE"]["NEGATIVE"], label_weights["IGNORE"]),
            "ignore_recall": _safe_ratio(matrix["IGNORE"]["NEGATIVE"], class_weights["NEGATIVE"]),
            "utility_by_label": MappingProxyType(utility),
            "rates_by_label": MappingProxyType(rates),
            "adjacent_utility_separation": MappingProxyType(
                {
                    "farm_minus_watch": None if farm_mean is None or watch_mean is None else farm_mean - watch_mean,
                    "watch_minus_ignore": None
                    if watch_mean is None or ignore_mean is None
                    else watch_mean - ignore_mean,
                }
            ),
        }
    )
