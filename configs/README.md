# Configs — 配置管理

> 本目录管理项目的配置文件模板与环境配置。
> 参考：`CONVENTIONS.md §12`（配置管理规范）、`.env.example`

---

## 目录结构

```
configs/
├── README.md               # 本文档
├── development/            # 开发环境配置
│   └── .env.development
├── staging/                # 预发布环境配置
│   └── .env.staging
├── production/             # 生产环境配置
│   └── .env.production
├── feature-flags/          # Feature Flags 配置
│   ├── flags.dev.json
│   └── flags.prod.json
└── observability/          # 可观测性配置（P2）
    └── otel/               # OpenTelemetry Collector + 仪器化元数据
        ├── otel-collector-config.yml
        ├── otel-instrumentation.json
        └── README.md
```

> 注：Docker Compose 文件位于仓库根目录（`docker-compose.prod.yml` 等），
> 不在本目录下。本目录仅管理环境变量与 Feature Flags 配置。

---

## 配置分层

项目遵循 [12-Factor App](https://12factor.net/config) 配置管理原则：

1. **代码默认值**：`config.py` 中定义的默认值（最低优先级）
2. **`.env` 文件**：本地开发环境变量覆盖
3. **环境变量**：容器/Docker 运行时注入（最高优先级）

---

## 环境配置

| 环境 | 配置文件 | 数据库 | LLM | 外部源 |
| --- | --- | --- | --- | --- |
| **development** | `configs/development/` | SQLite（`data/airdrop.db`） | 关（规则引擎） | 种子数据 |
| **staging** | `configs/staging/` | PostgreSQL（staging） | 开（有限调用） | 全部（mock 降级） |
| **production** | `configs/production/` | PostgreSQL（prod） | 开（有预算控制） | 全部 |

---

## Feature Flags

```json
{
  "llm_enhancement": {
    "enabled": false,
    "description": "LLM 增强（仅 OPENAI_API_KEY 非空时生效）"
  },
  "feedback_system": {
    "enabled": false,
    "description": "用户反馈系统（V2）"
  },
  "events_tracking": {
    "enabled": false,
    "description": "隐式行为埋点（V2）"
  },
  "user_system": {
    "enabled": false,
    "description": "多用户系统（V3）"
  },
  "competition_cache": {
    "enabled": true,
    "description": "竞争度子分缓存（ADR-010）"
  }
}
```

Feature Flags 在 `.env` 中以 `ENABLE_*` 前缀配置，由 `backend/app/config.py` 读取并全局生效（`flags.*.json` 为各环境的声明镜像，键集需与 config.py 的 `enable_*` 字段保持一致）。

> 当前 config.py 支持的 Flag 键：`llm_enhancement` / `feedback_system` / `events_tracking` / `user_system` / `competition_cache`（共 5 项）。

---

_文档版本：v1.0 · 2026-07-08_
