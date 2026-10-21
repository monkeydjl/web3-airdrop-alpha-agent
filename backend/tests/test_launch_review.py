"""已发币复查（launch_review，2026-10-08）：只隐藏确认已发币且无后续空投路径的项目。

约束：
- 只认确认已发币（token_launch_confirmed 三态）：RootData 没给发币证据的不藏。
- 隐藏不删除，默认列表不出现，include_hidden=True 仍可查到。
- 出现积分 / 任务入口 / 明确空投措辞后下一轮自动恢复。
- 有 active 参与计划的项目不藏；historical_backfill 不参与。
- 不改 updated_at（展示开关不是内容变化）。
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime

import pytest

from app.agents.base import AgentContext, PipelineState, RawProject
from app.db import init_db
from app.repository import ProjectRepository
from app.services.launch_review import HIDDEN_REASON_ALREADY_LAUNCHED, assess_project, run_launch_review
from app.services.token_registry import replace_registry


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    init_db(c)
    try:
        yield c
    finally:
        c.close()


def _save(conn, pid: str, *, source: str = "rootdata", signals: dict | None = None) -> None:
    ProjectRepository(conn).save(
        PipelineState(
            project=RawProject(id=pid, name=f"P-{pid}", sector="DeFi", stage="mainnet", source=source),
            context=AgentContext(run_id="r"),
            score=70,
            label="WATCH",
            confidence=0.6,
            reason=[],
        )
    )
    if signals:
        ProjectRepository(conn).update_meta_signals(pid, signals)


def _raw(conn, pid: str, source_id: str, raw_data: dict, *, raw_id: str | None = None, at: str | None = None) -> None:
    conn.execute(
        """
        INSERT INTO raw_projects (raw_id, source_id, dedup_key, raw_data, discovered_at, processed, project_id)
        VALUES (?, ?, ?, ?, ?, 1, ?)
        """,
        (
            raw_id or f"{pid}-{source_id}",
            source_id,
            f"{pid}::DeFi",
            json.dumps({"name": f"P-{pid}", **raw_data}),
            at or datetime.now(UTC).isoformat(),
            pid,
        ),
    )
    conn.commit()


def _hidden(conn, pid: str) -> str | None:
    return conn.execute("SELECT hidden_reason FROM projects WHERE id = ?", (pid,)).fetchone()["hidden_reason"]


class TestRunLaunchReview:
    def test_hides_confirmed_launch_without_path(self, conn):
        _save(conn, "listed")
        _raw(conn, "listed", "rootdata", {"no_token_yet": False, "token_symbol": "LST"})

        stats = run_launch_review(conn)

        assert stats["hidden"] == 1
        assert _hidden(conn, "listed") == HIDDEN_REASON_ALREADY_LAUNCHED
        assert conn.execute("SELECT hidden_at FROM projects WHERE id = 'listed'").fetchone()[0]

    def test_unknown_token_status_is_not_hidden(self, conn):
        """RootData 不给 ticker：状态未知，保留（2026-10-08 误删的那一类）。"""
        _save(conn, "unknown")
        _raw(conn, "unknown", "rootdata", {"no_token_yet": False})

        stats = run_launch_review(conn)

        assert stats["hidden"] == 0
        assert _hidden(conn, "unknown") is None

    def test_points_program_keeps_it_visible(self, conn):
        _save(conn, "season")
        _raw(conn, "season", "rootdata", {"no_token_yet": False, "token_symbol": "SZN", "has_points_program": True})

        assert run_launch_review(conn)["hidden"] == 0
        assert _hidden(conn, "season") is None

    def test_generic_staking_words_are_not_a_path(self, conn):
        """首轮实测：restaking / incentive 被宽松推断成积分计划，20 个已发币项目一个没藏。"""
        _save(conn, "restake", signals={"has_points_program": True})
        _raw(
            conn,
            "restake",
            "rootdata",
            {"no_token_yet": False, "token_symbol": "RST", "description": "Liquid restaking for stakers"},
        )

        assert run_launch_review(conn)["hidden"] == 1
        assert _hidden(conn, "restake") == HIDDEN_REASON_ALREADY_LAUNCHED

    def test_path_in_meta_signals_counts(self, conn):
        """富化器写进 meta 的任务入口证据同样算后续路径。"""
        _save(conn, "portal", signals={"has_task_portal": True})
        _raw(conn, "portal", "rootdata", {"no_token_yet": False, "token_symbol": "PTL"})

        assert run_launch_review(conn)["hidden"] == 0

    def test_unhides_when_path_appears(self, conn):
        _save(conn, "back")
        _raw(conn, "back", "rootdata", {"no_token_yet": False, "token_symbol": "BCK"}, at="2026-10-01T00:00:00+00:00")
        run_launch_review(conn)
        assert _hidden(conn, "back") == HIDDEN_REASON_ALREADY_LAUNCHED

        _raw(
            conn,
            "back",
            "rootdata",
            {"no_token_yet": False, "token_symbol": "BCK", "has_points_program": True},
            raw_id="back-rootdata-2",
            at="2026-10-09T00:00:00+00:00",
        )
        stats = run_launch_review(conn)

        assert stats["unhidden"] == 1
        assert _hidden(conn, "back") is None
        assert conn.execute("SELECT hidden_at FROM projects WHERE id = 'back'").fetchone()[0] is None

    def test_leaves_other_hidden_reasons_alone(self, conn):
        _save(conn, "manual")
        conn.execute("UPDATE projects SET hidden_reason = 'manual' WHERE id = 'manual'")
        conn.commit()

        assert run_launch_review(conn)["unhidden"] == 0
        assert _hidden(conn, "manual") == "manual"

    def test_active_plan_is_protected(self, conn):
        _save(conn, "mine")
        _raw(conn, "mine", "coingecko", {"no_token_yet": False})
        conn.execute(
            "INSERT INTO participation_plans (user_id, project_id, status) VALUES ('default', 'mine', 'active')"
        )
        conn.commit()

        stats = run_launch_review(conn)

        assert stats["protected_active_plan"] == 1
        assert _hidden(conn, "mine") is None

    def test_historical_backfill_is_skipped(self, conn):
        _save(conn, "hist", source="historical_backfill")
        _raw(conn, "hist", "coingecko", {"no_token_yet": False})

        assert run_launch_review(conn)["reviewed"] == 0

    def test_does_not_touch_updated_at(self, conn):
        _save(conn, "ts")
        _raw(conn, "ts", "coingecko", {"no_token_yet": False})
        before = conn.execute("SELECT updated_at FROM projects WHERE id = 'ts'").fetchone()[0]

        run_launch_review(conn)

        assert conn.execute("SELECT updated_at FROM projects WHERE id = 'ts'").fetchone()[0] == before

    def test_idempotent(self, conn):
        _save(conn, "twice")
        _raw(conn, "twice", "coingecko", {"no_token_yet": False})
        run_launch_review(conn)

        stats = run_launch_review(conn)

        assert stats["hidden"] == 0
        assert stats["kept_hidden"] == 1


class TestRegistryAndManualUnhide:
    """CoinGecko 币表补证 + 人工恢复显示（2026-10-08）。"""

    def _registry(self, conn, *names: str) -> None:
        coins = [{"id": f"coin-{i}", "symbol": f"s{i}", "name": n} for i, n in enumerate(names)]
        replace_registry(coins, conn=conn)

    def test_registry_hit_hides_unknown_status(self, conn):
        _save(conn, "arbitrum")
        _raw(conn, "arbitrum", "rootdata", {"no_token_yet": False})
        self._registry(conn, "P-arbitrum")

        stats = run_launch_review(conn)

        assert stats["registry_confirmed"] == 1
        assert _hidden(conn, "arbitrum") == HIDDEN_REASON_ALREADY_LAUNCHED

    def test_registry_hit_without_raw_rows(self, conn):
        _save(conn, "oldchain", signals={"no_token_yet": False})
        self._registry(conn, "P-oldchain")

        assert run_launch_review(conn)["hidden"] == 1

    def test_registry_never_overrides_explicit_pre_tge(self, conn):
        _save(conn, "pretoken", signals={"no_token_yet": True})
        _raw(conn, "pretoken", "rootdata", {"no_token_yet": True})
        self._registry(conn, "P-pretoken")

        stats = run_launch_review(conn)

        assert stats["registry_confirmed"] == 0
        assert _hidden(conn, "pretoken") is None

    def test_registry_hit_with_path_stays_visible(self, conn):
        _save(conn, "pointsfi", signals={"explicit_points_program": True})
        _raw(conn, "pointsfi", "rootdata", {"no_token_yet": False})
        self._registry(conn, "P-pointsfi")

        assert run_launch_review(conn)["hidden"] == 0

    def test_manual_unhide_is_respected(self, conn):
        _save(conn, "keep")
        _raw(conn, "keep", "coingecko", {"no_token_yet": False})
        run_launch_review(conn)
        assert _hidden(conn, "keep") == HIDDEN_REASON_ALREADY_LAUNCHED

        assert ProjectRepository(conn).unhide("keep") is True
        assert _hidden(conn, "keep") is None
        stats = run_launch_review(conn)

        assert stats["protected_user_unhidden"] == 1
        assert stats["hidden"] == 0
        assert _hidden(conn, "keep") is None

    def test_unhide_missing_project(self, conn):
        assert ProjectRepository(conn).unhide("nope") is False

    def test_unhide_does_not_touch_updated_at(self, conn):
        _save(conn, "ts2")
        before = conn.execute("SELECT updated_at FROM projects WHERE id = 'ts2'").fetchone()[0]

        ProjectRepository(conn).unhide("ts2")

        row = conn.execute("SELECT updated_at, unhidden_by_user_at FROM projects WHERE id = 'ts2'").fetchone()
        assert row["updated_at"] == before
        assert row["unhidden_by_user_at"] is not None


class TestAssessProject:
    def test_registry_hit_fills_unknown(self):
        assert assess_project({"no_token_yet": False}, [], registry_hit=True) == (True, False)

    def test_registry_hit_loses_to_raw_pre_tge(self):
        raw = [{"name": "X", "source": "defillama", "no_token_yet": True, "token_launch_confirmed": False}]
        assert assess_project({}, raw, registry_hit=True) == (False, False)

    def test_meta_pre_tge_overrides_raw_confirmation(self):
        """库内信号明确说未发币（人工修正 / 更新的评分）时证据冲突，按未知不藏。"""
        raw = [{"name": "X", "source": "coingecko", "no_token_yet": False, "token_launch_confirmed": True}]
        assert assess_project({"no_token_yet": True}, raw) == (False, False)

    def test_without_raw_rows_needs_explicit_confirmation(self):
        assert assess_project({"no_token_yet": False}, []) == (False, False)
        assert assess_project({"no_token_yet": False, "token_launch_confirmed": True}, []) == (True, False)


class TestListProjectsHidden:
    def test_default_list_excludes_hidden(self, conn):
        _save(conn, "seen")
        _save(conn, "gone")
        conn.execute("UPDATE projects SET hidden_reason = ? WHERE id = 'gone'", (HIDDEN_REASON_ALREADY_LAUNCHED,))
        conn.commit()
        repo = ProjectRepository(conn)

        rows, total = repo.list_projects()
        assert [r["id"] for r in rows] == ["seen"]
        assert total == 1

        rows, total = repo.list_projects(include_hidden=True)
        assert {r["id"] for r in rows} == {"seen", "gone"}
        assert total == 2
