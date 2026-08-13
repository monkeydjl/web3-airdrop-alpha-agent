"""Pure deterministic tests for Opportunity Action Workflow projection."""

from __future__ import annotations

import inspect
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from app.opportunity.models import (
    ConfidenceSet,
    DecisionStatus,
    EconomicsResult,
    EvidenceRecord,
    MoneyRange,
    OpportunityAssessment,
    ProbabilityRange,
    RiskLevel,
    RiskSet,
    SignedMoneyRange,
)

NOW = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)

# Pre-Task-8 / Task 6 offline surface must never appear on the workflow projection.
# Note: opportunity.economics (EconomicsResult) is a pre-existing assessment field and is allowed.
FORBIDDEN_ECONOMIC_WORKFLOW_KEYS = frozenset(
    {
        "economic_proxy",
        "economics_data_mode",
        "EconomicProxyProjection",
        "project_economics_data",
    }
)
BASELINE_WORKFLOW_PROJECTION_FIELDS = (
    "workflow_version",
    "project_id",
    "legacy",
    "opportunity",
    "workflow",
    "evidence",
    "validation",
    "review_at",
    "expires_at",
)
BASELINE_BUILDER_PARAMS = (
    "project",
    "assessment",
    "evidence",
    "participation_tasks",
    "interactions",
    "now",
)


def _canonical_json_bytes(payload: Any) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def _collect_keys(value: Any) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        for key, nested in value.items():
            keys.add(str(key))
            keys |= _collect_keys(nested)
    elif isinstance(value, (list, tuple)):
        for item in value:
            keys |= _collect_keys(item)
    return keys


def _assert_no_forbidden_economic_surface(payload: Any, *, require_json_blob: bool = True) -> None:
    keys = _collect_keys(payload)
    leaked = keys & FORBIDDEN_ECONOMIC_WORKFLOW_KEYS
    assert not leaked, f"forbidden economic keys on workflow surface: {sorted(leaked)}"
    assert "raw_snapshot_ref" not in keys
    if not require_json_blob:
        return
    # String-token defense for accidental serialization of private Task 6 names.
    blob = json.dumps(payload, ensure_ascii=False)
    for token in ("economic_proxy", "economics_data_mode", "raw_snapshot_ref"):
        assert token not in blob


def _confidence(**overrides: Any) -> ConfidenceSet:
    data = {
        "event": 0.8,
        "eligibility": 0.75,
        "reward": 0.7,
        "cost": 0.85,
        "risk": 0.8,
        "quality": 0.7,
        "overall": 0.76,
    }
    data.update(overrides)
    return ConfidenceSet(**data)


def _risks(**overrides: Any) -> RiskSet:
    data = {
        "capital_security": RiskLevel.LOW,
        "eligibility": RiskLevel.MEDIUM,
        "project_failure": RiskLevel.LOW,
        "reward_dilution": RiskLevel.MEDIUM,
        "liquidity": RiskLevel.LOW,
    }
    data.update(overrides)
    return RiskSet(**data)


def _economics(**overrides: Any) -> EconomicsResult:
    data = {
        "gross_reward": MoneyRange(low=50, base=100, high=200),
        "net_reward": SignedMoneyRange(low=20, base=60, high=180),
        "reward_to_cost_ratio": 8.0,
        "decision_value": 48.0,
        "capital_efficiency": 4.8,
        "time_efficiency": 24.0,
    }
    data.update(overrides)
    return EconomicsResult(**data)


def _project(**overrides: Any) -> dict[str, Any]:
    data = {
        "id": "proj-alpha",
        "name": "Alpha Protocol",
        "score": 88,
        "label": "FARM",
        "reason": ["strong testnet traction", "clear multiwallet policy"],
        "url": "https://alpha.example",
        "stage": "testnet",
    }
    data.update(overrides)
    return data


def _assessment(**overrides: Any) -> OpportunityAssessment:
    scored_at = overrides.pop("scored_at", NOW - timedelta(hours=6))
    review_at = overrides.pop("review_at", NOW + timedelta(hours=18))
    expires_at = overrides.pop("expires_at", NOW + timedelta(hours=42))
    data = {
        "assessment_id": "assess-1",
        "project_id": "proj-alpha",
        "model_version": "opportunity-v2.0",
        "profile_version": "low-cost-curated-multiwallet-v1",
        "event_probability": ProbabilityRange(low=0.6, base=0.7, high=0.8),
        "eligibility_probability": ProbabilityRange(low=0.55, base=0.65, high=0.75),
        "survival_probability": ProbabilityRange(low=0.7, base=0.8, high=0.9),
        "reward_probability": ProbabilityRange(low=0.3, base=0.4, high=0.5),
        "conditional_reward_usd": MoneyRange(low=40, base=80, high=160),
        "hard_cost_usd": MoneyRange(low=2, base=4, high=6),
        "economics": _economics(),
        "risks": _risks(),
        "confidence": _confidence(),
        "status": DecisionStatus.ACTIONABLE,
        "public_label": "FARM",
        "blocker_codes": (),
        "watch_reason_codes": (),
        "ignore_reason_codes": (),
        "requires_remediation": False,
        "recommended_action": "Run 1-2 wallets, record actual cost and time, then reassess.",
        "evidence_ids": ("ev-2", "ev-1"),
        "factor_snapshot": {"critical_unknowns": ()},
        "scored_at": scored_at,
        "review_at": review_at,
        "expires_at": expires_at,
    }
    data.update(overrides)
    return OpportunityAssessment(**data)


def _evidence(**overrides: Any) -> EvidenceRecord:
    data = {
        "evidence_id": "ev-1",
        "project_id": "proj-alpha",
        "factor_key": "participation_open",
        "value": True,
        "value_type": "bool",
        "observation_type": "observed",
        "source_url": "https://docs.alpha.example/tasks",
        "source_type": "official_docs",
        "source_grade": "A",
        "observed_at": NOW - timedelta(days=2),
        "expires_at": NOW + timedelta(days=10),
        "verification_status": "verified",
        "independence_group": "official",
        "raw_snapshot_ref": "s3://private/raw/ev-1",
    }
    data.update(overrides)
    return EvidenceRecord(**data)


def _task(
    task_id: str,
    *,
    priority: int,
    required: bool = False,
    category: str = "official",
    link: str | None = "https://alpha.example/tasks",
) -> dict[str, Any]:
    return {
        "id": task_id,
        "category": category,
        "title": f"Title {task_id}",
        "description": f"Description {task_id}",
        "priority": priority,
        "required": required,
        "link": link,
        "why": f"Why {task_id}",
        "action_hint": f"Hint {task_id}",
    }


def _interaction(
    interaction_id: str,
    *,
    status: str,
    created_at: datetime,
    assessment_id: str = "assess-1",
    **overrides: Any,
) -> dict[str, Any]:
    data = {
        "id": interaction_id,
        "project_id": "proj-alpha",
        "status": status,
        "created_at": created_at.isoformat(),
        "wallet_count": 1,
        "wallet_cohort_id": "cohort-aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
        "opportunity_assessment_id": assessment_id,
        "opportunity_model_version": "opportunity-v2.0",
        "opportunity_profile_version": "low-cost-curated-multiwallet-v1",
        "actual_hard_cost_usd": None,
        "actual_time_minutes": None,
        "eligibility_result": "unknown",
        "survival_result": "unknown",
        "disqualification_reason": None,
        "reward_received_usd": None,
        "claim_cost_usd": None,
        "outcome_observed_at": None,
        "notes": "private operator note",
    }
    data.update(overrides)
    return data


def _build(**overrides: Any):
    from app.opportunity.workflow import build_workflow_projection

    values = {
        "project": _project(),
        "assessment": _assessment(),
        "evidence": [
            _evidence(
                evidence_id="ev-old",
                observed_at=NOW - timedelta(days=5),
                source_grade="B",
            ),
            _evidence(
                evidence_id="ev-new",
                observed_at=NOW - timedelta(days=1),
                factor_key="task_path_known",
                source_grade="A",
            ),
        ],
        "participation_tasks": [
            _task("official-task-portal", priority=2, required=True),
            _task("research-official-site", priority=1, required=True, category="research"),
        ],
        "interactions": [],
        "now": NOW,
    }
    values.update(overrides)
    return build_workflow_projection(**values)


def test_module_exports_contract_symbols():
    from app.opportunity import workflow

    assert workflow.WORKFLOW_VERSION == "opportunity-action-workflow-v1"
    assert workflow.LEGACY_MODEL_VERSION == "score-v1.4"
    assert workflow.ALLOWED_TRANSITIONS == {
        "planned": ("active", "abandoned"),
        "active": ("done", "abandoned"),
        "done": (),
        "abandoned": (),
    }
    assert callable(workflow.build_workflow_projection)


@pytest.mark.parametrize(
    ("assessment", "now", "expected_state"),
    [
        (None, NOW, "NEEDS_EVALUATION"),
        (
            _assessment(review_at=NOW, expires_at=NOW + timedelta(hours=1)),
            NOW,
            "REVIEW_REQUIRED",
        ),
        (
            _assessment(review_at=NOW + timedelta(hours=1), expires_at=NOW),
            NOW,
            "REVIEW_REQUIRED",
        ),
        (
            _assessment(status=DecisionStatus.ACTIONABLE, public_label="FARM"),
            NOW,
            "ACTIONABLE",
        ),
        (
            _assessment(
                status=DecisionStatus.MONITOR,
                public_label="WATCH",
                recommended_action="Wait for official participation to open.",
                watch_reason_codes=("WAIT_TASK_OPEN",),
            ),
            NOW,
            "MONITOR",
        ),
        (
            _assessment(
                status=DecisionStatus.INSUFFICIENT_EVIDENCE,
                public_label="WATCH",
                recommended_action="Collect the missing critical evidence before participating.",
                factor_snapshot={"critical_unknowns": ("multiwallet_policy", "hard_cost")},
            ),
            NOW,
            "INSUFFICIENT_EVIDENCE",
        ),
        (
            _assessment(
                status=DecisionStatus.BLOCKED,
                public_label="IGNORE",
                requires_remediation=True,
                blocker_codes=("SAFETY_BLOCK",),
                recommended_action="Do not interact until credible remediation evidence is verified.",
            ),
            NOW,
            "BLOCKED",
        ),
        (
            _assessment(
                status=DecisionStatus.NOT_FIT,
                public_label="IGNORE",
                ignore_reason_codes=("NEGATIVE_EXPECTED_VALUE",),
                recommended_action="Do not allocate time or funds under the current profile.",
            ),
            NOW,
            "NOT_FIT",
        ),
    ],
)
def test_state_matrix_precedence(assessment, now, expected_state):
    projection = _build(assessment=assessment, now=now)
    assert projection.workflow.state == expected_state
    assert projection.workflow_version == "opportunity-action-workflow-v1"
    assert projection.project_id == "proj-alpha"


def test_legacy_authority_and_shadow_opportunity_untouched():
    projection = _build()
    assert projection.legacy.model_version == "score-v1.4"
    assert projection.legacy.score == 88
    assert projection.legacy.label == "FARM"
    assert list(projection.legacy.reason) == [
        "strong testnet traction",
        "clear multiwallet policy",
    ]
    assert projection.legacy.authoritative is True

    assert projection.opportunity is not None
    assert projection.opportunity.shadow is True
    assert projection.opportunity.model_version == "opportunity-v2.0"
    assert projection.opportunity.profile_version == "low-cost-curated-multiwallet-v1"
    assert projection.opportunity.assessment_id == "assess-1"
    assert projection.opportunity.status == DecisionStatus.ACTIONABLE
    assert projection.opportunity.public_label == "FARM"
    assert projection.opportunity.recommended_action.startswith("Run 1-2 wallets")
    assert projection.review_at == NOW + timedelta(hours=18)
    assert projection.expires_at == NOW + timedelta(hours=42)


def test_no_assessment_keeps_legacy_and_null_opportunity():
    projection = _build(assessment=None)
    assert projection.opportunity is None
    assert projection.workflow.state == "NEEDS_EVALUATION"
    assert projection.workflow.blockers == ()
    assert projection.workflow.upgrade_conditions == ()
    assert projection.legacy.authoritative is True
    assert projection.legacy.score == 88
    assert projection.review_at is None
    assert projection.expires_at is None


def test_repeated_calls_with_same_now_serialize_identically():
    first = _build()
    second = _build()
    assert first.model_dump(mode="json") == second.model_dump(mode="json")


def test_exactly_one_next_action_and_validation_start_only_for_actionable():
    for status, public_label, requires_remediation, extra in [
        (DecisionStatus.ACTIONABLE, "FARM", False, {}),
        (
            DecisionStatus.MONITOR,
            "WATCH",
            False,
            {"watch_reason_codes": ("WAIT_TASK_OPEN",)},
        ),
        (
            DecisionStatus.INSUFFICIENT_EVIDENCE,
            "WATCH",
            False,
            {"factor_snapshot": {"critical_unknowns": ("hard_cost",)}},
        ),
        (
            DecisionStatus.BLOCKED,
            "IGNORE",
            True,
            {"blocker_codes": ("SAFETY_BLOCK",)},
        ),
        (
            DecisionStatus.NOT_FIT,
            "IGNORE",
            False,
            {"ignore_reason_codes": ("TOO_EXPENSIVE",)},
        ),
    ]:
        projection = _build(
            assessment=_assessment(
                status=status,
                public_label=public_label,
                requires_remediation=requires_remediation,
                **extra,
            )
        )
        assert projection.workflow.next_action is not None
        assert isinstance(projection.workflow.next_action.key, str)
        assert projection.workflow.next_action.key
        assert projection.workflow.next_action.label
        if status == DecisionStatus.ACTIONABLE:
            assert projection.validation.can_start_validation is True
            assert projection.workflow.next_action.can_start_validation is True
        else:
            assert projection.validation.can_start_validation is False
            assert projection.workflow.next_action.can_start_validation is False

    needs = _build(assessment=None)
    assert needs.validation.can_start_validation is False
    assert needs.workflow.next_action.key == "evaluate"
    assert needs.workflow.next_action.label == "运行 Opportunity 评估"

    review = _build(
        assessment=_assessment(review_at=NOW - timedelta(minutes=1)),
        now=NOW,
    )
    assert review.validation.can_start_validation is False
    assert review.workflow.next_action.key == "re_evaluate"
    assert review.workflow.next_action.label == "重新评估"


def test_actionable_next_action_start_vs_continue():
    start = _build(interactions=[])
    assert start.workflow.next_action.key == "start_validation"
    assert start.workflow.next_action.label == "开始验证"

    cont = _build(interactions=[_interaction("ix-open", status="planned", created_at=NOW - timedelta(hours=1))])
    assert cont.workflow.next_action.key == "continue_validation"
    assert cont.workflow.next_action.label == "继续验证"
    assert cont.validation.can_start_validation is True


def test_missing_factor_keys_sorted_from_critical_unknowns():
    projection = _build(
        assessment=_assessment(
            status=DecisionStatus.INSUFFICIENT_EVIDENCE,
            public_label="WATCH",
            factor_snapshot={"critical_unknowns": ("hard_cost", "multiwallet_policy", "airdrop_basis")},
        )
    )
    assert projection.evidence.missing_factor_keys == (
        "airdrop_basis",
        "hard_cost",
        "multiwallet_policy",
    )


def test_evidence_ordering_freshness_age_and_grade_counts():
    expired = _evidence(
        evidence_id="ev-expired",
        observed_at=NOW - timedelta(days=3, hours=2),
        expires_at=NOW - timedelta(hours=1),
        source_grade="C",
        verification_status="invalidated",
        raw_snapshot_ref="s3://secret/expired",
    )
    current = _evidence(
        evidence_id="ev-current",
        observed_at=NOW - timedelta(days=1),
        expires_at=NOW + timedelta(days=2),
        source_grade="A",
        factor_key="safety_blocked",
        value=False,
    )
    same_time_lower_id = _evidence(
        evidence_id="ev-a",
        observed_at=NOW - timedelta(days=1),
        source_grade="B",
        factor_key="integrity_blocked",
        value=False,
    )
    same_time_higher_id = _evidence(
        evidence_id="ev-z",
        observed_at=NOW - timedelta(days=1),
        source_grade="U",
        factor_key="project_active",
        value=True,
    )
    projection = _build(
        evidence=[expired, current, same_time_lower_id, same_time_higher_id],
    )
    ids = [item.evidence_id for item in projection.evidence.items]
    assert ids == ["ev-z", "ev-current", "ev-a", "ev-expired"]

    by_id = {item.evidence_id: item for item in projection.evidence.items}
    assert by_id["ev-expired"].freshness == "EXPIRED"
    assert by_id["ev-current"].freshness == "CURRENT"
    assert by_id["ev-expired"].verification_status == "invalidated"
    assert by_id["ev-expired"].age_days >= 3
    assert all(item.age_days >= 0 for item in projection.evidence.items)

    payload = projection.model_dump(mode="json")
    for item in payload["evidence"]["items"]:
        assert "raw_snapshot_ref" not in item
        assert "notes" not in item

    assert projection.evidence.counts_by_grade == {
        "A": 1,
        "B": 1,
        "C": 1,
        "D": 0,
        "U": 1,
    }


def test_action_plan_sorts_by_phase_priority_required_and_id():
    projection = _build(
        assessment=_assessment(
            status=DecisionStatus.ACTIONABLE,
            public_label="FARM",
            factor_snapshot={"critical_unknowns": ("multiwallet_policy",)},
        ),
        participation_tasks=[
            _task("z-optional", priority=1, required=False, category="official"),
            _task("a-required", priority=1, required=True, category="official"),
            _task("research-docs", priority=2, required=True, category="research"),
            _task("track-log", priority=1, required=False, category="track"),
        ],
    )
    plan = list(projection.workflow.action_plan)
    assert plan, "expected a non-empty action plan for actionable assessment"
    phases = [item.phase for item in plan]
    phase_rank = {"review": 0, "evidence": 1, "validation": 2, "maintenance": 3, "outcome": 4}
    assert phases == sorted(phases, key=lambda phase: phase_rank[phase])

    # Within the same phase, priority asc, required first, then stable id.
    for index in range(len(plan) - 1):
        left, right = plan[index], plan[index + 1]
        if left.phase != right.phase:
            continue
        left_key = (left.priority, 0 if left.required else 1, left.id)
        right_key = (right.priority, 0 if right.required else 1, right.id)
        assert left_key <= right_key

    assert [item.sequence for item in plan] == list(range(1, len(plan) + 1))
    assert all(item.external_url is None or item.external_url.startswith(("http://", "https://")) for item in plan)


def test_blockers_and_upgrade_conditions_are_stable_and_sorted():
    projection = _build(
        assessment=_assessment(
            status=DecisionStatus.BLOCKED,
            public_label="IGNORE",
            requires_remediation=True,
            blocker_codes=("RULE_BLOCK", "SAFETY_BLOCK"),
            watch_reason_codes=("WAIT_MORE_EVIDENCE",),
            recommended_action="Do not interact until credible remediation evidence is verified.",
            factor_snapshot={"critical_unknowns": ("safety_blocked", "integrity_blocked")},
        )
    )
    assert [item.code for item in projection.workflow.blockers] == ["RULE_BLOCK", "SAFETY_BLOCK"]
    assert all(item.severity and item.message for item in projection.workflow.blockers)

    codes = [item.code for item in projection.workflow.upgrade_conditions]
    assert codes == sorted(codes)
    assert codes
    assert all(item.message for item in projection.workflow.upgrade_conditions)


def test_validation_current_selection_and_history_counts():
    linked = [
        _interaction("ix-old-open", status="planned", created_at=NOW - timedelta(hours=5)),
        _interaction("ix-new-open", status="active", created_at=NOW - timedelta(hours=1)),
        _interaction("ix-done", status="done", created_at=NOW - timedelta(hours=2)),
        _interaction(
            "ix-other-assessment",
            status="active",
            created_at=NOW - timedelta(minutes=10),
            assessment_id="assess-other",
        ),
    ]
    projection = _build(interactions=linked)
    assert projection.validation.current is not None
    assert projection.validation.current["id"] == "ix-new-open"
    assert projection.validation.history_summary.total == 3
    assert projection.validation.history_summary.by_status == {
        "planned": 1,
        "active": 1,
        "done": 1,
        "abandoned": 0,
    }
    assert projection.validation.allowed_transitions == {
        "planned": ["active", "abandoned"],
        "active": ["done", "abandoned"],
        "done": [],
        "abandoned": [],
    }
    # Privacy-safe validation payload: outcome fields present, notes excluded.
    current = projection.validation.current
    for field in (
        "actual_hard_cost_usd",
        "actual_time_minutes",
        "eligibility_result",
        "survival_result",
        "reward_received_usd",
        "claim_cost_usd",
        "outcome_observed_at",
    ):
        assert field in current
    assert "notes" not in current

    # Fall back to newest terminal when no open interaction exists.
    # Same created_at: id DESC picks ix-z over ix-a.
    terminal_only = _build(
        interactions=[
            _interaction("ix-a", status="done", created_at=NOW - timedelta(hours=1)),
            _interaction("ix-z", status="abandoned", created_at=NOW - timedelta(hours=1)),
            _interaction("ix-old", status="done", created_at=NOW - timedelta(hours=5)),
        ]
    )
    assert terminal_only.validation.current["id"] == "ix-z"


def test_builder_is_pure_and_does_not_mutate_inputs():
    project = _project()
    assessment = _assessment(
        status=DecisionStatus.MONITOR,
        public_label="WATCH",
        watch_reason_codes=("WAIT_RULES",),
        factor_snapshot={"critical_unknowns": ("multiwallet_policy",)},
    )
    evidence = [
        _evidence(evidence_id="ev-1", raw_snapshot_ref="raw/1"),
        _evidence(evidence_id="ev-2", observed_at=NOW - timedelta(hours=3), factor_key="hard_cost_usd"),
    ]
    tasks = [_task("t1", priority=1, required=True), _task("t2", priority=2, required=False)]
    interactions = [_interaction("ix-1", status="planned", created_at=NOW - timedelta(hours=2))]

    project_before = dict(project)
    tasks_before = [dict(task) for task in tasks]
    interactions_before = [dict(item) for item in interactions]
    assessment_dump = assessment.model_dump(mode="json")

    first = _build(
        project=project,
        assessment=assessment,
        evidence=evidence,
        participation_tasks=tasks,
        interactions=interactions,
    )
    second = _build(
        project=project,
        assessment=assessment,
        evidence=evidence,
        participation_tasks=tasks,
        interactions=interactions,
    )

    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert project == project_before
    assert tasks == tasks_before
    assert interactions == interactions_before
    assert assessment.model_dump(mode="json") == assessment_dump


# ── Task 8: workflow economic boundary regression (tests only) ─────────────


def test_opportunity_workflow_projection_model_has_no_economic_surface_fields():
    from app.opportunity.workflow import OpportunityWorkflowProjection

    field_names = tuple(OpportunityWorkflowProjection.model_fields.keys())
    assert field_names == BASELINE_WORKFLOW_PROJECTION_FIELDS
    forbidden = set(field_names) & FORBIDDEN_ECONOMIC_WORKFLOW_KEYS
    assert not forbidden
    assert "economic_proxy" not in field_names
    assert "economics_data_mode" not in field_names
    annotations = {name: str(field.annotation) for name, field in OpportunityWorkflowProjection.model_fields.items()}
    joined = " ".join(annotations.values())
    assert "EconomicProxyProjection" not in joined
    assert "economics_data_mode" not in joined
    assert "economic_proxy" not in joined


def test_workflow_model_dump_key_set_is_baseline_identical_without_economic_keys():
    projection = _build()
    json_dump = projection.model_dump(mode="json")
    python_dump = projection.model_dump()

    assert tuple(json_dump.keys()) == BASELINE_WORKFLOW_PROJECTION_FIELDS
    assert tuple(python_dump.keys()) == BASELINE_WORKFLOW_PROJECTION_FIELDS
    _assert_no_forbidden_economic_surface(json_dump)
    # Python-mode dump retains datetime objects; key-set scan only (not JSON blob).
    _assert_no_forbidden_economic_surface(python_dump, require_json_blob=False)

    # Pre-existing assessment economics remain under opportunity; Task 6 surface does not.
    assert "economics" in json_dump["opportunity"]
    assert "economic_proxy" not in json_dump
    assert "economics_data_mode" not in json_dump

    canonical = _canonical_json_bytes(json_dump)
    assert _canonical_json_bytes(projection.model_dump(mode="json")) == canonical
    assert b"economic_proxy" not in canonical
    assert b"economics_data_mode" not in canonical
    assert b"raw_snapshot_ref" not in canonical


def test_build_workflow_projection_signature_and_output_shape_unchanged():
    from app.opportunity.workflow import build_workflow_projection

    signature = inspect.signature(build_workflow_projection)
    assert tuple(signature.parameters) == BASELINE_BUILDER_PARAMS
    assert all(parameter.kind is inspect.Parameter.KEYWORD_ONLY for parameter in signature.parameters.values())
    assert signature.return_annotation is not inspect.Signature.empty

    projection = build_workflow_projection(
        project=_project(),
        assessment=_assessment(),
        evidence=[_evidence()],
        participation_tasks=[_task("t1", priority=1, required=True)],
        interactions=[],
        now=NOW,
    )
    dump = projection.model_dump(mode="json")
    assert tuple(dump.keys()) == BASELINE_WORKFLOW_PROJECTION_FIELDS
    _assert_no_forbidden_economic_surface(dump)
    # Existing kwargs only — no economic kwargs accepted on the builder.
    with pytest.raises(TypeError):
        build_workflow_projection(  # type: ignore[call-arg]
            project=_project(),
            assessment=None,
            evidence=[],
            participation_tasks=[],
            interactions=[],
            now=NOW,
            economic_proxy=None,
        )


def test_workflow_full_dump_raw_snapshot_ref_absent_under_boundary_contract():
    projection = _build(
        evidence=[
            _evidence(evidence_id="ev-private", raw_snapshot_ref="s3://secret/do-not-leak"),
            _evidence(
                evidence_id="ev-private-2",
                observed_at=NOW - timedelta(hours=3),
                factor_key="hard_cost_usd",
                raw_snapshot_ref="local://raw/2",
            ),
        ]
    )
    dump = projection.model_dump(mode="json")
    _assert_no_forbidden_economic_surface(dump)
    for item in dump["evidence"]["items"]:
        assert "raw_snapshot_ref" not in item
        # Evidence item contract still exposes public fields only.
        assert "evidence_id" in item
        assert "source_url" in item


def test_workflow_service_never_calls_economic_resolver_or_projection_helpers(
    monkeypatch,
):
    from app.db import init_db
    from app.opportunity.workflow_service import OpportunityWorkflowService

    call_log: list[str] = []

    def _spy_project_economics_data(*_args: Any, **_kwargs: Any) -> None:
        call_log.append("project_economics_data")
        raise AssertionError("project_economics_data must not be called from workflow")

    class _SpyResolver:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            call_log.append("EconomicResolver.__init__")

        def resolve(self, *_args: Any, **_kwargs: Any) -> None:
            call_log.append("EconomicResolver.resolve")
            raise AssertionError("EconomicResolver.resolve must not be called from workflow")

    monkeypatch.setattr(
        "app.opportunity.economic_resolver.project_economics_data",
        _spy_project_economics_data,
    )
    monkeypatch.setattr(
        "app.opportunity.economic_resolver.EconomicResolver",
        _SpyResolver,
    )

    connection = sqlite3.connect(":memory:", check_same_thread=False)
    connection.row_factory = sqlite3.Row
    init_db(connection)
    connection.execute(
        """INSERT INTO projects
               (id, name, sector, stage, score, label, confidence, source, url)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("proj-alpha", "Alpha", "DeFi", "testnet", 88, "FARM", 0.9, "seed", "https://alpha.example"),
    )
    connection.commit()

    try:
        for resolver_enabled in (False, True):
            call_log.clear()
            monkeypatch.setattr(
                "app.config.settings.opportunity_economic_resolver_enabled",
                resolver_enabled,
            )
            if resolver_enabled:
                # Valid Settings rollout chain when resolver is on.
                monkeypatch.setattr("app.config.settings.opportunity_economic_snapshot_enabled", True)
                monkeypatch.setattr("app.config.settings.opportunity_economic_evidence_emit_enabled", True)
            else:
                monkeypatch.setattr("app.config.settings.opportunity_economic_snapshot_enabled", False)
                monkeypatch.setattr("app.config.settings.opportunity_economic_evidence_emit_enabled", False)
                monkeypatch.setattr("app.config.settings.opportunity_economic_source_defillama_enabled", False)
                monkeypatch.setattr("app.config.settings.opportunity_economic_source_coingecko_enabled", False)
                monkeypatch.setattr("app.config.settings.opportunity_economic_source_cryptorank_enabled", False)

            service = OpportunityWorkflowService(connection)
            projection = service.get_project_workflow("proj-alpha", NOW)
            service.close()

            assert call_log == [], f"economic surfaces called under resolver={resolver_enabled}: {call_log}"
            dump = projection.model_dump(mode="json")
            assert tuple(dump.keys()) == BASELINE_WORKFLOW_PROJECTION_FIELDS
            _assert_no_forbidden_economic_surface(dump)
    finally:
        connection.close()


def test_workflow_and_router_production_sources_have_no_economic_tokens_static_scan():
    """Supplemental static defense; behavioral tests above remain primary proof."""
    repo_root = Path(__file__).resolve().parents[3]
    targets = (
        repo_root / "backend" / "app" / "opportunity" / "workflow.py",
        repo_root / "backend" / "app" / "opportunity" / "workflow_service.py",
        repo_root / "backend" / "app" / "routers" / "v1" / "opportunity.py",
    )
    forbidden_tokens = (
        "economic_proxy",
        "economics_data_mode",
        "project_economics_data",
        "EconomicProxyProjection",
    )
    for path in targets:
        source = path.read_text(encoding="utf-8")
        for token in forbidden_tokens:
            assert token not in source, f"{token!r} found in {path}"
