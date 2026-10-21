"""CoinGecko 全量币表缓存 + 发币核实（2026-10-08，ADR-015 补充）。

RootData 的 token 字段为空时，``token_launch_confirmed`` 只能落到「未知」，
于是 Arbitrum / Biconomy / AltLayer 这类早已上市的项目躲过了入库门和复审。
这里拿 CoinGecko ``/coins/list``（约 2 万个币，免费端点）做一份本地缓存，
给「状态未知」的项目补一条正面证据。

**严格匹配**（误判一个就会把项目藏起来，宁可漏判）：

- 名称归一（小写、去掉非字母数字）后必须**唯一**命中一个币；重名多币不算。
- 有 symbol 时 symbol 也必须一致。
- 没有 symbol 时，归一后名称不足 8 个字符的不算 —— 短名 / 通用词
  （Halo、Tower、commons、Safu……）在币表里撞名的概率太高。

只补「确认已发币」，从不改写「明确未发币」：来源写了 ``no_token_yet=True``
的，币表命中也不作数。表为空（从没刷过 / 刷新失败）时核实不生效，行为与
没有这个模块完全一样。
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog

from app.config import settings
from app.db import connection_scope, dict_from_row

logger = structlog.get_logger(__name__)

LAUNCH_EVIDENCE_REGISTRY = "coingecko_registry"
REFRESH_MAX_AGE = timedelta(days=7)
# 只靠名称命中时的最短归一长度
_MIN_NAME_ONLY_KEY_LEN = 8
# 少于这个数说明响应被截断 / 限流页，不能拿它覆盖整表
_MIN_PLAUSIBLE_COINS = 1000
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]")


def name_key(value: str | None) -> str:
    """归一名称：小写后去掉所有非字母数字（"Pell Network" → "pellnetwork"）。"""
    return _NON_ALNUM_RE.sub("", (value or "").lower())


@dataclass
class RegistryIndex:
    """name_key → [(coin_id, symbol)]。空索引 = 核实不生效。"""

    by_name: dict[str, list[tuple[str, str]]] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return bool(self.by_name)

    @classmethod
    def from_rows(cls, rows: Iterable[tuple[str, str, str]]) -> RegistryIndex:
        """rows: (coin_id, symbol, name_key)。"""
        by_name: dict[str, list[tuple[str, str]]] = {}
        for coin_id, symbol, key in rows:
            if key:
                by_name.setdefault(key, []).append((coin_id, symbol))
        return cls(by_name)

    def match(self, name: str | None, symbol: str | None = None) -> str | None:
        """严格匹配，命中返回 coin_id，否则 None。"""
        key = name_key(name)
        candidates = self.by_name.get(key) or []
        if len(candidates) != 1:
            return None
        coin_id, coin_symbol = candidates[0]
        sym = name_key(symbol)
        if sym:
            return coin_id if sym == name_key(coin_symbol) else None
        return coin_id if len(key) >= _MIN_NAME_ONLY_KEY_LEN else None


def registry_confirms_launch(
    index: RegistryIndex,
    *,
    name: str | None,
    symbol: str | None,
    no_token_yet: bool | None,
    token_launch_confirmed: bool | None,
) -> bool:
    """币表能否把「状态未知」补成「确认已发币」。已确认 / 明确未发币时不介入。"""
    if not index or token_launch_confirmed or no_token_yet:
        return False
    return index.match(name, symbol) is not None


def load_index(conn: Any = None) -> RegistryIndex:
    """读整张缓存表。表不存在（旧库未迁移）或读失败时返回空索引，不抛。"""
    with connection_scope(conn) as db:
        try:
            rows = db.execute("SELECT coin_id, symbol, name_key FROM token_registry").fetchall()
        except Exception as e:
            # 借用连接上（PG）失败的语句会让事务进入 aborted，先回滚再把连接还回去
            with suppress(Exception):
                db.rollback()
            logger.warning("token_registry.load_failed", error=str(e))
            return RegistryIndex()
    out = []
    for row in rows:
        r = dict_from_row(row)
        out.append((str(r["coin_id"]), str(r["symbol"] or ""), str(r["name_key"] or "")))
    return RegistryIndex.from_rows(out)


def _parse_ts(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        ts = value
    else:
        try:
            ts = datetime.fromisoformat(str(value))
        except ValueError:
            return None
    return ts if ts.tzinfo else ts.replace(tzinfo=UTC)


def _last_fetched(db: Any) -> datetime | None:
    row = db.execute("SELECT MAX(fetched_at) AS ts FROM token_registry").fetchone()
    return _parse_ts(dict_from_row(row).get("ts")) if row is not None else None


async def _fetch_coin_list() -> list[dict[str, Any]]:
    """GET /coins/list。走采集器统一的出站白名单客户端。"""
    # 函数内导入：采集器包 __init__ 会拉起全部采集器，collector agent 导入本模块时不需要它们
    from app.collectors.base import safe_collector_client

    headers: dict[str, str] = {}
    if settings.coingecko_api_key:
        headers["x-cg-demo-api-key"] = settings.coingecko_api_key
    async with safe_collector_client(timeout=settings.coingecko_timeout) as client:
        response = await client.get(f"{settings.coingecko_api_base_url}/coins/list", headers=headers)
        response.raise_for_status()
        data = response.json()
    if not isinstance(data, list):
        raise ValueError(f"Unexpected CoinGecko /coins/list response type: {type(data).__name__}")
    return data


def replace_registry(coins: list[dict[str, Any]], conn: Any = None) -> int:
    """整表覆盖写入，返回写入行数。单事务：失败时旧表原样保留。"""
    now = datetime.now(UTC)
    rows: dict[str, tuple[str, str, str, str, datetime]] = {}
    for coin in coins:
        coin_id = str(coin.get("id") or "").strip()
        name = str(coin.get("name") or "").strip()
        if not coin_id or not name:
            continue
        rows[coin_id] = (coin_id, str(coin.get("symbol") or "").strip(), name, name_key(name), now)
    with connection_scope(conn) as db:
        try:
            db.execute("DELETE FROM token_registry")
            db.executemany(
                "INSERT INTO token_registry (coin_id, symbol, name, name_key, fetched_at) VALUES (?, ?, ?, ?, ?)",
                list(rows.values()),
            )
            db.commit()
        except Exception:
            db.rollback()
            raise
    return len(rows)


async def refresh_registry(*, force: bool = False, conn: Any = None) -> dict[str, Any]:
    """缓存超过 7 天（或 force）时重新拉取。失败只记日志，旧缓存继续可用。"""
    if not settings.coingecko_enabled:
        return {"status": "disabled"}
    try:
        if not force:
            with connection_scope(conn) as db:
                last = _last_fetched(db)
            if last is not None and datetime.now(UTC) - last < REFRESH_MAX_AGE:
                return {"status": "fresh", "fetched_at": last.isoformat()}
        coins = await _fetch_coin_list()
        if len(coins) < _MIN_PLAUSIBLE_COINS:
            raise ValueError(f"CoinGecko /coins/list returned only {len(coins)} coins")
        count = replace_registry(coins, conn=conn)
    except Exception as e:
        logger.warning("token_registry.refresh_failed", error=str(e))
        return {"status": "failed", "error": str(e)}
    logger.info("token_registry.refreshed", coins=count)
    return {"status": "refreshed", "coins": count}
