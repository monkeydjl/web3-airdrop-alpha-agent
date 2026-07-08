# ──────────────────────────────────────────────
# Agent System
# ──────────────────────────────────────────────
# 本目录定义项目中所有 AI Agent 的职责、输入/输出、工具权限与交接规则。
# 目录中的每个子目录对应一个 Agent 角色。
#
# 目录结构（v1.1 — 已有详细定义的 Agent）：
#   agents/
#   ├── README.md               # 本文档
#   ├── planner/                # 任务规划 Agent ✅ AGENT.md
#   ├── architect/              # 架构设计 Agent ✅ AGENT.md
#   ├── backend/                # 后端开发 Agent ✅ AGENT.md
#   ├── researcher/             # 调研 Agent ✅ AGENT.md
#   ├── frontend/               # 前端开发 Agent ✅ AGENT.md
#   ├── database/               # 数据库 Agent ✅ AGENT.md
#   ├── devops/                 # DevOps Agent ✅ AGENT.md
#   ├── prompt/                 # Prompt Engineer Agent ✅ AGENT.md
#   ├── reviewer/               # Code Reviewer Agent ✅ AGENT.md
#   ├── security/               # 安全审查 Agent ✅ AGENT.md
#   ├── performance/            # 性能审查 Agent ✅ AGENT.md
#   ├── tester/                 # 测试 Agent ✅ AGENT.md
#   ├── release/                # 发布管理 Agent ✅ AGENT.md
#   ├── documentation/          # 文档编写 Agent ✅ AGENT.md
#   └── knowledge/              # 知识管理 Agent ✅ AGENT.md
#
# 注：✅ AGENT.md 表示该 Agent 已有详细定义文件
# ──────────────────────────────────────────────

---

## 1. Agent 设计原则

1. **单一职责**：每个 Agent 只负责一个领域，不跨域。
2. **明确契约**：输入/输出有 schema，交接有格式约束。
3. **工具受限**：每个 Agent 只能访问其职责范围内的文件和工具。
4. **可审计**：所有 Agent 操作记录日志，可追溯。
5. **互不阻塞**：Agent 间异步协作，不互相等待。

---

## 2. Agent 通用模板

```markdown
# Agent：<角色名>

## 职责
<一句话描述该 Agent 的核心职责>

## 输入
- 输入 schema / 格式说明

## 输出
- 输出 schema / 格式说明

## 限制
- 不能修改的文件/目录
- 不能运行的危险命令

## 工具
- 允许使用的工具列表

## 允许修改的文件
- 特定目录或文件列表

## 禁止修改的文件
- 特定目录或文件列表

## 交接规则
- 输出交给谁（下一个 Agent）
- 接收格式要求
```

---

## 3. Agent 角色目录

| Agent | 职责 | 输入 | 输出 |
| --- | --- | --- | --- |
| **Planner** | 将用户需求拆解为可执行的步骤计划 | 用户需求描述 | 步骤列表（含依赖/预估工时） |
| **Architect** | 设计系统架构、选型技术栈 | 需求文档 | 架构图、ADR、技术选型 |
| **Researcher** | 调研技术方案、库、API、最佳实践 | 调研问题 | 调研报告（含引用） |
| **Backend** | 后端代码实现（Python/FastAPI） | 功能需求 + 架构设计 | 实现代码 + 测试 |
| **Frontend** | 前端代码实现（Next.js/React） | UI 设计 + API 契约 | 前端组件 + 页面 |
| **Database** | 数据库设计、迁移、查询优化 | 数据模型需求 | DDL、迁移脚本、调优建议 |
| **DevOps** | 部署、CI/CD、容器化、监控 | 部署需求 | Dockerfile、CI 配置、监控面板 |
| **Prompt** | 编写、优化、评估 LLM Prompt | Agent 需求 | Prompt 模板 + 评估报告 |
| **Reviewer** | 代码审查、质量把关 | PR 代码 | Review 报告（问题列表 + 建议） |
| **Security** | 安全审查、漏洞扫描 | 代码/配置 | 安全报告（漏洞 + 修复建议） |
| **Performance** | 性能分析、优化建议 | 代码/基准数据 | 性能报告 + 优化方案 |
| **Tester** | 编写测试、维护回归集 | 功能/架构 | 测试代码 + 测试报告 |
| **Release** | 发布管理、版本控制 | 发布计划 | 发布检查清单 + 上线确认 |
| **Documentation** | 编写、维护项目文档 | 功能/变更 | 文档更新 |
| **Knowledge** | 管理知识库、FAQ、Glossary | 知识更新需求 | 知识库更新 |

---

## 4. 交接规则

### 4.1 通用交接格式

Agent 间交接使用结构化消息：

```json
{
  "from": "agent_name",
  "to": "next_agent_name",
  "task_id": "uuid",
  "status": "completed|failed|blocked",
  "artifacts": {
    "files": ["path/to/file"],
    "decisions": ["summary of decisions"],
    "pending": ["open questions"]
  },
  "context": {
    "summary": "brief summary of what was done",
    "risks": ["identified risks"]
  }
}
```

### 4.2 典型工作流

```
User Request
    │
    ▼
Planner ──→ Architect ──→ Researcher ──→ Backend/Frontend/DB ──→ Tester
    │                                            │
    └──────────────────────────────────────────────┘
                                                        │
                                                        ▼
                                                    Reviewer ──→ Security ──→ Performance
                                                        │
                                                        ▼
                                                    Release ──→ Documentation
                                                        │
                                                        ▼
                                                    Knowledge (更新知识库)
```

### 4.3 异常处理

- Agent 失败 → 记日志 + 通知上游 Agent 重新计划
- 输入不完整 → 拒绝执行 + 返回具体缺失字段
- 输出验证失败 → 重新生成（最多 3 次）
- 超出权限 → 记录告警 + 请求管理员介入

---

## 5. 安全约束

- Agent 只能使用分配的工具和文件权限。
- 禁止 Agent 运行 `rm -rf`、`git push`、`sudo` 等危险命令（除非显式授权）。
- Agent 生成的内容不得包含密钥、Token、密码。
- Agent 之间的通信需要经过审计日志记录。

---

_文档版本：v1.0 · 2026-07-08_
