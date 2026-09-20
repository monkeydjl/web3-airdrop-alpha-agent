"""Batch Runway & Viability Audit Script (全库存活率与跑道硬检验批量审计与洗牌脚本).

针对 Web3 市场低迷现状，对数据库中现有项目全量执行存活率与跑道健康度审计：
- 识别 `UNBACKED_POINTS_MACHINE`（零/未知融资纯积分盘）-> 拦截降级至 `IGNORE`
- 识别 `LOW_FUNDING_UNVIABLE`（公开融资 < $3M 且无顶级机构背书）-> 降级至 `WATCH`
- 识别 `RUNWAY_DEPLETED`（小额融资已超 18 个月且开发/TVL停摆）-> 降级至 `WATCH`
- 识别 `borderline` 与 `viable` 稳健项目
- 在 meta 中持久化 `viability_tier` 与 `viability_advisory`

用法:
    backend/venv/Scripts/python.exe backend/scripts/audit_viability.py               # 默认 dry-run 模式（只诊断不改库）
    backend/venv/Scripts/python.exe backend/scripts/audit_viability.py --apply       # 真实应用更新至数据库
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from app.config import settings

# 确保在仓库根目录或 backend 目录下执行时均指向真实 backend/data/airdrop.db
if not Path(settings.db_path).is_absolute():
    backend_db = BACKEND_DIR / settings.db_path
    if backend_db.exists():
        settings.db_path = str(backend_db)

from app.db import dict_from_row, get_connection
from app.opportunity.decision import LOW_RUNWAY_RISK
from app.services.project_signals import funding_public_view, parse_meta
from app.services.viability_gate import (
    LOW_FUNDING_UNVIABLE,
    RUNWAY_DEPLETED,
    UNBACKED_POINTS_MACHINE,
    evaluate_project_viability,
)


def run_viability_audit(*, apply_changes: bool = False) -> dict[str, Any]:
    """执行全库存活率审计并可选更新数据库。"""
    conn = get_connection()
    now = datetime.now(UTC)

    try:
        cursor = conn.execute(
            "SELECT id, name, sector, stage, score, label, reason, meta FROM projects ORDER BY score DESC"
        )
        rows = cursor.fetchall()

        total = len(rows)
        tier_counts = {"viable": 0, "borderline": 0, "unviable": 0}
        reason_counts = {
            UNBACKED_POINTS_MACHINE: 0,
            LOW_FUNDING_UNVIABLE: 0,
            RUNWAY_DEPLETED: 0,
        }
        downgraded_projects: list[dict[str, Any]] = []

        for row in rows:
            p = dict_from_row(row)
            project_id = str(p["id"])
            name = str(p.get("name") or project_id)
            current_label = str(p.get("label") or "WATCH")
            raw_reason = p.get("reason")
            reasons_list: list[str] = (
                json.loads(raw_reason)
                if isinstance(raw_reason, str) and raw_reason.startswith("[")
                else ([str(raw_reason)] if raw_reason else [])
            )

            meta = parse_meta(p.get("meta"))
            signals = meta.get("signals") if isinstance(meta.get("signals"), dict) else {}
            funding = funding_public_view(meta)

            funding_total_usd = signals.get("funding_total_usd") or funding.get("funding_total_usd")
            funding_tier = signals.get("funding_tier") or funding.get("funding_tier")
            funding_rounds = signals.get("funding_rounds") or funding.get("funding_rounds") or 0
            funding_last_date = signals.get("funding_last_date") or funding.get("funding_last_date")
            funding_investors = signals.get("funding_investors") or funding.get("funding_investors") or []
            funding_lead_investors = (
                signals.get("funding_lead_investors") or funding.get("funding_lead_investors") or []
            )
            github_inactive_days = signals.get("github_recent_push_days")
            tvl_usd = signals.get("tvl_usd")
            has_points_program = bool(signals.get("has_points_program"))
            stage = str(p.get("stage") or "ideation")

            res = evaluate_project_viability(
                funding_total_usd=float(funding_total_usd) if funding_total_usd is not None else None,
                funding_tier=str(funding_tier) if funding_tier else None,
                funding_rounds=int(funding_rounds) if funding_rounds else 0,
                funding_last_date=str(funding_last_date) if funding_last_date else None,
                funding_investors=list(funding_investors) if isinstance(funding_investors, (list, tuple)) else [],
                funding_lead_investors=list(funding_lead_investors)
                if isinstance(funding_lead_investors, (list, tuple))
                else [],
                github_inactive_days=int(github_inactive_days) if github_inactive_days is not None else None,
                tvl_usd=float(tvl_usd) if tvl_usd is not None else None,
                has_points_program=has_points_program,
                stage=stage,
                now=now,
            )

            tier = res["tier"]
            tier_counts[tier] = tier_counts.get(tier, 0) + 1
            for r in res["reasons"]:
                reason_counts[r] = reason_counts.get(r, 0) + 1

            # 检查是否需要对 FARM 项目进行门禁降级拦截
            new_label = current_label
            downgraded = False
            if current_label == "FARM" and tier == "unviable":
                if UNBACKED_POINTS_MACHINE in res["reasons"]:
                    new_label = "IGNORE"
                else:
                    new_label = "WATCH"

                if LOW_RUNWAY_RISK not in reasons_list:
                    reasons_list.append(LOW_RUNWAY_RISK)

                downgraded = True
                downgraded_projects.append(
                    {
                        "id": project_id,
                        "name": name,
                        "from_label": current_label,
                        "to_label": new_label,
                        "reasons": list(res["reasons"]),
                        "reasons_zh": list(res["reasons_zh"]),
                    }
                )

            # 持久化更新
            if apply_changes:
                meta["viability_tier"] = tier
                meta["viability_advisory"] = res
                meta_json = json.dumps(meta, ensure_ascii=False)
                reason_json = json.dumps(reasons_list, ensure_ascii=False)

                conn.execute(
                    """
                    UPDATE projects
                    SET label = ?, reason = ?, meta = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (new_label, reason_json, meta_json, now, project_id),
                )

        if apply_changes:
            conn.commit()

        return {
            "total_scanned": total,
            "tier_counts": tier_counts,
            "reason_counts": reason_counts,
            "downgraded_count": len(downgraded_projects),
            "downgraded_projects": downgraded_projects,
            "applied": apply_changes,
        }

    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="全库存活率与跑道硬检验批量审计")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="真实将存活率评级与 FARM 降级更新写入数据库（默认仅 dry-run 输出报告）",
    )
    args = parser.parse_args()

    mode_str = "【真实应用模式 (APPLY)】" if args.apply else "【预览诊断模式 (DRY-RUN)】"
    print(f"\n{'='*60}")
    print(f" Web3 Airdrop Alpha - 项目存活率与跑道门禁批量审计")
    print(f" 运行模式: {mode_str}")
    print(f"{'='*60}\n")

    report = run_viability_audit(apply_changes=args.apply)

    total = report["total_scanned"]
    tiers = report["tier_counts"]
    reasons = report["reason_counts"]
    downgraded = report["downgraded_projects"]

    print(f"总计扫描项目: {total} 个")
    print(f"存活等级分布:")
    print(f"  - 资金充裕 (viable)   : {tiers.get('viable', 0):>4} ({tiers.get('viable', 0)/max(total, 1)*100:.1f}%)")
    print(f"  - 跑道观察 (borderline): {tiers.get('borderline', 0):>4} ({tiers.get('borderline', 0)/max(total, 1)*100:.1f}%)")
    print(f"  - 存活预警 (unviable)  : {tiers.get('unviable', 0):>4} ({tiers.get('unviable', 0)/max(total, 1)*100:.1f}%)")

    print(f"\n存活预警风险触发明细:")
    print(f"  - 零融资纯积分盘 (UNBACKED_POINTS_MACHINE): {reasons.get(UNBACKED_POINTS_MACHINE, 0):>4}")
    print(f"  - 微额融资无背书 (LOW_FUNDING_UNVIABLE)   : {reasons.get(LOW_FUNDING_UNVIABLE, 0):>4}")
    print(f"  - 跑道资金已耗尽 (RUNWAY_DEPLETED)        : {reasons.get(RUNWAY_DEPLETED, 0):>4}")

    print(f"\nFARM 降级拦截:")
    print(f"  - 触发门禁降级项目数: {len(downgraded)} 个")

    if downgraded:
        print(f"\n被降级项目明细 (前 20 项):")
        print(f"  {'ID':<24} | {'原标签':<6} -> {'新标签':<6} | {'主要风险原因'}")
        print(f"  {'-'*24}-+-{'-'*6}----{'-'*6}-+-{'-'*40}")
        for p in downgraded[:20]:
            r_str = "; ".join(p["reasons_zh"]) if p["reasons_zh"] else ", ".join(p["reasons"])
            print(f"  {p['id']:<24} | {p['from_label']:<6} -> {p['to_label']:<6} | {r_str}")
        if len(downgraded) > 20:
            print(f"  ... 另有 {len(downgraded) - 20} 个项目被降级。")

    print(f"\n{'='*60}")
    if not args.apply:
        print("[提示] 当前为 DRY-RUN 预览模式，未修改数据库。")
        print("如需将上述降级与存活等级持久化至数据库，请运行:")
        print("  backend/venv/Scripts/python.exe backend/scripts/audit_viability.py --apply")
    else:
        print("[成功] 数据库已成功更新！全库已完成存活率硬门禁清洗与降级。")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
