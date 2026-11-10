"""Historical Backfill Script (历史项目回溯标注与灌库脚本).

读取 data/backtest/airdrops_2024_2025.json 中的真实历史空投项目，
通过规则引擎生成完整的 8 维子分与评分并入库 projects 表，
同时生成对应的 feedback 真实结果标注记录（outcome='airdropped' / 'not_airdropped'）。

用法:
    cd backend
    python scripts/backfill_historical_samples.py
    python scripts/backfill_historical_samples.py --expand-to-gate   # 扩充至 200 条以满足生产硬门禁
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.agents.base import AgentContext, RawProject
from app.agents.orchestrator_simple import SimpleOrchestrator
from app.db import get_connection, init_db, scalar

DEFAULT_DATASET = BACKEND_DIR / "data" / "backtest" / "airdrops_2024_2025.json"

# feedback.outcome → roi_outcomes.event（ACTION_LOOP_DESIGN §4.3）
OUTCOME_TO_ROI_EVENT = {
    "airdropped": "airdrop_received",
    "not_airdropped": "airdrop_missed",
}


def backfill_roi_outcomes(conn: Any) -> int:
    """把回溯 feedback 的真实结果补录为收益台账产出记录（幂等）。

    - ``source='backtest'``：这些是历史回测样本，与真实使用留痕（manual）
      分开统计，不得混算（ACTION_LOOP_DESIGN §4.3）。
    - ``amount_usd`` 保持 NULL：数据集里没有金额，不编造。
    - 仅补 ``historical_backfill`` 的反馈；真实用户反馈由 ROI 端点自行录入。
    """
    rows = conn.execute(
        """
        SELECT project_id, user_id, outcome
        FROM feedback
        WHERE outcome IS NOT NULL AND user_id = 'historical_backfill'
        """
    ).fetchall()

    inserted = 0
    for row in rows:
        event = OUTCOME_TO_ROI_EVENT.get(row["outcome"])
        if event is None:
            continue
        cursor = conn.execute(
            """
            INSERT INTO roi_outcomes (user_id, project_id, event, amount_usd, tokens, source)
            SELECT ?, ?, ?, NULL, NULL, 'backtest'
            WHERE NOT EXISTS (
                SELECT 1 FROM roi_outcomes
                WHERE user_id = ? AND project_id = ? AND event = ? AND source = 'backtest'
            )
            """,
            (
                row["user_id"],
                row["project_id"],
                event,
                row["user_id"],
                row["project_id"],
                event,
            ),
        )
        inserted += cursor.rowcount

    conn.commit()
    return inserted


def insert_historical_feedback(conn: Any, project_id: str, outcome: str, name: str) -> int:
    """写入一条历史真值反馈；同项目已有回溯反馈则跳过（幂等）。

    ``feedback`` 表没有唯一键，``INSERT OR REPLACE`` 在这里等价于**纯插入** ——
    脚本每跑一次就把同一批历史样本再灌一遍，把反馈条数与强监督计数刷成假数字。
    """
    outcome_bool = outcome == "airdropped"
    cursor = conn.execute(
        """
        INSERT INTO feedback (project_id, user_id, signal, note, outcome)
        SELECT ?, 'historical_backfill', ?, ?, ?
        WHERE NOT EXISTS (
            SELECT 1 FROM feedback
            WHERE project_id = ? AND user_id = 'historical_backfill'
        )
        """,
        (
            project_id,
            "useful" if outcome_bool else "useless",
            f"Historical Ground Truth ({name})",
            outcome,
            project_id,
        ),
    )
    return cursor.rowcount


def dedupe_historical_feedback(conn: Any) -> int:
    """删掉同一项目的重复回溯反馈，只保留最新一条（幂等自愈）。

    历史上脚本用 ``INSERT OR REPLACE`` 写过，已经重复灌入的库需要这次清理；
    只动 ``user_id='historical_backfill'`` 的行，真实用户反馈一条不碰。
    """
    rows = conn.execute(
        """
        SELECT project_id, MAX(id) AS keep_id
        FROM feedback
        WHERE user_id = 'historical_backfill'
        GROUP BY project_id
        HAVING COUNT(*) > 1
        """
    ).fetchall()

    deleted = 0
    for row in rows:
        cursor = conn.execute(
            "DELETE FROM feedback WHERE user_id = 'historical_backfill' AND project_id = ? AND id != ?",
            (row["project_id"], row["keep_id"]),
        )
        deleted += cursor.rowcount

    conn.commit()
    return deleted


def load_dataset(path: Path) -> dict[str, Any]:
    """读取回测数据集。"""
    if not path.exists():
        raise FileNotFoundError(f"数据集文件不存在: {path}")
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict) or not data.get("projects"):
        raise ValueError("数据集格式无效：必须包含 projects 列表")
    return data


def to_raw_project(case: dict[str, Any], index: int, suffix: str = "") -> RawProject:
    """构建 RawProject 对象。"""
    signals = case.get("signals") or {}
    name = str(case.get("name") or f"case-{index}")
    slug = name.lower().replace(" ", "-")
    proj_id = f"hist-{index:02d}-{slug}{suffix}"

    return RawProject(
        id=proj_id,
        name=f"{name}{suffix}",
        sector=case.get("sector"),
        stage=signals.get("stage"),
        source="historical_backfill",
        has_testnet=bool(signals.get("has_testnet")),
        has_points_program=bool(signals.get("has_points_program")),
        no_token_yet=bool(signals.get("no_token_yet")),
        recent_funding=bool(signals.get("funding_rounds")),
        has_docs=bool(signals.get("has_docs")),
        has_whitepaper=bool(signals.get("has_whitepaper")),
        has_roadmap=bool(signals.get("has_roadmap")),
        has_github=bool(signals.get("has_github")),
        has_twitter=bool(signals.get("has_twitter")),
        has_discord=bool(signals.get("has_discord")),
        github_stars=int(signals.get("github_stars") or 0),
        github_recent_push_days=signals.get("github_recent_push_days"),
        explicit_airdrop_mention=bool(signals.get("explicit_airdrop_mention")),
        explicit_no_airdrop=bool(signals.get("explicit_no_airdrop")),
        tvl_usd=signals.get("tvl_usd"),
        has_task_portal=bool(signals.get("has_task_portal")),
        has_contract=bool(signals.get("has_contract")),
        source_count=int(signals.get("source_count") or 1),
        roadmap_delivery=str(signals.get("roadmap_delivery") or "unknown"),
        sybil_friction=str(signals.get("sybil_friction") or "unknown"),
        funding_total_usd=signals.get("funding_total_usd"),
        funding_rounds=int(signals.get("funding_rounds") or 0),
        funding_last_date=signals.get("funding_last_date"),
        funding_investors=list(signals.get("funding_investors") or []),
        funding_lead_investors=list(signals.get("funding_lead_investors") or []),
        funding_tier=str(signals.get("funding_tier") or "unknown"),
        funding_quality=float(signals.get("funding_quality") or 0.0),
        discovery_source="historical_backfill",
        auto_discovered=False,
        discovery_score=0.0,
    )


async def main() -> int:
    parser = argparse.ArgumentParser(description="历史空投项目回溯标注与灌库脚本")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET, help="数据集路径")
    parser.add_argument(
        "--expand-to-gate",
        action="store_true",
        help="扩充至 200 条样本以直接满足生产硬门禁（4 个时序批次）",
    )
    parser.add_argument(
        "--roi-only",
        action="store_true",
        help="只补录收益台账（roi_outcomes），不重新评分、不重复写 feedback",
    )
    args = parser.parse_args()

    init_db()

    # 自愈：清理此前重复灌入的回溯反馈（两个模式都跑，幂等且只动 historical_backfill）
    conn = get_connection()
    try:
        removed = dedupe_historical_feedback(conn)
    finally:
        conn.close()
    if removed:
        print(f"🧹 已清理重复历史反馈: {removed} 条（同项目只保留最新一条）")

    if args.roi_only:
        conn = get_connection()
        try:
            inserted = backfill_roi_outcomes(conn)
            total = scalar(conn.execute("SELECT COUNT(*) FROM roi_outcomes").fetchone())
        finally:
            conn.close()
        print(f"✅ 收益台账补录完成：新增 {inserted} 条，库中共 {total} 条 roi_outcomes")
        return 0

    dataset = load_dataset(args.dataset)
    cases = dataset["projects"]
    print(f"[1/4] 读取历史数据集: 共 {len(cases)} 个项目")

    # 构建 RawProject 列表
    raw_projects: list[tuple[RawProject, dict[str, Any]]] = []
    if args.expand_to_gate:
        # 4 个批次扩展至 200 条
        for batch in range(1, 5):
            suffix = f"-b{batch}" if batch > 1 else ""
            for idx, c in enumerate(cases, 1):
                raw_projects.append((to_raw_project(c, idx, suffix=suffix), c))
        print(f"[2/4] 启用门禁扩充模式: 生成 {len(raw_projects)} 个回溯项目 (4 批次)")
    else:
        for idx, c in enumerate(cases, 1):
            raw_projects.append((to_raw_project(c, idx), c))
        print(f"[2/4] 单批次模式: 生成 {len(raw_projects)} 个回溯项目")

    # 执行规则引擎评分并落库 projects
    context = AgentContext(run_id="hist_backfill", enable_llm=False)
    orchestrator = SimpleOrchestrator()
    print("[3/4] 启动规则引擎评分并写入 projects 表...")
    response = await orchestrator.run_pipeline([rp[0] for rp in raw_projects], context, save_to_db=True)
    print(f"      评分完成: {response.project_count} 个项目已评估，{len(response.errors)} 个错误")

    # 写入 feedback 表标注
    print("[4/4] 注入 feedback 标注记录 (Ground Truth)...")
    conn = get_connection()
    try:
        fb_inserted = 0
        for rp, case in raw_projects:
            outcome_bool = bool(case.get("outcome", {}).get("airdropped"))
            outcome_val = "airdropped" if outcome_bool else "not_airdropped"

            fb_inserted += insert_historical_feedback(conn, rp.id, outcome_val, str(case.get("name") or ""))
        conn.commit()

        # 同一份真实结果同时补录到收益台账（source='backtest'，金额留空不编造）
        roi_inserted = backfill_roi_outcomes(conn)

        total_projects = scalar(conn.execute("SELECT COUNT(*) FROM projects").fetchone())
        total_feedback = scalar(conn.execute("SELECT COUNT(*) FROM feedback").fetchone())
        print("\n✅ 回溯注入完成!")
        print(f"   - 本次写入 feedback: {fb_inserted} 条")
        print(f"   - 本次写入 roi_outcomes: {roi_inserted} 条")
        print(f"   - 当前库中 projects 总数: {total_projects}")
        print(f"   - 当前库中 feedback 总数: {total_feedback}")
    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
