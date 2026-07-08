# ADR-002: 自研轻量 Orchestrator，对齐 LangGraph

- **Status**: Accepted
- **Date**: 2026-07-08
- **Deciders**: 架构

## 背景

Agent 编排需要：状态在 node 间流转、并行调度、错误捕获、日志留痕。
CrewAI / LangGraph 提供现成编排，但：
- 绑定框架抽象，迁移成本高
- MVP 7 个 agent 逻辑简单，框架过重
- 框架版本迭代快，可能被版本绑架

## 决策

**先自研轻量 Orchestrator**，接口对齐 LangGraph 概念：
- `PipelineState`：显式状态对象（state）
- 每个 Agent 是一个 node，签名 `node(state) -> partial state`
- Reducer 语义：`*_result` 字段 last-write-wins，`errors` 字段 list-extend
- 并行用 `asyncio.gather`，错误捕获不中断主流程

详见 Roadmap §6.1.1。

## 理由

| 备选 | 否决理由 |
| --- | --- |
| 直接上 LangGraph | MVP 过重；框架抽象与我们的 7-agent 流程不完全契合，反而要写适配 |
| 直接上 CrewAI | 偏向 role-based 协作，我们的流程是固定 pipeline，不需要 role 协商 |
| **自研对齐 LangGraph（本决策）** | < 200 行即可；保留无痛迁移路径；不被框架版本绑架 |

## 后果

- 需自实现并行调度、错误捕获、日志留痕（成本低，已有明确契约）。
- **接口契约（`PipelineState`/`AgentContext`）必须稳定**，否则迁移成本反增。任何字段变更需契约测试（§14.3）+ ADR。
- 迁移 LangGraph 时：state 字段 → `TypedDict`，reducer → `Annotated[list, add]`，node 签名不变。迁移成本主要是替换基类与调度器。
- V3 如需复杂条件分支/循环/人工审批节点，再评估切 LangGraph。
