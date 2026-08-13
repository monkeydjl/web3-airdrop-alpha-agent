"""Collection Scheduler.

基于 APScheduler 的采集调度器，按配置周期触发各数据源采集。
与 Analysis Scheduler 分离，形成 ADR-012 双调度模型。

参考：
- ENGINEERING_ROADMAP.md §6.2 双调度
- ADR-012-system-direction-auto-scan.md
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.collectors.base import CollectorResult
from app.collectors.metrics import CollectionMetrics
from app.config import settings
from app.metrics import (
    COLLECTION_DUPLICATES,
    COLLECTION_DURATION,
    COLLECTION_ITEMS,
    COLLECTION_RUNS,
)

if TYPE_CHECKING:
    from app.collectors.base import CollectorResult
    from app.collectors.registry import CollectorRegistry

logger = structlog.get_logger(__name__)


CollectionCallback = Callable[[str, "CollectorResult"], Awaitable[None]]


class CollectionScheduler:
    """采集调度器。

    负责按 cron 周期触发各 DataCollector，并把结果回调给处理函数。
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
        self._logger = logger.bind(component="collection_scheduler")

    def start(self) -> None:
        """启动调度器。"""
        if not settings.collection_scheduler_enabled:
            self._logger.info("collection_scheduler.disabled")
            return

        # 注册各采集源任务
        cron_map = {
            "defillama": settings.defillama_cron,
            "github": settings.github_cron,
            "coingecko": settings.coingecko_cron,
            "cryptorank": settings.cryptorank_cron,
            "rootdata": getattr(settings, "rootdata_cron", "45 9 * * *"),
            # Twitter 分 KOL 监听与关键词监听
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
                    # 显式 timezone：预先构造的 CronTrigger 不会继承 scheduler.timezone，
                    # 缺了它 10 个采集任务全部按容器时钟触发（见 analysis_scheduler 同一注释）
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
                    "collection_scheduler.job_added",
                    source_id=source_id,
                    cron=cron,
                    timezone=settings.timezone,
                )

        self.scheduler.start()
        self._logger.info("collection_scheduler.started")

    def shutdown(self, wait: bool = True) -> None:
        """停止调度器（未启动时为 no-op，避免 SchedulerNotRunningError）。"""
        if self.scheduler.running:
            self.scheduler.shutdown(wait=wait)
            self._logger.info("collection_scheduler.shutdown")

    async def _run_collection(self, source_id: str) -> None:
        """执行单个采集任务。"""
        collector = self.registry.get(source_id)
        if not collector or not collector.is_enabled():
            self._logger.warning("collection_scheduler.skip_disabled", source_id=source_id)
            return

        # Honor operator toggle in data_sources.enabled (default on if no row).
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
                        "collection_scheduler.skip_operator_disabled",
                        source_id=source_id,
                    )
                    return
            finally:
                conn.close()
        except Exception as exc:
            self._logger.warning(
                "collection_scheduler.operator_flag_check_failed",
                source_id=source_id,
                error_type=type(exc).__name__,
                error=str(exc)[:160],
            )

        started_at = datetime.now(UTC)
        self._logger.info(
            "collection_scheduler.run_started",
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
                "collection_scheduler.run_failed",
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
                    "collection_scheduler.callback_failed",
                    source_id=source_id,
                    error=str(e),
                )

        # 持久化回调会填充 items_duplicate，故在回调之后上报去重指标
        COLLECTION_DUPLICATES.labels(source_id=source_id).inc(result.items_duplicate or 0)

        # Check quality metrics after each run
        try:
            self.metrics.check_alerts(window_hours=24)
        except Exception as e:
            self._logger.error("collection_scheduler.metrics_alert_failed", error=str(e))

        self._logger.info(
            "collection_scheduler.run_completed",
            source_id=source_id,
            status=result.status,
            items=len(result.items),
        )

    async def trigger_now(self, source_id: str) -> Any:
        """手动立即触发一次采集。"""
        await self._run_collection(source_id)
        return {"source_id": source_id, "triggered_at": datetime.now(UTC).isoformat()}

    def get_jobs(self) -> list[dict[str, Any]]:
        """获取已注册任务列表。"""
        return [
            {
                "id": job.id,
                "name": job.name,
                "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None,
            }
            for job in self.scheduler.get_jobs()
        ]
