# Web3 Airdrop Alpha Agent System

从自动发现、结构化评分到「今天做什么」的 Web3 空投 Alpha 终端。

[![Tests](https://img.shields.io/badge/tests-4285%20passed-brightgreen)](backend/tests/)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.141-009688)](https://fastapi.tiangolo.com/)
[![Next.js](https://img.shields.io/badge/Next.js-16.4-000000)](https://nextjs.org/)
[![License](https://img.shields.io/badge/license-MIT-blue)](#许可证)

---

## 这是什么

大多数「空投工具」只做两件事：堆信息、给结论。这个项目把中间缺失的两段补上了：

1. **自动发现**：定时扫描 17 个数据源（默认启用 8 个来源），把「可能是早期空投机会」的项目送进发现队列，而不是等人工录入。
2. **可解释评分**：四个分析 Agent 并行给出叙事、团队、风险、代币经济结论，再由 Scorer 做八维加权，最后经过空投资格门控产出 `FARM / WATCH / IGNORE`。
3. **可执行闭环**：评分之后不是结束——系统生成跨项目「今日行动」、参与清单、每日通知、ROI 台账与领取监控，结果再回流到反馈校准。

分数是决策辅助，不是投资建议；系统不托管私钥，也不自动执行链上交易。

---

## 核心能力

- **自动发现闭环**：17 个采集器 → `raw_projects` 发现队列 → `discovery_score ≥ 0.30` 进入分析 → 去重 / 噪声过滤 / 脏数据隔离。
- **四 Agent 并行分析 + Scorer**：Narrative、Team、Tokenomics 并行；Risk 在 Tokenomics 之后执行，确保使用真实解锁数据；Scorer 产出八维加权分与理由。
- **空投资格门控（ADR-015）**：已发币且没有后续参与路径、明确声明无空投等项目会被确定性降级，避免「高分但已经错过」的项目占据 FARM。
- **三档决策**：`FARM`（优先参与）/ `WATCH`（观察）/ `IGNORE`（不推荐）。
- **行动闭环（F1–F4）**：决策推送、参与任务追踪、ROI 台账与历史回测、自有地址领取监控。
- **Web 终端**：14 个页面、56 个前端组件，覆盖工作台、发现队列、水龙头、空投日历、洞察、参与复盘、结果复盘、运维台、通知中心、归档、收藏、系统设置与项目详情。
- **运维能力**：统一调度器、官网活性探测、已发币复查、归档保留期、数据源开关与**采集源评分卡**（产量/分析率/隔离率/均分/断流）、异常检测、导入导出、可选多实例选主。
- **生产安全**：Bearer + API Key 分档鉴权、匿名 Token、限流、CORS 白名单、日志脱敏、LLM 日预算、Prometheus 指标。
- **诚实的数据口径**：核心链路使用真实公开数据；演示/估算类扩展端点统一标记 `data_quality: simulated`，前端显示「模拟数据」角标。

---

## 评分模型

主模型 `score-v1.4`，当前生效权重组 `v1.2`（Σ = 1.0，可由环境变量覆盖并在写入时记录 `weight_version`）：

| 维度 | 权重 | 说明 |
| --- | --- | --- |
| 空投信号 | 18% | 测试网、积分计划、未发币、任务入口、融资质量、多源交叉验证 |
| 叙事时机 | 15% | 赛道热度 + 项目阶段（early / peak / late） |
| 团队信誉 | 12% | VC 背书、创始人背景、融资质量 |
| 风险评估 | 12% | 代币风险、解锁压力、女巫难度 |
| 代币经济 | 10% | 分配比例、解锁周期 |
| 竞争度 | 10% | 同赛道项目数量 |
| 执行力 | 13% | GitHub 活跃度、路线图、推进信号 |
| 透明度 | 10% | 文档、白皮书、社媒完整度 |

**标签阈值**：`FARM ≥ 65`、`WATCH 50–64`、`IGNORE < 50`。

标签并非只由分数决定。确定性资格门控会在打分后追加否决：已发币且无参与路径、明确声明无空投、没有当前可执行路径的项目，即使质量分高也会被降级并写明原因。证据置信度低于 0.5 时还会执行 `FARM → WATCH`、`WATCH → IGNORE` 的保守降级。

**权重校准按来源分桶**：校准样本分 `live`（真实使用留痕）与 `backtest`（历史回测）两类，门禁只统计 `live`。回测样本能验证模型、提前跑通流程，但替代不了当前分布下的真实结果——所以灌再多历史回测也不会让门禁通过。门禁为 ≥200 条 live 样本且其中 ≥30 条 FARM 相关，未达标不切换默认权重。

**Opportunity Shadow**：`opportunity-v2.0` 旁路模型以追加方式保存不可变经济快照，属于非权威评估；项目分数与标签仍以 `score-v1.4` 为准。

---

## 从采集到行动

```text
17 个采集器
    │
    ▼
raw_projects（发现队列）
    │  discovery_score ≥ 0.30
    ▼
去重 / 噪声过滤 / 隔离 ──▶ quarantine
    │
    ▼
信号合并（project_signals）
    │
    ├── Narrative ──┐
    ├── Team ───────┤ 并行
    └── Tokenomics ─┴──▶ Risk（依赖解锁数据）
                              │
                              ▼
                    Scorer（score-v1.4）
                              │
                              ▼
              标签 + 资格门控（ADR-015）
                              │
          ┌───────────────────┼───────────────────┐
          ▼                   ▼                   ▼
     项目库 / 历史快照    Opportunity Shadow   今日行动 / 通知
          │                                       │
          └──────────────▶ 参与记录 / ROI / 反馈校准 ◀──┘
```

调度器默认按源的 cron 分别采集；分析任务每日 08:00 UTC 消费未处理队列；归档、官网活性、已发币复查、Alpha 速递与通知摘要各有独立开关和任务记录，可在运维台查看实际注册状态。

---

## 快速开始

### 前置要求

- Python 3.11+
- Node.js 20.9+（Docker 镜像使用 Node 22）
- Docker 20+（可选）

### 方式一：本地开发

```bash
git clone <repo-url>
cd Web3-Airdrop-Alpha-Agent-System

# 1. 环境变量
cp .env.example .env
# 本地可保持 APP_ENV=development；生产配置见下方「生产部署」
# 若启用鉴权，再设置 API_KEY 与 AUTH_TOKEN_SECRET

# 2. 后端
cd backend
python -m venv venv
# Windows PowerShell: .\venv\Scripts\Activate.ps1
# macOS / Linux:     source venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
python -m uvicorn app.main:app --host 0.0.0.0 --port 8002

# 3. 前端（另开终端）
cd frontend-next
npm install
npm run dev
```

访问：

| 服务 | 地址 |
| --- | --- |
| 前端 | http://localhost:3002 |
| Swagger | http://localhost:8002/docs |
| ReDoc | http://localhost:8002/redoc |
| 健康检查 | http://localhost:8002/health |
| Prometheus 指标 | http://localhost:8002/metrics |

### 方式二：Windows 一键启动

```batch
Start.bat   :: 创建虚拟环境、安装依赖、启动后端 + 前端
Stop.bat    :: 停止服务
```

### 方式三：Docker

```bash
# 最简 SQLite
docker compose up -d --build

# 基础 compose 的 PostgreSQL（需在 .env 设置 DB_BACKEND=postgres）
docker compose --profile postgres up -d --build

# 生产全栈：Nginx + Next.js + FastAPI + PostgreSQL + Prometheus/Grafana/Alertmanager
docker compose -f docker-compose.prod.yml up -d --build
```

生产端口映射：

| 服务 | 宿主机 | 说明 |
| --- | --- | --- |
| Nginx | `18080` | 页面 + API 统一入口 |
| Next.js | `13002` | 前端调试入口 |
| Prometheus | `19090` | 指标查询 |
| Alertmanager | `19093` | 告警管理 |
| Grafana | `13000` | 监控面板 |
| Loki | `13100` | 日志查询（`observability` profile） |
| OTel Collector | `14317` / `14318` / `18889` | OTLP / 指标（`observability` profile） |
| Jaeger | `11686` | 链路追踪（`observability` profile） |

> 生产部署必须使用 `docker-compose.prod.yml`，不要用 `docker-compose.yml --profile production`。前者才包含 Next.js 前端与生产 nginx 配置；后者只有裸 API，浏览器请求会绕过前端凭据注入而得到 401。
>
> 生产 `.env` 至少需要：`APP_ENV=production`、`API_KEY`、`AUTH_TOKEN_SECRET`、`BACKEND_API_KEY`、`POSTGRES_PASSWORD`、`GRAFANA_PASSWORD`、`CORS_ORIGINS`、`TRUSTED_PROXY_COUNT=1`。完整清单见 [GO_LIVE_CHECKLIST.md](docs/GO_LIVE_CHECKLIST.md)。

---

## 数据源

17 个采集器，按「配置开关 + 凭据 + 数据库源开关」三重条件决定是否运行：

| 采集器 | source_id | 默认 | 凭据 / 说明 |
| --- | --- | --- | --- |
| DefiLlama | `defillama` | 启用 | 免费；协议 TVL、链、赛道 |
| GitHub | `github` | 启用 | 免费；建议配置 Token 提升配额 |
| GitHub Curated | `github_curated` | 启用 | 公开 raw 内容；社区测试网与水龙头清单 |
| CoinGecko | `coingecko` | 启用 | 免费；行情与全量币表（用于发币判定） |
| Medium | `medium` | 启用 | RSS，无需 Key |
| Mirror | `mirror` | 启用 | 公开内容端点，无需 Key |
| Telegram | `telegram` | 启用 | 公开频道，无需 Key |
| Farcaster | `farcaster` | 启用 | 公共 Hub，无需 Key |
| CryptoRank | `cryptorank` | 关闭 | API Key |
| RootData | `rootdata` | 关闭 | API Key |
| Twitter KOL | `twitter_kol` | 关闭 | Bearer Token（付费） |
| Twitter Keywords | `twitter_keyword` | 关闭 | Bearer Token（付费） |
| Etherscan | `etherscan` | 关闭 | API Key |
| Galxe | `galxe` | 关闭 | API Key |
| Layer3 | `layer3` | 关闭 | API Key |
| Discord | `discord` | 关闭 | Bot Token |
| Reddit | `reddit` | 关闭 | OAuth |

采集层统一具备域名白名单、速率限制、熔断、缓存与跨源字段合并。低于发现阈值的记录不会直接丢弃，而是按保留期归档，便于复盘「当时为什么没立项」。

### 数据可信度

- **核心链路是真实数据**：采集、去重、信号合并、评分、资格门控与 ROI 台账均基于真实输入或确定性计算。
- **扩展工具箱含演示/估算端点**：跨链报价、聪明钱、女巫图谱、解锁雷达、积分推演等部分输出属于模拟或经验估算，响应会带 `data_quality.quality = "simulated"`，前端显示「模拟数据」角标。此类输出只适合教学与演练，不应作为资金决策依据。完整审计见 [EXPANSION_AUDIT_REPORT.md](docs/EXPANSION_AUDIT_REPORT.md)。
- **生产不灌种子数据**：`APP_ENV=production` 会强制关闭 seed 回退，避免内置示例项目混入真实库。
- **不构成投资建议**：系统输出是研究辅助，不保证空投存在、资格或收益。

---

## API 概览

所有业务端点使用统一响应包络：

```json
{ "ok": true, "data": {}, "error": null }
```

本地 `API_KEY` 为空时鉴权中间件短路，便于开发；生产必须配置鉴权。匿名用户可换取 72h Token 访问普通端点，管理员端点需要 `X-API-Key`。

```bash
# 消费发现队列中的未处理项目并评分
curl -X POST http://localhost:8002/api/v1/run \
  -H "Content-Type: application/json" \
  -d '{}'

# 直接提交项目评分
curl -X POST http://localhost:8002/api/v1/run \
  -H "Content-Type: application/json" \
  -d '{"projects":[{"name":"LayerX","sector":"L2","stage":"testnet","has_testnet":true,"no_token_yet":true}]}'

# 查询项目
curl "http://localhost:8002/api/v1/projects?sort_by=score&sort_order=desc&page_size=10"

# 今日行动
curl "http://localhost:8002/api/v1/action-queue?limit=5"

# 手动触发单个采集源
curl -X POST http://localhost:8002/api/v1/collections/defillama/trigger
```

主要端点分组：

| 分组 | 代表端点 | 说明 |
| --- | --- | --- |
| 分析 | `POST /api/v1/run` | 消费队列或提交项目评分 |
| 项目 | `GET/POST /api/v1/projects` | 列表、详情、评分、恢复显示 |
| 发现 | `GET /api/v1/discoveries` | 原始发现队列与发现分 |
| 采集 | `GET/PATCH/POST /api/v1/collections/*` | 源状态、评分卡、开关、手动触发 |
| 行动 | `GET /api/v1/action-queue` | 跨项目今日行动 |
| 参与 | `GET/POST/PATCH /api/v1/interactions` | 参与记录与完成状态 |
| ROI | `GET/POST /api/v1/projects/{id}/roi/*` | 投入与产出台账 |
| Opportunity | `GET /api/v1/projects/{id}/opportunity` | Shadow 评估与证据 |
| 通知 | `GET /api/v1/notifications` | 站内通知与已读状态 |
| 领取监控 | `GET/POST /api/v1/watched-wallets` | 自有地址到账监控（管理员） |
| 水龙头 | `GET /api/v1/faucets` | 列表、冷却、存活探测 |
| 洞察 | `GET /api/v1/insights` | 标签、赛道、风险、机会榜 |
| 运维 | `GET /api/v1/scheduler/jobs`、`GET /api/v1/anomalies` | 调度与异常 |
| 迁移 | `GET /api/v1/export/*`、`POST /api/v1/import/*` | Excel / CSV 导入导出 |
| 监控 | `GET /health`、`GET /metrics` | 健康检查与指标 |

完整契约见 [API_SPEC.md](docs/API_SPEC.md) 或运行时 `/docs`。

---

## 系统架构

```text
┌────────────────────────────────────────────────────────┐
│ Next.js 16 / React 19 前端（14 页面 / 56 组件）          │
└──────────────────────────┬─────────────────────────────┘
                           │ /api 经 Next 服务端代理，分档注入凭据
┌──────────────────────────▼─────────────────────────────┐
│ FastAPI 后端（63 个路由模块）                            │
│                                                        │
│  UnifiedScheduler（APScheduler）                        │
│    ├─ collect_{source}  17 源 cron                      │
│    ├─ analysis_run_queue                                │
│    ├─ archive_cleanup / vitals_probe / launch_review    │
│    └─ daily_alpha_digest / notify_digest                │
│                                                        │
│  Collector Registry → raw_projects → 分析流水线          │
│  SimpleOrchestrator → 4 Agent + Scorer + 资格门控        │
│                                                        │
│  鉴权 / 限流 / 指标 / 追踪 / LLM 预算 / 审计              │
└──────────────────────────┬─────────────────────────────┘
                           │
┌──────────────────────────▼─────────────────────────────┐
│ SQLite（WAL）/ PostgreSQL + Alembic（16 个迁移）         │
│ projects / raw_projects / project_signals / history     │
│ participation / roi / notify / watched_wallets / token  │
└────────────────────────────────────────────────────────┘
```

- **分析 Agent**：Narrative（叙事时机）、Team（团队信誉）、Risk（风险与解锁）、Tokenomics（代币经济）。
- **Scorer**：八维加权、置信度修正、理由生成、资格门控。
- **Opportunity Shadow**：旁路经济评估，不修改主分。
- **高可用**：可选数据库选主（`HA_ENABLED`），多实例下仅主实例执行调度任务。

---

## 界面

| 页面 | 路径 | 作用 |
| --- | --- | --- |
| 工作台 | `/` | 指标概览、今日行动、校准进度 |
| 发现队列 | `/discoveries` | 采集原始发现与发现分 |
| 水龙头 | `/faucets` | 公共 RPC/HTTP 存活探测与领取冷却 |
| 空投日历 | `/calendar` | 里程碑、倒计时、ICS 导出（日期含模拟标记） |
| 洞察 | `/insights` | 标签分布、赛道热度、高风险团队、机会榜 |
| 参与复盘 | `/portfolio` | ROI 台账、PnL、跨链/无常损失/团队协作工具 |
| 结果复盘 | `/review` | 一键批量标记真实结果，同时写入收益台账；按校准引擎真实门禁口径（live / FARM 样本）展示进度 |
| 运维台 | `/ops` | 数据源评分卡、调度任务、异常检测、隔离区、导入导出 |
| 通知中心 | `/notifications` | 站内通知与已读管理 |
| 归档历史 | `/archive` | 归档运行与保留策略 |
| 收藏关注 | `/collections` | Watchlist 项目与评分 |
| 不参与 | `/skipped` | 用户主动排除的项目 |
| 系统设置 | `/settings` | 自动化、数据源、界面与安全配置 |
| 项目详情 | `/project/[id]` | 评分因子、信号、时间轴、AI 简报/追问、参与清单、多钱包策略、Alpha 研报 |

扩展工具箱（位于洞察 / 参与复盘 / 项目详情）：Gas 告警、跨链路由、钱包体检、女巫隔离自查、身份护照、解锁雷达、积分推演、组合对比等。涉及模拟数据的面板会显式标注。

---

## 项目结构

```text
Web3-Airdrop-Alpha-Agent-System/
├── backend/
│   ├── app/
│   │   ├── agents/          # 4 个分析 Agent + Scorer + 资格门控 + 编排器
│   │   ├── collectors/      # 17 个采集器、注册表、持久化、噪声过滤
│   │   ├── opportunity/     # Shadow 评估、经济快照、校准
│   │   ├── routers/v1/      # 63 个 API 路由模块
│   │   ├── services/        # 58 个业务服务
│   │   ├── repositories/    # 数据访问层
│   │   ├── llm/             # 多接口 LLM 客户端与预算
│   │   ├── config.py        # Pydantic Settings
│   │   ├── scheduler.py     # 统一调度器
│   │   ├── auth.py          # 鉴权中间件
│   │   ├── metrics.py       # Prometheus 指标
│   │   └── main.py          # FastAPI 入口
│   ├── alembic/             # 16 个数据库迁移
│   ├── tests/               # 后端测试套件（4285 条用例）
│   ├── scripts/             # 校准、种子、双跑对比等脚本
│   └── requirements*.txt
├── frontend-next/
│   ├── app/                 # 14 个页面
│   ├── components/          # 56 个 React 组件
│   ├── lib/                 # API 客户端、类型、格式化
│   └── proxy.ts             # 服务端凭据注入
├── configs/                 # 功能开关与可观测性配置
├── docker/                  # Dockerfile、nginx、loki 配置
├── docs/                    # 16 份 ADR + 产品/架构/API/数据/运维文档
├── scripts/                 # 部署、回滚、工作流脚本
├── docker-compose.yml       # 开发 SQLite / PostgreSQL
├── docker-compose.prod.yml  # 生产全栈
├── Start.bat / Stop.bat     # Windows 一键启停
└── README.md
```

---

## 配置

复制 `.env.example` 到 `.env`。常用变量：

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `APP_ENV` | `development` | `production` 启用生产自检（弱密钥、localhost CORS、seed 回退等） |
| `API_KEY` | 空 | 管理员 API Key；为空时后端鉴权短路（仅适合本地） |
| `AUTH_TOKEN_SECRET` | 空 | 匿名 Bearer Token 签名密钥；生产为空拒绝启动 |
| `BACKEND_API_KEY` | 空 | 仅 Next.js 服务端使用，必须与 `API_KEY` 同值 |
| `API_PROXY_TARGET` | `http://web:8002` | 前端构建期 rewrite 与运行期换取 Token 的内网地址 |
| `CORS_ORIGINS` | localhost | 生产填实际前端域名，不得含 localhost |
| `TRUSTED_PROXY_COUNT` | `0` | 受控反代层数；生产 nginx + web 填 `1` |
| `DB_BACKEND` | `sqlite` | `sqlite` 或 `postgres` |
| `POSTGRES_PASSWORD` | 空 | PostgreSQL 密码（至少 16 字符） |
| `GITHUB_TOKEN` | 空 | 提升 GitHub API 配额；不设仍可受限速保护运行 |
| `OPENAI_API_KEY` | 空 | 项目 AI 简报与交互追问使用的 LLM 密钥（主评分管线始终 100% 确定性规则计算） |
| `LLM_DAILY_BUDGET_USD` | `1.0` | 日预算；`0` 或负数表示不限额 |
| `DISCOVERY_SCORE_ANALYSIS_THRESHOLD` | `0.30` | 发现分达到该值才进入分析 |
| `SCHEDULER_ENABLED` | `true` | 分析调度总开关 |
| `COLLECTION_SCHEDULER_ENABLED` | `true` | 采集调度总开关 |
| `NOTIFY_ENABLED` | `false` | 出站通知开关；关闭时仍写通知日志 |
| `SEED_FALLBACK_ENABLED` | `true` | 采集全挂时回退示例数据；生产强制关闭 |

完整变量、采集源凭据与调度 cron 见 [.env.example](.env.example) 与 [DEPLOYMENT.md](docs/DEPLOYMENT.md)。

---

## 测试与质量门

```bash
cd backend

# 全量测试（含覆盖率，门槛 80%）
pytest

# 并行快速跑（不生成覆盖率）
pytest -n 8 --no-cov

# 分组运行
pytest tests/agents/
pytest tests/collectors/
pytest tests/api/          # 若目录存在
pytest tests/opportunity/
pytest tests/golden/
```

2026-11-26 本机全量结果：**4285 passed / 26 skipped**（-n 8 并行约 2.6 分钟，覆盖率 ≥ 89.8%）。最新基线与覆盖率报告见 CI 与 [CHANGELOG.md](CHANGELOG.md)。

代码质量门：

```bash
cd backend
ruff check .
ruff format --check .
mypy app                    # strict

cd ../frontend-next
npm run typecheck
npm run lint
npm test
```

---

## 监控

关键指标：

- `airdrop_pipeline_runs_total` / `airdrop_pipeline_duration_seconds` — 流水线运行与延迟
- `airdrop_projects_scored_total` / `airdrop_projects_by_label_total` — 评分产出与标签分布
- `airdrop_fetcher_cache_hits_total` — 采集缓存命中
- `airdrop_fetcher_circuit_breaker_state` — 熔断状态
- `airdrop_competition_cache_hits_total` — 竞争度缓存命中

预置告警（`configs/observability/prometheus/alert_rules.yml`）：服务不可用、错误率过高、连续流水线失败。

Grafana 面板：`configs/observability/grafana/dashboards/airdrop-system-overview-v2.json`。

生产环境中 `/metrics` 不对公网开放；Prometheus 通过 Docker `backend` 网络直连后端。

---

## 生产部署

上线前逐项执行 [GO_LIVE_CHECKLIST.md](docs/GO_LIVE_CHECKLIST.md)，部署与回滚细节见 [DEPLOYMENT.md](docs/DEPLOYMENT.md)。

```bash
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml logs -f web
curl http://localhost:18080/health

# 数据库迁移（容器名 airdrop-web）
docker exec airdrop-web alembic upgrade head
docker exec airdrop-web alembic downgrade -1

docker compose -f docker-compose.prod.yml down
```

---

## 文档

- 文档总索引：[docs/00_index.md](docs/00_index.md)
- 产品与用户故事：[01_product.md](docs/01_product.md)、[USER_STORIES.md](docs/USER_STORIES.md)
- 架构与路线图：[02_architecture.md](docs/02_architecture.md)、[ENGINEERING_ROADMAP.md](docs/ENGINEERING_ROADMAP.md)
- 评分与权重：[DATA_SCORING_DICT.md](docs/DATA_SCORING_DICT.md)、[WEIGHT_CALIBRATION.md](docs/WEIGHT_CALIBRATION.md)
- 数据源策略：[DATA_SOURCE_STRATEGY.md](docs/DATA_SOURCE_STRATEGY.md)
- 行动闭环：[ACTION_LOOP_DESIGN.md](docs/ACTION_LOOP_DESIGN.md)
- 扩展功能审计：[EXPANSION_AUDIT_REPORT.md](docs/EXPANSION_AUDIT_REPORT.md)
- API 契约：[API_SPEC.md](docs/API_SPEC.md)
- 数据库：[DATABASE_DDL.md](docs/DATABASE_DDL.md)
- 运维与监控：[OPERATIONS.md](docs/OPERATIONS.md)、[OBSERVABILITY.md](docs/OBSERVABILITY.md)
- 安全：[SECURITY.md](docs/SECURITY.md)
- 当前进度：[PHASES.md](docs/PHASES.md)、[HANDOFF.md](HANDOFF.md)
- 架构决策：[docs/adr/](docs/adr/)（16 份）
- 变更记录：[CHANGELOG.md](CHANGELOG.md)

---

## 贡献

1. Fork 仓库并创建特性分支
2. 遵循 [CONVENTIONS.md](CONVENTIONS.md) 与 [CONTRIBUTING.md](CONTRIBUTING.md)
3. 提交前跑后端 `ruff`、`mypy`、`pytest` 与前端 `typecheck`、`lint`、`test`
4. 提交 Pull Request，说明变更动机与验证方式

---

## 许可证

MIT License。
