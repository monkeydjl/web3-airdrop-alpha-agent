"""
Agent 编排器 - 核心实现

设计原则：
1. DAG 执行流
2. 类型安全（Pydantic）
3. 可观测（日志 + 指标）
4. 错误隔离
5. 并发控制

引用：ADR-002
"""

from __future__ import annotations

import asyncio
import inspect
import time
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field
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

    model_config = ConfigDict(arbitrary_types_allowed=True)

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

    model_config = ConfigDict(arbitrary_types_allowed=True)

    node_id: str
    status: AgentStatus
    output: Optional[Any] = None
    error: Optional[str] = None
    duration_ms: float
    timestamp: float


class PipelineContext(BaseModel):
    """Pipeline 上下文"""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    run_id: str = Field(default_factory=lambda: str(uuid4()))
    data: Dict[str, Any] = Field(default_factory=dict)
    results: Dict[str, AgentResult] = Field(default_factory=dict)


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
            if inspect.iscoroutinefunction(node.agent_fn):
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
            tasks = [
                self._execute_node(self.nodes[node_id], context)
                for node_id in level_nodes
            ]

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


def create_pipeline() -> Orchestrator:
    """创建新 Pipeline"""
    return Orchestrator()
