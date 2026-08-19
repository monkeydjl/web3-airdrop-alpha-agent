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
}


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
    """upgrade head 在空库建出全部 24 张表（16 baseline + 8 V2 新表）。"""
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
    """upgrade head 后 alembic_version 表记录最新版本 0002。"""
    db_path = tmp_path / "migrate.db"
    _run_alembic("upgrade", "head", db_path=db_path)
    conn = sqlite3.connect(str(db_path))
    ver = conn.execute("SELECT version_num FROM alembic_version").fetchone()
    conn.close()
    assert ver is not None and ver[0] == "0002"
