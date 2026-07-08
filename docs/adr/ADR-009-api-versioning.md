# ADR-009: API 版本管理策略（URL Prefix + 生命周期管理）

- **Status**: Accepted
- **Date**: 2026-07-08
- **Deciders**: 架构师 / Tech Lead

## 背景

当前系统 API 使用 `/api/v1` 前缀，但缺乏版本管理策略：
- 没有定义何时/如何引入 `/api/v2`
- 没有弃用（Deprecation）与下架（Sunset）流程
- 没有向后兼容性保证
- v1→v2 迁移路径未设计
- 无版本监控指标

随着 V2 阶段引入新端点（feedback/events/audit/auth）、鉴权方式升级（API Key→JWT）、分页/筛选语法改进，必须有清晰的版本管理策略来管理变化，保护 API 消费者。

## 决策

采用 **URL 前缀版本化** 作为版本策略，并定义完整的版本生命周期与弃用流程：

### 1. 版本表示方式：`/api/v{n}/`

采用 URL 路径前缀，而非 Accept 头或 Query 参数。理由见 §26.3。

### 2. 版本生命周期：Alpha → Stable → Deprecated → Sunset

每个大版本经历完整生命周期，Stable 到 Sunset 至少 90 天弃用窗口（MVP→V2 无外部消费者时缩短至 30 天）。

### 3. 同一大版本内保持向后兼容

字段仅增不减、响应仅扩不缩、参数仅加不改。Breaking change 必须新版本。

### 4. 双版本并行

V2 发布后 `/api/v1` 和 `/api/v2` 并行服务至少 90 天，`/api/v1` 响应含 `Deprecation`/`Sunset`/`Link` 头引导迁移。

### 5. 解耦内部版本与 API 版本

评分权重版本、数据模型版本、Prompt 版本独立演进，不影响 API 契约。

### 6. MVP 特殊处理

MVP 阶段（当前 `/api/v1`）因无外部消费者，V2 发布时可走 30 天快速弃用。

## 理由

| 备选方案 | 被否理由 |
| --- | --- |
| **Accept 头协商** | curl/浏览器不原生支持，调试困难；中间件可能剥离自定义头 |
| **Query 参数** | 缓存污染、URL 语义不清晰 |
| **子域名** | SSL 证书/运维成本高，小系统没必要 |
| **无版本规划** | V2 发版时无迁移路径，API 消费者可能断崖式不可用 |

选择 URL 前缀是 REST API 领域最广泛采用的模式（GitHub API、Stripe API 等），工具链支持完善（Nginx/Traefik 可按前缀路由）、开发者直觉理解、缓存友好。

## 后果

### 正面
- 消费者可预期 API 稳定性，放心集成
- 平滑迁移路径，避免断崖式破坏
- 版本切换可观测（按版本统计调用量）
- 内部演进自由（权重/数据模型/LLM 变化不影响 API 消费者）

### 负面/限制
- 维护旧版路由代码（弃用窗口期内）
- 由于不采用 Accept 头，无法做细粒度版本（如单端点版本化）——但本系统不需要
- 弃用窗口期新旧版本并行，FastAPI 路由可能冲突（通过 APIRouter 隔离）
- **鉴权升级可能触发版本切换**：V3 引入 JWT 时，若认证端点响应格式/鉴权方式发生 breaking change（如匿名 token → JWT 的 payload 结构变化、认证头格式变更），将触发本 ADR 的版本升级流程（`/api/v2/`）。V3 设计时需前置评估：认证端点是否需要独立的 API 版本，或是否能在 v1 向后兼容地升级（见 ADR-008 V3 设计）。此风险已在 [ADR_CROSS_REFERENCE.md](ADR_CROSS_REFERENCE.md) CR-01 中记录。

### 需配套的工作
1. V2 发布时实现弃用中间件（`Deprecation`/`Sunset`/`Link` 头）
2. 注册 `api_version_calls_total` 等监控指标
3. 编写《v1→v2 API 迁移指南》
4. 更新 API_SPEC.md 标注各端点版本阶段
5. 监控旧版调用量归零后清理旧路由代码

### 迁移成本
- 路由代码：使用 FastAPI `APIRouter(prefix="/api/v1")` 隔离，迁移时只需调整 `include_router` 顺序
- 前端：通过 `NEXT_PUBLIC_API_VERSION` 环境变量控制 API 版本
- 部署：同一容器双路由，无需独立部署
