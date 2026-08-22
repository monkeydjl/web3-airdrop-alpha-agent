"""V2 Repository Layer — 新表数据访问层。

提供 §5.4 定义的 V2 新表的 CRUD 操作：
- AuditLogRepository: audit_logs (审计日志)
- MetricsRepository: metrics (数据质量指标)
- LLMEvalRepository: llm_eval_changelog (LLM 评估记录)
- QuarantineRepository: quarantine (脏数据隔离)
- ProjectHistoryRepository: project_history (项目历史快照)
- NarrativesRepository: narratives (赛道元数据维表)
- DedupKeysRepository: dedup_keys (去重键映射)
- PromptVersionsRepository: prompt_versions (Prompt 版本管理)

所有方法接受 conn 参数（由调用方管理连接生命周期）。

Reference:
- DATABASE_DDL.md §2.4–§2.12
- ENGINEERING_ROADMAP.md §5.4
- V2_TASKS.md E1
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import structlog

from app.db import dict_from_row

logger = structlog.get_logger(__name__)


# ── AuditLogRepository ──────────────────────────


class AuditLogRepository:
    """audit_logs 表数据访问（§5.4.7）。"""

    def __init__(self, conn) -> None:
        self.conn = conn

    def insert(
        self,
        *,
        action: str,
        user: str,
        detail: str | None = None,
        ip: str | None = None,
    ) -> int:
        cursor = self.conn.execute(
            """
            INSERT INTO audit_logs (action, "user", detail, ip)
            VALUES (?, ?, ?, ?)
            """,
            (action, user, detail, ip),
        )
        self.conn.commit()
        return cursor.lastrowid or 0

    def query(
        self,
        *,
        action: str | None = None,
        user: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        conditions = []
        params: list[Any] = []
        if action:
            conditions.append("action = ?")
            params.append(action)
        if user:
            conditions.append('"user" = ?')
            params.append(user)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(limit)

        # where 只由上面固定的字面量片段拼接（"action = ?" 等），所有取值一律走
        # 绑定参数 params；无用户输入进入 SQL 文本。
        rows = self.conn.execute(
            f"""
            SELECT * FROM audit_logs {where}
            ORDER BY created_at DESC LIMIT ?
            """,  # noqa: S608
            params,
        ).fetchall()

        return [dict_from_row(r) for r in rows]


# ── MetricsRepository ───────────────────────────


class MetricsRepository:
    """metrics 表数据访问（§5.4.7）。"""

    def __init__(self, conn) -> None:
        self.conn = conn

    def insert(
        self,
        *,
        run_id: str,
        metric_name: str,
        metric_value: float,
        detail: str | None = None,
    ) -> int:
        cursor = self.conn.execute(
            """
            INSERT INTO metrics (run_id, metric_name, metric_value, detail)
            VALUES (?, ?, ?, ?)
            """,
            (run_id, metric_name, metric_value, detail),
        )
        self.conn.commit()
        return cursor.lastrowid or 0

    def query_by_run(self, run_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM metrics WHERE run_id = ? ORDER BY timestamp DESC",
            (run_id,),
        ).fetchall()
        return [dict_from_row(r) for r in rows]

    def query_by_name(self, metric_name: str, *, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM metrics WHERE metric_name = ? ORDER BY timestamp DESC LIMIT ?",
            (metric_name, limit),
        ).fetchall()
        return [dict_from_row(r) for r in rows]


# ── LLMEvalRepository ───────────────────────────


class LLMEvalRepository:
    """llm_eval_changelog 表数据访问（§5.4.7）。"""

    def __init__(self, conn) -> None:
        self.conn = conn

    def insert(
        self,
        *,
        eval_date: str,
        sample_count: int,
        rule_accuracy: float,
        llm_accuracy: float,
        llm_cost_usd: float,
        decision: str,
        detail: str | None = None,
    ) -> int:
        cursor = self.conn.execute(
            """
            INSERT INTO llm_eval_changelog
                (eval_date, sample_count, rule_accuracy, llm_accuracy,
                 llm_cost_usd, decision, detail)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (eval_date, sample_count, rule_accuracy, llm_accuracy, llm_cost_usd, decision, detail),
        )
        self.conn.commit()
        return cursor.lastrowid or 0

    def get_latest(self) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM llm_eval_changelog ORDER BY eval_date DESC LIMIT 1").fetchone()
        return dict_from_row(row) if row else None

    def list_all(self, *, limit: int = 20) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM llm_eval_changelog ORDER BY eval_date DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict_from_row(r) for r in rows]


# ── QuarantineRepository ────────────────────────


class QuarantineRepository:
    """quarantine 表数据访问（§5.4.3）。"""

    def __init__(self, conn) -> None:
        self.conn = conn

    def insert(
        self,
        *,
        project_id: str | None = None,
        raw_data: str,
        failure_reason: str,
        severity: str = "warning",
    ) -> int:
        cursor = self.conn.execute(
            """
            INSERT INTO quarantine
                (project_id, raw_data, failure_reason, severity, status)
            VALUES (?, ?, ?, ?, 'pending')
            """,
            (project_id, raw_data, failure_reason, severity),
        )
        self.conn.commit()
        return cursor.lastrowid or 0

    def resolve(self, quarantine_id: int, *, status: str = "resolved") -> bool:
        cursor = self.conn.execute(
            """
            UPDATE quarantine
            SET status = ?, resolved_at = ?
            WHERE id = ? AND status = 'pending'
            """,
            (status, datetime.now(UTC).isoformat(), quarantine_id),
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def query_pending(self, *, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM quarantine WHERE status = 'pending' ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict_from_row(r) for r in rows]

    def query_by_reason(self, reason: str, *, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM quarantine WHERE failure_reason = ? ORDER BY created_at DESC LIMIT ?",
            (reason, limit),
        ).fetchall()
        return [dict_from_row(r) for r in rows]


# ── ProjectHistoryRepository ────────────────────


class ProjectHistoryRepository:
    """project_history 表数据访问（§5.4.4）。"""

    def __init__(self, conn) -> None:
        self.conn = conn

    def insert(
        self,
        *,
        project_id: str,
        run_id: str,
        score: int | None = None,
        label: str | None = None,
        stage: str | None = None,
        weight_version: str | None = None,
        snapshot: str,
    ) -> int:
        cursor = self.conn.execute(
            """
            INSERT INTO project_history
                (project_id, run_id, score, label, stage, weight_version, snapshot)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (project_id, run_id, score, label, stage, weight_version, snapshot),
        )
        self.conn.commit()
        return cursor.lastrowid or 0

    def query_by_project(self, project_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM project_history WHERE project_id = ? ORDER BY created_at DESC, id DESC LIMIT ?",
            (project_id, limit),
        ).fetchall()
        return [dict_from_row(r) for r in rows]

    def query_by_run(self, run_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM project_history WHERE run_id = ? ORDER BY created_at DESC, id DESC",
            (run_id,),
        ).fetchall()
        return [dict_from_row(r) for r in rows]


# ── NarrativesRepository ────────────────────────


class NarrativesRepository:
    """narratives 维表数据访问（§5.4.6）。"""

    def __init__(self, conn) -> None:
        self.conn = conn

    def upsert(
        self,
        *,
        sector: str,
        aliases: list[str] | None = None,
        base_heat: float | None = None,
        stage: str | None = None,
        momentum: float | None = None,
    ) -> None:
        aliases_json = json.dumps(aliases) if aliases else None
        self.conn.execute(
            """
            INSERT INTO narratives (sector, aliases, base_heat, stage, momentum, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(sector) DO UPDATE SET
                aliases = COALESCE(excluded.aliases, narratives.aliases),
                base_heat = COALESCE(excluded.base_heat, narratives.base_heat),
                stage = COALESCE(excluded.stage, narratives.stage),
                momentum = COALESCE(excluded.momentum, narratives.momentum),
                updated_at = excluded.updated_at
            """,
            (sector, aliases_json, base_heat, stage, momentum, datetime.now(UTC).isoformat()),
        )
        self.conn.commit()

    def get(self, sector: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM narratives WHERE sector = ?",
            (sector,),
        ).fetchone()
        return dict_from_row(row) if row else None

    def list_all(self) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT * FROM narratives ORDER BY sector").fetchall()
        return [dict_from_row(r) for r in rows]

    def delete(self, sector: str) -> bool:
        cursor = self.conn.execute(
            "DELETE FROM narratives WHERE sector = ?",
            (sector,),
        )
        self.conn.commit()
        return cursor.rowcount > 0


# ── DedupKeysRepository ─────────────────────────


class DedupKeysRepository:
    """dedup_keys 表数据访问（§5.4.8）。"""

    def __init__(self, conn) -> None:
        self.conn = conn

    def upsert(
        self,
        *,
        dedup_key: str,
        project_id: str,
        name_raw: str,
        sector_raw: str,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO dedup_keys (dedup_key, project_id, name_raw, sector_raw)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(dedup_key) DO UPDATE SET
                project_id = excluded.project_id,
                name_raw = excluded.name_raw,
                sector_raw = excluded.sector_raw
            """,
            (dedup_key, project_id, name_raw, sector_raw),
        )
        self.conn.commit()

    def lookup(self, dedup_key: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM dedup_keys WHERE dedup_key = ?",
            (dedup_key,),
        ).fetchone()
        return dict_from_row(row) if row else None

    def query_by_project(self, project_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM dedup_keys WHERE project_id = ?",
            (project_id,),
        ).fetchall()
        return [dict_from_row(r) for r in rows]


# ── PromptVersionsRepository ────────────────────


class PromptVersionsRepository:
    """prompt_versions 表数据访问（§5.4.9）。"""

    def __init__(self, conn) -> None:
        self.conn = conn

    def insert(
        self,
        *,
        agent_name: str,
        prompt_key: str,
        version: str,
        content: str,
        created_by: str,
        is_default: bool = False,
    ) -> int:
        cursor = self.conn.execute(
            """
            INSERT INTO prompt_versions
                (agent_name, prompt_key, version, content, is_default, created_by)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (agent_name, prompt_key, version, content, 1 if is_default else 0, created_by),
        )
        self.conn.commit()

        if is_default:
            self._clear_other_defaults(agent_name, prompt_key, exclude_id=cursor.lastrowid)

        return cursor.lastrowid or 0

    def _clear_other_defaults(self, agent_name: str, prompt_key: str, *, exclude_id: int) -> None:
        self.conn.execute(
            """
            UPDATE prompt_versions SET is_default = 0
            WHERE agent_name = ? AND prompt_key = ? AND id != ?
            """,
            (agent_name, prompt_key, exclude_id),
        )
        self.conn.commit()

    def get_default(self, agent_name: str, prompt_key: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT * FROM prompt_versions
            WHERE agent_name = ? AND prompt_key = ? AND is_default = 1
            """,
            (agent_name, prompt_key),
        ).fetchone()
        return dict_from_row(row) if row else None

    def get_version(self, agent_name: str, version: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM prompt_versions WHERE agent_name = ? AND version = ?",
            (agent_name, version),
        ).fetchone()
        return dict_from_row(row) if row else None

    def list_by_agent(self, agent_name: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM prompt_versions WHERE agent_name = ? ORDER BY created_at DESC",
            (agent_name,),
        ).fetchall()
        return [dict_from_row(r) for r in rows]

    def set_default(self, prompt_id: int) -> bool:
        row = self.conn.execute(
            "SELECT agent_name, prompt_key FROM prompt_versions WHERE id = ?",
            (prompt_id,),
        ).fetchone()
        if not row:
            return False

        agent_name = row["agent_name"]
        prompt_key = row["prompt_key"]

        self.conn.execute(
            "UPDATE prompt_versions SET is_default = 0 WHERE agent_name = ? AND prompt_key = ?",
            (agent_name, prompt_key),
        )
        self.conn.execute(
            "UPDATE prompt_versions SET is_default = 1 WHERE id = ?",
            (prompt_id,),
        )
        self.conn.commit()
        return True
