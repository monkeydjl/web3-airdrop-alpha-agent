import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType


@dataclass(frozen=True)
class RangeValue:
    low: float
    base: float
    high: float

    def __post_init__(self) -> None:
        if not all(math.isfinite(value) for value in (self.low, self.base, self.high)):
            raise ValueError("range values must be finite")
        if not self.low <= self.base <= self.high:
            raise ValueError("range values must satisfy low <= base <= high")


@dataclass(frozen=True)
class CalibrationSample:
    project_id: str
    assessment_id: str
    cohort_id: str
    scored_at: datetime
    outcome_observed_at: datetime
    model_version: str
    profile_version: str
    status: str
    public_label: str
    wallet_count: int
    event_probability: RangeValue
    eligibility_probability: RangeValue
    survival_probability: RangeValue
    reward_probability: RangeValue
    net_reward: RangeValue
    hard_cost: RangeValue
    total_time_hours: RangeValue
    outcome: str | None
    eligibility_result: str | None
    survival_result: str | None
    reward_received_usd: float | None
    actual_hard_cost_usd: float | None
    claim_cost_usd: float | None
    actual_time_minutes: int | None


@dataclass(frozen=True)
class OutcomeValues:
    event: int | None
    eligibility: int | None
    survival: int | None
    reward: int | None
    realized_net_usd: float | None
    realized_class: str | None
    actual_hard_cost_usd: float | None
    actual_time_hours: float | None
    claim_cost_usd: float | None


@dataclass(frozen=True)
class BinaryObservation:
    project_id: str
    predicted: float
    actual: int

    def __post_init__(self) -> None:
        if not self.project_id:
            raise ValueError("project_id must not be empty")
        if not math.isfinite(self.predicted) or not 0 <= self.predicted <= 1:
            raise ValueError("predicted must be finite and between 0 and 1")
        if self.actual not in (0, 1):
            raise ValueError("actual must be 0 or 1")


@dataclass(frozen=True)
class NumericObservation:
    project_id: str
    low: float
    base: float
    high: float
    actual: float

    def __post_init__(self) -> None:
        if not self.project_id:
            raise ValueError("project_id must not be empty")
        if not all(math.isfinite(value) for value in (self.low, self.base, self.high, self.actual)):
            raise ValueError("numeric observation values must be finite")
        if not self.low <= self.base <= self.high:
            raise ValueError("prediction range must satisfy low <= base <= high")


@dataclass(frozen=True)
class CalibrationDataset:
    samples: tuple[CalibrationSample, ...]
    quality: Mapping[str, int]
    backend: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "quality", MappingProxyType(dict(self.quality)))
