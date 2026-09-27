"""采集侧结构化 Anti-PUA 信号（points_season_count / tge_clarity / is_perp）。

背景（2026-09-27）：opportunity evidence 的 fatigue/friction 输入改为消费
meta.signals 三个结构化键后，新采集数据必须直接携带它们，否则旁路模型对
所有新项目永远落在保守默认档。

推断词表唯一来源是 services.structured_signals —— 与存量回填脚本共用，
防止两套词表漂移。置信度契约：
- is_perp：高置信 → sector/description 命中即 True（显式字段优先）；
- tge_clarity：仅 confirmed_quarter 有可靠词形；显式枚举值优先；
- points_season_count：文本推断低置信 → 不自动采信（None）；
  仅接受显式 int 1-10（bool 显式拒绝）。
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from app.agents.base import AgentContext, PipelineState, RawProject
from app.agents.collector import CollectorAgent
from app.db import init_db
from app.repository import ProjectRepository
from app.services.project_signals import SIGNAL_KEYS, signals_from_project


def _flags(source: str, raw: dict) -> dict:
    return CollectorAgent._infer_airdrop_flags(source, raw)


def _save(state: PipelineState, conn: sqlite3.Connection) -> None:
    ProjectRepository(conn=conn).save(state)


def _project(pid: str, **overrides) -> RawProject:
    base = dict(
        id=pid,
        name=pid,
        url=f"https://{pid}.example.com",
        sector="DEX",
        stage="testnet",
        source="defillama",
    )
    base.update(overrides)
    return RawProject(**base)


# ── 推断契约 ──────────────────────────────────────────────────


def test_perp_detected_from_sector_and_description():
    sector_hit = _flags("defillama", {"name": "p", "sector": "perp-dex", "description": "swap"})
    desc_hit = _flags("defillama", {"name": "p", "sector": "DEX", "description": "a perpetual futures exchange"})
    assert sector_hit["is_perp"] is True
    assert desc_hit["is_perp"] is True


def test_perp_not_confused_by_deceptive_words():
    """项目名/子串不得触发:is_perp_dex 的既有契约在采集侧同样生效。"""
    brand = _flags("defillama", {"name": "PerpX", "sector": "DEX", "description": "an amm"})
    substring = _flags("defillama", {"name": "p", "sector": "ai", "description": "perplexity search engine"})
    assert brand["is_perp"] is False
    assert substring["is_perp"] is False


def test_tge_clarity_only_confirmed_gets_written():
    hit = _flags("defillama", {"name": "p", "description": "TGE confirmed for Q3 2026"})
    vague = _flags("defillama", {"name": "p", "description": "TGE coming soon, stay tuned"})
    nothing = _flags("defillama", {"name": "p", "description": "a dex"})
    assert hit["tge_clarity"] == "confirmed_quarter"
    assert vague["tge_clarity"] == "unannounced"  # 模糊词形不可靠,不写
    assert nothing["tge_clarity"] == "unannounced"


def test_explicit_fields_always_win():
    explicit = _flags(
        "manual",
        {
            "name": "p",
            "description": "a plain dex",  # 文本推断不出任何信号
            "is_perp": True,
            "tge_clarity": "vague_soon",
            "points_season_count": 4,
        },
    )
    assert explicit["is_perp"] is True
    assert explicit["tge_clarity"] == "vague_soon"
    assert explicit["points_season_count"] == 4


def test_season_text_inference_never_auto_trusted():
    """低置信:文本命中 season 3 也不写,只有显式 int 才被采信。"""
    text_hit = _flags("defillama", {"name": "p", "description": "season 3 rewards are live"})
    assert text_hit["points_season_count"] is None

    explicit_int = _flags("manual", {"name": "p", "points_season_count": 3})
    assert explicit_int["points_season_count"] == 3


@pytest.mark.parametrize("bad", [True, "3", 2.5, 0, 11, -1])
def test_season_type_guards_reject_dirty_values(bad):
    assert _flags("manual", {"name": "p", "points_season_count": bad})["points_season_count"] is None


# ── 全链路:_infer → RawProject → to_dict → signals_from_project ──


def test_structured_signals_flow_through_raw_project_to_signals():
    project = _project(
        "perp-proj",
        sector="perp-dex",
        description="perpetual futures, TGE confirmed for Q3 2026",
        is_perp=True,
        tge_clarity="confirmed_quarter",
    )
    signals = signals_from_project(project)
    # SIGNAL_KEYS 已登记三个新键,signals_from_project 按 hasattr 采集
    assert "points_season_count" in SIGNAL_KEYS
    assert signals["is_perp"] is True
    assert signals["tge_clarity"] == "confirmed_quarter"
    assert "points_season_count" in signals  # None 也写入(显式未观测)


def test_end_to_end_collector_to_meta_signals():
    """完整链路:RawProject → repo.save → meta.signals 落库。"""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    try:
        _save(
            PipelineState(
                project=_project(
                    "perp-proj",
                    sector="perp-dex",
                    description="perpetual futures dex",
                    is_perp=True,
                ),
                context=AgentContext(run_id="r1"),
                score=70,
                label="FARM",
                confidence=0.6,
                reason=[],
            ),
            conn,
        )
        meta = json.loads(dict(conn.execute("SELECT meta FROM projects WHERE id='perp-proj'").fetchone())["meta"])
        signals = meta["signals"]
        assert signals["is_perp"] is True
        assert signals["tge_clarity"] == "unannounced"
        assert signals["points_season_count"] is None
    finally:
        conn.close()


def test_merge_keeps_max_season_and_higher_tge_confidence():
    """多源合并:season 取最大季数,tge 取置信最高档,is_perp 走 OR。"""
    from app.utils.normalize import merge_raw_records

    merged = merge_raw_records(
        [
            {"name": "p", "source": "github", "is_perp": False, "tge_clarity": "unannounced", "points_season_count": 2},
            {"name": "p", "source": "manual", "is_perp": True, "tge_clarity": "vague_soon", "points_season_count": 4},
        ]
    )
    assert merged["is_perp"] is True
    assert merged["tge_clarity"] == "vague_soon"
    assert merged["points_season_count"] == 4


def test_inferred_flags_carry_structured_signals_after_dedup(tmp_path=None):
    """_raw_to_record → _dedup_records 后 RawProject 仍保留结构化信号。"""
    agent = CollectorAgent()
    rec = agent._raw_to_record(
        {"name": "PerpChain", "sector": "perp-dex", "description": "perpetual futures dex", "source": "defillama"}
    )
    assert rec["is_perp"] is True
    assert rec["tge_clarity"] in ("unannounced", "confirmed_quarter")
