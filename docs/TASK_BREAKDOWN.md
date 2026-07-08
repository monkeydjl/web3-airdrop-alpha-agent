# W1–W12 任务分解（Task Breakdown）

> 本文档基于 [ENGINEERING_ROADMAP.md §13](ENGINEERING_ROADMAP.md) 拆解为可执行的任务清单。
> 适用范围：MVP → V2 → V3 全周期。每任务含 ID、描述、验收标准、依赖关系、预估工时。
> **关键路径**：W1→W2→W3→W4（MVP 完成）→W5/W6 可并行→W7–W11（V2 渐进）→W12+（V3）。

---

## 📋 任务状态图例

| 状态 | 含义 |
|---|---|
| ⬜ 待开始 | 未启动 |
| 🟡 进行中 | 开发中 |
| ✅ 已完成 | 通过验收 |
| ⛔ 阻塞 | 依赖未满足 |

---

## 🟢 W1｜基础设施（第 1 周）

### 目标
搭建项目骨架、配置系统、数据层基础、FastAPI 入口、fetcher 骨架。

### 交付物
- 目录结构（backend/frontend/data/tests/docs）
- config.py（pydantic-settings）
- models.py（Pydantic 模型）
- db.py（SQLite WAL 模式）
- main.py（FastAPI app + /health）
- fetcher.py（缓存/重试/熔断骨架）

### 任务清单

| ID | 任务 | 描述 | 验收标准 | 依赖 | 工时 |
|---|---|---|---|---|---|
| W1-01 | 创建目录结构 | 按 §4 创建 backend/app/agents/prompts、frontend、data、tests/unit/contracts/golden/api、docs 等目录 | `ls -la` 目录完整 | — | 0.5h |
| W1-02 | 配置系统 config.py | 实现 pydantic-settings：WeightsConfig（Σ=1.0 断言）、ThresholdsConfig、SourcesConfig、LLMConfig、SchedulerConfig | 单元测试：加载默认值；Σ=1.0 断言通过 | — | 2h |
| W1-03 | Pydantic 模型 models.py | 定义 RawProject、NarrativeResult、TeamResult、RiskResult、TokenomicsResult、ScoreResult、AgentContext、PipelineState、AgentError | 契约测试：模型校验通过；字段与 DATA_SCORING_DICT §3 对齐 | — | 3h |
| W1-04 | 数据层 db.py | 实现 SQLite WAL 连接、init_db() 幂等建表（projects/logs 表 §5.1/§5.2）、CRUD 基础函数 | `/health` 返回 db:connected；init_db() 重复调用不报错 | — | 3h |
| W1-05 | FastAPI 入口 main.py | 创建 app、Mount 静态目录、/health 端点、CORS 配置、uvicorn 入口 run.py | `curl /health` → 200 {"ok":true,"data":{"status":"healthy"}} | W1-02, W1-04 | 2h |
| W1-06 | Fetcher 骨架 fetcher.py | 实现统一 fetcher.get(url, cache_key, ttl, timeout)：进程内 LRU 缓存、指数退避重试、滑动窗口熔断 | 单元测试：缓存命中/miss；重试退避；熔断开启/恢复 | — | 4h |
| W1-07 | 依赖管理 requirements.txt | 锁定 fastapi/uvicorn/pydantic/pydantic-settings/sqlalchemy/structlog/prometheus_client/apscheduler 等 | `pip install -r requirements.txt` 成功 | — | 0.5h |
| W1-08 | .env.example + .gitignore | 环境变量模板（PORT/DB_PATH/OPENAI_API_KEY/API_KEY 等）；gitignore 含 .env/data/backups | 文件完整 | — | 0.5h |

### 验收门
- [ ] `curl localhost:8000/health` → 200 healthy
- [ ] `init_db()` 幂等（重复调用不报错）
- [ ] 配置 Σ=1.0 启动断言通过
- [ ] 单元测试：config 加载 + 模型校验全绿

### 风险缓解
- W1-03 Pydantic 模型定义后立即跑契约测试（§14.3），防后期返工
- W1-06 fetcher 缓存/熔断需独立单元测试

---

## 🟢 W2｜Agent 核心（第 2 周）

### 目标
实现 7 个 Agent（规则引擎）+ Orchestrator + 归一化去重 + Scorer。

### 交付物
- BaseAgent 抽象基类 + PipelineState
- Collector（含归一化去重）
- Narrative / Team / Risk / Tokenomics Agent
- Scorer（6 维加权）
- Orchestrator（collect→analyze→score 流程）
- 单元测试 + LayerX golden 用例

### 任务清单

| ID | 任务 | 描述 | 验收标准 | 依赖 | 工时 |
|---|---|---|---|---|---|
| W2-01 | BaseAgent 基类 | 抽象基类 + `run(context)` 契约 + `llm_enhance()` 钩子 + PipelineState dataclass + AgentContext | 契约测试通过 | W1-03 | 2h |
| W2-02 | 归一化/去重逻辑 | `normalize(name)` 小写→去空格/连字符→剔除后缀→NFKC；`SECTOR_ALIAS` 词表；`dedup_key = f"{name_key}::{sector_key}"` | 单元测试：`"Layer2 Finance"` vs `"layer2-finance"` 命中同 dedup_key | — | 3h |
| W2-03 | Collector Agent | 产出 RawProject[]；UUID v5 确定性 id；去重仲裁（seed>defillama>cryptorank>twitter） | 单元测试：同 dedup_key 多源合并；UUID 跨 run 稳定 | W2-01, W2-02 | 4h |
| W2-04 | Narrative Agent | 规则引擎：SECTOR_PROFILE 表 → heat_score × 动量修正；timing 映射（stage→timing 表 §5.2） | 单元测试：4 stage → timing 映射正确；heat_score 边界 0/1 | W2-01 | 3h |
| W2-05 | Team Agent | 规则引擎：匿名团队 -0.2、历史失败 -0.25、知名 VC +0.2；score 截断 [0,1]；risk_level 映射 | 单元测试：多 flag 叠加截断；risk_level 三档边界 | W2-01 | 2h |
| W2-06 | Risk Agent | 规则引擎：sybil_difficulty 三档 × farming_cost 三档组合；token_risk 缺失走 0.5 | 单元测试：9 种组合；缺失降级 | W2-01 | 2h |
| W2-07 | Tokenomics Agent | 规则引擎：`risk = vc×0.4 + team×0.3 + unlock×0.3`；unlock_pressure 三档映射 | 单元测试：公式精确断言；边界值 | W2-01 | 2h |
| W2-08 | Scorer | 6 维加权汇总；clamp [0,100]；round-half-to-even；reason 生成规则（§7.4）；缺失降级（§7.6）；label 阈值（§7.3） | 单元测试：LayerX 计算 = 67/WATCH；权重和 = 1.0 | W2-04~07 | 4h |
| W2-09 | Orchestrator（MVP 串行） | MVP 串行版本：for 循环逐个项目跑 pipeline；单项目内 4 agent asyncio.gather；try/except 错误隔离；写 projects 表 + logs 表 | 集成测试：全链路跑通；4 agent 并行；单 agent 异常不中断其他项目 | W2-03~08 | 3h |
| W2-09b | Orchestrator（V2 并发） | V2 `asyncio.Semaphore` 版本：Semaphore 控制并发项目数；LLM 独立 Semaphore；fetcher Semaphore；单项目超时保护；ConcurrencyConfig 配置化 | 集成测试：并发 10 项目全链路跑通；Semaphore 限流生效；超时跳过 | W2-09 | 4h |
| W2-09c | 并发监控指标 | 注册 §6.9.9 的 6 个 `airdrop_concurrency_*` 指标 | `/metrics` 可查 | W2-09b | 1h |
| W2-10 | Golden 回归集 | `tests/golden/projects.jsonl` 维护 20+ 历史项目（含 LayerX）的输入→期望输出快照 | `pytest tests/golden` 通过 | W2-08, W2-09 | 3h |
| W2-11 | 单元测试补全 | 每个 Agent `run()` + 评分公式 + 归一化/去重（~50 个用例） | 行覆盖率 ≥ 80%，agents/scorer/orchestrator ≥ 90% | W2-03~09 | 4h |

### 验收门
- [ ] 单元测试全绿（~50 用例）
- [ ] LayerX golden 用例通过（score=67, label=WATCH）
- [ ] 集成测试：Orchestrator 全链路跑通
- [ ] 覆盖率：行 ≥ 80%，关键模块 ≥ 90%

### 风险缓解
- W2-02 归一化边界 case 前置 20+ 测试集
- W2-01 BaseAgent 契约先锁定，4 agent 并行开发时不漂移

---

## 🟢 W3｜API + 前端（第 3 周）

### 目标
实现 REST 4 端点 + 单页 HTML Dashboard + 前后端联调。

### 交付物
- POST /api/v1/run
- GET /api/v1/projects
- GET /api/v1/project/{id}
- POST /api/v1/re-score/{id}
- GET /api/v1/insights（MVP 基础聚合：label_counts / sector_counts / score_distribution；V2 增强见 FRONTEND_SPEC §3.3）
- frontend/index.html（单页 Dashboard）
- API 测试（端点 × 正常/异常路径）

### 任务清单

| ID | 任务 | 描述 | 验收标准 | 依赖 | 工时 |
|---|---|---|---|---|---|
| W3-01 | POST /api/v1/run | 触发 pipeline；请求体 source/limit；响应 analyzed/inserted/updated/top_id/top_score/elapsed_ms | API 测试：200 正常；400 非法 source | W2-09 | 2h |
| W3-02 | GET /api/v1/projects | 列表查询；Query label/sector/limit/order；SQL 层排序 tie-break（§7.8） | API 测试：筛选/排序/分页参数组合 | W2-09 | 2h |
| W3-03 | GET /api/v1/project/{id} | 单项目详情；含四 agent JSON 明细 + reason + confidence | API 测试：200 正常；404 不存在 | W2-09 | 1h |
| W3-04 | POST /api/v1/re-score/{id} | 重跑 analyze+score；不重新采集；幂等（§6.2.3） | API 测试：200 更新后记录；404 不存在；并发安全 | W2-09 | 2h |
| W3-05 | GET /api/v1/insights（MVP 基础聚合） | label_counts / sector_counts / score_distribution 从 projects 表聚合 | API 测试：200 返回基础聚合 | W2-09 | 1h |
| W3-05b | 统一响应包络 | 所有端点返回 `{ok, data, error}`；Pydantic 模型校验（422 自动）；ProjectRecord 含 confidence 字段 | 响应结构一致 | W3-01~05 | 1h |
| W3-06 | 单页 Dashboard HTML | `frontend/index.html`：统计条（FARM/WATCH/IGNORE 计数）+ Score 分布图 + 赛道分布图 + Top 项目卡片 + 筛选栏 | 浏览器打开可预览 Top 项目；Chart.js 加载 | — | 6h |
| W3-07 | Dashboard JS 逻辑 | fetch `/api/v1/projects` 渲染卡片；筛选栏防抖 300ms；点击跳详情（V2 用 anchor） | 筛选/排序交互正常 | W3-06 | 3h |
| W3-08 | 前后端联调 | 本地起服务 + Dashboard 预览；CORS 配置（如需） | Dashboard 显示真实数据 | W3-05, W3-07 | 2h |
| W3-09 | API 测试补全 | 4 端点 × 正常/异常路径（400/404/422/500）；POST /run 幂等性 | ~15 个用例全绿 | W3-01~04 | 3h |

### 验收门
- [ ] API 测试通过（~15 用例）
- [ ] Dashboard 可预览 Top 项目与分布
- [ ] 筛选/排序交互正常
- [ ] 4 端点响应结构统一

### 风险缓解
- W3-06 Chart.js CDN 国内访问问题：备选 ECharts 或本地打包
- W3-08 跨联调：确认 API base URL 正确（`/api/v1`）

---

## 🟢 W4｜部署 + 文档 + 可观测骨架（第 4 周）

### 目标
Docker 部署、README、种子数据、structlog + /metrics 骨架、CI 流水线。

### 交付物
- Dockerfile + docker-compose.yml
- README.md（启动/使用/架构说明）
- seed.py（演示种子数据）
- structlog JSON 输出 + /metrics 文本端点
- GitHub Actions CI 流水线
- MVP DoD（§17）达标

### 任务清单

| ID | 任务 | 描述 | 验收标准 | 依赖 | 工时 |
|---|---|---|---|---|---|
| W4-01 | Dockerfile | 多阶段构建；python:3.11-slim 基础镜像；非 root 用户；安装依赖 + 复制代码 | `docker build` 成功；镜像 < 200MB | W1-07 | 2h |
| W4-02 | docker-compose.yml | web 服务（FastAPI + 静态前端）；挂载 ./data；/health 健康检查；restart: unless-stopped | `docker compose up` 成功；/health 200 | W4-01 | 1h |
| W4-03 | 种子数据 seed.py | 内置 LayerX 等 10+ 演示项目；除 raw_signals 外携带 §6.2.4 约定的分析字段（heat_score/team_score/vc_share 等），使 MVP 评分非中性 | `POST /run?source=seed` 写入 ≥10 项目且 confidence=1.0 | W2-09 | 2h |
| W4-04 | structlog 配置 | JSON 输出到 stdout；含 run_id/project_id/agent_name 贯穿链路；redact 敏感字段 | 日志格式符合 OBSERVABILITY §2.1 | — | 2h |
| W4-05 | /metrics 端点 | Prometheus 文本格式；注册 run_total/run_duration/projects_analyzed/agent_duration 等基础指标 | `curl /metrics` 返回文本格式 | — | 3h |
| W4-06 | README.md | 启动说明（本地 + Docker）；架构图；API 文档链接；环境变量清单；截图 | 新人可按 README 启动 | W4-01~05 | 3h |
| W4-07 | CI 流水线 | GitHub Actions：lint(ruff) → test(pytest + coverage) → build(docker) | push/PR 触发；CI 绿 | — | 4h |
| W4-08 | 部署后冒烟 | CI 部署后自动 curl /health + POST /run?source=seed；断言 analyzed>0 | 冒烟通过 | W4-07 | 1h |
| W4-09 | MVP DoD 自查 | §17 共 11 项验收标准逐项检查 | 全部达标 | W4-01~08 | 2h |

### 验收门
- [ ] `docker compose up` 可启动并访问
- [ ] `/health` 返回 healthy
- [ ] CI 流水线全绿（lint + test + build）
- [ ] MVP DoD（§17）11 项全部达标
- [ ] README 含启动/使用/架构说明

### 风险缓解
- W4-07 CI 首次搭建：参考 GitHub Actions 官方模板；先跑通 lint+test，再叠加 build
- W4-05 /metrics 指标命名与 OBSERVABILITY §3 对齐

---

### 风险缓解（新增）
- W2-09b `asyncio.Semaphore` 并发测试需构造 50+ 项目输入验证限流、OOM 保护、超时跳过
- W2-09c 并发指标注册须与 OBSERVABILITY §3.2 对齐命名

---

## 🟡 W5｜LLM 集成（ADR-001）（第 5 周）

### 目标
实现可选 LLM 增强插件：llm_enhance 钩子、prompt 模板、降级链、成本控制。

### 交付物
- `llm_enhance()` 钩子实现
- agents/prompts/ 模板（版本化）
- 降级链（超时/4xx/5xx/JSON 解析失败 → 回退规则）
- 成本控制（预算/采样/缓存）
- LLM 开/关双路径测试

### 任务清单

| ID | 任务 | 描述 | 验收标准 | 依赖 | 工时 |
|---|---|---|---|---|---|
| W5-01 | LLM 客户端封装 | OpenAI SDK 封装；同步阻塞 + 软超时（deadline_ms=8s）；仅 OPENAI_API_KEY 非空时启用 | 单元测试：key 空时跳过；超时时返回 None | — | 2h |
| W5-02 | llm_enhance 钩子 | BaseAgent.llm_enhance(prompt) → 修正 JSON；失败返回 None 触发规则回退 | 契约测试：成功返回修正；失败返回 None | W5-01 | 2h |
| W5-03 | Narrative LLM prompt | 模板：输入 sector + raw_signals → 输出 heat_score_adjustment [-0.3,0.3] + timing_correction + evidence | 模板版本化（prompt_version 写入 logs） | — | 3h |
| W5-04 | Team LLM prompt | 模板：输入 team 信息 → 输出 score_adjustment + flags + evidence | 同上 | — | 2h |
| W5-05 | 降级链 | LLM 失败/超时 → 回退规则引擎；记 AgentError(kind="llm_fallback")；连续 3 次 fallback → 该 agent 本次 run 跳过 LLM | 单元测试：降级不中断主流程；熔断生效 | W5-02 | 3h |
| W5-06 | 成本控制 | daily_budget_usd（默认 $1）；非 FARM 候选 30% 概率调用；相同 (agent, prompt_hash) 缓存 6h | 单元测试：超预算自动停用；采样率正确 | W5-01 | 3h |
| W5-07 | LLM 指标 | llm_calls_total、llm_cost_usd_total、llm_fallback_total | /metrics 可查 | W4-05 | 1h |
| W5-08 | 双路径测试 | LLM 开/关两种配置下跑全链路；对比评分差异写入 logs | 测试通过；开/关均可产出评分 | W5-05, W5-06 | 3h |

### 验收门
- [ ] LLM 开/关双路径测试通过
- [ ] 超预算自动停用
- [ ] 降级链稳定性（连续 3 次 fallback 熔断）
- [ ] LLM 不可用绝不中断主流程

### 风险缓解
- W5-03/04 Prompt 调优：先跑通 JSON schema 约束，再迭代调优
- W5-06 成本控制：预算硬上限 + 采样 + 缓存三重保障

---

## 🟡 W6｜安全与合规硬化（第 6 周）

### 目标
依赖安全扫描、鉴权骨架、输入校验审计、SRI。

### 交付物
- pip-audit 进 CI
- API_KEY Bearer 鉴权中间件
- 输入校验审计（Pydantic 模型 + 自定义校验）
- 前端 CDN 资源 SRI hash

### 任务清单

| ID | 任务 | 描述 | 验收标准 | 依赖 | 工时 |
|---|---|---|---|---|---|
| W6-01 | pip-audit 进 CI | CI 跑 `pip-audit -r requirements.lock.txt --strict`；高危 CVE 阻断 PR | CI 安全扫描无高危 | W4-07 | 1h |
| W6-02 | 依赖锁定 | `requirements.lock.txt`（pip-compile 生成）锁全部传递依赖 | 可复现安装 | W1-07 | 1h |
| W6-03 | API_KEY 鉴权中间件 | Bearer Token 校验；API_KEY 空则跳过（MVP 模式）；/health /metrics /docs 白名单 | 单元测试：有 key → 401/200；无 key → 跳过 | — | 3h |
| W6-04 | 输入校验审计 | source 枚举白名单；limit 1-500；id UUID v5 格式；外部数据 schema 校验 | 单元测试：非法输入 → 422/400 | W3-01~04 | 2h |
| W6-05 | 前端 SRI | Chart.js CDN 资源加 integrity hash + crossorigin | 浏览器控制台无 SRI 报错 | W3-06 | 1h |
| W6-06 | 渗透清单自查 | SECURITY §8.3 7 项检查（鉴权绕过/越权/注入/XSS/CSRF/速率限制/密钥泄漏） | 全部通过 | W6-03~05 | 2h |
| W6-07 | 用户鉴权测试 | 匿名 token 获取/刷新/过期；API_KEY 校验；无 token 401；白名单端点免鉴权 | 测试通过 | W6-03, §25.3.2 | 2h |
| W6-08 | API 版本弃用中间件 | 实现 `APIVersionMiddleware`：Deprecation/Sunset/Link 响应头；版本元端点 `/api/version`；弃用版本返回 410 | 单元测试：弃用版本响应头正确；Sunset 后 410 | — | 3h |
| W6-09 | API 版本监控指标 | 注册 `api_version_calls_total`、`api_version_deprecated_calls_total`、`api_sunset_blocked_requests_total` | /metrics 可查版本统计 | W6-08 | 1h |

### 验收门
- [ ] 安全扫描无高危
- [ ] 鉴权端点 401 用例通过
- [ ] 输入校验 422/400 用例通过
- [ ] SRI hash 正确

### 风险缓解
- W6-03 鉴权中间件：环境变量开关控制（API_KEY 空则跳过校验）
- W6-01 pip-audit：建立白名单策略处理已知误报

---

## 🟡 W7–W8｜V2 数据接入（第 7–8 周）

### 目标
接入 4 个真实数据源（DefiLlama/CryptoRank/Twitter/Dune）+ 容错矩阵 + Next.js Dashboard。

### 交付物
- DefiLlama /protocols 与 /new 端点接入
- CryptoRank 项目库 API 接入
- Twitter API v2 关键词扫描
- Dune API 链上指标查询
- 容错矩阵（4×4 单元格测试）
- Next.js 14 Dashboard（App Router + Tailwind + TanStack Query）

### 任务清单

| ID | 任务 | 描述 | 验收标准 | 依赖 | 工时 |
|---|---|---|---|---|---|
| W7-01 | DefiLlama fetcher | `/protocols`（TTL 1h）+ `/new`（TTL 15min）；公开 REST 无需 key | 单元测试：拉取成功；缓存命中 | W1-06 | 3h |
| W7-02 | CryptoRank fetcher | 项目库 API（TTL 6h）；API key 环境变量 | 单元测试：拉取成功 | W1-06 | 2h |
| W7-03 | Twitter fetcher | API v2 关键词扫描（TTL 30min）；限流 429 处理 | 单元测试：限流走缓存 | W1-06 | 4h |
| W7-04 | Dune fetcher | 链上指标查询（TTL 1h）；API key 环境变量 | 单元测试：拉取成功 | W1-06 | 3h |
| W7-05 | 容错矩阵 | 4 源 × 4 降级路径（§10.2）；熔断/降级演练 | 演练通过：单源失败不影响主流程 | W7-01~04 | 4h |
| W7-06 | Next.js 工程搭建 | Next.js 14 App Router + Tailwind + TanStack Query；路由 /、/project/[id]、/insights | `npm run dev` 可启动 | — | 4h |
| W7-07 | Next.js 组件 | StatCard、ProjectCard、ScoreBadge、ScoreRing、DistributionChart、AgentPanel、FilterBar | 组件渲染正常 | W7-06 | 6h |
| W7-08 | Next.js 数据层 | TanStack Query 封装 API 调用；SSR 支持 | 数据正常加载 | W7-07 | 3h |
| W7-09 | 数据源健康指标 | fetcher_duration_seconds、fetcher_errors_total、fetcher_circuit_open、fetcher_cache_hits_total | /metrics 可查 | W4-05, W7-01~04 | 2h |

### 验收门
- [ ] 4 源成功率 ≥95%（在线）
- [ ] 熔断/降级演练通过
- [ ] Next.js Dashboard 可预览
- [ ] 数据源健康指标可观测

### 风险缓解
- W7-03 Twitter 限流：走缓存（可能过期）→ 缓存 miss 则 heat_score=0.5 中性
- W7-06 Next.js 学习曲线：先用最小可用组件跑通，再逐步完善

---

## 🟡 W9｜可观测性完整（第 9 周）

### 目标
Prometheus 全指标、Grafana 面板、告警规则、OpenTelemetry trace。

### 交付物
- 完整 Prometheus 指标（OBSERVABILITY §3.2 全量）
- Grafana 运维面板（7 行 × 多列）
- Alertmanager 告警规则 + 路由
- OpenTelemetry trace（agent span + run_id 贯穿）

### 任务清单

| ID | 任务 | 描述 | 验收标准 | 依赖 | 工时 |
|---|---|---|---|---|---|
| W9-01 | 全量 Prometheus 指标 | 补齐 OBSERVABILITY §3.2 所有指标（pipeline/agent/fetcher/llm/db/api/quality 层） | `curl /metrics` 返回全量 | W4-05 | 4h |
| W9-02 | Grafana 面板 | 7 行面板：概览/pipeline/agent/fetcher/llm/db/数据质量 | 面板可观测所有指标 | W9-01 | 6h |
| W9-03 | 告警规则 | OBSERVABILITY §5.2 9 条规则（critical/warning 分级） | 规则加载成功 | W9-01 | 3h |
| W9-04 | Alertmanager 路由 | critical → PagerDuty；warning → Slack；5min 聚合 | 路由配置正确 | W9-03 | 2h |
| W9-05 | OpenTelemetry trace | opentelemetry-instrumentation-fastapi；每个 agent 一个 span；run_id 作为 trace attribute | trace 可查（Jaeger/Tempo） | — | 4h |
| W9-06 | 告警演练 | 构造"pipeline 连续失败"、"DB 写失败"场景；验证告警触发 | 演练通过 | W9-03, W9-04 | 2h |

### 验收门
- [ ] 面板可观测所有 §20.2 指标
- [ ] 告警演练通过
- [ ] trace 链路完整（API → orchestrator → agents → scorer → db）

### 风险缓解
- W9-06 告警演练：需构造异常场景（Mock 或断网）
- W9-05 OTel：采样策略（error 100%，success 10%）控制成本

---

## 🟡 W10｜V2 数据层迁移（第 10 周）

### 目标
引入 Alembic、PostgreSQL、V2 新表（§5.4）、SQLite→PG 迁移。

### 交付物
- Alembic 配置 + 初始迁移
- PostgreSQL 连接（db.py 抽象层）
- V2 新表（feedback/events/quarantine/project_history/weight_changelog/narratives）
- SQLite→PG 迁移脚本
- 回滚演练通过

### 任务清单

| ID | 任务 | 描述 | 验收标准 | 依赖 | 工时 |
|---|---|---|---|---|---|
| W10-01 | Alembic 配置 | alembic.ini + env.py；初始迁移（projects/logs 表） | `alembic upgrade head` 成功 | — | 2h |
| W10-02 | PostgreSQL 连接 | db.py 支持 DATABASE_URL；SQLAlchemy Core 跨库兼容 | 单元测试：PG 连接成功 | W10-01 | 2h |
| W10-03 | V2 新表迁移 | feedback/events/quarantine/project_history/weight_changelog/narratives（§5.4 DDL） | 迁移成功；表结构正确 | W10-01 | 4h |
| W10-04 | SQLite→PG 迁移脚本 | 读取 SQLite → 写入 PG；保留 id 一致性 | 迁移后数据完整；id 不变 | W10-02, W10-03 | 4h |
| W10-05 | 回滚演练 | `alembic downgrade -1` → 验证 → `alembic upgrade head` | 回滚后可恢复 | W10-01~04 | 2h |
| W10-06 | 应用层双写兼容 | 迁移期间应用可回退到上一版本而不依赖数据回滚 | 回退演练通过 | W10-04 | 2h |

### 验收门
- [ ] 切换零数据丢失
- [ ] 回滚演练通过
- [ ] 应用可回退到上一版本

### 风险缓解
- W10-01 Alembic 学习曲线：参考官方文档；先跑通基本迁移
- W10-04 数据迁移：迁移前备份；迁移后校验行数

---

## 🟡 W11｜反馈与校准闭环（第 11 周）

### 目标
feedback/events 表、backtest.py、权重灰度发布机制。

### 交付物
- feedback/events 表 CRUD API
- backtest.py（网格搜索权重优化）
- 权重灰度发布机制（双跑对比 + changelog）
- 样本 ≥200 触发首次校准

### 任务清单

| ID | 任务 | 描述 | 验收标准 | 依赖 | 工时 |
|---|---|---|---|---|---|
| W11-01 | feedback API | POST /api/v1/feedback（signal/note/outcome）；GET /api/v1/feedback?project_id | API 测试通过 | W10-03 | 2h |
| W11-02 | events 埋点 | Dashboard 点击/停留/展开 reason → POST /api/v1/events | 埋点数据可查 | W10-03 | 2h |
| W11-02b | audit 端点 | GET /api/v1/audit（action/user 过滤，对应 audit_logs 表）；run/re-score 关键操作写 audit_logs | 审计日志可查；与 `SECURITY.md` §4.3 对齐 | W10-03 | 2h |
| W11-03 | backtest.py | 历史项目 + 候选权重重算；对比用户事后标注；计算命中率/误报率 | 回测可运行 | — | 6h |
| W11-04 | 网格搜索 | 权重空间（每项 0.05–0.40，Σ=1.0）网格/贝叶斯优化；目标函数 = recall(FARM) − 2×false_positive(FARM) | 搜索可运行；产出候选权重 | W11-03 | 4h |
| W11-05 | 权重灰度发布 | 新权重写入 config.weights_v2；双跑对比 1 周；记 weight_changelog | 灰度机制可用 | W11-04 | 3h |
| W11-06 | 校准触发 | 样本 ≥200 自动触发首次校准；changelog 记录完整 | 触发逻辑正确 | W11-01, W11-05 | 2h |

### 验收门
- [ ] 样本 ≥200 触发首次校准
- [ ] changelog 记录完整（from_version/to_version/old_weights/new_weights/metrics）
- [ ] 权重变更需 ADR + 灰度（禁止全自动切默认）

### 风险缓解
- W11-03/04 backtest 复杂度：先实现网格搜索，贝叶斯优化 V3 补充
- W11-06 样本采集：V2 采集期可能不足，需提前埋点

---

## 🔴 W12+｜V3（第 12 周+）

### 目标
多钱包策略、Memory 系统、多实例 HA、异常检测。

### 交付物
- 多钱包策略建议（基于风险/Sybil 难度）
- Memory 系统（project_history 时间序列 + user_profile）
- 多实例 HA（leader election + Celery/RQ）
- 异常检测（评分漂移/数据质量退化）

### 任务清单

| ID | 任务 | 描述 | 验收标准 | 依赖 | 工时 |
|---|---|---|---|---|---|
| W12-01 | 多钱包策略 | 基于 risk.sybil_difficulty + farming_cost 输出多钱包参与建议 | 策略可运行 | W11-05 | 6h |
| W12-02 | Memory 系统 | project_history 时间序列查询；user_profile 偏好向量（从 feedback 推断） | Memory 可读取 | W11-05 | 8h |
| W12-03 | 多实例 HA | APScheduler → Celery/RQ；leader election（PG  advisory lock） | 多实例可运行 | W11-05 | 8h |
| W12-04 | 异常检测 | 评分漂移检测（score 分布突变）；数据质量退化告警 | 异常可检测 | W11-05 | 6h |
| W12-05 | V3 集成测试 | 全链路：多钱包 + memory + 多实例 + 异常检测 | 集成测试通过 | W12-01~04 | 4h |

### 用户系统（V3 子项目）

| ID | 任务 | 描述 | 验收标准 | 依赖 | 工时 |
|---|---|---|---|---|---|
| W12-06 | 用户认证 | JWT 签发/校验、bcrypt 密码、refresh token、JWT 吊销、匿名 token 兼容 | 注册/登录/刷新/登出/吊销全流程测试通过 | — | 6h |
| W12-07 | RBAC 中间件 | admin/analyst/viewer 角色鉴权；端点权限表；角色越界返回 403 | 三角色各端点权限测试通过 | W12-06 | 4h |
| W12-08 | 用户偏好 API | GET/PUT/PATCH user_preferences；JSON 格式持久化 | 偏好 CRUD 测试通过 | W12-06 | 2h |
| W12-09 | API Key 管理 | 创建/列出/撤销 API Key；Key 用于鉴权 | API Key 全生命周期测试通过 | W12-06, W12-07 | 3h |
| W12-10 | 行级数据隔离 | feedback/events 按 user_id 过滤；admin 可查看全部；projects 全局共享 | 隔离测试：A 用户看不到 B 用户的反馈 | W12-07 | 3h |
| W12-11 | GDPR 合规 | 数据导出（JSON）、账户删除（去标识化反馈+删除 events）、全设备登出 | 导出完整；删除后可重新注册；原反馈不关联原 user_id | W12-06, W12-10 | 4h |
| W12-12 | 用户系统集成测试 | 全链路：注册→登录→偏好→反馈→数据导出→账户删除 | 全链路测试通过 | W12-06~11 | 4h |

### 验收门
- [ ] JWT 签发/校验/吊销全流程通过
- [ ] RBAC 三角色权限测试通过
- [ ] 行级隔离测试通过
- [ ] GDPR 数据导出/删除测试通过
- [ ] 按子项目单独验收
- [ ] Memory 系统冷启动：V2 采集期数据 ≥3 个月
- [ ] 多实例 HA：leader 故障自动切换

### 风险缓解
- W12-02 Memory 冷启动：V2 采集期提前埋点（§24.1），保证 3-6 个月数据量
- W12-03 多实例：APScheduler → Celery/RQ 迁移需评估成本

---

## 📊 工时汇总

| 周次 | 工时 | 累计 | 里程碑 |
|---|---|---|---|
| W1 | 16h | 16h | 基础设施 |
| W2 | 32h | 48h | Agent 核心 |
| W3 | 22h | 70h | API + 前端 |
| W4 | 20h | 90h | 部署 + 文档 + 可观测 |
| W5 | 19h | 109h | LLM 集成 |
| W6 | 10h | 119h | 安全合规 |
| W7–W8 | 31h | 150h | V2 数据接入 |
| W9 | 21h | 171h | 可观测性完整 |
| W10 | 16h | 187h | 数据层迁移 |
| W11 | 19h | 206h | 反馈校准 |
| W12+ | 32h | 238h | V3 |

> 单人集约估算：约 238h ≈ 6 周全职（40h/周）。团队协作可压缩。

---

## 🔗 依赖关系图

```
W1 ──▶ W2 ──▶ W3 ──▶ W4 ──┬──▶ W5 ──┐
                           │         ├──▶ W7–W8 ──▶ W9 ──▶ W10 ──▶ W11 ──▶ W12+
                           └──▶ W6 ──┘
```

- W5/W6 可并行（均在 W4 后）
- W7–W11 串行（V2 渐进）
- W12+ 在 W11 后

---

## 📝 使用说明

1. **开工前**：确认前置依赖任务已完成（如 W2-01 依赖 W1-03）
2. **验收时**：逐项勾选验收门清单，全部通过方可进入下一里程碑
3. **风险跟踪**：每里程碑结束前 review §16 风险清单状态
4. **工时调整**：根据实际进度动态更新预估

---

_文档版本：v1.0 · 基于 ENGINEERING_ROADMAP.md §13 拆解 · 规划阶段。_
