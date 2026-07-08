# 并发模型决策树

> 引用键：`KN:decision:ADR-007`
> 来源：`docs/adr/ADR-007-multi-project-concurrency.md`
> 更新：2026-07-08

## 决策树

```
需要并发执行？
├── 是多个项目？
│   ├── YES → Level 1: Semaphore(max_concurrent_projects=10)
│   └── NO  → 单项目模式
├── 是多个 Agent？
│   ├── YES → Level 2: asyncio.gather (Narrative/Team/Risk/Tokenomics)
│   └── NO  → 单 Agent 模式
└── 是 LLM/API 调用？
    ├── YES → Level 3: Semaphore(llm_semaphore_size=5)
    └── NO  → 直接执行
```

## 配置参数

| 参数 | 默认值 | 环境变量 | 说明 |
| --- | --- | --- | --- |
| max_concurrent_projects | 10 | MAX_CONCURRENT_PROJECTS | 同时分析的最大项目数 |
| llm_semaphore_size | 5 | LLM_SEMAPHORE_SIZE | LLM 调用并发上限 |

## 相关 ADR

- ADR-002: 自研 Orchestrator（执行引擎）
- ADR-004: SQLite → PG（数据层并发）
- ADR-010: 竞争度缓存（缓存层并发）
