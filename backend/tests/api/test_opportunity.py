import json
import logging
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db import DbConnection, init_db
from app.main import create_app
from app.opportunity.models import (
    ConfidenceSet,
    DecisionStatus,
    EvidenceRecord,
    OpportunityAssessment,
    RiskSet,
    validate_source_url,
)
from app.opportunity.repository import OpportunityRepository
from app.opportunity.service import OpportunityService
from app.repository import ProjectRepository
from app.routers.v1 import opportunity

NOW = datetime(2026, 7, 15, 12, tzinfo=UTC)
WORKFLOW_PATH = "/api/v1/projects/{project_id}/opportunity/workflow"
FORBIDDEN_RESPONSE_MARKERS = (
    "raw_snapshot_ref",
    "wallet_cohort_id",
    "private key",
    "private_key",
    "seed phrase",
    "seed_phrase",
    "0xdeadbeefwallet",
    "mnemonic",
)
# Task 8 boundary: Task 6 offline economic surface must not leak into workflow API.
# Pre-existing opportunity.economics (assessment EconomicsResult) remains allowed.
FORBIDDEN_ECONOMIC_WORKFLOW_KEYS = frozenset(
    {
        "economic_proxy",
        "economics_data_mode",
    }
)
BASELINE_WORKFLOW_DATA_KEYS = (
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
ECONOMIC_FLAG_NAMES = (
    "opportunity_economic_snapshot_enabled",
    "opportunity_economic_source_defillama_enabled",
    "opportunity_economic_source_coingecko_enabled",
    "opportunity_economic_source_cryptorank_enabled",
    "opportunity_economic_evidence_emit_enabled",
    "opportunity_economic_resolver_enabled",
)


@pytest.fixture
def conn():
    connection = sqlite3.connect(":memory:", check_same_thread=False)
    connection.row_factory = sqlite3.Row
    init_db(connection)
    connection.executemany(
        """INSERT INTO projects
               (id, name, sector, stage, score, label, confidence, source, url)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            ("p1", "Alpha", "DeFi", "testnet", 90, "FARM", 0.95, "seed", "https://alpha.example"),
            ("p2", "Beta", "L2", "testnet", 70, "WATCH", 0.70, "seed", "https://beta.example"),
        ],
    )
    connection.commit()
    yield connection
    connection.close()


@pytest.fixture
def client(conn):
    project_repo = ProjectRepository(conn)
    opportunity_repo = OpportunityRepository(conn)
    service = OpportunityService(
        project_repo=project_repo,
        opportunity_repo=opportunity_repo,
        now_factory=lambda: NOW,
    )
    app = create_app(db_override=lambda: None)
    app.dependency_overrides[opportunity.get_project_repository] = lambda: project_repo
    app.dependency_overrides[opportunity.get_opportunity_repository] = lambda: opportunity_repo
    app.dependency_overrides[opportunity.get_opportunity_service] = lambda: service
    app.dependency_overrides[opportunity.get_current_time] = lambda: NOW
    try:
        from app.opportunity.workflow_service import OpportunityWorkflowService

        workflow_service = OpportunityWorkflowService(conn)
        app.dependency_overrides[opportunity.get_opportunity_workflow_service] = lambda: workflow_service
    except (ImportError, AttributeError):
        # RED phase: service/route not wired yet.
        pass
    with TestClient(app) as test_client:
        yield test_client


def _table_names(connection) -> set[str]:
    return {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")}


def _row_counts(connection) -> dict[str, int]:
    return {
        "projects": connection.execute("SELECT COUNT(*) FROM projects").fetchone()[0],
        "opportunity_assessments": connection.execute("SELECT COUNT(*) FROM opportunity_assessments").fetchone()[0],
        "opportunity_evidence": connection.execute("SELECT COUNT(*) FROM opportunity_evidence").fetchone()[0],
        "interactions": connection.execute("SELECT COUNT(*) FROM interactions").fetchone()[0],
    }


def _insert_interaction(connection, **overrides):
    payload = {
        "project_id": "p1",
        "status": "active",
        "opportunity_assessment_id": None,
        "opportunity_model_version": "opportunity-v2.0",
        "opportunity_profile_version": "low-cost-curated-multiwallet-v1",
        "wallet_cohort_id": "cohort-private-xyz",
        "note": "secret note about seed phrase and 0xdeadbeefwallet",
        "wallet_count": 2,
        "created_at": "2026-07-15T10:00:00+00:00",
    }
    payload.update(overrides)
    connection.execute(
        """INSERT INTO interactions (
               project_id, status, opportunity_assessment_id,
               opportunity_model_version, opportunity_profile_version,
               wallet_cohort_id, note, wallet_count, created_at
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            payload["project_id"],
            payload["status"],
            payload["opportunity_assessment_id"],
            payload["opportunity_model_version"],
            payload["opportunity_profile_version"],
            payload["wallet_cohort_id"],
            payload["note"],
            payload["wallet_count"],
            payload["created_at"],
        ),
    )
    connection.commit()
    return connection.execute("SELECT id FROM interactions ORDER BY id DESC LIMIT 1").fetchone()[0]


def _canonical_json_bytes(payload) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def _collect_keys(value) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        for key, nested in value.items():
            keys.add(str(key))
            keys |= _collect_keys(nested)
    elif isinstance(value, (list, tuple)):
        for item in value:
            keys |= _collect_keys(item)
    return keys


def _set_economic_flags(monkeypatch, **overrides: bool) -> None:
    values = {name: False for name in ECONOMIC_FLAG_NAMES}
    values.update(overrides)
    # Valid Settings rollout chain when resolver is enabled.
    if values.get("opportunity_economic_resolver_enabled"):
        values["opportunity_economic_evidence_emit_enabled"] = True
        values["opportunity_economic_snapshot_enabled"] = True
    for name, value in values.items():
        monkeypatch.setattr(settings, name, value)


def _assert_no_economic_workflow_surface(payload: dict) -> None:
    keys = _collect_keys(payload)
    leaked = keys & FORBIDDEN_ECONOMIC_WORKFLOW_KEYS
    assert not leaked, f"forbidden economic keys in workflow response: {sorted(leaked)}"
    assert "raw_snapshot_ref" not in keys
    blob = json.dumps(payload, ensure_ascii=False)
    for token in ("economic_proxy", "economics_data_mode", "raw_snapshot_ref"):
        assert token not in blob


def _assert_workflow_privacy(payload: dict) -> None:
    serialized = json.dumps(payload, ensure_ascii=False).lower()
    for marker in FORBIDDEN_RESPONSE_MARKERS:
        assert marker.lower() not in serialized
    assert "raw_snapshot_ref" not in serialized
    assert set(payload.keys()) == {
        "workflow_version",
        "project_id",
        "legacy",
        "opportunity",
        "workflow",
        "evidence",
        "validation",
        "review_at",
        "expires_at",
    }
    current = payload["validation"]["current"]
    if current is not None:
        assert "wallet_cohort_id" not in current
        assert "note" not in current
    for item in payload["evidence"]["items"]:
        validate_source_url(item["source_url"])
        assert "raw_snapshot_ref" not in item
    for plan_item in payload["workflow"]["action_plan"]:
        url = plan_item.get("external_url")
        if url is not None:
            parsed = urlsplit(url)
            assert parsed.scheme in {"http", "https"}
            assert parsed.netloc
    _assert_no_economic_workflow_surface(payload)


def _evidence(**overrides):
    payload = {
        "factor_key": "participation_open",
        "value": True,
        "value_type": "bool",
        "observation_type": "observed",
        "source_url": "https://project.example/rules",
        "source_type": "official_docs",
        "source_grade": "A",
        "observed_at": "2026-07-15T11:00:00Z",
        "verification_status": "verified",
        "independence_group": "official-rules",
    }
    payload.update(overrides)
    return payload


def _assessment(project_id="p1", **overrides):
    payload = {
        "assessment_id": None,
        "project_id": project_id,
        "model_version": "opportunity-v2.0",
        "profile_version": "low-cost-curated-multiwallet-v1",
        "risks": RiskSet(),
        "confidence": ConfidenceSet(
            event=0,
            eligibility=0,
            reward=0,
            cost=0,
            risk=0,
            quality=0,
        ),
        "status": DecisionStatus.INSUFFICIENT_EVIDENCE,
        "public_label": "WATCH",
        "recommended_action": "collect evidence",
        "factor_snapshot": {"nested": {"values": [1, 2]}},
        "scored_at": NOW - timedelta(hours=2),
        "review_at": NOW + timedelta(minutes=30),
        "expires_at": NOW + timedelta(hours=1),
    }
    payload.update(overrides)
    return OpportunityAssessment(**payload)


@pytest.mark.parametrize("shadow_enabled", [False, True])
def test_sparse_project_explicit_evaluation_works_for_both_shadow_flag_states(
    client, conn, monkeypatch, shadow_enabled
):
    monkeypatch.setitem(settings.__dict__, "opportunity_shadow_enabled", shadow_enabled)
    assert settings.opportunity_shadow_enabled is shadow_enabled

    response = client.post("/api/v1/projects/p1/opportunity/evaluate")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["model_version"] == "opportunity-v2.0"
    assert data["status"] == "INSUFFICIENT_EVIDENCE"
    assert data["public_label"] == "WATCH"
    assert data["assessment_id"] is not None
    assert conn.execute("SELECT COUNT(*) FROM opportunity_assessments").fetchone()[0] == 1
    latest = client.get("/api/v1/projects/p1/opportunity").json()["data"]["assessment"]
    assert latest["assessment_id"] == data["assessment_id"]


def test_get_before_evaluation_returns_none_and_project_must_exist(client):
    response = client.get("/api/v1/projects/p1/opportunity")
    missing = client.get("/api/v1/projects/missing/opportunity")

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "data": {"assessment": None, "stale": False, "review_due": False},
    }
    assert missing.status_code == 404
    assert missing.json() == {
        "ok": False,
        "error": {"code": "PROJECT_NOT_FOUND", "message": "Project not found"},
    }


@pytest.mark.parametrize(
    "path,method",
    [
        ("/api/v1/projects/missing/opportunity/evidence", "post"),
        ("/api/v1/projects/missing/opportunity/evidence", "get"),
        ("/api/v1/projects/missing/opportunity/evaluate", "post"),
    ],
)
def test_every_operation_requires_an_existing_project(client, path, method):
    kwargs = {"json": _evidence()} if method == "post" and path.endswith("evidence") else {}
    response = getattr(client, method)(path, **kwargs)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PROJECT_NOT_FOUND"


def test_add_evidence_appends_and_lists_newest_first_with_project_isolation(client):
    older = client.post(
        "/api/v1/projects/p1/opportunity/evidence",
        json=_evidence(observed_at="2026-07-14T11:00:00Z"),
    )
    newer = client.post(
        "/api/v1/projects/p1/opportunity/evidence",
        json=_evidence(value=False, observed_at="2026-07-15T11:00:00Z"),
    )
    other = client.post(
        "/api/v1/projects/p2/opportunity/evidence",
        json=_evidence(factor_key="project_active"),
    )

    assert older.status_code == newer.status_code == other.status_code == 201
    assert older.json()["data"]["evidence_id"] != newer.json()["data"]["evidence_id"]
    response = client.get("/api/v1/projects/p1/opportunity/evidence")
    evidence = response.json()["data"]["evidence"]
    assert [item["value"] for item in evidence] == [False, True]
    assert {item["project_id"] for item in evidence} == {"p1"}
    assert all(set(item) != {"_conn", "_owns_connection"} for item in evidence)


@pytest.mark.parametrize(
    "source_url",
    [
        "https://project.example/rules#fragment",
        "https://user:password@project.example/rules",
        "https://project.example/rules?token=secret-value",
        "https://project.example/rules?access-token=secret-value",
        "https://project.example/rules?refresh_token=secret-value",
        "https://project.example/rules?api.key=secret-value",
        "https://project.example/rules?key=secret-value",
        "https://project.example/rules?secret=secret-value",
        "https://project.example/rules?signature=secret-value",
        "https://project.example/rules?sig=secret-value",
        "https://project.example/rules?auth=secret-value",
        "https://project.example/rules?authorization=secret-value",
        "https://project.example/rules?jwt=secret-value",
        "https://project.example/rules?session=secret-value",
        "https://project.example/rules?credential=secret-value",
        "https://project.example/rules?password=secret-value",
        "https://project.example/rules?client_secret=secret-value",
        "https://project.example/rules?access_key=secret-value",
        "https://project.example/rules?private_key=secret-value",
        "https://project.example/rules?x-api-key=secret-value",
        "https://project.example/rules?X-Amz-Credential=secret-value",
    ],
)
def test_evidence_api_rejects_credentials_and_sensitive_url_queries(client, source_url):
    response = client.post(
        "/api/v1/projects/p1/opportunity/evidence",
        json=_evidence(source_url=source_url),
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "query_key",
    [
        "model_token_count",
        "token_count",
        "tokenization",
        "credential_type",
        "authorization_endpoint",
        "session_duration",
        "secretary",
        "monkey",
        "hockey",
        "market",
        "utm_source",
        "ref",
        "page",
    ],
)
def test_evidence_api_allows_benign_url_query_keys(client, query_key):
    response = client.post(
        "/api/v1/projects/p1/opportunity/evidence",
        json=_evidence(source_url=f"https://project.example/rules?{query_key}=value"),
    )

    assert response.status_code == 201, response.text


@pytest.mark.parametrize(
    "raw_snapshot_ref",
    [
        "https://project.example/snapshot",
        "folder/snapshot",
        "..\\snapshot",
        "snapshot?token=value",
        "snapshot#fragment",
    ],
)
def test_evidence_api_rejects_non_opaque_snapshot_references(client, raw_snapshot_ref):
    response = client.post(
        "/api/v1/projects/p1/opportunity/evidence",
        json=_evidence(raw_snapshot_ref=raw_snapshot_ref),
    )
    assert response.status_code == 422


def test_evidence_api_accepts_safe_opaque_snapshot_and_supersession(client):
    original = client.post(
        "/api/v1/projects/p1/opportunity/evidence",
        json=_evidence(
            factor_key="safety_blocked",
            value=True,
            raw_snapshot_ref="snapshot_20260715-v1",
        ),
    )
    response = client.post(
        "/api/v1/projects/p1/opportunity/evidence",
        json=_evidence(
            factor_key="safety_blocked",
            value=False,
            raw_snapshot_ref="snapshot_20260715-v2",
            supersedes_evidence_id=original.json()["data"]["evidence_id"],
        ),
    )
    assert response.status_code == 201, response.text
    assert response.json()["data"]["supersedes_evidence_id"] == original.json()["data"]["evidence_id"]


def test_evidence_api_rejects_backdated_supersession(client):
    target = client.post(
        "/api/v1/projects/p1/opportunity/evidence",
        json=_evidence(
            factor_key="safety_blocked",
            value=True,
            observed_at="2026-07-15T11:00:00Z",
        ),
    ).json()["data"]

    response = client.post(
        "/api/v1/projects/p1/opportunity/evidence",
        json=_evidence(
            factor_key="safety_blocked",
            value=False,
            observed_at="2026-07-15T10:00:00Z",
            supersedes_evidence_id=target["evidence_id"],
        ),
    )

    assert response.status_code == 422


def test_evidence_api_accepts_chronological_chain_and_branching(client):
    root = client.post(
        "/api/v1/projects/p1/opportunity/evidence",
        json=_evidence(factor_key="safety_blocked", value=True),
    ).json()["data"]
    confirmation = client.post(
        "/api/v1/projects/p1/opportunity/evidence",
        json=_evidence(
            factor_key="safety_blocked",
            value=True,
            observed_at="2026-07-15T11:01:00Z",
            supersedes_evidence_id=root["evidence_id"],
        ),
    )
    branch = client.post(
        "/api/v1/projects/p1/opportunity/evidence",
        json=_evidence(
            factor_key="safety_blocked",
            value=False,
            observed_at="2026-07-15T11:02:00Z",
            supersedes_evidence_id=root["evidence_id"],
        ),
    )
    tip = client.post(
        "/api/v1/projects/p1/opportunity/evidence",
        json=_evidence(
            factor_key="safety_blocked",
            value=False,
            observed_at="2026-07-15T11:03:00Z",
            supersedes_evidence_id=confirmation.json()["data"]["evidence_id"],
        ),
    )

    assert confirmation.status_code == branch.status_code == tip.status_code == 201


def test_evidence_api_rejects_target_with_cyclic_ancestry(client, conn):
    first = client.post(
        "/api/v1/projects/p1/opportunity/evidence",
        json=_evidence(factor_key="safety_blocked", value=True),
    ).json()["data"]
    second = client.post(
        "/api/v1/projects/p1/opportunity/evidence",
        json=_evidence(
            factor_key="safety_blocked",
            value=True,
            supersedes_evidence_id=first["evidence_id"],
        ),
    ).json()["data"]
    conn.execute(
        "UPDATE opportunity_evidence SET supersedes_evidence_id = ? WHERE evidence_id = ?",
        (second["evidence_id"], first["evidence_id"]),
    )
    conn.commit()

    response = client.post(
        "/api/v1/projects/p1/opportunity/evidence",
        json=_evidence(
            factor_key="safety_blocked",
            value=False,
            observed_at="2026-07-15T11:01:00Z",
            supersedes_evidence_id=second["evidence_id"],
        ),
    )

    assert response.status_code == 422
    assert "cycle" in response.text


def test_evidence_history_includes_invalidated_records(client):
    response = client.post(
        "/api/v1/projects/p1/opportunity/evidence",
        json=_evidence(verification_status="invalidated"),
    )

    assert response.status_code == 201
    history = client.get("/api/v1/projects/p1/opportunity/evidence").json()["data"]["evidence"]
    assert [item["verification_status"] for item in history] == ["invalidated"]


@pytest.mark.parametrize(
    "payload",
    [
        _evidence(factor_key="magic_score", value=100, value_type="number"),
        _evidence(value="true"),
        _evidence(value_type="string"),
        _evidence(
            factor_key="event_probability",
            value={"low": 0.2, "base": 1.2, "high": 0.8},
            value_type="range",
        ),
        _evidence(factor_key="project_quality", value=101, value_type="number"),
        _evidence(factor_key="opportunity_timing", value="finished", value_type="string"),
    ],
)
def test_invalid_factor_payload_returns_unified_422_before_persistence(client, conn, payload):
    response = client.post(
        "/api/v1/projects/p1/opportunity/evidence",
        json=payload,
    )

    assert response.status_code == 422
    body = response.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert conn.execute("SELECT COUNT(*) FROM opportunity_evidence").fetchone()[0] == 0


def test_latest_assessment_is_isolated_and_serializes_mapping_proxy(client, conn):
    repo = OpportunityRepository(conn)
    repo.save_assessment(_assessment(scored_at=NOW - timedelta(hours=3)))
    repo.save_assessment(
        _assessment(
            scored_at=NOW - timedelta(hours=1),
            recommended_action="latest review",
        )
    )
    repo.save_assessment(_assessment("p2", recommended_action="other project"))

    response = client.get("/api/v1/projects/p1/opportunity")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["assessment"]["recommended_action"] == "latest review"
    assert data["assessment"]["factor_snapshot"] == {"nested": {"values": [1, 2]}}
    assert data["assessment"]["project_id"] == "p1"
    assert data["stale"] is False
    assert data["review_due"] is False


def test_review_can_be_due_before_assessment_is_stale(client, conn):
    OpportunityRepository(conn).save_assessment(_assessment(review_at=NOW, expires_at=NOW + timedelta(hours=1)))

    data = client.get("/api/v1/projects/p1/opportunity").json()["data"]

    assert data["review_due"] is True
    assert data["stale"] is False


def test_expired_blocked_assessment_is_review_due_and_never_cleared(client, conn):
    OpportunityRepository(conn).save_assessment(
        _assessment(
            status=DecisionStatus.BLOCKED,
            public_label="WATCH",
            requires_remediation=True,
            blocker_codes=("integrity_blocked",),
            recommended_action="remediate integrity issue",
            review_at=NOW,
            expires_at=NOW,
        )
    )

    response = client.get("/api/v1/projects/p1/opportunity")

    data = response.json()["data"]
    assert data["stale"] is True
    assert data["review_due"] is True
    assert "cleared" not in data
    assert data["assessment"]["status"] == "BLOCKED"
    assert data["assessment"]["requires_remediation"] is True
    assert data["assessment"]["blocker_codes"] == ["integrity_blocked"]


def test_health_registers_shadow_capability_without_claiming_replacement(client):
    response = client.get(settings.health_check_path)

    assert response.status_code == 200
    body = response.json()
    assert body["opportunity_model_version"] == "opportunity-v2.0"
    assert body["opportunity_shadow_enabled"] is settings.opportunity_shadow_enabled
    assert body["opportunity_shadow_sample_rate"] == settings.opportunity_shadow_sample_rate
    assert "replace" not in str(body).lower()


def test_openapi_registers_exactly_five_opportunity_operations(client):
    paths = client.get("/openapi.json").json()["paths"]
    operations = {
        (path, method)
        for path, methods in paths.items()
        if "/opportunity" in path
        for method in methods
        if method in {"get", "post", "put", "patch", "delete"}
    }

    assert operations == {
        ("/api/v1/projects/{project_id}/opportunity/evidence", "post"),
        ("/api/v1/projects/{project_id}/opportunity/evidence", "get"),
        ("/api/v1/projects/{project_id}/opportunity/evaluate", "post"),
        ("/api/v1/projects/{project_id}/opportunity", "get"),
        ("/api/v1/projects/{project_id}/opportunity/workflow", "get"),
    }


def test_workflow_missing_project_returns_structured_404(client):
    response = client.get(WORKFLOW_PATH.format(project_id="missing"))

    assert response.status_code == 404
    assert response.json() == {
        "ok": False,
        "error": {"code": "PROJECT_NOT_FOUND", "message": "Project not found"},
    }


def test_workflow_without_assessment_is_needs_evaluation(client, conn, monkeypatch):
    def boom(*_args, **_kwargs):
        raise AssertionError("evaluation/LLM must not be called for workflow reads")

    monkeypatch.setattr(OpportunityService, "evaluate", boom)
    monkeypatch.setattr(OpportunityService, "evaluate_row", boom)

    tables_before = _table_names(conn)
    counts_before = _row_counts(conn)

    first = client.get(WORKFLOW_PATH.format(project_id="p1"))
    second = client.get(WORKFLOW_PATH.format(project_id="p1"))

    assert first.status_code == 200, first.text
    body = first.json()
    assert body["ok"] is True
    data = body["data"]
    assert data["workflow"]["state"] == "NEEDS_EVALUATION"
    assert data["opportunity"] is None
    assert data["workflow"]["next_action"]["key"] == "evaluate"
    _assert_workflow_privacy(data)
    assert first.json() == second.json()
    assert _row_counts(conn) == counts_before
    assert _table_names(conn) == tables_before
    assert "opportunity_workflow" not in tables_before


def test_workflow_uses_latest_assessment_ordering(client, conn):
    repo = OpportunityRepository(conn)
    older = repo.save_assessment(
        _assessment(
            assessment_id="assess-old",
            scored_at=NOW - timedelta(hours=5),
            recommended_action="older",
            status=DecisionStatus.MONITOR,
            public_label="WATCH",
        )
    )
    # Same scored_at: later created_at and higher assessment_id DESC should win.
    repo.save_assessment(
        _assessment(
            assessment_id="assess-aaa",
            scored_at=NOW - timedelta(hours=1),
            recommended_action="mid",
            status=DecisionStatus.MONITOR,
            public_label="WATCH",
        )
    )
    latest = repo.save_assessment(
        _assessment(
            assessment_id="assess-zzz",
            scored_at=NOW - timedelta(hours=1),
            recommended_action="latest shadow",
            status=DecisionStatus.ACTIONABLE,
            public_label="FARM",
        )
    )
    assert older.assessment_id != latest.assessment_id

    response = client.get(WORKFLOW_PATH.format(project_id="p1"))
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["opportunity"]["assessment_id"] == "assess-zzz"
    assert data["opportunity"]["recommended_action"] == "latest shadow"
    assert data["workflow"]["state"] == "ACTIONABLE"
    _assert_workflow_privacy(data)


def test_workflow_review_and_expiry_precedence_uses_current_time(client, conn, monkeypatch):
    OpportunityRepository(conn).save_assessment(
        _assessment(
            assessment_id="assess-review",
            status=DecisionStatus.ACTIONABLE,
            public_label="FARM",
            recommended_action="start validation",
            review_at=NOW + timedelta(minutes=10),
            expires_at=NOW + timedelta(hours=2),
        )
    )

    fresh = client.get(WORKFLOW_PATH.format(project_id="p1"))
    assert fresh.status_code == 200
    assert fresh.json()["data"]["workflow"]["state"] == "ACTIONABLE"

    monkeypatch.setitem(
        client.app.dependency_overrides,
        opportunity.get_current_time,
        lambda: NOW + timedelta(minutes=15),
    )
    review_due = client.get(WORKFLOW_PATH.format(project_id="p1"))
    assert review_due.status_code == 200
    assert review_due.json()["data"]["workflow"]["state"] == "REVIEW_REQUIRED"
    assert review_due.json()["data"]["workflow"]["next_action"]["key"] == "re_evaluate"

    monkeypatch.setitem(
        client.app.dependency_overrides,
        opportunity.get_current_time,
        lambda: NOW + timedelta(hours=3),
    )
    expired = client.get(WORKFLOW_PATH.format(project_id="p1"))
    assert expired.status_code == 200
    assert expired.json()["data"]["workflow"]["state"] == "REVIEW_REQUIRED"


def test_workflow_includes_invalidated_evidence_and_safe_urls(client, conn):
    client.post(
        "/api/v1/projects/p1/opportunity/evidence",
        json=_evidence(
            verification_status="invalidated",
            value=False,
            observed_at="2026-07-14T10:00:00Z",
            raw_snapshot_ref="snap-private-1",
        ),
    )
    client.post(
        "/api/v1/projects/p1/opportunity/evidence",
        json=_evidence(
            verification_status="verified",
            value=True,
            observed_at="2026-07-15T10:00:00Z",
            source_url="https://project.example/rules?utm_source=docs",
            raw_snapshot_ref="snap-private-2",
        ),
    )
    OpportunityRepository(conn).save_assessment(
        _assessment(assessment_id="assess-ev", status=DecisionStatus.MONITOR, public_label="WATCH")
    )

    response = client.get(WORKFLOW_PATH.format(project_id="p1"))
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    statuses = [item["verification_status"] for item in data["evidence"]["items"]]
    assert "invalidated" in statuses
    assert "verified" in statuses
    assert statuses[0] == "verified"  # observed_at DESC
    _assert_workflow_privacy(data)


def test_workflow_selects_interactions_for_current_assessment_only(client, conn):
    repo = OpportunityRepository(conn)
    current = repo.save_assessment(
        _assessment(
            assessment_id="assess-current",
            scored_at=NOW - timedelta(hours=1),
            status=DecisionStatus.ACTIONABLE,
            public_label="FARM",
            recommended_action="validate",
        )
    )
    repo.save_assessment(
        _assessment(
            assessment_id="assess-old",
            scored_at=NOW - timedelta(hours=5),
            status=DecisionStatus.MONITOR,
            public_label="WATCH",
            recommended_action="old",
        )
    )
    _insert_interaction(
        conn,
        opportunity_assessment_id="assess-old",
        status="done",
        created_at="2026-07-15T11:00:00+00:00",
        note="old assessment private note",
        wallet_cohort_id="old-cohort",
    )
    _insert_interaction(
        conn,
        opportunity_assessment_id=current.assessment_id,
        status="active",
        created_at="2026-07-15T09:00:00+00:00",
        note="current assessment private note",
        wallet_cohort_id="current-cohort",
        wallet_count=1,
    )
    _insert_interaction(
        conn,
        opportunity_assessment_id=current.assessment_id,
        status="planned",
        created_at="2026-07-15T12:00:00+00:00",
        note="newer open interaction",
        wallet_cohort_id="current-cohort-2",
        wallet_count=2,
    )

    response = client.get(WORKFLOW_PATH.format(project_id="p1"))
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["opportunity"]["assessment_id"] == "assess-current"
    assert data["validation"]["history_summary"]["total"] == 2
    assert data["validation"]["history_summary"]["by_status"]["planned"] == 1
    assert data["validation"]["history_summary"]["by_status"]["active"] == 1
    assert data["validation"]["history_summary"]["by_status"].get("done", 0) == 0
    assert data["validation"]["current"]["status"] == "planned"
    assert data["validation"]["current"]["wallet_count"] == 2
    assert data["workflow"]["next_action"]["key"] == "continue_validation"
    _assert_workflow_privacy(data)


def test_workflow_malformed_persisted_data_returns_structured_500(client, conn, caplog):
    conn.execute(
        """INSERT INTO opportunity_assessments (
               assessment_id, project_id, model_version, profile_version,
               assessment_json, decision_status, public_label,
               overall_confidence, scored_at, expires_at
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "assess-bad",
            "p1",
            "opportunity-v2.0",
            "low-cost-curated-multiwallet-v1",
            "{not-valid-json",
            "ACTIONABLE",
            "FARM",
            0.5,
            "2026-07-15T10:00:00+00:00",
            "2026-07-16T10:00:00+00:00",
        ),
    )
    conn.commit()

    with caplog.at_level(logging.ERROR):
        response = client.get(WORKFLOW_PATH.format(project_id="p1"))

    assert response.status_code == 500
    assert response.json() == {
        "ok": False,
        "error": {
            "code": "OPPORTUNITY_WORKFLOW_PROJECTION_ERROR",
            "message": "Failed to build opportunity workflow projection",
        },
    }
    joined = " ".join(record.getMessage() for record in caplog.records).lower()
    assert "p1" in joined
    assert "projection" in joined or "error" in joined
    assert "not-valid-json" not in joined
    assert "cohort" not in joined
    assert "seed phrase" not in joined
    assert "token=" not in joined


def test_workflow_success_logs_are_privacy_safe(client, conn, caplog):
    OpportunityRepository(conn).save_assessment(
        _assessment(
            assessment_id="assess-log",
            status=DecisionStatus.ACTIONABLE,
            public_label="FARM",
            recommended_action="start validation",
        )
    )
    _insert_interaction(
        conn,
        opportunity_assessment_id="assess-log",
        note="do not log this note or cohort-secret-value",
        wallet_cohort_id="cohort-secret-value",
    )
    client.post(
        "/api/v1/projects/p1/opportunity/evidence",
        json=_evidence(
            value=True,
            source_url="https://project.example/rules?utm_source=safe",
            raw_snapshot_ref="snap-do-not-log",
        ),
    )

    with caplog.at_level(logging.INFO):
        response = client.get(WORKFLOW_PATH.format(project_id="p1"))

    assert response.status_code == 200, response.text
    messages = " ".join(record.getMessage() for record in caplog.records)
    lowered = messages.lower()
    assert "p1" in lowered
    assert "assess-log" in lowered
    assert "actionable" in lowered
    assert "start_validation" in lowered or "continue_validation" in lowered
    assert "cohort-secret-value" not in lowered
    assert "do not log this note" not in lowered
    assert "snap-do-not-log" not in lowered
    assert "utm_source" not in lowered


def test_workflow_get_is_read_only_and_idempotent(client, conn, monkeypatch):
    def boom(*_args, **_kwargs):
        raise AssertionError("evaluate must not be called")

    monkeypatch.setattr(OpportunityService, "evaluate", boom)

    OpportunityRepository(conn).save_assessment(
        _assessment(assessment_id="assess-idemp", status=DecisionStatus.MONITOR, public_label="WATCH")
    )
    client.post("/api/v1/projects/p1/opportunity/evidence", json=_evidence())
    _insert_interaction(conn, opportunity_assessment_id="assess-idemp")

    tables_before = _table_names(conn)
    counts_before = _row_counts(conn)

    first = client.get(WORKFLOW_PATH.format(project_id="p1"))
    second = client.get(WORKFLOW_PATH.format(project_id="p1"))

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert _row_counts(conn) == counts_before
    assert _table_names(conn) == tables_before
    _assert_workflow_privacy(first.json()["data"])


def test_workflow_service_db_adapter_contract_matches_across_connection_wrappers(conn):
    from app.opportunity.workflow_service import OpportunityWorkflowService

    repo = OpportunityRepository(conn)
    assessment = repo.save_assessment(
        _assessment(
            assessment_id="assess-adapter",
            status=DecisionStatus.ACTIONABLE,
            public_label="FARM",
            recommended_action="validate now",
            factor_snapshot={"critical_unknowns": ["hard_cost_usd"]},
        )
    )
    repo.add_evidence(
        EvidenceRecord(
            **{
                **_evidence(),
                "project_id": "p1",
                "evidence_id": "ev-adapter-1",
                "verification_status": "invalidated",
            }
        )
    )
    _insert_interaction(
        conn,
        opportunity_assessment_id=assessment.assessment_id,
        status="active",
        created_at="2026-07-15T08:00:00+00:00",
    )
    _insert_interaction(
        conn,
        opportunity_assessment_id="other-assessment",
        status="done",
        created_at="2026-07-15T09:00:00+00:00",
    )

    tables_before = _table_names(conn)
    raw_service = OpportunityWorkflowService(conn)
    wrapped_service = OpportunityWorkflowService(DbConnection(conn, kind="sqlite"))

    raw_projection = raw_service.get_project_workflow("p1", NOW)
    wrapped_projection = wrapped_service.get_project_workflow("p1", NOW)

    raw_dump = raw_projection.model_dump(mode="json")
    wrapped_dump = wrapped_projection.model_dump(mode="json")
    assert raw_dump == wrapped_dump
    assert raw_dump["opportunity"]["assessment_id"] == "assess-adapter"
    assert raw_dump["validation"]["history_summary"]["total"] == 1
    assert raw_dump["validation"]["current"]["status"] == "active"
    assert raw_dump["evidence"]["items"][0]["verification_status"] == "invalidated"
    assert raw_dump["workflow"]["state"] == "ACTIONABLE"
    assert "raw_snapshot_ref" not in json.dumps(raw_dump)
    assert _table_names(conn) == tables_before
    raw_service.close()
    wrapped_service.close()


# ── Task 8: v1 workflow API economic boundary regression (tests only) ─────


def _seed_workflow_boundary_fixture(conn) -> None:
    repo = OpportunityRepository(conn)
    assessment = repo.save_assessment(
        _assessment(
            assessment_id="assess-econ-boundary",
            status=DecisionStatus.ACTIONABLE,
            public_label="FARM",
            recommended_action="validate boundary",
            factor_snapshot={"critical_unknowns": []},
        )
    )
    # Persist private raw_snapshot_ref in storage; workflow projection must not expose it.
    repo.add_evidence(
        EvidenceRecord(
            **{
                **_evidence(
                    source_url="https://project.example/rules",
                    raw_snapshot_ref="snap-boundary-private",
                ),
                "project_id": "p1",
                "evidence_id": "ev-boundary-1",
                "verification_status": "verified",
            }
        )
    )
    _insert_interaction(
        conn,
        opportunity_assessment_id=assessment.assessment_id,
        status="planned",
        created_at="2026-07-15T11:30:00+00:00",
        note="private boundary note",
        wallet_cohort_id="cohort-boundary-private",
    )


def test_workflow_api_all_economic_flags_false_exact_baseline_body(client, conn, monkeypatch):
    _set_economic_flags(monkeypatch)  # all six false
    _seed_workflow_boundary_fixture(conn)

    call_log: list[str] = []

    def _spy_project_economics_data(*_args, **_kwargs):
        call_log.append("project_economics_data")
        raise AssertionError("workflow API must not call project_economics_data")

    class _SpyResolver:
        def __init__(self, *_args, **_kwargs):
            call_log.append("EconomicResolver.__init__")

        def resolve(self, *_args, **_kwargs):
            call_log.append("EconomicResolver.resolve")
            raise AssertionError("workflow API must not call EconomicResolver")

    monkeypatch.setattr(
        "app.opportunity.economic_resolver.project_economics_data",
        _spy_project_economics_data,
    )
    monkeypatch.setattr(
        "app.opportunity.economic_resolver.EconomicResolver",
        _SpyResolver,
    )

    first = client.get(WORKFLOW_PATH.format(project_id="p1"))
    second = client.get(WORKFLOW_PATH.format(project_id="p1"))

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert call_log == []

    body = first.json()
    assert body["ok"] is True
    data = body["data"]
    assert tuple(data.keys()) == BASELINE_WORKFLOW_DATA_KEYS
    _assert_workflow_privacy(data)
    _assert_no_economic_workflow_surface(data)

    # Exact baseline: repeated GET is byte-identical under canonical dump.
    baseline_bytes = _canonical_json_bytes(body)
    assert _canonical_json_bytes(second.json()) == baseline_bytes
    assert first.content == second.content

    # Meaningful baseline vs service direct model_dump (router serialization path).
    from app.opportunity.workflow_service import OpportunityWorkflowService

    service = OpportunityWorkflowService(conn)
    projection = service.get_project_workflow("p1", NOW)
    service.close()
    expected_data = projection.model_dump(mode="json")
    assert data == expected_data
    assert _canonical_json_bytes(data) == _canonical_json_bytes(expected_data)
    assert b"economic_proxy" not in baseline_bytes
    assert b"economics_data_mode" not in baseline_bytes
    assert b"raw_snapshot_ref" not in baseline_bytes


def test_workflow_api_resolver_flag_true_still_has_no_economic_surface(client, conn, monkeypatch):
    # Valid Settings: resolver requires evidence_emit requires snapshot.
    _set_economic_flags(
        monkeypatch,
        opportunity_economic_resolver_enabled=True,
    )
    assert settings.opportunity_economic_resolver_enabled is True
    assert settings.opportunity_economic_evidence_emit_enabled is True
    assert settings.opportunity_economic_snapshot_enabled is True

    _seed_workflow_boundary_fixture(conn)

    call_log: list[str] = []

    def _spy_project_economics_data(*_args, **_kwargs):
        call_log.append("project_economics_data")
        return None

    class _SpyResolver:
        def __init__(self, *_args, **_kwargs):
            call_log.append("EconomicResolver.__init__")

        def resolve(self, *_args, **_kwargs):
            call_log.append("EconomicResolver.resolve")
            return None

    monkeypatch.setattr(
        "app.opportunity.economic_resolver.project_economics_data",
        _spy_project_economics_data,
    )
    monkeypatch.setattr(
        "app.opportunity.economic_resolver.EconomicResolver",
        _SpyResolver,
    )

    # Capture flag-off baseline key set first (same fixture, flags toggled).
    _set_economic_flags(monkeypatch)
    baseline_response = client.get(WORKFLOW_PATH.format(project_id="p1"))
    assert baseline_response.status_code == 200, baseline_response.text
    baseline_data = baseline_response.json()["data"]
    baseline_keys = _collect_keys(baseline_data)
    baseline_top = tuple(baseline_data.keys())

    _set_economic_flags(monkeypatch, opportunity_economic_resolver_enabled=True)
    response = client.get(WORKFLOW_PATH.format(project_id="p1"))
    assert response.status_code == 200, response.text
    assert call_log == [], f"economic surfaces invoked with resolver on: {call_log}"

    body = response.json()
    assert body["ok"] is True
    data = body["data"]
    assert tuple(data.keys()) == BASELINE_WORKFLOW_DATA_KEYS
    assert tuple(data.keys()) == baseline_top
    _assert_workflow_privacy(data)
    _assert_no_economic_workflow_surface(data)

    keys = _collect_keys(data)
    assert "economic_proxy" not in keys
    assert "economics_data_mode" not in keys
    assert "raw_snapshot_ref" not in keys
    # Key set must not grow Task 6 economic surface relative to baseline.
    assert not (keys - baseline_keys) & FORBIDDEN_ECONOMIC_WORKFLOW_KEYS
    assert keys == baseline_keys
    # Body remains free of new economic surface vs flag-off baseline dump.
    assert _canonical_json_bytes(data) == _canonical_json_bytes(baseline_data)


def test_workflow_router_returns_projection_model_dump_path(client, conn, monkeypatch):
    """End-to-end proof that the router exposes projection.model_dump(mode='json')."""
    _set_economic_flags(monkeypatch)
    _seed_workflow_boundary_fixture(conn)

    response = client.get(WORKFLOW_PATH.format(project_id="p1"))
    assert response.status_code == 200, response.text
    http_data = response.json()["data"]

    from app.opportunity.workflow_service import OpportunityWorkflowService
    from app.routers.v1 import opportunity as opportunity_router

    service = OpportunityWorkflowService(conn)
    projection = service.get_project_workflow("p1", NOW)
    service.close()
    direct_dump = projection.model_dump(mode="json")

    assert http_data == direct_dump
    assert tuple(http_data.keys()) == BASELINE_WORKFLOW_DATA_KEYS
    _assert_no_economic_workflow_surface(http_data)
    assert "raw_snapshot_ref" not in _collect_keys(http_data)

    # Router source still serializes via model_dump (supplemental static check).
    router_source = Path(opportunity_router.__file__).read_text(encoding="utf-8")
    assert 'projection.model_dump(mode="json")' in router_source or (
        "projection.model_dump(mode='json')" in router_source
    )
    for token in (
        "economic_proxy",
        "economics_data_mode",
        "project_economics_data",
        "EconomicProxyProjection",
    ):
        assert token not in router_source


def test_workflow_api_raw_snapshot_ref_absent_from_response_body(client, conn, monkeypatch):
    _set_economic_flags(monkeypatch)
    _seed_workflow_boundary_fixture(conn)

    response = client.get(WORKFLOW_PATH.format(project_id="p1"))
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    _assert_no_economic_workflow_surface(data)
    for item in data["evidence"]["items"]:
        assert "raw_snapshot_ref" not in item
        assert "evidence_id" in item
        assert "source_url" in item
