"""Testnet Faucet Registry & Cooldown Tracking Engine.

Maintains metadata of high-quality free faucets across major testnets
and tracks per-user 24h claim cooldowns to maximize testnet interaction efficiency.
Zero external API costs.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from app.db import DbConnection, get_connection

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
    {
        "id": "story-odyssey",
        "name": "Story Odyssey Faucet",
        "chain": "story_odyssey",
        "chain_name": "Story Odyssey",
        "url": "https://faucet.story.foundation/",
        "requires_auth": False,
        "cooldown_hours": 24,
        "description": "Story Protocol 官方测试币 IP 水龙头",
        "daily_quota": "1.0 IP",
    },
    {
        "id": "soneium-minato",
        "name": "Soneium Minato Bridge & Faucet",
        "chain": "soneium_minato",
        "chain_name": "Soneium Minato",
        "url": "https://bridge.soneium.org/",
        "requires_auth": False,
        "cooldown_hours": 24,
        "description": "索尼 Soneium 官方测试网跨链水龙头通道",
        "daily_quota": "0.05 Minato ETH",
    },
    {
        "id": "monad-testnet",
        "name": "Monad Devnet Faucet",
        "chain": "monad_testnet",
        "chain_name": "Monad Devnet",
        "url": "https://testnet.monad.xyz/",
        "requires_auth": True,
        "cooldown_hours": 12,
        "description": "Monad 官方生态水龙头通道",
        "daily_quota": "0.1 MON",
    },
]

_PROBE_CACHE: dict[str, Any] = {"timestamp": 0.0, "data": []}


def probe_faucets_liveness(force_refresh: bool = False) -> list[dict[str, Any]]:
    """Probe real-time HTTP reachability and latency for all registered faucets."""
    import time
    import httpx

    now = time.time()
    if not force_refresh and _PROBE_CACHE["data"] and (now - _PROBE_CACHE["timestamp"] < 60.0):
        return _PROBE_CACHE["data"]

    results = []
    for faucet in FREE_FAUCETS:
        url = faucet["url"]
        start_t = time.perf_counter()
        status = "online"
        status_code = 200
        try:
            with httpx.Client(timeout=1.8, follow_redirects=True) as client:
                resp = client.head(url)
                latency_ms = max(10, int((time.perf_counter() - start_t) * 1000))
                status_code = resp.status_code
                if resp.status_code == 429:
                    status = "rate_limited"
                elif resp.status_code >= 400:
                    status = "warning"
        except Exception:
            latency_ms = 999
            status = "offline"

        results.append(
            {
                "faucet_id": faucet["id"],
                "name": faucet["name"],
                "chain": faucet["chain"],
                "chain_name": faucet.get("chain_name", faucet["chain"]),
                "url": url,
                "status": status,
                "latency_ms": latency_ms,
                "status_code": status_code,
                "requires_auth": faucet.get("requires_auth", False),
                "daily_quota": faucet.get("daily_quota", ""),
                "probed_at": int(now),
            }
        )

    _PROBE_CACHE["timestamp"] = now
    _PROBE_CACHE["data"] = results
    return results


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


async def check_faucets_liveness(
    faucet_id: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> list[dict[str, Any]]:
    """Check liveness and balance status across faucets."""
    import time
    import httpx
    from app.services.public_rpc_verifier import get_wallet_balance_and_nonce

    targets = FREE_FAUCETS
    if faucet_id:
        targets = [f for f in FREE_FAUCETS if f["id"] == faucet_id]

    own_client = False
    if client is None:
        client = httpx.AsyncClient(timeout=3.5, follow_redirects=True)
        own_client = True

    results: list[dict[str, Any]] = []
    now_iso = datetime.now(UTC).isoformat()

    try:
        for f in targets:
            start_t = time.perf_counter()
            f_id = f["id"]
            vault = f.get("vault_address")
            url = f.get("url", "")
            chain = f.get("chain", "sepolia")

            if vault:
                # Query on-chain vault balance
                bal_data = await get_wallet_balance_and_nonce(vault, chain=chain, client=client)
                bal = bal_data.get("balance_eth", 0.0)
                latency_ms = bal_data.get("latency_ms", 0.0)
                if bal >= 0.5:
                    health = "healthy"
                    health_zh = "存量充沛"
                elif bal > 0.0:
                    health = "low_balance"
                    health_zh = "余额紧张"
                else:
                    health = "depleted"
                    health_zh = "暂时枯竭"

                results.append({
                    "id": f_id,
                    "name": f["name"],
                    "chain": chain,
                    "health": health,
                    "health_zh": health_zh,
                    "vault_balance_eth": bal,
                    "latency_ms": latency_ms,
                    "checked_at": now_iso,
                })
            else:
                # Ping HTTP endpoint
                try:
                    res = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
                    latency_ms = round((time.perf_counter() - start_t) * 1000, 2)
                    if res.status_code < 400 or res.status_code in (401, 403):
                        health = "healthy"
                        health_zh = "正常开放"
                    elif res.status_code == 429:
                        health = "low_balance"
                        health_zh = "领水拥堵"
                    else:
                        health = "degraded"
                        health_zh = "维护中"
                except Exception:
                    latency_ms = round((time.perf_counter() - start_t) * 1000, 2)
                    health = "degraded"
                    health_zh = "连接超时"

                results.append({
                    "id": f_id,
                    "name": f["name"],
                    "chain": chain,
                    "health": health,
                    "health_zh": health_zh,
                    "vault_balance_eth": None,
                    "latency_ms": latency_ms,
                    "checked_at": now_iso,
                })
    finally:
        if own_client:
            await client.aclose()

    return results

