"""Focused tests for the DAG orchestrator."""

import asyncio

import pytest

from app.agents.orchestrator import Orchestrator


@pytest.mark.asyncio
async def test_run_respects_max_concurrency() -> None:
    active = 0
    peak = 0
    lock = asyncio.Lock()

    async def agent() -> str:
        nonlocal active, peak
        async with lock:
            active += 1
            peak = max(peak, active)
        await asyncio.sleep(0.01)
        async with lock:
            active -= 1
        return "ok"

    orchestrator = Orchestrator()
    for index in range(4):
        orchestrator.add_node(
            node_id=f"node-{index}",
            name=f"Node {index}",
            agent_fn=agent,
            input_keys=[],
            output_key=f"output-{index}",
        )

    await orchestrator.run({}, max_concurrency=2)

    assert peak == 2
