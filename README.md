# Web3 Airdrop Alpha Agent System

多智能体驱动的 Web3 早期项目识别与空投参与决策系统。

[![Tests](https://img.shields.io/badge/tests-CI%20green-brightgreen)](backend/tests/)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688)](https://fastapi.tiangolo.com/)
[![License](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

---

## 功能概览

### 核心能力

- **6 Agent 并行评分流水线** — Narrative / Team / Risk / Tokenomics / AirdropSignal / Scorer，单项目评分延迟 < 2s
- **10 个数据源采集器** — DefiLlama / GitHub / CoinGecko / CryptoRank / Etherscan / RootData / Twitter KOL / Twitter Keywords / Galxe / Layer3，统一调度 + 熔断 + 跨源合并
- **三档分类决策** — FARM (>= 65 分, 高推荐) / WATCH (观察) / IGNORE (不推荐)
- **Opportunity Shadow 旁路模型** — `opportunity-v2.0` 非权威评估，追加不可变经济快照，不影响主分数
- **LLM 增强**（可选） — OpenAI 接口增强评分叙述，按发现分数阈值触发，日预算可控
- **权重自动校准** — 基于反馈数据自动调整八维权重，支持 A/B 对比和灰度发布
- **Bearer 鉴权 + 匿名 Token** — 生产默认强制鉴权；管理员用 `X-API-Key`，普通读请求由前端服务端注入 72h TTL 匿名 token
- **Prometheus 指标 + Grafana Dashboard** — 运行时指标覆盖服务可用性与 pipeline 失败率；生产公网不暴露 `/metrics`
- **Docker 一键部署** — 开发用 SQLite / PostgreSQL；生产全栈必须使用 `docker-compose.prod.yml`

### 评分模型

主评分模型 `score-v1.4` 八因子加权：

| 维度 | 权重 | 说明 |
|------|------|------|
| 空投信号 | 20% | 测试网、积分计划、无代币、近期融资 |
| 叙事时机 | 15% | 赛道热度 + 项目阶段 |
| 团队信誉 | 15% | VC 背书 + 创始人背景 |
| 风险评估 | 15% | 代币风险 + 解锁压力 |
| 代币经济 | 15% | 分配比例 + 解锁周期 |
| 竞争度 | 10% | 同赛道竞争强度 |
| 执行力 | 5% | 开发活跃度 |
| 透明度 | 5% | 文档 + 路线图 |

**三档分类**：FARM (>= 65) / WATCH (50-64) / IGNORE (< 50)

Opportunity 旁路模型使用 `opportunity-v2.0` + 配置档案 `low-cost-curbed-multiwallet-v1`，评估以追加方式保存不可变快照，属于非权威 Shadow 输出；`score-v1.4` 的项目分数与标签仍是主决策。

---

## 快速开始

### 前置要求

- Python 3.10+
- Node.js 18+（前端）
- Docker 20+（可选，容器化部署）

### 方式 1: 本地开发

```bash
# 1. 克隆仓库
git clone <repo-url>
cd Web3-Airdrop-Alpha-Agent-System

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env：本地可保持 APP_ENV=development。
# 若启用 API 鉴权，再设置：
#   API_KEY=<python -c "import secrets; print(secrets.token_urlsafe(32))">
#   AUTH_TOKEN_SECRET=<python -c "import secrets; print(secrets.token_urlsafe(48))">

# 3. 启动后端
cd backend
pip install -e ".[dev]"
python -m uvicorn app.main:app --host 0.0.0.0 --port 8002

# 4. 启动前端（另开终端）
cd frontend-next
npm install
npm run dev
```

### 方式 2: Docker 部署

```bash
# SQLite 模式（最简，开发测试）
docker compose up -d --build

# PostgreSQL 模式（数据量大时推荐）
docker compose --profile postgres up -d --build
# 在 .env 中设置 DB_BACKEND=postgres

# 生产全栈（Nginx + Next.js 前端 + PostgreSQL + 监控栈）
docker compose -f docker-compose.prod.yml up -d --build
```

> ⚠️ **生产部署必须用 `docker-compose.prod.yml`**，不是 `docker-compose.yml --profile production`。
>
> 区别：
> - `docker-compose.yml` 的 `--profile production` 只有 `backend` + `postgres` + `nginx`，
>   **没有 Next.js 前端服务**，挂的是根目录 `nginx.conf`（整站直连后端的纯 API 入口）。
>   起来后只有裸 API、没有 UI，且浏览器 API 请求会绕过前端代理拿不到凭据 → 全站 401。
> - `docker-compose.prod.yml` 才包含完整的 `frontend` 服务与生产 nginx 配置
>   （`docker/nginx/nginx-http.conf`），将 `/api/` 先转发给 Next.js，
>   由 `frontend-next/proxy.ts` 在服务端按请求路径分档注入凭据：
>   - 管理员端点（`/run`、`/settings/*`、`/watched-wallets` 等）注入 `X-API-Key`
>   - 其余只读端点（`/projects`、`/public-config` 等）注入匿名 Bearer token
>
> 生产环境还需在 `.env` 里设置以下必填项（详见 `docs/GO_LIVE_CHECKLIST.md`）：
> ```bash
> APP_ENV=production
> API_KEY=<至少 32 字符随机字符串>
> AUTH_TOKEN_SECRET=<至少 48 字符随机字符串>
> BACKEND_API_KEY=<与 API_KEY 同值>
> POSTGRES_PASSWORD=<强密码>
> CORS_ORIGINS=<实际前端域名>
> TRUSTED_PROXY_COUNT=1  # 按实际反代层数设置，见 GO_LIVE_CHECKLIST §1b
> ```

#### Docker 端口映射

宿主机端口采用 `1` 前缀方案（原端口前加 `1`），避免与其他项目冲突：

| 服务 | 宿主机 | 容器内 | 说明 |
|------|--------|--------|------|
| **Nginx 反向代理** | `18080` | 80 | 前端页面 + API 代理入口 |
| **前端 (Next.js)** | `13002` | 3002 | 可直连调试 |
| **Prometheus** | `19090` | 9090 | 指标查询 |
| **Grafana** | `13000` | 3000 | 监控面板登录 |
| **Loki** | `13100` | 3100 | 日志查询 API |

> 后端 API、PostgreSQL 位于 `backend` 内部网络，不暴露到宿主机。
> 可选服务（OTel Collector `14317`/`14318`/`18889`、Jaeger `11686`）需启用 `observability` profile。

### 方式 3: Windows 一键启动

```batch
Start.bat   :: 启动后端 + 前端
Stop.bat    :: 停止所有服务
```

### 访问地址

| 服务 | 地址 | 说明 |
|------|------|------|
| 前端 | http://localhost:3002 | Next.js 16 + React 19 |
| API 文档 | http://localhost:8002/docs | Swagger UI |
| API 参照 | http://localhost:8002/redoc | ReDoc |
| 健康检查 | http://localhost:8002/health | 本地后端健康探针 |
| 指标 | http://localhost:8002/metrics | 本地 Prometheus 格式指标 |

> 生产全栈的公网入口是 `http://<host>:18080`（TLS 由上游反代终止时）。
> 后端 API、PostgreSQL 和 `/metrics` 均不应直接暴露到公网：生产 nginx 对公网
> `/metrics` 返回 403，Prometheus 通过 Docker `backend` 网络直连 `airdrop-web:8002/metrics`。
> 查看生产指标请登录 Grafana，而不是公开 exporter。

## API 概览

主要端点：

### 核心操作

```bash
# 触发评分流水线（seed 数据）
curl -X POST http://localhost:8002/api/v1/run \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"source":"seed"}'

# 查询项目列表
curl -H "X-API-Key: $API_KEY" \
  "http://localhost:8002/api/v1/projects?sort_by=score&order=desc&limit=10"

# 触发采集
curl -X POST -H "X-API-Key: $API_KEY" \
  http://localhost:8002/api/v1/collections/defillama/trigger
```

### 主要端点分组

| 分组 | 端点 | 说明 |
|------|------|------|
| 评分 | `POST /api/v1/run` | 触发评分流水线 |
| 项目 | `GET/POST /api/v1/projects` | 项目 CRUD |
| 采集 | `GET/POST /api/v1/collections/{source}` | 采集源管理 + 手动触发 |
| Opportunity | `GET /api/v1/projects/{id}/opportunity` | Shadow 旁路评估 |
| 反馈 | `GET/POST /api/v1/feedback` | 人工反馈 + 权重校准输入 |
| 鉴权 | `POST /api/v1/auth/anonymous` | 匿名 Token 签发 |
| 观察列表 | `GET/POST /api/v1/watchlist` | 关注项目标记 |
| 隔离 | `GET /api/v1/quarantine` | 数据质量隔离管理 |
| 公开配置 | `GET /api/v1/public-config` | 匿名可读的权重与标签阈值 |
| 领取监控 | `GET/POST /api/v1/watched-wallets` | 自有地址到账监控（管理员锁） |
| 导入导出 | `GET /api/v1/export/*`, `POST /api/v1/import/*` | Excel/CSV 批量操作 |
| 校准 | `GET /api/v1/calibration/status` | 权重校准状态 |
| LLM | `GET /api/v1/llm/status` | LLM 增强状态 |
| 监控 | `GET /health`, `GET /metrics` | 健康检查 + Prometheus 指标（公网不暴露） |
| Webhook | `POST /api/v1/webhook/alchemy` | Alchemy 事件回调 |

完整 API 文档见 [docs/API_SPEC.md](docs/API_SPEC.md) 或运行时 `/docs`。

---

## 数据源

10 个采集器，按配置启用：

| 数据源 | 类型 | 默认 | 说明 |
|--------|------|------|------|
| DefiLlama | 免费 API | 启用 | TVL + 协议元数据 |
| GitHub | 免费 API | 启用 | 开发活跃度（建议设 Token 提升 60->5000 req/h） |
| CoinGecko | 免费 API | 启用 | 币种价格 + 市值 |
| CryptoRank | API Key | 启用 | 项目库 + 融资数据 |
| Etherscan | 免费 API | 启用 | 链上交互数据 |
| RootData | API Key | 禁用 | 项目库 + 融资数据 |
| Twitter KOL | Bearer Token | 禁用 | KOL/VC 动态 |
| Twitter Keywords | Bearer Token | 禁用 | 关键词监控 |
| Galxe | API Key | 禁用 | 活动数据 |
| Layer3 | API Key | 禁用 | 活动数据 |

采集器具备熔断器（`FETCHER_CIRCUIT_BREAKER`）、速率限制和跨源字段合并。调度器按 `CRON_EXPRESSION` 定时触发（默认每日 08:00 UTC）。

---

## 系统架构

```
┌──────────────────────────────────────────────────┐
│         Next.js 16 / React 19 Frontend          │
│              http://localhost:3002                │
└──────────────────┬───────────────────────────────┘
                   │ REST API (X-API-Key)
                   ▼
┌──────────────────────────────────────────────────┐
│              FastAPI Backend                      │
│           http://localhost:8002                    │
├──────────────────────────────────────────────────┤
│                                                   │
│  ┌─────────────┐   ┌──────────────────────┐      │
│  │  Collector   │   │  Unified Scheduler   │      │
│  │  Registry    │   │  (APScheduler)        │      │
│  │  (10 sources)│   │  cron + misfire      │      │
│  └──────┬──────┘   └──────────┬───────────┘      │
│         │                       │                  │
│         ▼                       ▼                  │
│  ┌──────────────────────────────────────┐         │
│  │     Multi-Agent Pipeline              │         │
│  │  ┌─────────┬─────────┬─────────┐      │         │
│  │  │Narrative│  Team   │  Risk   │      │         │
│  │  └─────────┴─────────┴─────────┘      │         │
│  │  ┌─────────────┬──────────────┐       │         │
│  │  │ Tokenomics  │AirdropSignal│       │         │
│  │  └─────────────┴──────────────┘       │         │
│  │            ▼                          │         │
│  │       Scorer (score-v1.4)             │         │
│  │            ▼                          │         │
│  │  Opportunity Shadow (v2.0)            │         │
│  └──────────────────────────────────────┘         │
│                     ▼                              │
│  ┌──────────────────────────────────────┐         │
│  │  Repository Pattern                   │         │
│  │  SQLite (WAL) / PostgreSQL             │         │
│  │  + Alembic Migrations                 │         │
│  └──────────────────────────────────────┘         │
└──────────────────────────────────────────────────┘
```

### Agent 流水线

```
Collector → [Narrative, Team, Risk, Tokenomics, AirdropSignal] → Scorer
                          (并行执行, Semaphore 限流)
                                   │
                                   ▼
                          Opportunity Shadow
                          (追加评估, 不修改主分)
```

- **Narrative**: 叙事时机分析（赛道热度 + 项目阶段）
- **Team**: 团队信誉分析（VC 背书 + 创始人）
- **Risk**: 风险评估（代币风险 + 解锁压力）
- **Tokenomics**: 代币经济学（分配比例 + 解锁周期）
- **AirdropSignal**: 空投信号检测（测试网 + 积分 + 融资）
- **Scorer**: `score-v1.4` 八维加权评分
- **Opportunity Shadow**: `opportunity-v2.0` 旁路评估，保存不可变经济快照

---

## 项目结构

```
Web3-Airdrop-Alpha-Agent-System/
├── backend/                    # 后端服务
│   ├── app/
│   │   ├── agents/             # 6 个 Agent + Orchestrator
│   │   ├── collectors/         # 10 个采集器 + Registry + Scheduler
│   │   ├── opportunity/        # Opportunity Shadow 旁路模型
│   │   │   └── calibration/    # 权重校准
│   │   ├── routers/v1/         # API 路由 (16 个模块)
│   │   ├── services/           # 业务服务层
│   │   ├── repositories/       # V2 数据访问层
│   │   ├── llm/                # LLM 客户端
│   │   ├── config.py           # Pydantic Settings
│   │   ├── db.py               # 数据库抽象层
│   │   ├── auth.py             # 鉴权中间件
│   │   ├── metrics.py          # Prometheus 指标
│   │   └── main.py             # FastAPI 入口
│   ├── alembic/                # 数据库迁移
│   ├── tests/                  # 测试套件
│   ├── scripts/                # 运维 + 校准脚本
│   ├── Dockerfile
│   └── pyproject.toml
├── frontend-next/              # Next.js 16 前端
│   ├── app/                    # App Router 页面
│   ├── components/             # React 组件
│   └── lib/                    # API 客户端 + 工具
├── configs/                    # 配置文件
│   ├── feature-flags/          # 功能开关
│   └── observability/          # Prometheus + Grafana + OTel
├── docker/                     # Docker 辅助配置
│   ├── loki/                   # 日志收集
│   └── nginx/                  # 反向代理
├── docs/                       # 技术文档
│   ├── adr/                    # 14 份 ADR
│   ├── ENGINEERING_ROADMAP.md
│   ├── API_SPEC.md
│   ├── DEPLOYMENT.md
│   ├── GO_LIVE_CHECKLIST.md
│   ├── GO_LIVE_REPORT.md
│   └── ...
├── scripts/                    # 运维脚本
│   └── deploy/                 # 部署 + 回滚脚本
├── docker-compose.yml          # SQLite 模式
├── docker-compose.postgres.yml # PostgreSQL 模式
├── docker-compose.prod.yml     # 生产全栈
├── .env.example                # 环境变量模板
├── Start.bat / Stop.bat        # Windows 一键启停
└── README.md                   # 本文件
```

---

## 配置

### 核心环境变量

复制 `.env.example` 到 `.env` 并配置：

| 变量 | 必填 | 默认 | 说明 |
|------|------|------|------|
| `APP_ENV` | 生产是 | development | 生产全栈 compose 会强制覆盖为 `production`，从而启用安全校验 |
| `API_KEY` | 生产是 | - | 后端管理员 API Key，至少 32 字符；空值会关闭后端鉴权 |
| `AUTH_TOKEN_SECRET` | 生产是 | - | 匿名 Bearer token 的签名密钥；生产为空会拒绝启动 |
| `BACKEND_API_KEY` | 生产前端是 | - | 必须与 `API_KEY` 同值；仅在 Next.js 服务端用于管理员端点，**不能**使用 `NEXT_PUBLIC_` 前缀 |
| `API_PROXY_TARGET` | 生产前端是 | `http://web:8002` | Next.js 构建期 rewrite 与运行期匿名 token 换取均使用此内网地址 |
| `CORS_ORIGINS` | 生产是 | localhost | 填实际前端域名；production 中包含 localhost / 127.0.0.1 会拒绝启动 |
| `TRUSTED_PROXY_COUNT` | 反代时是 | 0 | 本仓生产拓扑 nginx → web 填 `1`；每多一层受控反代加 `1` |
| `DB_BACKEND` | 否 | sqlite | `sqlite` 或 `postgres` |
| `DB_PATH` | SQLite 时 | data/airdrop.db | SQLite 文件路径 |
| `POSTGRES_PASSWORD` | PostgreSQL 时 | - | 强密码（至少 16 字符，不能用 `airdrop` / `postgres` 等占位符） |
| `OPENAI_API_KEY` | 否 | - | LLM 增强（不设则走规则引擎） |
| `LLM_DAILY_BUDGET_USD` | 否 | 1.0 | LLM 日费用上限，超出后拒绝调用并降级回规则引擎；`0` = 不限额 |
| `RATE_LIMIT_REQUESTS` | 否 | 100 | 每 60 秒单 IP 最大请求数 |
| `SEED_FALLBACK_ENABLED` | 否 | true | 采集全挂时使用内置种子；生产建议设为 `false`，避免仪表盘混入兜底数据 |

完整变量列表见 `.env.example`。

---

## 测试

```bash
cd backend

# 运行全部测试
pytest

# 按模块运行
pytest tests/agents/          # Agent 测试
pytest tests/api/             # API 端点测试
pytest tests/collectors/      # 采集器测试
pytest tests/opportunity/     # Opportunity Shadow 测试
pytest tests/golden/          # 金标准回归测试

# 生成覆盖率报告
pytest --cov=app --cov-report=html
```

测试基线以 CI 最新一次后端全量结果为准。本地建议：

```bash
cd backend
venv/Scripts/python.exe -m pytest --no-cov -p no:cacheprovider
```

近期 CI 已验证过 3292 passed / 5 skipped。

---

## 监控

### Prometheus 指标

本地开发可直接查看：

```bash
curl http://localhost:8002/metrics
```

生产全栈中 `/metrics` **不通过 nginx 向公网转发**（公网请求返回 403），避免暴露
项目数量、pipeline 成败、LLM 花费与采集源错误率等运行信息。Prometheus 已在 Docker
`backend` 网络内直连 `airdrop-web:8002/metrics`；外部监控请使用 Grafana 登录入口。

关键指标：

- `pipeline_runs_total` — 评分流水线运行次数
- `pipeline_run_duration_seconds` — 评分延迟
- `airdrop_fetcher_cache_hits_total` — 采集器缓存命中
- `airdrop_fetcher_circuit_breaker_state` — 熔断器状态
- `airdrop_competition_cache_hits_total` — 竞争度缓存命中

### 告警规则

预置 3 条告警（`configs/observability/prometheus/alert_rules.yml`）：

- `APIDown` — 服务不可用 (1m, critical)
- `HighAPIErrorRate` — 错误率 > 0.1/s (5m, critical)
- `PipelineConsecutiveFailures` — 15 分钟内 >= 2 次失败 (critical)

### Grafana

导入 `configs/observability/grafana/dashboard-system-overview.json` 查看系统概览面板。

---

## 部署

### 部署检查

上线前请按 [GO_LIVE_CHECKLIST.md](docs/GO_LIVE_CHECKLIST.md) 逐项检查，或查看 [GO_LIVE_REPORT.md](docs/GO_LIVE_REPORT.md) 获取最新检查结果。

### Docker 命令

```bash
docker build -t airdrop-alpha:latest -f docker/Dockerfile .

# SQLite 基础部署
docker compose up -d --build

# 仅启用基础 compose 的 PostgreSQL
docker compose --profile postgres up -d --build

# 生产全栈（推荐：Next.js + FastAPI + PostgreSQL + Nginx + 监控）
docker compose -f docker-compose.prod.yml up -d --build

# 查看生产日志
docker compose -f docker-compose.prod.yml logs -f web

# 生产健康检查
curl http://localhost:18080/health

# 停止生产全栈
docker compose -f docker-compose.prod.yml down
```

> 生产命令使用独立的 `docker-compose.prod.yml`，不要改写成
> `docker compose --profile production`。完整变量要求、限流验证、备份恢复与回滚流程见
> [docs/GO_LIVE_CHECKLIST.md](docs/GO_LIVE_CHECKLIST.md) 和 [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)。

### 数据库迁移

生产全栈的后端容器名为 `airdrop-web`：

```bash
# 应用迁移
docker exec airdrop-web alembic upgrade head

# 回滚
docker exec airdrop-web alembic downgrade -1
```

详细部署指南见 [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)。

---

## 技术栈

### 后端

- **框架**: FastAPI 0.115 + Pydantic 2.10
- **Python**: 3.10+
- **数据库**: SQLite (WAL 模式) / PostgreSQL（通过 `DB_BACKEND` 切换）
- **迁移**: Alembic
- **调度**: APScheduler (Unified Scheduler)
- **日志**: structlog (JSON, 脱敏)
- **指标**: prometheus-client
- **鉴权**: Bearer Token + API Key
- **限流**: 滑动窗口 + IP 限流

### 前端

- **框架**: Next.js 16 + React 19 + TypeScript
- **样式**: Tailwind CSS
- **图表**: 自建轻量图表库 (ADR-011)
- **构建**: 标准-next 构建

### 基础设施

- **容器**: Docker + docker-compose
- **反向代理**: Nginx (可选)
- **监控**: Prometheus + Grafana
- **日志收集**: Loki + Promtail (可选)
- **CI/CD**: GitHub Actions

---

## 文档

### 开发与部署

- [docs/ENGINEERING_ROADMAP.md](docs/ENGINEERING_ROADMAP.md) — 工程路线图
- [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) — 部署指南
- [docs/GO_LIVE_CHECKLIST.md](docs/GO_LIVE_CHECKLIST.md) — 上线检查清单
- [docs/GO_LIVE_REPORT.md](docs/GO_LIVE_REPORT.md) — 上线检查报告
- [docs/OPERATIONS.md](docs/OPERATIONS.md) — 运维手册
- [docs/SECURITY.md](docs/SECURITY.md) — 安全规范

### API 与数据

- [docs/API_SPEC.md](docs/API_SPEC.md) — API 规格说明
- [docs/DATA_SCORING_DICT.md](docs/DATA_SCORING_DICT.md) — 评分算法字典
- [docs/DATABASE_DDL.md](docs/DATABASE_DDL.md) — 数据库 DDL
- [docs/DATA_SOURCE_STRATEGY.md](docs/DATA_SOURCE_STRATEGY.md) — 数据源策略

### 架构决策

- [docs/adr/](docs/adr/) — 14 份架构决策记录
- [docs/V2_TASKS.md](docs/V2_TASKS.md) — V2 任务追踪

---

## 贡献

1. Fork 本仓库
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 开启 Pull Request

详见 [CONTRIBUTING.md](CONTRIBUTING.md) 和 [CONVENTIONS.md](CONVENTIONS.md)。

---

## 许可证

MIT License - 详见 [LICENSE](LICENSE)
