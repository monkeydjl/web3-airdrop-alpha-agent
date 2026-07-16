"""Tests for API key auth and quarantine helpers."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db import init_db
from app.main import create_app
from app.quarantine import list_quarantined, quarantine_raw, release_quarantine


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(settings, "db_path", str(db_path))
    monkeypatch.setattr(settings, "api_key", "")
    monkeypatch.setattr(settings, "app_env", "testing")
    monkeypatch.setattr(settings, "enable_feedback_system", True)
    init_db()
    app = create_app(db_override=lambda: None)
    return TestClient(app)


def test_health_includes_flags(client: TestClient):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert "db_backend" in body
    assert "feedback_enabled" in body
    assert "quarantined_raw" in body


def test_auth_blocks_when_api_key_set(tmp_path, monkeypatch):
    db_path = tmp_path / "auth.db"
    monkeypatch.setattr(settings, "db_path", str(db_path))
    monkeypatch.setattr(settings, "api_key", "secret-test-key")
    monkeypatch.setattr(settings, "app_env", "testing")
    init_db()
    app = create_app(db_override=lambda: None)
    c = TestClient(app)

    denied = c.get("/api/v1/projects")
    assert denied.status_code == 401

    ok_health = c.get("/health")
    assert ok_health.status_code == 200

    allowed = c.get("/api/v1/projects", headers={"X-API-Key": "secret-test-key"})
    assert allowed.status_code == 200


def test_quarantine_roundtrip(tmp_path, monkeypatch):
    db_path = tmp_path / "q.db"
    monkeypatch.setattr(settings, "db_path", str(db_path))
    monkeypatch.setattr(settings, "app_env", "testing")
    init_db()
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        INSERT INTO raw_projects (
            raw_id, source_id, dedup_key, raw_data, discovered_at,
            processed, discovery_score
        ) VALUES (?, ?, ?, ?, ?, 0, ?)
        """,
        (
            "raw-q-1",
            "defillama",
            "noise::defi",
            '{"name":"Uniswap V4","sector":"Dexs"}',
            datetime.now(UTC).isoformat(),
            0.9,
        ),
    )
    conn.commit()
    conn.close()

    assert quarantine_raw("raw-q-1", "test-reason")
    items = list_quarantined()
    assert any(i["raw_id"] == "raw-q-1" for i in items)
    assert release_quarantine("raw-q-1")
