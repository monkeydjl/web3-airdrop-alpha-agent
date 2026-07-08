# Agent 流水线技术知识

> 引用键：`KN:technical:agent-pipeline`
> 来源：`docs/ENGINEERING_ROADMAP.md §6`
> 更新：2026-07-08

## 概述

Agent 流水线是系统的核心执行引擎，负责协调多个 Agent 完成项目分析。

## 流水线阶段

```
Collect → Dedup → Analyze → Score → Write
```

### 1. Collect（采集）
- **Agent**：Collector Agent
- **输入**：数据源配置
- **输出**：原始项目列表（RawProject）
- **职责**：从外部源获取项目数据

### 2. Dedup（去重）
- **Agent**：Orchestrator（内置逻辑）
- **输入**：RawProject
- **输出**：去重后的项目 + 操作类型（new/updated/skip）
- **职责**：基于 raw_signals_hash 判断项目是否已存在

### 3. Analyze（分析）
- **Agents**：Narrative / Team / Risk / Tokenomics（并行）
- **输入**：RawProject + AgentContext
- **输出**：各 Agent 的结构化结果
- **职责**：多维度分析项目

### 4. Score（评分）
- **Agent**：Scorer
- **输入**：4 个 Agent 的输出
- **输出**：ScoreResult（score/label/confidence/reason）
- **职责**：汇总子项分数，生成最终评分

### 5. Write（写入）
- **Agent**：Orchestrator（内置逻辑）
- **输入**：ScoreResult
- **输出**：DB 写入 + 日志记录
- **职责**：持久化结果

## 并发模型（ADR-007）

```
Level 1: 项目级并行（Semaphore 控制）
Level 2: Agent 级并行（asyncio.gather）
Level 3: 子调用并发（LLM/API 调用）
```

## 错误处理

- Agent 失败 → 记录 AgentError → 继续其他 Agent
- 所有 Agent 失败 → 标记项目为 failed
- DB 写入失败 → 重试 3 次 → 记录错误

## 相关引用

- [KN:business:scoring] — 评分逻辑
- [KN:technical:concurrency] — 并发控制细节
- [KN:decision:ADR-002] — 自研 Orchestrator 决策
