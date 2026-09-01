"""Repository Layer - 数据访问层.

提供项目和运行记录的 CRUD 操作。
遵循 Repository 模式，隔离数据库实现细节。

Reference:
- CONVENTIONS.md §13 数据库访问模式
- DATABASE_DDL.md 表结构定义
"""

import json
import sqlite3
from contextlib import suppress
from copy import deepcopy
from datetime import UTC, datetime
from functools import partial
from typing import Any

import structlog

from app.agents.base import PipelineState
from app.db import dict_from_row, get_connection, is_postgres, scalar
from app.opportunity.economic_evidence import replay_economic_snapshots_for_project
from app.services.project_signals import merge_meta, parse_meta

logger = structlog.get_logger(__name__)


def _sub_scores_json(state: PipelineState) -> str | None:
    """子分快照序列化；无子分时返回 None（交由 UPSERT 的 COALESCE 保留旧值）。

    ScorerAgent 失败时会吞掉异常并留下空 sub_scores（scorer.py 的 run()），
    若此处写入 "{}"，一次评分失败就会永久抹掉上一次成功评分的子分快照。
    """
    sub_scores = getattr(state, "sub_scores", None)
    if not sub_scores:
        return None
    return json.dumps(sub_scores, ensure_ascii=False)


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

            # Preserve + merge extended signals into meta.
            # 先开写事务/行锁再读旧 meta，关闭并发保存时的 read-modify-write 丢更新窗口。
            with suppress(Exception):  # 已有事务打开时尽力而为
                if hasattr(conn, "begin_serialized_write"):
                    conn.begin_serialized_write()
            select_meta_sql = "SELECT meta FROM projects WHERE id = ?"
            if getattr(conn, "kind", None) == "postgres":
                select_meta_sql += " FOR UPDATE"
            existing = conn.execute(select_meta_sql, (project.id,)).fetchone()
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
                    discovery_source, discovered_at, auto_discovered, signal_count,
                    weight_version, sub_scores, veto
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    signal_count = EXCLUDED.signal_count,
                    weight_version = COALESCE(EXCLUDED.weight_version, projects.weight_version),
                    sub_scores = COALESCE(EXCLUDED.sub_scores, projects.sub_scores),
                    veto = EXCLUDED.veto
                RETURNING *
                """
            elif sqlite3.sqlite_version_info >= (3, 24, 0):
                # SQLite UPSERT（3.24+）：与 Postgres 分支保持同一语义。
                # 不能用 INSERT OR REPLACE：它是 DELETE+INSERT，会把未列出的列
                # （recommendation/raw_signals/raw_signals_hash/created_at）清空。
                sql = """
                INSERT INTO projects (
                    id, name, url, sector, stage,
                    score, label, confidence, reason,
                    narrative_json, team_json, risk_json, tokenomics_json,
                    source, meta, fetched_at, updated_at,
                    discovery_source, discovered_at, auto_discovered, signal_count,
                    weight_version, sub_scores, veto
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    signal_count = EXCLUDED.signal_count,
                    weight_version = COALESCE(EXCLUDED.weight_version, projects.weight_version),
                    sub_scores = COALESCE(EXCLUDED.sub_scores, projects.sub_scores),
                    veto = EXCLUDED.veto
                """
                if sqlite_supports_returning:
                    sql += " RETURNING *"
            else:
                sql = """
                INSERT OR REPLACE INTO projects (
                    id, name, url, sector, stage,
                    score, label, confidence, reason,
                    narrative_json, team_json, risk_json, tokenomics_json,
                    source, meta, fetched_at, updated_at,
                    discovery_source, discovered_at, auto_discovered, signal_count,
                    weight_version, sub_scores, veto
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    # 生效权重版本 + 子分快照：离线重加权与版本归属所必需
                    # （WEIGHT_CALIBRATION §1.2 / §4.3）。Scorer 失败时二者为空，
                    # 此时传 NULL 让 UPSERT 的 COALESCE 保留上一次的好值，
                    # 而不是用空壳覆盖掉可用的历史快照。
                    getattr(state, "weight_version", None) or None,
                    _sub_scores_json(state),
                    # Unlike score snapshots, a successful scoring pass may have no
                    # veto and must clear a stale previous veto.
                    getattr(state, "veto", None),
                ),
            )
            if postgres_upsert or sqlite_supports_returning:
                saved_row = cursor.fetchone()
            else:
                saved_row = conn.execute("SELECT * FROM projects WHERE id = ?", (project.id,)).fetchone()
            if saved_row is None:
                raise RuntimeError(f"Saved project row not found: {project.id}")
            snapshot = deepcopy(dict_from_row(saved_row))

            # E4 (§6.9.12 / §6.11): 在同一事务内写 project_history 快照行。
            # 事务回滚时两表一致（projects + project_history 同时撤销）。
            run_id = getattr(state.context, "run_id", None) or "unknown"
            weight_version = getattr(state, "weight_version", None) or None
            history_snapshot = json.dumps(
                {
                    "project_name": project.name,
                    "url": project.url,
                    "sector": project.sector,
                    "source": project.source,
                    "confidence": state.confidence,
                    "veto": getattr(state, "veto", None),
                    "reason": state.reason,
                    "narrative": state.narrative.model_dump() if state.narrative else None,
                    "team": state.team.model_dump() if state.team else None,
                    "risk": state.risk.model_dump() if state.risk else None,
                    "tokenomics": state.tokenomics.model_dump() if state.tokenomics else None,
                    "sub_scores": getattr(state, "sub_scores", None),
                    "meta": json.loads(meta_json) if meta_json else None,
                },
                ensure_ascii=False,
                default=str,
            )
            conn.execute(
                """
                INSERT INTO project_history
                    (project_id, run_id, score, label, stage, weight_version, snapshot)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (project.id, run_id, state.score, state.label, project.stage, weight_version, history_snapshot),
            )

            conn.commit()

            logger.info(
                "repository.project.saved",
                project_id=project.id,
                name=project.name,
                score=state.score,
            )

            # ADR-010 写时失效：项目落库后使对应 sector 缓存失效
            if project.sector:
                with suppress(Exception):
                    self.invalidate_sector_cache(project.sector)

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

    def update_meta_signals(
        self,
        project_id: str,
        signals: dict[str, Any],
        meta_updates: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Merge keys into projects.meta.signals and return updated row.

        meta_updates（可选）在**同一事务**内合并进 meta 顶层（如 funding_note）。
        此前调用方要写顶层键须另开一条连接、重新整体覆盖 meta，与这里的 signals
        写非同一事务：第二次写用读时刻的 meta 快照覆盖，并发下会丢掉中间写入，
        且第二次失败时 signals 已提交、顶层键丢失。合并到这里消除该窗口。
        """
        conn = self._get_conn()
        try:
            with suppress(Exception):
                if hasattr(conn, "begin_serialized_write"):
                    conn.begin_serialized_write()
            select_sql = "SELECT * FROM projects WHERE id = ?"
            if getattr(conn, "kind", None) == "postgres":
                select_sql += " FOR UPDATE"
            row = conn.execute(select_sql, (project_id,)).fetchone()
            if not row:
                conn.rollback()
                return None
            d = dict_from_row(row)
            meta = parse_meta(d.get("meta"))
            raw_signals = meta.get("signals")
            prev = raw_signals if isinstance(raw_signals, dict) else {}
            merged = {**prev, **signals}
            # drop Nones that would wipe intentionally? keep explicit null clear
            meta["signals"] = merged
            if meta_updates:
                meta.update(meta_updates)
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
        """Save states and return one detached row snapshot per successful save.

        整批复用一条连接：此前每个 state 都新建并关闭一次连接（含 WAL pragma
        与 SQLite 文件打开），500 个项目就是 500 次建连开销。逐条提交的语义保持
        不变，单条失败仍只跳过该条。
        """
        persisted_project_rows: list[dict[str, Any]] = []
        owns_conn = self._conn is None
        conn = self._conn if self._conn is not None else get_connection()
        # 绑定到同一连接的作用域仓库：其 _should_close() 为 False，save() 不会关闭它
        scoped = ProjectRepository(conn) if owns_conn else self
        try:
            for state in states:
                try:
                    persisted_project_rows.append(scoped.save(state))
                except Exception as e:
                    logger.error(
                        "repository.project.save_failed",
                        project_id=state.project.id,
                        error=str(e),
                    )
        finally:
            if owns_conn:
                conn.close()
        return persisted_project_rows

    def aggregate_counts(self, column: str) -> dict[str, int]:
        """在数据库侧按列做分组计数（label / sector）。

        避免为了统计把全部行搬进 Python。列名走白名单，杜绝注入。
        """
        allowed = {"label", "sector", "stage"}
        if column not in allowed:
            raise ValueError(f"unsupported aggregate column: {column}")
        conn = self._get_conn()
        try:
            # 列名来自上方闭合白名单，取值无用户输入
            sql = f"SELECT {column} AS bucket, COUNT(*) AS n FROM projects GROUP BY {column}"
            rows = conn.execute(sql).fetchall()
            return {dict_from_row(r)["bucket"]: int(dict_from_row(r)["n"]) for r in rows}
        finally:
            if self._should_close():
                conn.close()

    def count_by_sector(self, sector: str) -> int:
        """统计指定赛道的项目数（ADR-010 读时重建的数据源）。

        直接走 DB COUNT(*)，调用方应优先通过 SectorCountCache 间接调用。
        """
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM projects WHERE sector = ?",
                (sector,),
            ).fetchone()
            return int(row["n"]) if row else 0
        finally:
            if self._should_close():
                conn.close()

    def global_sector_counts(self, sectors: set[str] | None = None) -> dict[str, int]:
        """全库 sector 计数（经 SectorCountCache 缓存，ADR-010 V2）。

        Args:
            sectors: 需要查询的 sector 集合；None 表示查全库所有 sector。

        Returns:
            sector → count 字典
        """
        from app.cache import get_sector_count_cache

        cache = get_sector_count_cache()

        if sectors is None:
            # 全量查询，直接走 aggregate_counts（一次性查完比逐个缓存更高效）
            all_counts = self.aggregate_counts("sector")
            for s, n in all_counts.items():
                cache.put(s, n)
            return all_counts

        result: dict[str, int] = {}
        for sector in sectors:
            # functools.partial 而非带默认值的 lambda：后者 mypy 无法推断
            # （Cannot infer type of lambda），同时保留"绑定当前 sector"的语义。
            result[sector] = cache.get_or_compute(
                sector,
                partial(self.count_by_sector, sector),
            )
        return result

    def invalidate_sector_cache(self, sector: str | None = None) -> None:
        """写时失效：写入项目后使对应 sector 缓存项失效（ADR-010）。"""
        from app.cache import get_sector_count_cache

        cache = get_sector_count_cache()
        if sector:
            cache.invalidate(sector)
        else:
            cache.invalidate_all()

    def list_insight_rows(self) -> list[dict[str, Any]]:
        """只取洞察聚合真正需要的窄投影。

        原实现用 `SELECT *` 拉最多 1 万行，连 raw_signals / meta / risk_json /
        tokenomics_json 等大 JSON 一起搬运，仅为读取其中两个字段。
        """
        conn = self._get_conn()
        try:
            rows = conn.execute("SELECT id, name, sector, label, narrative_json, team_json FROM projects").fetchall()
            return [dict_from_row(r) for r in rows]
        finally:
            if self._should_close():
                conn.close()

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
        auto_discovered: bool | None = None,
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
            auto_discovered: 仅查自动发现的项目 (True) 或手动录入 (False)

        Returns:
            (项目列表, 总数量)
        """
        conn = self._get_conn()
        try:
            # 构建 WHERE 条件
            conditions = []
            params: list[Any] = []

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

            if auto_discovered is not None:
                conditions.append("auto_discovered = ?")
                params.append(1 if auto_discovered else 0)

            where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

            # 查询总数（scalar 兼容 sqlite Row 与 Postgres dict_row）
            count_query = f"SELECT COUNT(*) FROM projects {where_clause}"
            cursor = conn.execute(count_query, params)
            total = int(scalar(cursor.fetchone()) or 0)

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
            deleted = bool(cursor.rowcount > 0)

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
        input_data: dict[str, Any] | None = None,
        output_data: dict[str, Any] | None = None,
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
