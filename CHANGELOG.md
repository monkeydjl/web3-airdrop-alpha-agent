# Changelog

> 所有显著变更均记录在此文件。
> 格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)，
> 版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

---

## [Unreleased]

### Added
- 工程基础设施完整搭建（P0/P1 全部完成）
- `pyproject.toml` — 项目元数据 + ruff/mypy/pytest 配置
- `.env.example` — 全量环境变量模板
- `.gitignore` — 完整的忽略规则
- `.editorconfig` — 跨编辑器格式统一
- `Makefile` — 开发常用命令
- `backend/app/` — FastAPI 应用骨架（config/db/main/models）
- `agents/` — 15 个详细 Agent 定义文件（Planner/Architect/Backend/Researcher/Frontend/Database/DevOps/Prompt/Reviewer/Security/Performance/Tester/Release/Documentation/Knowledge）
- `skills/` — 21 个实际 Skill 模板（backend/frontend/database/security/performance/deployment/documentation/api/llm/prompt/evaluation/debug/refactor/review/architecture）
- `prompts/` — 5 个 Prompt 模板文件（Narrative/Team/Risk/Tokenomics/Orchestrator）
- `knowledge/` — 业务和技术知识文件（business/technical/api/external/decisions）
- `configs/` — 分环境配置文件（dev/staging/prod）+ Feature Flags
- `tests/` — 可运行测试骨架（unit/contracts/golden/api，22 passed）
- `docs/00_index.md` — 00–15 编号体系文档索引
- `.github/workflows/docs.yml` — 文档链接校验 CI

---

## [0.1.0] - 2026-07-08

### Added
- 完整设计文档体系（20+ 份文档）
- 11 份 ADR（ADR-001 ~ ADR-011）
- 编码规范（`CONVENTIONS.md`，17 节）
- API 规范（`docs/API_SPEC.md`）
- 评分数据字典（`docs/DATA_SCORING_DICT.md`）
- 数据库 DDL（`docs/DATABASE_DDL.md`）
- 前端规范（`docs/FRONTEND_SPEC.md`）
- 用户故事（`docs/USER_STORIES.md`）
- 任务分解（`docs/TASK_BREAKDOWN.md`）
- 部署文档（`docs/DEPLOYMENT.md`）
- 可观测性设计（`docs/OBSERVABILITY.md`）
- 安全规范（`docs/SECURITY.md`）
- 数据质量框架（`docs/DATA_QUALITY.md`）
- 运维手册（`docs/OPERATIONS.md`）
- 性能基准（`docs/PERFORMANCE_BENCHMARK.md`）
- Golden 测试用例（`docs/GOLDEN_TEST_CASES.md`）
- 设计令牌（`docs/DESIGN_TOKENS.md`）
- 术语表（`docs/GLOSSARY.md`）
- Agent 系统（`agents/README.md`）
- Skills 系统（`skills/README.md`）
- Prompt 管理（`prompts/README.md`）
- 知识库（`knowledge/README.md`）
- CI/CD 流水线（ci.yml / security.yml / release.yml）
- PR 模板 + Issue 模板
- 测试骨架（`tests/` + `conftest.py`）
- Docker 配置（Dockerfile + nginx）
- AI 开发工作流（`docs/AI_DEV_WORKFLOW.md`）
- 项目启动检查清单（`docs/PROJECT_BOOTSTRAP_CHECKLIST.md`）

---

## [0.0.1] - 2026-07-07

### Added
- 项目初始化
- README.md 基础结构
- 基础目录结构

---

[Unreleased]: https://github.com/web3-airdrop-alpha/web3-airdrop-alpha-agent/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/web3-airdrop-alpha/web3-airdrop-alpha-agent/compare/v0.0.1...v0.1.0
[0.0.1]: https://github.com/web3-airdrop-alpha/web3-airdrop-alpha-agent/releases/tag/v0.0.1
