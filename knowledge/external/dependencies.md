# 外部依赖知识

> 引用键：`KN:external:sqlite` / `KN:external:fastapi` / `KN:external:structlog` / `KN:external:pydantic` / `KN:external:apscheduler`
> 来源：`backend/requirements.txt`、`docs/adr/`
> 更新：2026-07-08

## 核心依赖

| 依赖 | 版本 | 用途 | 选型依据 |
| --- | --- | --- | --- |
| fastapi | >=0.110 | REST 框架 | ADR-002 自研编排 |
| pydantic / pydantic-settings | v2 | 数据模型 + 配置 | 严格校验、frozen 模型 |
| structlog | latest | 结构化日志 | CONVENTIONS.md §10 |
| sqlite3 | stdlib | MVP 存储 | ADR-004（V2 迁 Postgres） |
| apscheduler | >=3.10 | 进程内调度 | ADR-005 |
| uvicorn | latest | ASGI 服务器 | FastAPI 官方推荐 |

## 依赖锁定

- MVP：由 `backend/requirements.txt` 声明。
- V2：引入 `pip-compile` 生成 `requirements.lock.txt`。

## 安全约束

- 依赖审计：`pip-audit`（CI security.yml）。
- 禁止引入未评审的 transitive 重型依赖。

## 参考

- `docs/adr/ADR-002-self-built-orchestrator.md`
- `docs/adr/ADR-004-sqlite-to-postgres.md`
- `docs/adr/ADR-005-apscheduler-inprocess.md`
