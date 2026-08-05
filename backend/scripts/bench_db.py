#!/usr/bin/env python3
"""数据库热路径基准。

覆盖三条路径：
1. save_batch  —— 批量保存是否复用连接
2. persist_collection_result —— 去重查找是 N 次单行 SELECT 还是分块批查
3. /insights 聚合 —— 是否把全表大 JSON 搬进 Python

用法:
    python scripts/bench_db.py [规模]
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_TMP = tempfile.mkdtemp(prefix="benchdb-")
os.environ["DB_PATH"] = os.path.join(_TMP, "bench.db")
os.environ["APP_ENV"] = "testing"

from datetime import UTC, datetime

from app.agents.base import AgentContext, PipelineState, RawProject
from app.collectors.base import CollectorResult, RawDiscovery
from app.collectors.persistence import CollectionRepository
from app.db import init_db
from app.repository import ProjectRepository


def make_states(n: int) -> list[PipelineState]:
    states = []
    for i in range(n):
        project = RawProject(
            id=f"bench-{i:05d}",
            name=f"BenchProject{i}",
            url=f"https://bench{i}.example",
            sector="L2" if i % 2 else "DeFi",
            stage="testnet",
            source="seed",
        )
        state = PipelineState(project=project, context=AgentContext(run_id="bench"))
        state.score = 50 + (i % 50)
        state.label = "FARM" if state.score >= 65 else "WATCH"
        state.confidence = 0.7
        state.reason = ["bench reason a", "bench reason b"]
        states.append(state)
    return states


def make_result(n: int) -> CollectorResult:
    result = CollectorResult(source_id="benchsource")
    result.started_at = datetime.now(UTC)
    result.items = [
        RawDiscovery(
            source_id="benchsource",
            raw_id=f"raw-{i}",
            name=f"Disco{i}",
            url=f"https://d{i}.example",
            sector="L2",
            stage="testnet",
            raw_data={"k": "v"},
            raw_signals=[],
            discovery_score=0.5,
            discovered_at=datetime.now(UTC),
        )
        for i in range(n)
    ]
    result.finished_at = datetime.now(UTC)
    return result


def main(n: int) -> None:
    init_db()

    t0 = time.perf_counter()
    saved = ProjectRepository().save_batch(make_states(n))
    save_ms = (time.perf_counter() - t0) * 1000
    print(f"save_batch({n})            : {save_ms:8.1f} ms   ({saved} saved)")

    repo = CollectionRepository()
    result = make_result(n)
    repo.persist_collection_result(result, source_name="bench")  # 首轮：全新插入
    t0 = time.perf_counter()
    repo.persist_collection_result(make_result(n), source_name="bench")  # 二轮：全部命中去重
    persist_ms = (time.perf_counter() - t0) * 1000
    print(f"persist_collection({n})    : {persist_ms:8.1f} ms   (全部走去重查找)")

    import asyncio
    import inspect

    from app.routers.v1.insights import get_insights

    def call_insights():
        out = get_insights()
        # 兼容基线代码（彼时该处理器为 async def）
        return asyncio.run(out) if inspect.iscoroutine(out) else out

    call_insights()  # 预热
    t0 = time.perf_counter()
    resp = call_insights()
    insights_ms = (time.perf_counter() - t0) * 1000
    print(f"/insights 聚合             : {insights_ms:8.1f} ms   (total={resp.data['total_projects']})")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 1000)
