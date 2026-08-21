"""Alchemy Notify Webhook Handler.

Receives Alchemy Notify push notifications about on-chain events (new contract
deployments, address activity) and persists them as RawDiscovery records.

Reference:
- DATA_SOURCE_STRATEGY.md §3. On-chain Data
- ENGINEERING_ROADMAP.md §6.2
- ADR-012-system-direction-auto-scan.md
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime
from typing import Any

import structlog
from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse

from app.collectors.base import CollectorResult, RawDiscovery, RawSignal
from app.collectors.etherscan import _KNOWN_NOISE_CONTRACTS
from app.collectors.persistence import CollectionRepository
from app.config import settings

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["webhook"])

# Keep on-chain-only discoveries below default analysis threshold (0.3)
MAX_DISCOVERY_SCORE = 0.28


def _verify_signature(body: bytes, signature: str | None, signing_key: str) -> bool:
    """Verify Alchemy webhook HMAC-SHA256 signature."""
    if not signature:
        return False
    expected = hmac.new(
        signing_key.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def _parse_hex_value(value: str | None) -> int:
    """Parse a hex string value (wei) from the webhook payload."""
    if not value:
        return 0
    try:
        if isinstance(value, str) and value.startswith("0x"):
            return int(value, 16)
        return int(value)
    except (ValueError, TypeError):
        return 0


def _build_discovery(payload: dict[str, Any]) -> RawDiscovery | None:
    """Build a RawDiscovery from an Alchemy webhook payload.

    Returns None if the event should be skipped (unsupported type, noise
    contract, or missing address).
    """
    webhook_type = payload.get("type", "")
    webhook_id = payload.get("webhookId", "")
    event_id = payload.get("id", "")

    # Only ADDRESS_ACTIVITY and CUSTOM webhooks carry contract/activity data
    if webhook_type not in ("ADDRESS_ACTIVITY", "CUSTOM"):
        return None

    event = payload.get("event", {})
    data = event.get("data", {})

    address = (data.get("address") or data.get("to") or data.get("from") or "").lower()
    if not address:
        return None

    # Filter out well-known high-volume noise contracts
    if address in _KNOWN_NOISE_CONTRACTS:
        return None

    transaction_hash = data.get("transactionHash", "")
    block_number = data.get("blockNumber", "")
    value = _parse_hex_value(data.get("value"))
    asset = data.get("asset", "ETH")
    category = data.get("category", "")

    name = f"Contract {address[:10]}"

    raw_data = {
        "address": address,
        "chain": "ethereum",
        "transaction_hash": transaction_hash,
        "block_number": block_number,
        "webhook_type": webhook_type,
        "webhook_id": webhook_id,
        "event_data": data,
    }

    # Signal strength based on transaction value (1 ETH scale)
    value_strength = min(1.0, value / 1e18) if value else 0.0

    signals = [
        RawSignal(
            signal_type="chain_activity",
            signal_source="alchemy_webhook",
            signal_data={
                "address": address,
                "webhook_type": webhook_type,
                "category": category,
            },
            signal_strength=max(0.1, value_strength),
        ),
        RawSignal(
            signal_type="gas_usage",
            signal_source="alchemy_webhook",
            signal_data={"value": value, "asset": asset},
            signal_strength=value_strength,
        ),
    ]

    # Discovery score: modest, capped below analysis threshold (signal-only)
    discovery_score = round(min(MAX_DISCOVERY_SCORE, 0.08 + value_strength * 0.2), 3)

    return RawDiscovery(
        source_id="alchemy_webhook",
        raw_id=event_id,
        name=name,
        url=f"https://etherscan.io/address/{address}",
        sector=None,
        stage="mainnet",
        raw_data=raw_data,
        raw_signals=signals,
        discovery_score=discovery_score,
        discovered_at=datetime.now(UTC),
    )


@router.post("/webhook/alchemy")
async def receive_alchemy_webhook(
    request: Request,
    x_alchemy_signature: str | None = Header(None, alias="x-alchemy-signature"),
) -> JSONResponse:
    """Receive and process an Alchemy Notify webhook.

    Verifies the HMAC-SHA256 signature, parses the payload, and persists
    on-chain activity as a RawDiscovery. Returns 200 even on internal
    errors — Alchemy retries on non-200 responses.
    """
    signing_key = settings.alchemy_api_key

    # Webhook not configured
    if not signing_key:
        return JSONResponse(
            status_code=503,
            content={
                "ok": False,
                "error": {
                    "code": "WEBHOOK_NOT_CONFIGURED",
                    "message": "Alchemy webhook signing key is not configured",
                },
            },
        )

    # Read raw body for signature verification
    body = await request.body()

    # Verify signature
    if not _verify_signature(body, x_alchemy_signature, signing_key):
        return JSONResponse(
            status_code=401,
            content={
                "ok": False,
                "error": {
                    "code": "INVALID_SIGNATURE",
                    "message": "Missing or invalid webhook signature",
                },
            },
        )

    # Parse payload
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, ValueError) as exc:
        logger.error("webhook.alchemy.invalid_json", error=str(exc))
        return JSONResponse(
            status_code=200,
            content={"ok": True, "data": {"event_id": None, "processed": False}},
        )

    event_id = payload.get("id", "")

    try:
        discovery = _build_discovery(payload)

        if discovery is None:
            logger.info("webhook.alchemy.skipped", event_id=event_id)
            return JSONResponse(
                status_code=200,
                content={"ok": True, "data": {"event_id": event_id, "processed": False}},
            )

        result = CollectorResult(
            source_id="alchemy_webhook",
            status="success",
            items=[discovery],
        )
        result.started_at = datetime.now(UTC)
        result.finished_at = datetime.now(UTC)

        repo = CollectionRepository()
        repo.persist_collection_result(
            result,
            source_type="webhook",
            source_name="Alchemy Webhook",
        )

        logger.info(
            "webhook.alchemy.processed",
            event_id=event_id,
            address=discovery.raw_data.get("address"),
        )

        return JSONResponse(
            status_code=200,
            content={"ok": True, "data": {"event_id": event_id, "processed": True}},
        )

    except Exception as exc:
        logger.error(
            "webhook.alchemy.error",
            event_id=event_id,
            error=str(exc),
            exc_info=True,
        )
        # Return 200 even on errors — Alchemy retries on non-200
        return JSONResponse(
            status_code=200,
            content={"ok": True, "data": {"event_id": event_id, "processed": False}},
        )


@router.get("/webhook/alchemy/status")
def alchemy_webhook_status() -> JSONResponse:
    """Health check for the Alchemy webhook endpoint."""
    configured = bool(settings.alchemy_api_key)
    return JSONResponse(
        status_code=200,
        content={
            "ok": True,
            "data": {
                "source_id": "alchemy_webhook",
                "source_type": "webhook",
                "configured": configured,
                "webhook_url": settings.alchemy_webhook_url or None,
            },
        },
    )
