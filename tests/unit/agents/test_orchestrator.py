"""
Orchestrator 单元测试
"""

import pytest
from backend.app.agents.orchestrator import create_pipeline, AgentStatus


async def mock_agent_a(x: int) -> int:
    """测试 Agent A"""
    return x + 1


async def mock_agent_b(a_result: int) -> int:
    """测试 Agent B"""
    return a_result * 2


async def mock_agent_c(b_result: int) -> int:
    """测试 Agent C"""
    return b_result + 10


@pytest.mark.asyncio
async def test_linear_pipeline():
    """测试线性 Pipeline"""
    pipeline = create_pipeline()

    pipeline.add_node(
        node_id="a",
        name="Agent A",
        agent_fn=mock_agent_a,
        input_keys=["x"],
        output_key="a_result",
    )

    pipeline.add_node(
        node_id="b",
        name="Agent B",
        agent_fn=mock_agent_b,
        input_keys=["a_result"],
        output_key="b_result",
        depends_on=["a"],
    )

    pipeline.add_node(
        node_id="c",
        name="Agent C",
        agent_fn=mock_agent_c,
        input_keys=["b_result"],
        output_key="c_result",
        depends_on=["b"],
    )

    result = await pipeline.run(initial_data={"x": 5})

    assert result.data["a_result"] == 6
    assert result.data["b_result"] == 12
    assert result.data["c_result"] == 22

    assert all(r.status == AgentStatus.SUCCESS for r in result.results.values())


@pytest.mark.asyncio
async def test_parallel_execution():
    """测试并行执行"""

    async def slow_agent(x: int) -> int:
        import asyncio

        await asyncio.sleep(0.1)
        return x + 1

    pipeline = create_pipeline()

    # 两个独立的慢速 Agent
    pipeline.add_node(
        node_id="slow1",
        name="Slow Agent 1",
        agent_fn=slow_agent,
        input_keys=["x"],
        output_key="result1",
    )

    pipeline.add_node(
        node_id="slow2",
        name="Slow Agent 2",
        agent_fn=slow_agent,
        input_keys=["x"],
        output_key="result2",
    )

    import time

    start = time.time()
    result = await pipeline.run(initial_data={"x": 5})
    duration = time.time() - start

    # 并行执行应该 < 0.15s（而不是 0.2s）
    assert duration < 0.15
    assert result.data["result1"] == 6
    assert result.data["result2"] == 6


@pytest.mark.asyncio
async def test_error_handling():
    """测试错误处理"""

    async def failing_agent(x: int) -> int:
        raise ValueError("故意失败")

    pipeline = create_pipeline()

    pipeline.add_node(
        node_id="fail",
        name="Failing Agent",
        agent_fn=failing_agent,
        input_keys=["x"],
        output_key="result",
    )

    result = await pipeline.run(initial_data={"x": 5})

    assert result.results["fail"].status == AgentStatus.FAILED
    assert "故意失败" in result.results["fail"].error


@pytest.mark.asyncio
async def test_diamond_dependency():
    """测试菱形依赖图"""

    async def agent_root(x: int) -> int:
        return x

    async def agent_left(root: int) -> int:
        return root + 10

    async def agent_right(root: int) -> int:
        return root * 2

    async def agent_merge(left: int, right: int) -> int:
        return left + right

    pipeline = create_pipeline()

    pipeline.add_node(
        node_id="root",
        name="Root",
        agent_fn=agent_root,
        input_keys=["x"],
        output_key="root",
    )

    pipeline.add_node(
        node_id="left",
        name="Left",
        agent_fn=agent_left,
        input_keys=["root"],
        output_key="left",
        depends_on=["root"],
    )

    pipeline.add_node(
        node_id="right",
        name="Right",
        agent_fn=agent_right,
        input_keys=["root"],
        output_key="right",
        depends_on=["root"],
    )

    pipeline.add_node(
        node_id="merge",
        name="Merge",
        agent_fn=agent_merge,
        input_keys=["left", "right"],
        output_key="final",
        depends_on=["left", "right"],
    )

    result = await pipeline.run(initial_data={"x": 5})

    assert result.data["root"] == 5
    assert result.data["left"] == 15  # 5 + 10
    assert result.data["right"] == 10  # 5 * 2
    assert result.data["final"] == 25  # 15 + 10


@pytest.mark.asyncio
async def test_circular_dependency_detection():
    """测试循环依赖检测"""
    pipeline = create_pipeline()

    pipeline.add_node(
        node_id="a",
        name="A",
        agent_fn=mock_agent_a,
        input_keys=["x"],
        output_key="a_result",
        depends_on=["b"],  # A 依赖 B
    )

    pipeline.add_node(
        node_id="b",
        name="B",
        agent_fn=mock_agent_b,
        input_keys=["a_result"],
        output_key="b_result",
        depends_on=["a"],  # B 依赖 A (循环!)
    )

    with pytest.raises(ValueError, match="循环依赖"):
        await pipeline.run(initial_data={"x": 5})
