# Code Generator Templates

> 本目录保存项目代码生成器使用的 Jinja2 模板，用于从 schema 或元数据快速生成骨架代码。
> 与手写代码不同，生成器产物需经过 Reviewer 审查与 Tester 验证后方可合入。
>
> 优先级：P2（V2+ 逐步启用）

---

## 目录结构

```
templates/codegen/
├── README.md                      # 本文档
├── fastapi_crud.py.jinja          # FastAPI CRUD 端点
├── pydantic_model.py.jinja        # Pydantic 数据模型
├── agent_stub.py.jinja            # Agent 类骨架
├── skill_stub.md.jinja            # Skill 文档骨架
├── prompt_json.jinja             # Prompt JSON 骨架
└── config_yaml.jinja              # 配置 YAML 骨架
```

---

## 使用方式

```bash
python scripts/codegen.py --model Project --template fastapi_crud --output backend/app/routes
python scripts/codegen.py --model User --template pydantic_model --output backend/app/models
python scripts/codegen.py --agent narrative --template agent_stub --output backend/app/agents
python scripts/codegen.py --skill backend-fastapi-api --category backend --template skill_stub --output skills
```

---

## 命名规范

| 模板 | 用途 | 输出文件命名 |
| --- | --- | --- |
| `fastapi_crud.py.jinja` | 生成 REST 资源 CRUD 路由 | `{resource}_routes.py` |
| `pydantic_model.py.jinja` | 生成 Pydantic/数据模型 | `{model}.py` |
| `agent_stub.py.jinja` | 生成 Agent 类骨架 | `{agent}_agent.py` |
| `skill_stub.md.jinja` | 生成 Skill 文档骨架 | `{category}-{name}.md` |
| `prompt_json.jinja` | 生成 Prompt JSON 模板 | `v1_{key}.json` |
| `config_yaml.jinja` | 生成 YAML 配置片段 | `{name}.yml` |

---

## 模板变量

所有模板共享以下变量：

- `project_name`: 项目名称（从 `pyproject.toml` 读取）
- `module_name`: Python 模块名（snake_case）
- `timestamp`: 生成时间 ISO 8601
- `generator_version`: 生成器版本

各模板专有变量见模板头部注释。

---

## 安全约束

- 模板中不得包含密钥、Token、密码占位符。
- 生成代码后必须运行 `ruff check` 与 `pytest`。
- 禁止生成直接操作生产数据库或外部支付的代码。

---

_模板版本：v1.0 · 2026-07-08_
