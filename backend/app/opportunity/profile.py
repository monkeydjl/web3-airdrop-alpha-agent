from typing import Literal

from app.opportunity.models import OpportunityProfile

MODEL_VERSION: Literal["opportunity-v2.0"] = "opportunity-v2.0"

DEFAULT_PROFILE = OpportunityProfile(
    profile_id="low-cost-curated-multiwallet-v1",
    wallet_count_min=3,
    wallet_count_max=10,
    hard_cost_limit_per_wallet_usd=10,
    weekly_time_limit_hours=2,
    horizon_months=(3, 6),
    strategy="compliant_curated_multiwallet",
    loss_preference="conservative",
)
