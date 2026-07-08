# ADR-007: 多项目并发模型（三级并行 + Semaphore + 事务边界）

- **Status**: Accepted
- **Date**: 2026-07-08
- **Deciders**: 架构

## 背景

Collector 一次产出 N 个项目后，如何控制 pipeline 的并行度、保护资源、隔离错误、防止 OOM？

原有设计仅在 §6.8 简短提及"多项目之间可分批并发（V2）"、§23.3 提到"用 `asyncio.Semaphore` 限流 10"，缺乏完整的并发模型设计。具体缺失：

1. **三级并行层次未区分**：多项目间并发、单项目内 agent 并行、agent 内 I/O 并行混为一谈。
2. **并发控制参数未定义**：Semaphore 大小、超时、批大小等全为硬编码。
3. **OOM 保护缺失**：同时跑 N 个项目 × 4 agent 的内存压力无保护。
4. **LLM 并发控制与项目并发耦合**：10 个项目并发 → 40 并发 LLM 调用，打爆配额。
5. **错误隔离不完整**：一个项目 analyze 超时是否影响其他项目？
6. **事务边界未定义**：analyze 写 logs、Scorer 写 projects 之间的原子性无保证。

## 决策

### 1. 三级并行层次

| 层次 | 控制方式 | 聚焦 |
| --- | --- | --- |
| Level 1：多项目间 | `asyncio.Semaphore(max_concurrent_projects)` | **本节核心** |
| Level 2：单项目内 agent 间 | `asyncio.gather`（固定 4 agent） | 已有 §6.1.3 定义 |
| Level 3：Agent 内 I/O | `asyncio.gather`（fetcher 多源） | 已有 §10.1 定义 |

### 2. 并发策略按阶段演进

| 阶段 | 策略 |
| --- | --- |
| MVP | 串行（单项目逐个处理，无多项目并发） |
| V2 | `asyncio.Semaphore` 有限并发，可配置（默认 10） |
| V3 | Celery/RQ 分布式队列 |

### 3. LLM 独立 Semaphore

LLM 调用使用全局独立的 `llm_semaphore`（默认 5），与项目并发数解耦，防止多项目并行时打爆 LLM 配额。

### 4. 错误隔离

单项目异常被 `try/except` 捕获为 `AgentError` 写入 `PipelineState.errors`，**绝不**向外传播阻断其他项目。

### 5. 事务边界：最终一致性

- Collect→Analyze→Score：不开启 DB 事务（防止长事务锁）
- Write：`BEGIN/COMMIT` 事务写入 `projects` + `project_history`
- Logs 写入不参与事务，允许孤立行存在（业务可接受）
- 下轮 run 基于幂等性自动修复

### 6. 并发参数全部配置化

`ConcurrencyConfig` 含 8 项参数（`max_concurrent_projects`、`llm_semaphore_size`、`fetcher_semaphore_size`、`batch_size`、`project_timeout_seconds` 等），全可通过环境变量覆盖。

## 理由

| 备选 | 否决理由 |
| --- | --- |
| MVP 就用多项目并发 | 50 项目 × 1s = 50s < 60s 预算，串行足够；串行消除所有并发复杂度 |
| 用线程池（`ThreadPoolExecutor`） | asyncio 在 Python 3.11+ 更轻量（无 GIL 上下文切换开销），且 fetcher/LLM 均为 I/O bound |
| LLM 调用不隔离，随项目并发自然扩 | 10 项目 × 4 agent × 30% 采样 = 12 并发 LLM 调用，独立 Semaphore 可精确控制到 5 |
| 强事务（analyze+score+write 在同一事务） | SQLite 长事务锁表；V2 PG 也推荐短事务。logs 允许孤立行是故意设计 |
| 不配置化，代码硬编码 | 排期调优、A/B 测试并发参数时需要改代码重启，无法快速实验 |

## 后果

- **Config 模块新增**：`ConcurrencyConfig`（8 项参数），配置变更需评价联动影响（§6.9.10）。
- **新增 6 个 Prometheus 指标**：`airdrop_concurrency_*` 系列（§6.9.9）。
- **Orchestrator 实现变更**：MVP 串行循环 → V2 `asyncio.Semaphore` + `asyncio.gather`。
- **Transformer 阶段同步变更**：§23.3 性能预算与 §6.9 联动——50 项目串行仍 <60s，100+ 项目需 Semaphore。
- **TASK_BREAKDOWN 新增**：W2 增加 concurrency 章节实现任务；W4 增加并发参数冒烟测试。
- **事务边界的"最终一致性"** 需要监控告警：孤立 logs 行 >0 告警。
- **迁移 LangGraph 时**：`asyncio.Semaphore` 需替换为 LangGraph 的并行调度（如 `Send` API），但三级并发的设计思想不变。
