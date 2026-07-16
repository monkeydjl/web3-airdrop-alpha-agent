from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum
from math import isfinite
from types import MappingProxyType
from typing import Any, Literal
from urllib.parse import parse_qsl, urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    field_serializer,
    field_validator,
    model_validator,
)

_SENSITIVE_SOURCE_QUERY_KEYS = frozenset(
    {
        "token",
        "accesstoken",
        "refreshtoken",
        "idtoken",
        "securitytoken",
        "sessiontoken",
        "authtoken",
        "apikey",
        "xapikey",
        "clientsecret",
        "apisecret",
        "appsecret",
        "accesskey",
        "accesskeyid",
        "awsaccesskeyid",
        "privatekey",
        "credential",
        "credentials",
        "xamzcredential",
        "signature",
        "xamzsignature",
        "password",
        "passwd",
        "authorization",
        "auth",
        "jwt",
        "session",
        "sessionid",
        "sig",
        "key",
        "secret",
    }
)


def validate_source_url(value: HttpUrl | str) -> HttpUrl | str:
    parsed = urlsplit(str(value))
    if parsed.fragment:
        raise ValueError("source_url must not contain a fragment")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("source_url must not contain userinfo")
    for key, _ in parse_qsl(parsed.query, keep_blank_values=True):
        normalized = "".join(char for char in key.lower() if char.isalnum())
        if normalized in _SENSITIVE_SOURCE_QUERY_KEYS:
            raise ValueError("source_url must not contain sensitive query keys")
    return value


def _freeze_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise ValueError("JSON object keys must be strings")
        return MappingProxyType({key: _freeze_json(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    if isinstance(value, float) and not isfinite(value):
        raise ValueError("JSON numbers must be finite")
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    raise ValueError("expected a JSON-like value")


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


class DecisionStatus(StrEnum):
    ACTIONABLE = "ACTIONABLE"
    MONITOR = "MONITOR"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    NOT_FIT = "NOT_FIT"
    BLOCKED = "BLOCKED"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ProbabilityRange(BaseModel):
    model_config = ConfigDict(frozen=True, allow_inf_nan=False)
    low: float = Field(ge=0, le=1)
    base: float = Field(ge=0, le=1)
    high: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def ordered(self):
        if not self.low <= self.base <= self.high:
            raise ValueError("expected low <= base <= high")
        return self


class MoneyRange(BaseModel):
    model_config = ConfigDict(frozen=True, allow_inf_nan=False)
    low: float = Field(ge=0)
    base: float = Field(ge=0)
    high: float = Field(ge=0)

    @model_validator(mode="after")
    def ordered(self):
        if not self.low <= self.base <= self.high:
            raise ValueError("expected low <= base <= high")
        return self


class EvidenceRecord(BaseModel):
    model_config = ConfigDict(frozen=True, allow_inf_nan=False)
    evidence_id: str | None = None
    project_id: str | None = None
    factor_key: str = Field(min_length=1, max_length=100)
    value: Any
    value_type: Literal["bool", "number", "string", "range", "json"]
    observation_type: Literal["observed", "derived", "estimated", "assumed"]
    source_url: HttpUrl
    source_type: str = Field(min_length=1, max_length=50)
    source_grade: Literal["A", "B", "C", "D", "U"]
    observed_at: datetime
    effective_at: datetime | None = None
    expires_at: datetime | None = None
    verification_status: Literal["verified", "partially_verified", "unverified", "conflicted", "invalidated"] = (
        "unverified"
    )
    independence_group: str = Field(min_length=1, max_length=100)
    raw_snapshot_ref: str | None = None
    supersedes_evidence_id: str | None = None

    @field_validator("source_url")
    @classmethod
    def safe_source_url(cls, value: HttpUrl) -> HttpUrl:
        return validate_source_url(value)

    @field_validator("value", mode="before")
    @classmethod
    def freeze_value(cls, value: Any) -> Any:
        return _freeze_json(value)

    @field_serializer("value", when_used="json")
    def serialize_value(self, value: Any) -> Any:
        return _thaw_json(value)


class SignedMoneyRange(BaseModel):
    model_config = ConfigDict(frozen=True, allow_inf_nan=False)
    low: float
    base: float
    high: float

    @model_validator(mode="after")
    def ordered(self):
        if not self.low <= self.base <= self.high:
            raise ValueError("expected low <= base <= high")
        return self


class ConfidenceSet(BaseModel):
    model_config = ConfigDict(frozen=True, allow_inf_nan=False)
    event: float = Field(ge=0, le=1)
    eligibility: float = Field(ge=0, le=1)
    reward: float = Field(ge=0, le=1)
    cost: float = Field(ge=0, le=1)
    risk: float = Field(ge=0, le=1)
    quality: float = Field(ge=0, le=1)
    overall: float = Field(0.0, ge=0, le=1)


class RiskSet(BaseModel):
    model_config = ConfigDict(frozen=True, allow_inf_nan=False)
    capital_security: RiskLevel | None = None
    eligibility: RiskLevel | None = None
    project_failure: RiskLevel | None = None
    reward_dilution: RiskLevel | None = None
    liquidity: RiskLevel | None = None


class QualityFactors(BaseModel):
    model_config = ConfigDict(frozen=True, allow_inf_nan=False)
    product_demand: float | None = Field(None, ge=0, le=100)
    execution_growth: float | None = Field(None, ge=0, le=100)
    team_governance: float | None = Field(None, ge=0, le=100)
    financial_sustainability: float | None = Field(None, ge=0, le=100)
    security_transparency: float | None = Field(None, ge=0, le=100)


class EconomicsResult(BaseModel):
    model_config = ConfigDict(frozen=True, allow_inf_nan=False)
    gross_reward: MoneyRange
    net_reward: SignedMoneyRange
    reward_to_cost_ratio: float = Field(ge=0)
    decision_value: float
    capital_efficiency: float
    time_efficiency: float


class DecisionResult(BaseModel):
    model_config = ConfigDict(frozen=True, allow_inf_nan=False)
    status: DecisionStatus
    public_label: Literal["FARM", "WATCH", "IGNORE"]
    blocker_codes: tuple[str, ...] = ()
    watch_reason_codes: tuple[str, ...] = ()
    ignore_reason_codes: tuple[str, ...] = ()
    requires_remediation: bool = False
    recommended_action: str
    review_at: datetime
    expires_at: datetime

    @model_validator(mode="after")
    def remediation_matches_status(self):
        if self.requires_remediation != (self.status == DecisionStatus.BLOCKED):
            raise ValueError("requires_remediation must be true exactly when status is BLOCKED")
        return self


class OpportunityProfile(BaseModel):
    model_config = ConfigDict(frozen=True, allow_inf_nan=False)
    profile_id: str
    wallet_count_min: int = Field(ge=1)
    wallet_count_max: int = Field(ge=1)
    hard_cost_limit_per_wallet_usd: float = Field(ge=0)
    weekly_time_limit_hours: float = Field(gt=0)
    horizon_months: tuple[int, int]
    strategy: Literal["compliant_curated_multiwallet"]
    loss_preference: Literal["conservative"]

    @model_validator(mode="after")
    def ordered_limits(self):
        if self.wallet_count_min > self.wallet_count_max:
            raise ValueError("wallet_count_min must not exceed wallet_count_max")
        if self.horizon_months != (3, 6):
            raise ValueError("the v1 profile horizon must be 3-6 months")
        return self


class OpportunityInputs(BaseModel):
    model_config = ConfigDict(frozen=True, allow_inf_nan=False)
    project_id: str
    event_probability: ProbabilityRange | None = None
    eligibility_probability: ProbabilityRange | None = None
    survival_probability: ProbabilityRange | None = None
    conditional_reward_usd: MoneyRange | None = None
    hard_cost_usd: MoneyRange | None = None
    capital_at_risk_usd: MoneyRange | None = None
    expected_capital_loss_usd: MoneyRange | None = None
    liquidity_cost_usd: MoneyRange | None = None
    total_time_hours: MoneyRange | None = None
    weekly_maintenance_hours: float | None = Field(None, ge=0)
    participation_open: bool | None = None
    task_path_known: bool | None = None
    authorization_exit_known: bool | None = None
    distribution_catalyst_3_6m: bool | None = None
    project_active: bool | None = None
    opportunity_timing: Literal["open", "late", "closed", "unknown"] = "unknown"
    profile_fit: Literal["fit", "single_wallet_only", "mismatch", "unknown"] = "unknown"
    weekly_time_confirmed_minimum: bool = False
    project_quality: float | None = Field(None, ge=0, le=100)
    project_failure_risk: RiskLevel | None = None
    capital_security_risk: RiskLevel | None = None
    official_multiwallet_policy: Literal["allowed", "not_forbidden", "forbidden", "unknown"] = "unknown"
    official_airdrop_evidence_count_a: int = Field(0, ge=0)
    independent_airdrop_evidence_count_b: int = Field(0, ge=0)
    confidence: ConfidenceSet
    risks: RiskSet
    critical_unknowns: tuple[str, ...] = ()
    integrity_blocked: bool | None = None
    safety_blocked: bool | None = None
    evidence_ids: tuple[str, ...] = ()


class OpportunityAssessment(BaseModel):
    model_config = ConfigDict(frozen=True, allow_inf_nan=False)
    assessment_id: str | None = None
    project_id: str
    model_version: Literal["opportunity-v2.0"]
    profile_version: Literal["low-cost-curated-multiwallet-v1"]
    event_probability: ProbabilityRange | None = None
    eligibility_probability: ProbabilityRange | None = None
    survival_probability: ProbabilityRange | None = None
    reward_probability: ProbabilityRange | None = None
    conditional_reward_usd: MoneyRange | None = None
    hard_cost_usd: MoneyRange | None = None
    capital_at_risk_usd: MoneyRange | None = None
    expected_capital_loss_usd: MoneyRange | None = None
    liquidity_cost_usd: MoneyRange | None = None
    total_time_hours: MoneyRange | None = None
    weekly_maintenance_hours: float | None = None
    economics: EconomicsResult | None = None
    project_quality: float | None = None
    risks: RiskSet
    confidence: ConfidenceSet
    status: DecisionStatus
    public_label: Literal["FARM", "WATCH", "IGNORE"]
    blocker_codes: tuple[str, ...] = ()
    watch_reason_codes: tuple[str, ...] = ()
    ignore_reason_codes: tuple[str, ...] = ()
    requires_remediation: bool = False
    recommended_action: str
    evidence_ids: tuple[str, ...] = ()
    factor_snapshot: Mapping[str, Any] = Field(default_factory=dict)
    scored_at: datetime
    review_at: datetime
    expires_at: datetime

    @model_validator(mode="after")
    def remediation_matches_status(self):
        if self.requires_remediation != (self.status == DecisionStatus.BLOCKED):
            raise ValueError("requires_remediation must be true exactly when status is BLOCKED")
        return self

    @field_validator("factor_snapshot", mode="after")
    @classmethod
    def freeze_factor_snapshot(cls, value: Mapping[str, Any]) -> Mapping[str, Any]:
        return _freeze_json(value)

    @field_serializer("factor_snapshot", when_used="json")
    def serialize_factor_snapshot(self, value: Mapping[str, Any]) -> dict[str, Any]:
        return _thaw_json(value)
