import sqlite3
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db import init_db
from app.main import create_app
from app.opportunity.models import (
    ConfidenceSet,
    DecisionStatus,
    OpportunityAssessment,
    RiskSet,
)
from app.opportunity.repository import OpportunityRepository
from app.opportunity.service import OpportunityService
from app.repository import ProjectRepository
from app.routers.v1 import opportunity

NOW = datetime(2026, 7, 15, 12, tzinfo=UTC)


@pytest.fixture
def conn():
    connection = sqlite3.connect(":memory:", check_same_thread=False)
    connection.row_factory = sqlite3.Row
    init_db(connection)
    connection.executemany(
        """INSERT INTO projects
               (id, name, sector, stage, score, label, confidence, source)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            ("p1", "Alpha", "DeFi", "testnet", 90, "FARM", 0.95, "seed"),
            ("p2", "Beta", "L2", "testnet", 70, "WATCH", 0.70, "seed"),
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
    with TestClient(app) as test_client:
        yield test_client


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


def test_openapi_registers_exactly_four_opportunity_operations(client):
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
    }
