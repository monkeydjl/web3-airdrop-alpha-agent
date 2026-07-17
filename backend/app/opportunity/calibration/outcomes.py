from datetime import datetime, timedelta

from .models import CalibrationSample, OutcomeValues


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
    reward = None if sample.reward_received_usd is None else int(sample.reward_received_usd > 0)

    contradictory = (
        sample.reward_received_usd is not None
        and sample.reward_received_usd > 0
        and (event == 0 or eligibility == 0 or survival == 0)
    )
    if contradictory:
        reward = None

    realized_net_usd = None
    realized_class = None
    if not contradictory and all(
        value is not None
        for value in (
            sample.reward_received_usd,
            sample.actual_hard_cost_usd,
            sample.claim_cost_usd,
        )
    ):
        realized_net_usd = sample.reward_received_usd - sample.actual_hard_cost_usd - sample.claim_cost_usd
        if realized_net_usd > 0:
            realized_class = "POSITIVE"
        elif realized_net_usd < 0:
            realized_class = "NEGATIVE"
        else:
            realized_class = "NEUTRAL"

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
