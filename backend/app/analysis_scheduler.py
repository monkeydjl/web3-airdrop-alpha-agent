"""Analysis scheduler — drains unprocessed raw_projects on cron (ADR-012 dual schedule).

Reference: docs/COLLECTION_ANALYSIS_HANDOFF.md
"""

from __future__ import annotations

from typing import Any

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import settings
from app.pipeline_run import execute_analysis_pipeline

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
            trigger=CronTrigger.from_crontab(settings.cron_expression),
            id="analysis_run_queue",
            name="Analyze unprocessed raw_projects",
            replace_existing=True,
        )
        self.scheduler.start()
        self._logger.info(
            "analysis_scheduler.started",
            cron=settings.cron_expression,
        )

    def shutdown(self, wait: bool = True) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=wait)
            self._logger.info("analysis_scheduler.shutdown")

    async def _run_analysis(self) -> None:
        self._logger.info("analysis_scheduler.run_started")
        try:
            result = await execute_analysis_pipeline(trigger="cron")
            self._logger.info(
                "analysis_scheduler.run_completed",
                project_count=result.get("project_count"),
                scored_count=result.get("scored_count"),
                status=result.get("status"),
            )
        except Exception as e:
            self._logger.error("analysis_scheduler.run_failed", error=str(e), exc_info=True)

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
