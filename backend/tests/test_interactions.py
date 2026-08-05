"""Interaction log API tests."""

from __future__ import annotations

import asyncio
import re
import sqlite3
import threading
import uuid
from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db import DbConnection, get_connection, init_db
from app.main import create_app
from app.routers.v1.interactions import InteractionCreate, InteractionUpdate

_BECH32_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"


def _bech32_polymod(values: list[int]) -> int:
    generators = (0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3)
    checksum = 1
    for value in values:
        top = checksum >> 25
        checksum = ((checksum & 0x1FFFFFF) << 5) ^ value
        for index, generator in enumerate(generators):
            if (top >> index) & 1:
                checksum ^= generator
    return checksum


def _valid_bech32(hrp: str, *, bech32m: bool = False) -> str:
    expanded = [ord(char) >> 5 for char in hrp] + [0]
    expanded += [ord(char) & 31 for char in hrp]
    data = [0, *([1] * 32)]
    constant = 0x2BC830A3 if bech32m else 1
    polymod = _bech32_polymod([*expanded, *data, 0, 0, 0, 0, 0, 0]) ^ constant
    checksum = [(polymod >> (5 * (5 - index))) & 31 for index in range(6)]
    return hrp + "1" + "".join(_BECH32_CHARSET[value] for value in [*data, *checksum])


def _base58_encode(raw: bytes) -> str:
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    number = int.from_bytes(raw, "big")
    encoded = ""
    while number:
        number, remainder = divmod(number, 58)
        encoded = alphabet[remainder] + encoded
    zeroes = len(raw) - len(raw.lstrip(b"\0"))
    return "1" * zeroes + (encoded or "")


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "interactions.db"
    monkeypatch.setattr(settings, "db_path", str(db_path))
    monkeypatch.setattr(settings, "api_key", "")
    monkeypatch.setattr(settings, "app_env", "testing")
    init_db()
    # seed one project
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO projects (id, name, sector, stage, score, label, confidence, source)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("proj-1", "Demo", "L2", "testnet", 70, "FARM", 0.9, "seed"),
    )
    conn.commit()
    conn.close()
    return TestClient(create_app(db_override=lambda: None))


def test_create_list_update_delete_interaction(client: TestClient):
    r = client.post(
        "/api/v1/interactions",
        json={
            "project_id": "proj-1",
            "status": "active",
            "started_at": "2026-07-01",
            "cost_usd": 12.5,
            "activities": "测试网,积分",
            "note": "钱包 A",
        },
    )
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["project_id"] == "proj-1"
    assert data["status"] == "active"
    assert data["cost_usd"] == 12.5
    assert data["score_at_start"] == 70
    assert data["label_at_start"] == "FARM"
    iid = data["id"]

    r2 = client.get("/api/v1/projects/proj-1/interactions")
    assert r2.status_code == 200
    assert r2.json()["data"]["count"] >= 1

    r3 = client.patch(
        f"/api/v1/interactions/{iid}",
        json={
            "status": "done",
            "ended_at": "2026-07-14",
            "profit_usd": 40,
            "outcome": "airdropped",
        },
    )
    assert r3.status_code == 200
    d3 = r3.json()["data"]
    assert d3["status"] == "done"
    assert d3["profit_usd"] == 40
    assert abs(d3["net_usd"] - (40 - 12.5)) < 0.01

    r4 = client.get("/api/v1/interactions/summary")
    assert r4.status_code == 200
    s = r4.json()["data"]
    assert s["total"] >= 1
    assert s["total_cost_usd"] >= 12.5

    r5 = client.delete(f"/api/v1/interactions/{iid}")
    assert r5.status_code == 200


def test_create_unknown_project_404(client: TestClient):
    r = client.post(
        "/api/v1/interactions",
        json={"project_id": "missing", "status": "planned"},
    )
    assert r.status_code == 404


def test_modern_sqlite_create_uses_insert_returning(monkeypatch, client: TestClient):
    from app.routers.v1 import interactions

    statements = []
    original_get_connection = interactions.get_connection

    class RecordingConnection:
        kind = "sqlite"

        def __init__(self, connection):
            self.connection = connection

        def execute(self, sql, params=None):
            statements.append(sql)
            return self.connection.execute(sql, params)

        def begin_serialized_write(self):
            self.connection.begin_serialized_write()

        def commit(self):
            self.connection.commit()

        def rollback(self):
            self.connection.rollback()

        def close(self):
            self.connection.close()

    monkeypatch.setattr(
        interactions,
        "get_connection",
        lambda: RecordingConnection(original_get_connection()),
    )

    response = client.post("/api/v1/interactions", json={"project_id": "proj-1"})

    assert response.status_code == 200, response.text
    insert = next(sql for sql in statements if "INSERT INTO interactions" in sql)
    assert "RETURNING *" in insert


def test_old_sqlite_fallback_returns_own_insert_before_commit(monkeypatch, client: TestClient):
    from app.routers.v1 import interactions

    original_get_connection = interactions.get_connection
    raw = original_get_connection()
    raw.execute(
        """CREATE TRIGGER insert_decoy AFTER INSERT ON interactions
           WHEN NEW.note IS NULL
           BEGIN
             INSERT INTO interactions (project_id, status, note, wallet_cohort_id)
             VALUES (NEW.project_id, 'planned', 'trigger-decoy', 'cohort-decoy');
           END"""
    )
    raw.commit()
    raw.close()
    monkeypatch.setattr(interactions.sqlite3, "sqlite_version_info", (3, 34, 0))

    response = client.post("/api/v1/interactions", json={"project_id": "proj-1"})

    assert response.status_code == 200, response.text
    assert response.json()["data"]["note"] is None
    assert response.json()["data"]["wallet_cohort_id"] != "cohort-decoy"


def test_modern_sqlite_patch_uses_update_returning(monkeypatch, client: TestClient):
    from app.routers.v1 import interactions

    created = client.post("/api/v1/interactions", json={"project_id": "proj-1"})
    interaction_id = created.json()["data"]["id"]
    statements = []
    original_get_connection = interactions.get_connection

    class RecordingConnection:
        kind = "sqlite"

        def __init__(self, connection):
            self.connection = connection

        def execute(self, sql, params=None):
            statements.append(sql)
            return self.connection.execute(sql, params)

        def begin_serialized_write(self):
            self.connection.begin_serialized_write()

        def commit(self):
            self.connection.commit()

        def rollback(self):
            self.connection.rollback()

        def close(self):
            self.connection.close()

    monkeypatch.setattr(interactions, "get_connection", lambda: RecordingConnection(original_get_connection()))

    response = client.patch(f"/api/v1/interactions/{interaction_id}", json={"note": "returned atomically"})

    assert response.status_code == 200, response.text
    update = next(sql for sql in statements if "UPDATE interactions SET" in sql)
    assert "RETURNING *" in update


def test_old_sqlite_patch_reads_updated_row_before_commit(monkeypatch, client: TestClient):
    from app.routers.v1 import interactions

    created = client.post("/api/v1/interactions", json={"project_id": "proj-1"})
    interaction_id = created.json()["data"]["id"]
    events = []
    original_get_connection = interactions.get_connection

    class OrderedConnection:
        kind = "sqlite"

        def __init__(self, connection):
            self.connection = connection

        def execute(self, sql, params=None):
            if "UPDATE interactions SET" in sql:
                events.append("update")
            elif sql.strip().startswith("SELECT * FROM interactions"):
                events.append("select")
            return self.connection.execute(sql, params)

        def begin_serialized_write(self):
            self.connection.begin_serialized_write()

        def commit(self):
            events.append("commit")
            self.connection.commit()

        def rollback(self):
            self.connection.rollback()

        def close(self):
            self.connection.close()

    monkeypatch.setattr(interactions.sqlite3, "sqlite_version_info", (3, 34, 0))
    monkeypatch.setattr(interactions, "get_connection", lambda: OrderedConnection(original_get_connection()))

    response = client.patch(f"/api/v1/interactions/{interaction_id}", json={"note": "fallback"})

    assert response.status_code == 200, response.text
    assert events[-3:] == ["update", "select", "commit"]


def test_patch_response_is_the_atomic_update_snapshot_not_later_state(monkeypatch, client: TestClient):
    from app.routers.v1 import interactions

    created = client.post("/api/v1/interactions", json={"project_id": "proj-1"})
    interaction_id = created.json()["data"]["id"]
    original_get_connection = interactions.get_connection

    class ConcurrentCommitConnection:
        kind = "sqlite"

        def __init__(self, connection):
            self.connection = connection

        def execute(self, sql, params=None):
            return self.connection.execute(sql, params)

        def begin_serialized_write(self):
            self.connection.begin_serialized_write()

        def commit(self):
            self.connection.commit()
            self.connection.execute(
                "UPDATE interactions SET note = ? WHERE id = ?",
                ("concurrent-later-value", interaction_id),
            )
            self.connection.commit()

        def rollback(self):
            self.connection.rollback()

        def close(self):
            self.connection.close()

    monkeypatch.setattr(
        interactions,
        "get_connection",
        lambda: ConcurrentCommitConnection(original_get_connection()),
    )

    response = client.patch(f"/api/v1/interactions/{interaction_id}", json={"note": "patch-snapshot"})

    assert response.status_code == 200, response.text
    assert response.json()["data"]["note"] == "patch-snapshot"
    conn = original_get_connection()
    try:
        persisted = conn.execute("SELECT note FROM interactions WHERE id = ?", (interaction_id,)).fetchone()
        assert persisted["note"] == "concurrent-later-value"
    finally:
        conn.close()


def test_patch_rolls_back_when_atomic_readback_fails(monkeypatch, client: TestClient):
    from app.routers.v1 import interactions

    created = client.post("/api/v1/interactions", json={"project_id": "proj-1"})
    interaction_id = created.json()["data"]["id"]
    original_get_connection = interactions.get_connection
    state = {"rolled_back": False}

    class BrokenReturningCursor:
        rowcount = 1

        def fetchone(self):
            raise RuntimeError("readback failed")

    class BrokenConnection:
        kind = "postgres"

        def __init__(self, connection):
            self.connection = connection

        def execute(self, sql, params=None):
            if "UPDATE interactions SET" in sql:
                self.connection.execute(sql.replace(" RETURNING *", ""), params)
                return BrokenReturningCursor()
            return self.connection.execute(sql.replace(" FOR UPDATE", ""), params)

        def begin_serialized_write(self):
            self.connection.begin_serialized_write()

        def commit(self):
            self.connection.commit()

        def rollback(self):
            state["rolled_back"] = True
            self.connection.rollback()

        def close(self):
            self.connection.close()

    monkeypatch.setattr(interactions, "get_connection", lambda: BrokenConnection(original_get_connection()))

    with pytest.raises(RuntimeError, match="readback failed"):
        asyncio.run(
            interactions.update_interaction(interaction_id=interaction_id, body=InteractionUpdate(note="not committed"))
        )

    assert state["rolled_back"] is True


def test_db_connection_begin_serialized_write_reserves_sqlite_write_transaction():
    raw = sqlite3.connect(":memory:")
    conn = DbConnection(raw, kind="sqlite")

    conn.begin_serialized_write()

    assert raw.in_transaction is True
    conn.rollback()
    conn.close()


def test_postgres_patch_locks_row_before_merged_validation(monkeypatch):
    from app.routers.v1 import interactions

    statements = []

    class Cursor:
        rowcount = 1

        def __init__(self, row):
            self.row = row

        def fetchone(self):
            return self.row

    class PostgresConnection:
        kind = "postgres"

        def begin_serialized_write(self):
            statements.append("begin")

        def execute(self, sql, params=None):
            statements.append(sql)
            if sql.startswith("SELECT * FROM interactions"):
                return Cursor(
                    {
                        "id": 1,
                        "project_id": "proj-1",
                        "survival_result": "passed",
                        "disqualification_reason": None,
                    }
                )
            return Cursor(
                {
                    "id": 1,
                    "project_id": "proj-1",
                    "survival_result": "passed",
                    "disqualification_reason": None,
                    "note": "locked",
                }
            )

        def commit(self):
            statements.append("commit")

        def rollback(self):
            statements.append("rollback")

        def close(self):
            statements.append("close")

    monkeypatch.setattr(interactions, "get_connection", PostgresConnection)

    # 该处理器现为同步函数（FastAPI 自动交线程池执行），直接调用即可
    result = interactions.update_interaction(interaction_id=1, body=InteractionUpdate(note="locked"))

    assert result["ok"] is True
    assert statements[0] == "begin"
    assert statements[1].endswith(" FOR UPDATE")


def test_concurrent_reason_clear_and_disqualify_preserve_invariant(monkeypatch, client: TestClient):
    from app.routers.v1 import interactions

    created = client.post(
        "/api/v1/interactions",
        json={
            "project_id": "proj-1",
            "survival_result": "passed",
            "disqualification_reason": "Prior reason",
        },
    )
    interaction_id = created.json()["data"]["id"]
    first_has_lock = threading.Event()
    second_attempted_lock = threading.Event()
    connection_number = 0
    number_lock = threading.Lock()
    original_get_connection = interactions.get_connection

    class CoordinatedConnection:
        kind = "sqlite"

        def __init__(self, connection, number):
            self.connection = connection
            self.number = number

        def begin_serialized_write(self):
            if self.number == 1:
                self.connection.begin_serialized_write()
                first_has_lock.set()
                assert second_attempted_lock.wait(5)
            else:
                assert first_has_lock.wait(5)
                second_attempted_lock.set()
                self.connection.begin_serialized_write()

        def execute(self, sql, params=None):
            return self.connection.execute(sql, params)

        def commit(self):
            self.connection.commit()

        def rollback(self):
            self.connection.rollback()

        def close(self):
            self.connection.close()

    def coordinated_connection():
        nonlocal connection_number
        with number_lock:
            connection_number += 1
            number = connection_number
        raw = sqlite3.connect(settings.db_path, timeout=10)
        raw.row_factory = sqlite3.Row
        raw.execute("PRAGMA foreign_keys=ON")
        return CoordinatedConnection(DbConnection(raw, kind="sqlite"), number)

    monkeypatch.setattr(interactions, "get_connection", coordinated_connection)
    results = []

    def patch(body):
        try:
            results.append(
                asyncio.run(
                    interactions.update_interaction(interaction_id=interaction_id, body=InteractionUpdate(**body))
                )
            )
        except Exception as error:
            results.append(error)

    clear_thread = threading.Thread(target=patch, args=({"disqualification_reason": ""},))
    disqualify_thread = threading.Thread(target=patch, args=({"survival_result": "disqualified"},))
    clear_thread.start()
    assert first_has_lock.wait(5)
    disqualify_thread.start()
    clear_thread.join(10)
    disqualify_thread.join(10)

    assert not clear_thread.is_alive()
    assert not disqualify_thread.is_alive()
    assert sorted(getattr(result, "status_code", 200) for result in results) == [200, 422]
    conn = original_get_connection()
    try:
        row = conn.execute(
            "SELECT survival_result, disqualification_reason FROM interactions WHERE id = ?",
            (interaction_id,),
        ).fetchone()
        assert row["survival_result"] != "disqualified"
        assert not row["disqualification_reason"]
    finally:
        conn.close()


@pytest.mark.parametrize("method", ["post", "patch"])
@pytest.mark.parametrize("field", ["started_at", "ended_at"])
@pytest.mark.parametrize(
    "invalid_date",
    [
        pytest.param(0, id="unix-epoch-number"),
        pytest.param(86400, id="unix-day-number"),
        pytest.param(0.0, id="unix-epoch-float"),
        pytest.param(86400.0, id="unix-day-float"),
        pytest.param(True, id="boolean"),
        pytest.param("2026-07-01T00:00:00", id="midnight-datetime"),
        pytest.param("2026-07-01Z", id="timezone-suffix"),
        pytest.param("2026-07-01+00:00", id="timezone-offset"),
        pytest.param("2026-02-30", id="malformed-calendar-date"),
    ],
)
def test_interaction_api_rejects_non_exact_json_dates(
    client: TestClient, method: str, field: str, invalid_date: object
):
    if method == "post":
        response = client.post(
            "/api/v1/interactions",
            json={"project_id": "proj-1", field: invalid_date},
        )
    else:
        created = client.post("/api/v1/interactions", json={"project_id": "proj-1"})
        response = client.patch(
            f"/api/v1/interactions/{created.json()['data']['id']}",
            json={field: invalid_date},
        )

    assert response.status_code == 422


@pytest.mark.parametrize("method", ["post", "patch"])
@pytest.mark.parametrize("field", ["started_at", "ended_at"])
@pytest.mark.parametrize(
    ("valid_date", "expected"),
    [
        pytest.param("2026-07-01", "2026-07-01", id="exact-date"),
        pytest.param(None, None, id="null"),
    ],
)
def test_interaction_api_accepts_exact_json_dates_and_null(
    client: TestClient,
    method: str,
    field: str,
    valid_date: str | None,
    expected: str | None,
):
    if method == "post":
        response = client.post(
            "/api/v1/interactions",
            json={"project_id": "proj-1", field: valid_date},
        )
    else:
        created = client.post("/api/v1/interactions", json={"project_id": "proj-1"})
        response = client.patch(
            f"/api/v1/interactions/{created.json()['data']['id']}",
            json={field: valid_date},
        )

    assert response.status_code == 200, response.text
    actual = response.json()["data"][field]
    if method == "post" and field == "started_at" and valid_date is None:
        assert re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", actual)
    else:
        assert actual == expected


@pytest.mark.parametrize("model", [InteractionCreate, InteractionUpdate])
@pytest.mark.parametrize("field", ["started_at", "ended_at"])
def test_interaction_models_accept_date_objects_for_internal_construction(model, field):
    payload = {field: date(2026, 7, 1)}
    if model is InteractionCreate:
        payload["project_id"] = "proj-1"

    interaction = model(**payload)

    assert getattr(interaction, field) == date(2026, 7, 1)


@pytest.mark.parametrize("model", [InteractionCreate, InteractionUpdate])
@pytest.mark.parametrize("field", ["started_at", "ended_at"])
def test_interaction_models_reject_datetime_objects(model, field):
    payload = {field: datetime(2026, 7, 1)}
    if model is InteractionCreate:
        payload["project_id"] = "proj-1"

    with pytest.raises(ValueError):
        model(**payload)


def test_interaction_records_shadow_prediction_and_realized_outcome(client: TestClient):
    created = client.post(
        "/api/v1/interactions",
        json={
            "project_id": "proj-1",
            "wallet_cohort_id": "cohort-550e8400-e29b-41d4-a716-446655440000",
            "wallet_count": 2,
            "status": "active",
            "actual_hard_cost_usd": 4.5,
            "actual_time_minutes": 80,
        },
    )
    assert created.status_code == 200, created.text
    data = created.json()["data"]
    assert data["wallet_cohort_id"] == "cohort-550e8400-e29b-41d4-a716-446655440000"
    assert data["wallet_count"] == 2
    assert data["realized_net_usd"] == -4.5

    updated = client.patch(
        f"/api/v1/interactions/{data['id']}",
        json={
            "status": "done",
            "eligibility_result": "eligible",
            "survival_result": "passed",
            "reward_received_usd": 120,
            "claim_cost_usd": 1.5,
            "outcome_observed_at": "2026-07-15T12:00:00Z",
        },
    )
    assert updated.status_code == 200, updated.text
    outcome = updated.json()["data"]
    assert outcome["realized_net_usd"] == 114
    assert outcome["net_usd"] is None


@pytest.mark.parametrize(
    "payload",
    [
        {"eligibility_result": "eligible"},
        {"survival_result": "passed"},
        {"reward_received_usd": 0},
    ],
)
def test_create_outcome_fields_default_observed_at_to_utc(client, payload):
    response = client.post("/api/v1/interactions", json={"project_id": "proj-1", **payload})
    observed = datetime.fromisoformat(response.json()["data"]["outcome_observed_at"])
    assert observed.tzinfo is not None
    assert observed.utcoffset() == UTC.utcoffset(observed)


@pytest.mark.parametrize(
    "payload",
    [
        {"eligibility_result": "eligible"},
        {"survival_result": "passed"},
        {"reward_received_usd": 0},
    ],
)
def test_patch_outcome_fields_default_observed_at_to_utc(client, payload):
    created = client.post("/api/v1/interactions", json={"project_id": "proj-1"})
    response = client.patch(f"/api/v1/interactions/{created.json()['data']['id']}", json=payload)
    observed = datetime.fromisoformat(response.json()["data"]["outcome_observed_at"])
    assert observed.tzinfo is not None
    assert observed.utcoffset() == UTC.utcoffset(observed)


@pytest.mark.parametrize(
    "invalid",
    ["2026-07-15T12:00:00", "2026-07-15", 0, True],
)
def test_outcome_observed_at_requires_strict_timezone_datetime(client, invalid):
    response = client.post(
        "/api/v1/interactions",
        json={"project_id": "proj-1", "outcome_observed_at": invalid},
    )
    assert response.status_code == 422


def test_outcome_observed_at_preserves_chronology_across_patch(client):
    created = client.post(
        "/api/v1/interactions",
        json={
            "project_id": "proj-1",
            "eligibility_result": "eligible",
            "outcome_observed_at": "2026-07-15T11:00:00Z",
        },
    )
    patched = client.patch(
        f"/api/v1/interactions/{created.json()['data']['id']}",
        json={
            "reward_received_usd": 25,
            "outcome_observed_at": "2026-07-15T12:00:00Z",
        },
    )
    assert datetime.fromisoformat(patched.json()["data"]["outcome_observed_at"]) > datetime.fromisoformat(
        created.json()["data"]["outcome_observed_at"]
    )


def test_interaction_accepts_matching_optional_assessment(client: TestClient):
    conn = get_connection()
    conn.execute(
        """INSERT INTO opportunity_assessments (
               assessment_id, project_id, model_version, profile_version,
               assessment_json, decision_status, public_label,
               overall_confidence, scored_at, expires_at
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "assessment-1",
            "proj-1",
            "opportunity-v2.0",
            "low-cost-curated-multiwallet-v1",
            "{}",
            "actionable",
            "FARM",
            0.9,
            "2026-07-15T10:00:00Z",
            "2026-07-16T10:00:00Z",
        ),
    )
    conn.commit()
    conn.close()

    response = client.post(
        "/api/v1/interactions",
        json={
            "project_id": "proj-1",
            "opportunity_assessment_id": "assessment-1",
            "opportunity_model_version": "opportunity-v2.0",
            "opportunity_profile_version": "low-cost-curated-multiwallet-v1",
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["opportunity_assessment_id"] == "assessment-1"
    assert data["opportunity_model_version"] == "opportunity-v2.0"
    assert data["opportunity_profile_version"] == "low-cost-curated-multiwallet-v1"


def test_interaction_populates_canonical_versions_when_omitted(client: TestClient):
    conn = get_connection()
    conn.execute(
        """INSERT INTO opportunity_assessments (
               assessment_id, project_id, model_version, profile_version,
               assessment_json, decision_status, public_label,
               overall_confidence, scored_at, expires_at
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "assessment-canonical",
            "proj-1",
            "opportunity-v2.0",
            "low-cost-curated-multiwallet-v1",
            "{}",
            "watch",
            "WATCH",
            0.8,
            "2026-07-15T10:00:00Z",
            "2026-07-16T10:00:00Z",
        ),
    )
    conn.commit()
    conn.close()

    response = client.post(
        "/api/v1/interactions",
        json={
            "project_id": "proj-1",
            "opportunity_assessment_id": "assessment-canonical",
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert (
        data["opportunity_assessment_id"],
        data["opportunity_model_version"],
        data["opportunity_profile_version"],
    ) == (
        "assessment-canonical",
        "opportunity-v2.0",
        "low-cost-curated-multiwallet-v1",
    )


def test_create_rejects_assessment_model_mismatch_when_client_omits_model(
    client: TestClient,
):
    conn = get_connection()
    conn.execute(
        """INSERT INTO opportunity_assessments (
               assessment_id, project_id, model_version, profile_version,
               assessment_json, decision_status, public_label,
               overall_confidence, scored_at, expires_at
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "assessment-unsupported-model",
            "proj-1",
            "opportunity-v3.0",
            "low-cost-curated-multiwallet-v1",
            "{}",
            "watch",
            "WATCH",
            0.5,
            "2026-07-15T10:00:00Z",
            "2026-07-16T10:00:00Z",
        ),
    )
    conn.commit()
    conn.close()

    response = client.post(
        "/api/v1/interactions",
        json={
            "project_id": "proj-1",
            "opportunity_assessment_id": "assessment-unsupported-model",
        },
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "payload",
    [
        {"opportunity_model_version": "opportunity-v2.0"},
        {"opportunity_profile_version": "low-cost-curated-multiwallet-v1"},
        {
            "opportunity_model_version": "opportunity-v2.0",
            "opportunity_profile_version": "low-cost-curated-multiwallet-v1",
        },
    ],
)
def test_create_rejects_versions_without_assessment(client: TestClient, payload: dict[str, object]):
    response = client.post("/api/v1/interactions", json={"project_id": "proj-1", **payload})
    assert response.status_code == 422


@pytest.mark.parametrize(
    ("assessment_project", "assessment_profile", "request_profile"),
    [
        ("other-project", "low-cost-curated-multiwallet-v1", "low-cost-curated-multiwallet-v1"),
        ("proj-1", "other-profile", "low-cost-curated-multiwallet-v1"),
    ],
)
def test_interaction_rejects_mismatched_assessment(
    client: TestClient,
    assessment_project: str,
    assessment_profile: str,
    request_profile: str,
):
    conn = get_connection()
    conn.execute(
        """INSERT INTO opportunity_assessments (
               assessment_id, project_id, model_version, profile_version,
               assessment_json, decision_status, public_label,
               overall_confidence, scored_at, expires_at
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "assessment-mismatch",
            assessment_project,
            "opportunity-v2.0",
            assessment_profile,
            "{}",
            "watch",
            "WATCH",
            0.5,
            "2026-07-15T10:00:00Z",
            "2026-07-16T10:00:00Z",
        ),
    )
    conn.commit()
    conn.close()

    response = client.post(
        "/api/v1/interactions",
        json={
            "project_id": "proj-1",
            "opportunity_assessment_id": "assessment-mismatch",
            "opportunity_profile_version": request_profile,
        },
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "payload",
    [
        {"wallet_count": 0},
        {"wallet_count": 1.5},
        {"actual_hard_cost_usd": -0.01},
        {"actual_hard_cost_usd": "NaN"},
        {"actual_time_minutes": -1},
        {"reward_received_usd": -1},
        {"claim_cost_usd": -1},
        {"cost_usd": -1},
        {"hours_spent": -1},
        {"eligibility_result": "maybe"},
        {"survival_result": "failed"},
        {"opportunity_model_version": "opportunity-v3.0"},
        {"opportunity_profile_version": "other-profile"},
    ],
)
def test_interaction_rejects_invalid_calibration_values(client: TestClient, payload: dict[str, object]):
    response = client.post(
        "/api/v1/interactions",
        json={"project_id": "proj-1", **payload},
    )
    assert response.status_code == 422, response.text


def test_disqualified_survival_requires_reason(client: TestClient):
    response = client.post(
        "/api/v1/interactions",
        json={"project_id": "proj-1", "survival_result": "disqualified"},
    )
    assert response.status_code == 422

    accepted = client.post(
        "/api/v1/interactions",
        json={
            "project_id": "proj-1",
            "survival_result": "disqualified",
            "disqualification_reason": "Sybil filter",
        },
    )
    assert accepted.status_code == 200, accepted.text

    passed = client.patch(
        f"/api/v1/interactions/{accepted.json()['data']['id']}",
        json={"survival_result": "passed"},
    )
    assert passed.status_code == 200, passed.text
    assert passed.json()["data"]["disqualification_reason"] == "Sybil filter"


def test_patch_model_defers_disqualified_reason_check_until_locked_merge():
    update = InteractionUpdate(survival_result="disqualified")

    assert update.survival_result == "disqualified"


def test_disqualified_survival_reason_cannot_be_cleared(client: TestClient):
    created = client.post(
        "/api/v1/interactions",
        json={
            "project_id": "proj-1",
            "survival_result": "disqualified",
            "disqualification_reason": "Sybil filter",
        },
    )
    response = client.patch(
        f"/api/v1/interactions/{created.json()['data']['id']}",
        json={"disqualification_reason": ""},
    )
    assert response.status_code == 422


def test_linked_assessment_is_revalidated_on_version_update(client: TestClient):
    conn = get_connection()
    conn.execute(
        """INSERT INTO opportunity_assessments (
               assessment_id, project_id, model_version, profile_version,
               assessment_json, decision_status, public_label,
               overall_confidence, scored_at, expires_at
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "assessment-linked",
            "proj-1",
            "opportunity-v2.0",
            "other-profile",
            "{}",
            "watch",
            "WATCH",
            0.5,
            "2026-07-15T10:00:00Z",
            "2026-07-16T10:00:00Z",
        ),
    )
    conn.commit()
    conn.execute(
        """INSERT INTO interactions (
               project_id, status, opportunity_assessment_id,
               opportunity_profile_version
           ) VALUES (?, ?, ?, ?)""",
        ("proj-1", "active", "assessment-linked", "other-profile"),
    )
    interaction_id = conn.execute("SELECT id FROM interactions ORDER BY id DESC LIMIT 1").fetchone()["id"]
    conn.commit()
    conn.close()

    response = client.patch(
        f"/api/v1/interactions/{interaction_id}",
        json={"opportunity_profile_version": "low-cost-curated-multiwallet-v1"},
    )
    assert response.status_code == 422


def test_patch_switches_linkage_to_canonical_assessment_trio(client: TestClient):
    created = client.post("/api/v1/interactions", json={"project_id": "proj-1"})
    interaction_id = created.json()["data"]["id"]
    conn = get_connection()
    conn.execute(
        """INSERT INTO opportunity_assessments (
               assessment_id, project_id, model_version, profile_version,
               assessment_json, decision_status, public_label,
               overall_confidence, scored_at, expires_at
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "assessment-switch",
            "proj-1",
            "opportunity-v2.0",
            "low-cost-curated-multiwallet-v1",
            "{}",
            "watch",
            "WATCH",
            0.5,
            "2026-07-15T10:00:00Z",
            "2026-07-16T10:00:00Z",
        ),
    )
    conn.commit()
    conn.close()

    response = client.patch(
        f"/api/v1/interactions/{interaction_id}",
        json={"opportunity_assessment_id": "assessment-switch"},
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert (
        data["opportunity_assessment_id"],
        data["opportunity_model_version"],
        data["opportunity_profile_version"],
    ) == (
        "assessment-switch",
        "opportunity-v2.0",
        "low-cost-curated-multiwallet-v1",
    )


def test_patch_null_assessment_atomically_unlinks_trio(client: TestClient):
    conn = get_connection()
    conn.execute(
        """INSERT INTO interactions (
               project_id, status, opportunity_assessment_id,
               opportunity_model_version, opportunity_profile_version
           ) VALUES (?, ?, ?, ?, ?)""",
        (
            "proj-1",
            "active",
            "assessment-old",
            "opportunity-v2.0",
            "low-cost-curated-multiwallet-v1",
        ),
    )
    interaction_id = conn.execute("SELECT id FROM interactions ORDER BY id DESC LIMIT 1").fetchone()["id"]
    conn.commit()
    conn.close()

    response = client.patch(
        f"/api/v1/interactions/{interaction_id}",
        json={"opportunity_assessment_id": None},
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["opportunity_assessment_id"] is None
    assert data["opportunity_model_version"] is None
    assert data["opportunity_profile_version"] is None


@pytest.mark.parametrize(
    "payload",
    [
        {"opportunity_model_version": "opportunity-v2.0"},
        {"opportunity_model_version": None},
        {"opportunity_profile_version": "low-cost-curated-multiwallet-v1"},
        {"opportunity_profile_version": None},
        {
            "opportunity_assessment_id": None,
            "opportunity_model_version": "opportunity-v2.0",
        },
        {
            "opportunity_assessment_id": None,
            "opportunity_profile_version": None,
        },
    ],
)
def test_patch_rejects_partial_or_null_version_linkage(client: TestClient, payload: dict[str, object]):
    created = client.post("/api/v1/interactions", json={"project_id": "proj-1"})
    response = client.patch(f"/api/v1/interactions/{created.json()['data']['id']}", json=payload)
    assert response.status_code == 422


@pytest.mark.parametrize(
    ("assessment_id", "project_id", "model_version", "profile_version"),
    [
        (
            "assessment-other-project",
            "other-project",
            "opportunity-v2.0",
            "low-cost-curated-multiwallet-v1",
        ),
        (
            "assessment-other-model",
            "proj-1",
            "opportunity-v3.0",
            "low-cost-curated-multiwallet-v1",
        ),
        (
            "assessment-other-profile",
            "proj-1",
            "opportunity-v2.0",
            "other-profile",
        ),
    ],
)
def test_patch_rejects_assessment_with_wrong_project_model_or_profile(
    client: TestClient,
    assessment_id: str,
    project_id: str,
    model_version: str,
    profile_version: str,
):
    created = client.post("/api/v1/interactions", json={"project_id": "proj-1"})
    conn = get_connection()
    conn.execute(
        """INSERT INTO opportunity_assessments (
               assessment_id, project_id, model_version, profile_version,
               assessment_json, decision_status, public_label,
               overall_confidence, scored_at, expires_at
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            assessment_id,
            project_id,
            model_version,
            profile_version,
            "{}",
            "watch",
            "WATCH",
            0.5,
            "2026-07-15T10:00:00Z",
            "2026-07-16T10:00:00Z",
        ),
    )
    conn.commit()
    conn.close()
    response = client.patch(
        f"/api/v1/interactions/{created.json()['data']['id']}",
        json={"opportunity_assessment_id": assessment_id},
    )
    assert response.status_code == 422


@pytest.mark.parametrize("field", ["wallet_address", "device_id", "kyc_id"])
def test_interaction_rejects_sensitive_identity_fields(client: TestClient, field: str):
    response = client.post(
        "/api/v1/interactions",
        json={"project_id": "proj-1", field: "sensitive-value"},
    )
    assert response.status_code == 422


def test_create_generates_unique_canonical_uuid_cohort_ids(client: TestClient):
    first = client.post("/api/v1/interactions", json={"project_id": "proj-1"})
    second = client.post("/api/v1/interactions", json={"project_id": "proj-1"})
    first_id = first.json()["data"]["wallet_cohort_id"]
    second_id = second.json()["data"]["wallet_cohort_id"]
    pattern = re.compile(r"cohort-[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z")
    assert pattern.fullmatch(first_id)
    assert pattern.fullmatch(second_id)
    assert first_id != second_id
    assert uuid.UUID(first_id.removeprefix("cohort-")).version == 4


def test_supplied_uuid_cohort_id_is_canonicalized_to_lowercase(client: TestClient):
    response = client.post(
        "/api/v1/interactions",
        json={
            "project_id": "proj-1",
            "wallet_cohort_id": "cohort-550E8400-E29B-41D4-A716-446655440000",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["wallet_cohort_id"] == "cohort-550e8400-e29b-41d4-a716-446655440000"


@pytest.mark.parametrize(
    "wallet_cohort_id",
    [
        "cohort-0x1234567890abcdef1234567890abcdef12345678",
        "cohort-0X1234567890ABCDEF1234567890ABCDEF12345678",
        "cohort-4Nd1mYpW8fJ6K2vT9qR7sL3xC5bH1zUe",
        "cohort-AbCdEfGhJkMnPqRsTuVwXyZ23456789ABCDE",
        "cohort-benignArbitraryToken1234567890ABCDE",
        "cohort-123e4567e89b12d3a456426614174000",
        "cohort-123e4567-e89b-12d3-a456-42661417400z",
        "cohort-123e4567-e89b-12d3-a456-426614174000-extra",
        "wallet-123e4567-e89b-12d3-a456-426614174000",
        "cohort-local-001",
    ],
)
def test_interaction_rejects_non_uuid_cohort_ids(client: TestClient, wallet_cohort_id: str):
    response = client.post(
        "/api/v1/interactions",
        json={"project_id": "proj-1", "wallet_cohort_id": wallet_cohort_id},
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "cohort_uuid",
    [
        "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
        "6fa459ea-ee8a-3ca4-894e-db77e160355e",
        "21f7f8de-8051-5b89-8680-0195ef798b6a",
        "00000000-0000-0000-0000-000000000000",
        "550e8400-e29b-41d4-2716-446655440000",
    ],
)
def test_interaction_rejects_non_v4_or_non_rfc_cohort_uuid(client: TestClient, cohort_uuid: str):
    response = client.post(
        "/api/v1/interactions",
        json={"project_id": "proj-1", "wallet_cohort_id": f"cohort-{cohort_uuid}"},
    )
    assert response.status_code == 422


def test_patch_validates_and_canonicalizes_supplied_cohort_id(client: TestClient):
    created = client.post("/api/v1/interactions", json={"project_id": "proj-1"})
    response = client.patch(
        f"/api/v1/interactions/{created.json()['data']['id']}",
        json={"wallet_cohort_id": "cohort-550E8400-E29B-41D4-A716-446655440000"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["wallet_cohort_id"] == "cohort-550e8400-e29b-41d4-a716-446655440000"


def test_explicit_null_cohort_id_is_rejected_on_create_and_patch(client: TestClient):
    created = client.post("/api/v1/interactions", json={"project_id": "proj-1"})
    rejected_create = client.post(
        "/api/v1/interactions",
        json={"project_id": "proj-1", "wallet_cohort_id": None},
    )
    rejected_patch = client.patch(
        f"/api/v1/interactions/{created.json()['data']['id']}",
        json={"wallet_cohort_id": None},
    )
    assert rejected_create.status_code == 422
    assert rejected_patch.status_code == 422


def test_free_text_fields_warn_against_sensitive_data():
    from app.routers.v1.interactions import InteractionCreate, InteractionUpdate

    create_properties = InteractionCreate.model_json_schema()["properties"]
    update_properties = InteractionUpdate.model_json_schema()["properties"]
    for field in ("user_id", "activities", "note", "disqualification_reason"):
        assert "sensitive" in create_properties[field]["description"].lower()
        assert "wallet" in create_properties[field]["description"].lower()
        assert "sensitive" in update_properties[field]["description"].lower()
        assert "wallet" in update_properties[field]["description"].lower()


@pytest.mark.parametrize("field", ["user_id", "activities", "note", "disqualification_reason"])
@pytest.mark.parametrize(
    "address",
    [
        "0x1234567890abcdef1234567890abcdef12345678",
        _valid_bech32("sei"),
        _valid_bech32("bc", bech32m=True),
        _base58_encode(bytes(range(32))),
        "a" * 64,
    ],
)
def test_create_rejects_wallet_address_in_each_free_text_field(client: TestClient, field: str, address: str):
    response = client.post(
        "/api/v1/interactions",
        json={"project_id": "proj-1", field: f"safe prefix ({address}) safe suffix"},
    )
    assert response.status_code == 422


@pytest.mark.parametrize("field", ["user_id", "activities", "note", "disqualification_reason"])
@pytest.mark.parametrize(
    "address",
    [
        "0x1234567890abcdef1234567890abcdef12345678",
        _valid_bech32("cosmos"),
        _valid_bech32("eth", bech32m=True),
        _base58_encode(bytes(reversed(range(32)))),
        "f" * 64,
    ],
)
def test_patch_rejects_wallet_address_in_each_free_text_field(client: TestClient, field: str, address: str):
    created = client.post("/api/v1/interactions", json={"project_id": "proj-1"})
    response = client.patch(
        f"/api/v1/interactions/{created.json()['data']['id']}",
        json={field: f"safe prefix [{address}] safe suffix"},
    )
    assert response.status_code == 422


@pytest.mark.parametrize("field", ["user_id", "activities", "note", "disqualification_reason"])
def test_free_text_fields_allow_safe_protocol_lookalikes(client: TestClient, field: str):
    valid_bech32 = _valid_bech32("sei")
    invalid_bech32 = valid_bech32[0].upper() + valid_bech32[1:]
    decoded_31_bytes = _base58_encode(bytes(range(31)))
    tx_hash = "a" * 64
    evm_adjacent = "prefix0x1234567890abcdef1234567890abcdef12345678suffix"
    safe_value = f"Invalid encoding {invalid_bech32}; token {decoded_31_bytes}; tx: {tx_hash}; adjacent {evm_adjacent}"
    created = client.post(
        "/api/v1/interactions",
        json={"project_id": "proj-1", field: safe_value},
    )
    assert created.status_code == 200, created.text
    updated = client.patch(
        f"/api/v1/interactions/{created.json()['data']['id']}",
        json={field: f"Updated {safe_value}"},
    )
    assert updated.status_code == 200, updated.text


def test_invalid_bech32_checksum_is_not_rejected_as_base58(client: TestClient):
    valid_bech32 = _valid_bech32("sei")
    invalid_checksum = valid_bech32[:-1] + ("q" if valid_bech32[-1] != "q" else "p")
    response = client.post(
        "/api/v1/interactions",
        json={"project_id": "proj-1", "note": invalid_checksum},
    )
    assert response.status_code == 200, response.text


def test_checksum_valid_punctuation_hrp_bech32_is_rejected(client: TestClient):
    address = _valid_bech32("web3!wallet")
    response = client.post(
        "/api/v1/interactions",
        json={"project_id": "proj-1", "note": f"candidate ({address})"},
    )
    assert response.status_code == 422


def test_invalid_punctuation_hrp_bech32_candidate_is_allowed(client: TestClient):
    valid = _valid_bech32("web3!wallet")
    invalid_checksum = valid[:-1] + ("q" if valid[-1] != "q" else "p")
    response = client.post(
        "/api/v1/interactions",
        json={"project_id": "proj-1", "note": f"candidate ({invalid_checksum})"},
    )
    assert response.status_code == 200, response.text


def test_free_text_fields_have_bounded_lengths():
    from app.routers.v1.interactions import InteractionCreate, InteractionUpdate

    for schema in (
        InteractionCreate.model_json_schema(),
        InteractionUpdate.model_json_schema(),
    ):
        for field in ("user_id", "activities", "note", "disqualification_reason"):
            variants = schema["properties"][field]["anyOf"]
            string_schema = next(item for item in variants if item.get("type") == "string")
            assert string_schema["maxLength"] > 0


@pytest.mark.parametrize(
    ("field", "max_length"),
    [
        ("user_id", 255),
        ("activities", 1000),
        ("note", 2000),
        ("disqualification_reason", 1000),
    ],
)
def test_create_and_patch_enforce_free_text_length_boundaries(client: TestClient, field: str, max_length: int):
    at_limit = "z" * max_length
    created = client.post(
        "/api/v1/interactions",
        json={"project_id": "proj-1", field: at_limit},
    )
    assert created.status_code == 200, created.text

    interaction_id = created.json()["data"]["id"]
    patched = client.patch(f"/api/v1/interactions/{interaction_id}", json={field: at_limit})
    assert patched.status_code == 200, patched.text

    rejected_create = client.post(
        "/api/v1/interactions",
        json={"project_id": "proj-1", field: at_limit + "z"},
    )
    rejected_patch = client.patch(f"/api/v1/interactions/{interaction_id}", json={field: at_limit + "z"})
    assert rejected_create.status_code == 422
    assert rejected_patch.status_code == 422


@pytest.mark.parametrize("raw_length", [31, 33])
def test_base58_screening_allows_tokens_that_do_not_decode_to_exactly_32_bytes(client: TestClient, raw_length: int):
    token = _base58_encode(bytes(range(raw_length)))
    response = client.post(
        "/api/v1/interactions",
        json={"project_id": "proj-1", "note": f"Observed token ({token})."},
    )
    assert response.status_code == 200, response.text


def test_base58_screening_does_not_match_inside_larger_alphanumeric_token(
    client: TestClient,
):
    token = _base58_encode(bytes(range(32)))
    response = client.post(
        "/api/v1/interactions",
        json={"project_id": "proj-1", "note": f"prefix{token}suffix"},
    )
    assert response.status_code == 200, response.text


@pytest.mark.parametrize(
    "value",
    [
        "a" * 64,
        f"secret ({'b' * 64})",
        f"transaction id is {'c' * 64}",
    ],
)
def test_unlabeled_private_key_shaped_token_is_rejected(client: TestClient, value: str):
    response = client.post("/api/v1/interactions", json={"project_id": "proj-1", "note": value})
    assert response.status_code == 422


@pytest.mark.parametrize("label", ["tx:", "transaction:", "TX:", "Transaction:"])
def test_explicitly_labeled_transaction_hash_is_allowed(client: TestClient, label: str):
    tx_hash = "d" * 64
    response = client.post(
        "/api/v1/interactions",
        json={"project_id": "proj-1", "note": f"Confirmed {label} {tx_hash}"},
    )
    assert response.status_code == 200, response.text


@pytest.mark.parametrize("prefix", ["notx:", "context tx: identifier ", "transaction-id:"])
def test_private_key_shaped_token_requires_an_explicit_adjacent_transaction_label(client: TestClient, prefix: str):
    response = client.post(
        "/api/v1/interactions",
        json={"project_id": "proj-1", "note": prefix + "e" * 64},
    )
    assert response.status_code == 422


def test_evm_token_boundaries_allow_hash_and_adjacent_identifier(client: TestClient):
    tx_hash = "0x" + "a" * 64
    adjacent = "prefix0x1234567890abcdef1234567890abcdef12345678suffix"
    response = client.post(
        "/api/v1/interactions",
        json={"project_id": "proj-1", "activities": f"tx: {tx_hash} {adjacent}"},
    )
    assert response.status_code == 200, response.text


def test_wallet_count_defaults_to_one_and_rejects_explicit_null(client: TestClient):
    created = client.post("/api/v1/interactions", json={"project_id": "proj-1"})
    assert created.status_code == 200
    assert created.json()["data"]["wallet_count"] == 1

    rejected_create = client.post(
        "/api/v1/interactions",
        json={"project_id": "proj-1", "wallet_count": None},
    )
    assert rejected_create.status_code == 422
    rejected_patch = client.patch(
        f"/api/v1/interactions/{created.json()['data']['id']}",
        json={"wallet_count": None},
    )
    assert rejected_patch.status_code == 422


def test_init_db_adds_outcome_columns_to_existing_interactions_table(tmp_path):
    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """CREATE TABLE interactions (
                   id INTEGER PRIMARY KEY,
                   project_id TEXT NOT NULL,
                   status TEXT,
                   started_at TEXT
               )"""
        )
        init_db(conn)
        init_db(conn)
        columns = {row[1] for row in conn.execute("PRAGMA table_info(interactions)").fetchall()}
    finally:
        conn.close()

    assert {
        "wallet_cohort_id",
        "wallet_count",
        "actual_hard_cost_usd",
        "actual_time_minutes",
        "eligibility_result",
        "survival_result",
        "disqualification_reason",
        "reward_received_usd",
        "claim_cost_usd",
        "opportunity_assessment_id",
        "opportunity_model_version",
        "opportunity_profile_version",
        "outcome_observed_at",
    } <= columns


_COHORT_UUID4 = re.compile(
    r"^cohort-[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_SENSITIVE_RESPONSE_KEYS = frozenset(
    {
        "wallet_address",
        "private_key",
        "secret",
        "mnemonic",
        "seed_phrase",
        "device_id",
        "kyc_id",
    }
)


def _seed_supported_assessment(assessment_id: str = "assessment-lifecycle") -> str:
    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO opportunity_assessments (
                   assessment_id, project_id, model_version, profile_version,
                   assessment_json, decision_status, public_label,
                   overall_confidence, scored_at, expires_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                assessment_id,
                "proj-1",
                "opportunity-v2.0",
                "low-cost-curated-multiwallet-v1",
                "{}",
                "actionable",
                "FARM",
                0.9,
                "2026-07-15T10:00:00Z",
                "2026-07-16T10:00:00Z",
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return assessment_id


def _assert_no_sensitive_response_material(payload: object) -> None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            assert key not in _SENSITIVE_RESPONSE_KEYS
            assert "wallet_address" not in key.lower()
            assert "private_key" not in key.lower()
            _assert_no_sensitive_response_material(value)
        return
    if isinstance(payload, list):
        for item in payload:
            _assert_no_sensitive_response_material(item)
        return
    if isinstance(payload, str):
        assert re.search(r"(?<![0-9a-z])0x[0-9a-f]{40}(?![0-9a-z])", payload, re.IGNORECASE) is None
        assert re.fullmatch(r"[0-9a-f]{64}", payload, re.IGNORECASE) is None


def test_planned_interaction_accepts_supported_assessment_linkage(client: TestClient):
    assessment_id = _seed_supported_assessment("assessment-planned-ok")

    response = client.post(
        "/api/v1/interactions",
        json={
            "project_id": "proj-1",
            "status": "planned",
            "opportunity_assessment_id": assessment_id,
            "opportunity_model_version": "opportunity-v2.0",
            "opportunity_profile_version": "low-cost-curated-multiwallet-v1",
        },
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["status"] == "planned"
    assert data["opportunity_assessment_id"] == assessment_id
    assert data["opportunity_model_version"] == "opportunity-v2.0"
    assert data["opportunity_profile_version"] == "low-cost-curated-multiwallet-v1"
    assert _COHORT_UUID4.fullmatch(data["wallet_cohort_id"])
    _assert_no_sensitive_response_material(response.json())


@pytest.mark.parametrize(
    ("assessment_project", "model_version", "profile_version"),
    [
        ("other-project", "opportunity-v2.0", "low-cost-curated-multiwallet-v1"),
        ("proj-1", "opportunity-v3.0", "low-cost-curated-multiwallet-v1"),
        ("proj-1", "opportunity-v2.0", "other-profile"),
    ],
)
def test_planned_interaction_rejects_project_model_or_profile_mismatch(
    client: TestClient,
    assessment_project: str,
    model_version: str,
    profile_version: str,
):
    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO opportunity_assessments (
                   assessment_id, project_id, model_version, profile_version,
                   assessment_json, decision_status, public_label,
                   overall_confidence, scored_at, expires_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "assessment-planned-mismatch",
                assessment_project,
                model_version,
                profile_version,
                "{}",
                "watch",
                "WATCH",
                0.5,
                "2026-07-15T10:00:00Z",
                "2026-07-16T10:00:00Z",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    response = client.post(
        "/api/v1/interactions",
        json={
            "project_id": "proj-1",
            "status": "planned",
            "opportunity_assessment_id": "assessment-planned-mismatch",
            "opportunity_model_version": "opportunity-v2.0",
            "opportunity_profile_version": "low-cost-curated-multiwallet-v1",
        },
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    ("from_status", "to_status"),
    [
        ("planned", "active"),
        ("planned", "abandoned"),
        ("active", "done"),
        ("active", "abandoned"),
    ],
)
def test_allowed_lifecycle_transitions_succeed(
    client: TestClient,
    from_status: str,
    to_status: str,
):
    created = client.post(
        "/api/v1/interactions",
        json={"project_id": "proj-1", "status": from_status},
    )
    assert created.status_code == 200, created.text
    interaction_id = created.json()["data"]["id"]

    response = client.patch(
        f"/api/v1/interactions/{interaction_id}",
        json={"status": to_status},
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["status"] == to_status
    _assert_no_sensitive_response_material(response.json())


@pytest.mark.parametrize(
    ("from_status", "to_status"),
    [
        ("planned", "done"),
        ("active", "planned"),
        ("done", "planned"),
        ("done", "active"),
        ("done", "abandoned"),
        ("abandoned", "planned"),
        ("abandoned", "active"),
        ("abandoned", "done"),
    ],
)
def test_disallowed_lifecycle_transitions_are_rejected(
    client: TestClient,
    from_status: str,
    to_status: str,
):
    created = client.post(
        "/api/v1/interactions",
        json={"project_id": "proj-1", "status": from_status},
    )
    assert created.status_code == 200, created.text
    interaction_id = created.json()["data"]["id"]
    assert created.json()["data"]["status"] == from_status

    response = client.patch(
        f"/api/v1/interactions/{interaction_id}",
        json={"status": to_status},
    )
    assert response.status_code == 422, response.text


def test_terminal_statuses_reject_every_outbound_transition(client: TestClient):
    for terminal in ("done", "abandoned"):
        created = client.post(
            "/api/v1/interactions",
            json={"project_id": "proj-1", "status": terminal},
        )
        assert created.status_code == 200, created.text
        interaction_id = created.json()["data"]["id"]

        for target in ("planned", "active", "done", "abandoned"):
            if target == terminal:
                continue
            response = client.patch(
                f"/api/v1/interactions/{interaction_id}",
                json={"status": target},
            )
            assert response.status_code == 422, (terminal, target, response.text)


def test_outcome_fields_round_trip_through_create_and_patch(client: TestClient):
    assessment_id = _seed_supported_assessment("assessment-outcome-roundtrip")
    create_payload = {
        "project_id": "proj-1",
        "status": "planned",
        "wallet_count": 2,
        "actual_hard_cost_usd": 3.25,
        "actual_time_minutes": 45,
        "eligibility_result": "eligible",
        "survival_result": "passed",
        "reward_received_usd": 10.5,
        "claim_cost_usd": 0.75,
        "outcome_observed_at": "2026-07-15T12:30:00Z",
        "opportunity_assessment_id": assessment_id,
        "opportunity_model_version": "opportunity-v2.0",
        "opportunity_profile_version": "low-cost-curated-multiwallet-v1",
    }
    created = client.post("/api/v1/interactions", json=create_payload)
    assert created.status_code == 200, created.text
    data = created.json()["data"]
    for key, value in create_payload.items():
        if key == "outcome_observed_at":
            assert datetime.fromisoformat(data[key]).astimezone(UTC) == datetime(
                2026, 7, 15, 12, 30, tzinfo=UTC
            )
        else:
            assert data[key] == value
    assert _COHORT_UUID4.fullmatch(data["wallet_cohort_id"])
    assert abs(data["realized_net_usd"] - (10.5 - 3.25 - 0.75)) < 1e-9
    _assert_no_sensitive_response_material(created.json())

    patch_payload = {
        "status": "active",
        "actual_hard_cost_usd": 5.0,
        "actual_time_minutes": 90,
        "eligibility_result": "ineligible",
        "survival_result": "disqualified",
        "disqualification_reason": "Sybil cluster",
        "reward_received_usd": 0,
        "claim_cost_usd": 0,
        "outcome_observed_at": "2026-07-16T09:00:00Z",
    }
    patched = client.patch(f"/api/v1/interactions/{data['id']}", json=patch_payload)
    assert patched.status_code == 200, patched.text
    outcome = patched.json()["data"]
    for key, value in patch_payload.items():
        if key == "outcome_observed_at":
            assert datetime.fromisoformat(outcome[key]).astimezone(UTC) == datetime(
                2026, 7, 16, 9, 0, tzinfo=UTC
            )
        else:
            assert outcome[key] == value
    assert outcome["opportunity_assessment_id"] == assessment_id
    assert abs(outcome["realized_net_usd"] - (0 - 5.0 - 0)) < 1e-9
    _assert_no_sensitive_response_material(patched.json())


@pytest.mark.parametrize(
    "wallet_shaped",
    [
        "0x1234567890abcdef1234567890abcdef12345678",
        "wallet-local-1",
        "my-wallet",
    ],
)
def test_wallet_shaped_cohort_values_are_rejected(client: TestClient, wallet_shaped: str):
    """Reject cohort identifiers that look like wallets or non-cohort labels.

    UUID-shaped invalids are covered by test_interaction_rejects_non_uuid_cohort_ids.
    """
    response = client.post(
        "/api/v1/interactions",
        json={"project_id": "proj-1", "wallet_cohort_id": wallet_shaped},
    )
    assert response.status_code == 422


def test_interaction_responses_never_expose_wallet_or_secret_fields(client: TestClient):
    assessment_id = _seed_supported_assessment("assessment-privacy")
    created = client.post(
        "/api/v1/interactions",
        json={
            "project_id": "proj-1",
            "status": "planned",
            "opportunity_assessment_id": assessment_id,
            "note": "Tracked via local cohort only",
            "activities": "bridge and swap checklist",
        },
    )
    assert created.status_code == 200, created.text
    listed = client.get("/api/v1/projects/proj-1/interactions")
    assert listed.status_code == 200, listed.text
    _assert_no_sensitive_response_material(created.json())
    _assert_no_sensitive_response_material(listed.json())
    assert "wallet_address" not in created.text.lower()
    assert "private_key" not in created.text.lower()
    assert "mnemonic" not in created.text.lower()
