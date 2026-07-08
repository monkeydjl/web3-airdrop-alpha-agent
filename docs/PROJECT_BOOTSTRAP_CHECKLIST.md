# Project Bootstrap Checklist

> 基于 **Project Bootstrap Architect** 框架的 18 个部分，按优先级分级。
> 每项标记完成状态，方便持续跟踪项目初始化进度。
>
> 更新日期：2026-07-08（v1.4 架构师审查补充：AI 特有安全 / Git 完整策略 / 测试框架文档 / LLM 评估脚本）

---

## 状态图例

| 符号 | 含义 |
| --- | --- |
| ✅ 完成 | 已实现并通过验证 |
| 🔄 进行中 | 实现中，未完成 |
| ⬜ 未开始 | 未启动 |
| ❌ 阻塞 | 依赖未满足 |
| 🚫 不适用 | 当前阶段不需要 |

---

## P0（必须 — 项目启动的基础设施）

| # | 项 | 对应部分 | 状态 | 说明 |
| --- | --- | --- | --- | --- |
| 1 | 项目目录结构 | §1 | ✅ 完成 | 28+ 子目录，含 backend/app/ |
| 2 | 文档体系 | §2 | ✅ 完成 | `docs/` 下 20+ 份专项文档 |
| 3 | ADR 系统 | §3 | ✅ 完成 | 11 份 ADR（ADR-001 ~ ADR-011） |
| 4 | 编码规范 | §7 | ✅ 完成 | `CONVENTIONS.md`（17 节） |
| 5 | 日志与观测 | §13 | ✅ 完成 | `docs/OBSERVABILITY.md` |
| 6 | 安全规范 | §14 | ✅ 完成 | `docs/SECURITY.md`（含 §10 AI 特有安全：Prompt Injection / Tool Permission / Sandbox / Model Safety / Data Leakage） |
| 7 | `.env.example` | §11 | ✅ 完成 | 含全部配置项 + Feature Flags |
| 8 | `.gitignore` | §11 | ✅ 完成 | 涵盖 Python/Docker/IDE/OS/Data |
| 9 | CI/CD 流水线 | §15 | ✅ 完成 | ci.yml / security.yml / release.yml |
| 10 | PR 模板 | §6 | ✅ 完成 | 16 项自查清单 |
| 11 | Issue 模板 | §16 | ✅ 完成 | Bug Report + Feature Request + Meeting Notes |
| 12 | 测试骨架 | §12 | ✅ 完成 | `tests/` + `conftest.py` + `__init__.py` |
| 13 | 启动检查清单 | §18 | ✅ 完成 | 本文档 |
| 14 | pyproject.toml | §7 | ✅ 完成 | ruff/mypy/pytest/项目元数据 |
| 15 | .editorconfig | §7 | ✅ 完成 | 跨编辑器格式统一 |
| 16 | Makefile | §1 | ✅ 完成 | 开发常用命令 |
| 17 | 后端应用骨架 | §1 | ✅ 完成 | backend/app/ (config/db/main/models) |

---

## P1（强烈建议 — 工程体系完整所需）

| # | 项 | 对应部分 | 状态 | 说明 |
| --- | --- | --- | --- | --- |
| 1 | Knowledge Base | §4 | ✅ 完成 | `knowledge/README.md` + 知识图谱 + 详细知识文件（含 api/external） |
| 2 | Skills 系统 | §8 | ✅ 完成 | `skills/README.md` + 22 个实际 Skill 文件 |
| 3 | Agent 系统 | §9 | ✅ 完成 | `agents/README.md` + 15 个 Agent AGENT.md 定义 |
| 4 | Prompt 管理 | §10 | ✅ 完成 | `prompts/README.md` + 5 个 Prompt 模板文件 |
| 5 | AI 开发工作流 | §17 | ✅ 完成 | `docs/AI_DEV_WORKFLOW.md`（12 步） |
| 6 | 配置管理 | §11 | ✅ 完成 | `configs/` 分环境配置 |
| 7 | 数据库迁移 | §1 | ✅ 完成 | `database/README.md` + MVP/V2 策略 |
| 8 | Docker 生产配置 | §1 | ✅ 完成 | `docker/Dockerfile` + `nginx.conf` |
| 9 | 基础设施文档 | §1 | ✅ 完成 | `infra/README.md` + 部署架构图 |
| 10 | 设置与种子脚本 | §1 | ✅ 完成 | `scripts/setup.sh` + `scripts/seed.py` |
| 11 | 示例指南 | §1 | ✅ 完成 | `examples/README.md` + API 调用示例 |
| 12 | 性能基准 | §1 | ✅ 完成 | `benchmark/README.md` + 脚本目录 |
| 13 | Git 策略文档 | §6 | ✅ 完成 | `docs/GIT_STRATEGY.md`（完整 Version/Release/Tag/Hotfix/Rollback 流程）+ `CONVENTIONS.md §11` |
| 14 | CHANGELOG | §16 | ✅ 完成 | `CHANGELOG.md` |
| 15 | CONTRIBUTING | §6 | ✅ 完成 | `CONTRIBUTING.md` |
| 16 | 测试骨架可运行 | §12 | ✅ 完成 | `tests/` 含 unit/contracts/golden/api + 22 passed |
| 17 | 文档 00-15 编号索引 | §2 | ✅ 完成 | `docs/00_index.md` 编号映射 |
| 18 | 测试框架规范 | §12 | ✅ 完成 | `docs/TESTING_FRAMEWORK.md`（12 节，含 LLM Evaluation / Prompt Benchmark / Regression / 自动化测试规范） |
| 19 | LLM 评估脚本 | §12 | ✅ 完成 | `evaluation/llm/template_validation.py`（模板校验 + LLM 评估 + Benchmark，被多处 README 引用） |

---

## P2（可选 — 远期优化）

| # | 项 | 对应部分 | 状态 | 说明 |
| --- | --- | --- | --- | --- |
| 1 | 知识图谱可视化 | §5 | ✅ 完成 | `knowledge/README.md` 含 5 张 Mermaid 图 |
| 2 | Meeting Notes 模板 | §16 | ✅ 完成 | `.github/ISSUE_TEMPLATE/meeting_notes.md` + `docs/meeting_notes_template.md` |
| 3 | Feature Flags 系统 | §11 | ✅ 完成 | `configs/feature-flags/` |
| 4 | 版本发布策略 | §6 | ✅ 完成 | `release.yml` + `CONVENTIONS.md §11` |
| 5 | 文档链接校验 CI | §2 | ✅ 完成 | `.github/workflows/docs.yml` + `markdown-link-check.json` |
| 6 | 代码生成器模板 | §1 | ✅ 完成 | `templates/codegen/` + `scripts/codegen.py` |
| 7 | 日志集中采集（Loki） | §13 | ✅ 完成 | `docker/loki/` + `docker-compose.prod.yml` |
| 8 | OpenTelemetry 集成 | §13 | ✅ 完成 | `configs/observability/otel/` + `docker-compose.prod.yml` |

---

## 完整性统计

| 级别 | 总计 | 完成 | 未开始 | 完成率 |
| --- | --- | --- | --- | --- |
| **P0** | 17 | 17 | 0 | **100%** |
| **P1** | 19 | 19 | 0 | **100%** |
| **P2** | 8 | 8 | 0 | **100%** |
| **总计** | 44 | 44 | 0 | **100%** |

> ✅ P0 + P1 + P2 全部完成。Bootstrap 工程基础设施已达进入业务开发标准。
> v1.4 架构师审查补充：AI 特有安全（SECURITY.md §10）、完整 Git 策略（GIT_STRATEGY.md）、测试框架规范（TESTING_FRAMEWORK.md）、LLM 评估脚本（template_validation.py）。

---

## 新增文件清单（v1.4 架构师审查补充）

| 文件 | 用途 | 优先级 |
| --- | --- | --- |
| `docs/SECURITY.md` §10 | AI 特有安全（Prompt Injection / Tool Permission / Sandbox / Model Safety / Data Leakage / Agent 信任边界 / AI 安全测试清单） | P0 |
| `docs/GIT_STRATEGY.md` | 完整 Git 工作流（分支/提交/版本/发布/Tag/Code Review/Hotfix/Rollback/CHANGELOG） | P1 |
| `docs/TESTING_FRAMEWORK.md` | 测试框架规范（12 节：Unit/Contract/Golden/API/E2E/Load/LLM Eval/Prompt Benchmark/Regression/自动化规范） | P1 |
| `evaluation/llm/template_validation.py` | LLM 评估脚本（模板校验 + LLM 评估 + Benchmark + 阈值告警 + 历史指标） | P1 |

---

## 新增文件清单（v1.3 更新）

| 文件 | 用途 | 优先级 |
| --- | --- | --- |
| `pyproject.toml` | 项目元数据 + 工具配置 | P0 |
| `.env.example` | 环境变量完整模板 | P0 |
| `.gitignore` | Git 忽略规则 | P0 |
| `.editorconfig` | 跨编辑器格式统一 | P0 |
| `Makefile` | 开发常用命令 | P0 |
| `backend/app/__init__.py` | 包初始化 | P0 |
| `backend/app/config.py` | pydantic-settings 配置 | P0 |
| `backend/app/db.py` | 数据库访问层 | P0 |
| `backend/app/main.py` | FastAPI 应用入口 | P0 |
| `backend/app/models.py` | Pydantic 数据模型 | P0 |
| `configs/development/.env.development` | 开发环境配置 | P1 |
| `configs/staging/.env.staging` | 预发布环境配置 | P1 |
| `configs/production/.env.production` | 生产环境配置 | P1 |
| `agents/planner/AGENT.md` | Planner Agent 定义 | P1 |
| `agents/architect/AGENT.md` | Architect Agent 定义 | P1 |
| `agents/backend/AGENT.md` | Backend Agent 定义 | P1 |
| `skills/backend-fastapi-api.md` | FastAPI API Skill | P1 |
| `skills/testing-unit-test.md` | 单元测试 Skill | P1 |
| `skills/backend-agent-implementation.md` | Agent 实现 Skill | P1 |
| `prompts/agents/narrative/v1_heat_score.json` | Narrative Prompt | P1 |
| `prompts/agents/team/v1_team_analysis.json` | Team Prompt | P1 |
| `prompts/system/v1_orchestrator_planner.json` | Orchestrator Prompt | P1 |
| `knowledge/business/scoring-logic.md` | 评分业务知识 | P1 |
| `knowledge/technical/agent-pipeline.md` | Agent 流水线知识 | P1 |
| `knowledge/technical/concurrency.md` | 并发控制知识 | P1 |
| `CHANGELOG.md` | 变更日志 | P1 |
| `CONTRIBUTING.md` | 贡献指南 | P1 |
| `templates/codegen/README.md` | 代码生成器模板说明 | P2 |
| `templates/codegen/*.jinja` | FastAPI/Pydantic/Agent/Skill/Prompt 代码模板 | P2 |
| `scripts/codegen.py` | 代码生成器 CLI | P2 |
| `docker/loki/loki-config.yml` | Loki 配置 | P2 |
| `docker/loki/promtail-config.yml` | Promtail 采集配置 | P2 |
| `docker/loki/README.md` | Loki 使用文档 | P2 |
| `configs/observability/otel/otel-collector-config.yml` | OTel Collector 配置 | P2 |
| `configs/observability/otel/otel-instrumentation.json` | OTel 仪器化元数据 | P2 |
| `configs/observability/otel/README.md` | OpenTelemetry 使用文档 | P2 |
| `.github/ISSUE_TEMPLATE/task.md` | 任务 Issue 模板 | P1 |
| `docs/risk_register.md` | 风险登记表 | P1 |
| `docs/decision_log.md` | 决策日志 | P1 |
| `docs/sprint_template.md` | Sprint 模板 | P1 |
| `docs/backlog_template.md` | Backlog 模板 | P1 |
| `docs/meeting_notes_template.md` | 会议记录模板 | P1 |
| `tests/load/locustfile.py` | locust 负载测试 | P2 |
| `tests/e2e/test_e2e_pipeline.py` | 端到端测试 | P2 |
| `tests/README.md` | 测试体系说明 | P1 |

---

_文档版本：v1.4 · 2026-07-08_
