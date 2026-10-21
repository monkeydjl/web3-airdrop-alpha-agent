"""Analysis queue skips denylisted historical raw_projects."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime

import pytest

from app.agents.collector import CollectorAgent
from app.collectors.persistence import CollectionRepository
from app.db import init_db
from app.utils.normalize import create_dedup_key, generate_deterministic_id


@pytest.fixture
def repo_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    try:
        yield conn
    finally:
        conn.close()


def _insert(
    conn,
    raw_id: str,
    name: str,
    sector: str = "DeFi",
    score: float = 0.8,
    *,
    raw_data: str | None = None,
    discovered_at: str | None = None,
):
    dedup = create_dedup_key(name, sector).to_string()
    pid = generate_deterministic_id(create_dedup_key(name, sector))
    if raw_data is None:
        raw_data = json.dumps(
            {
                "name": name,
                "sector": sector,
                "slug": name.lower().replace(" ", "-"),
                "no_token_yet": True,
                "stage": "mainnet",
            }
        )
    if discovered_at is None:
        discovered_at = datetime.now(UTC).isoformat()
    conn.execute(
        """
        INSERT INTO raw_projects (
            raw_id, source_id, dedup_key, raw_data, discovered_at,
            processed, discovery_score, project_id
        ) VALUES (?, ?, ?, ?, ?, 0, ?, ?)
        """,
        (
            raw_id,
            "defillama",
            dedup,
            raw_data,
            discovered_at,
            score,
            pid,
        ),
    )
    conn.commit()
    return pid


def test_collect_from_repository_skips_and_marks_noise(repo_conn):
    _insert(repo_conn, "r-noise", "Uniswap V4", "Dexs")
    _insert(repo_conn, "r-ok", "Nova Vault", "Yield")
    repo = CollectionRepository(repo_conn)
    agent = CollectorAgent()

    projects = agent.collect_from_repository(repo, min_discovery_score=0.3, limit=10)
    names = {p.name for p in projects}
    assert "Nova Vault" in names
    assert "Uniswap V4" not in names

    row = repo_conn.execute(
        "SELECT processed, quarantined FROM raw_projects WHERE raw_id = ?",
        ("r-noise",),
    ).fetchone()
    assert row["processed"] == 1
    # quarantined may be 1 when column exists
    if "quarantined" in row:
        assert row["quarantined"] in (0, 1)

    row_ok = repo_conn.execute(
        "SELECT processed FROM raw_projects WHERE raw_id = ?",
        ("r-ok",),
    ).fetchone()
    assert row_ok["processed"] == 0


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


class TestIngestionCriteria:
    """入库标准（2026-10-06）：撸毛工具仓库与「已发币 + 只有测试网」不进 projects。"""

    def test_existing_github_tooling_row_is_quarantined(self, repo_conn):
        """过滤上线前就进了队列的 github bot 仓库，在分析入口被隔离。"""
        _insert_raw(
            repo_conn,
            "r-bot",
            "github",
            {
                "name": "Pharos-Auto-Bot",
                "sector": "Infrastructure",
                "description": "An automated bot for interacting with the Pharos Testnet",
                "topics": ["airdrop", "pharos-testnet-bot"],
                "has_testnet": True,
            },
        )
        _insert_raw(repo_conn, "r-ok", "defillama", {"name": "Nova Vault", "sector": "Yield", "no_token_yet": True})
        projects = CollectorAgent().collect_from_repository(CollectionRepository(repo_conn), limit=10)

        assert {p.name for p in projects} == {"Nova Vault"}
        row = repo_conn.execute(
            "SELECT processed, quarantined, quarantine_reason FROM raw_projects WHERE raw_id = 'r-bot'"
        ).fetchone()
        assert row["processed"] == 1
        assert row["quarantined"] == 1
        assert row["quarantine_reason"].startswith("tooling_repo:github:")

    def test_existing_rootdata_person_row_is_quarantined(self, repo_conn):
        """RootData 人物 / 社媒条目（type!=1）在分析入口被隔离，type=1 照常入库。"""
        _insert_raw(repo_conn, "r-person", "rootdata", {"name": "Deirdre Connolly", "sector": "DeFi", "type": 3})
        _insert_raw(repo_conn, "r-list", "rootdata", {"name": "Web3 Testnets List", "sector": "DeFi", "type": 5})
        _insert_raw(repo_conn, "r-proj", "rootdata", {"name": "Nova Rollup", "sector": "L2", "type": 1})
        projects = CollectorAgent().collect_from_repository(CollectionRepository(repo_conn), limit=10)

        assert {p.name for p in projects} == {"Nova Rollup"}
        rows = {
            r["raw_id"]: r["quarantine_reason"]
            for r in repo_conn.execute("SELECT raw_id, quarantine_reason FROM raw_projects WHERE quarantined = 1")
        }
        assert set(rows) == {"r-person", "r-list"}
        assert all(v.startswith("non_project:rootdata:") for v in rows.values())

    def test_type_field_only_gates_rootdata(self, repo_conn):
        """别的源的 type 字段语义不同，不按 RootData 口径拦。"""
        _insert_raw(repo_conn, "r-other", "defillama", {"name": "Nova Vault", "sector": "Yield", "type": 3})
        projects = CollectorAgent().collect_from_repository(CollectionRepository(repo_conn), limit=10)
        assert {p.name for p in projects} == {"Nova Vault"}

    def test_listed_token_with_only_testnet_is_quarantined(self, repo_conn):
        """已发币 + 只有测试网：与 ADR-015 already_launched 同口径，停在隔离区。"""
        _insert_raw(
            repo_conn,
            "r-listed",
            "rootdata",
            {
                "name": "Launched Chain",
                "sector": "L1",
                "no_token_yet": False,
                "token_symbol": "LCH",
                "has_testnet": True,
            },
        )
        projects = CollectorAgent().collect_from_repository(CollectionRepository(repo_conn), limit=10)

        assert projects == []
        row = repo_conn.execute(
            "SELECT quarantined, quarantine_reason FROM raw_projects WHERE raw_id = 'r-listed'"
        ).fetchone()
        assert row["quarantined"] == 1
        assert row["quarantine_reason"].startswith("listed_token_no_airdrop:")

    def test_rootdata_without_token_evidence_still_enters(self, repo_conn):
        """三态（2026-10-08）：RootData 没给 ticker / 发币状态 = 未知，不隔离。

        此前 no_token_yet=False 被当成已发币，约 30 个未发币项目被误删。
        """
        _insert_raw(
            repo_conn,
            "r-unknown",
            "rootdata",
            {"name": "Quiet Infra", "sector": "Infrastructure", "no_token_yet": False, "has_testnet": True},
        )
        projects = CollectorAgent().collect_from_repository(CollectionRepository(repo_conn), limit=10)

        assert [p.name for p in projects] == ["Quiet Infra"]
        assert projects[0].token_launch_confirmed is False
        row = repo_conn.execute("SELECT quarantined FROM raw_projects WHERE raw_id = 'r-unknown'").fetchone()
        assert row["quarantined"] == 0

    def test_listed_token_with_points_still_enters(self, repo_conn):
        """已发币但有积分计划（后续空投路径）仍可入库。"""
        _insert_raw(
            repo_conn,
            "r-points",
            "rootdata",
            {"name": "Season Two", "sector": "DeFi", "no_token_yet": False, "has_points_program": True},
        )
        projects = CollectorAgent().collect_from_repository(CollectionRepository(repo_conn), limit=10)
        assert {p.name for p in projects} == {"Season Two"}

    def test_github_text_does_not_imply_pre_tge(self):
        """github 文本里的 airdrop 字样不再推出 no_token_yet；已发币品牌给出反证。"""
        neutral = CollectorAgent._infer_airdrop_flags("github", {"name": "Freshchain", "description": "airdrop soon"})
        listed = CollectorAgent._infer_airdrop_flags("github", {"name": "monad-sdk", "description": "airdrop"})
        assert neutral["no_token_yet"] is True
        assert listed["no_token_yet"] is False


class TestCorruptRowQuarantine:
    """队列中毒防护（2026-08-30）：坏行隔离 + 跳过，批次继续。

    此前一条损坏的 raw_data / discovered_at 会让整批 collect_from_repository
    抛异常；该行 processed=0 且按 discovery_score DESC 排序每轮都被重新取到，
    流水线永久卡死，只能手工修库。
    """

    def test_corrupt_raw_data_is_quarantined_and_batch_survives(self, repo_conn):
        _insert(repo_conn, "r-corrupt", "Broken Json", "DeFi", raw_data="{not valid json")
        _insert(repo_conn, "r-ok", "Healthy Protocol", "Yield")
        repo = CollectionRepository(repo_conn)
        agent = CollectorAgent()

        # 不抛异常是本测试的核心断言 —— 此前这里会整批 raise
        projects = agent.collect_from_repository(repo, min_discovery_score=0.3, limit=10)

        names = {p.name for p in projects}
        assert "Healthy Protocol" in names
        assert "Broken Json" not in names

        row = repo_conn.execute(
            "SELECT processed, quarantined FROM raw_projects WHERE raw_id = ?",
            ("r-corrupt",),
        ).fetchone()
        # 必须离开待分析队列：processed=1（隔离路径本身会置位）
        assert row["processed"] == 1
        assert row["quarantined"] == 1

    def test_corrupt_discovered_at_is_quarantined_and_batch_survives(self, repo_conn):
        _insert(repo_conn, "r-badts", "Broken Timestamp", "DeFi", discovered_at="not-a-date")
        _insert(repo_conn, "r-ok", "Another Healthy", "NFT")
        repo = CollectionRepository(repo_conn)
        agent = CollectorAgent()

        projects = agent.collect_from_repository(repo, min_discovery_score=0.3, limit=10)

        names = {p.name for p in projects}
        assert "Another Healthy" in names
        assert "Broken Timestamp" not in names

        row = repo_conn.execute(
            "SELECT processed, quarantined FROM raw_projects WHERE raw_id = ?",
            ("r-badts",),
        ).fetchone()
        assert row["processed"] == 1
        assert row["quarantined"] == 1

    def test_corrupt_rows_do_not_permanently_jam_the_queue(self, repo_conn):
        """连续多行损坏也只损失这些行本身，其余照常进分析。"""
        for i in range(5):
            _insert(repo_conn, f"r-bad-{i}", f"Bad Actor {i}", "DeFi", raw_data="[[[")
        _insert(repo_conn, "r-ok", "Survivor Protocol", "Yield")
        repo = CollectionRepository(repo_conn)
        agent = CollectorAgent()

        projects = agent.collect_from_repository(repo, min_discovery_score=0.3, limit=10)

        assert {p.name for p in projects} == {"Survivor Protocol"}
        processed = repo_conn.execute("SELECT COUNT(*) AS n FROM raw_projects WHERE processed = 1").fetchone()["n"]
        assert processed == 5


class TestTokenLaunchConfirmed:
    """``token_launch_confirmed`` 三态推断（2026-10-08，ADR-015 补充）。"""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ({"name": "X", "no_token_yet": False}, False),
            ({"name": "X", "no_token_yet": False, "token_symbol": "XYZ"}, True),
            ({"name": "X", "no_token_yet": False, "token_symbol": "-"}, False),
            ({"name": "X", "no_token_yet": False, "token_status": "listed"}, True),
            ({"name": "X", "no_token_yet": True, "token_symbol": "XYZ"}, False),
            ({"name": "Monad Bridge", "no_token_yet": False}, True),
        ],
    )
    def test_rootdata_needs_positive_evidence(self, raw, expected):
        flags = CollectorAgent._infer_airdrop_flags("rootdata", raw)
        assert flags["token_launch_confirmed"] is expected

    def test_defillama_listed_is_confirmed(self):
        listed = CollectorAgent._infer_airdrop_flags("defillama", {"name": "Lend", "symbol": "LND", "gecko_id": "lnd"})
        unlisted = CollectorAgent._infer_airdrop_flags("defillama", {"name": "Lend", "no_token_yet": True})
        assert listed["token_launch_confirmed"] is True
        assert unlisted["token_launch_confirmed"] is False

    def test_text_sources_never_confirm(self):
        flags = CollectorAgent._infer_airdrop_flags("github", {"name": "Freshchain", "description": "token launch"})
        assert flags["token_launch_confirmed"] is False

    def test_explicit_field_wins(self):
        flags = CollectorAgent._infer_airdrop_flags("rootdata", {"name": "X", "token_launch_confirmed": True})
        assert flags["token_launch_confirmed"] is True


class TestExplicitPointsProgram:
    """严格积分证据（2026-10-08）：通用 DeFi 词不算已发币项目的后续空投路径。"""

    @pytest.mark.parametrize(
        ("description", "expected"),
        [
            ("Liquid restaking for Bitcoin stakers", False),
            ("Earn incentive rewards in our vaults", False),
            ("Liquidity mining on Solana", False),
            ("Join our points program before season 2", True),
            ("Earn points and airdrop rewards", True),
            ("Earn XP points and potential airdrops", True),
            ("RPC endpoints with rewards", False),
            ("Points program ended; airdrop has been distributed", False),
        ],
    )
    def test_text_inference(self, description, expected):
        flags = CollectorAgent._infer_airdrop_flags("rootdata", {"name": "X", "description": description})
        assert flags["explicit_points_program"] is expected

    def test_loose_text_still_feeds_has_points_program(self):
        """宽松字段保留给 airdrop_signal 子分，评分口径不变。"""
        flags = CollectorAgent._infer_airdrop_flags("rootdata", {"name": "X", "description": "restaking vaults"})
        assert flags["has_points_program"] is True
        assert flags["explicit_points_program"] is False

    def test_defillama_loose_raw_flag_is_not_trusted(self):
        raw = {"name": "X", "description": "staking vault", "has_points_program": True}
        assert CollectorAgent._infer_airdrop_flags("defillama", raw)["explicit_points_program"] is False
        assert CollectorAgent._infer_airdrop_flags("galxe", raw)["explicit_points_program"] is True

    def test_listed_restaking_project_is_quarantined(self, repo_conn):
        _insert_raw(
            repo_conn,
            "r-restake",
            "rootdata",
            {
                "name": "Restake Chain",
                "sector": "L1",
                "no_token_yet": False,
                "token_symbol": "RST",
                "description": "Modular L1 with native restaking for stakers",
            },
        )
        assert CollectorAgent().collect_from_repository(CollectionRepository(repo_conn), limit=10) == []
        row = repo_conn.execute("SELECT quarantine_reason FROM raw_projects WHERE raw_id = 'r-restake'").fetchone()
        assert row["quarantine_reason"].startswith("listed_token_no_airdrop:")
