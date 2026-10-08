"""CoinGecko 币表发币核实（token_registry，2026-10-08）。

约束：
- 严格匹配：归一名称唯一命中；有 symbol 时 symbol 也要一致；无 symbol 时名称 ≥ 8 字符。
- 只把「未知」补成「确认已发币」，不改写「明确未发币」。
- 刷新：7 天内不出网；响应截断 / 失败时旧表原样保留。
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.collector import CollectorAgent
from app.collectors.persistence import CollectionRepository
from app.db import init_db
from app.services import token_registry
from app.services.token_registry import (
    RegistryIndex,
    load_index,
    name_key,
    refresh_registry,
    registry_confirms_launch,
    replace_registry,
)


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    init_db(c)
    try:
        yield c
    finally:
        c.close()


def _coins(*items: tuple[str, str, str], pad: int = 0) -> list[dict[str, str]]:
    coins = [{"id": i, "symbol": s, "name": n} for i, s, n in items]
    coins += [{"id": f"filler-{k}", "symbol": f"f{k}", "name": f"Filler Coin {k}"} for k in range(pad)]
    return coins


_INDEX = RegistryIndex.from_rows(
    [
        ("arbitrum", "arb", name_key("Arbitrum")),
        ("halo-a", "halo", name_key("Halo")),
        ("halo-b", "hlo", name_key("Halo")),
        ("mezo", "mezo", name_key("Mezo")),
        ("pell-network", "pell", name_key("Pell Network")),
    ]
)


class TestMatch:
    def test_name_key_strips_case_and_punctuation(self):
        assert name_key("Pell Network") == "pellnetwork"
        assert name_key("De.Fi") == "defi"
        assert name_key(None) == ""

    def test_unique_long_name_matches(self):
        assert _INDEX.match("Arbitrum") == "arbitrum"
        assert _INDEX.match("pell-network") == "pell-network"

    def test_name_shared_by_several_coins_never_matches(self):
        assert _INDEX.match("Halo") is None
        assert _INDEX.match("Halo", "halo") is None

    def test_short_name_needs_matching_symbol(self):
        assert _INDEX.match("Mezo") is None
        assert _INDEX.match("Mezo", "MEZO") == "mezo"
        assert _INDEX.match("Mezo", "MZ") is None

    def test_symbol_mismatch_rejects_long_name(self):
        assert _INDEX.match("Arbitrum", "OP") is None

    def test_unknown_name(self):
        assert _INDEX.match("Nobody Knows") is None
        assert _INDEX.match("") is None


class TestConfirmsLaunch:
    def test_fills_unknown(self):
        assert registry_confirms_launch(
            _INDEX, name="Arbitrum", symbol=None, no_token_yet=False, token_launch_confirmed=False
        )

    def test_never_overrides_explicit_pre_tge(self):
        assert not registry_confirms_launch(
            _INDEX, name="Arbitrum", symbol=None, no_token_yet=True, token_launch_confirmed=False
        )

    def test_already_confirmed_needs_no_help(self):
        assert not registry_confirms_launch(
            _INDEX, name="Arbitrum", symbol=None, no_token_yet=False, token_launch_confirmed=True
        )

    def test_empty_index_is_inert(self):
        assert not registry_confirms_launch(
            RegistryIndex(), name="Arbitrum", symbol=None, no_token_yet=False, token_launch_confirmed=False
        )


class TestStorage:
    def test_replace_and_load_round_trip(self, conn):
        assert replace_registry(_coins(("arbitrum", "arb", "Arbitrum"), ("", "x", "No Id")), conn=conn) == 1
        assert load_index(conn).match("Arbitrum") == "arbitrum"

    def test_replace_overwrites_whole_table(self, conn):
        replace_registry(_coins(("old-coin", "old", "Old Coin Name")), conn=conn)
        replace_registry(_coins(("arbitrum", "arb", "Arbitrum")), conn=conn)
        index = load_index(conn)
        assert index.match("Old Coin Name") is None
        assert index.match("Arbitrum") == "arbitrum"

    def test_missing_table_yields_empty_index(self):
        c = sqlite3.connect(":memory:")
        c.row_factory = sqlite3.Row
        try:
            assert not load_index(c)
        finally:
            c.close()


class TestRefresh:
    @pytest.fixture(autouse=True)
    def _enabled(self, monkeypatch):
        monkeypatch.setattr(token_registry.settings, "coingecko_enabled", True)

    async def test_refreshes_empty_table(self, conn):
        fetch = AsyncMock(return_value=_coins(("arbitrum", "arb", "Arbitrum"), pad=1500))
        with patch.object(token_registry, "_fetch_coin_list", fetch):
            result = await refresh_registry(conn=conn)
        assert result == {"status": "refreshed", "coins": 1501}
        assert load_index(conn).match("Arbitrum") == "arbitrum"

    async def test_fresh_table_skips_network(self, conn):
        replace_registry(_coins(("arbitrum", "arb", "Arbitrum")), conn=conn)
        fetch = AsyncMock()
        with patch.object(token_registry, "_fetch_coin_list", fetch):
            result = await refresh_registry(conn=conn)
        assert result["status"] == "fresh"
        fetch.assert_not_called()

    async def test_stale_table_refetches(self, conn):
        replace_registry(_coins(("old-coin", "old", "Old Coin Name")), conn=conn)
        stale = datetime.now(UTC) - timedelta(days=8)
        conn.execute("UPDATE token_registry SET fetched_at = ?", (stale,))
        conn.commit()
        fetch = AsyncMock(return_value=_coins(("arbitrum", "arb", "Arbitrum"), pad=1500))
        with patch.object(token_registry, "_fetch_coin_list", fetch):
            assert (await refresh_registry(conn=conn))["status"] == "refreshed"
        assert load_index(conn).match("Old Coin Name") is None

    async def test_truncated_response_keeps_old_table(self, conn):
        replace_registry(_coins(("arbitrum", "arb", "Arbitrum")), conn=conn)
        fetch = AsyncMock(return_value=_coins(("only-one", "one", "Only One Coin")))
        with patch.object(token_registry, "_fetch_coin_list", fetch):
            result = await refresh_registry(force=True, conn=conn)
        assert result["status"] == "failed"
        assert load_index(conn).match("Arbitrum") == "arbitrum"

    async def test_network_error_is_swallowed(self, conn):
        fetch = AsyncMock(side_effect=RuntimeError("boom"))
        with patch.object(token_registry, "_fetch_coin_list", fetch):
            result = await refresh_registry(conn=conn)
        assert result == {"status": "failed", "error": "boom"}

    async def test_disabled_source_does_nothing(self, conn, monkeypatch):
        monkeypatch.setattr(token_registry.settings, "coingecko_enabled", False)
        fetch = AsyncMock()
        with patch.object(token_registry, "_fetch_coin_list", fetch):
            assert await refresh_registry(conn=conn) == {"status": "disabled"}
        fetch.assert_not_called()


class TestIngestionGate:
    """入库门同样认币表证据：RootData 没写 ticker 但币表命中 → 已发币 → 无路径即隔离。"""

    def _insert(self, conn, raw_id: str, raw_data: dict) -> None:
        conn.execute(
            """
            INSERT INTO raw_projects (raw_id, source_id, dedup_key, raw_data, discovered_at, discovery_score)
            VALUES (?, 'rootdata', ?, ?, ?, 0.5)
            """,
            (raw_id, f"{raw_id}::L2", json.dumps(raw_data), datetime.now(UTC).isoformat()),
        )
        conn.commit()

    def test_registry_hit_without_path_is_quarantined(self, conn):
        replace_registry(_coins(("arbitrum", "arb", "Arbitrum")), conn=conn)
        self._insert(conn, "r-arb", {"name": "Arbitrum", "sector": "L2", "no_token_yet": False})
        self._insert(conn, "r-new", {"name": "Brand New Rollup", "sector": "L2", "no_token_yet": False})

        projects = CollectorAgent().collect_from_repository(CollectionRepository(conn), limit=10)

        assert {p.name for p in projects} == {"Brand New Rollup"}
        row = conn.execute("SELECT quarantined, quarantine_reason FROM raw_projects WHERE raw_id = 'r-arb'").fetchone()
        assert row["quarantined"] == 1
        assert row["quarantine_reason"].startswith("listed_token_no_airdrop:rootdata:")

    def test_registry_hit_with_points_still_enters(self, conn):
        replace_registry(_coins(("arbitrum", "arb", "Arbitrum")), conn=conn)
        self._insert(
            conn,
            "r-arb",
            {"name": "Arbitrum", "sector": "L2", "no_token_yet": False, "description": "Arbitrum points program"},
        )

        projects = CollectorAgent().collect_from_repository(CollectionRepository(conn), limit=10)

        assert [p.name for p in projects] == ["Arbitrum"]
        assert projects[0].token_launch_confirmed is True

    def test_explicit_pre_tge_beats_registry(self, conn):
        replace_registry(_coins(("arbitrum", "arb", "Arbitrum")), conn=conn)
        self._insert(conn, "r-arb", {"name": "Arbitrum", "sector": "L2", "no_token_yet": True})

        projects = CollectorAgent().collect_from_repository(CollectionRepository(conn), limit=10)

        assert [p.name for p in projects] == ["Arbitrum"]
