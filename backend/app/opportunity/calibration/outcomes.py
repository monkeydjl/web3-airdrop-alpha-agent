from dataclasses import dataclass
from datetime import datetime, timedelta

from .models import CalibrationSample, OutcomeValues


@dataclass(frozen=True)
class MappedOutcome:
    sample: CalibrationSample
    outcome: OutcomeValues
    concerns: tuple[str, ...]


def maturity_state(
    sample: CalibrationSample,
    *,
    as_of: datetime,
    window_days: int,
) -> str:
    if sample.scored_at > sample.outcome_observed_at:
        return "outcome_before_assessment"
    if sample.outcome_observed_at > as_of:
        return "outcome_after_as_of"
    if sample.outcome_observed_at - sample.scored_at < timedelta(days=window_days):
        return "immature"
    return "mature"


def map_outcomes(sample: CalibrationSample) -> tuple[OutcomeValues, tuple[str, ...]]:
    event = {"airdropped": 1, "not_airdropped": 0}.get(sample.outcome)
    eligibility = {"eligible": 1, "ineligible": 0}.get(sample.eligibility_result)
    survival = {"passed": 1, "disqualified": 0}.get(sample.survival_result)
    positive_reward = sample.reward_received_usd is not None and sample.reward_received_usd > 0
    negative_reward = sample.reward_received_usd is not None and sample.reward_received_usd < 0
    explicit_no_reward = sample.reward_received_usd == 0 or event == 0 or eligibility == 0 or survival == 0

    contradictory = positive_reward and (event == 0 or eligibility == 0 or survival == 0)
    if contradictory or negative_reward:
        reward = None
    elif positive_reward:
        reward = 1
    elif explicit_no_reward:
        reward = 0
    else:
        reward = None

    realized_net_usd = None
    realized_class = None
    if (
        not contradictory
        and reward is not None
        and all(
            value is not None
            for value in (
                sample.reward_received_usd,
                sample.actual_hard_cost_usd,
                sample.claim_cost_usd,
            )
        )
    ):
        realized_net_usd = sample.reward_received_usd - sample.actual_hard_cost_usd - sample.claim_cost_usd

    if not contradictory and not negative_reward:
        if eligibility == 0 or survival == 0 or (realized_net_usd is not None and realized_net_usd < 0):
            realized_class = "NEGATIVE"
        elif eligibility == 1 and survival == 1 and realized_net_usd is not None:
            realized_class = "POSITIVE" if realized_net_usd > 0 else "NEUTRAL"

    return (
        OutcomeValues(
            event=event,
            eligibility=eligibility,
            survival=survival,
            reward=reward,
            realized_net_usd=realized_net_usd,
            realized_class=realized_class,
            actual_hard_cost_usd=sample.actual_hard_cost_usd,
            actual_time_hours=(None if sample.actual_time_minutes is None else sample.actual_time_minutes / 60),
            claim_cost_usd=sample.claim_cost_usd,
        ),
        ("contradictory_outcome",) if contradictory else (),
    )


def map_sample(sample: CalibrationSample) -> MappedOutcome:
    outcome, concerns = map_outcomes(sample)
    return MappedOutcome(sample, outcome, concerns)
