# Opportunity v2.0 Shadow MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a conservative backend Shadow evaluator for `opportunity-v2.0` that stores traceable evidence, calculates probability/reward/cost/risk outputs, persists immutable prediction snapshots, and exposes them through API without changing the current `score-v1.4` labels.

**Architecture:** Add a focused `app/opportunity/` package with immutable domain models, pure calculators, an evidence adapter, a decision engine, and a repository. The existing pipeline optionally invokes the new service after legacy scoring and persists a separate Shadow assessment; it never mutates `PipelineState.score`, `PipelineState.label`, or existing `projects` columns. Missing critical evidence yields `INSUFFICIENT_EVIDENCE/WATCH`, never guessed FARM.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic v2, SQLite/PostgreSQL through the existing `DbConnection`, pytest, existing `{ok,data,error}` API envelope.

## Global Constraints

- Model version is exactly `opportunity-v2.0`.
- Default profile is exactly `low-cost-curated-multiwallet-v1`.
- Default profile uses 3-10 wallets, at most 10 USD hard cost per wallet, at most 2 portfolio maintenance hours per week, and a 3-6 month horizon.
- The strategy is compliant curated multi-wallet participation; do not implement anti-sybil evasion guidance.
- Existing `score-v1.4` output remains authoritative and unchanged during Shadow mode.
- Opportunity Shadow evaluation is controlled by `opportunity_shadow_enabled`, default `False`.
- Missing critical evidence must return `INSUFFICIENT_EVIDENCE/WATCH`; it must not receive a neutral default that can produce FARM.
- FARM requires all hard gates, `P_event.low >= 0.50`, `P_eligibility.low >= 0.50`, `P_survival.low >= 0.60`, `P_reward.low >= 0.20`, conservative net reward above 0 USD, base net reward at least 30 USD, reward-to-cost ratio at least 3, Project Quality at least 50, and the confidence floors from the approved design.
- The optimistic scenario contributes only 10% to Decision Value and cannot independently make a project FARM.
- A single underlying fact has one primary scoring owner; other components may cite it but must not score it again.
- Do not read or modify `.env`; only update `.env.example` if configuration documentation is needed.
- All database DDL must remain idempotent and work on SQLite and PostgreSQL.
- All implementation follows TDD: failing focused test, minimal implementation, passing focused test, then affected suite.
- The current workspace contains pre-existing uncommitted changes in files this plan will touch. Treat every listed commit step as conditional: run it only after the user explicitly requests commits and the execution workspace has a clean, verified baseline that includes the current W1-W4/post-W4 code. Otherwise stop each task at the passing verification checkpoint; never stage an entire dirty file or unrelated changes.

## Scope Boundaries

This plan delivers the first independently testable subsystem: the backend Shadow MVP. It intentionally does not implement:

- Real-time qualified-wallet counts, leaderboard concentration, or market valuation collectors.
- A Next.js opportunity dashboard or action workflow.
- Automated calibration/search against realized outcomes.
- Replacement of the existing FARM/WATCH/IGNORE decision.
- Automated execution or wallet integration.

Those are separate follow-up plans after Shadow data quality is measured.

## File Map

New package responsibilities:

- `backend/app/opportunity/models.py`: immutable domain enums and Pydantic contracts.
- `backend/app/opportunity/profile.py`: the versioned default user profile only.
- `backend/app/opportunity/evidence.py`: evidence validation, source grading, independence, critical-field extraction, and legacy-signal adaptation.
- `backend/app/opportunity/probability.py`: pure `P_event`, `P_eligibility`, `P_survival`, and interval multiplication.
- `backend/app/opportunity/economics.py`: conditional reward, expected net reward, Decision Value, capital/time efficiency.
- `backend/app/opportunity/quality.py`: Project Quality and per-domain confidence calculations.
- `backend/app/opportunity/decision.py`: hard gates and internal/public label decision.
- `backend/app/opportunity/repository.py`: evidence and immutable assessment persistence.
- `backend/app/opportunity/service.py`: orchestration from project row/evidence to assessment.
- `backend/app/routers/v1/opportunity.py`: evidence and Shadow assessment API.

Existing files touched:

- `backend/app/config.py`: Shadow feature flag.
- `backend/app/db.py`: evidence and assessment tables/indexes for both DB backends.
- `backend/app/main.py`: router registration and health capability signal.
- `backend/app/pipeline_run.py`: optional best-effort Shadow invocation after legacy scoring.
- `backend/app/routers/v1/interactions.py`: outcome fields required for later calibration.
- `docs/API_SPEC.md`, `docs/DATABASE_DDL.md`, `docs/IMPLEMENTATION_STATUS.md`: contracts and implementation status.

---

### Task 1: Domain Contracts and Default Profile

**Files:**
- Create: `backend/app/opportunity/__init__.py`
- Create: `backend/app/opportunity/models.py`
- Create: `backend/app/opportunity/profile.py`
- Create: `backend/tests/opportunity/__init__.py`
- Create: `backend/tests/opportunity/test_models.py`

**Interfaces:**
- Produces: `ProbabilityRange`, `MoneyRange`, `EvidenceRecord`, `OpportunityInputs`, `OpportunityAssessment`, `DecisionStatus`, `RiskLevel`, `OpportunityProfile`.
- Produces: `DEFAULT_PROFILE: OpportunityProfile` and `MODEL_VERSION = "opportunity-v2.0"`.
- Consumes: Pydantic v2 only; no database or service dependencies.

- [ ] **Step 1: Write failing model and profile tests**

```python
from pydantic import ValidationError
import pytest

from app.opportunity.models import (
    DecisionStatus,
    EvidenceRecord,
    MoneyRange,
    ProbabilityRange,
)
from app.opportunity.profile import DEFAULT_PROFILE, MODEL_VERSION


def test_probability_range_orders_values():
    value = ProbabilityRange(low=0.2, base=0.4, high=0.7)
    assert value.low == 0.2
    with pytest.raises(ValidationError):
        ProbabilityRange(low=0.6, base=0.4, high=0.8)


def test_money_range_rejects_negative_rewards():
    with pytest.raises(ValidationError):
        MoneyRange(low=-1, base=20, high=30)


def test_evidence_requires_provenance():
    with pytest.raises(ValidationError):
        EvidenceRecord(
            factor_key="official_airdrop_statement",
            value=True,
            source_type="official_docs",
            source_grade="A",
            observed_at="2026-07-14T00:00:00Z",
        )


def test_default_profile_is_exact():
    assert MODEL_VERSION == "opportunity-v2.0"
    assert DEFAULT_PROFILE.profile_id == "low-cost-curated-multiwallet-v1"
    assert DEFAULT_PROFILE.wallet_count_min == 3
    assert DEFAULT_PROFILE.wallet_count_max == 10
    assert DEFAULT_PROFILE.hard_cost_limit_per_wallet_usd == 10
    assert DEFAULT_PROFILE.weekly_time_limit_hours == 2
    assert DEFAULT_PROFILE.horizon_months == (3, 6)
    assert DecisionStatus.ACTIONABLE.value == "ACTIONABLE"
```

- [ ] **Step 2: Run tests and verify RED**

Run: `pytest tests/opportunity/test_models.py -v`

Expected: collection fails because `app.opportunity.models` and `app.opportunity.profile` do not exist.

- [ ] **Step 3: Implement immutable domain models**

Create `models.py` with these exact public contracts:

```python
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


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
    model_config = ConfigDict(frozen=True)
    low: float = Field(ge=0, le=1)
    base: float = Field(ge=0, le=1)
    high: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def ordered(self):
        if not self.low <= self.base <= self.high:
            raise ValueError("expected low <= base <= high")
        return self


class MoneyRange(BaseModel):
    model_config = ConfigDict(frozen=True)
    low: float = Field(ge=0)
    base: float = Field(ge=0)
    high: float = Field(ge=0)

    @model_validator(mode="after")
    def ordered(self):
        if not self.low <= self.base <= self.high:
            raise ValueError("expected low <= base <= high")
        return self


class EvidenceRecord(BaseModel):
    model_config = ConfigDict(frozen=True)
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
    verification_status: Literal[
        "verified", "partially_verified", "unverified", "conflicted", "invalidated"
    ] = "unverified"
    independence_group: str = Field(min_length=1, max_length=100)
    raw_snapshot_ref: str | None = None
```

Also define these immutable contracts exactly. `SignedMoneyRange` is required because a conservative net return must remain negative when costs exceed expected reward:

```python
class SignedMoneyRange(BaseModel):
    model_config = ConfigDict(frozen=True)
    low: float
    base: float
    high: float

    @model_validator(mode="after")
    def ordered(self):
        if not self.low <= self.base <= self.high:
            raise ValueError("expected low <= base <= high")
        return self


class ConfidenceSet(BaseModel):
    model_config = ConfigDict(frozen=True)
    event: float = Field(ge=0, le=1)
    eligibility: float = Field(ge=0, le=1)
    reward: float = Field(ge=0, le=1)
    cost: float = Field(ge=0, le=1)
    risk: float = Field(ge=0, le=1)
    quality: float = Field(ge=0, le=1)
    overall: float = Field(0.0, ge=0, le=1)


class RiskSet(BaseModel):
    model_config = ConfigDict(frozen=True)
    capital_security: RiskLevel
    eligibility: RiskLevel
    project_failure: RiskLevel
    reward_dilution: RiskLevel
    liquidity: RiskLevel


class QualityFactors(BaseModel):
    model_config = ConfigDict(frozen=True)
    product_demand: float | None = Field(None, ge=0, le=100)
    execution_growth: float | None = Field(None, ge=0, le=100)
    team_governance: float | None = Field(None, ge=0, le=100)
    financial_sustainability: float | None = Field(None, ge=0, le=100)
    security_transparency: float | None = Field(None, ge=0, le=100)


class EconomicsResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    gross_reward: MoneyRange
    net_reward: SignedMoneyRange
    reward_to_cost_ratio: float = Field(ge=0)
    decision_value: float
    capital_efficiency: float
    time_efficiency: float


class DecisionResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    status: DecisionStatus
    public_label: Literal["FARM", "WATCH", "IGNORE"]
    blocker_codes: tuple[str, ...] = ()
    watch_reason_codes: tuple[str, ...] = ()
    ignore_reason_codes: tuple[str, ...] = ()
    recommended_action: str
    review_at: datetime
    expires_at: datetime


class OpportunityProfile(BaseModel):
    model_config = ConfigDict(frozen=True)
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
```

`OpportunityInputs` contains explicit optional ranges/values rather than generic untyped score dictionaries:

```python
class OpportunityInputs(BaseModel):
    model_config = ConfigDict(frozen=True)
    project_id: str
    event_probability: ProbabilityRange | None = None
    eligibility_probability: ProbabilityRange | None = None
    survival_probability: ProbabilityRange | None = None
    conditional_reward_usd: MoneyRange | None = None
    hard_cost_usd: MoneyRange | None = None
    expected_capital_loss_usd: MoneyRange | None = None
    liquidity_cost_usd: MoneyRange | None = None
    total_time_hours: MoneyRange | None = None
    weekly_maintenance_hours: float | None = Field(None, ge=0)
    project_quality: float | None = Field(None, ge=0, le=100)
    project_failure_risk: RiskLevel | None = None
    capital_security_risk: RiskLevel | None = None
    official_multiwallet_policy: Literal["allowed", "not_forbidden", "forbidden", "unknown"] = "unknown"
    official_airdrop_evidence_count_a: int = Field(0, ge=0)
    independent_airdrop_evidence_count_b: int = Field(0, ge=0)
    confidence: ConfidenceSet
    risks: RiskSet
    critical_unknowns: tuple[str, ...] = ()
    integrity_blocked: bool = False
    safety_blocked: bool = False
    evidence_ids: tuple[str, ...] = ()
```

Define the immutable assessment snapshot exactly:

```python
class OpportunityAssessment(BaseModel):
    model_config = ConfigDict(frozen=True)
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
    recommended_action: str
    evidence_ids: tuple[str, ...] = ()
    factor_snapshot: dict[str, Any] = Field(default_factory=dict)
    scored_at: datetime
    review_at: datetime
    expires_at: datetime
```

- [ ] **Step 4: Implement the versioned profile**

```python
from app.opportunity.models import OpportunityProfile

MODEL_VERSION = "opportunity-v2.0"

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
```

- [ ] **Step 5: Run focused tests and type/import checks**

Run: `pytest tests/opportunity/test_models.py -v`

Expected: all tests pass.

Run: `python -c "from app.opportunity.models import OpportunityAssessment; from app.opportunity.profile import DEFAULT_PROFILE; print(DEFAULT_PROFILE.profile_id)"`

Expected: prints `low-cost-curated-multiwallet-v1`.

- [ ] **Step 6: Commit Task 1**

```bash
git add backend/app/opportunity/__init__.py backend/app/opportunity/models.py backend/app/opportunity/profile.py backend/tests/opportunity/__init__.py backend/tests/opportunity/test_models.py
git commit -m "feat(opportunity): add v2 domain contracts"
```

---

### Task 2: Idempotent Evidence and Assessment Storage

**Files:**
- Modify: `backend/app/db.py:190-375,378-563,580-601`
- Create: `backend/app/opportunity/repository.py`
- Create: `backend/tests/opportunity/test_repository.py`

**Interfaces:**
- Consumes: `EvidenceRecord`, `OpportunityAssessment` from Task 1.
- Produces: `OpportunityRepository.add_evidence(record) -> EvidenceRecord`.
- Produces: `OpportunityRepository.list_evidence(project_id, include_invalid=False) -> list[EvidenceRecord]`.
- Produces: `OpportunityRepository.save_assessment(assessment) -> str`.
- Produces: `OpportunityRepository.latest_assessment(project_id, profile_id) -> OpportunityAssessment | None`.

- [ ] **Step 1: Write failing schema and repository tests**

```python
import sqlite3

from app.db import init_db
from app.opportunity.models import EvidenceRecord
from app.opportunity.repository import OpportunityRepository


def test_init_db_creates_opportunity_tables():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "opportunity_evidence" in names
    assert "opportunity_assessments" in names


def test_evidence_is_append_only_and_round_trips():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    repo = OpportunityRepository(conn)
    record = EvidenceRecord(
        project_id="p1",
        factor_key="official_points_program",
        value=True,
        value_type="bool",
        observation_type="observed",
        source_url="https://project.example/docs/points",
        source_type="official_docs",
        source_grade="A",
        observed_at="2026-07-14T00:00:00Z",
        verification_status="verified",
        independence_group="official-docs-points",
    )
    first = repo.add_evidence(record)
    second = repo.add_evidence(record)
    assert first.evidence_id != second.evidence_id
    assert len(repo.list_evidence("p1")) == 2
```

Add a third test that saves two assessments for the same project/profile and asserts `latest_assessment()` returns the second without updating or deleting the first.

- [ ] **Step 2: Run repository tests and verify RED**

Run: `pytest tests/opportunity/test_repository.py -v`

Expected: fails because the tables and repository do not exist.

- [ ] **Step 3: Add SQLite and PostgreSQL DDL**

Add equivalent tables to both DDL functions:

```sql
CREATE TABLE IF NOT EXISTS opportunity_evidence (
    evidence_id        TEXT PRIMARY KEY,
    project_id         TEXT NOT NULL,
    factor_key         TEXT NOT NULL,
    value_json         TEXT NOT NULL,
    value_type         TEXT NOT NULL,
    observation_type   TEXT NOT NULL,
    source_url         TEXT NOT NULL,
    source_type        TEXT NOT NULL,
    source_grade       TEXT NOT NULL,
    observed_at        TIMESTAMP NOT NULL,
    effective_at       TIMESTAMP,
    expires_at         TIMESTAMP,
    verification_status TEXT NOT NULL,
    independence_group TEXT NOT NULL,
    raw_snapshot_ref   TEXT,
    created_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS opportunity_assessments (
    assessment_id      TEXT PRIMARY KEY,
    project_id         TEXT NOT NULL,
    model_version      TEXT NOT NULL,
    profile_version    TEXT NOT NULL,
    assessment_json    TEXT NOT NULL,
    decision_status    TEXT NOT NULL,
    public_label       TEXT NOT NULL,
    decision_value     DOUBLE PRECISION,
    overall_confidence DOUBLE PRECISION NOT NULL,
    scored_at          TIMESTAMP NOT NULL,
    review_at          TIMESTAMP,
    expires_at         TIMESTAMP NOT NULL,
    created_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

Use `REAL` instead of `DOUBLE PRECISION` in SQLite. Add indexes:

```sql
CREATE INDEX IF NOT EXISTS idx_opportunity_evidence_project
ON opportunity_evidence(project_id, observed_at DESC);
CREATE INDEX IF NOT EXISTS idx_opportunity_evidence_factor
ON opportunity_evidence(project_id, factor_key, verification_status);
CREATE INDEX IF NOT EXISTS idx_opportunity_assessment_latest
ON opportunity_assessments(project_id, profile_version, scored_at DESC);
CREATE INDEX IF NOT EXISTS idx_opportunity_assessment_label
ON opportunity_assessments(public_label, expires_at);
```

Do not add foreign keys in this task because existing project deletion behavior has no cascade contract.

- [ ] **Step 4: Implement the repository with explicit JSON serialization**

Use `_as_db_connection()` to accept raw SQLite or `DbConnection`, generate UUIDs with `uuid.uuid4()`, and serialize with Pydantic JSON mode. Use these exact column lists:

```python
class OpportunityRepository:
    def __init__(self, conn=None):
        self._conn, self._owns_connection = _as_db_connection(conn)

    def add_evidence(self, record: EvidenceRecord) -> EvidenceRecord:
        stored = record.model_copy(update={"evidence_id": record.evidence_id or str(uuid.uuid4())})
        self._conn.execute(
            """INSERT INTO opportunity_evidence (
                   evidence_id, project_id, factor_key, value_json, value_type,
                   observation_type, source_url, source_type, source_grade,
                   observed_at, effective_at, expires_at, verification_status,
                   independence_group, raw_snapshot_ref
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                stored.evidence_id, stored.project_id, stored.factor_key,
                json.dumps(stored.value, ensure_ascii=False), stored.value_type,
                stored.observation_type, str(stored.source_url), stored.source_type,
                stored.source_grade, stored.observed_at, stored.effective_at,
                stored.expires_at, stored.verification_status,
                stored.independence_group, stored.raw_snapshot_ref,
            ),
        )
        self._conn.commit()
        return stored

    def save_assessment(self, assessment: OpportunityAssessment) -> str:
        assessment_id = assessment.assessment_id or str(uuid.uuid4())
        payload = assessment.model_copy(update={"assessment_id": assessment_id})
        self._conn.execute(
            """INSERT INTO opportunity_assessments (
                   assessment_id, project_id, model_version, profile_version,
                   assessment_json, decision_status, public_label, decision_value,
                   overall_confidence, scored_at, review_at, expires_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                assessment_id, payload.project_id, payload.model_version,
                payload.profile_version, payload.model_dump_json(), payload.status,
                payload.public_label,
                payload.economics.decision_value if payload.economics else None,
                payload.confidence.overall, payload.scored_at, payload.review_at,
                payload.expires_at,
            ),
        )
        self._conn.commit()
        return assessment_id
```

Add `close()` and context-manager methods; close only when `_owns_connection` is true. `list_evidence()` reconstructs `EvidenceRecord` after `json.loads(value_json)`. `latest_assessment()` orders by `scored_at DESC, created_at DESC LIMIT 1` and validates `assessment_json` with `OpportunityAssessment.model_validate_json()`.

No update method is allowed for assessments. Evidence invalidation, when needed later, must append superseding evidence or explicitly change only `verification_status`; it must never overwrite `value_json`.

- [ ] **Step 5: Run repository tests**

Run: `pytest tests/opportunity/test_repository.py -v`

Expected: all tests pass.

Run: `pytest tests/test_deployment.py tests/test_pipeline_run.py -v`

Expected: existing DB initialization and pipeline tests pass.

- [ ] **Step 6: Commit Task 2**

```bash
git add backend/app/db.py backend/app/opportunity/repository.py backend/tests/opportunity/test_repository.py
git commit -m "feat(opportunity): persist evidence and assessments"
```

---

### Task 3: Evidence Normalization and Legacy Adapter

**Files:**
- Create: `backend/app/opportunity/evidence.py`
- Create: `backend/tests/opportunity/test_evidence.py`

**Interfaces:**
- Consumes: `EvidenceRecord`, `OpportunityInputs`, existing project row and `meta.signals`.
- Produces: `SOURCE_GRADE_WEIGHT: dict[str, float]`.
- Produces: `independent_count(records, minimum_grade) -> int`.
- Produces: `build_inputs(project_row, evidence, profile) -> OpportunityInputs`.
- Produces: critical unknown keys and evidence IDs used by the service.

- [ ] **Step 1: Write failing evidence tests**

```python
from app.opportunity.evidence import build_inputs, independent_count
from app.opportunity.models import EvidenceRecord
from app.opportunity.profile import DEFAULT_PROFILE


def _record(factor, value, grade="A", group="g1"):
    return EvidenceRecord(
        project_id="p1",
        factor_key=factor,
        value=value,
        value_type="bool" if isinstance(value, bool) else "string",
        observation_type="observed",
        source_url="https://project.example/rules",
        source_type="official_docs",
        source_grade=grade,
        observed_at="2026-07-14T00:00:00Z",
        verification_status="verified",
        independence_group=group,
    )


def test_reposts_count_as_one_independent_source():
    records = [
        _record("official_airdrop_statement", True, "B", "same-announcement"),
        _record("official_airdrop_statement", True, "B", "same-announcement"),
    ]
    assert independent_count(records, minimum_grade="B") == 1


def test_legacy_signals_never_create_complete_inputs():
    row = {
        "id": "p1",
        "stage": "testnet",
        "meta": '{"signals":{"no_token_yet":true,"has_points_program":true}}',
    }
    inputs = build_inputs(row, [], DEFAULT_PROFILE)
    assert "multiwallet_policy" in inputs.critical_unknowns
    assert "hard_cost" in inputs.critical_unknowns
    assert inputs.official_airdrop_evidence_count_a == 0


def test_verified_forbidden_policy_is_preserved():
    inputs = build_inputs(
        {"id": "p1", "meta": "{}"},
        [_record("multiwallet_policy", "forbidden")],
        DEFAULT_PROFILE,
    )
    assert inputs.official_multiwallet_policy == "forbidden"
```

- [ ] **Step 2: Run tests and verify RED**

Run: `pytest tests/opportunity/test_evidence.py -v`

Expected: fails because `app.opportunity.evidence` does not exist.

- [ ] **Step 3: Implement source grading and current-evidence filtering**

```python
SOURCE_GRADE_WEIGHT = {"A": 1.0, "B": 0.8, "C": 0.5, "D": 0.2, "U": 0.0}


def usable(record: EvidenceRecord, now: datetime) -> bool:
    if record.verification_status in {"invalidated", "conflicted"}:
        return False
    return record.expires_at is None or record.expires_at > now


def independent_count(records: list[EvidenceRecord], minimum_grade: str) -> int:
    floor = SOURCE_GRADE_WEIGHT[minimum_grade]
    return len({
        record.independence_group
        for record in records
        if SOURCE_GRADE_WEIGHT[record.source_grade] >= floor
        and record.verification_status in {"verified", "partially_verified"}
    })
```

- [ ] **Step 4: Implement a closed factor-key mapping**

The Shadow MVP supports these evidence keys only; unknown keys are rejected by the API in Task 8:

```python
SUPPORTED_FACTOR_KEYS = {
    "official_identity",
    "participation_open",
    "official_airdrop_statement",
    "official_points_future_value",
    "community_allocation",
    "distribution_catalyst_3_6m",
    "multiwallet_policy",
    "eligibility_mechanism",
    "hard_cost_usd",
    "weekly_maintenance_hours",
    "total_time_hours",
    "conditional_reward_usd",
    "capital_at_risk_usd",
    "expected_capital_loss_usd",
    "liquidity_cost_usd",
    "project_quality",
    "project_failure_risk",
    "capital_security_risk",
    "integrity_blocked",
    "safety_blocked",
    "event_probability",
    "eligibility_probability",
    "survival_probability",
}
```

Range-valued evidence uses JSON objects with the keys `low`, `base`, and `high`. Probability ranges are 0-1; money/time ranges are non-negative. Validate the object with `ProbabilityRange.model_validate()` or `MoneyRange.model_validate()` according to `factor_key`; reject missing keys, additional keys, wrong order, or values outside the relevant domain.

- [ ] **Step 5: Implement conservative legacy adaptation**

`build_inputs()` may use existing `meta.signals` only as low-confidence context. It must not create A/B counts, explicit costs, reward amounts, multiwallet policy, safety clearance, or user-provided probability ranges from legacy booleans. If evidence is missing, populate these exact critical unknown keys:

```python
CRITICAL_KEYS = {
    "official_identity",
    "participation_open",
    "airdrop_basis",
    "multiwallet_policy",
    "hard_cost",
    "weekly_maintenance",
    "capital_security",
    "conditional_reward",
}
```

Use the latest non-expired verified evidence per factor, ordered by `observed_at`, and retain all supporting evidence IDs for audit. Do not synthesize a probability range in this adapter; probability derivation belongs to Task 4.

- [ ] **Step 6: Run evidence tests**

Run: `pytest tests/opportunity/test_evidence.py -v`

Expected: all tests pass.

- [ ] **Step 7: Commit Task 3**

```bash
git add backend/app/opportunity/evidence.py backend/tests/opportunity/test_evidence.py
git commit -m "feat(opportunity): normalize auditable evidence"
```

---

### Task 4: Probability Engine

**Files:**
- Create: `backend/app/opportunity/probability.py`
- Create: `backend/tests/opportunity/test_probability.py`

**Interfaces:**
- Consumes: `OpportunityInputs`, verified factor observations from Task 3.
- Produces: `derive_probability_inputs(inputs: OpportunityInputs, evidence: list[EvidenceRecord], profile: OpportunityProfile) -> tuple[ProbabilityRange | None, ProbabilityRange | None, ProbabilityRange | None]`.
- Produces: `joint_probability(event, eligibility, survival) -> ProbabilityRange`.
- Does not read the database or assign labels.

- [ ] **Step 1: Write failing interval arithmetic tests**

```python
import pytest

from app.opportunity.models import ProbabilityRange
from app.opportunity.probability import joint_probability


def test_joint_probability_multiplies_matching_scenarios():
    result = joint_probability(
        ProbabilityRange(low=0.60, base=0.70, high=0.80),
        ProbabilityRange(low=0.55, base=0.65, high=0.75),
        ProbabilityRange(low=0.70, base=0.80, high=0.90),
    )
    assert result.low == pytest.approx(0.231)
    assert result.base == pytest.approx(0.364)
    assert result.high == pytest.approx(0.54)
```

Add tests asserting:

- Explicit `event_probability` evidence is preserved.
- An official A-grade airdrop statement plus open participation can derive a bounded event range, but no official basis returns `None`.
- Unknown multiwallet policy never derives `P_survival`.
- Forbidden multiwallet policy derives `ProbabilityRange(low=0, base=0, high=0)`.

- [ ] **Step 2: Run tests and verify RED**

Run: `pytest tests/opportunity/test_probability.py -v`

Expected: fails because the probability module does not exist.

- [ ] **Step 3: Implement interval multiplication**

```python
def joint_probability(
    event: ProbabilityRange,
    eligibility: ProbabilityRange,
    survival: ProbabilityRange,
) -> ProbabilityRange:
    return ProbabilityRange(
        low=event.low * eligibility.low * survival.low,
        base=event.base * eligibility.base * survival.base,
        high=event.high * eligibility.high * survival.high,
    )
```

- [ ] **Step 4: Implement a bounded cold-start rule table**

Use only verified evidence. Manual explicit ranges take precedence. Otherwise derive conservative ranges from these exact combinations:

```python
EVENT_RULES = {
    "official_distribution_and_catalyst": ProbabilityRange(low=0.65, base=0.78, high=0.90),
    "official_distribution": ProbabilityRange(low=0.55, base=0.70, high=0.85),
    "official_points_value": ProbabilityRange(low=0.50, base=0.65, high=0.80),
}

ELIGIBILITY_RULES = {
    "deterministic_open_within_budget": ProbabilityRange(low=0.65, base=0.80, high=0.90),
    "points_open_within_budget": ProbabilityRange(low=0.50, base=0.67, high=0.82),
    "behavioral_open_within_budget": ProbabilityRange(low=0.40, base=0.58, high=0.75),
}

SURVIVAL_RULES = {
    "allowed": ProbabilityRange(low=0.75, base=0.88, high=0.95),
    "not_forbidden": ProbabilityRange(low=0.60, base=0.75, high=0.88),
    "forbidden": ProbabilityRange(low=0.0, base=0.0, high=0.0),
}
```

Do not derive eligibility if participation is closed, cost is unknown, or the recommended hard-cost base exceeds the profile limit. Do not derive event probability from `no_token_yet`, funding, task-portal presence, or narrative heat alone.

- [ ] **Step 5: Run probability tests**

Run: `pytest tests/opportunity/test_probability.py -v`

Expected: all tests pass.

- [ ] **Step 6: Commit Task 4**

```bash
git add backend/app/opportunity/probability.py backend/tests/opportunity/test_probability.py
git commit -m "feat(opportunity): calculate bounded reward probability"
```

---

### Task 5: Economics, Quality, and Confidence Calculators

**Files:**
- Create: `backend/app/opportunity/economics.py`
- Create: `backend/app/opportunity/quality.py`
- Create: `backend/tests/opportunity/test_economics.py`
- Create: `backend/tests/opportunity/test_quality.py`

**Interfaces:**
- Consumes: ranges and evidence from Tasks 1-4.
- Produces: `calculate_economics(*, reward_probability: ProbabilityRange, conditional_reward: MoneyRange, hard_cost: MoneyRange, capital_loss: MoneyRange, liquidity_cost: MoneyRange, total_time_hours: MoneyRange, capital_at_risk_base: float = 0.0) -> EconomicsResult`.
- Produces: `calculate_overall_confidence(confidence: ConfidenceSet) -> float`.
- Produces: `calculate_project_quality(factors: QualityFactors) -> float | None`.
- Pure functions only.

- [ ] **Step 1: Write failing economics tests**

```python
import pytest

from app.opportunity.economics import calculate_economics
from app.opportunity.models import MoneyRange, ProbabilityRange


def test_economics_uses_net_reward_and_conservative_decision_weights():
    result = calculate_economics(
        reward_probability=ProbabilityRange(low=0.25, base=0.365, high=0.51),
        conditional_reward=MoneyRange(low=40, base=160, high=500),
        hard_cost=MoneyRange(low=3, base=3, high=3),
        capital_loss=MoneyRange(low=0, base=0, high=0),
        liquidity_cost=MoneyRange(low=0, base=0, high=0),
        total_time_hours=MoneyRange(low=1, base=1.2, high=2),
    )
    assert result.net_reward.low == pytest.approx(7)
    assert result.net_reward.base == pytest.approx(55.4)
    assert result.net_reward.high == pytest.approx(252)
    assert result.decision_value == pytest.approx(50.86)
    assert result.time_efficiency == pytest.approx(50.86 / 1.2)
```

Add tests for zero hard cost using a safe minimum denominator of 1 USD, and for missing conditional reward returning `None` rather than zero.

- [ ] **Step 2: Write failing confidence and quality tests**

```python
import pytest

from app.opportunity.models import ConfidenceSet
from app.opportunity.quality import calculate_overall_confidence


def test_overall_confidence_penalizes_weakest_critical_domain():
    confidence = ConfidenceSet(
        event=0.8,
        eligibility=0.75,
        reward=0.4,
        cost=0.9,
        risk=0.8,
        quality=0.7,
    )
    expected_average = (0.8 + 0.75 + 0.4 + 0.9 + 0.8 + 0.7) / 6
    assert calculate_overall_confidence(confidence) == pytest.approx(
        0.3 * 0.4 + 0.7 * expected_average
    )
```

Add quality tests for the exact weighted dimensions `25/25/20/15/15`, and assert that any missing quality dimension returns `None` rather than filling 50.

- [ ] **Step 3: Run calculator tests and verify RED**

Run: `pytest tests/opportunity/test_economics.py tests/opportunity/test_quality.py -v`

Expected: fails because the modules do not exist.

- [ ] **Step 4: Implement economics without duplicate deductions**

```python
def calculate_economics(
    *,
    reward_probability: ProbabilityRange,
    conditional_reward: MoneyRange,
    hard_cost: MoneyRange,
    capital_loss: MoneyRange,
    liquidity_cost: MoneyRange,
    total_time_hours: MoneyRange,
    capital_at_risk_base: float = 0.0,
) -> EconomicsResult:
    gross = MoneyRange(
        low=reward_probability.low * conditional_reward.low,
        base=reward_probability.base * conditional_reward.base,
        high=reward_probability.high * conditional_reward.high,
    )
    net = SignedMoneyRange(
        low=gross.low - hard_cost.high - capital_loss.high - liquidity_cost.high,
        base=gross.base - hard_cost.base - capital_loss.base - liquidity_cost.base,
        high=gross.high - hard_cost.low - capital_loss.low - liquidity_cost.low,
    )
    decision_value = 0.5 * net.low + 0.4 * net.base + 0.1 * net.high
    reward_to_cost_ratio = gross.base / max(hard_cost.base, 1.0)
    capital_efficiency = decision_value / max(hard_cost.base + capital_at_risk_base, 1.0)
    time_efficiency = decision_value / max(total_time_hours.base, 0.25)
    return EconomicsResult(
        gross_reward=gross,
        net_reward=net,
        reward_to_cost_ratio=reward_to_cost_ratio,
        decision_value=decision_value,
        capital_efficiency=capital_efficiency,
        time_efficiency=time_efficiency,
    )
```

Use `SignedMoneyRange` for net result fields and retain non-negative `MoneyRange` for rewards and costs. Add a test where hard cost exceeds gross reward and assert a negative conservative net reward is retained, not clamped to zero.

Calculate `reward_to_cost_ratio = base_gross / max(hard_cost.base, 1.0)`, `capital_efficiency = decision_value / max(hard_cost.base + capital_at_risk_base, 1.0)`, and `time_efficiency = decision_value / max(total_time_hours.base, 0.25)`.

- [ ] **Step 5: Implement quality and confidence**

```python
QUALITY_WEIGHTS = {
    "product_demand": 0.25,
    "execution_growth": 0.25,
    "team_governance": 0.20,
    "financial_sustainability": 0.15,
    "security_transparency": 0.15,
}


def calculate_project_quality(factors: QualityFactors) -> float | None:
    values = factors.model_dump()
    if any(value is None for value in values.values()):
        return None
    return sum(values[key] * weight for key, weight in QUALITY_WEIGHTS.items())


def calculate_overall_confidence(value: ConfidenceSet) -> float:
    scores = [value.event, value.eligibility, value.reward, value.cost, value.risk, value.quality]
    return 0.3 * min(scores) + 0.7 * (sum(scores) / len(scores))
```

Domain confidence derives from source reliability 35%, coverage 25%, independence 15%, freshness/consistency 25%. Implement:

```python
def calculate_domain_confidence(
    *,
    source_reliability: float,
    evidence_coverage: float,
    source_independence: float,
    freshness_consistency: float,
) -> float:
    value = (
        0.35 * source_reliability
        + 0.25 * evidence_coverage
        + 0.15 * source_independence
        + 0.25 * freshness_consistency
    )
    return max(0.0, min(1.0, value))
```

After calculating all six domains, set `ConfidenceSet.overall` with `calculate_overall_confidence()` via `model_copy(update={"overall": value})`.

- [ ] **Step 6: Run calculator tests**

Run: `pytest tests/opportunity/test_economics.py tests/opportunity/test_quality.py -v`

Expected: all tests pass.

- [ ] **Step 7: Commit Task 5**

```bash
git add backend/app/opportunity/models.py backend/app/opportunity/economics.py backend/app/opportunity/quality.py backend/tests/opportunity/test_models.py backend/tests/opportunity/test_economics.py backend/tests/opportunity/test_quality.py
git commit -m "feat(opportunity): calculate conservative economics"
```

---

### Task 6: Hard Gates and Decision Engine

**Files:**
- Create: `backend/app/opportunity/decision.py`
- Create: `backend/tests/opportunity/test_decision.py`

**Interfaces:**
- Consumes: `OpportunityInputs`, component probabilities, joint probability, economics, quality, confidence, profile.
- Produces: `decide(*, inputs: OpportunityInputs, event: ProbabilityRange | None, eligibility: ProbabilityRange | None, survival: ProbabilityRange | None, reward_probability: ProbabilityRange | None, economics: EconomicsResult | None, profile: OpportunityProfile, now: datetime) -> DecisionResult`.
- Does not persist or mutate legacy scores.

- [ ] **Step 1: Write the decision-table tests first**

Create a factory for a fully passing input, then these tests:

```python
def test_complete_profitable_safe_project_is_actionable(passing_case):
    result = decide(**passing_case)
    assert result.status == DecisionStatus.ACTIONABLE
    assert result.public_label == "FARM"


@pytest.mark.parametrize(
    ("override", "code"),
    [
        ({"safety_blocked": True}, "SAFETY_BLOCK"),
        ({"integrity_blocked": True}, "INTEGRITY_BLOCK"),
        ({"official_multiwallet_policy": "forbidden"}, "RULE_BLOCK"),
    ],
)
def test_hard_blockers_cannot_be_compensated(passing_case, override, code):
    result = decide(**{**passing_case, **override})
    assert result.status == DecisionStatus.BLOCKED
    assert result.public_label == "IGNORE"
    assert code in result.blocker_codes


def test_missing_reward_evidence_is_watch_not_ignore(passing_case):
    result = decide(**{**passing_case, "conditional_reward": None})
    assert result.status == DecisionStatus.INSUFFICIENT_EVIDENCE
    assert result.public_label == "WATCH"
    assert "REWARD_TOO_UNCERTAIN" in result.watch_reason_codes


def test_optimistic_reward_cannot_rescue_negative_conservative_case(passing_case):
    economics = passing_case["economics"].model_copy(
        update={"net_reward": SignedMoneyRange(low=-2, base=10, high=1000)}
    )
    result = decide(**{**passing_case, "economics": economics})
    assert result.public_label != "FARM"
```

Add a parameterized test named `test_each_farm_threshold_prevents_actionable` with cases for event low, eligibility low, survival low, joint low, conservative net, base net, reward-to-cost ratio, hard cost, weekly maintenance, project quality, project-failure risk, overall confidence, and each domain confidence. Each case lowers exactly one field below its threshold and asserts the output is WATCH or IGNORE, never FARM. Add parameterized reason-code tests covering every code listed in the approved design.

- [ ] **Step 2: Run decision tests and verify RED**

Run: `pytest tests/opportunity/test_decision.py -v`

Expected: fails because `decision.py` does not exist.

- [ ] **Step 3: Implement blocker precedence**

Apply this exact order:

```python
if safety_blocked:
    return blocked("SAFETY_BLOCK")
if integrity_blocked:
    return blocked("INTEGRITY_BLOCK")
if official_multiwallet_policy == "forbidden":
    return blocked("RULE_BLOCK")
if critical_unknowns:
    return insufficient_evidence(map_unknowns_to_watch_codes(critical_unknowns))
```

Unknown identity with a suspicious/invalid official source maps to `SAFETY_BLOCK`; ordinary missing identity maps to `WAIT_MORE_EVIDENCE`.

- [ ] **Step 4: Implement FARM conjunction, not weighted compensation**

```python
farm_checks = (
    event.low >= 0.50,
    eligibility.low >= 0.50,
    survival.low >= 0.60,
    reward_probability.low >= 0.20,
    economics.net_reward.low > 0,
    economics.net_reward.base >= 30,
    economics.reward_to_cost_ratio >= 3,
    hard_cost.base <= profile.hard_cost_limit_per_wallet_usd,
    weekly_maintenance_hours <= profile.weekly_time_limit_hours,
    project_quality >= 50,
    project_failure_risk not in {RiskLevel.HIGH, RiskLevel.CRITICAL},
    confidence.overall >= 0.65,
    confidence.event >= 0.70,
    confidence.eligibility >= 0.65,
    confidence.reward >= 0.50,
    confidence.cost >= 0.70,
    confidence.risk >= 0.70,
)
```

FARM requires `all(farm_checks)`. Projects with plausible future value but remediable unmet conditions become `MONITOR/WATCH`. Structurally negative expected value, dust reward, permanently excessive cost/time, inactive project, or profile mismatch become `NOT_FIT/IGNORE`.

- [ ] **Step 5: Implement deterministic actions and review windows**

- `ACTIONABLE`: `"Run 1-2 wallets, record actual cost and time, then reassess before expanding."`, expiry 48 hours.
- `MONITOR`: action derived from the first watch reason, expiry 7 days.
- `INSUFFICIENT_EVIDENCE`: `"Collect the missing critical evidence before participating."`, expiry 7 days.
- `NOT_FIT`: `"Do not allocate time or funds under the current profile."`, expiry 30 days.
- `BLOCKED`: `"Do not interact until credible remediation evidence is verified."`, no automatic clearance; use a 30-day review marker only.

- [ ] **Step 6: Run decision tests**

Run: `pytest tests/opportunity/test_decision.py -v`

Expected: all tests pass.

- [ ] **Step 7: Commit Task 6**

```bash
git add backend/app/opportunity/decision.py backend/tests/opportunity/test_decision.py
git commit -m "feat(opportunity): enforce participation gates"
```

---

### Task 7: Opportunity Evaluation Service

**Files:**
- Create: `backend/app/opportunity/service.py`
- Create: `backend/tests/opportunity/test_service.py`

**Interfaces:**
- Consumes: `ProjectRepository.get_by_id`, `OpportunityRepository`, default profile, evidence adapter and pure calculators.
- Produces: `OpportunityService.evaluate(project_id, persist=True) -> OpportunityAssessment`.
- Produces: `OpportunityService.evaluate_row(row, persist=True) -> OpportunityAssessment` for pipeline integration.
- Guarantees no mutation of legacy project score/label.

- [ ] **Step 1: Write failing service integration tests**

Use an in-memory SQLite connection, seed a project with legacy `score=90,label='FARM'`, and test:

```python
def test_sparse_legacy_project_becomes_shadow_watch_without_mutating_legacy(conn):
    service = OpportunityService(project_repo=ProjectRepository(conn), opportunity_repo=OpportunityRepository(conn))
    assessment = service.evaluate("p1")
    assert assessment.model_version == "opportunity-v2.0"
    assert assessment.status == DecisionStatus.INSUFFICIENT_EVIDENCE
    assert assessment.public_label == "WATCH"
    row = conn.execute("SELECT score, label FROM projects WHERE id = 'p1'").fetchone()
    assert row["score"] == 90
    assert row["label"] == "FARM"
```

Add a complete verified-evidence test that produces `ACTIONABLE/FARM`, persists one assessment, includes every evidence ID, and sets expiry to 48 hours after scoring.

- [ ] **Step 2: Run service tests and verify RED**

Run: `pytest tests/opportunity/test_service.py -v`

Expected: fails because `OpportunityService` does not exist.

- [ ] **Step 3: Implement orchestration in one service**

```python
class OpportunityService:
    def evaluate(self, project_id: str, *, persist: bool = True) -> OpportunityAssessment:
        row = self.project_repo.get_by_id(project_id)
        if row is None:
            raise LookupError(project_id)
        return self.evaluate_row(row, persist=persist)

    def evaluate_row(self, row: dict[str, Any], *, persist: bool = True) -> OpportunityAssessment:
        evidence = self.opportunity_repo.list_evidence(row["id"])
        inputs = build_inputs(row, evidence, self.profile)
        event, eligibility, survival = derive_probability_inputs(inputs, evidence, self.profile)
        # If any probability is unavailable, decision receives critical unknowns.
        # Otherwise calculate joint probability and economics.
        # Calculate quality/confidence, then decide.
        # Construct one immutable assessment and optionally append it.
```

Catch no unexpected exceptions inside this service. API maps `LookupError` to 404; pipeline integration catches/logs failures so Shadow cannot break legacy scoring.

- [ ] **Step 4: Ensure assessment snapshots are complete**

The created assessment must include:

- Model and profile versions.
- All component ranges or explicit `None`.
- Joint probability and economics where calculable.
- All six domain confidences and overall confidence.
- All five risks.
- Internal status, public label, codes, action, scored/review/expiry timestamps.
- Sorted unique evidence IDs.
- A `factor_snapshot` JSON object containing only these normalized non-sensitive keys: `event_probability`, `eligibility_probability`, `survival_probability`, `conditional_reward_usd`, `hard_cost_usd`, `expected_capital_loss_usd`, `liquidity_cost_usd`, `total_time_hours`, `weekly_maintenance_hours`, `project_quality`, `risks`, `confidence`, `critical_unknowns`, and evidence counts. It must never include `source_url`, raw snapshots, wallet identifiers, notes, or free text.

- [ ] **Step 5: Run service tests and opportunity suite**

Run: `pytest tests/opportunity/test_service.py -v`

Expected: all tests pass.

Run: `pytest tests/opportunity -v`

Expected: all opportunity tests pass.

- [ ] **Step 6: Commit Task 7**

```bash
git add backend/app/opportunity/service.py backend/tests/opportunity/test_service.py
git commit -m "feat(opportunity): orchestrate shadow assessment"
```

---

### Task 8: Evidence and Assessment API

**Files:**
- Create: `backend/app/routers/v1/opportunity.py`
- Modify: `backend/app/main.py:82-93,172-207,246-270`
- Create: `backend/tests/api/test_opportunity.py`

**Interfaces:**
- Consumes: `OpportunityRepository`, `OpportunityService`, `SUPPORTED_FACTOR_KEYS`.
- Produces: `POST /api/v1/projects/{project_id}/opportunity/evidence`.
- Produces: `GET /api/v1/projects/{project_id}/opportunity/evidence`.
- Produces: `POST /api/v1/projects/{project_id}/opportunity/evaluate`.
- Produces: `GET /api/v1/projects/{project_id}/opportunity`.

- [ ] **Step 1: Write failing API tests**

```python
def test_sparse_project_evaluates_to_shadow_watch(client):
    response = client.post("/api/v1/projects/proj-1/opportunity/evaluate")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["model_version"] == "opportunity-v2.0"
    assert data["status"] == "INSUFFICIENT_EVIDENCE"
    assert data["public_label"] == "WATCH"


def test_add_evidence_rejects_unknown_factor(client):
    response = client.post(
        "/api/v1/projects/proj-1/opportunity/evidence",
        json={
            "factor_key": "magic_score",
            "value": 100,
            "value_type": "number",
            "observation_type": "observed",
            "source_url": "https://project.example/rules",
            "source_type": "official_docs",
            "source_grade": "A",
            "observed_at": "2026-07-14T00:00:00Z",
            "verification_status": "verified",
            "independence_group": "official-rules",
        },
    )
    assert response.status_code == 422
```

Add tests for 404 project, evidence round-trip, latest assessment retrieval, and GET before evaluation returning `data.assessment = None` rather than 404.

- [ ] **Step 2: Run API tests and verify RED**

Run: `pytest tests/api/test_opportunity.py -v`

Expected: endpoints return 404 because the router is absent.

- [ ] **Step 3: Implement request validation and endpoints**

Reuse `EvidenceRecord` fields in an `EvidenceCreate` model without `evidence_id/project_id`. Validate `factor_key`:

```python
@field_validator("factor_key")
@classmethod
def supported_factor(cls, value: str) -> str:
    if value not in SUPPORTED_FACTOR_KEYS:
        raise ValueError(f"unsupported opportunity factor: {value}")
    return value
```

Endpoint behavior:

- Evidence POST checks project existence, appends evidence, and returns 201.
- Evidence GET returns current and historical evidence ordered newest first.
- Evaluate POST runs and persists an assessment even when Shadow auto-run is disabled; this is an explicit user action.
- Assessment GET returns latest non-deleted snapshot and `stale = now >= expires_at`.
- All responses use `{ok: True, data: ...}`; use existing `HTTPException` envelope for errors.

- [ ] **Step 4: Register router and capability health fields**

Add `opportunity` to router imports and:

```python
app.include_router(opportunity.router, prefix="/api/v1", tags=["v1"])
```

Add health response fields:

```python
"opportunity_model_version": "opportunity-v2.0",
"opportunity_shadow_enabled": settings.opportunity_shadow_enabled,
```

Do not describe v2 as replacing legacy labels in OpenAPI.

- [ ] **Step 5: Run API and OpenAPI tests**

Run: `pytest tests/api/test_opportunity.py tests/api/test_openapi.py -v`

Expected: all tests pass.

- [ ] **Step 6: Commit Task 8**

```bash
git add backend/app/routers/v1/opportunity.py backend/app/main.py backend/tests/api/test_opportunity.py
git commit -m "feat(api): expose shadow opportunity assessments"
```

---

### Task 9: Feature-Flagged Pipeline Shadow Integration

**Files:**
- Modify: `backend/app/config.py:177-183`
- Modify: `backend/app/pipeline_run.py:119-158`
- Modify: `.env.example`
- Modify: `backend/tests/test_pipeline_run.py`

**Interfaces:**
- Consumes: `settings.opportunity_shadow_enabled`, successful legacy states, `OpportunityService.evaluate(project_id)`.
- Produces: best-effort append-only Shadow assessments after legacy persistence.
- Does not affect project success, raw-project processing, existing response scores, or labels.

- [ ] **Step 1: Write failing disabled/enabled integration tests**

Add tests using monkeypatch and an async pipeline stub:

```python
def test_shadow_disabled_does_not_call_service(monkeypatch):
    monkeypatch.setattr(settings, "opportunity_shadow_enabled", False)
    service = Mock()
    run_opportunity_shadow([successful_state], service=service)
    service.evaluate.assert_not_called()


def test_shadow_failure_does_not_change_legacy_state(monkeypatch):
    monkeypatch.setattr(settings, "opportunity_shadow_enabled", True)
    service = Mock()
    service.evaluate.side_effect = RuntimeError("shadow failed")
    state = SimpleNamespace(project=SimpleNamespace(id="p1"), score=75, label="FARM")
    result = run_opportunity_shadow([state], service=service)
    assert result == {"attempted": 1, "saved": 0, "failed": 1}
    assert state.score == 75
    assert state.label == "FARM"
```

Add a test that states with `score is None` are skipped.

- [ ] **Step 2: Run tests and verify RED**

Run: `pytest tests/test_pipeline_run.py -v`

Expected: fails because setting/helper do not exist.

- [ ] **Step 3: Add the feature flag**

```python
opportunity_shadow_enabled: bool = False
```

Document in `.env.example` without secrets:

```dotenv
# Opportunity v2.0 shadow assessment; does not replace legacy labels
OPPORTUNITY_SHADOW_ENABLED=false
```

- [ ] **Step 4: Implement best-effort helper and invoke after legacy save**

```python
def run_opportunity_shadow(states, service=None) -> dict[str, int]:
    stats = {"attempted": 0, "saved": 0, "failed": 0}
    if not settings.opportunity_shadow_enabled:
        return stats
    service = service or OpportunityService()
    for state in states:
        if getattr(state, "score", None) is None:
            continue
        stats["attempted"] += 1
        try:
            service.evaluate(state.project.id, persist=True)
            stats["saved"] += 1
        except Exception as exc:
            stats["failed"] += 1
            logger.warning(
                "opportunity.shadow_failed",
                project_id=state.project.id,
                error=str(exc),
            )
    return stats
```

Call it only after `run_orchestrator()` returns and legacy project rows have been saved. Include Shadow counts in logs and `/run` response under `opportunity_shadow`; do not include assessment labels in `top_projects` yet.

- [ ] **Step 5: Run affected tests**

Run: `pytest tests/test_pipeline_run.py tests/api/test_run.py tests/api/test_opportunity.py -v`

Expected: all tests pass.

- [ ] **Step 6: Commit Task 9**

```bash
git add backend/app/config.py backend/app/pipeline_run.py backend/tests/test_pipeline_run.py .env.example
git commit -m "feat(opportunity): run optional shadow evaluations"
```

---

### Task 10: Outcome Capture for Future Calibration

**Files:**
- Modify: `backend/app/db.py` opportunity-compatible interaction columns
- Modify: `backend/app/routers/v1/interactions.py:21-57,91-137,249-279`
- Modify: `backend/tests/test_interactions.py`

**Interfaces:**
- Consumes: existing interaction API.
- Produces: anonymized cohort outcomes tied to model/profile/prediction snapshots.
- Does not store wallet addresses, private keys, device identity, or KYC data.

- [ ] **Step 1: Write failing outcome-capture API test**

```python
def test_interaction_records_shadow_prediction_and_realized_outcome(client):
    created = client.post(
        "/api/v1/interactions",
        json={
            "project_id": "proj-1",
            "wallet_cohort_id": "cohort-123e4567-e89b-12d3-a456-426614174000",
            "wallet_count": 2,
            "status": "active",
            "actual_hard_cost_usd": 4.5,
            "actual_time_minutes": 80,
            "opportunity_model_version": "opportunity-v2.0",
            "opportunity_profile_version": "low-cost-curated-multiwallet-v1",
        },
    )
    assert created.status_code == 200
    iid = created.json()["data"]["id"]
    updated = client.patch(
        f"/api/v1/interactions/{iid}",
        json={
            "status": "done",
            "eligibility_result": "eligible",
            "survival_result": "passed",
            "reward_received_usd": 120,
            "claim_cost_usd": 1.5,
        },
    )
    assert updated.json()["data"]["realized_net_usd"] == 114
```

- [ ] **Step 2: Run test and verify RED**

Run: `pytest tests/test_interactions.py -v`

Expected: API rejects the new fields or response lacks realized net value.

- [ ] **Step 3: Add idempotent interaction columns**

Use `_add_column_if_not_exists()` for both backends:

```text
wallet_cohort_id TEXT
wallet_count INTEGER DEFAULT 1
actual_hard_cost_usd REAL/DOUBLE PRECISION
actual_time_minutes INTEGER
eligibility_result TEXT
survival_result TEXT
disqualification_reason TEXT
reward_received_usd REAL/DOUBLE PRECISION
claim_cost_usd REAL/DOUBLE PRECISION
opportunity_assessment_id TEXT
opportunity_model_version TEXT
opportunity_profile_version TEXT
outcome_observed_at TIMESTAMP
```

Do not remove the existing `cost_usd`, `profit_usd`, or `hours_spent` fields; they remain backward compatible for shipped records.

- [ ] **Step 4: Extend request models and serialization**

Use literals:

```python
EligibilityResult = Literal["unknown", "eligible", "ineligible"]
SurvivalResult = Literal["unknown", "passed", "disqualified"]
```

Calculate response-only:

```python
realized_net_usd = (
    float(reward_received_usd or 0)
    - float(actual_hard_cost_usd or 0)
    - float(claim_cost_usd or 0)
)
```

If `survival_result == "disqualified"`, require non-empty `disqualification_reason` in a model validator. Limit `wallet_cohort_id` to 100 characters and document that it is an anonymous local identifier.

- [ ] **Step 5: Run interaction tests**

Run: `pytest tests/test_interactions.py -v`

Expected: all tests pass, including existing CRUD behavior.

- [ ] **Step 6: Commit Task 10**

```bash
git add backend/app/db.py backend/app/routers/v1/interactions.py backend/tests/test_interactions.py
git commit -m "feat(opportunity): capture realized cohort outcomes"
```

---

### Task 11: Documentation, Cross-Backend Verification, and Regression Gate

**Files:**
- Modify: `docs/API_SPEC.md`
- Modify: `docs/DATABASE_DDL.md`
- Modify: `docs/IMPLEMENTATION_STATUS.md`
- Modify: `.workbuddy/memory/MEMORY.md`
- Create: `backend/scripts/verify_opportunity_shadow.py`
- Create: `backend/tests/scripts/test_verify_opportunity_shadow.py`

**Interfaces:**
- Consumes: completed Shadow API, SQLite/PostgreSQL repository, service.
- Produces: deterministic smoke verification with no network calls.
- Produces: current documentation and memory state.

- [ ] **Step 1: Write failing smoke-script test**

```python
def test_verify_shadow_smoke_returns_watch_for_sparse_project(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "shadow.db"))
    result = run_verification()
    assert result["model_version"] == "opportunity-v2.0"
    assert result["sparse_status"] == "INSUFFICIENT_EVIDENCE"
    assert result["legacy_label_unchanged"] is True
    assert result["assessment_count"] >= 1
```

- [ ] **Step 2: Run test and verify RED**

Run: `pytest tests/scripts/test_verify_opportunity_shadow.py -v`

Expected: fails because script does not exist.

- [ ] **Step 3: Implement network-free verification script**

`run_verification()` must:

1. Call `init_db()`.
2. Insert a deterministic project with legacy score/label.
3. Run sparse Shadow evaluation and assert WATCH/insufficient evidence.
4. Append complete synthetic A-grade evidence using `https://example.invalid/...` URLs.
5. Run a second assessment and verify immutable snapshot count is 2.
6. Verify legacy score/label are unchanged.
7. Return only booleans/counts/versions; never print secrets or environment values.

CLI output ends with `RESULT: PASS` on success and exits non-zero on assertion failure.

- [ ] **Step 4: Document exact API and database contracts**

Update `API_SPEC.md` with all four endpoints, request examples, internal status/public label distinction, and explicit Shadow behavior. Update `DATABASE_DDL.md` with both new tables and interaction columns. Update `IMPLEMENTATION_STATUS.md` to mark Opportunity v2.0 as Shadow only, not the primary label source. Update memory with:

- Model/profile versions.
- Feature flag default off.
- Existing labels remain authoritative.
- Sparse legacy inputs return WATCH/insufficient evidence.
- Next plans: live dilution/valuation inputs, frontend action workflow, calibration.

- [ ] **Step 5: Run focused and full backend verification**

Run from `backend/`:

```bash
pytest tests/opportunity tests/api/test_opportunity.py tests/test_pipeline_run.py tests/test_interactions.py tests/scripts/test_verify_opportunity_shadow.py -v
```

Expected: all selected tests pass.

Run:

```bash
python scripts/verify_opportunity_shadow.py
```

Expected: final line `RESULT: PASS`.

Run:

```bash
ruff check app tests scripts
```

Expected: exit 0 with no lint errors.

Run:

```bash
pytest
```

Expected: full backend suite passes with no new failures.

If test PostgreSQL on port 5433 is available, run with `DATABASE_URL` set by the user/environment, not read from `.env`:

```bash
python scripts/verify_opportunity_shadow.py
```

Expected: `RESULT: PASS` and `db_backend=postgres` in the non-sensitive summary. If PostgreSQL is unavailable, report that cross-backend runtime verification was not run; DDL unit coverage is not a substitute for this claim.

- [ ] **Step 6: Inspect only intended diff**

Run:

```bash
git diff --check -- backend/app/opportunity backend/app/routers/v1/opportunity.py backend/app/config.py backend/app/db.py backend/app/main.py backend/app/pipeline_run.py backend/app/routers/v1/interactions.py backend/tests/opportunity backend/tests/api/test_opportunity.py backend/tests/test_pipeline_run.py backend/tests/test_interactions.py backend/scripts/verify_opportunity_shadow.py backend/tests/scripts/test_verify_opportunity_shadow.py docs/API_SPEC.md docs/DATABASE_DDL.md docs/IMPLEMENTATION_STATUS.md .workbuddy/memory/MEMORY.md .env.example
```

Expected: no whitespace errors. Do not revert or stage unrelated dirty-worktree files.

- [ ] **Step 7: Commit Task 11**

```bash
git add backend/scripts/verify_opportunity_shadow.py backend/tests/scripts/test_verify_opportunity_shadow.py docs/API_SPEC.md docs/DATABASE_DDL.md docs/IMPLEMENTATION_STATUS.md .workbuddy/memory/MEMORY.md
git commit -m "docs(opportunity): document shadow scoring model"
```

## Follow-Up Plans

After the Shadow MVP has enough coverage data, create separate implementation plans in this order:

1. **Opportunity data acquisition:** qualified-wallet estimates, participation growth, points distribution, market/Tokenomics comparables, and evidence freshness jobs.
2. **Next.js opportunity UI:** six-dimensional assessment, blocker banners, WATCH upgrade conditions, evidence provenance, and 1-2-wallet validation workflow.
3. **Calibration pipeline:** immutable prediction/outcome joins, project-clustered samples, Brier/ECE, interval coverage, negative-return rate, and Shadow promotion gates.
4. **Primary-model migration:** only after calibration and manual review; promote `opportunity-v2.0` while retaining `score-v1.4` as Project Quality context and rollback support.
