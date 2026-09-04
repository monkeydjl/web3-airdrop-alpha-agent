"""Alembic baseline 迁移冒烟测试。

验收标准（docs/V2_TASKS.md A1）：
1. alembic upgrade head 在空库建出与 init_db() 一致的 schema
2. alembic downgrade base 可回滚到空库

用子进程运行 alembic / init_db，确保 DB_PATH 指向临时库且不影响主进程的
settings 单例。CI 通过现有 pytest 流水线自动覆盖本测试。
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent

_EXPECTED_TABLES = {
    "projects",
    "logs",
    "data_sources",
    "raw_projects",
    "project_signals",
    "collection_logs",
    "raw_projects_archive",
    "project_signals_archive",
    "feedback",
    "events",
    "interactions",
    "opportunity_evidence",
    "opportunity_assessments",
    "opportunity_economic_snapshots",
    "watchlist",
    "weight_changelog",
    # V2 新表（§5.4，迁移 0002）
    "quarantine",
    "project_history",
    "audit_logs",
    "llm_eval_changelog",
    "metrics",
    "narratives",
    "dedup_keys",
    "prompt_versions",
    "notification_reads",
    # 归档运行历史（迁移 0003）
    "archive_runs",
    # LLM 日花费账本（迁移 0004）
    "llm_spend_daily",
    # 决策推派出站日志（迁移 0005，ACTION_LOOP_DESIGN §2）
    "notify_log",
    # 参与流水（迁移 0006，ACTION_LOOP_DESIGN §3）
    "participation_plans",
    "participation_tasks",
    # 收益台账（迁移 0007，ACTION_LOOP_DESIGN §4）
    "roi_entries",
    "roi_outcomes",
    # 领取监控的自有地址（迁移 0009，ACTION_LOOP_DESIGN §5）
    "watched_wallets",
}

# 每个迁移引入的表 —— 可回滚性测试按「回滚到 N ⇒ 移除 N 之后全部表」推导，
# 新迁移只需在这里登记一行，不必再改各测试的差集。
_REVISION_TABLES: dict[str, set[str]] = {
    "0004": {"llm_spend_daily"},
    "0005": {"notify_log"},
    "0006": {"participation_plans", "participation_tasks"},
    "0007": {"roi_entries", "roi_outcomes"},
    # 0008 只给 projects 加了一列（veto），不引入新表
    "0008": set(),
    "0009": {"watched_wallets"},
}
_REVISION_ORDER = ["0001", "0002", "0003", "0004", "0005", "0006", "0007", "0008", "0009"]


def _tables_removed_after(revision: str) -> set[str]:
    """回滚到 revision 时应当消失的表（revision 之后的所有迁移引入的表）。"""
    idx = _REVISION_ORDER.index(revision)
    out: set[str] = set()
    for rev in _REVISION_ORDER[idx + 1 :]:
        out |= _REVISION_TABLES.get(rev, set())
    return out


def _run(cmd: list[str], *, db_path: Path) -> subprocess.CompletedProcess:
    """在子进程中运行命令，DB_PATH 指向临时库。"""
    env = {**os.environ, "DB_PATH": str(db_path)}
    result = subprocess.run(
        cmd,
        cwd=str(BACKEND_DIR),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, f"command failed: {' '.join(cmd)}\nstdout: {result.stdout}\nstderr: {result.stderr}"
    return result


def _run_alembic(*args: str, db_path: Path) -> subprocess.CompletedProcess:
    return _run([sys.executable, "-m", "alembic", *args], db_path=db_path)


def _get_user_tables(db_path: Path) -> set[str]:
    conn = sqlite3.connect(str(db_path))
    tables = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' AND name != 'alembic_version'"
        )
    }
    conn.close()
    return tables


def _dump_schema(db_path: Path) -> tuple[dict, dict]:
    """返回 (tables: {name: [(col, type, notnull, default)]}, indexes: {name: sql})。"""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    tables: dict[str, list] = {}
    for (tname,) in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%' AND name != 'alembic_version' ORDER BY name"
    ).fetchall():
        tables[tname] = [(r[1], r[2], r[3], r[4]) for r in conn.execute(f"PRAGMA table_info({tname})")]
    indexes: dict[str, str] = {}
    for row in conn.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall():
        indexes[row[0]] = (row[1] or "").strip()
    conn.close()
    return tables, indexes


def test_alembic_upgrade_creates_all_tables(tmp_path: Path) -> None:
    """upgrade head 在空库建出全部表（16 baseline + 8 V2 新表 + archive_runs）。"""
    db_path = tmp_path / "migrate.db"
    _run_alembic("upgrade", "head", db_path=db_path)
    tables = _get_user_tables(db_path)
    assert tables == _EXPECTED_TABLES, f"missing: {_EXPECTED_TABLES - tables}, extra: {tables - _EXPECTED_TABLES}"


def test_alembic_downgrade_base_drops_all_tables(tmp_path: Path) -> None:
    """upgrade head 后 downgrade base 删除全部用户表。"""
    db_path = tmp_path / "migrate.db"
    _run_alembic("upgrade", "head", db_path=db_path)
    assert _get_user_tables(db_path) == _EXPECTED_TABLES
    _run_alembic("downgrade", "base", db_path=db_path)
    assert _get_user_tables(db_path) == set()


def test_alembic_schema_matches_init_db(tmp_path: Path) -> None:
    """alembic 建出的 schema 与 init_db() 直建完全一致（表/列/索引）。"""
    alembic_db = tmp_path / "alembic.db"
    init_db_path = tmp_path / "init.db"

    # 1. alembic 建库
    _run_alembic("upgrade", "head", db_path=alembic_db)

    # 2. init_db() 直建（子进程，确保 settings.db_path 指向临时库）
    _run(
        [sys.executable, "-c", "from app.db import init_db; init_db()"],
        db_path=init_db_path,
    )

    # 3. 比对表/列
    a_tables, a_indexes = _dump_schema(alembic_db)
    i_tables, i_indexes = _dump_schema(init_db_path)

    assert set(a_tables) == set(i_tables) == _EXPECTED_TABLES
    for tname in _EXPECTED_TABLES:
        assert a_tables[tname] == i_tables[tname], f"column mismatch on {tname}"

    # 4. 比对索引（名称 + SQL 定义，含部分索引 WHERE 子句）
    assert set(a_indexes) == set(i_indexes), "index name set differs"
    for name in a_indexes:
        assert a_indexes[name] == i_indexes[name], f"index definition differs: {name}"


def test_alembic_version_recorded(tmp_path: Path) -> None:
    """upgrade head 后 alembic_version 表记录最新版本。

    期望值从 `_REVISION_ORDER[-1]` 推导，**不再硬编码数字**（2026-09-02 改）：
    这里钉住的语义本来就是「head 就是最后一个 revision」，写死数字的话每加
    一个迁移都要来改两处（这张表 + 这行断言），而漏改的表现是本条测试红 ——
    信息量为零的红灯，只会训练人把它当噪音顺手改掉。

    现在漏登记 `_REVISION_TABLES` / `_REVISION_ORDER` 才会红，而那正是
    真正需要人来确认的地方（新表要不要参与回滚推导）。
    """
    db_path = tmp_path / "migrate.db"
    _run_alembic("upgrade", "head", db_path=db_path)
    conn = sqlite3.connect(str(db_path))
    ver = conn.execute("SELECT version_num FROM alembic_version").fetchone()
    conn.close()
    expected_head = _REVISION_ORDER[-1]
    assert ver is not None and ver[0] == expected_head, (
        f"alembic head 是 {ver[0] if ver else None}，但 _REVISION_ORDER 末位是 "
        f"{expected_head} —— 新增迁移后请在 _REVISION_TABLES 与 _REVISION_ORDER 各登记一处"
    )


def test_alembic_0003_is_reversible(tmp_path: Path) -> None:
    """0003 可以单独回滚到 0002（归档表与索引一起消失，其余表不动）。

    归档是 2026-08-22 新加的一档，必须能在不动前两版 schema 的前提下回退 ——
    否则一旦归档出问题，运维只能整库回滚。

    注意：0004 在 0003 之后，所以要先回到 0003 再回到 0002，
    而 `llm_spend_daily` 会跟着 0004 一起消失。
    """
    db_path = tmp_path / "migrate.db"
    _run_alembic("upgrade", "head", db_path=db_path)
    assert "archive_runs" in _get_user_tables(db_path)

    _run_alembic("downgrade", "0002", db_path=db_path)
    tables = _get_user_tables(db_path)
    assert "archive_runs" not in tables
    assert tables == _EXPECTED_TABLES - {"archive_runs"} - _tables_removed_after("0003"), "回滚 0003 不应影响其它表"

    _, indexes = _dump_schema(db_path)
    assert "idx_archive_runs_started" not in indexes
    assert "idx_archive_archived_at" not in indexes
    assert "idx_signals_archive_archived_at" not in indexes

    # 再升回来必须成功（回滚不是单程票）
    _run_alembic("upgrade", "head", db_path=db_path)
    assert _get_user_tables(db_path) == _EXPECTED_TABLES


def test_alembic_0004_is_reversible(tmp_path: Path) -> None:
    """0004 可以单独回滚到 0003（只有 llm_spend_daily 消失）。

    预算账本是新加的一档。它比归档更需要能单独回退：**它在 LLM 调用的
    热路径上** —— 一旦账本本身出问题（比如某个部署环境上 UPSERT 语法不兼容），
    运维需要能在不碰其它 26 张表的前提下把它摘掉，让 LLM 退回到不限额但可用。
    """
    db_path = tmp_path / "migrate.db"
    _run_alembic("upgrade", "head", db_path=db_path)
    assert "llm_spend_daily" in _get_user_tables(db_path)

    _run_alembic("downgrade", "0003", db_path=db_path)
    tables = _get_user_tables(db_path)
    assert tables == _EXPECTED_TABLES - _tables_removed_after("0003"), "回滚 0004（到 0003）只应移除 llm_spend_daily"

    _run_alembic("upgrade", "head", db_path=db_path)
    assert _get_user_tables(db_path) == _EXPECTED_TABLES
