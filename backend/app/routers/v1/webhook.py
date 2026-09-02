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


def _process_claim_watch(payload: dict[str, Any]) -> bool:
    """匹配自有地址并入库 airdrop_candidate 事件。返回是否命中。

    整个函数吞掉所有异常：领取监控是附加价值（F4），它挂掉绝不能让 webhook
    返回非 200 —— Alchemy 对非 200 会反复重投，一个次要功能的 bug 会变成
    持续的重投风暴，连带把主职责（RawDiscovery 入库）也一起拖垮。

    这里不直接发送，只入库 pending。发送由 F1 既有的 `dispatch_pending`
    统一做，那条路径已经有重试上限、失败记录与指标 —— 另开一条发送路径
    等于把那些保障重写一遍。
    """
    try:
        from app.db import get_connection
        from app.services.claim_watch import evaluate_claim_candidate, record_claim_candidate

        with get_connection() as conn:
            event = evaluate_claim_candidate(conn, payload)
            if event is None:
                return False
            inserted = record_claim_candidate(conn, event, settings.notify_channel)
            conn.commit()
        return inserted
    except Exception as exc:
        logger.error("webhook.alchemy.claim_watch_failed", error=str(exc), exc_info=True)
        return False


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
    signing_key = settings.alchemy_webhook_signing_key

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

    # ── 领取监控（F4，ACTION_LOOP_DESIGN §5）─────────────────────
    #
    # 刻意放在 _build_discovery **之前**且用独立 try：这两件事职责无关 ——
    # discovery 是"发现了一个新项目"，claim 是"我的钱包收到了东西"。同一条
    # payload 可能只满足其中一个（自有地址收到代币时 address 多半在 noise
    # denylist 里、discovery 会被跳过），把它们串成一条链会让先失败的那个
    # 把后面的一起吃掉。
    claim_matched = _process_claim_watch(payload)

    try:
        discovery = _build_discovery(payload)

        if discovery is None:
            logger.info("webhook.alchemy.skipped", event_id=event_id, claim_matched=claim_matched)
            return JSONResponse(
                status_code=200,
                content={
                    "ok": True,
                    "data": {
                        "event_id": event_id,
                        "processed": False,
                        "claim_matched": claim_matched,
                    },
                },
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

        # 地址只记前 10 位。这里的 address 多数是别人的合约（discovery 的
        # 语义），但**自有地址收到代币时也会走到这条日志** —— 一旦命中就等于
        # 把自有钱包地址写进日志文件，绕过 /watched-wallets 的管理员锁
        # （ACTION_LOOP_DESIGN §5.4.1）。分不清来源时按更严的口径处理。
        raw_address = str(discovery.raw_data.get("address") or "")
        logger.info(
            "webhook.alchemy.processed",
            event_id=event_id,
            address_prefix=raw_address[:10],
            claim_matched=claim_matched,
        )

        return JSONResponse(
            status_code=200,
            content={
                "ok": True,
                "data": {"event_id": event_id, "processed": True, "claim_matched": claim_matched},
            },
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
            content={
                "ok": True,
                "data": {"event_id": event_id, "processed": False, "claim_matched": claim_matched},
            },
        )


@router.get("/webhook/alchemy/status")
def alchemy_webhook_status() -> JSONResponse:
    """Health check for the Alchemy webhook endpoint."""
    configured = bool(settings.alchemy_webhook_signing_key)
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
