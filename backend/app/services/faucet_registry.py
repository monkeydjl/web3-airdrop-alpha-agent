"""Testnet Faucet Registry & Cooldown Tracking Engine.

Maintains metadata of high-quality free faucets across major testnets
and tracks per-user 24h claim cooldowns to maximize testnet interaction efficiency.
Zero external API costs.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from app.db import DbConnection, dict_from_row, get_connection

DEFAULT_USER = "default"

FREE_FAUCETS: list[dict[str, Any]] = [
    {
        "id": "sepolia-pow",
        "name": "Sepolia PoW Faucet",
        "chain": "sepolia",
        "chain_name": "Ethereum Sepolia",
        "url": "https://sepolia-faucet.pk910.de/",
        "requires_auth": False,
        "cooldown_hours": 24,
        "description": "无需任何账号或 API Key，浏览器挖矿即可秒领 Sepolia ETH",
        "daily_quota": "0.1 - 2.5 Sepolia ETH",
    },
    {
        "id": "google-sepolia",
        "name": "Google Cloud Web3 Faucet",
        "chain": "sepolia",
        "chain_name": "Ethereum Sepolia",
        "url": "https://cloud.google.com/application/web3/faucet/ethereum/sepolia",
        "requires_auth": True,
        "cooldown_hours": 24,
        "description": "Google Web3 官方提供，每日免费领 0.05 Sepolia ETH",
        "daily_quota": "0.05 Sepolia ETH",
    },
    {
        "id": "arbitrum-sepolia",
        "name": "Arbitrum Sepolia Faucet",
        "chain": "arbitrum_sepolia",
        "chain_name": "Arbitrum Sepolia",
        "url": "https://faucet.quicknode.com/arbitrum/sepolia",
        "requires_auth": False,
        "cooldown_hours": 24,
        "description": "Arbitrum 官方推荐测试网水龙头",
        "daily_quota": "0.1 Arb Sepolia ETH",
    },
    {
        "id": "base-sepolia",
        "name": "Base Sepolia Faucet",
        "chain": "base_sepolia",
        "chain_name": "Base Sepolia",
        "url": "https://www.coinbase.com/faucets/base-ethereum-sepolia-faucet",
        "requires_auth": True,
        "cooldown_hours": 24,
        "description": "Coinbase / Base 官方测试网领水通道",
        "daily_quota": "0.1 Base Sepolia ETH",
    },
    {
        "id": "berachain-bartio",
        "name": "Berachain bArtio Faucet",
        "chain": "berachain_bartio",
        "chain_name": "Berachain Testnet",
        "url": "https://bartio.faucet.berachain.com/",
        "requires_auth": False,
        "cooldown_hours": 8,
        "description": "Berachain 官方测试币 BERA 水龙头（8小时冷却周期）",
        "daily_quota": "0.1 BERA",
    },
    {
        "id": "polygon-amoy",
        "name": "Polygon Amoy Faucet",
        "chain": "polygon_amoy",
        "chain_name": "Polygon Amoy",
        "url": "https://faucet.polygon.technology/",
        "requires_auth": False,
        "cooldown_hours": 24,
        "description": "Polygon 官方新一代测试网水龙头",
        "daily_quota": "0.2 POL",
    },
]


def ensure_faucet_claims_table(conn: DbConnection) -> None:
    """Ensure the faucet_claims table and indexes exist."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS faucet_claims (
            claim_id       TEXT PRIMARY KEY,
            user_id        TEXT NOT NULL,
            faucet_id      TEXT NOT NULL,
            claimed_at     TIMESTAMP NOT NULL,
            cooldown_hours INTEGER DEFAULT 24
        );
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_faucet_claims_user
        ON faucet_claims(user_id, faucet_id);
        """
    )
    conn.commit()


def _parse_dt(val: Any) -> datetime | None:
    if not val:
        return None
    if isinstance(val, datetime):
        return val if val.tzinfo else val.replace(tzinfo=UTC)
    try:
        dt = datetime.fromisoformat(str(val).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    except Exception:
        return None


def list_faucets_with_status(
    conn: DbConnection | None = None,
    user_id: str = DEFAULT_USER,
) -> list[dict[str, Any]]:
    """List all available faucets with the user's real-time cooldown status."""
    own_conn = False
    if conn is None:
        conn = get_connection()
        own_conn = True

    try:
        ensure_faucet_claims_table(conn)
        cursor = conn.execute(
            """
            SELECT faucet_id, claimed_at, cooldown_hours
            FROM faucet_claims
            WHERE user_id = ?
            """,
            (user_id,),
        )
        rows = cursor.fetchall()
        claims: dict[str, dict[str, Any]] = {}
        for r in rows:
            if hasattr(r, "keys"):
                d = dict(r)
            elif isinstance(r, dict):
                d = dict(r)
            else:
                d = {"faucet_id": r[0], "claimed_at": r[1], "cooldown_hours": r[2]}
            claims[d["faucet_id"]] = d

        now = datetime.now(UTC)
        result: list[dict[str, Any]] = []

        for f in FREE_FAUCETS:
            f_id = f["id"]
            claim = claims.get(f_id)
            cooldown_h = f.get("cooldown_hours", 24)
            status = "ready"
            remaining_seconds = 0
            last_claimed_at = None
            next_claim_at = None

            if claim:
                c_at = _parse_dt(claim.get("claimed_at"))
                if c_at:
                    last_claimed_at = c_at.isoformat()
                    cooldown_delta = timedelta(hours=claim.get("cooldown_hours") or cooldown_h)
                    unlock_time = c_at + cooldown_delta
                    next_claim_at = unlock_time.isoformat()
                    if now < unlock_time:
                        status = "cooling"
                        remaining_seconds = int((unlock_time - now).total_seconds())

            if remaining_seconds > 0:
                hours = remaining_seconds // 3600
                minutes = (remaining_seconds % 3600) // 60
                remaining_human = f"{hours}小时{minutes}分"
            else:
                remaining_human = "可领取"

            item = dict(f)
            item.update(
                {
                    "status": status,
                    "status_zh": "冷却中" if status == "cooling" else "可领取",
                    "remaining_seconds": remaining_seconds,
                    "remaining_human": remaining_human,
                    "last_claimed_at": last_claimed_at,
                    "next_claim_at": next_claim_at,
                }
            )
            result.append(item)

        return result
    finally:
        if own_conn:
            conn.close()


def record_faucet_claim(
    conn: DbConnection | None = None,
    user_id: str = DEFAULT_USER,
    faucet_id: str = "",
) -> dict[str, Any]:
    """Record that the user has claimed from the specified faucet."""
    own_conn = False
    if conn is None:
        conn = get_connection()
        own_conn = True

    try:
        ensure_faucet_claims_table(conn)
        faucet_meta = next((f for f in FREE_FAUCETS if f["id"] == faucet_id), None)
        cooldown_h = faucet_meta["cooldown_hours"] if faucet_meta else 24
        now = datetime.now(UTC)

        # Upsert claim
        cursor = conn.execute(
            "SELECT claim_id FROM faucet_claims WHERE user_id = ? AND faucet_id = ?",
            (user_id, faucet_id),
        )
        existing = cursor.fetchone()
        if existing:
            conn.execute(
                "UPDATE faucet_claims SET claimed_at = ?, cooldown_hours = ? WHERE user_id = ? AND faucet_id = ?",
                (now.isoformat(), cooldown_h, user_id, faucet_id),
            )
        else:
            claim_id = f"clm-{uuid.uuid4().hex[:12]}"
            conn.execute(
                "INSERT INTO faucet_claims (claim_id, user_id, faucet_id, claimed_at, cooldown_hours) VALUES (?, ?, ?, ?, ?)",
                (claim_id, user_id, faucet_id, now.isoformat(), cooldown_h),
            )
        conn.commit()

        # Return updated faucet status
        faucets = list_faucets_with_status(conn, user_id=user_id)
        return next((f for f in faucets if f["id"] == faucet_id), {})
    finally:
        if own_conn:
            conn.close()


def reset_faucet_claim(
    conn: DbConnection | None = None,
    user_id: str = DEFAULT_USER,
    faucet_id: str = "",
) -> bool:
    """Reset a faucet claim back to ready."""
    own_conn = False
    if conn is None:
        conn = get_connection()
        own_conn = True

    try:
        ensure_faucet_claims_table(conn)
        conn.execute(
            "DELETE FROM faucet_claims WHERE user_id = ? AND faucet_id = ?",
            (user_id, faucet_id),
        )
        conn.commit()
        return True
    finally:
        if own_conn:
            conn.close()
