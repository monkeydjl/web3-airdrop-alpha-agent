"""Repository Layer - 数据访问层.

提供项目和运行记录的 CRUD 操作。
遵循 Repository 模式，隔离数据库实现细节。

Reference:
- CONVENTIONS.md §13 数据库访问模式
- DATABASE_DDL.md 表结构定义
"""

import json
import sqlite3
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any

import structlog

from app.db import get_connection, dict_from_row
from app.agents.base import PipelineState

logger = structlog.get_logger(__name__)


class ProjectRepository:
    """项目数据仓库。

    负责项目的持久化和查询操作。
    """

    def __init__(self, conn: Optional[sqlite3.Connection] = None):
        """初始化仓库。

        Args:
            conn: 可选的数据库连接。不提供时每次操作创建新连接。
        """
        self._conn = conn

    def _get_conn(self) -> sqlite3.Connection:
        """获取数据库连接。"""
        return self._conn if self._conn else get_connection()

    def _should_close(self) -> bool:
        """判断是否应该关闭连接。"""
        return self._conn is None

    def save(self, state: PipelineState) -> None:
        """保存项目评分结果。

        Args:
            state: Pipeline 状态对象，包含完整的评分结果
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

            # Insert or replace
            conn.execute("""
                INSERT OR REPLACE INTO projects (
                    id, name, url, sector, stage,
                    score, label, confidence, reason,
                    narrative_json, team_json, risk_json, tokenomics_json,
                    source, fetched_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
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
                project.created_at,
                datetime.now(timezone.utc),
            ))
            conn.commit()

            logger.info(
                "repository.project.saved",
                project_id=project.id,
                name=project.name,
                score=state.score,
            )

        finally:
            if self._should_close():
                conn.close()

    def save_batch(self, states: List[PipelineState]) -> int:
        """批量保存项目。

        Args:
            states: Pipeline 状态列表

        Returns:
            保存成功的项目数量
        """
        saved = 0
        for state in states:
            try:
                self.save(state)
                saved += 1
            except Exception as e:
                logger.error(
                    "repository.project.save_failed",
                    project_id=state.project.id,
                    error=str(e),
                )
        return saved

    def get_by_id(self, project_id: str) -> Optional[Dict[str, Any]]:
        """根据 ID 查询项目。

        Args:
            project_id: 项目 ID

        Returns:
            项目字典，不存在返回 None
        """
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                "SELECT * FROM projects WHERE id = ?",
                (project_id,)
            )
            row = cursor.fetchone()
            return dict_from_row(row) if row else None
        finally:
            if self._should_close():
                conn.close()

    def list_projects(
        self,
        page: int = 1,
        page_size: int = 20,
        label: Optional[str] = None,
        sector: Optional[str] = None,
        stage: Optional[str] = None,
        min_score: Optional[int] = None,
        sort_by: str = "score",
        sort_order: str = "desc",
    ) -> tuple[List[Dict[str, Any]], int]:
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
            cursor = conn.execute(list_query, params + [page_size, offset])
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
            cursor = conn.execute(
                "DELETE FROM projects WHERE id = ?",
                (project_id,)
            )
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

    def __init__(self, conn: Optional[sqlite3.Connection] = None):
        """初始化仓库。

        Args:
            conn: 可选的数据库连接
        """
        self._conn = conn

    def _get_conn(self) -> sqlite3.Connection:
        """获取数据库连接。"""
        return self._conn if self._conn else get_connection()

    def _should_close(self) -> bool:
        """判断是否应该关闭连接。"""
        return self._conn is None

    def log_run(
        self,
        run_id: str,
        project_id: Optional[str] = None,
        agent_name: Optional[str] = None,
        input_data: Optional[Dict] = None,
        output_data: Optional[Dict] = None,
        error: Optional[str] = None,
        duration_ms: Optional[int] = None,
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

            conn.execute("""
                INSERT INTO logs (
                    run_id, project_id, agent_name,
                    input, output, error, duration_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                run_id,
                project_id,
                agent_name,
                input_json,
                output_json,
                error,
                duration_ms,
            ))
            conn.commit()

        finally:
            if self._should_close():
                conn.close()

    def get_run_logs(self, run_id: str) -> List[Dict[str, Any]]:
        """获取某次运行的所有日志。

        Args:
            run_id: 运行 ID

        Returns:
            日志列表
        """
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                "SELECT * FROM logs WHERE run_id = ? ORDER BY timestamp",
                (run_id,)
            )
            rows = cursor.fetchall()
            return [dict_from_row(row) for row in rows]

        finally:
            if self._should_close():
                conn.close()
