# 编码规范（Coding Conventions）

> 配套文档：ENGINEERING_ROADMAP.md、API_SPEC.md、DATA_SCORING_DICT.md。本文档定义项目的编码风格、命名约定、模块组织、测试规范与工具配置，所有贡献者在实现前应通读并遵守。
>
> 适用阶段：MVP → V2 → V3 全周期。随着技术栈演进（如 V2 引入 Next.js），相应补充前端规范。

---

## 1. 语言与运行时

| 项 | 约定 |
|---|---|
| **语言** | Python 3.11+（后端）；TypeScript 5.x（V2 前端 Next.js） |
| **包管理** | `pip` + `pyproject.toml`（MVP）；`npm` / `pnpm`（V2 前端） |
| **依赖锁定** | `pyproject.toml` + `requirements.lock.txt`（由 `pip-compile` 生成，V2 引入） |
| **环境变量** | `.env` → `pydantic-settings` 读取，`.env.example` 维护模板 |

---

## 2. 目录结构

 严格遵循 [ENGINEERING_ROADMAP.md §4](ENGINEERING_ROADMAP.md) 定义的最终形态目录结构：

> **实现状态（2026-07-09 更新）**：下方为**实际已存在的 MVP 文件结构**（手动输入方向）。路由 `/api/v1/run`、`/api/v1/projects`、`/api/v1/export_import` 已在 `main.py` 注册，agents 目录已落地（`base/collector/narrative/team/risk/tokenomics/scorer/orchestrator/orchestrator_simple`）。

```
backend/app/
├── __init__.py
├── main.py              # FastAPI app + 路由注册（/api/v1/run, /api/v1/projects, /api/v1/export_import）
├── config.py            # pydantic-settings 配置
├── models.py            # Pydantic 数据模型
├── db.py                # SQLite 数据层
├── repository.py        # 数据访问层（projects 读写封装）
├── export.py            # 项目导出（CSV/JSON）
├── import_utils.py      # 项目导入工具
├── openapi.py           # OpenAPI 自定义配置
├── agents/
│   ├── __init__.py
│   ├── base.py           # BaseAgent + RawProject + PipelineState + AgentContext
│   ├── collector.py
│   ├── narrative.py
│   ├── team.py
│   ├── risk.py
│   ├── tokenomics.py
│   ├── scorer.py
│   ├── orchestrator.py
│   └── orchestrator_simple.py  # 串行处理多项目
├── routers/
│   └── v1/
│       ├── __init__.py
│       ├── run.py          # POST /api/v1/run（ProjectInput + RunRequest）
│       ├── projects.py     # GET /api/v1/projects
│       └── export_import.py # /api/v1/export_import 导出导入
└── utils/
    ├── __init__.py
    ├── fetcher.py         # 统一 fetcher（缓存/重试/熔断）
    └── normalize.py       # 归一化/去重工具
```

> 注：以下为 V2 规划，尚未实现（勿假定其已存在）：`seed.py`（演示种子）、`scheduler.py`（APScheduler）、`backtest.py`（权重回测）、`cache.py`（竞争度缓存，ADR-010）、`auth.py` + `middleware/`（鉴权，V2+）、`agents/prompts/`（prompt 版本化）。
>
> **v2.0 更新（ADR-012，系统方向反转）**：系统从"手动输入为主"转为"自动扫描为主"。以下文件为 v2.0 计划实现，勿假定已存在：
> - `backend/app/collectors/`（DefiLlama/GitHub/CoinGecko/Twitter/Chain/Quest/CryptoRank Collector）
> - `backend/app/utils/rate_limiter.py`（采集速率限制器，令牌桶）
> - `backend/app/http_client.py`（统一 HTTP 出口，域名白名单校验）
> - `backend/app/scheduler/collection_scheduler.py`（采集调度器，独立于分析调度器）
> - 采集表（`data_sources`/`raw_projects`/`project_signals`/`collection_logs`，见 DATABASE_DDL.md §2.13-2.16）
> - 采集相关 API 端点（`/api/v1/discoveries`、`/api/v1/collections/*`，见 API_SPEC.md §16-21）
>
> 手动输入路径（`POST /api/v1/run`）保留为补充能力，覆盖采集盲区。详见 `SYSTEM_DIRECTION_CHANGE.md` 与 `DATA_SOURCE_STRATEGY.md`。

- 不在 `backend/app/` 根目录存放业务逻辑文件（仅 `main.py` 例外）。
- `tests/` 目录镜像 `backend/app/` 结构。
- 前端代码严格隔离在 `frontend/`，不混入后端目录。

---

## 3. 命名约定

### 3.1 Python

| 类型 | 约定 | 示例 |
|---|---|---|
| 模块/包 | `snake_case` | `collector.py`, `risk.py` |
| 类 | `PascalCase` | `NarrativeAgent`, `ScoreResult` |
| 函数/方法 | `snake_case` | `normalize_name()`, `get_sector_count()` |
| 变量 | `snake_case` | `heat_score`, `dedup_key` |
| 常量 | `UPPER_SNAKE_CASE` | `SECTOR_ALIAS`, `DEFAULT_TTL` |
| 私有方法/变量 | 前导 `_` | `_dedup_key()`, `_cache` |
| 类型变量 | `T`, `TKey`, `TValue` | — |
| 异常类 | `PascalCase` + `Error` 后缀 | `AgentError`, `ConfigValidationError` |

### 3.2 TypeScript（V2 前端）

| 类型 | 约定 | 示例 |
|---|---|---|
| 文件 | `PascalCase`（组件）/ `camelCase`（工具） | `ProjectCard.tsx`, `api.ts` |
| 组件函数 | `PascalCase` | `function StatCard()` |
| 接口/类型 | `PascalCase` | `interface ProjectRecord` |
| 变量/函数 | `camelCase` | `fetchProjects()`, `sectorCount` |
| 枚举 | `PascalCase`，值 UPPER_SNAKE | `enum Label { FARM = "FARM" }` |

### 3.3 数据库

| 类型 | 约定 | 示例 |
|---|---|---|
| 表名 | `snake_case` 复数 | `projects`, `logs`, `feedback` |
| 列名 | `snake_case` | `project_id`, `heat_score` |
| 索引 | `idx_<表名>_<列名>` | `idx_projects_score`, `idx_logs_run` |
| 触发器 | `trg_<表名>_<操作>` | `trg_projects_updated` |

### 3.4 API

| 类型 | 约定 | 示例 |
|---|---|---|
| 路径 | `snake_case` + 名词复数 | `/api/v1/projects`, `/api/v1/project/{id}` |
| Query 参数 | `snake_case` | `?label=FARM&sector=L2&limit=50` |
| JSON 字段 | `snake_case` | `"project_id"`, `"heat_score"` |

> JSON 字段统一 `snake_case`，与 Python 数据模型一致，无需 camelCase 转换。

---

## 4. 导入规范

### 4.1 导入顺序

按以下分组，组间空一行：

```python
# 1) Python 标准库
import hashlib
import time
from collections import OrderedDict
from dataclasses import dataclass

# 2) 第三方库
import structlog
from fastapi import FastAPI, Request
from pydantic import BaseModel, Field

# 3) 项目内部模块
from app.config import Settings, WeightsConfig
from app.models import RawProject, ScoreResult

# 4) 类型导入（仅在类型检查时使用）
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from app.db import Database
```

### 4.2 导入风格

- 优先用 `from x import y` 而非 `import x`（减少命名空间污染）。
- 避免 `from x import *`。
- 类型导入仅在需要运行时引用的类/函数时用 `TYPE_CHECKING` guard。

---

## 5. 类型注解

### 5.1 强制规则

- **所有函数必须标注参数类型与返回类型**。例外：`main.py` 启动逻辑和 `__init__.py`。
- **所有 Pydantic 模型的字段必须标注类型**。
- `Optional[X]` 优先用 `X | None`（Python 3.10+ 语法）。
- 复杂类型用 `type alias` 提高可读性：

```python
ProjectId: TypeAlias = str
SectorName: TypeAlias = str
RawSignals: TypeAlias = dict[str, Any]
```

### 5.2 返回类型约定

| 场景 | 返回类型 |
|---|---|
| 成功/失败都有意义 | `Result[T, E]` 或 `tuple[T, Error \| None]` |
| 可能返回 None | `T \| None` |
| 异步函数 | `async def func() -> T:` |
| 不返回值 | `-> None`（void） |
| Generator | `Generator[T, None, None]` 或 `AsyncGenerator[T]` |

### 5.3 Pydantic 模型严格模式

```python
class NarrativeResult(BaseModel):
    model_config = ConfigDict(
        frozen=True,         # 不可变，防运行时修改
        extra="forbid",      # 禁止额外字段
        str_strip_whitespace=True,
        validate_default=True,
    )
    sector: str = Field(..., description="标准赛道名")
    stage: str = Field(..., pattern=r"^(early|growth|peak|mature)$")
    heat_score: float = Field(..., ge=0.0, le=1.0)
    timing: str = Field(..., pattern=r"^(early|peak|late)$")
```

---

## 6. 代码风格

### 6.1 格式化

- 使用 **ruff** 格式化（相当于 Black + isort 的超集）。
- 行宽 **120 字符**。
- 在 `pyproject.toml` 中锁定配置：

```toml
[tool.ruff]
line-length = 120
target-version = "py311"

[tool.ruff.lint]
# S = bandit 安全规则（对齐 SECURITY.md §8.1：禁 eval/exec、禁硬编码密钥、禁弱哈希）
select = ["E", "F", "I", "N", "W", "UP", "B", "SIM", "ARG", "RUF", "S"]

[tool.ruff.format]
quote-style = "double"
indent-style = "space"
docstring-code-format = true
```

### 6.2 字符串引号

- Python：双引号 `"`（与 ruff 默认一致）。
- SQL：双引号 `"`（标识符），单引号 `'`（字符串字面量）。
- JSON：双引号 `"`（标准 JSON 强制）。

### 6.3 文档字符串

所有公开 API（函数、类、模块）必须有 docstring：

```python
def get_sector_count(db, sector: str) -> int:
    """查询指定赛道的项目计数。

    使用竞争度缓存（若启用），miss 时回退 COUNT(*)。
    
    Args:
        db: 数据库连接对象。
        sector: 标准化赛道名（`ENGINEERING_ROADMAP.md` §6.2.1 sector_key）。
    
    Returns:
        该赛道的项目计数。缓存 miss 时走 COUNT 查询。
    
    Raises:
        DatabaseError: 数据库不可用时抛出。
    """
    ...
```

- 使用 Google-style docstring（sphinx 兼容）。
- 单元测试不需要 docstring（但需有清晰的方法名）。

### 6.4 注释

- 注释用中文或英文均可，但同一文件内保持一致。
- **不要注释显而易见的事**（如 `# 加 1` → `i += 1` 旁边的注释）。
- 注释应回答"为什么这样写"，而非"写了什么"。
- TODO 注释格式：`# TODO(#issue): <描述>`。

---

## 7. 错误处理

### 7.1 Agent 错误

所有 Agent 通过 `AgentError` 错误对象传递异常信息，不抛出未被捕获的异常：

```python
@dataclass
class AgentError:
    project_id: str
    agent_name: str
    kind: str          # llm_fallback | pipeline_error | timeout | schema_error
    message: str
    recoverable: bool = True
```

- Agent 内始终用 `try/except` 包裹可能失败的操作。
- 不可恢复错误（如 DB 不可写）向上抛出，由 Orchestrator 捕获。

### 7.2 API 错误

- 业务异常用 HTTPException + 语义化状态码。
- 不抛裸 `500` —— 统一用 `{ "ok": false, "error": { "code": ..., "message": ... } }` 包络。
- 校验错误（422）由 Pydantic 自动处理。
- 未捕获异常由全局 `@app.exception_handler(Exception)` 捕获，记录完整 trace 后返回 500。

### 7.3 外部调用错误

- fetcher 层统一处理 `requests.RequestException`。
- 4xx 不重试（401/403/404/429 各走对应路径）。
- 5xx 指数退避重试，`base=1s, factor=2, max=30s, cap=3`。

---

## 8. 异步与并发

### 8.1 async/await

- 所有 I/O 操作（DB、HTTP 请求、LLM 调用）用 `async/await`。
- CPU 密集型操作（评分公式、归一化）保持同步，不用 `asyncio.to_thread`（除非 >100ms）。
- API 端点统一 `async def`。

### 8.2 并发控制

- 多项目并发使用 `asyncio.Semaphore`（V2），**绝不**手动 `asyncio.gather` N 个不受限任务。
- LLM 调用使用独立 `llm_semaphore`，与项目并发数解耦。
- 单项目内 4 个 agent 始终用 `asyncio.gather` 并行（无依赖）。
- 参考 [ADR-007](docs/adr/ADR-007-multi-project-concurrency.md) 三级并行模型。

### 8.3 线程安全

- SQLite 连接默认单写者（通过 `threading.Lock` 串行化写入）。
- 进程内缓存（如 `SectorCountCache`）访问不跨协程，无竞态——但仍需注意 `asyncio` 下的协程切换点。

---

## 9. 测试规范

### 9.1 目录结构

```
tests/
├── unit/           # 单元测试（每个 Agent + Scorer + Collector）
│   ├── test_narrative.py
│   ├── test_team.py
│   ├── test_scorer.py
│   └── ...
├── contracts/      # 契约测试（Pydantic 模型校验）
│   ├── test_narrative_contract.py
│   └── ...
├── golden/         # Golden 回归快照
│   ├── projects.jsonl
│   └── test_golden.py
└── api/            # API 集成测试
    ├── test_run.py
    ├── test_projects.py
    └── ...
```

### 9.2 命名与结构

- 测试文件：`test_<模块名>.py`
- 测试类：`Test<模块名>`（可选，仅当需 setup/teardown 时用）
- 测试函数：`test_<功能>_<场景>_<预期>`，例如：
  - `test_score_layerx_returns_67_watch()`
  - `test_normalize_removes_suffix()`
  - `test_run_with_invalid_source_returns_400()`
- 每个测试函数只测一个行为（一个 assert 或一组逻辑相关的 assert）。

### 9.3 Mock 策略

- 外部 API 调用（DefiLlama/Twitter/Dune）使用 `unittest.mock.patch` 或 pytest `monkeypatch`。
- fetcher 单元测试中 mock `requests.Session`，**不**发起真实 HTTP。
- Agent 单元测试用纯 Python dict 作为输入，不依赖 DB。
- Orchestrator 集成测试使用 Test SQLite（`:memory:` 或临时文件）。

### 9.4 Fixture 约定

```python
# conftest.py
@pytest.fixture
def db() -> Generator:
    """提供内存 SQLite 数据库，测试间自动清理"""
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA journal_mode=WAL")
    init_db(conn)           # 建表
    yield conn
    conn.close()

@pytest.fixture
def sample_project() -> RawProject:
    """标准测试项目"""
    return RawProject(
        id="test-uuid",
        name="LayerX",
        sector="L2",
        stage="testnet",
        raw_signals={"has_points": True, "airdrop_hint": True},
    )

@pytest.fixture
def app_client(db) -> TestClient:
    """FastAPI 测试客户端"""
    from app.main import create_app
    app = create_app(db_override=db)
    return TestClient(app)
```

### 9.5 覆盖率要求

- MVP：行覆盖率 ≥ 80%，关键模块（`agents/`、`scorer.py`、`orchestrator.py`、`db.py`）≥ 90%。
- CI 覆盖率下降 >3% 告警（不阻断 PR，供 review）。

### 9.6 可解释性测试

每个 FARM 项目 `reason` ≥2 条且含 ≥1 正向信号。
每个 IGNORE 项目含 ≥1 反向信号。
缺失字段场景必含对应 `"* missing/uncertain"` 标记。
`meta.missing_count ≥ 3` 时 label 必降一档。

---

## 10. 日志规范

### 10.1 structlog 约定

```python
import structlog

logger = structlog.get_logger(__name__)

# 使用
logger.info("agent.run.completed",
    run_id=run_id,
    project_id=project.id,
    agent_name=self.name,
    duration_ms=elapsed_ms,
)

logger.warning("agent.llm.fallback",
    run_id=run_id,
    project_id=project.id,
    agent_name=self.name,
    error=str(e),
)

logger.error("pipeline.write.failed",
    run_id=run_id,
    project_id=project.id,
    exc_info=True,  # 仅 error 级别包含 traceback
)
```

### 10.2 键命名规范

| 域 | 键前缀 | 示例 |
|---|---|---|
| Pipeline | `pipeline.*` | `pipeline.start`, `pipeline.complete` |
| Agent | `agent.*` | `agent.run.start`, `agent.run.completed` |
| Fetcher | `fetcher.*` | `fetcher.call`, `fetcher.cache_hit` |
| LLM | `llm.*` | `llm.call.start`, `llm.fallback` |
| DB | `db.*` | `db.query`, `db.write` |
| API | `api.*` | `api.request.start`, `api.request.completed` |

- 事件名使用 `.` 分隔的层级结构，动词用过去式（`completed`、`failed`）。
- 日志事件名统一小写 + `.` 分隔，**不**用驼峰或空格。

### 10.3 敏感数据

- 日志中禁止记录：API Key、密码、token、私钥。
- 外部源响应中含敏感字段时需在 structlog 配置中 `redact`。

---

## 11. Git 规范

### 11.1 分支策略

| 分支 | 用途 | 源 |
|---|---|---|
| `main` | 生产就绪代码 | — |
| `feat/*` | 新功能分支 | main |
| `fix/*` | Bug 修复 | main |
| `docs/*` | 文档更新 | main |
| `perf/*` | 性能优化 | main |
| `release/v*` | 发布分支 | main |

- 禁止直接向 `main` 推送。所有变更通过 PR + review。
- PR 标题格式：`<type>(<scope>): <简短描述>`，例如 `feat(scorer): add competition cache`。

### 11.2 Commit Message

```
<type>(<scope>): <简短描述>

<详细说明（可选）>

Closes #<issue>
```

| type | 含义 |
|---|---|
| `feat` | 新功能 |
| `fix` | Bug 修复 |
| `docs` | 文档 |
| `refactor` | 重构 |
| `test` | 测试 |
| `chore` | CI/构建/杂项 |
| `perf` | 性能优化 |

### 11.3 文件变更原则

- 一个 PR 只做一件事（单一职责）。
- 不要在同个 PR 中混入重构和新功能。
- 代码变动前先更新对应测试。
- 若修改了 Pydantic 模型，必须先更新契约测试。

---

## 12. 配置管理

```python
# config.py — pydantic-settings 集中管理
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 应用
    port: int = 8000
    debug: bool = False
    db_path: str = "data/airdrop.db"
    api_key: str = ""                     # 空 = 无鉴权（MVP 模式）

    # 评分权重（Σ=1.0，启动时断言）
    weight_airdrop_signal: float = 0.20
    weight_narrative_timing: float = 0.20
    weight_team_reputation: float = 0.15
    weight_risk: float = 0.15
    weight_tokenomics: float = 0.15
    weight_competition: float = 0.15

    # 并发（ADR-007 / V2）
    max_concurrent_projects: int = 10
    llm_semaphore_size: int = 5

    # LLM（ADR-001）
    openai_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    daily_budget_usd: float = 1.0

    # 调度（ADR-005）
    cron_expression: str = "0 8 * * *"

    def model_post_init(self, __context):
        """启动时断言权重和为 1.0"""
        total = sum([
            self.weight_airdrop_signal,
            self.weight_narrative_timing,
            self.weight_team_reputation,
            self.weight_risk,
            self.weight_tokenomics,
            self.weight_competition,
        ])
        assert abs(total - 1.0) < 0.001, f"Weights sum to {total}, expected 1.0"
```

- 配置组可拆分为嵌套模型（`WeightsConfig`、`ConcurrencyConfig`、`LLMConfig`），但建议启动时统一加载 `Settings` 单例。
- 所有环境变量在 `.env.example` 中有定义。
- 敏感配置（API Key）**不入库、不打印、不记日志**。

---

## 13. 数据库访问模式

### 13.1 SQLite（MVP）

```python
# db.py — 使用原生 sqlite3，直接执行 SQL
import sqlite3

def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect("data/airdrop.db")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn

def init_db(conn: sqlite3.Connection) -> None:
    """幂等建表"""
    conn.executescript(DATABASE_DDL)  # 来自 DATABASE_DDL.md
    conn.commit()
```

- 使用 `?` 占位符传参，**绝不** f-string 拼接 SQL（防 SQL 注入）。
- 批量写入使用 `executemany` + 事务显式 `BEGIN/COMMIT`。

### 13.2 事务边界

- analyze 阶段不开启事务（防长事务锁表）。
- Write 阶段 `BEGIN/COMMIT` 包裹 `projects` 表 upsert（参考 `ENGINEERING_ROADMAP.md` §6.9.12）。
- logs 表写入允许孤立行（业务上可接受），不参与事务。

---

## 14. Prometheus 指标命名

遵循 `airdrop_<层>_<名称>_<单位>` 模式：

| 层 | 前缀 | 示例 |
|---|---|---|
| Pipeline | `airdrop_pipeline_*` | `airdrop_pipeline_run_duration_seconds` |
| Agent | `airdrop_agent_*` | `airdrop_agent_duration_seconds` |
| Fetcher | `airdrop_fetcher_*` | `airdrop_fetcher_errors_total` |
| LLM | `airdrop_llm_*` | `airdrop_llm_calls_total` |
| DB | `airdrop_db_*` | `airdrop_db_write_errors_total` |
| API | `airdrop_api_*` | `airdrop_api_request_duration_seconds` |
| 并发 | `airdrop_concurrency_*` | `airdrop_concurrency_active_projects` |
| 缓存 | `airdrop_competition_cache_*` | `airdrop_competition_cache_hits_total` |
| 版本 | `airdrop_api_version_*` | `airdrop_api_version_calls_total` |
| 数据质量 | `airdrop_quality_*` | `airdrop_quality_completeness` |

- 后缀 `_total` 用于 counter，`_seconds` 用于 histogram/gauge 的时间类指标。
- 标签（labels）小写 + 下划线，如 `source`, `agent_name`, `sector`。

---

## 15. 文档规范

### 15.1 代码内文档

- 公开函数/类必须有 docstring（Google style）。
- Pydantic 模型字段用 `Field(description=...)` 提供描述。
- Agent 的 `run()` 方法必须标注输入上下文与输出格式。

### 15.2 doc/ 目录文档

- `.md` 文件使用 GitHub Flavored Markdown。
- 跨文档引用使用相对路径链接（`[ADR-007](docs/adr/ADR-007-...)`）。
- 代码块标注语言（`\`\`\`python`、`\`\`\`sql`、`\`\`\`json`）。
- 文档版本号标在文件末尾（`_文档版本：v1.x`）。

---

## 16. 代码审查清单

提交 PR 前自查：

- [ ] 所有新代码有对应的测试（单元/契约/golden/API）
- [ ] 测试通过：`pytest -q --cov` 全绿，覆盖率不下降
- [ ] lint 通过：`ruff check .` + `ruff format --check .`
- [ ] 类型检查通过：`mypy . --strict`（V2 启用）
- [ ] 无 `print()` / `input()` / 调试断点残留
- [ ] Pydantic 模型变更时同步更新了契约测试
- [ ] API 变更时同步更新了 API_SPEC.md
- [ ] 环境变量变更时同步更新了 `.env.example`
- [ ] 新增外部依赖时同步更新 `requirements.txt` + `.lock.txt`
- [ ] `AgentError.kind` 新增枚举时同步更新了文档
- [ ] 日志事件名遵循 `层级.动词过去式` 格式

---

## 17. 参考与延伸

| 文档 | 内容 |
|---|---|
| [ENGINEERING_ROADMAP.md](ENGINEERING_ROADMAP.md) | 完整工程路线图与技术设计 |
| [API_SPEC.md](docs/API_SPEC.md) | REST API 详细规范 |
| [DATA_SCORING_DICT.md](docs/DATA_SCORING_DICT.md) | 评分算法与数据字典 |
| [DATABASE_DDL.md](docs/DATABASE_DDL.md) | 数据库完整 DDL |
| [TASK_BREAKDOWN.md](docs/TASK_BREAKDOWN.md) | 按周任务分解 |
| [docs/adr/](docs/adr/) | 架构决策记录（ADR-001~011） |

---

_文档版本：v1.0 · 配套 ENGINEERING_ROADMAP.md · 实现阶段按本规范执行。_
