"""Repository Layer - 数据访问层.

提供项目和运行记录的 CRUD 操作。
遵循 Repository 模式，隔离数据库实现细节。

Reference:
- CONVENTIONS.md §13 数据库访问模式
- DATABASE_DDL.md 表结构定义
"""

import json
import sqlite3
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

import structlog

from app.agents.base import PipelineState
from app.db import dict_from_row, get_connection, is_postgres
from app.opportunity.economic_evidence import replay_economic_snapshots_for_project
from app.services.project_signals import merge_meta, parse_meta

logger = structlog.get_logger(__name__)


class ProjectRepository:
    """项目数据仓库。

    负责项目的持久化和查询操作。
    """

    def __init__(self, conn: Any = None, *, economic_replay_enabled: bool = False):
        """初始化仓库。

        Args:
            conn: 可选的数据库连接。不提供时每次操作创建新连接。
            economic_replay_enabled: When True, post-commit economic Evidence replay
                runs for the saved project. Defaults False (no-op for existing callers).
                Does not read Settings; production wiring is Task 7.
        """
        self._conn = conn
        self._economic_replay_enabled = economic_replay_enabled

    def _get_conn(self) -> Any:
        """获取数据库连接。"""
        return self._conn if self._conn else get_connection()

    def _should_close(self) -> bool:
        """判断是否应该关闭连接。"""
        return self._conn is None

    def save(self, state: PipelineState) -> dict[str, Any]:
        """保存项目评分结果。

        Args:
            state: Pipeline 状态对象，包含完整的评分结果

        Returns:
            Detached snapshot of the canonical row persisted by this save.
        """
        conn = self._get_conn()
        try:
            project = state.project

            # 序列化 JSON 字段
            narrative_json = json.dumps(state.narrative.model_dump()) if state.narrative else None
            team_json = json.dumps(state.team.model_dump()) if state.team else None
            risk_json = json.dumps(state.risk.model_dump()) if state.risk else None
            tokenomics_json = json.dumps(state.tokenomics.model_dump()) if state.tokenomics else None
            reason_json = json.dumps(state.reason) if state.reason else None

            # Preserve + merge extended signals into meta
            existing = conn.execute("SELECT meta FROM projects WHERE id = ?", (project.id,)).fetchone()
            existing_meta = None
            if existing is not None:
                existing_meta = dict_from_row(existing).get("meta")
            meta_json = merge_meta(existing_meta, project)
            source_count = int(getattr(project, "source_count", 1) or 1)

            # SQLite added DML RETURNING in 3.35; older runtimes must snapshot
            # on the same transaction before commit so the write lock closes the race.
            postgres_upsert = is_postgres() and getattr(conn, "kind", None) != "sqlite"
            sqlite_supports_returning = sqlite3.sqlite_version_info >= (3, 35, 0)
            if postgres_upsert:
                sql = """
                INSERT INTO projects (
                    id, name, url, sector, stage,
                    score, label, confidence, reason,
                    narrative_json, team_json, risk_json, tokenomics_json,
                    source, meta, fetched_at, updated_at,
                    discovery_source, discovered_at, auto_discovered, signal_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    url = EXCLUDED.url,
                    sector = EXCLUDED.sector,
                    stage = EXCLUDED.stage,
                    score = EXCLUDED.score,
                    label = EXCLUDED.label,
                    confidence = EXCLUDED.confidence,
                    reason = EXCLUDED.reason,
                    narrative_json = EXCLUDED.narrative_json,
                    team_json = EXCLUDED.team_json,
                    risk_json = EXCLUDED.risk_json,
                    tokenomics_json = EXCLUDED.tokenomics_json,
                    source = EXCLUDED.source,
                    meta = EXCLUDED.meta,
                    fetched_at = EXCLUDED.fetched_at,
                    updated_at = EXCLUDED.updated_at,
                    discovery_source = EXCLUDED.discovery_source,
                    discovered_at = EXCLUDED.discovered_at,
                    auto_discovered = EXCLUDED.auto_discovered,
                    signal_count = EXCLUDED.signal_count
                RETURNING *
                """
            else:
                sql = """
                INSERT OR REPLACE INTO projects (
                    id, name, url, sector, stage,
                    score, label, confidence, reason,
                    narrative_json, team_json, risk_json, tokenomics_json,
                    source, meta, fetched_at, updated_at,
                    discovery_source, discovered_at, auto_discovered, signal_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """
                if sqlite_supports_returning:
                    sql += " RETURNING *"
            cursor = conn.execute(
                sql,
                (
                    project.id,
                    project.name,
                    project.url,
                    project.sector,
                    project.stage,
                    state.score,
                    state.label,
                    state.confidence,
                    reason_json,
                    narrative_json,
                    team_json,
                    risk_json,
                    tokenomics_json,
                    project.source,
                    meta_json,
                    project.created_at,
                    datetime.now(UTC),
                    project.discovery_source or project.source,
                    project.discovered_at or project.created_at,
                    1 if project.auto_discovered else 0,
                    source_count,
                ),
            )
            if postgres_upsert or sqlite_supports_returning:
                saved_row = cursor.fetchone()
            else:
                saved_row = conn.execute("SELECT * FROM projects WHERE id = ?", (project.id,)).fetchone()
            if saved_row is None:
                raise RuntimeError(f"Saved project row not found: {project.id}")
            snapshot = deepcopy(dict_from_row(saved_row))
            conn.commit()

            logger.info(
                "repository.project.saved",
                project_id=project.id,
                name=project.name,
                score=state.score,
            )

            # Post-commit, pre-return economic Evidence replay on the same conn.
            # Failures warn only — never roll back the committed project.
            try:
                replay_economic_snapshots_for_project(
                    project.id,
                    conn=conn,
                    enabled=self._economic_replay_enabled,
                )
            except Exception as exc:
                logger.warning(
                    "repository.project.economic_replay_failed",
                    project_id=project.id,
                    error=str(exc),
                    error_type=type(exc).__name__,
                )

            return snapshot

        except Exception:
            conn.rollback()
            raise
        finally:
            if self._should_close():
                conn.close()

    def update_meta_signals(self, project_id: str, signals: dict[str, Any]) -> dict[str, Any] | None:
        """Merge keys into projects.meta.signals and return updated row."""
        conn = self._get_conn()
        try:
            row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
            if not row:
                return None
            d = dict_from_row(row)
            meta = parse_meta(d.get("meta"))
            prev = meta.get("signals") if isinstance(meta.get("signals"), dict) else {}
            merged = {**prev, **signals}
            # drop Nones that would wipe intentionally? keep explicit null clear
            meta["signals"] = merged
            meta_json = json.dumps(meta, ensure_ascii=False)
            conn.execute(
                "UPDATE projects SET meta = ?, updated_at = ? WHERE id = ?",
                (meta_json, datetime.now(UTC), project_id),
            )
            conn.commit()
            d["meta"] = meta_json
            return d
        finally:
            if self._should_close():
                conn.close()

    def save_batch(self, states: list[PipelineState]) -> int:
        """批量保存项目。

        Args:
            states: Pipeline 状态列表
        Returns:
            保存成功的项目数量
        """
        return len(self.save_batch_with_rows(states))

    def save_batch_with_rows(self, states: list[PipelineState]) -> list[dict[str, Any]]:
        """Save states and return one detached row snapshot per successful save."""
        persisted_project_rows: list[dict[str, Any]] = []
        for state in states:
            try:
                persisted_project_rows.append(self.save(state))
            except Exception as e:
                logger.error(
                    "repository.project.save_failed",
                    project_id=state.project.id,
                    error=str(e),
                )
        return persisted_project_rows

    def get_by_id(self, project_id: str) -> dict[str, Any] | None:
        """根据 ID 查询项目。

        Args:
            project_id: 项目 ID

        Returns:
            项目字典，不存在返回 None
        """
        conn = self._get_conn()
        try:
            cursor = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,))
            row = cursor.fetchone()
            return dict_from_row(row) if row else None
        finally:
            if self._should_close():
                conn.close()

    def list_projects(
        self,
        page: int = 1,
        page_size: int = 20,
        label: str | None = None,
        sector: str | None = None,
        stage: str | None = None,
        min_score: int | None = None,
        sort_by: str = "score",
        sort_order: str = "desc",
    ) -> tuple[list[dict[str, Any]], int]:
        """分页查询项目列表。

        Args:
            page: 页码（从1开始）
            page_size: 每页数量
            label: 标签筛选
            sector: 赛道筛选
            stage: 阶段筛选
            min_score: 最低分数筛选
            sort_by: 排序字段
            sort_order: 排序顺序

        Returns:
            (项目列表, 总数量)
        """
        conn = self._get_conn()
        try:
            # 构建 WHERE 条件
            conditions = []
            params = []

            if label:
                conditions.append("label = ?")
                params.append(label)

            if sector:
                conditions.append("sector = ?")
                params.append(sector)

            if stage:
                conditions.append("stage = ?")
                params.append(stage)

            if min_score is not None:
                conditions.append("score >= ?")
                params.append(min_score)

            where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

            # 查询总数
            count_query = f"SELECT COUNT(*) FROM projects {where_clause}"
            cursor = conn.execute(count_query, params)
            total = cursor.fetchone()[0]

            # 构建排序
            sort_column = {
                "score": "score",
                "name": "name",
                "created_at": "created_at",
            }.get(sort_by, "score")

            sort_direction = "DESC" if sort_order.lower() == "desc" else "ASC"
            order_clause = f"ORDER BY {sort_column} {sort_direction}"

            # 分页查询
            offset = (page - 1) * page_size
            list_query = f"""
                SELECT * FROM projects
                {where_clause}
                {order_clause}
                LIMIT ? OFFSET ?
            """
            cursor = conn.execute(list_query, [*params, page_size, offset])
            rows = cursor.fetchall()

            projects = [dict_from_row(row) for row in rows]

            logger.info(
                "repository.project.listed",
                total=total,
                page=page,
                page_size=page_size,
                returned=len(projects),
            )

            return projects, total

        finally:
            if self._should_close():
                conn.close()

    def delete_by_id(self, project_id: str) -> bool:
        """删除项目。

        Args:
            project_id: 项目 ID

        Returns:
            是否删除成功
        """
        conn = self._get_conn()
        try:
            cursor = conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
            conn.commit()
            deleted = cursor.rowcount > 0

            if deleted:
                logger.info(
                    "repository.project.deleted",
                    project_id=project_id,
                )

            return deleted

        finally:
            if self._should_close():
                conn.close()


class LogRepository:
    """运行日志仓库。

    记录每次运行的详细日志。
    """

    def __init__(self, conn: Any = None):
        """初始化仓库。

        Args:
            conn: 可选的数据库连接。不提供时每次操作创建新连接。
        """
        self._conn = conn

    def _get_conn(self) -> Any:
        """获取数据库连接。"""
        return self._conn if self._conn else get_connection()

    def _should_close(self) -> bool:
        """判断是否应该关闭连接。"""
        return self._conn is None

    def log_run(
        self,
        run_id: str,
        project_id: str | None = None,
        agent_name: str | None = None,
        input_data: dict | None = None,
        output_data: dict | None = None,
        error: str | None = None,
        duration_ms: int | None = None,
    ) -> None:
        """记录运行日志。

        Args:
            run_id: 运行 ID
            project_id: 项目 ID
            agent_name: Agent 名称
            input_data: 输入数据
            output_data: 输出数据
            error: 错误信息
            duration_ms: 耗时（毫秒）
        """
        conn = self._get_conn()
        try:
            input_json = json.dumps(input_data) if input_data else None
            output_json = json.dumps(output_data) if output_data else None

            conn.execute(
                """
                INSERT INTO logs (
                    run_id, project_id, agent_name,
                    input, output, error, duration_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    run_id,
                    project_id,
                    agent_name,
                    input_json,
                    output_json,
                    error,
                    duration_ms,
                ),
            )
            conn.commit()

        finally:
            if self._should_close():
                conn.close()

    def get_run_logs(self, run_id: str) -> list[dict[str, Any]]:
        """获取某次运行的所有日志。

        Args:
            run_id: 运行 ID

        Returns:
            日志列表
        """
        conn = self._get_conn()
        try:
            cursor = conn.execute("SELECT * FROM logs WHERE run_id = ? ORDER BY timestamp", (run_id,))
            rows = cursor.fetchall()
            return [dict_from_row(row) for row in rows]

        finally:
            if self._should_close():
                conn.close()
