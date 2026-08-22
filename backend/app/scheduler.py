"""Unified Scheduler — merges collection + analysis into a single APScheduler instance.

ADR-005 双调度模型的归并实现。此前 `CollectionScheduler` 和 `AnalysisScheduler`
各自持有独立的 `AsyncIOScheduler` 实例，造成：
1. 两个调度线程池、两套 misfire 配置、两套 shutdown 逻辑
2. 生命周期管理分散（第二个启动失败需手动回收第一个）
3. skip-if-running 语义隐式（靠 `QueueDrainInProgressError` 异常捕获），
   无法在触发前显式判断

本模块用单个 `AsyncIOScheduler` 注册全部 job，并在分析触发前**显式检查**
`active_runs()` 实现跳过——§11「前一次未完成则跳过」语义。

2026-08-22 补入归档 job：`app/archive.py` 的归档逻辑此前只有手动脚本调用，
没有任何调度，等于保留期配置从未生效过。

Reference:
- ENGINEERING_ROADMAP.md §11 调度
- ADR-005 APScheduler 内嵌调度
- V2_TASKS.md B3
- DATABASE_DDL.md §6 数据保留策略
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.collectors.base import CollectorResult
from app.collectors.metrics import CollectionMetrics
from app.config import settings
from app.inflight import QUEUE_DRAIN_KEY, QueueDrainInProgressError, active_runs
from app.metrics import (
    COLLECTION_DUPLICATES,
    COLLECTION_DURATION,
    COLLECTION_ITEMS,
    COLLECTION_RUNS,
)
from app.pipeline_run import execute_analysis_pipeline, record_pipeline_run

if TYPE_CHECKING:
    from app.collectors.registry import CollectorRegistry

logger = structlog.get_logger(__name__)

CollectionCallback = Callable[[str, "CollectorResult"], Awaitable[None]]


class UnifiedScheduler:
    """统一调度器：采集 + 分析共用一个 APScheduler 实例。

    取代此前分离的 `CollectionScheduler` + `AnalysisScheduler`，提供：
    - 单一 `AsyncIOScheduler`（一个线程池、一套 misfire 配置）
    - 显式 skip-if-running：分析触发前检查 `QUEUE_DRAIN_KEY` 是否在飞
    - 统一生命周期管理（start/shutdown 一次调用覆盖全部 job）
    """

    def __init__(
        self,
        registry: CollectorRegistry,
        on_collection: CollectionCallback | None = None,
    ) -> None:
        self.registry = registry
        self.on_collection = on_collection
        self.scheduler = AsyncIOScheduler(timezone=settings.timezone)
        self.metrics = CollectionMetrics()
        self._logger = logger.bind(component="unified_scheduler")

    # ── 生命周期 ──────────────────────────────────

    def start(self) -> None:
        """启动统一调度器：注册全部采集 job + 分析 job + 归档 job，然后启动。"""
        if (
            not settings.scheduler_enabled
            and not settings.collection_scheduler_enabled
            and not settings.archive_scheduler_enabled
        ):
            self._logger.info("unified_scheduler.disabled")
            return

        self._register_collection_jobs()
        self._register_analysis_job()
        self._register_archive_job()
        self.scheduler.start()
        self._logger.info("unified_scheduler.started")

    def shutdown(self, wait: bool = True) -> None:
        """停止调度器（未启动时为 no-op，避免 SchedulerNotRunningError）。"""
        if self.scheduler.running:
            self.scheduler.shutdown(wait=wait)
            self._logger.info("unified_scheduler.shutdown")

    # ── 采集 job 注册 ──────────────────────────────

    def _register_collection_jobs(self) -> None:
        """注册各采集源任务（吸收自 CollectionScheduler）。"""
        if not settings.collection_scheduler_enabled:
            self._logger.info("unified_scheduler.collection_disabled")
            return

        cron_map = {
            "defillama": settings.defillama_cron,
            "github": settings.github_cron,
            "coingecko": settings.coingecko_cron,
            "cryptorank": settings.cryptorank_cron,
            "rootdata": getattr(settings, "rootdata_cron", "45 9 * * *"),
            "twitter_kol": settings.twitter_kol_cron,
            "twitter_keyword": settings.twitter_keyword_cron,
            "etherscan": settings.etherscan_cron,
            "galxe": settings.galxe_cron,
            "layer3": settings.layer3_cron,
        }

        for source_id, cron in cron_map.items():
            collector = self.registry.get(source_id)
            if collector and collector.is_enabled():
                self.scheduler.add_job(
                    self._run_collection,
                    trigger=CronTrigger.from_crontab(cron, timezone=settings.timezone),
                    id=f"collect_{source_id}",
                    name=f"Collect {source_id}",
                    replace_existing=True,
                    args=(source_id,),
                    misfire_grace_time=settings.scheduler_misfire_grace_seconds,
                    coalesce=True,
                    max_instances=1,
                )
                self._logger.info(
                    "unified_scheduler.collection_job_added",
                    source_id=source_id,
                    cron=cron,
                    timezone=settings.timezone,
                )

    async def _run_collection(self, source_id: str) -> None:
        """执行单个采集任务（吸收自 CollectionScheduler）。"""
        collector = self.registry.get(source_id)
        if not collector or not collector.is_enabled():
            self._logger.warning("unified_scheduler.skip_disabled", source_id=source_id)
            return

        # Honor operator toggle in data_sources.enabled
        try:
            from app.db import get_connection

            conn = get_connection()
            try:
                row = conn.execute(
                    "SELECT enabled FROM data_sources WHERE source_id = ?",
                    (source_id,),
                ).fetchone()
                if row is not None and not bool(row["enabled"]):
                    self._logger.info(
                        "unified_scheduler.skip_operator_disabled",
                        source_id=source_id,
                    )
                    return
            finally:
                conn.close()
        except Exception as exc:
            self._logger.warning(
                "unified_scheduler.operator_flag_check_failed",
                source_id=source_id,
                error_type=type(exc).__name__,
                error=str(exc)[:160],
            )

        started_at = datetime.now(UTC)
        self._logger.info(
            "unified_scheduler.collection_started",
            source_id=source_id,
            started_at=started_at.isoformat(),
        )

        try:
            result = await collector.collect()
        except Exception as e:
            result = CollectorResult(
                source_id=source_id,
                status="error",
                error_message=str(e),
            )
            result.started_at = started_at
            result.finished_at = datetime.now(UTC)
            self._logger.error(
                "unified_scheduler.collection_failed",
                source_id=source_id,
                error=str(e),
            )

        if not result.started_at:
            result.started_at = started_at
        if not result.finished_at:
            result.finished_at = datetime.now(UTC)

        duration = (result.finished_at - result.started_at).total_seconds()
        COLLECTION_RUNS.labels(source_id=source_id, status=result.status).inc()
        COLLECTION_DURATION.labels(source_id=source_id).observe(duration)
        COLLECTION_ITEMS.labels(source_id=source_id).inc(len(result.items))

        if self.on_collection:
            try:
                await self.on_collection(source_id, result)
            except Exception as e:
                self._logger.error(
                    "unified_scheduler.collection_callback_failed",
                    source_id=source_id,
                    error=str(e),
                )

        COLLECTION_DUPLICATES.labels(source_id=source_id).inc(result.items_duplicate or 0)

        try:
            self.metrics.check_alerts(window_hours=24)
        except Exception as e:
            self._logger.error("unified_scheduler.metrics_alert_failed", error=str(e))

        self._logger.info(
            "unified_scheduler.collection_completed",
            source_id=source_id,
            status=result.status,
            items=len(result.items),
        )

    async def trigger_collection_now(self, source_id: str) -> dict[str, Any]:
        """手动立即触发一次采集。"""
        await self._run_collection(source_id)
        return {"source_id": source_id, "triggered_at": datetime.now(UTC).isoformat()}

    # ── 分析 job 注册 + skip-if-running ────────────

    def _register_analysis_job(self) -> None:
        """注册分析排空 job（吸收自 AnalysisScheduler）。"""
        if not settings.scheduler_enabled:
            self._logger.info("unified_scheduler.analysis_disabled")
            return

        self.scheduler.add_job(
            self._run_analysis,
            trigger=CronTrigger.from_crontab(settings.cron_expression, timezone=settings.timezone),
            id="analysis_run_queue",
            name="Analyze unprocessed raw_projects",
            replace_existing=True,
            misfire_grace_time=settings.scheduler_misfire_grace_seconds,
            coalesce=True,
            max_instances=1,
        )
        self._logger.info(
            "unified_scheduler.analysis_job_added",
            cron=settings.cron_expression,
            timezone=settings.timezone,
            misfire_grace_seconds=settings.scheduler_misfire_grace_seconds,
        )

    async def _run_analysis(self) -> None:
        """执行分析排空，带显式 skip-if-running 检查。

        §11「前一次未完成则跳过」语义：
        在调用 `execute_analysis_pipeline` 之前**显式检查** `QUEUE_DRAIN_KEY`
        是否已在 `active_runs()` 中。若在飞则跳过并记日志，不触发 pipeline。

        这比此前"先调用再捕获 `QueueDrainInProgressError`"更高效：
        避免了无意义的 `claim_run` 争抢与异常构造/捕获开销。
        仍保留 except 兜底以防竞态（检查与调用之间有其他入口抢到锁）。
        """
        # ── 显式 skip-if-running ──
        if QUEUE_DRAIN_KEY in active_runs():
            self._logger.info(
                "unified_scheduler.analysis_skipped",
                reason="queue_drain_in_progress",
                guard_key=QUEUE_DRAIN_KEY,
            )
            return

        self._logger.info("unified_scheduler.analysis_started")
        started = time.perf_counter()
        run_id = f"cron-run-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S-%f')}"
        try:
            result = await execute_analysis_pipeline(trigger="cron")
            self._logger.info(
                "unified_scheduler.analysis_completed",
                project_count=result.get("project_count"),
                scored_count=result.get("scored_count"),
                persisted_count=result.get("persisted_count"),
                status=result.get("status"),
            )
        except QueueDrainInProgressError:
            # 竞态兜底：显式检查通过后，调用 execute_analysis_pipeline 之前
            # 另一个入口（如 collection auto-run）抢到了锁。跳过即可。
            self._logger.info(
                "unified_scheduler.analysis_skipped",
                reason="queue_drain_in_progress_race",
                guard_key=QUEUE_DRAIN_KEY,
            )
        except Exception as e:
            self._logger.error("unified_scheduler.analysis_failed", error=str(e), exc_info=True)
            record_pipeline_run(
                run_id=run_id,
                trigger="cron",
                duration_ms=int((time.perf_counter() - started) * 1000),
                summary={"status": "failed"},
                error=str(e),
            )

    async def trigger_analysis_now(self) -> dict[str, Any]:
        """手动立即触发一次分析。"""
        return await execute_analysis_pipeline(trigger="manual")

    # ── 归档 job 注册 ──────────────────────────────

    def _register_archive_job(self) -> None:
        """注册归档清理 job。

        归档逻辑（`app/archive.py`）此前只有手动脚本会调用，**没有任何调度**，
        所以保留期配置实际上从未生效过。默认 03:00 跑，在所有采集 job
        （08:00–10:30）之前完成，避免和写入争锁。
        """
        if not settings.archive_scheduler_enabled:
            self._logger.info("unified_scheduler.archive_disabled")
            return

        self.scheduler.add_job(
            self._run_archive,
            trigger=CronTrigger.from_crontab(settings.archive_cron, timezone=settings.timezone),
            id="archive_cleanup",
            name="Archive expired raw collection data",
            replace_existing=True,
            misfire_grace_time=settings.scheduler_misfire_grace_seconds,
            coalesce=True,
            max_instances=1,
        )
        self._logger.info(
            "unified_scheduler.archive_job_added",
            cron=settings.archive_cron,
            timezone=settings.timezone,
        )

    def _run_archive(self) -> None:
        """执行一次归档清理并记入 `archive_runs`。

        同步函数：归档全是 SQL，没有 await 点；APScheduler 会把它丢到线程池里，
        因此不会阻塞事件循环。异常不外抛 —— 归档失败不该让调度器停掉，
        失败已经作为一行 `status=failed` 记进历史了。
        """
        from app.archive import RawDataArchiver
        from app.db import get_connection
        from app.repositories.archive_runs import TRIGGER_SCHEDULER

        conn = get_connection()
        try:
            result = RawDataArchiver().run_and_record(conn, trigger=TRIGGER_SCHEDULER)
            self._logger.info(
                "unified_scheduler.archive_completed",
                **result.to_dict(),
            )
        except Exception as e:
            self._logger.error("unified_scheduler.archive_failed", error=str(e), exc_info=True)
        finally:
            conn.close()

    # ── 诊断 ──────────────────────────────────────

    def get_jobs(self) -> list[dict[str, Any]]:
        """获取已注册任务列表（采集 + 分析统一视图）。"""
        return [
            {
                "id": job.id,
                "name": job.name,
                "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None,
            }
            for job in self.scheduler.get_jobs()
        ]
