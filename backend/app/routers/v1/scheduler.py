"""调度器任务表（只读诊断端点）。

## 为什么加这个端点

`UnifiedScheduler.get_jobs()` 一直存在，返回每个已注册任务的
`next_run_time` —— 但**没有任何路由暴露它**，所以运维台看不到任务表。

这不是"少个页面"的问题。归档功能从上线到 2026-08-24 **一次都没被触发过**，
而这件事是靠翻数据库（`archive_runs` 表 0 行）才发现的。
如果当时有这张任务表，"`archive_cleanup` 根本不在列表里"一眼就能看出来。

**一个看不见调度状态的运维台，会把"任务没注册"表现成"功能好像不太对"。**

## 这个端点最容易犯的错：把三种原因压成一个空数组

「任务表是空的」在本项目里有三种完全不同的原因，处置动作各不相同：

| 原因 | `scheduler_state` | 该怎么办 |
|---|---|---|
| 测试环境，压根没构造调度器 | `not_initialized` | 正常，无需处理 |
| 三个开关全关 | `disabled` | 检查 `.env`，是不是不该全关 |
| 开关开了但注册出错 | `running` 且 `jobs` 为空 | **真故障**，查启动日志 |

如果只返回 `{"jobs": []}`，这三种会长得一模一样 ——
而第三种是生产事故，前两种是正常配置。
所以响应里必须带 `scheduler_state`，且**读不出来时不能装作是空**。

这一条是本项目反复出现的同一个教训：
**静默的错误状态比明确的空状态坏得多。**
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.config import settings

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["scheduler"])


class SchedulerJobsResponse(BaseModel):
    ok: bool = True
    data: dict = Field(default_factory=dict)


# 任务 id → 它由哪个开关控制。运维看到"任务不在表里"时，
# 下一个问题必然是"那我该去开哪个开关"—— 直接把答案放进响应里，
# 而不是让人回去翻文档。
#
# ⚠️ 这些 id 必须与 `app/scheduler.py` 里 `add_job(id=...)` 的字面量一致。
# 我第一版凭印象写成 `daily_analysis`，真实是 **`analysis_run_queue`**
# （`scheduler.py:246`）。17 个用 MagicMock 的测试全绿 —— 因为替身
# 返回的正是我编的那个 id。**替身会照着我的误解回答我。**
# 下面 `TestJobIdsMatchTheScheduler` 那组测试就是为此加的：
# 直接从 scheduler.py 源码里抽 id，不再靠记性。
_JOB_OWNER: dict[str, str] = {
    "analysis_run_queue": "SCHEDULER_ENABLED",
    "archive_cleanup": "ARCHIVE_SCHEDULER_ENABLED",
}
_COLLECTION_SWITCH = "COLLECTION_SCHEDULER_ENABLED"


def _owner_switch(job_id: str) -> str:
    """这个 job 由哪个环境变量控制。"""
    if job_id in _JOB_OWNER:
        return _JOB_OWNER[job_id]
    # 采集 job 的 id 形如 `collect_defillama`
    if job_id.startswith("collect_"):
        return _COLLECTION_SWITCH
    return "unknown"


def _expected_jobs(request: Request) -> dict[str, str]:
    """按当前配置**应当**注册的任务 → 控制它的开关。

    有了"应当"才能算出"缺了谁"。只列出实际注册的任务时，
    缺失是看不见的 —— 而缺失恰恰是归档那次事故的形态。

    ## 采集任务的"应当"不能只看总开关

    ⚠️ 第一版这里犯了错，实测才发现：只要 `COLLECTION_SCHEDULER_ENABLED`
    为真，就把 10 个采集源全列进"应当注册"。但 `scheduler.py:121` 的真实
    条件是 `if collector and collector.is_enabled()` ——
    **没配 API key 的源根本不会注册，而那是正常的**。

    结果是本机实测报出 6 个假缺失（galxe / layer3 / rootdata /
    twitter_kol / twitter_keyword，外加一个我把 id 写错的分析任务）。

    这个方向的错比漏报更坏：**一栏天天亮红灯的告警，等于没有这一栏。**
    人会先学会忽略它，然后在真出事那天照样忽略。

    所以采集源的"应当"要问 registry 要 —— 与调度器注册时用的是同一个判据。
    """
    expected: dict[str, str] = {}
    if settings.scheduler_enabled:
        expected["analysis_run_queue"] = "SCHEDULER_ENABLED"
    if settings.archive_scheduler_enabled:
        expected["archive_cleanup"] = "ARCHIVE_SCHEDULER_ENABLED"

    if settings.collection_scheduler_enabled:
        registry = getattr(request.app.state, "collector_registry", None)
        if registry is not None:
            try:
                # 与 scheduler.py 注册采集 job 时同一个判据：已启用的采集器
                for collector in registry.list_enabled():
                    source_id = getattr(collector, "source_id", None)
                    if source_id:
                        expected[f"collect_{source_id}"] = _COLLECTION_SWITCH
            except Exception as exc:
                # 问不出来就不猜。宁可少报一个缺失，也不要报一堆不存在的缺失。
                logger.warning("scheduler.jobs.registry_probe_failed", error=str(exc)[:200])
    return expected


@router.get(
    "/scheduler/jobs",
    response_model=SchedulerJobsResponse,
    summary="调度器任务表（只读）",
    description=(
        "当前已注册的定时任务及各自的下次运行时间，外加三个调度开关的真实值、"
        "以及**按配置应当注册却没注册**的任务清单。\n\n"
        "只读端点，不触发任何任务。手动触发归档请用 `scripts/archive_raw_data.py`。"
    ),
)
def get_scheduler_jobs(request: Request) -> SchedulerJobsResponse:
    """返回调度器任务表 + 开关状态 + 缺失任务。"""
    scheduler = getattr(request.app.state, "unified_scheduler", None)

    switches = {
        "SCHEDULER_ENABLED": settings.scheduler_enabled,
        "COLLECTION_SCHEDULER_ENABLED": settings.collection_scheduler_enabled,
        "ARCHIVE_SCHEDULER_ENABLED": settings.archive_scheduler_enabled,
        "COLLECTION_AUTO_RUN_ENABLED": settings.collection_auto_run_enabled,
    }
    expected = _expected_jobs(request)

    # ── 三种"空"必须分得开，见模块 docstring ──
    if scheduler is None:
        # app.state 上没有调度器对象。生产不该出现（只有 app_env == "testing" 会）。
        return SchedulerJobsResponse(
            data={
                "scheduler_state": "not_initialized",
                "running": False,
                "timezone": settings.timezone,
                "jobs": [],
                "job_count": 0,
                "expected_job_count": len(expected),
                "missing_jobs": sorted(expected),
                "switches": switches,
                "read_error": None,
                "note": (
                    "调度器对象不存在（app_env == 'testing' 时如此）。"
                    "生产环境看到这个值意味着启动流程没走到调度器构造那一步，请查启动日志。"
                ),
            }
        )

    jobs: list[dict[str, Any]] = []
    read_error: str | None = None
    running = False
    try:
        running = bool(scheduler.scheduler.running)
        jobs = scheduler.get_jobs()
    except Exception as exc:
        # 读不出来 ≠ 没有任务。绝不返回空数组假装成"一个任务都没注册"——
        # 那会让一个坏掉的诊断接口看起来像一个空闲的调度器。
        read_error = str(exc)[:200]
        logger.warning("scheduler.jobs.read_failed", error=read_error)

    for job in jobs:
        job["owner_switch"] = _owner_switch(job.get("id", ""))

    if read_error is not None:
        state = "read_error"
    elif running:
        state = "running"
    else:
        state = "disabled"

    registered = {job.get("id") for job in jobs}
    missing = sorted(job_id for job_id in expected if job_id not in registered)

    return SchedulerJobsResponse(
        data={
            "scheduler_state": state,
            "running": running,
            "timezone": settings.timezone,
            "jobs": sorted(jobs, key=lambda j: str(j.get("next_run_time") or "9999")),
            # job_count 在 read_error 时是 None 而不是 0 —— 见上面那段注释。
            "job_count": None if read_error else len(jobs),
            "expected_job_count": len(expected),
            "missing_jobs": None if read_error else missing,
            "switches": switches,
            "read_error": read_error,
            "note": None,
        }
    )
