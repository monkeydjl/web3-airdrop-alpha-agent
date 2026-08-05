"""Analysis scheduler — drains unprocessed raw_projects on cron (ADR-012 dual schedule).

Reference: docs/COLLECTION_ANALYSIS_HANDOFF.md
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import settings
from app.inflight import QueueDrainInProgressError
from app.pipeline_run import execute_analysis_pipeline, record_pipeline_run

logger = structlog.get_logger(__name__)


class AnalysisScheduler:
    """Cron-driven analysis of the raw_projects queue."""

    def __init__(self) -> None:
        self.scheduler = AsyncIOScheduler(timezone=settings.timezone)
        self._logger = logger.bind(component="analysis_scheduler")

    def start(self) -> None:
        if not settings.scheduler_enabled:
            self._logger.info("analysis_scheduler.disabled")
            return

        self.scheduler.add_job(
            self._run_analysis,
            # 必须显式传 timezone：APScheduler 只在**它自己**构造 trigger 时注入
            # scheduler.timezone，对预先构造好的 CronTrigger 实例不生效。
            # 缺了它，TIMEZONE=Asia/Shanghai 会被静默忽略，任务按容器时钟触发。
            trigger=CronTrigger.from_crontab(settings.cron_expression, timezone=settings.timezone),
            id="analysis_run_queue",
            name="Analyze unprocessed raw_projects",
            replace_existing=True,
            # 默认 misfire_grace_time=1 秒：日更任务错过 1 秒就整天不跑，且不告警。
            # coalesce 保证补跑只跑一次，而不是把错过的多次触发一起堆上来。
            misfire_grace_time=settings.scheduler_misfire_grace_seconds,
            coalesce=True,
            max_instances=1,
        )
        self.scheduler.start()
        self._logger.info(
            "analysis_scheduler.started",
            cron=settings.cron_expression,
            timezone=settings.timezone,
            misfire_grace_seconds=settings.scheduler_misfire_grace_seconds,
        )

    def shutdown(self, wait: bool = True) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=wait)
            self._logger.info("analysis_scheduler.shutdown")

    async def _run_analysis(self) -> None:
        self._logger.info("analysis_scheduler.run_started")
        started = time.perf_counter()
        run_id = f"cron-run-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S-%f')}"
        try:
            result = await execute_analysis_pipeline(trigger="cron")
            self._logger.info(
                "analysis_scheduler.run_completed",
                project_count=result.get("project_count"),
                scored_count=result.get("scored_count"),
                persisted_count=result.get("persisted_count"),
                status=result.get("status"),
            )
        except QueueDrainInProgressError:
            # 不记 failed：上一次排空还没跑完（cron 周期短于单次运行耗时，或
            # 某个采集源的 auto-run 正在跑）。本次跳过，队列里的项目仍是
            # processed=0，下一次触发照样取到，不需要补记账。
            self._logger.info(
                "analysis_scheduler.run_skipped",
                reason="queue_drain_in_progress",
            )
        except Exception as e:
            self._logger.error("analysis_scheduler.run_failed", error=str(e), exc_info=True)
            # 抛异常时 execute_analysis_pipeline 来不及记账，这里补一条持久记录：
            # 否则一次崩溃的定时运行在 DB 和 metrics 里都不留痕迹。
            record_pipeline_run(
                run_id=run_id,
                trigger="cron",
                duration_ms=int((time.perf_counter() - started) * 1000),
                summary={"status": "failed"},
                error=str(e),
            )

    async def trigger_now(self) -> dict[str, Any]:
        return await execute_analysis_pipeline(trigger="manual")

    def get_jobs(self) -> list[dict[str, Any]]:
        return [
            {
                "id": job.id,
                "name": job.name,
                "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None,
            }
            for job in self.scheduler.get_jobs()
        ]
