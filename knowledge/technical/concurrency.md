# 并发控制知识

> 引用键：`KN:technical:concurrency`
> 来源：`docs/ENGINEERING_ROADMAP.md §7.5`、`docs/adr/ADR-007-multi-project-concurrency.md`
> 更新：2026-07-08

## 概述

系统采用三级并发模型，平衡性能与资源消耗。

## 三级并发模型

### Level 1: 多项目并行
- **控制机制**：`asyncio.Semaphore(max_concurrent_projects)`
- **默认值**：10
- **配置**：`MAX_CONCURRENT_PROJECTS`
- **说明**：同时分析的最大项目数

### Level 2: Agent 并行
- **控制机制**：`asyncio.gather`
- **说明**：单项目内 4 个分析 Agent 并行执行
- **无依赖**：Narrative/Team/Risk/Tokenomics 互不依赖

### Level 3: 子调用并发
- **控制机制**：`asyncio.Semaphore(llm_semaphore_size)`
- **默认值**：5
- **配置**：`LLM_SEMAPHORE_SIZE`
- **说明**：LLM API 调用的并发上限

## 事务边界

- **Analyze 阶段**：不开事务（防长事务锁表）
- **Write 阶段**：`BEGIN/COMMIT` 包裹 upsert
- **Logs 写入**：允许孤立行，不参与事务

## SQLite 并发

- WAL 模式：读写不阻塞
- 单写者：通过 `threading.Lock` 串行化写入
- 连接池：每个协程独立连接

## 相关引用

- [KN:technical:agent-pipeline] — 流水线阶段
- [KN:decision:ADR-007] — 并发模型决策
