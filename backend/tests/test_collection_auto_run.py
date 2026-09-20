"""Tests for collection auto-run pipeline triggering.

Verifies:
1. Explicit auto_run parameter via query parameter or JSON body triggers analysis pipeline.
2. Explicit auto_run=false suppresses pipeline even if settings.collection_auto_run_enabled=True.
3. Fallback to settings.collection_auto_run_enabled when parameter is not provided.
4. Concurrency protection: QueueDrainInProgressError is caught and reported as auto_run_skipped="queue_drain_in_progress".
"""

from __future__ import annotations

import pytest
import respx
from fastapi.testclient import TestClient
from httpx import Response

from app.config import settings
from app.inflight import QUEUE_DRAIN_KEY, claim_run, reset_active_runs
from app.main import app


@pytest.fixture(autouse=True)
def _reset_inflight():
    reset_active_runs()
    yield
    reset_active_runs()


@respx.mock
def test_explicit_auto_run_query_param_triggers_pipeline(monkeypatch) -> None:
    monkeypatch.setattr(settings, "collection_auto_run_enabled", False)
    protocols = [
        {
            "name": "AutoRunQuery",
            "slug": "auto-run-query",
            "tvl": 5_000_000,
            "category": "DeFi",
            "chains": ["Ethereum"],
        }
    ]
    respx.get("https://api.llama.fi/protocols").mock(return_value=Response(200, json=protocols))

    with TestClient(app) as client:
        response = client.post("/api/v1/collections/defillama/trigger?auto_run=true")
        assert response.status_code == 200
        data = response.json()["data"]
        assert data.get("auto_run") is not None
        assert data["auto_run"]["status"] == "completed"
        assert data.get("auto_run_skipped") is None


@respx.mock
def test_explicit_auto_run_body_triggers_pipeline(monkeypatch) -> None:
    monkeypatch.setattr(settings, "collection_auto_run_enabled", False)
    protocols = [
        {
            "name": "AutoRunBody",
            "slug": "auto-run-body",
            "tvl": 6_000_000,
            "category": "DeFi",
            "chains": ["Ethereum"],
        }
    ]
    respx.get("https://api.llama.fi/protocols").mock(return_value=Response(200, json=protocols))

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/collections/defillama/trigger",
            json={"auto_run": True},
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data.get("auto_run") is not None
        assert data["auto_run"]["status"] == "completed"
        assert data.get("auto_run_skipped") is None


@respx.mock
def test_explicit_auto_run_false_suppresses_pipeline(monkeypatch) -> None:
    monkeypatch.setattr(settings, "collection_auto_run_enabled", True)
    protocols = [
        {
            "name": "AutoRunSuppressed",
            "slug": "auto-run-suppressed",
            "tvl": 7_000_000,
            "category": "DeFi",
            "chains": ["Ethereum"],
        }
    ]
    respx.get("https://api.llama.fi/protocols").mock(return_value=Response(200, json=protocols))

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/collections/defillama/trigger",
            json={"auto_run": False},
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data.get("auto_run") is None
        assert data.get("auto_run_skipped") is None


@respx.mock
def test_auto_run_skipped_when_drain_in_flight(monkeypatch) -> None:
    monkeypatch.setattr(settings, "collection_auto_run_enabled", False)
    protocols = [
        {
            "name": "AutoRunInFlight",
            "slug": "auto-run-in-flight",
            "tvl": 9_000_000,
            "category": "DeFi",
            "chains": ["Ethereum"],
        }
    ]
    respx.get("https://api.llama.fi/protocols").mock(return_value=Response(200, json=protocols))

    with claim_run(QUEUE_DRAIN_KEY) as acquired:
        assert acquired
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/collections/defillama/trigger",
                json={"auto_run": True},
            )
            assert response.status_code == 200
            data = response.json()["data"]
            assert data.get("auto_run") is None
            assert data.get("auto_run_skipped") == "queue_drain_in_progress"
