# ──────────────────────────────────────────────
# AI Skills System
# ──────────────────────────────────────────────
# 本目录管理可复用的 AI Skills，每个 Skill 是一组结构化的指令/模板，
# 用于指导 AI Agent 完成特定类型的任务。
#
# 目录结构（v1.1 — 已有实际文件的 Skill）：
#   skills/
#   ├── README.md                         # 本文档
#   ├── backend-fastapi-api.md            # ✅ FastAPI API 端点创建
#   ├── backend-agent-implementation.md   # ✅ Agent 类实现
#   ├── backend-pydantic-model.md         # ✅ Pydantic 模型定义
#   ├── testing-unit-test.md              # ✅ 单元测试编写
#   ├── frontend-nextjs-page.md           # ✅ Next.js 页面（V2）
#   ├── frontend-react-component.md       # ✅ React 组件（V2）
#   ├── database-sqlite-setup.md          # ✅ SQLite 建表
#   ├── database-alembic-migration.md     # ✅ Alembic 迁移（V2）
#   ├── security-api-auth.md              # ✅ API 鉴权（V2）
#   ├── security-secret-scan.md           # ✅ 密钥扫描
#   ├── performance-query-optimize.md      # ✅ 查询优化
#   ├── deployment-docker-setup.md        # ✅ Docker 构建
#   ├── deployment-ci-pipeline.md         # ✅ CI 流水线
#   ├── documentation-adr-create.md       # ✅ 编写 ADR
#   ├── api-rest-endpoint.md              # ✅ REST 端点
#   ├── llm-integration.md                # ✅ LLM 集成
#   ├── prompt-template.md                # ✅ Prompt 编写
#   ├── evaluation-ab-test.md             # ✅ A/B 测试（V2）
#   ├── debug-log-trace.md                # ✅ 日志追踪
#   ├── refactor-code-refactor.md         # ✅ 代码重构
#   ├── review-code-review.md             # ✅ 代码审查
#   └── architecture-adr-decision.md      # ✅ 架构决策
#
# 注：✅ 表示该 Skill 已有实际文件（共 22 个，与 `ls skills/*.md` 减去本文件一致）
#
# 本目录于 2026-09-04 做过一轮「与代码现状对齐」的清理：修掉了 `frontend/`（实际
# `frontend-next/`）、`tests/unit/`、`tests/contracts/`、`tests/perf/`、
# `backend/app/middleware/`、`backend/app/agents/prompts/`、`evaluation/experiments/`、
# `requirements.lock.txt`、`.gitleaks.toml`、`docs/DESIGN_GAP_ANALYSIS.md` 等
# **一批指向不存在路径的引用**，以及 React Testing Library 测试方案（项目根本没装）。
#
# 同一轮里还订正了三处「写法和代码对不上」的契约/命令：
#   - `BaseAgent.run()` 实为 `(self, state: PipelineState) -> PipelineState`，不是
#     `(context) -> AgentResult`（`backend-agent-implementation.md`）
#   - 日志事件前缀没有 `db.*`；`api.*` 真实存在但来自 `main.py`（`debug-log-trace.md`）
#   - 覆盖率只有 80% 一条线，没有「关键模块 ≥ 90%」；mypy 只跑 `app` 且非 `--strict`；
#     依赖没有 `.lock` 文件，门禁是 `test_requirements_pinning.py`（`review-code-review.md`）
#
# 再改这些文档时，请先用 `git ls-files` 确认路径真实存在，别凭印象写。
# ──────────────────────────────────────────────

---

## 1. 什么是 Skill？

Skill 是 AI Agent 的可复用行为模块，包含：

- **目标**：该 Skill 解决什么问题
- **输入**：需要什么信息/文件
- **步骤**：执行的具体步骤序列
- **输出**：生成的产物
- **检查清单**：完成后的验证项

---

## 2. Skill 模板

```markdown
# Skill：<名称>

## 目标
<一句话描述>

## 适用场景
- 场景 1
- 场景 2

## 输入要求
- 文件：<路径或类型>
- 信息：<需要的外部信息>

## 执行步骤

### Step 1: <步骤名>
- 操作：<详细说明>
- 验证：<如何确认完成>

### Step 2: <步骤名>
- ...

## 输出
- 文件：<生成的产物>
- 信息：<返回的信息>

## 检查清单
- [ ] 检查项 1
- [ ] 检查项 2

## 参考
- 相关文档链接
- 外部资源链接
```

---

## 3. Skills 目录

| 分类 | Skill 名称 | 用途 | 阶段 |
| --- | --- | --- | --- |
| **Backend** | `fastapi-api` | 创建 FastAPI 端点 | MVP |
| | `pydantic-model` | 定义 Pydantic 数据模型 | MVP |
| | `agent-implementation` | 实现 Agent 类 | MVP |
| **Frontend** | `nextjs-page` | 创建 Next.js 页面 | V2 |
| | `react-component` | 创建 React 组件 | V2 |
| **Database** | `sqlite-setup` | 配置 SQLite 连接与建表 | MVP |
| | `alembic-migration` | 创建 Alembic 迁移 | V2 |
| **Testing** | `unit-test` | 编写 pytest 单元测试 | MVP |
| **Security** | `api-auth` | 实现 API 鉴权 | V2 |
| | `secret-scan` | 密钥扫描配置 | MVP |
| **Performance** | `query-optimize` | SQL 查询优化 | V2 |
| **Deployment** | `docker-setup` | Docker 构建配置 | MVP |
| | `ci-pipeline` | CI 流水线配置 | MVP |
| **Documentation** | `adr-create` | 编写 ADR | MVP |
| **API** | `rest-endpoint` | 设计/实现 REST 端点 | MVP |
| **LLM** | `llm-integration` | LLM 集成与降级 | V2 |
| **Prompt** | `prompt-template` | 编写 Prompt 模板 | V2 |
| **Evaluation** | `ab-test` | 权重校准与效果评估 | V2 |
| **Debug** | `log-trace` | 日志追踪分析 | MVP |
| **Refactor** | `code-refactor` | 代码重构 | V2 |
| **Review** | `code-review` | 代码审查 | MVP |
| **Architecture** | `adr-decision` | 架构决策 | MVP |

> 契约测试与 golden 回归**没有独立 Skill 文件**：契约断言写在所属模块的测试里
> （见 `backend-pydantic-model.md`），golden 回归见
> `backend/tests/golden/test_golden_cases.py` 与 `refactor-code-refactor.md`。

---

## 4. Skill 命名规范

- 文件名：`<category>-<skill-name>.md`
- 示例：`backend-fastapi-api.md`, `testing-unit-test.md`
- 全小写 + 连字符

## 5. 引用规范

在 Prompt 中引用 Skill：

```markdown
使用 Skill: `backend/fastapi-api` 创建用户管理端点。
```

## 6. 生命周期

| 阶段 | 状态 | 说明 |
| --- | --- | --- |
| Draft | `draft` | 编写中，未验证 |
| Active | `active` | 已验证可用 |
| Deprecated | `deprecated` | 被新 Skill 替代 |
| Archived | `archived` | 不再使用 |

---

## 7. 维护约定

Skill 文档的价值全在**路径与命令是否真的能跑**。一条指向不存在目录的
"操作"比没有文档更糟：照着它写出来的代码会落在一个不被构建、不被测试的位置，
而且不报错。

改 Skill 前的三件事：

1. `git ls-files --full-name <路径>` 确认引用的文件/目录真实存在
2. 涉及命令的，实际跑一遍（后端统一用 `backend/venv/Scripts/python.exe -m ...`）
3. 涉及"项目有没有装某个工具"的，读 `package.json` / `requirements*.txt`，别凭印象

改完跑：

```bash
cd backend && ./venv/Scripts/python.exe -m pytest \
  tests/test_check_terminology.py tests/test_encoding_mojibake.py \
  --no-cov -p no:cacheprovider -q
```

---

_文档版本：v1.1 · 2026-09-04（路径对齐清理）_
