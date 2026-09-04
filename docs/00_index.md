# 文档体系总索引（00–15 编号体系）

> 本文档为 `docs/` 的编号化入口，对应 Project Bootstrap 第二部分"Documentation System"。
> 每个编号对应一类文档主题；右侧指向项目内实际文档（避免重复内容，仅做索引 + 模板锚点）。
>
> 更新日期：2026-07-13

---

## 编号映射

| 编号 | 主题 | 现有文档（索引） | 状态 |
| --- | --- | --- | --- |
| 00 | Project | [`Web3 Airdrop Alpha Agent System.md`](Web3 Airdrop Alpha Agent System.md)、`README.md`、[`CHANGELOG.md`](../CHANGELOG.md)、[`PHASES.md`](PHASES.md)（实现状态）、[`HANDOFF.md`](../HANDOFF.md) | ✅ |
| 01 | Product | [`01_product.md`](01_product.md)、[`USER_STORIES.md`](USER_STORIES.md) | ✅ |
| 02 | Architecture | [`02_architecture.md`](02_architecture.md)、[`ENGINEERING_ROADMAP.md`](ENGINEERING_ROADMAP.md) | ✅ |
| 03 | Backend | `backend/app/`（代码）+ `CONVENTIONS.md` | ✅ |
| 04 | Frontend | [`FRONTEND_SPEC.md`](FRONTEND_SPEC.md)、`DESIGN_TOKENS.md`、[`adr/ADR-013-nextjs-primary-frontend.md`](adr/ADR-013-nextjs-primary-frontend.md) | ✅ |
| 05 | Database | [`DATABASE_DDL.md`](DATABASE_DDL.md) | ✅ |
| 06 | API | [`API_SPEC.md`](API_SPEC.md) | ✅ |
| 07 | Agent | `agents/README.md` + `agents/*/AGENT.md` | ✅ |
| 08 | AI / LLM | [`adr/ADR-001-llm-default-off.md`](adr/ADR-001-llm-default-off.md)、`prompts/README.md`、[`WEIGHT_CALIBRATION.md`](WEIGHT_CALIBRATION.md) | ✅ |
| 09 | Deployment | [`DEPLOYMENT.md`](DEPLOYMENT.md)、`infra/README.md` | ✅ |
| 10 | Security | [`SECURITY.md`](SECURITY.md) | ✅ |
| 11 | Testing | [`TESTING_FRAMEWORK.md`](TESTING_FRAMEWORK.md)、`tests/`、[`GOLDEN_TEST_CASES.md`](GOLDEN_TEST_CASES.md) | ✅ |
| 12 | Operations | [`OPERATIONS.md`](OPERATIONS.md) | ✅ |
| 13 | Monitoring | [`OBSERVABILITY.md`](OBSERVABILITY.md) | ✅ |
| 14 | Decisions (ADR) | `docs/adr/`（ADR-001~013 + `TEMPLATE.md`） | ✅ |
| 15 | Changelog | [`CHANGELOG.md`](../CHANGELOG.md) | ✅ |
| 16 | Direction | [`SYSTEM_DIRECTION_CHANGE.md`](SYSTEM_DIRECTION_CHANGE.md)（v2.0 自动扫描）、[`DATA_SOURCE_STRATEGY.md`](DATA_SOURCE_STRATEGY.md)（自动采集视角）、[`ACTION_LOOP_DESIGN.md`](ACTION_LOOP_DESIGN.md)（V3 执行闭环设计稿） | ✅ |

> **2026-08-22 更正**：本表原先索引 6 个已在 `0966179`（移除遗留 HTML 原型与过时文件）
> 中删除的文档 —— `PROJECT_BOOTSTRAP_OVERVIEW.md`、`IMPLEMENTATION_STATUS.md`、
> `PROJECT_BOOTSTRAP_CHECKLIST_V2.md`、`PROJECT_BOOTSTRAP_AUDIT_REPORT_V2.md`、
> `COLLECTION_ANALYSIS_HANDOFF.md`、`DESIGN_REVIEW_CHANGELOG.md`。
> 索引却一直标着 ✅，是 CI 的 Docs Link Check 把它们查出来的。
> 实现状态现由 [`PHASES.md`](PHASES.md) 承担。

---

## 文档模板（新建同类文档时复制）

### 通用文档头模板

```markdown
# <标题>

> 引用：<关联 ADR / 文档>
> 阶段：MVP / V2 / V3
> 更新：YYYY-MM-DD

## 概述
<1–2 段说明>

## 正文
<分节>

---
_文档版本：v1.0 · YYYY-MM-DD_
```

### ADR 模板

见 [`docs/adr/TEMPLATE.md`](adr/TEMPLATE.md)。

### Skill 模板

见 [`skills/README.md`](../skills/README.md) §2。

### Agent 模板

见 [`agents/README.md`](../agents/README.md) §2。

或使用脚本自动生成：
```bash
./scripts/workflows/agent-create.sh "<agent-id>" "<Agent Name>"
```

### 项目管理模板

见 [`risk_register.md`](risk_register.md)、[`decision_log.md`](decision_log.md)、[`sprint_template.md`](sprint_template.md)、[`backlog_template.md`](backlog_template.md)、[`meeting_notes_template.md`](meeting_notes_template.md)。

### 工作流自动化

见 [`WORKFLOW_AUTOMATION.md`](WORKFLOW_AUTOMATION.md)。

---

## 文档规范（摘要）

- 使用 GitHub Flavored Markdown，代码块标注语言。
- 跨文档引用用相对路径（如 `docs/adr/ADR-007-...`）。
- 文档版本号标于文件末尾 `_文档版本：vX.Y_`。
- 变更文档须同步更新本索引与对应知识（`[KN:...]`）。

---

_文档版本：v2.0 · 2026-07-08_
