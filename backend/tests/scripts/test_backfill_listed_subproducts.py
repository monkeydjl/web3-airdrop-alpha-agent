"""backfill_listed_subproducts.py 的门禁：存量「已发币品牌子产品」的追溯清理。

背景（2026-09-06）：已发币过滤 9/5 上线，只管**新**采集；9/3 入库的
"Plume Vaults"（WATCH 65）躺在库里没有任何机制会再碰它。品牌首词兜底
（A，`is_listed_brand_subproduct`）修好后，存量行需要一次性追溯：

- 命中已发币品牌、且无自有空投信号（testnet/points/task/explicit）的行
  → 降级 IGNORE、reason 前插追溯标记、meta.signals.no_token_yet 修正为
  False（让未来 rescore 的 eligibility veto 与本次决定一致）；
- 有自有信号的行（父项目发币不影响子产品自己的空投机会）一律不动；
- source='seed' 的演示行不动；已经是 IGNORE 的行不动（幂等）。
"""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

from app.agents.base import AgentContext, PipelineState, RawProject
from app.db import init_db
from app.repository import ProjectRepository

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "backfill_listed_subproducts.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("backfill_listed_subproducts", SCRIPT)
    assert spec and spec.loader, f"{SCRIPT} 不存在 —— 被测对象没了。"
    mod = importlib.util.module_from_spec(spec)
    sys.modules["backfill_listed_subproducts"] = mod
    spec.loader.exec_module(mod)
    return mod


def _repo_with_rows() -> ProjectRepository:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    repo = ProjectRepository(conn=conn)

    def _save(pid: str, name: str, *, label: str, score: int, reason, no_token_yet=True, has_points=False):
        repo.save(
            PipelineState(
                project=RawProject(
                    id=pid,
                    name=name,
                    url=f"https://{pid}.example.com",
                    sector="RWA",
                    stage="growth",
                    source="defillama",
                    no_token_yet=no_token_yet,
                    has_points_program=has_points,
                    created_at=None,
                ),
                context=AgentContext(run_id="r1"),
                score=score,
                label=label,
                confidence=0.6,
                reason=reason,
            )
        )

    # 1) 目标行：品牌命中 + 无自有信号 + JSON 列表 reason → 应降级 IGNORE
    _save("plume-vaults", "Plume Vaults", label="WATCH", score=65, reason=["active development / roadmap traction"])
    # 2) 品牌命中但有自有空投信号（points）→ 不动
    _save("plume-points", "Plume Points", label="FARM", score=72, reason=[], has_points=True)
    # 3) 未知品牌 → 不动
    _save("freshchain-vaults", "Freshchain Vaults", label="WATCH", score=58, reason=[])
    # 4) 已是 IGNORE → 幂等跳过
    _save("plume-bridge", "Plume Bridge", label="IGNORE", score=40, reason=[])
    return repo


def _row(repo: ProjectRepository, pid: str) -> dict:
    return dict(repo.get_by_id(pid))


def _reasons(row: dict) -> list:
    """repo 对空 reason 存 None（`json.dumps(state.reason) if state.reason else None`）。"""
    return json.loads(row["reason"] or "[]")


class TestBackfill:
    def test_relabels_listed_subproduct_and_fixes_signal(self) -> None:
        mod = _load_script()
        repo = _repo_with_rows()
        stats = mod.run(repo=repo, apply=True)

        assert stats["relabelled"] == 1
        row = _row(repo, "plume-vaults")
        assert row["label"] == "IGNORE"
        reasons = _reasons(row)
        assert any("backfill" in r for r in reasons), "追溯降级必须在 reason 里留痕"
        assert "active development" in reasons[1] if len(reasons) > 1 else True
        # 信号修正：未来 rescore 的 eligibility veto 必须与本次决定一致
        meta = json.loads(row["meta"])
        assert meta["signals"]["no_token_yet"] is False

    def test_rows_with_own_signals_untouched(self) -> None:
        mod = _load_script()
        repo = _repo_with_rows()
        mod.run(repo=repo, apply=True)
        row = _row(repo, "plume-points")
        assert row["label"] == "FARM", "有自有 points 信号的子产品不能被追溯降级"

    def test_unknown_brand_untouched(self) -> None:
        mod = _load_script()
        repo = _repo_with_rows()
        mod.run(repo=repo, apply=True)
        assert _row(repo, "freshchain-vaults")["label"] == "WATCH"

    def test_already_ignored_is_idempotent(self) -> None:
        mod = _load_script()
        repo = _repo_with_rows()
        first = mod.run(repo=repo, apply=True)
        second = mod.run(repo=repo, apply=True)
        assert first["relabelled"] == 1
        assert second["relabelled"] == 0, "重复运行不得再次改动"
        row = _row(repo, "plume-bridge")
        reasons = _reasons(row)
        assert not any("backfill" in r for r in reasons), "原 IGNORE 行不应被追加标记"

    def test_dry_run_writes_nothing(self) -> None:
        mod = _load_script()
        repo = _repo_with_rows()
        stats = mod.run(repo=repo, apply=False)
        assert stats["relabelled"] == 1, "dry-run 仍要报告会改多少行"
        row = _row(repo, "plume-vaults")
        assert row["label"] == "WATCH", "dry-run 不得写库"

    def test_seed_rows_never_touched(self) -> None:
        mod = _load_script()
        repo = _repo_with_rows()
        repo.save(
            PipelineState(
                project=RawProject(
                    id="seed-demo",
                    name="Plume Demo",
                    url="https://seed.example.com",
                    sector="RWA",
                    stage="testnet",
                    source="seed",
                    no_token_yet=True,
                    created_at=None,
                ),
                context=AgentContext(run_id="r1"),
                score=70,
                label="WATCH",
                confidence=0.5,
                reason=[],
            )
        )
        mod.run(repo=repo, apply=True)
        assert _row(repo, "seed-demo")["label"] == "WATCH", "seed 演示行不参与追溯降级"
