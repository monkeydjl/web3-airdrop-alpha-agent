#!/usr/bin/env python3
# ──────────────────────────────────────────────
# Listed-Brand Subproduct Backfill — Web3 Airdrop Alpha Agent System
# ──────────────────────────────────────────────
# 用法: python scripts/backfill_listed_subproducts.py [--apply]
# 用途: 追溯清理存量「已发币品牌子产品」（修复方案 B，2026-09-06）
# ──────────────────────────────────────────────

"""
存量追溯：已发币过滤（2026-09-05）只管**新**采集，过滤上线前入库的
「父品牌已发币、自己无空投信号」的行（实测：Plume Vaults，9/3 采集，
WATCH 65）会永久躺在库里。本脚本对 projects 表做一次全量追溯：

- 命中已发币品牌（KNOWN_LISTED_BRANDS 首词匹配）且无自有空投信号
  （testnet / points / task portal / explicit mention）的行：
  降级 IGNORE、reason 前插追溯标记、meta.signals.no_token_yet 修正为
  False（让未来 rescore 的 eligibility veto 与本次决定一致）。
- 有自有空投信号的行不动 —— 父项目发币不影响子产品自己的空投机会。
- source='seed' 的演示行不动；已是 IGNORE 的行不动（幂等，可重复运行）。

用法:
    cd backend
    python ../scripts/backfill_listed_subproducts.py           # dry-run，只统计
    python ../scripts/backfill_listed_subproducts.py --apply   # 实际写库

⚠️ 必须从 backend/ 目录运行：DB_PATH 是相对路径、按 CWD 解析，
与后端同 CWD 才会命中同一个库文件（实测从仓库根目录跑会连到另一份库）。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

# 将 backend 目录加入 sys.path，使 `import app` 在任意 CWD 下可用
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.agents.base import AgentContext, PipelineState, RawProject
from app.agents.eligibility import VETO_ALREADY_LAUNCHED
from app.collectors.noise import KNOWN_LISTED_BRANDS, is_listed_brand_subproduct
from app.repository import ProjectRepository
from app.services.project_signals import apply_signals_to_kwargs

BACKFILL_TAG = "eligibility backfill"
_OWN_SIGNAL_KEYS = ("has_testnet", "has_points_program", "has_task_portal", "explicit_airdrop_mention")


def _own_signal(row: dict) -> bool:
    """自有空投信号判定：行列与 meta.signals 取**或**。

    实测行结构：has_testnet / has_points_program 等信号只落在 meta.signals
    （行上的独立列为 None），只读列会漏判 —— 把带 points 的子产品误降级。
    """
    kwargs = apply_signals_to_kwargs(row.get("meta"))
    return any(bool(row.get(k)) or bool(kwargs.get(k)) for k in _OWN_SIGNAL_KEYS)


def _reason_list(raw: object) -> list[str]:
    """行里的 reason 是 JSON 数组字符串（真实行）或裸字符串（旧行），统一成列表。"""
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return [raw.strip()]
        if isinstance(parsed, list):
            return [str(x) for x in parsed]
        return [str(parsed)]
    if isinstance(raw, list):
        return [str(x) for x in raw]
    return []


def _relabel(repo: ProjectRepository, row: dict) -> None:
    """降级 IGNORE + reason 留痕 + 修正存量 no_token_yet 信号。

    走 repo.save()（而非裸 UPDATE）：双方言、project_history、审计留痕
    都由既有路径承接。信号修正是刻意的 —— 只改标签不改信号的话，未来
    一次 rescore 会把 no_token_yet=True 读回去，veto 与本次决定打架。
    """
    date = datetime.now(UTC).date().isoformat()
    kwargs = apply_signals_to_kwargs(row.get("meta"))
    kwargs["no_token_yet"] = False
    project = RawProject(
        id=row["id"],
        name=row.get("name") or "",
        url=row.get("url") or "",
        sector=row.get("sector") or "",
        stage=row.get("stage") or "",
        source=row.get("source") or "",
        created_at=None,
        **kwargs,
    )
    reasons = [
        f"{BACKFILL_TAG} ({date}): 父品牌已发币且无自有空投信号 —— "
        "token already launched with no verified follow-on airdrop path"
    ]
    reasons += _reason_list(row.get("reason"))
    state = PipelineState(
        project=project,
        context=AgentContext(run_id=f"backfill-{date}"),
        score=int(row.get("score") or 0),
        label="IGNORE",
        confidence=float(row["confidence"]) if row.get("confidence") is not None else 0.5,
        reason=reasons,
    )
    state.veto = VETO_ALREADY_LAUNCHED
    repo.save(state)


def run(*, repo: ProjectRepository | None = None, apply: bool = False) -> dict:
    """全量追溯。返回统计；`relabelled` 是（将要/已经）降级的行数。"""
    repo = repo or ProjectRepository()
    stats: dict = {
        "scanned": 0,
        "relabelled": 0,
        "skipped_own_signals": 0,
        "skipped_already_ignored": 0,
        "skipped_seed": 0,
        "apply": apply,
        "names": [],
    }

    page = 1
    while True:
        rows, _total = repo.list_projects(page=page, page_size=100)
        if not rows:
            break
        for row in rows:
            d = dict(row)
            stats["scanned"] += 1
            if (d.get("source") or "") == "seed":
                stats["skipped_seed"] += 1
                continue
            if str(d.get("label") or "").upper() == "IGNORE":
                stats["skipped_already_ignored"] += 1
                continue
            if _own_signal(d):
                stats["skipped_own_signals"] += 1
                continue
            if not is_listed_brand_subproduct(name=str(d.get("name") or "")):
                continue
            stats["relabelled"] += 1
            stats["names"].append(d.get("name"))
            if apply:
                _relabel(repo, d)
        if len(rows) < 100:
            break
        page += 1

    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="追溯清理存量已发币品牌子产品")
    parser.add_argument("--apply", action="store_true", help="实际写库；缺省为 dry-run")
    args = parser.parse_args()

    stats = run(apply=args.apply)
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    if not args.apply:
        print("\n[dry-run] 未写库。确认上述行数后加 --apply 执行。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
