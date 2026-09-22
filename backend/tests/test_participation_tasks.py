"""Participation checklist generation tests."""

import json

from app.services.participation_tasks import generate_participation_tasks
from app.services.project_signals import signals_view


def test_testnet_and_portal_generate_core_tasks():
    data = generate_participation_tasks(
        {
            "id": "p1",
            "name": "QuestNet",
            "url": "https://questnet.xyz",
            "label": "FARM",
            "stage": "testnet",
            "has_testnet": True,
            "has_points_program": True,
            "no_token_yet": True,
            "has_task_portal": True,
            "has_discord": True,
            "has_twitter": True,
            "has_docs": True,
            "has_github": True,
            "sybil_friction": "low",
        }
    )
    ids = {t["id"] for t in data["tasks"]}
    assert "official-task-portal" in ids
    assert "testnet-faucet-and-tx" in ids
    assert "social-discord-join" in ids
    assert "track-log-interaction" in ids
    assert data["summary"]["total"] >= 5
    assert any(t["required"] for t in data["tasks"])


def test_ignore_sparse_project_has_deprioritize():
    data = generate_participation_tasks(
        {
            "id": "p2",
            "name": "Ghost",
            "label": "IGNORE",
            "stage": "ideation",
            "no_token_yet": True,
        }
    )
    ids = {t["id"] for t in data["tasks"]}
    assert "track-deprioritize" in ids or "official-watch-announcement" in ids


# ── 存储形态回归 ──────────────────────────────────────────────
# 上面两个用例传的是**扁平** dict，而真实的 projects 行把扩展信号存在
# meta.signals 里、表本身没有这些列。于是线上每个项目的信号判断全部恒为
# False，281 个项目拿到的都是同一份通用兜底清单（实测最高分项目也只有 5 条），
# 而这两个用例照样通过 —— 这正是该 bug 能长期潜伏的原因。
# 下面用真实存储形态断言，防止回归。


def _row_like(signals: dict) -> dict:
    """模拟一行真实的 projects 记录：信号只存在 meta.signals，顶层没有这些列。"""
    return {
        "id": "p3",
        "name": "MetaShape",
        "url": "https://metashape.xyz",
        "label": "FARM",
        "stage": "testnet",
        "meta": json.dumps({"signals": signals}, ensure_ascii=False),
    }


def test_meta_signals_are_actually_used():
    """经 signals_view 后，meta.signals 必须真正驱动任务生成。"""
    row = _row_like(
        {
            "has_testnet": True,
            "has_task_portal": True,
            "has_points_program": True,
            "has_discord": True,
            "explicit_airdrop_mention": True,
            "sybil_friction": "high",
        }
    )

    raw = generate_participation_tasks(dict(row))
    viewed = generate_participation_tasks(signals_view(row))

    raw_ids = {t["id"] for t in raw["tasks"]}
    viewed_ids = {t["id"] for t in viewed["tasks"]}

    # 直接传原始行时这些任务全都出不来（信号读不到）
    assert "official-task-portal" not in raw_ids
    assert "risk-kyc-decision" not in raw_ids

    # 经 signals_view 后必须出现
    assert "official-task-portal" in viewed_ids
    assert "official-airdrop-rules" in viewed_ids
    assert "social-discord-join" in viewed_ids
    assert "risk-kyc-decision" in viewed_ids
    assert viewed["summary"]["total"] > raw["summary"]["total"]
    assert viewed["signals_used"]["has_task_portal"] is True
    assert viewed["signals_used"]["sybil_friction"] == "high"


def test_signals_view_prefers_top_level_over_meta():
    """顶层是权威值：已迁移到真实列的字段不应被 meta 里的旧快照覆盖。"""
    row = _row_like({"has_testnet": False, "sybil_friction": "low"})
    row["has_testnet"] = True  # 顶层显式为真
    row["sybil_friction"] = "high"

    view = signals_view(row)
    assert view["has_testnet"] is True
    assert view["sybil_friction"] == "high"


def test_signals_view_keeps_observed_false_from_meta():
    """meta 里显式为 False 是有效观测，展平后不得变成 True/缺失。"""
    view = signals_view(_row_like({"has_testnet": False, "github_stars": 0}))
    assert view["has_testnet"] is False
    assert view["github_stars"] == 0


def test_signals_view_tolerates_missing_or_broken_meta():
    assert signals_view({"id": "x"}) == {"id": "x"}
    assert signals_view({"id": "x", "meta": None})["id"] == "x"
    assert signals_view({"id": "x", "meta": "not-json"})["id"] == "x"
    assert signals_view({"id": "x", "meta": json.dumps({"signals": "wrong-type"})})["id"] == "x"
    assert signals_view(None) == {}


def test_curated_protocol_tasks_enrichment():
    """验证重点 FARM 项目生成协议专属的高置信度指引及富文本字段。"""
    # 1. Symbiotic
    symbiotic = generate_participation_tasks(
        {
            "id": "76ad0874-e3e7-5067-8aef-d6d92449aa5a",
            "name": "Symbiotic",
            "sector": "Collateral Markets",
            "label": "FARM",
            "url": "https://symbiotic.fi",
        }
    )
    symbiotic_ids = {t["id"] for t in symbiotic["tasks"]}
    assert "curated-symbiotic-vault-deposit" in symbiotic_ids
    curated_task = next(t for t in symbiotic["tasks"] if t["id"] == "curated-symbiotic-vault-deposit")
    assert curated_task["estimated_gas"] is not None
    assert "wstETH" in curated_task["recommended_asset"]
    assert len(curated_task["execution_steps"]) >= 3
    assert curated_task["anti_sybil_tip"] is not None
    assert curated_task["dapp_url"] == "https://app.symbiotic.fi"

    # 2. Berachain
    bera = generate_participation_tasks(
        {
            "id": "bera-1",
            "name": "Berachain",
            "sector": "DeFi",
            "label": "FARM",
            "stage": "testnet",
        }
    )
    bera_ids = {t["id"] for t in bera["tasks"]}
    assert "curated-berachain-artio-loop" in bera_ids
    bera_task = next(t for t in bera["tasks"] if t["id"] == "curated-berachain-artio-loop")
    assert "0 USD" in bera_task["estimated_gas"]
    assert "BERA" in bera_task["recommended_asset"]

    # 3. Mantle Restaking
    mantle = generate_participation_tasks(
        {
            "id": "mantle-1",
            "name": "Mantle Restaking",
            "sector": "Liquid Restaking",
            "label": "FARM",
        }
    )
    mantle_ids = {t["id"] for t in mantle["tasks"]}
    assert "curated-mantle-restaking" in mantle_ids

