import math
from dataclasses import dataclass
from datetime import datetime


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
