# Project Bootstrap 总览

> 本文档汇总项目工程基础设施（Project Bootstrap）18 个部分的落地文件，
> 作为进入业务开发前的最终索引。所有 P0/P1/P2 项均已完成。
>
> 更新日期：2026-07-08 · Bootstrap 版本：v2.0

---

## 18 部分落地索引

| 部分 | 主题 | 落地文件 / 目录 | 状态 |
| --- | --- | --- | --- |
| §1 | 项目目录初始化 | `README.md`, `backend/`, `frontend/`, `docs/`, `tests/`, `scripts/`, `configs/`, `docker/`, `infra/`, `database/`, `examples/`, `benchmark/`, `data/`, `logs/`, `backups/`, `agents/`, `skills/`, `prompts/`, `knowledge/`, `evaluation/`, `templates/` | ✅ |
| §2 | Documentation System | `docs/00_index.md`, `docs/01_product.md`, `docs/02_architecture.md`, `docs/ENGINEERING_ROADMAP.md`, `docs/API_SPEC.md`, `docs/FRONTEND_SPEC.md`, `docs/DATA_SCORING_DICT.md`, `docs/DATABASE_DDL.md`, `docs/SECURITY.md`, `docs/OBSERVABILITY.md`, `docs/OPERATIONS.md`, `docs/DATA_QUALITY.md`, `docs/GLOSSARY.md`, `docs/AI_DEV_WORKFLOW.md`, `docs/WORKFLOW_AUTOMATION.md` 等 | ✅ |
| §3 | ADR | `docs/adr/README.md`, `docs/adr/TEMPLATE.md`, `docs/adr/ADR-001` ~ `ADR-011` | ✅ |
| §4 | Knowledge Base | `knowledge/README.md`, `knowledge/faq.md`, `knowledge/business/`, `knowledge/technical/`, `knowledge/api/`, `knowledge/external/`, `knowledge/decisions/`, `knowledge/glossary/README.md` | ✅ |
| §5 | Knowledge Graph | `knowledge/README.md` 含 5 张 Mermaid 图（系统模块 / Agent / DB / Prompt / 配置关系） | ✅ |
| §6 | Git Strategy | `CONVENTIONS.md §11`（Branch / Commit / Version / Release / Tag / Review / Hotfix / Rollback） | ✅ |
| §7 | Coding Standards | `CONVENTIONS.md`, `.editorconfig`, `pyproject.toml`（ruff / mypy / pytest） | ✅ |
| §8 | AI Skills System | `skills/README.md`, `skills/*.md`（22 个 Skill） | ✅ |
| §9 | Agent System | `agents/README.md`, `agents/*/AGENT.md`（15 个 Agent） | ✅ |
| §10 | Prompt Management | `prompts/README.md`, `prompts/agents/*/*.json`, `prompts/system/*.json` | ✅ |
| §11 | Configuration Management | `.env.example`, `configs/development/`, `configs/staging/`, `configs/production/`, `configs/feature-flags/` | ✅ |
| §12 | Testing Framework | `tests/unit/`, `tests/contracts/`, `tests/golden/`, `tests/api/`, `tests/e2e/`, `tests/load/`, `tests/conftest.py`, `tests/README.md` | ✅ |
| §13 | Logging & Monitoring | `docs/OBSERVABILITY.md`, `docker/loki/`, `configs/observability/otel/`, `docker-compose.prod.yml` | ✅ |
| §14 | Security | `docs/SECURITY.md`, `skills/security-api-auth.md`, `skills/security-secret-scan.md`, `.github/workflows/security.yml` | ✅ |
| §15 | CI/CD | `.github/workflows/ci.yml`, `.github/workflows/security.yml`, `.github/workflows/release.yml`, `.github/workflows/docs.yml` | ✅ |
| §16 | Project Management | `.github/ISSUE_TEMPLATE/*.md`, `docs/risk_register.md`, `docs/decision_log.md`, `docs/sprint_template.md`, `docs/backlog_template.md`, `docs/meeting_notes_template.md`, `CHANGELOG.md`, `CONTRIBUTING.md` | ✅ |
| §17 | AI Development Workflow | `docs/AI_DEV_WORKFLOW.md` | ✅ |
| §18 | 最终检查 | `docs/PROJECT_BOOTSTRAP_CHECKLIST.md` | ✅ |

---

## 快速启动

```bash
# 1. 安装依赖
make setup

# 2. 环境配置
cp .env.example .env

# 3. 运行测试
make test

# 4. 启动开发服务
make dev

# 5. 启动完整监控栈（可选，P2）
docker compose --profile observability -f docker-compose.prod.yml up -d loki promtail otel-collector jaeger
```

---

## 关键约定

- **AI First**：无文档/ADR/Skill 不编码。
- **Git First**：所有变更通过 PR，使用 Conventional Commits。
- **文档驱动**：`docs/` 是设计真相源，`knowledge/` 是可引用知识库。
- **安全优先**：无密钥入仓库；所有环境变量走 `.env`。
- **渐进式验证**：每阶段完成后通过 CI / 测试 / Review 验收。

---

## 状态统计

| 级别 | 总计 | 完成 | 完成率 |
| --- | --- | --- | --- |
| P0 | 18 | 18 | 100% |
| P1 | 22 | 22 | 100% |
| P2 | 11 | 11 | 100% |
| **总计** | **51** | **51** | **100%** |

---

_文档版本：v2.0 · 2026-07-08_
