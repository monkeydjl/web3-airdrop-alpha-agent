"""进程内在飞守卫（in-flight guard）。

## 为什么需要

两类重复触发原先都无任何防护：

1. **手动采集** `POST /collections/{source_id}/trigger` 无幂等、无运行锁。重复
   POST（前端连点、客户端重试）会各自发出真实出站 `collect()`、各自 persist。
   出站限流器（`collectors/rate_limiter.py`）只约束请求**速率**，不阻止入站
   重复触发。
2. **全量重评分** `execute_analysis_pipeline` 不带 projects 时会排空
   `raw_projects` 未处理队列——这是全流程最昂贵的一步。它有四个入口：analysis
   cron、collection scheduler 回调（`main.py`）、trigger 端点的 auto-run、
   `POST /run` 空 body。APScheduler 的 `max_instances=1` 只约束**单个 job**，
   而 10 个采集源各有独立 job，两个源同时完成即触发两次并发排空；且它对另外
   三个入口完全无效。

并发排空的后果不只是浪费算力：两次运行会取到重叠的未处理项目
（`mark_raw_project_processed` 要等评分结束才写 processed=1），于是同一项目被
重复评分、重复写 `projects`，并各自跑一次 opportunity shadow 评估。

## 设计取舍

守卫放在**队列排空这一层**（`pipeline_run`）而不是各调用点，四个入口因此共享
同一个不变量：进程内最多一次排空在飞。采集守卫按 `source_id` 分键——不同源
并行采集是合理的，只有同源重入才需要挡。

用 `threading.Lock` 而不是 `asyncio.Lock`：临界区只做"查表+登记"，纯同步无
await；而 `asyncio.Lock` 首次 acquire 时惰性绑定事件循环，模块级单例跨多个
事件循环（每个 `TestClient` 一个）复用会抛 "bound to a different event loop"。
与 `collectors/factory.py` 的取舍一致。

守卫是**进程级**的：单进程 uvicorn（当前部署形态）下完备。多 worker 部署需换
成 DB 层面的租约——`data_sources.sync_status` 当前不能充当此角色，它是事后状态
（采集完成后才写 `result.status`，全仓无处写 `running`），且其 UPDATE 无 upsert，
行缺失时静默 no-op。
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager

#: 队列排空的守卫键。全量重评分共享同一条 `raw_projects` 队列，不按触发源分键。
QUEUE_DRAIN_KEY = "analysis:queue_drain"


class QueueDrainInProgressError(RuntimeError):
    """已有一次队列排空在飞，本次触发被拒。

    刻意用异常而非"返回一个 status=skipped 的结果"：跳过是**没有运行**，
    伪造一份运行结果会污染调用方的统计与响应体。四个入口各自决定语义——
    HTTP 端点映射 409，调度器记一行 info（不是失败，无需补记账）。
    """


_active: set[str] = set()
_lock = threading.Lock()


def collect_key(source_id: str) -> str:
    """单个数据源的采集守卫键。"""
    return f"collect:{source_id}"


@contextmanager
def claim_run(key: str) -> Iterator[bool]:
    """尝试登记一次运行，yield 是否抢到。

    抢到的一方退出时释放；没抢到的一方**不释放**（否则会误放别人的登记）。
    """
    acquired = False
    with _lock:
        if key not in _active:
            _active.add(key)
            acquired = True
    try:
        yield acquired
    finally:
        if acquired:
            with _lock:
                _active.discard(key)


def active_runs() -> frozenset[str]:
    """当前在飞的键快照（诊断/测试用）。"""
    with _lock:
        return frozenset(_active)


def reset_active_runs() -> None:
    """清空登记（仅测试用：避免用例间互相污染）。"""
    with _lock:
        _active.clear()
