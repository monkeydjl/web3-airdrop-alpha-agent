"""Tests for the Alchemy Notify webhook handler."""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

from app.collectors.persistence import CollectionRepository
from app.config import settings
from app.db import init_db
from app.main import create_app

SIGNING_KEY = "test_signing_key"


@pytest.fixture
def client(tmp_path):
    """Create a test client with an isolated database."""
    db_path = tmp_path / "test.db"
    prev_db_path = settings.db_path
    settings.db_path = str(db_path)
    init_db()
    app = create_app(db_override=lambda: None)
    yield TestClient(app)
    settings.db_path = prev_db_path


def _sign(body: bytes, key: str = SIGNING_KEY) -> str:
    """Compute the Alchemy webhook HMAC-SHA256 signature."""
    return hmac.new(key.encode(), body, hashlib.sha256).hexdigest()


def _address_activity_payload(
    address: str = "0xabc1234567890abcdef1234567890abcdef1234",
) -> dict:
    """Build a sample ADDRESS_ACTIVITY webhook payload."""
    return {
        "webhookId": "wh_test_001",
        "id": "evt_test_001",
        "createdAt": "2024-01-01T00:00:00.000Z",
        "type": "ADDRESS_ACTIVITY",
        "event": {
            "data": {
                "address": address,
                "transactionHash": "0xdef4567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
                "blockNumber": "0x1234567",
                "from": "0x1111111111111111111111111111111111111111",
                "to": address,
                "value": "0xde0b6b3a7640000",  # 1 ETH in wei
                "asset": "ETH",
                "category": "external",
            },
            "metadata": {
                "blockTimestamp": "2024-01-01T00:00:00.000Z",
            },
        },
    }


class TestAlchemyWebhook:
    def test_webhook_disabled_without_api_key(self, client: TestClient, monkeypatch) -> None:
        """Returns 503 when alchemy_api_key is empty."""
        monkeypatch.setattr(settings, "alchemy_api_key", "")
        body = json.dumps(_address_activity_payload()).encode()
        response = client.post(
            "/api/v1/webhook/alchemy",
            content=body,
            headers={"x-alchemy-signature": _sign(body)},
        )
        assert response.status_code == 503
        data = response.json()
        assert data["ok"] is False
        assert data["error"]["code"] == "WEBHOOK_NOT_CONFIGURED"

    def test_webhook_invalid_signature(self, client: TestClient, monkeypatch) -> None:
        """Returns 401 when x-alchemy-signature doesn't match."""
        monkeypatch.setattr(settings, "alchemy_api_key", SIGNING_KEY)
        body = json.dumps(_address_activity_payload()).encode()
        response = client.post(
            "/api/v1/webhook/alchemy",
            content=body,
            headers={"x-alchemy-signature": "0xbadsignature"},
        )
        assert response.status_code == 401
        data = response.json()
        assert data["ok"] is False
        assert data["error"]["code"] == "INVALID_SIGNATURE"

    def test_webhook_missing_signature(self, client: TestClient, monkeypatch) -> None:
        """Returns 401 when x-alchemy-signature header is absent."""
        monkeypatch.setattr(settings, "alchemy_api_key", SIGNING_KEY)
        body = json.dumps(_address_activity_payload()).encode()
        response = client.post(
            "/api/v1/webhook/alchemy",
            content=body,
        )
        assert response.status_code == 401
        data = response.json()
        assert data["ok"] is False
        assert data["error"]["code"] == "INVALID_SIGNATURE"

    def test_webhook_valid_address_activity(self, client: TestClient, monkeypatch) -> None:
        """Valid ADDRESS_ACTIVITY webhook creates RawDiscovery and persists it."""
        monkeypatch.setattr(settings, "alchemy_api_key", SIGNING_KEY)
        payload = _address_activity_payload()
        body = json.dumps(payload).encode()
        response = client.post(
            "/api/v1/webhook/alchemy",
            content=body,
            headers={
                "x-alchemy-signature": _sign(body),
                "Content-Type": "application/json",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["data"]["event_id"] == "evt_test_001"
        assert data["data"]["processed"] is True

        # Verify discovery was persisted
        discoveries = client.get("/api/v1/discoveries")
        assert discoveries.status_code == 200
        items = discoveries.json()["data"]["items"]
        assert len(items) >= 1
        item = items[0]
        assert item["source_id"] == "alchemy_webhook"
        assert item["discovery_score"] <= 0.28
        assert item["stage"] == "mainnet"

    def test_webhook_custom_type(self, client: TestClient, monkeypatch) -> None:
        """CUSTOM webhook type works."""
        monkeypatch.setattr(settings, "alchemy_api_key", SIGNING_KEY)
        payload = _address_activity_payload()
        payload["type"] = "CUSTOM"
        payload["id"] = "evt_custom_001"
        body = json.dumps(payload).encode()
        response = client.post(
            "/api/v1/webhook/alchemy",
            content=body,
            headers={
                "x-alchemy-signature": _sign(body),
                "Content-Type": "application/json",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["data"]["event_id"] == "evt_custom_001"
        assert data["data"]["processed"] is True

    def test_webhook_noise_contract_filtered(self, client: TestClient, monkeypatch) -> None:
        """USDT/USDC addresses are filtered out."""
        monkeypatch.setattr(settings, "alchemy_api_key", SIGNING_KEY)
        payload = _address_activity_payload(
            address="0xdac17f958d2ee523a2206206994597c13d831ec7",  # USDT
        )
        body = json.dumps(payload).encode()
        response = client.post(
            "/api/v1/webhook/alchemy",
            content=body,
            headers={
                "x-alchemy-signature": _sign(body),
                "Content-Type": "application/json",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["data"]["processed"] is False

    def test_webhook_status_endpoint(self, client: TestClient, monkeypatch) -> None:
        """GET /webhook/alchemy/status returns health info."""
        monkeypatch.setattr(settings, "alchemy_api_key", SIGNING_KEY)
        monkeypatch.setattr(settings, "alchemy_webhook_url", "https://example.com/webhook")
        response = client.get("/api/v1/webhook/alchemy/status")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["data"]["source_id"] == "alchemy_webhook"
        assert data["data"]["source_type"] == "webhook"
        assert data["data"]["configured"] is True
        assert data["data"]["webhook_url"] == "https://example.com/webhook"

    def test_webhook_error_resilience(self, client: TestClient, monkeypatch) -> None:
        """Returns 200 even on internal errors (Alchemy expects 200)."""
        monkeypatch.setattr(settings, "alchemy_api_key", SIGNING_KEY)

        def failing_persist(self, *args, **kwargs):
            raise RuntimeError("DB connection failed")

        monkeypatch.setattr(CollectionRepository, "persist_collection_result", failing_persist)

        body = json.dumps(_address_activity_payload()).encode()
        response = client.post(
            "/api/v1/webhook/alchemy",
            content=body,
            headers={
                "x-alchemy-signature": _sign(body),
                "Content-Type": "application/json",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["data"]["processed"] is False
