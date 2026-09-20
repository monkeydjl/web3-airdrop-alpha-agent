# Architecture Decision Records (ADR)

> 本目录记录 Web3 Airdrop Alpha Agent System 的架构决策。每份 ADR 独立成文，按序号递增，不删除历史。
>
> 格式：**背景 → 决策 → 理由 → 后果**。被推翻的决策标记 `Status: Superseded by ADR-0xx`，保留原文。
>
> 新增 ADR 请使用 [TEMPLATE.md](TEMPLATE.md) 创建。

## 索引

| ADR | 标题 | 状态 | 日期 | 一句话摘要 | 影响面 |
| --- | --- | --- | --- | --- | --- |
| [ADR-001](ADR-001-llm-default-off.md) | MVP 默认关闭 LLM，作为可选插件 | Accepted | 2026-07-08 | 规则引擎默认运行；LLM 仅在配置 API key 时启用，失败自动回退规则 | 核心评分、成本、可离线运行 |
| [ADR-002](ADR-002-self-built-orchestrator.md) | 自研轻量 Orchestrator，对齐 LangGraph | Accepted | 2026-07-08 | 自定义 `state/node/reducer` 三件套；保留未来迁移 LangGraph 的可能 | 架构、Agent 编排、可扩展性 |
| [ADR-003](ADR-003-single-page-html-mvp.md) | MVP 前端用单页 HTML | Accepted | 2026-07-08 | 零构建、开箱即用；V2 演进为 Next.js | 前端、构建流程、部署 |
| [ADR-004](ADR-004-sqlite-to-postgres.md) | 数据层 MVP 用 SQLite(WAL)，V2 切 PostgreSQL | Accepted | 2026-07-08 | 零运维启动；满足 4 个触发条件后迁移到 PG | 数据库、部署、容量 |
| [ADR-005](ADR-005-apscheduler-inprocess.md) | 调度用 APScheduler 进程内 | Accepted | 2026-07-08 | 容器自包含定时调度；多实例场景 V3 引入 leader election | 调度、容器、高可用 |
| [ADR-006](ADR-006-weights-freeze.md) | 评分权重初值冻结与校准策略 | Accepted | 2026-07-08 | MVP 权重固定；V2 通过灰度 + 用户反馈校准，并记录 weight_changelog | 算法、数据、校准 |
| [ADR-007](ADR-007-multi-project-concurrency.md) | 多项目并发模型 | Accepted | 2026-07-08 | 项目级并行、Agent 级串行、子调用并发；Semaphore + 事务边界 | 性能、并发、一致性 |
| [ADR-008](ADR-008-user-system.md) | 用户系统与多租户隔离 | Accepted | 2026-07-08 | V2 引入 anonymous user + persistent user；资源按 user_id 隔离 | 鉴权、数据隔离、API |
| [ADR-009](ADR-009-api-versioning.md) | API 版本管理策略（URL Prefix + 生命周期管理） | Accepted | 2026-07-08 | `/api/v1/` 路径版本；同一大版本向后兼容，Deprecated 带 90 天窗口 | API 契约、兼容性、演进 |
| [ADR-010](ADR-010-competition-cache.md) | 竞争度子分缓存与增量计数策略 | Accepted | 2026-07-08 | 按 `sector` 缓存竞争度，增量刷新，避免每次全量扫描 | 性能、缓存、竞争度评分 |
| [ADR-011](ADR-011-mvp-chart-library.md) | MVP Dashboard 图表库选型 | Accepted | 2026-07-08 | MVP 用 Chart.js 4.x CDN，三种图表类型；国内访问问题走降级方案 | 前端、图表、CDN |
| [ADR-012](ADR-012-system-direction-auto-scan.md) | 系统方向反转为自动扫描全网发现平台 | Accepted | 2026-07-09 | 手动输入→自动扫描；双调度器；4 张采集表；LLM 分级使用 | 数据源、调度、数据库、API、安全、成本 |
| [ADR-013](ADR-013-nextjs-primary-frontend.md) | 主前端演进为 Next.js（App Router） | Accepted | 2026-07-13 | `frontend-next` 为主路径；ADR-003 HTML 保留为原型 | 前端、部署、CORS/代理 |
| [ADR-014](ADR-014-engine-spec-conformance.md) | 评分决策引擎回归规范 + 旁路机会引擎区间算法修正 | Accepted | 2026-07-26 | 按规范修正实现而非改规范迁就实现；跨源合并不再丢信号，低置信降档与 TOO_EXPENSIVE 由死规则变为可达 | 评分算法、旁路决策、Golden、DB 写入列 |
| [ADR-015](ADR-015-eligibility-gate-before-scoring.md) | 机会资格前置门（否决条件与打分分离） | Accepted | 2026-09-01 | 回测实测 fpr=100%（19/19 全判 FARM）；「已发币=无机会」改为不可补偿的否决而非可补偿打分，否决只改 label 不改 score。实测目标函数 −1.00 → +0.129 | 评分算法、权重校准协议、API 契约、前端标签 |
| [ADR-016](ADR-016-llm-provider-round-robin.md) | 多接口多模型自动轮询（编号配置迁移 + 组合级 round-robin） | Accepted | 2026-09-03 | 原实现是固定顺序 failover，第一个接口承担全部流量；改为 provider×model 组合级确定性轮询，新编号格式优先、旧编号进弃用窗口；预算仍是全局单账本 | LLM 配置、调度、成本分布、状态接口 |

## 按主题快速导航

| 主题 | 相关 ADR |
| --- | --- |
| 评分算法 | [ADR-006](ADR-006-weights-freeze.md) 权重冻结与校准、竞争度缓存；[ADR-014](ADR-014-engine-spec-conformance.md) 实现回归规范；[ADR-015](ADR-015-eligibility-gate-before-scoring.md) 资格门前置（否决与打分分离） |
| 旁路决策引擎 | [ADR-014](ADR-014-engine-spec-conformance.md) 联合概率区间算法与 TOO_EXPENSIVE 可达性 |
| 数据层 | [ADR-004](ADR-004-sqlite-to-postgres.md) SQLite→PG |
| 调度与执行 | [ADR-005](ADR-005-apscheduler-inprocess.md) APScheduler、多项目并发 |
| Agent 编排 | [ADR-002](ADR-002-self-built-orchestrator.md) 自研 Orchestrator |
| 前端 | [ADR-003](ADR-003-single-page-html-mvp.md) 单页 HTML 原型 → [ADR-013](ADR-013-nextjs-primary-frontend.md) Next 主路径 |
| 成本与可用性 | [ADR-001](ADR-001-llm-default-off.md) LLM 默认关闭、可离线运行；[ADR-016](ADR-016-llm-provider-round-robin.md) 多接口轮询与成本分布 |
| 用户与鉴权 | [ADR-008](ADR-008-user-system.md) 用户系统与多租户隔离 |
| API 与兼容性 | [ADR-009](ADR-009-api-versioning.md) API 版本管理 |
| 性能与缓存 | [ADR-010](ADR-010-competition-cache.md) 竞争度缓存 |
| 并发与一致性 | [ADR-007](ADR-007-multi-project-concurrency.md) 多项目并发 |
| **数据源与采集** | **[ADR-012](ADR-012-system-direction-auto-scan.md) 系统方向反转与自动扫描** |

## 何时新增 ADR

- 架构级决策（技术栈、数据层、编排框架、调度、鉴权、外部依赖引入）。
- 权重默认值、评分阈值等可调参数的**初值冻结**。
- 任何"如果以后改，会有迁移成本"的决策。

## 何时不需 ADR

- 纯实现细节（函数命名、变量提取）。
- Bug 修复。
- 文档润色。

## 模板

使用 [TEMPLATE.md](TEMPLATE.md) 创建新 ADR。模板包含：

- **元数据**：Status / Date / Deciders / 技术栈 / 影响面
- **必填章节**：背景 → 决策 → 理由（含备选方案对比表）→ 后果
- **可选章节**：备选方案详情 / 关联 / 状态变更历史

创建步骤：
1. 确定下一个序号（如当前最新为 ADR-010，新 ADR 即 ADR-011）
2. 复制 `TEMPLATE.md` 为 `ADR-0xx-<english-slug>.md`
3. 填入内容，保留注释作为编写指引
4. 更新本文档索引表
