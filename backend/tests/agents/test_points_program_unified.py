"""积分计划判定统一口径（2026-11-09）回归。

漏洞：采集侧曾用 restaking / vaults / incentive 这类通用词把
`has_points_program` 置真，而资格门与已发币复查只认
`explicit_points_program`。同一份数据在"空投信号阶梯"里算积分、在
"已发币否决"里不算，已发币项目靠通用词同时拿到积分台阶并绕过否决。

这里锁定统一后的三条路径（采集归一化 / 入库门 / 资格门 / 信号阶梯）
对"已发币 + 仅通用词"给出一致结论：不通过。
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime

import pytest

from app.agents.airdrop_signal import airdrop_signal_subscore
from app.agents.base import RawProject
from app.agents.collector import CollectorAgent
from app.agents.eligibility import (
    VETO_ALREADY_LAUNCHED,
    apply_eligibility_gate,
    has_participation_path,
    has_post_launch_airdrop_path,
    is_already_launched_without_airdrop_path,
)
from app.collectors.noise import is_listed_token_no_airdrop_signals
from app.collectors.persistence import CollectionRepository
from app.db import init_db
from app.utils.normalize import create_dedup_key, generate_deterministic_id
from app.utils.points import (
    project_has_points_program,
    resolve_points_program,
    signals_have_points_program,
)


@pytest.fixture
def repo_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    try:
        yield conn
    finally:
        conn.close()


def _insert_raw(conn, raw_id: str, source_id: str, raw_data: dict, score: float = 0.8) -> None:
    name = str(raw_data.get("name") or "")
    sector = raw_data.get("sector")
    key = create_dedup_key(name, sector)
    conn.execute(
        """
        INSERT INTO raw_projects (
            raw_id, source_id, dedup_key, raw_data, discovered_at,
            processed, discovery_score, project_id
        ) VALUES (?, ?, ?, ?, ?, 0, ?, ?)
        """,
        (
            raw_id,
            source_id,
            key.to_string(),
            json.dumps(raw_data),
            datetime.now(UTC).isoformat(),
            score,
            generate_deterministic_id(key),
        ),
    )
    conn.commit()


def _listed_project(**overrides: object) -> RawProject:
    """已发币、只有通用词（未归一化成积分）的项目。"""
    values: dict[str, object] = {
        "id": "listed-generic",
        "name": "Listed Generic",
        "sector": "L2",
        "source": "rootdata",
        "no_token_yet": False,
        "token_launch_confirmed": True,
        "has_points_program": False,
        "explicit_points_program": False,
        "has_testnet": False,
        "has_task_portal": False,
        "explicit_airdrop_mention": False,
        "recent_funding": False,
        "source_count": 1,
    }
    values.update(overrides)
    return RawProject(**values)  # type: ignore[arg-type]


class TestCollectorNormalization:
    """采集侧只认字段级证据与明确积分措辞。"""

    @pytest.mark.parametrize(
        "description",
        [
            "Liquid restaking for Bitcoin stakers",
            "Earn incentive rewards in our vaults",
            "Liquidity mining on Solana",
            "staking vault with deposit rewards",
        ],
    )
    def test_generic_words_do_not_set_has_points_program(self, description: str) -> None:
        flags = CollectorAgent._infer_airdrop_flags("rootdata", {"name": "X", "description": description})
        assert flags["has_points_program"] is False
        assert flags["explicit_points_program"] is False

    def test_field_level_evidence_still_wins(self) -> None:
        """可信源的显式字段是权威，优先于文本推断（哪怕文本只有通用词）。"""
        flags = CollectorAgent._infer_airdrop_flags(
            "rootdata",
            {"name": "X", "description": "restaking vaults", "has_points_program": True},
        )
        assert flags["has_points_program"] is True
        assert flags["explicit_points_program"] is True

    def test_defillama_loose_field_from_stored_raw_is_recomputed(self) -> None:
        """存量 raw 里 defillama 的关键词字段在重新扫描时按新口径重算为 False。"""
        flags = CollectorAgent._infer_airdrop_flags(
            "defillama",
            {"name": "X", "description": "staking vault incentives", "has_points_program": True},
        )
        assert flags["has_points_program"] is False
        assert flags["explicit_points_program"] is False


class TestIngestionGate:
    """已发币 + 仅通用词的行在入库门被隔离。"""

    def test_listed_generic_row_is_quarantined(self, repo_conn) -> None:
        _insert_raw(
            repo_conn,
            "r-listed-generic",
            "rootdata",
            {
                "name": "Generic Yield",
                "sector": "DeFi",
                "no_token_yet": False,
                "token_symbol": "GEN",
                "description": "Liquid restaking vaults with incentive rewards",
            },
        )
        assert CollectorAgent().collect_from_repository(CollectionRepository(repo_conn), limit=10) == []
        row = repo_conn.execute(
            "SELECT quarantine_reason FROM raw_projects WHERE raw_id = 'r-listed-generic'"
        ).fetchone()
        assert row["quarantine_reason"].startswith("listed_token_no_airdrop:")

    def test_stored_defillama_loose_row_is_quarantined(self, repo_conn) -> None:
        """旧采集器写进 raw 的宽松 has_points_program 不能让它混进 projects。"""
        _insert_raw(
            repo_conn,
            "r-defillama-loose",
            "defillama",
            {
                "name": "Loose Restake",
                "sector": "DeFi",
                "no_token_yet": False,
                "symbol": "LRS",
                "gecko_id": "loose-restake",
                "has_points_program": True,
                "description": "restaking vaults with incentive rewards",
            },
        )
        assert CollectorAgent().collect_from_repository(CollectionRepository(repo_conn), limit=10) == []
        row = repo_conn.execute(
            "SELECT quarantine_reason FROM raw_projects WHERE raw_id = 'r-defillama-loose'"
        ).fetchone()
        assert row["quarantine_reason"].startswith("listed_token_no_airdrop:")

    def test_signal_helper_matches_noise_gate(self) -> None:
        blocked = is_listed_token_no_airdrop_signals(
            no_token_yet=False,
            has_points_program=False,
            explicit_points_program=False,
            token_launch_confirmed=True,
            source_id="rootdata",
        )
        exempt = is_listed_token_no_airdrop_signals(
            no_token_yet=False,
            has_points_program=False,
            explicit_points_program=True,
            token_launch_confirmed=True,
            source_id="rootdata",
        )
        assert blocked is True
        assert exempt is False


class TestEligibilityAndSignalLadder:
    """资格门与空投信号阶梯读取同一判定。"""

    def test_listed_generic_project_fails_eligibility(self) -> None:
        project = _listed_project()
        assert project_has_points_program(project) is False
        assert has_post_launch_airdrop_path(project) is False
        assert is_already_launched_without_airdrop_path(project) is True
        assert has_participation_path(project) is False

        decision = apply_eligibility_gate(project, "FARM")
        assert decision.label == "IGNORE"
        assert decision.veto == VETO_ALREADY_LAUNCHED

    def test_listed_generic_project_signal_subscore_capped(self) -> None:
        assert airdrop_signal_subscore(_listed_project()) == 20.0

    def test_explicit_points_field_exempts_launched_project(self) -> None:
        """字段级积分证据仍然有效（口径收紧的是通用词，不是真实积分计划）。"""
        project = _listed_project(explicit_points_program=True, has_points_program=True)
        assert project_has_points_program(project) is True
        assert has_post_launch_airdrop_path(project) is True
        assert is_already_launched_without_airdrop_path(project) is False
        assert apply_eligibility_gate(project, "FARM").veto is None
        assert airdrop_signal_subscore(project) > 35.0


class TestSingleSourceHelpers:
    """全仓唯一判定入口的语义。"""

    def test_resolve_prefers_explicit(self) -> None:
        assert resolve_points_program(explicit=None, has_points=True) is True
        assert resolve_points_program(explicit=False, has_points=True) is False
        assert resolve_points_program(explicit=True, has_points=False) is True

    def test_signals_mapping_uses_same_rule(self) -> None:
        assert signals_have_points_program({"has_points_program": True}) is True
        assert signals_have_points_program({"has_points_program": True, "explicit_points_program": False}) is False
        assert signals_have_points_program({"explicit_points_program": True}) is True
        assert signals_have_points_program(None) is False
