"""项目身份别名解析（app/identity.py）与采集归并的回归测试。

覆盖用户明确要求的边界：
- 未命中别名时 project_id 与旧 uuid5 完全一致（不漂移）
- 手工别名可信度最高，能覆盖回填/自动推断
- 同名多赛道不会被自动合并
- 别名命中后多个 dedup_key 合成同一个 RawProject
- 回填脚本 dry-run 不写库、冲突只报告
"""

from __future__ import annotations

import sqlite3

import pytest

from app.agents.collector import CollectorAgent
from app.db import DbConnection, init_db
from app.identity import (
    ALIAS_SOURCE_AUTO,
    ALIAS_SOURCE_BACKFILL,
    ALIAS_SOURCE_MANUAL,
    ProjectIdentityResolver,
    backfill_project_aliases,
    make_alias_key,
)
from app.utils.normalize import create_dedup_key, generate_deterministic_id


@pytest.fixture
def conn(tmp_path):
    raw = sqlite3.connect(tmp_path / "identity.db")
    raw.row_factory = sqlite3.Row
    db = DbConnection(raw, kind="sqlite")
    init_db(db)
    yield db
    db.close()


@pytest.fixture
def resolver(conn):
    return ProjectIdentityResolver(conn)


def _record(name: str, sector: str | None, source: str, raw_id: str) -> dict:
    return {
        "_dedup_key": create_dedup_key(name, sector),
        "name": name,
        "sector": sector,
        "source": source,
        "raw_id": raw_id,
    }


# ── 解析优先级 ──────────────────────────────────


def test_legacy_id_is_identical_to_old_uuid5(resolver):
    """没有别名时必须逐字节复用旧 ID，保证历史评分/历史记录不断裂。"""
    identity = resolver.resolve("Layer-X Finance", "layer2")

    assert identity.project_id == generate_deterministic_id(create_dedup_key("Layer-X Finance", "layer2"))
    assert identity.matched == "legacy"
    assert identity.is_legacy is True
    assert identity.source is None


def test_manual_alias_outranks_backfill_and_auto(resolver):
    resolver.upsert_alias("Acme::DeFi", "pid-backfill", source=ALIAS_SOURCE_BACKFILL)
    # 自动别名不能覆盖回填
    blocked = resolver.upsert_alias("Acme::DeFi", "pid-auto", source=ALIAS_SOURCE_AUTO)
    assert blocked["applied"] is False
    # 手工别名可以覆盖回填
    assert resolver.upsert_alias("Acme::DeFi", "pid-manual", source=ALIAS_SOURCE_MANUAL)["applied"] is True

    identity = resolver.resolve("ACME", "defi")
    assert identity.project_id == "pid-manual"
    assert identity.matched == "manual_exact"
    assert identity.confidence == 1.0

    # 自动别名也不能反向覆盖手工
    assert resolver.upsert_alias("Acme::DeFi", "pid-other", source=ALIAS_SOURCE_AUTO)["applied"] is False
    assert resolver.resolve("Acme", "DeFi").project_id == "pid-manual"


def test_manual_name_wide_beats_backfill_exact(resolver):
    """名称级手工别名优先于精确的回填别名；且跨赛道都归到同一项目。"""
    resolver.upsert_alias(
        make_alias_key("Nexus", name_wide=True),
        "pid-wide",
        source=ALIAS_SOURCE_MANUAL,
    )
    resolver.upsert_alias("Nexus::L1", "pid-l1", source=ALIAS_SOURCE_BACKFILL)

    assert resolver.resolve("Nexus", "L1").matched == "manual_name"
    assert resolver.resolve("Nexus", "L1").project_id == "pid-wide"
    assert resolver.resolve("Nexus", "Gaming").project_id == "pid-wide"


def test_same_name_multi_sector_is_not_merged(resolver):
    """同名多赛道：只认精确键，未命中的赛道继续走旧 uuid5，绝不猜测合并。"""
    resolver.upsert_alias("Nexus::L1", "pid-l1", source=ALIAS_SOURCE_BACKFILL)

    l1 = resolver.resolve("Nexus", "L1")
    gaming = resolver.resolve("Nexus", "Gaming")

    assert l1.project_id == "pid-l1"
    assert gaming.project_id != l1.project_id
    assert gaming.is_legacy is True

    # 名称级别名只有手工能写，自动推断不得越权
    with pytest.raises(ValueError):
        resolver.upsert_alias(make_alias_key("Nexus", name_wide=True), "pid-l1", source=ALIAS_SOURCE_AUTO)


def test_alias_keys_are_normalized_on_write(resolver):
    resolver.upsert_alias("Uniswap Protocol::de-fi", "pid-uni", source=ALIAS_SOURCE_MANUAL)

    rows = resolver.list_aliases(project_id="pid-uni")

    assert [row["dedup_key"] for row in rows] == ["uniswap::DeFi"]
    assert resolver.resolve("Uniswap", "DeFi").project_id == "pid-uni"


# ── 采集归并 ────────────────────────────────────


def test_dedup_merges_aliased_keys_into_one_project(resolver):
    pid = "11111111-1111-5111-8111-111111111111"
    resolver.upsert_alias("Jito::Liquid Staking", pid, source=ALIAS_SOURCE_MANUAL)
    resolver.upsert_alias("JitoSol::Liquid Staking", pid, source=ALIAS_SOURCE_MANUAL)

    agent = CollectorAgent()
    projects = agent._dedup_records(
        [
            _record("Jito", "Liquid Staking", "defillama", "r1"),
            _record("JitoSol", "Liquid Staking", "twitter", "r2"),
        ],
        resolver,
    )

    assert len(projects) == 1
    assert projects[0].id == pid
    assert projects[0].raw_ids == ["r1", "r2"]


def test_dedup_keeps_same_name_multi_sector_apart(resolver):
    pid = "22222222-2222-5222-8222-222222222222"
    resolver.upsert_alias("Nexus::L1", pid, source=ALIAS_SOURCE_BACKFILL)

    agent = CollectorAgent()
    projects = agent._dedup_records(
        [
            _record("Nexus", "L1", "defillama", "r1"),
            _record("Nexus", "Gaming", "defillama", "r2"),
        ],
        resolver,
    )

    assert sorted(project.id for project in projects) == sorted(
        [pid, generate_deterministic_id(create_dedup_key("Nexus", "Gaming"))]
    )


def test_folded_sectorless_key_learns_auto_alias(conn, resolver):
    """赛道未知的信号源分组被折叠后，该键应学成 auto 别名，下一轮直接命中。"""
    target_id = generate_deterministic_id(create_dedup_key("Jito", "Liquid Staking"))

    projects = CollectorAgent()._dedup_records(
        [
            _record("Jito", "Liquid Staking", "defillama", "r1"),
            _record("Jito", None, "galxe", "r2"),
        ],
        resolver,
    )

    assert len(projects) == 1
    assert projects[0].id == target_id

    fresh = ProjectIdentityResolver(conn)
    learned = fresh.resolve("Jito", None)
    assert learned.project_id == target_id
    assert learned.matched == "auto_exact"


# ── 回填 ────────────────────────────────────────


def test_backfill_dry_run_reports_conflicts_without_writing(conn, resolver):
    conn.execute("INSERT INTO projects (id, name, sector) VALUES (?, ?, ?)", ("pid-a", "Nexus", "L1"))
    conn.execute("INSERT INTO projects (id, name, sector) VALUES (?, ?, ?)", ("pid-b", "Nexus", "L1"))
    conn.execute("INSERT INTO projects (id, name, sector) VALUES (?, ?, ?)", ("pid-c", "Aave", "Lending"))
    conn.commit()

    report = backfill_project_aliases(apply=False, conn=conn)
    payload = report.to_dict()

    assert payload["apply"] is False
    assert payload["scanned"] == 3
    assert payload["candidate_count"] == 1
    assert payload["applied"] == 0
    reasons = {item["reason"] for item in payload["conflicts"]}
    assert reasons == {"multiple_projects_share_key"}
    # dry-run 不写库
    assert resolver.list_aliases() == []


def test_backfill_apply_pins_project_id(conn):
    conn.execute("INSERT INTO projects (id, name, sector) VALUES (?, ?, ?)", ("pid-aave", "Aave", "Lending"))
    conn.commit()

    report = backfill_project_aliases(apply=True, conn=conn)

    assert report.applied == 1
    identity = ProjectIdentityResolver(conn).resolve("Aave", "Lending")
    assert identity.project_id == "pid-aave"
    assert identity.matched == "backfill_exact"
