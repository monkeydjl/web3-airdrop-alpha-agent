# Agent 编排器实现骨架

> 自研轻量级 Agent 编排器（对齐 LangGraph 接口风格）  
> 引用：ADR-002  
> 更新：2026-07-08

---

## 架构设计

```python
# backend/app/agents/orchestrator.py
"""
Agent 编排器 - 核心实现

设计原则：
1. DAG 执行流
2. 类型安全（Pydantic）
3. 可观测（日志 + 指标）
4. 错误隔离
5. 并发控制
"""

from __future__ import annotations

import asyncio
import time
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set
from uuid import uuid4

from pydantic import BaseModel, Field
import structlog

logger = structlog.get_logger()


class AgentStatus(str, Enum):
    """Agent 执行状态"""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class AgentNode(BaseModel):
    """Agent 节点定义"""

    id: str
    name: str
    agent_fn: Any  # Callable，Pydantic 不序列化
    input_keys: List[str] = Field(default_factory=list)
    output_key: str
    retry: int = 0
    timeout: Optional[float] = None
    depends_on: List[str] = Field(default_factory=list)


class AgentResult(BaseModel):
    """Agent 执行结果"""

    node_id: str
    status: AgentStatus
    output: Optional[Any] = None
    error: Optional[str] = None
    duration_ms: float
    timestamp: float


class PipelineContext(BaseModel):
    """Pipeline 上下文"""

    run_id: str = Field(default_factory=lambda: str(uuid4()))
    data: Dict[str, Any] = Field(default_factory=dict)
    results: Dict[str, AgentResult] = Field(default_factory=dict)

    class Config:
        arbitrary_types_allowed = True


class Orchestrator:
    """Agent 编排器"""

    def __init__(self):
        self.nodes: Dict[str, AgentNode] = {}
        self.graph: Dict[str, Set[str]] = {}  # 依赖图

    def add_node(
        self,
        node_id: str,
        name: str,
        agent_fn: Callable,
        input_keys: List[str],
        output_key: str,
        depends_on: Optional[List[str]] = None,
        retry: int = 0,
        timeout: Optional[float] = None,
    ) -> Orchestrator:
        """添加 Agent 节点"""
        node = AgentNode(
            id=node_id,
            name=name,
            agent_fn=agent_fn,
            input_keys=input_keys,
            output_key=output_key,
            depends_on=depends_on or [],
            retry=retry,
            timeout=timeout,
        )

        self.nodes[node_id] = node
        self.graph[node_id] = set(depends_on or [])

        logger.info(
            "orchestrator.node_added",
            node_id=node_id,
            name=name,
            depends_on=depends_on,
        )

        return self

    def _topological_sort(self) -> List[str]:
        """拓扑排序"""
        in_degree = {node_id: len(deps) for node_id, deps in self.graph.items()}
        queue = [node_id for node_id, deg in in_degree.items() if deg == 0]
        result = []

        while queue:
            node_id = queue.pop(0)
            result.append(node_id)

            # 更新依赖此节点的其他节点
            for other_id, deps in self.graph.items():
                if node_id in deps:
                    in_degree[other_id] -= 1
                    if in_degree[other_id] == 0:
                        queue.append(other_id)

        if len(result) != len(self.nodes):
            raise ValueError("检测到循环依赖")

        return result

    async def _execute_node(
        self,
        node: AgentNode,
        context: PipelineContext,
    ) -> AgentResult:
        """执行单个 Agent 节点"""
        start_time = time.time()

        logger.info(
            "orchestrator.node_start",
            run_id=context.run_id,
            node_id=node.id,
            name=node.name,
        )

        try:
            # 准备输入
            input_data = {key: context.data[key] for key in node.input_keys}

            # 执行 Agent
            if asyncio.iscoroutinefunction(node.agent_fn):
                output = await asyncio.wait_for(
                    node.agent_fn(**input_data),
                    timeout=node.timeout,
                )
            else:
                output = node.agent_fn(**input_data)

            # 存储输出
            context.data[node.output_key] = output

            duration_ms = (time.time() - start_time) * 1000

            result = AgentResult(
                node_id=node.id,
                status=AgentStatus.SUCCESS,
                output=output,
                duration_ms=duration_ms,
                timestamp=time.time(),
            )

            logger.info(
                "orchestrator.node_success",
                run_id=context.run_id,
                node_id=node.id,
                duration_ms=duration_ms,
            )

            return result

        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000

            logger.error(
                "orchestrator.node_failed",
                run_id=context.run_id,
                node_id=node.id,
                error=str(e),
                duration_ms=duration_ms,
            )

            return AgentResult(
                node_id=node.id,
                status=AgentStatus.FAILED,
                error=str(e),
                duration_ms=duration_ms,
                timestamp=time.time(),
            )

    async def run(
        self,
        initial_data: Dict[str, Any],
        max_concurrency: int = 3,
    ) -> PipelineContext:
        """执行 Pipeline"""
        context = PipelineContext(data=initial_data)

        logger.info(
            "orchestrator.pipeline_start",
            run_id=context.run_id,
            nodes_count=len(self.nodes),
        )

        # 拓扑排序
        execution_order = self._topological_sort()

        # 按依赖层级分组（支持并发）
        levels: List[List[str]] = []
        executed: Set[str] = set()

        while executed != set(execution_order):
            current_level = []
            for node_id in execution_order:
                if node_id not in executed:
                    deps = self.graph[node_id]
                    if deps.issubset(executed):
                        current_level.append(node_id)

            if current_level:
                levels.append(current_level)
                executed.update(current_level)
            else:
                break

        # 逐层执行
        for level_idx, level_nodes in enumerate(levels):
            logger.info(
                "orchestrator.level_start",
                run_id=context.run_id,
                level=level_idx,
                nodes=level_nodes,
            )

            # 并发执行同层节点
            tasks = [self._execute_node(self.nodes[node_id], context) for node_id in level_nodes]

            results = await asyncio.gather(*tasks, return_exceptions=False)

            # 记录结果
            for result in results:
                context.results[result.node_id] = result

                # 失败则中断
                if result.status == AgentStatus.FAILED:
                    logger.error(
                        "orchestrator.pipeline_aborted",
                        run_id=context.run_id,
                        failed_node=result.node_id,
                    )
                    return context

        logger.info(
            "orchestrator.pipeline_success",
            run_id=context.run_id,
            total_nodes=len(execution_order),
        )

        return context


# 便捷构造器
def create_pipeline() -> Orchestrator:
    """创建新 Pipeline"""
    return Orchestrator()
```

---

## 使用示例

```python
# backend/app/agents/example_pipeline.py
"""
示例 Pipeline：项目评分流程
"""

from backend.app.agents.orchestrator import create_pipeline


async def collect_data(project_id: str) -> dict:
    """采集数据"""
    # 模拟数据采集
    return {
        "twitter_followers": 10000,
        "github_stars": 500,
    }


async def score_project(raw_data: dict) -> dict:
    """计算评分"""
    # 模拟评分
    score = (raw_data["twitter_followers"] / 1000) * 0.3 + (raw_data["github_stars"] / 100) * 0.7
    return {"total_score": score}


async def generate_reason(raw_data: dict, score_data: dict) -> str:
    """生成 reason"""
    return f"基于 {score_data['total_score']} 分的评估..."


async def run_scoring_pipeline(project_id: str):
    """运行评分 Pipeline"""

    pipeline = create_pipeline()

    # 添加节点
    pipeline.add_node(
        node_id="collect",
        name="数据采集",
        agent_fn=collect_data,
        input_keys=["project_id"],
        output_key="raw_data",
    )

    pipeline.add_node(
        node_id="score",
        name="评分计算",
        agent_fn=score_project,
        input_keys=["raw_data"],
        output_key="score_data",
        depends_on=["collect"],
    )

    pipeline.add_node(
        node_id="reason",
        name="Reason 生成",
        agent_fn=generate_reason,
        input_keys=["raw_data", "score_data"],
        output_key="reason",
        depends_on=["collect", "score"],
    )

    # 执行
    result = await pipeline.run(
        initial_data={"project_id": project_id},
        max_concurrency=2,
    )

    return result


# 测试
if __name__ == "__main__":
    import asyncio

    async def main():
        result = await run_scoring_pipeline("test-project-123")
        print(f"Run ID: {result.run_id}")
        print(f"Final Reason: {result.data.get('reason')}")

        for node_id, node_result in result.results.items():
            print(f"{node_id}: {node_result.status} ({node_result.duration_ms:.0f}ms)")

    asyncio.run(main())
```

---

## 测试

```python
# tests/unit/agents/test_orchestrator.py
"""
Orchestrator 单元测试
"""

import pytest
from backend.app.agents.orchestrator import create_pipeline, AgentStatus


async def mock_agent_a(x: int) -> int:
    return x + 1


async def mock_agent_b(a_result: int) -> int:
    return a_result * 2


async def mock_agent_c(b_result: int) -> int:
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
```

---

## 后续扩展

### V2 功能

1. **重试机制**
   ```python
   pipeline.add_node(
       ...,
       retry=3,
       retry_delay=1.0,
   )
   ```

2. **条件分支**
   ```python
   pipeline.add_conditional_node(
       node_id="check",
       condition_fn=lambda ctx: ctx.data["score"] > 80,
       true_branch="high_score_flow",
       false_branch="low_score_flow",
   )
   ```

3. **人工介入**
   ```python
   pipeline.add_human_approval_node(
       node_id="approve",
       approval_fn=send_approval_request,
   )
   ```

4. **持久化**
   ```python
   # 保存 Pipeline 状态到数据库
   await pipeline.checkpoint(context)
   
   # 从断点恢复
   context = await pipeline.resume(run_id)
   ```

---

_文档版本：v1.0 · 2026-07-08_
