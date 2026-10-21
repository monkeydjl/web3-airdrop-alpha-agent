"""hide_rootdata_non_projects.py：存量 RootData 人物 / 社媒条目的追溯隐藏（2026-10-08）。

- 只有**全部**来源行都是 RootData 非项目实体的项目才隐藏（有任何真实行佐证就不动）；
- 只隐藏不删除，对应 raw 行进隔离区；
- 用户手动恢复过的不动；幂等；launch_review 不会把它恢复回来。
"""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.agents.base import AgentContext, PipelineState, RawProject
from app.db import init_db
from app.repository import ProjectRepository
from app.services.launch_review import run_launch_review

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "hide_rootdata_non_projects.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("hide_rootdata_non_projects", SCRIPT)
    assert spec and spec.loader, f"{SCRIPT} 不存在 —— 被测对象没了。"
    mod = importlib.util.module_from_spec(spec)
    sys.modules["hide_rootdata_non_projects"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    init_db(c)
    try:
        yield c
    finally:
        c.close()


def _project(conn, pid: str, name: str) -> None:
    ProjectRepository(conn).save(
        PipelineState(
            project=RawProject(id=pid, name=name, sector="DeFi", stage="mainnet", source="rootdata"),
            context=AgentContext(run_id="r"),
            score=40,
            label="IGNORE",
            confidence=0.4,
            reason=[],
        )
    )


def _raw(conn, raw_id: str, pid: str, source_id: str, raw_data: dict) -> None:
    conn.execute(
        """
        INSERT INTO raw_projects (raw_id, source_id, dedup_key, raw_data, discovered_at, processed, project_id)
        VALUES (?, ?, ?, ?, ?, 1, ?)
        """,
        (raw_id, source_id, f"{raw_id}::DeFi", json.dumps(raw_data), datetime.now(UTC).isoformat(), pid),
    )
    conn.commit()


def _hidden(conn, pid: str) -> str | None:
    return conn.execute("SELECT hidden_reason FROM projects WHERE id = ?", (pid,)).fetchone()["hidden_reason"]


def _seed(conn) -> None:
    _project(conn, "person", "Deirdre Connolly")
    _raw(conn, "r-person", "person", "rootdata", {"name": "Deirdre Connolly", "type": 3})
    _project(conn, "list", "Web3 Testnets List")
    _raw(conn, "r-list", "list", "rootdata", {"name": "Web3 Testnets List", "type": "5"})
    # 同名但另有真实来源佐证：不动
    _project(conn, "spark", "Spark")
    _raw(conn, "r-spark-person", "spark", "rootdata", {"name": "spark", "type": 3})
    _raw(conn, "r-spark-llama", "spark", "defillama", {"name": "Spark"})
    # 正常 RootData 项目：不动
    _project(conn, "metis", "Metis")
    _raw(conn, "r-metis", "metis", "rootdata", {"name": "Metis", "type": 1})


def test_plan_only_targets_projects_backed_solely_by_non_project_rows(conn):
    mod = _load_script()
    _seed(conn)

    to_hide, to_quarantine = mod.plan(conn)

    assert sorted(pid for pid, _ in to_hide) == ["list", "person"]
    assert sorted(to_quarantine) == ["r-list", "r-person"]


def test_apply_hides_and_survives_launch_review(conn, monkeypatch):
    mod = _load_script()
    _seed(conn)
    monkeypatch.setattr(mod, "init_db", lambda: None)
    monkeypatch.setattr(mod, "get_connection", lambda: _NoClose(conn))
    monkeypatch.setattr(sys, "argv", ["hide_rootdata_non_projects.py"])

    assert mod.main() == 0

    assert _hidden(conn, "person") == mod.HIDDEN_REASON_NOT_A_PROJECT
    assert _hidden(conn, "list") == mod.HIDDEN_REASON_NOT_A_PROJECT
    assert _hidden(conn, "spark") is None
    assert _hidden(conn, "metis") is None
    q = {r["raw_id"] for r in conn.execute("SELECT raw_id FROM raw_projects WHERE quarantined = 1")}
    assert q == {"r-list", "r-person"}

    # launch_review 只撤销它自己的 already_launched_no_path，不碰 not_a_project
    run_launch_review(conn)
    assert _hidden(conn, "person") == mod.HIDDEN_REASON_NOT_A_PROJECT

    # 幂等：再跑一遍不产生新动作
    assert mod.plan(conn) == ([], [])


def test_user_unhidden_project_is_left_alone(conn):
    mod = _load_script()
    _seed(conn)
    conn.execute("UPDATE projects SET unhidden_by_user_at = ? WHERE id = 'person'", (datetime.now(UTC).isoformat(),))
    conn.commit()

    to_hide, _ = mod.plan(conn)

    assert [pid for pid, _ in to_hide] == ["list"]


class _NoClose:
    """main() 结束会 close 连接；测试还要接着断言，所以吞掉 close。"""

    def __init__(self, inner):
        self._inner = inner

    def close(self) -> None:
        return None

    def __getattr__(self, item):
        return getattr(self._inner, item)
