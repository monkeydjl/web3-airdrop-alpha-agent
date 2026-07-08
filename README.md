# Web3 Airdrop Alpha Agent System

> 多智能体驱动的 Web3 早期项目识别与空投参与决策系统。当前处于 **设计阶段**，工程基础设施 v2.0 已完成，实现代码即将启动。

---

## 1. 一句话介绍

一个基于 **多 Agent 系统** 的 Web3 早期项目机会识别工具：每天自动发现新项目、评估空投潜力、给出 `FARM` / `WATCH` / `IGNORE` 三档建议，并解释为什么。

---

## 2. 项目边界（明确不做什么）

| 不做什么 | 说明 |
| --- | --- |
| 不保证收益 | 输出仅作决策参考，不构成投资建议 |
| 不执行交易 | v1/v2 不操作链上资金或钱包 |
| 不自动 farming | 仅输出可执行 checklist，不代用户操作 |
| 不做 KYC/托管 | 不接触用户资产或私钥 |

---

## 3. 文档地图

设计阶段产物统一放在 `docs/`。按读者角色选择入口：

| 文档 | 读者 | 内容 |
| --- | --- | --- |
| [`docs/ENGINEERING_ROADMAP.md`](docs/ENGINEERING_ROADMAP.md) | 全角色 | 工程路线图、排期、架构、数据模型、ADR 索引 |
| [`docs/API_SPEC.md`](docs/API_SPEC.md) | 后端/前端 | REST API 契约、错误码、版本策略 |
| [`docs/DATA_SCORING_DICT.md`](docs/DATA_SCORING_DICT.md) | 算法/后端 | 评分 6 子项、权重、reason 生成规则 |
| [`docs/FRONTEND_SPEC.md`](docs/FRONTEND_SPEC.md) | 前端 | Dashboard 页面、状态、组件、交互 |
| [`docs/DATABASE_DDL.md`](docs/DATABASE_DDL.md) | 后端/数据 | 表结构、索引、V2 增量 DDL |
| [`docs/USER_STORIES.md`](docs/USER_STORIES.md) | 产品/前端 | 用户故事与验收标准 |
| [`docs/TASK_BREAKDOWN.md`](docs/TASK_BREAKDOWN.md) | 项目管理 | W1–W12 任务、依赖、验收门 |
| [`docs/GAP_ANALYSIS.md`](docs/GAP_ANALYSIS.md) | 架构/全角色 | 18 部分框架差距分析 |
| [`docs/AI_DEV_WORKFLOW.md`](docs/AI_DEV_WORKFLOW.md) | 全角色 | AI 协作开发工作流（12 步） |
| [`docs/PROJECT_BOOTSTRAP_CHECKLIST_V2.md`](docs/PROJECT_BOOTSTRAP_CHECKLIST_V2.md) | 项目管理 | P0/P1/P2 启动检查清单（v2.0） |
| [`docs/PROJECT_BOOTSTRAP_AUDIT_REPORT_V2.md`](docs/PROJECT_BOOTSTRAP_AUDIT_REPORT_V2.md) | 架构/全角色 | v2.0 审计与补充报告 |
| [`docs/01_product.md`](docs/01_product.md) | 产品/全角色 | 产品规格（编号体系 01） |
| [`docs/02_architecture.md`](docs/02_architecture.md) | 架构/全角色 | 系统架构（编号体系 02，含 C4 模型） |
| [`docs/WORKFLOW_AUTOMATION.md`](docs/WORKFLOW_AUTOMATION.md) | 开发/运维 | 工作流自动化脚本指南 |
| [`docs/GOLDEN_TEST_CASES.md`](docs/GOLDEN_TEST_CASES.md) | 算法/测试 | 16 条评分回归黄金用例 |
| [`docs/PERFORMANCE_BENCHMARK.md`](docs/PERFORMANCE_BENCHMARK.md) | 性能/测试 | 性能基准、压测场景 |
| [`docs/DESIGN_TOKENS.md`](docs/DESIGN_TOKENS.md) | 前端/设计 | 颜色、字体、间距、图表规范 |
| [`docs/DESIGN_REVIEW_CHANGELOG.md`](docs/DESIGN_REVIEW_CHANGELOG.md) | 全角色 | 设计评审、变更、决策记录 |
| [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) | 运维/后端 | 部署、环境、Docker、迁移 |
| [`docs/OBSERVABILITY.md`](docs/OBSERVABILITY.md) | 运维/后端 | 日志、指标、告警、Grafana 面板 |
| [`docs/SECURITY.md`](docs/SECURITY.md) | 安全/合规 | 威胁模型、鉴权、密钥、事件响应 |
| [`docs/DATA_QUALITY.md`](docs/DATA_QUALITY.md) | 数据/后端 | 6 维质量框架、quarantine、SLA |
| [`docs/OPERATIONS.md`](docs/OPERATIONS.md) | 运维/值班 | 日周月检查、故障手册、回滚 |
| [`docs/GLOSSARY.md`](docs/GLOSSARY.md) | 全角色 | 业务/技术/角色术语统一 |
| [`docs/adr/README.md`](docs/adr/README.md) | 架构/全角色 | 11 份架构决策记录（ADR-001~011） |

---

## 4. 当前阶段

- **阶段**：设计阶段（v1.3）→ 工程基础设施 v2.0 ✅
- **状态**：文档体系已闭环，工程基础设施已全面完成，核心组件已实现
- **下一步**：MVP 代码实现（W1–W4，见 `TASK_BREAKDOWN.md`）

项目工程基础设施现状（详见 [`docs/PROJECT_BOOTSTRAP_CHECKLIST_V2.md`](docs/PROJECT_BOOTSTRAP_CHECKLIST_V2.md)）：
- **P0（必须）**：18/18 ✅ 100%
- **P1（强烈建议）**：22/22 ✅ 100%
- **P2（可选）**：11/11 ✅ 100%
- **总计**：51/51 ✅ 100%

**v2.0 核心新增：**
- ✅ Agent 编排器核心实现（orchestrator.py + 测试）
- ✅ 完整架构文档（01_product + 02_architecture）
- ✅ 工作流自动化（7 个脚本）
- ✅ 生产部署脚本（部署 + 回滚）
- ✅ 监控配置完善（Grafana Dashboard + Prometheus 告警）
- ✅ Prompt 工程知识库

---

## 5. 项目工程基础设施

### 5.1 目录结构

```
.
├── .github/                   # GitHub 配置
│   ├── workflows/             # CI/CD 流水线
│   │   ├── ci.yml             # Lint → Test → Build → Smoke
│   │   ├── security.yml       # pip-audit + Trivy + secret scan
│   │   └── release.yml        # 版本发布 + SBOM
│   ├── PULL_REQUEST_TEMPLATE.md
│   └── ISSUE_TEMPLATE/        # Bug / Feature / Meeting 模板
├── agents/                    # Agent 系统文档 + 详细定义
├── backend/                   # 后端应用代码
│   └── app/
│       ├── __init__.py        # 包初始化
│       ├── config.py          # pydantic-settings 配置
│       ├── db.py              # 数据库访问层
│       ├── main.py            # FastAPI 应用入口
│       └── models.py          # Pydantic 数据模型
├── benchmark/                 # 性能基准
├── configs/                   # 分环境配置
│   ├── development/           # 开发环境
│   ├── staging/               # 预发布环境
│   ├── production/            # 生产环境
│   └── feature-flags/         # Feature Flags
├── data/                      # 运行时数据（gitignored）
├── database/                  # 数据库迁移指南
├── docker/                    # Docker + Nginx 配置
├── docs/                      # 完整文档体系
├── evaluation/                # 评估相关
├── examples/                  # 使用示例
├── frontend/                  # 前端应用（V2）
├── infra/                     # 基础设施文档
├── knowledge/                 # 知识库 + 知识图谱
│   ├── business/              # 业务知识
│   └── technical/             # 技术知识
├── logs/                      # 运行时日志
├── prompts/                   # Prompt 管理系统
│   ├── agents/                # Agent 级 Prompt
│   └── system/                # 系统级 Prompt
├── scripts/                   # 设置与种子脚本
├── skills/                    # AI Skills 系统
├── tests/                     # 测试骨架
│   ├── unit/                  # 单元测试
│   ├── contracts/             # 契约测试
│   ├── golden/                # Golden 回归
│   └── api/                   # API 测试
├── .editorconfig              # 编辑器格式统一
├── .env.example               # 环境变量模板
├── .gitignore                 # Git 忽略规则
├── CHANGELOG.md               # 变更日志
├── CONVENTIONS.md             # 编码规范（17 节）
├── CONTRIBUTING.md            # 贡献指南
├── docker-compose.prod.yml    # 生产编排
├── Makefile                   # 开发常用命令
├── pyproject.toml             # 项目元数据 + 工具配置
└── README.md                  # 本文档
```

### 5.2 关键配置文件

| 文件 | 用途 |
| --- | --- |
| [`pyproject.toml`](pyproject.toml) | 项目元数据、ruff/mypy/pytest 配置 |
| [`.env.example`](.env.example) | 全量环境变量模板 |
| [`.editorconfig`](.editorconfig) | 跨编辑器格式统一 |
| [`Makefile`](Makefile) | 开发常用命令（dev/test/lint/format） |
| [`CONVENTIONS.md`](CONVENTIONS.md) | 编码规范（17 节） |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | 贡献指南 |
| [`CHANGELOG.md`](CHANGELOG.md) | 变更日志 |

### 5.3 关键新增文档（v2.0）

| 文档 | 说明 |
| --- | --- |
| [`docs/PROJECT_BOOTSTRAP_AUDIT_REPORT_V2.md`](docs/PROJECT_BOOTSTRAP_AUDIT_REPORT_V2.md) | v2.0 完整审计与补充报告 |
| [`docs/01_product.md`](docs/01_product.md) | 产品规格文档（编号体系 01） |
| [`docs/02_architecture.md`](docs/02_architecture.md) | 系统架构文档（C4 模型 + Mermaid 图） |
| [`docs/WORKFLOW_AUTOMATION.md`](docs/WORKFLOW_AUTOMATION.md) | 工作流自动化指南 |
| [`backend/app/agents/orchestrator.py`](backend/app/agents/orchestrator.py) | Agent 编排器核心实现 |
| [`scripts/workflows/`](scripts/workflows/) | 7 个工作流自动化脚本 |
| [`scripts/deploy/`](scripts/deploy/) | 生产部署与回滚脚本 |
| [`configs/observability/grafana/`](configs/observability/grafana/) | Grafana Dashboard 配置 |
| [`configs/observability/prometheus/`](configs/observability/prometheus/) | Prometheus 告警规则 |
| [`knowledge/technical/prompt-engineering.md`](knowledge/technical/prompt-engineering.md) | Prompt 工程最佳实践 |

## 6. 快速开始

```bash
# 开发者快速开始
# 1. 查看 v2.0 完整审计报告
cat docs/PROJECT_BOOTSTRAP_AUDIT_REPORT_V2.md

# 2. 查看 AI 开发工作流
cat docs/AI_DEV_WORKFLOW.md

# 3. 一键设置开发环境
make setup

# 4. 创建新 Feature 分支
./scripts/workflows/git-new-feature.sh "your-feature-name"

# 5. 创建新 Agent（自动生成文档+代码+测试）
./scripts/workflows/agent-create.sh "agent-id" "Agent Name"

# 6. 快速验证（Pre-commit）
./scripts/workflows/quick-check.sh

# 7. 启动开发服务器
make dev

# 8. 运行测试
make test

# 9. 代码检查
make lint
make format-check
make typecheck

# 运维快速开始
# 1. 部署生产环境
./scripts/deploy/production.sh "1.0.0"

# 2. 查看健康状态
curl http://localhost:8000/health

# 3. 查看监控面板
open http://localhost:3000  # Grafana

# 4. 回滚（如需）
./scripts/deploy/rollback.sh
```

---

## 7. 技术栈（MVP）

| 层 | 选型 |
| --- | --- |
| 语言 | Python 3.11+ |
| Web 框架 | FastAPI |
| Agent 编排 | 自研轻量 Orchestrator（接口对齐 LangGraph） |
| 数据层 | SQLite（WAL 模式） |
| 前端 | 单页 HTML+JS（MVP 预览）；V2 切 Next.js |
| 调度 | APScheduler 进程内 / 外部 cron 触发 `POST /run` |
| 配置 | 环境变量 + `.env`（pydantic-settings） |
| 部署 | Docker + docker-compose |
| 观测 | structlog + Prometheus 指标（V2 完整接入） |
| Lint/Format | ruff |
| Type Check | mypy（strict mode） |
| Test | pytest + pytest-asyncio + pytest-cov |

---

## 8. 关键决策（ADR）

| ADR | 决策 | 状态 |
| --- | --- | --- |
| [ADR-001](docs/adr/ADR-001-llm-default-off.md) | MVP 默认关闭 LLM，可选插件 | Accepted |
| [ADR-002](docs/adr/ADR-002-self-built-orchestrator.md) | 自研轻量 Orchestrator | Accepted |
| [ADR-003](docs/adr/ADR-003-single-page-html-mvp.md) | MVP 前端用单页 HTML | Accepted |
| [ADR-004](docs/adr/ADR-004-sqlite-to-postgres.md) | MVP 用 SQLite，V2 切 PostgreSQL | Accepted |
| [ADR-005](docs/adr/ADR-005-apscheduler-inprocess.md) | 调度用 APScheduler 进程内 | Accepted |
| [ADR-006](docs/adr/ADR-006-weights-freeze.md) | 评分权重初值冻结 | Accepted |
| [ADR-007](docs/adr/ADR-007-multi-project-concurrency.md) | 多项目并发模型 | Accepted |
| [ADR-008](docs/adr/ADR-008-user-system.md) | 用户系统与多租户隔离 | Accepted |
| [ADR-009](docs/adr/ADR-009-api-versioning.md) | API 版本管理策略 | Accepted |
| [ADR-010](docs/adr/ADR-010-competition-cache.md) | 竞争度缓存与增量计数 | Accepted |
| [ADR-011](docs/adr/ADR-011-mvp-chart-library.md) | MVP Dashboard 图表库选型 | Accepted |

---

## 9. 贡献与反馈

- 设计阶段问题请在 `docs/DESIGN_REVIEW_CHANGELOG.md` 或通过 GitHub Issues 追踪
- 实现阶段使用 [PR 模板](.github/PULL_REQUEST_TEMPLATE.md) + 16 项自查清单
- 详细贡献指南见 [`CONTRIBUTING.md`](CONTRIBUTING.md)

---

## 10. 许可证

[MIT License](LICENSE)

---

_文档版本：v2.1 · 2026-07-08 · 设计阶段 v1.3 + 工程基础设施 v2.0 完成_
