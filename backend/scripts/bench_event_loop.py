#!/usr/bin/env python3
"""事件循环阻塞基准。

衡量：在一个重请求（导出全部项目为 Excel）执行期间，并发的轻量 /health
请求的延迟。若重处理器占用事件循环，/health 会被完全挂起。

用法:
    python scripts/bench_event_loop.py [项目数]
"""

from __future__ import annotations

import asyncio
import os
import statistics
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_TMP = tempfile.mkdtemp(prefix="bench-")
os.environ["DB_PATH"] = os.path.join(_TMP, "bench.db")
os.environ["APP_ENV"] = "testing"

import httpx

from app.agents.base import AgentContext, PipelineState, RawProject
from app.db import get_connection, init_db
from app.main import create_app
from app.repository import ProjectRepository


def seed(n: int) -> None:
    init_db()
    conn = get_connection()
    repo = ProjectRepository(conn)
    for i in range(n):
        project = RawProject(
            id=f"bench-{i:05d}",
            name=f"BenchProject{i}",
            url=f"https://bench{i}.example",
            sector="L2",
            stage="testnet",
            source="seed",
        )
        state = PipelineState(project=project, context=AgentContext(run_id="bench"))
        state.score = 50 + (i % 50)
        state.label = "FARM" if state.score >= 65 else "WATCH"
        state.confidence = 0.7
        state.reason = ["bench reason a", "bench reason b"]
        repo.save(state)
    conn.close()


async def main(n: int) -> None:
    seed(n)
    app = create_app()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://bench", timeout=120) as client:
        # 预热
        await client.get("/health")
        await client.get("/api/v1/export/projects?format=excel")

        health_latencies: list[float] = []
        stop = asyncio.Event()

        async def poll_health() -> None:
            while not stop.is_set():
                t0 = time.perf_counter()
                await client.get("/health")
                health_latencies.append((time.perf_counter() - t0) * 1000)
                await asyncio.sleep(0.005)

        poller = asyncio.create_task(poll_health())
        await asyncio.sleep(0.05)  # 让轮询先跑起来

        t0 = time.perf_counter()
        resp = await client.get("/api/v1/export/projects?format=excel")
        heavy_ms = (time.perf_counter() - t0) * 1000
        assert resp.status_code == 200, resp.status_code

        stop.set()
        await poller

    ordered = sorted(health_latencies)
    p50 = statistics.median(ordered)
    p99 = ordered[int(len(ordered) * 0.99) - 1] if len(ordered) > 1 else ordered[0]
    print(f"projects              : {n}")
    print(f"heavy export          : {heavy_ms:8.1f} ms")
    print(f"/health samples       : {len(ordered)}")
    print(f"/health p50           : {p50:8.1f} ms")
    print(f"/health p99           : {p99:8.1f} ms")
    print(f"/health max           : {ordered[-1]:8.1f} ms   <-- 事件循环被阻塞的时长")


if __name__ == "__main__":
    asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 2000))
