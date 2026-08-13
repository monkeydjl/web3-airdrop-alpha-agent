# Web3 Airdrop Alpha Agent System — 工程 Roadmap

> 本文档是基于《Web3 Airdrop Alpha Agent System（完整版工程方案）》拆解出的**可执行的工程路线图**。
> 目标：把一份"方案/PPT 级"的设计，转成"团队拿到就能开工"的实施计划。
> 适用范围：MVP → V2 → V3 全周期。**实现状态**：W1–W4 已完成（见 [`IMPLEMENTATION_STATUS.md`](IMPLEMENTATION_STATUS.md)）；本文保留规划全文，与代码冲突时以实现现状表 + 代码为准。

---

## 0. 如何使用本文档

| 读者 | 重点章节 |
| --- | --- |
| 决策者 / 产品 | §1 定位边界、§12 演进路线、§13 排期、§16 风险、§18 ADR、§23 容量 |
| 架构 / Tech Lead | §2 技术栈、§3 架构、§5 数据模型、§6 Agent、§7 评分、§8 API、§18 ADR、§19 LLM |
| 后端工程师 | §5、§6、§7、§8、§10 数据容错、§14 测试、§15 部署、§20 可观测性 |
| 前端工程师 | §9 Dashboard、§8 API、§24.1 反馈埋点 |
| 数据 / 运维 | §10 数据接入、§11 调度、§15 部署、§20 可观测性、§22 数据治理、§23 容量 |
| 安全 / 合规 | §16 风险、§21 安全合规、§22 数据治理 |

**版本约定**：本文档随实现推进更新；任何架构级决策变更需在 §18 索引并落到 [docs/adr/](adr/) 独立 ADR 文件（背景→决策→理由→后果）。配套规范：[API_SPEC.md](API_SPEC.md) / [DATA_SCORING_DICT.md](DATA_SCORING_DICT.md) / [FRONTEND_SPEC.md](FRONTEND_SPEC.md) / [DEPLOYMENT.md](DEPLOYMENT.md) / [OBSERVABILITY.md](OBSERVABILITY.md) / [SECURITY.md](SECURITY.md) / [DATA_QUALITY.md](DATA_QUALITY.md) / [OPERATIONS.md](OPERATIONS.md) / [GLOSSARY.md](GLOSSARY.md) / [adr/](adr/)。

---

## 1. 产品定位与边界（对齐设计文档）

### 1.1 一句话定义
> 一个基于多智能体系统的 **Web3 早期项目机会识别 + 空投参与决策系统**。

系统每天自动产出：
- 新 Web3 项目列表
- 每个项目的综合评分（0–100）
- 是否值得参与空投（FARM / WATCH / IGNORE）
- 具体参与策略（actionable steps）

### 1.2 系统本质（设计文档原文强调）
这是一套 **「Web3 叙事周期 + 项目质量 + 风险建模 + 时间窗口识别」系统**，而不是一个"空投刷量工具"。

### 1.3 边界（明确不做什么）
| 不做什么 | 说明 |
| --- | --- |
| 不保证收益 | 输出是决策参考，不是投资建议 |
| 不执行交易（v1/v2） | 无链上资金自动操作 |
| 不做自动 farming 执行 | V3 仅给出 checklist，不代操作钱包 |
| 不做 KYC/资金托管 | 不涉及用户资产 |

### 1.4 成功指标（建议追加，用于验收）
- 每日自动产出项目数 ≥ 20，覆盖率（DefiLlama + CryptoRank）≥ 80%
- 单项目端到端分析延迟 < 3s（规则引擎）/ < 15s（含 LLM）
- Dashboard 可用，关键指标可解释（每个评分附 reason）
- 误报可被用户反馈回流（V3 memory 系统）

---

## 2. 技术栈选型与决策

| 层 | 选型 | 备选 | 决策理由 |
| --- | --- | --- | --- |
| 语言 | **Python 3.11+** | Node.js | Agent / LLM / 数据抓取生态最成熟；团队已具备 Python 运行时 |
| Web 框架 | **FastAPI** | Flask | 原生 async、Pydantic 校验、自动 OpenAPI 文档，契合 REST 设计 |
| Agent 编排 | **自研轻量 Orchestrator（先）** → 后续可切 **LangGraph / CrewAI** | CrewAI、LangGraph | MVP 用纯 Python 模块即可跑通；抽象出 `BaseAgent` 接口，后续可无痛替换框架（见 §6.1） |
| 数据层 | **SQLite（MVP）→ PostgreSQL（V2+）** | Postgres 直上 | MVP 本地零运维；通过 SQLAlchemy/原生 SQL 抽象，切换 DB 仅改连接串 |
| ORM | **SQLAlchemy Core（可选）** | 原生 sqlite3 | 提供迁移与跨库能力；MVP 可先用原生 SQL 降低依赖 |
| 前端 | **Next.js 14（App Router）**（V2） / **单页静态 HTML+JS（MVP 预览）** | React SPA、Vue | MVP 用单页 HTML 低成本可预览；正式 Dashboard 用 Next.js |
| 调度 | **系统 cron / GitHub Actions / APScheduler** | 云函数 | MVP 用 cron 触发 `POST /run`；V2 用容器内固定调度 |
| 配置 | **环境变量 + `.env` + pydantic-settings** | YAML | 12-factor 友好 |
| 部署 | **Docker + docker-compose** | K8s | MVP 单机构建即可；compose 一键起后端+前端 |
| 日志/观测 | **structlog + 简易 metrics** | Prometheus | MVP 轻量；V2 接入 Prometheus |

### 2.1 关键决策点（已决议，详见 §18 ADR 记录）
- **ADR-001**：MVP 默认 **规则引擎**（无外部依赖、可离线演示）；`OPENAI_API_KEY` 存在时启用 LLM 增强作为可选插件，失败自动回退规则引擎。
- **ADR-002**：Agent 编排 **先自研轻量 Orchestrator**，接口对齐 LangGraph 概念（state + node + reducer），保留后续无痛切换 LangGraph/CrewAI 的迁移路径。
- **ADR-003**：前端 MVP 接受 **单页 HTML+JS** 作为可预览原型；正式 Dashboard 用 Next.js 14 在 V2 完成。
- **ADR-004**（新增）：数据层 MVP 用 **SQLite（WAL 模式）**，V2 切 PostgreSQL；通过 `db.py` 抽象隔离，切换仅改连接串。
- **ADR-005**（新增）：调度 MVP 用 **APScheduler 进程内调度**（而非外部 cron），便于容器自包含与本地零依赖；保留 `POST /run` 供外部触发。

---

## 3. 系统总体架构（细化）

### 3.1 分层架构
```
┌─────────────────────────────────────────────┐
│  Frontend (Next.js Dashboard / 单页预览)       │
└───────────────────────┬─────────────────────┘
                        │  HTTPS / REST (JSON)
┌───────────────────────▼─────────────────────┐
│  API Gateway (FastAPI)                         │
│   /run  /projects  /project/{id}  /re-score/{id}│
└───────────────────────┬─────────────────────┘
                        │
┌───────────────────────▼─────────────────────┐
│  Orchestrator Layer (多智能体协调引擎)          │
│   collect → enrich → analyze → score → rank    │
└───┬───────────┬───────────┬───────────┬──────┘
    │           │           │           │
┌───▼───┐  ┌────▼────┐ ┌────▼────┐ ┌────▼────┐
│Collector│  │Analyzer │ │ Scoring │ │ Scheduler│
│ Agent  │  │ Agents  │ │ Engine  │ │ (cron)  │
└───┬───┘  └────┬────┘ └────┬────┘ └─────────┘
    │           │           │
┌───▼───────────▼───────────▼──────────────────┐
│  Specialized Agents Layer                      │
│  Narrative | Team | Risk | Tokenomics          │
└───────────────────────┬──────────────────────┘
                        │
┌───────────────────────▼─────────────────────┐
│  Data Layer  (SQLite → PostgreSQL)             │
│  projects 表 | logs 表 | (V2) narratives 维表  │
└───────────────────────────────────────────────┘
```

### 3.2 进程 / 部署拓扑（MVP）
- 单进程：FastAPI（uvicorn）同时提供 API 与静态前端（Mount 静态目录）。
- 调度：外部 cron 每晨调用 `POST /run`；或容器内 APScheduler。
- 数据：本地 SQLite 文件（`backend/data/airdrop.db`）。

### 3.3 关键数据流
```
cron
 → POST /run
   → Orchestrator.collect()        # 拉取原始项目
   → 去重 (by name+sector)
   → 每个项目并行: Narrative/Team/Risk/Tokenomics.analyze()
   → Scorer.score()                # 汇总加权
   → 写 projects 表
 → GET /projects                   # Dashboard 拉取
```

---

## 4. 目标目录结构（最终形态）
> **实现状态（2026-07-09 更新）**：MVP 已实现并完整落地。下方 `backend/app/` 为**实际已存在的文件结构**（手动输入方向，非 seed 自动采集）。`fetcher/seed/scheduler/backtest/cache/auth` 等曾规划的模块**未实现**，列入文末"V2 规划（尚未实现）"小节。

```
Web3 Airdrop Alpha Agent System/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                 # FastAPI app + 路由注册（/api/v1/run, /api/v1/projects, /api/v1/export_import 已注册）
│   │   ├── config.py               # pydantic-settings：权重/阈值/源/LLM/调度
│   │   ├── models.py               # Pydantic 模型（RawProject / AgentResult 系列 + AgentContext）
│   │   ├── db.py                   # SQLite 数据层（WAL）
│   │   ├── repository.py           # 数据访问层（projects 读写封装）
│   │   ├── export.py               # 项目导出（CSV/JSON）
│   │   ├── import_utils.py         # 项目导入工具
│   │   ├── openapi.py              # OpenAPI 自定义配置
│   │   ├── agents/
│   │   │   ├── __init__.py
│   │   │   ├── base.py             # BaseAgent + RawProject + PipelineState + AgentContext（§6.1）
│   │   │   ├── collector.py        # Collector（MVP 由 run.py 的 ProjectInput 手动输入驱动）
│   │   │   ├── narrative.py        # Narrative Agent（已落地）
│   │   │   ├── team.py             # Team Agent（已落地）
│   │   │   ├── risk.py             # Risk Agent（已落地）
│   │   │   ├── tokenomics.py       # Tokenomics Agent（已落地）
│   │   │   ├── scorer.py           # Scorer（加权评分，已落地，§7）
│   │   │   ├── orchestrator.py     # Orchestrator（并行编排）
│   │   │   └── orchestrator_simple.py  # SimpleOrchestrator（串行处理多项目）
│   │   ├── routers/
│   │   │   └── v1/
│   │   │       ├── __init__.py
│   │   │       ├── run.py          # POST /api/v1/run（ProjectInput + RunRequest，手动输入方向）
│   │   │       ├── projects.py     # GET /api/v1/projects
│   │   │       └── export_import.py # /api/v1/export_import 导出导入端点
│   │   └── utils/
│   │       ├── __init__.py
│   │       ├── fetcher.py          # 统一外部源 fetcher（缓存/重试/熔断，§10.1）
│   │       └── normalize.py        # 归一化/去重工具（§6.2.1）
│   ├── requirements.txt
│   └── run.py                      # uvicorn 入口
├── frontend/
│   ├── (MVP) index.html           # 单页预览（ADR-003）
│   └── (V2)  app/  components/ ... # Next.js 工程
├── data/
│   ├── airdrop.db                  # SQLite（gitignore）
│   └── cache/                      # fetcher 磁盘缓存（gitignore）
├── tests/
│   ├── unit/                       # 单元测试（§14.2）
│   ├── contracts/                  # 契约测试（§14.3）
│   ├── golden/                     # golden 回归快照（§14.6）
│   │   └── projects.jsonl
│   └── api/                        # API 测试（§14.7）
├── docs/                           # 设计文档与规范
├── Dockerfile
├── docker-compose.yml
├── .dockerignore
├── .env.example
├── .gitignore
 └── README.md
 ```

> **注：以下为 V2 规划，尚未实现**（Roadmap 目标形态，非当前代码）：
> - `backend/app/seed.py` — MVP 演示种子数据（当前 MVP 为手动输入方向，无 seed 模块）
> - `backend/app/scheduler.py` — APScheduler 定时触发（ADR-005），当前由外部 cron / 手动 `POST /run` 触发
> - `backend/app/backtest.py` — 权重回测（V2，§7.9）
> - `backend/app/cache.py` — 竞争度缓存（V2，ADR-010，§7.5.1）
> - `backend/app/auth.py` + `middleware/` — 鉴权逻辑与中间件（V2+）
> - `backend/app/agents/prompts/` — LLM prompt 模板版本化（§19.2，当前 prompt 内联）

---

## 5. 数据模型与数据库 Schema

### 5.1 `projects` 表（生产级）
```sql
CREATE TABLE projects (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    url             TEXT,
    sector          TEXT,
    stage           TEXT,                -- testnet | mainnet | ideation
    score           INTEGER,             -- 0-100
    label           TEXT,                -- FARM | WATCH | IGNORE
    recommendation  TEXT,                -- FARM | WATCH | IGNORE（MVP/V2 与 label 恒等，见 GLOSSARY）
    confidence      REAL,                -- 数据完整度 0-1（非缺失分析 agent 数 / 4）
    weight_version  TEXT,                -- 评分权重版本（ADR-006，默认 "v1"）
    reason          TEXT,                -- JSON array<string>
    narrative_json  TEXT,                -- JSON(NarrativeResult)
    team_json       TEXT,                -- JSON(TeamResult)
    risk_json       TEXT,                -- JSON(RiskResult)
    tokenomics_json TEXT,                -- JSON(TokenomicsResult)
    raw_signals     TEXT,                -- 原始信号 JSON（含 sources[]）
    meta            TEXT,                -- 元数据 JSON（missing_count 等）
    source          TEXT,                -- 来源: defillama/cryptorank/seed/twitter
    raw_signals_hash TEXT,               -- raw_signals 稳定哈希（变化检测）
    fetched_at      TIMESTAMP,           -- 外部源采集时间（V2 填充；MVP seed 为 NULL）
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_projects_score ON projects(score DESC);
CREATE INDEX idx_projects_sector ON projects(sector);
CREATE INDEX idx_projects_label  ON projects(label);
CREATE INDEX idx_projects_source ON projects(source);
```

### 5.2 `logs` 表（_agent 执行留痕，用于可解释与调试）
```sql
CREATE TABLE logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      TEXT NOT NULL,       -- pipeline 运行 ID（贯穿链路追踪，§6.1.1/§20.3）
    project_id  TEXT,
    agent_name  TEXT,
    input       TEXT,     -- JSON
    output      TEXT,     -- JSON
    error       TEXT,     -- JSON(AgentError)，可空；成功时为 NULL
    duration_ms INTEGER,
    timestamp   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_logs_project ON logs(project_id);
CREATE INDEX idx_logs_run     ON logs(run_id);
```

### 5.3 迁移策略
- MVP：应用启动时 `init_db()` 自动建表（幂等 `CREATE IF NOT EXISTS`）。
- V2：引入 **Alembic**，支持 schema 演进与回滚。
- 字段扩展（如 narrative 升级）采用 **追加列 + JSON 兼容**，避免破坏性迁移。

### 5.4 V2 新增表 DDL（反馈/治理/可观测/校准）

> 这些表在 V2 引入，但 V1 阶段就需在设计中明确 schema，避免 V2 冷启动无规划。MVP 不建表。

#### 5.4.1 `feedback` 表（用户反馈，§24.1）
```sql
CREATE TABLE feedback (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  TEXT NOT NULL,
    user_id     TEXT,                -- V2 匿名 token；V3 接登录
    signal      TEXT NOT NULL,       -- useful|useless|wrong_label|correct_outcome
    note        TEXT,                -- 用户自由文本（可选）
    outcome     TEXT,                -- airdropped|not_airdropped|pumped|dumped|NULL
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_feedback_project ON feedback(project_id);
CREATE INDEX idx_feedback_outcome ON feedback(outcome) WHERE outcome IS NOT NULL;
```

#### 5.4.2 `events` 表（隐式行为埋点，§24.1）
```sql
CREATE TABLE events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  TEXT,                -- 可空，全局事件如 page_view
    user_id     TEXT,
    event_type  TEXT NOT NULL,     -- click|expand|feedback|...
    detail      TEXT,                -- JSON: 停留时长/筛选条件等
    timestamp   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_events_project ON events(project_id);
CREATE INDEX idx_events_type    ON events(event_type);
```

#### 5.4.3 `quarantine` 表（脏数据隔离，§22.3）
> 权威 DDL 以 `DATABASE_DDL.md §2.5` 为准。

```sql
CREATE TABLE quarantine (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id      TEXT,                       -- 关联项目（可能为 NULL）
    raw_data        TEXT NOT NULL,              -- 原始数据 JSON（内部含 source）
    failure_reason  TEXT NOT NULL,              -- schema_violation|business_rule_violation|accuracy_mismatch|reference_error|dedup_conflict
    severity        TEXT DEFAULT 'warning',    -- warning/critical
    status          TEXT DEFAULT 'pending',     -- pending/resolved/discarded
    resolved_at     TIMESTAMP,                  -- 解决时间
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_quarantine_status  ON quarantine(status);
CREATE INDEX idx_quarantine_reason  ON quarantine(failure_reason);
CREATE INDEX idx_quarantine_created ON quarantine(created_at DESC);
```

#### 5.4.4 `project_history` 物化视图（项目演化，§24.3）
> 记录项目跨 run 的 score/stage/label 变化与完整快照，V3 memory 系统读取。
```sql
CREATE TABLE project_history (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id   TEXT NOT NULL,
    run_id       TEXT NOT NULL,
    score        INTEGER,
    label        TEXT,
    stage        TEXT,
    weight_version TEXT,             -- 评分权重版本（§7.9）
    snapshot     TEXT NOT NULL,      -- 完整项目快照 JSON（含 raw_signals/四 agent 结果）
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (project_id) REFERENCES projects(id)
);
CREATE INDEX idx_history_project ON project_history(project_id, created_at);
CREATE INDEX idx_history_run     ON project_history(run_id);
```
- 每次 `POST /run` 或 `POST /re-score/{id}` 完成后插入一行（即使值未变，也记心跳）。
- V3 由此构建项目画像时间序列。

#### 5.4.5 `weight_changelog` 表（权重校准审计，§7.9/§24.4）
```sql
CREATE TABLE weight_changelog (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    from_version    TEXT NOT NULL,
    to_version      TEXT NOT NULL,
    old_weights     TEXT NOT NULL,   -- JSON
    new_weights     TEXT NOT NULL,   -- JSON
    trigger_samples INTEGER,         -- 触发校准的样本数
    metrics_before  TEXT,            -- JSON: recall/FPR 等
    metrics_after   TEXT,
    changed_by      TEXT,            -- user/system
    changed_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```
- 每次权重切换必记，禁止无声漂移。

#### 5.4.6 `narratives` 维表（赛道元数据，V2）
```sql
CREATE TABLE narratives (
    sector          TEXT PRIMARY KEY,   -- 标准赛道名（§6.2.1 sector_key）
    aliases         TEXT,               -- JSON: ["restake","restaking"]
    base_heat       REAL,               -- 基础热度 0-1
    stage           TEXT,               -- early|growth|peak|mature
    momentum        REAL,               -- 动量修正系数
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```
- 取代 MVP 内嵌 `config.SECTOR_PROFILE`，支持动态更新与运营干预。

#### 5.4.7 其他 V2 辅助表（索引）
> 以下三张表在 `DATABASE_DDL.md` 中有完整 DDL，本节仅做索引说明。

| 表 | 作用 | 对应 DATABASE_DDL 章节 |
|---|---|---|
| `audit_logs` | 审计日志：记录 `run` / `re-score` / `config_change` / `weight_change` 等操作 | `DATABASE_DDL.md` §2.7 |
| `llm_eval_changelog` | LLM 评估记录：每周或触发式离线评估后写入规则 vs LLM 准确率对比 | `DATABASE_DDL.md` §2.9 |
| `metrics` | 数据质量指标：每次 run 后写入完整性/时效性/一致性等维度指标 | `DATABASE_DDL.md` §2.10 |

#### 5.4.8 `dedup_keys` 表（去重键映射，可选）
> 详见 [DATABASE_DDL.md §2.11](DATABASE_DDL.md)。`dedup_key → project_id` 的持久化映射，便于跨 run 去重溯源与冲突排查；非核心流程强制依赖（Orchestrator 已用确定性 UUID v5 保证跨 run 稳定 id），可作为可观测性辅助表按需启用。

#### 5.4.9 `prompt_versions` 表（Prompt 版本管理，V2 起）
> 详见 [DATABASE_DDL.md §2.12](DATABASE_DDL.md)。LLM prompt 模板的版本化存储（agent_name / prompt_key / version / content / is_default），支持 prompt 回滚与 A/B（对齐 ROADMAP §19.2 `prompt_version` 写入 logs）。

---

## 6. 各 Agent 详细设计

### 6.1 通用 Agent 契约（`BaseAgent`）
```python
class BaseAgent(ABC):
    name: str
    @abstractmethod
    def run(self, context: AgentContext) -> AgentResult: ...
    # 可选 LLM 增强钩子（ADR-001），失败返回 None 触发规则回退
    def llm_enhance(self, prompt: str) -> str | None: ...
    # Agent 自检钩子（供 /health 端点聚合）
    def health_check(self) -> dict:
        return {"agent": self.name, "status": "healthy", "latency_ms": None, "error_rate": 0.0}
```

#### 6.1.1 状态契约（对齐 LangGraph：state + node + reducer）
编排以**显式状态对象**在 node 间流转，避免隐式全局变量。每个 Agent 是一个 node，读取 state 的某子集，写入自己的 result 字段。

```python
@dataclass
class PipelineState:
    project: RawProject                 # Collector 产出，只读
    narrative: NarrativeResult | None   # Narrative node 写入
    team:      TeamResult | None        # Team node 写入
    risk:      RiskResult | None        # Risk node 写入
    tokenomics:TokenomicsResult | None  # Tokenomics node 写入
    score:     ScoreResult | None       # Scorer node 写入
    errors:    list[AgentError]         # reducer: list.extend（累计而非覆盖）
    meta:      dict                     # run_id、timing、retry 计数等
```

- **Reducer 语义**：
  - 各 `*_result` 字段采用 **last-write-wins**（单写者）。
  - `errors` 采用 **list-extend reducer**（累积所有 node 的失败，不互相覆盖）。
  - `meta` 内同名字段 last-write-wins，新增字段追加。
- **不可变性**：node 内对 state 做浅拷贝后写回，避免跨 node 副作用。
- **迁移 LangGraph**：state 字段 → `TypedDict`，reducer → `Annotated[list, add]`；node 签名 `node(state) -> partial state`。接口已对齐，迁移成本主要是替换基类与调度器。

#### 6.1.2 AgentContext 输入 schema
`context` 不仅是 dict，明确字段以约束契约：
| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `run_id` | str | 本次 pipeline 运行唯一 ID（写入 logs） |
| `project` | RawProject | 原始项目（含 raw_signals） |
| `upstream` | dict[str, Result] | 上游 node 已产出的结果（按需取用） |
| `config` | RuntimeConfig | 权重/阈值/LLM 开关（只读快照） |
| `deadline_ms` | int | 本 node 软超时（超时则回退规则引擎） |

#### 6.1.3 运行时保证
- **留痕**：每次 `run` 自动写 `logs` 表（`run_id`/`project_id`/`agent_name`/`input`/`output`/`duration_ms`/`error`）。
- **降级**：LLM 失败/超时 → 回退规则引擎，`AgentError(kind="llm_fallback")` 记入 `errors`，不中断主流程。
- **并行**：analyze 阶段四个 agent 对同一项目无依赖，`asyncio.gather` 并行；单 agent 异常被捕获，对应字段保持 `None`，Scorer 按缺失字段策略处理（§7.4）。
- **幂等**：同一 `(run_id, project_id, agent_name)` 重跑覆盖 logs 最新一条；projects 表按 `id` upsert。

### 6.2 Collector Agent
- **职责**：持续发现 Web3 新项目，产出 `RawProject[]`。
- **v2.0 方向（ADR-012，自动扫描为主）**：Collector 从被动接收转为**主动采集**，通过多数据源自动发现未空投的早期项目。
  - **P0 核心采集源**：DefiLlama（全量协议扫描，每日）/ GitHub（仓库活跃度，每日）/ CoinGecko（代币状态验证，每日）/ Twitter（VC/KOL + 关键词，每小时或实时流）。
  - **P1 增强源**：链上（新合约监控，webhook）/ Galxe/Layer3（任务平台扫描）/ CryptoRank（融资数据）。
  - **手动输入（补充）**：保留 `POST /api/v1/run` 手动输入路径作为补充，覆盖采集盲区。
  - **双调度**：采集调度器（按源不同频率）+ 分析调度器（新项目入队即触发）。详见 `DATA_SOURCE_STRATEGY.md §双调度模型`。
- **输出结构**（对齐设计文档 `proj`）：
```json
{ "id":"uuid", "name":"LayerX", "url":"...", "sector":"L2",
  "stage":"testnet", "raw_signals": { "has_points": true, "airdrop_hint": true, "sources": ["defillama", "github"] } }
```
- **新项目识别**：硬规则过滤（未发币 + 活跃度达标），`discovery_score ≥ 0.3` 才进入分析管道。详见 `DATA_SOURCE_STRATEGY.md §新项目识别规则`。
- **LLM 分级使用**：仅 `discovery_score ≥ 0.7` 的高价值项目启用 LLM 增强（ADR-012），其余走规则引擎。

#### 6.2.1 归一化与去重（关键）
不同来源对同一项目命名/大小写/前后缀不一致，必须归一化后再去重：
- `name_key = normalize(name)`：小写 → 去空格/连字符 → 剔除常见后缀（`"protocol"`, `"finance"`, `"dao"`）→ Unicode NFKC。
- `sector_key = normalize(sector)`：映射同义赛道到标准词表（`"restake"/"restaking"` → `"Restaking"`；`"layer2"/"l2"` → `"L2"`）。词表维护在 `config.SECTOR_ALIAS`。
- **去重键**：`dedup_key = f"{name_key}::{sector_key}"`。
- **冲突仲裁**：多源命中同一 `dedup_key` 时，按来源优先级 `seed > defillama > cryptorank > twitter` 取主记录，其余来源信息合并进 `raw_signals.sources[]`，URL 取第一个非空。

#### 6.2.2 新增 vs 更新策略
对 Collector 产出的每个 `dedup_key`：
- **库中不存在** → INSERT 新项目 → 进入完整 pipeline（analyze+score）。
- **库中已存在** →
  - 若 `raw_signals` 有变化（如新增 `airdrop_hint`）→ 触发 `re-score`（仅重跑 analyze+score，不重新采集）。
  - 若无变化 → 跳过（仅更新 `updated_at` 心跳）。
- 判定"变化"用 `raw_signals` 的稳定哈希（剔除 `sources[]` 后 SHA1），避免来源元数据抖动触发无效重算。

#### 6.2.3 幂等性
- `POST /run` 可被重复触发（cron 重试、手动重跑）；同一 `dedup_key` 在同一次 run 内只处理一次。
- 项目 `id` 由 `dedup_key` 的确定性 UUID v5（namespace + dedup_key）生成，**保证跨 run 稳定**，避免重复入库产生新 id。
- `re-score` 端点对同一 `id` 并发调用靠 SQLite WAL + 应用层 `threading.Lock`（MVP）/ 行锁（V2 PG）串行化。

### 6.2.4 输入数据约定（关键，v2.0 更新 ADR-012）

> **v2.0 方向反转**：系统从"手动输入为主"转为"自动扫描为主"。手动输入路径保留为补充能力。

**自动扫描路径（v2.0 主路径）**：
- Collector 从多数据源（DefiLlama/GitHub/CoinGecko/Twitter 等）自动采集项目，写入 `raw_projects` 表。
- 经 `discovery_score` 过滤后，自动进入分析管道。
- 各分析 agent 所需字段（`heat_score`/`team_score`/`vc_share` 等）由对应 agent 从采集信号推导，不再依赖用户输入。

**手动输入路径（补充能力）**：
- `POST /api/v1/run` 接收 `RunRequest{ projects: ProjectInput[], enable_llm, llm_model }` 扁平字段。
- 用于覆盖采集盲区（未上 DefiLlama 的新项目、未公开代码库的项目）。
- 手动输入项目可额外携带策划字段（见下表），使规则引擎能产出非中性评分。

| 字段（在 RawProject 扩展） | 消费方 | 说明 |
| --- | --- | --- |
| `heat_score` | Narrative | 赛道热度（0–1），缺失时由 `SECTOR_PROFILE` 推导 |
| `narrative_stage` | Narrative | 赛道阶段 `early/growth/peak/mature` |
| `team_score` | Team | 团队信誉分（0–1），缺失时走 Team 规则（匿名/VC 启发式） |
| `team_flags` | Team | 已知 flag 列表（如 `anonymous team`） |
| `token_risk` | Risk | 代币结构风险（0–1） |
| `vc_share` / `team_share` | Tokenomics | VC/团队占比（0–1） |
| `unlock_pressure` | Tokenomics | `low/medium/high` |

- 自动采集路径下，这些字段由 agent 从 `project_signals` 表的信号推导，不依赖用户携带。
- 手动输入路径下，用户可直接携带上述字段（MVP 演示用）。
- `confidence` 仍按实际成功产出的 agent 数计算；全字段齐备时 `confidence=1.0`。
- `W4-03` 种子数据任务验收需包含上述字段（见 TASK_BREAKDOWN）。

### 6.3 Narrative Engine（赛道周期）
- **职责**：判断赛道处于什么周期阶段。
- **输入**：`sector` + `raw_signals` + （V2）Twitter 热度/VC 流入。
- **输出**（对齐 `nar`）：
```json
{ "sector":"Restaking", "stage":"growth", "heat_score":0.82,
  "timing":"early|peak|late" }
```
- **MVP 逻辑（规则）**：
  - 维护 `SECTOR_PROFILE` 表：每个赛道预设 `{base_heat, stage, momentum}`。
  - `heat_score` = base_heat × 动量修正（新项目数量信号加权）。
  - `timing`：依据 stage（early/growth→early；peak→peak；mature→late）。
- **V2 增强**：实时爬 Twitter 讨论量、VC 公告、KOL 泛滥度，动态更新 `heat_score`。
- **评分映射**：`narrative_score(0-100)` = `heat_score×100` × 时点系数（early 1.0 / peak 0.8 / late 0.5）。

### 6.4 Team Reputation Engine（团队信誉）
- **职责**：识别换皮团队、rug/scam 历史、VC 是否洗白工具。
- **输出**（对齐 `team`）：
```json
{ "score":0.72, "risk_level":"medium",
  "flags":["previous failed project","anonymous team"] }
```
- **MVP 逻辑**：基于 `raw_signals` 与静态规则：
  - 匿名团队 → `-0.2`，flag `anonymous team`。
  - 历史失败项目 → `-0.25`，flag `previous failed project`。
  - 知名 VC 背书 → `+0.2`。
  - `score` 截断 [0,1]，映射 `risk_level`（<0.4 high / 0.4-0.7 medium / >0.7 low）。
- **V2 增强**：接入链上地址聚类、团队历史项目数据库、Scam 黑名单 API。

### 6.5 Risk Engine（风险模型）
- **职责**：评估 Sybil 难度、farming 成本、token 结构风险。
- **输出**（对齐 `risk`）：
```json
{ "sybil_difficulty":"high", "farming_cost":"medium", "token_risk":0.68 }
```
- **MVP 逻辑**（独立可并行，不依赖 Tokenomics 输出）：
  - `sybil_difficulty`：依据所需交互复杂度（多步交互/多链 → high）。
  - `farming_cost`：估算 gas + 时间成本 → low/medium/high。
  - `token_risk`：由 Risk agent **独立**从项目信号估算（MVP 用 `raw_signals` 启发式 + seed 携带的 token 线索；V2 失败回退见 §10.2 也走此路径），**不阻塞 analyze 阶段并行**。
  - > 注：Risk 与 Tokenomics 在 `analyze` 阶段并行执行（§6.8），二者各自产出 `token_risk` 与 `tokenomics.risk`，分别供 `risk` 子分与 `tokenomics` 子分使用，互不等待。
- **评分映射**：`risk_score(0-100)` = `(1 - token_risk)×100 × sybil_factor`，sybil 难度高则参与门槛高但确定性更强（需在 reason 中说明）。

### 6.6 Tokenomics Engine（代币经济，关键模块）
- **职责**：分析 token 分配、unlock 压力、VC&team 占比、通胀。
- **输出**（对齐 `token`）：
```json
{ "vc_share":0.25, "team_share":0.2, "unlock_pressure":"high", "risk":0.75 }
```
- **MVP 逻辑**：
  - `risk` = `vc_share×0.4 + team_share×0.3 + unlock_penalty×0.3`。
  - `unlock_pressure`：依据 cliff/线性释放比例 → low/medium/high。
  - 通胀率高 → 额外 penalty。
- **评分映射**：`tokenomics_score(0-100)` = `(1 - risk)×100`。

### 6.7 Scorer（核心决策）
- **职责**：按权重汇总各子分，输出统一评分。
- **输出**（对齐 `score`）：
```json
{ "score":67, "label":"WATCH", "recommendation":"WATCH",
  "reason":["strong airdrop signal","early narrative, high heat","high token unlock pressure"] }
```
- **算法见 §7**。

### 6.8 Orchestrator（系统大脑）
- **职责**：调度所有 agent、去重、控制顺序、输出结果。
- **流程**（对齐设计文档 `flow`）：
```
collect → enrich → analyze → risk → score → rank → output
```
- **并行策略**：`analyze` 内 Narrative/Team/Risk/Tokenomics 对同一项目并行；多项目之间可分批并发——详细设计见 §6.9。
- **rank**：按 `score` 降序；同分按 `airdrop_signal`  tie-break。
- **输出**：写 `projects` 表 + 触发 Dashboard 刷新（V2 加 Telegram 推送）。

---

### 6.9 多项目并发模型（Multi-Project Concurrency）

> 本节点定义系统在多项目场景下的并发策略：Notion Collector 一次产出 N 个项目后，如何控制 pipeline 的并行度、保护资源、隔离错误、防止 OOM。
>
> 对应 ADR：[ADR-007](adr/ADR-007-multi-project-concurrency.md)。

#### 6.9.1 三级并行层次

系统存在三个层次的并行，必须独立控制，不可混为一谈：

| 层次 | 范围 | 实现方式 | 主要瓶颈 |
| --- | --- | --- | --- |
| **Level 1：多项目间** | N 个项目同时跑完整 pipeline | `asyncio.Semaphore` 控制并发项目数 | CPU（规则引擎）+ I/O（LLM/DB） |
| **Level 2：单项目内 agent 间** | 4 个分析 agent 并行 | `asyncio.gather`（§6.1.3） | 无瓶颈（纯 CPU 短运算） |
| **Level 3：Agent 内部 I/O** | 单 agent 内多路外部调用 | `asyncio.gather`（如 fetcher 多源请求） | 网络 I/O |

- **Level 1** 是本节的焦点（MVP/V2/V3 策略不同）。
- **Level 2** 已在 §6.1.3 定义（4 agent 对同一项目始终 `asyncio.gather`），本节不重复。
- **Level 3** 在 §10.1 fetcher 统一契约中隐含处理。

---

#### 6.9.2 各阶段并发特征

Pipeline 各阶段的 CPU/I/O 特征不同，理想的并发策略应区分对待：

| 阶段 | 类型 | 耗时估算（单项目） | 是否可跨项目并行 | 限制因素 |
| --- | --- | --- | --- | --- |
| **collect** | I/O bound | 0.5–5s（外部 API） | 否（单源限流+一致性） | 外部源 API 限流、fetcher 熔断 |
| **enrich/dedup** | CPU bound | 10–50ms | 是，但受益有限 | 去重逻辑依赖全局 dedup_keys |
| **analyze**（规则） | CPU light | 200–800ms | **是**，主要并发收益点 | CPU 核数、内存 |
| **analyze**（含 LLM） | I/O bound | 3–15s | **是**，但需特殊控制 | LLM 配额/预算/速率限制 |
| **score** | CPU bound | 5–20ms | 否（单项目轻量，不值得调度） | — |
| **write(DB)** | I/O bound | 10–50ms（WAL） | 否（SQLite 写锁） | 单写者序列化 |

> **核心结论**：`analyze` 阶段是跨项目并发的唯一主要收益点。`collect` 受外部源限制不可并行；`score` 和 `write` 因依赖关系和 DB 锁不可并行。因此并发控制以 analyze 阶段为中心。

---

#### 6.9.3 并发策略演进

| | MVP | V2 | V3 |
| --- | --- | --- | --- |
| **多项目并发** | 串行（串行） | 有限并发（asyncio.Semaphore） | 分布式队列（Celery/RQ） |
| **并发项目数上限** | 1 | 可配置，默认 10 | 可配置，无硬上限 |
| **批量大小** | 50 | 300（全量）+ 增量重试 | 队列化，无批量概念 |
| **OOM 保护** | 无（低风险） | 单个 Semaphore | 多 worker 资源隔离 |
| **错误隔离** | 全量失败回滚 | 项目级 try/except + 累积 errors | Task 级重试 + DLQ |
| **LLM 并发控制** | N/A | 项目并发数 × 4 × 采样率 | 独立 LLM 配额池 |

---

#### 6.9.4 MVP 策略：串行执行

```python
# MVP：串行执行，无多项目并发
for project in projects:
    try:
        pipeline_state = await run_single_project_pipeline(project)
        results.append(pipeline_state)
    except Exception as e:
        # 单个项目失败不中断整体流程
        errors.append(AgentError(project_id=project.id, kind="pipeline_error", message=str(e)))
```

**理由**：
- MVP 单次 run 项目数 ≤ 50，50 × 1s = 50s < 60s（§23.3 预算），串行足够。
- 串行消除所有并发复杂度：无竞态、无死锁、日志天然有序。
- SQLite 单写者语义天然与串行匹配。
- OOM 风险为零。

**约束**：
- `POST /run` 同步阻塞上限 60s；超时后客户端断开但后端继续执行（不中断）。
- V2 超 60s 切后台 task（§8.1）。

---

#### 6.9.5 V2 策略：`asyncio.Semaphore` 有限并发

##### 核心机制

```python
# V2：asyncio.Semaphore 控制多项目并发数
semaphore = asyncio.Semaphore(config.concurrency.max_concurrent_projects)  # 默认 10

async def process_project(sem, project, run_id):
    async with sem:  # 不超过 max_concurrent_projects
        state = await run_single_project_pipeline(project, run_id)
        return state

tasks = [process_project(semaphore, p, run_id) for p in projects]
results = await asyncio.gather(*tasks, return_exceptions=True)
```

##### 并发参数配置（`ConcurrencyConfig`）

所有参数集中管理在 `config.py` 的 `ConcurrencyConfig`，环境变量可覆盖：

| 参数 | 类型 | 默认值 | 范围 | 说明 |
| --- | --- | --- | --- | --- |
| `max_concurrent_projects` | int | 10 | 1–50 | 同时跑 pipeline 的项目数上限 |
| `max_concurrent_analyze_per_project` | int | 4 | 1–8 | 单项目内并行 agent 数（固定 4 不调） |
| `llm_semaphore_size` | int | 5 | 1–20 | LLM 调用全局并发上限（独立于项目并发） |
| `fetcher_semaphore_size` | int | 3 | 1–10 | 外部源同时拉取的并发上限 |
| `batch_size` | int | 300 | 1–1000 | 单次 run 最大项目数 |
| `project_timeout_seconds` | int | 30 | 10–120 | 单项目 pipeline 超时（含 LLM），超时跳过该项目 |
| `project_batch_window_ms` | int | 100 | 0–1000 | 提交任务的窗口时间，用于动态批处理 |

##### LLM 独立并发控制

LLM 调用有独立的 Semaphore，与项目并发数解耦，防止所有项目并行时打爆 LLM 配额：

```python
# LLM 全局 Semaphore（独立于项目并发）
llm_semaphore = asyncio.Semaphore(config.concurrency.llm_semaphore_size)

class NarrativeAgent(BaseAgent):
    async def llm_enhance(self, prompt):
        async with llm_semaphore:
            return await call_openai(prompt)
```

> 理由：10 个项目同时 analyze，每个项目 4 agent 都调 LLM → 40 并发 LLM 调用。独立 Semaphore 可限制到 5（默认），保护 LLM 配额与成本。

##### 资源保护与 OOM 防护

| 保护机制 | 实现 | 触发条件 |
| --- | --- | --- |
| **项目级 Semaphore** | `asyncio.Semaphore(max_concurrent_projects)` | 并发项目数超上限 |
| **LLM Semaphore** | `asyncio.Semaphore(llm_semaphore_size)` | LLM 并发超限 |
| **fetcher Semaphore** | `asyncio.Semaphore(fetcher_semaphore_size)` | fetcher 并发超限 |
| **单项目超时** | `asyncio.wait_for(project_task, timeout=project_timeout_seconds)` | 项目处理超时。注意：超时后已完成的 agent logs 已写入，正在执行的 agent logs 可能缺失 |
| **内存预算** | 见下方 | 超出阈值时暂停新项目 |

> **⚠️ logs I/O 瓶颈**：每个项目 analyze 阶段写入 ~8 行 logs（4 agent × start+end）。10 个并发项目同时写入 logs 表时，SQLite 需在短时间内处理约 80 次 INSERT。SQLite 实测写入吞吐约 50–100 INSERT/s → 80 行 ≈ 0.8–1.6s，可接受。V2 切 PG 后此瓶颈自然消除。

**内存预算机制（V2 可选）**：

```python
# 内存感知并发（非强制，通过 psutil/memory 指标可选启用）
class MemoryBudget:
    def __init__(self, max_memory_percent=80.0):
        self.max_memory_percent = max_memory_percent
    
    @property
    def can_accept(self) -> bool:
        usage = psutil.virtual_memory().percent
        return usage < self.max_memory_percent
    
    def wait_for_space(self):
        while not self.can_accept:
            asyncio.sleep(1)
```
- MVP/V2 默认**不启用**内存预算（单进程 Python 内存通常不是瓶颈）。
- 如需启用，通过 `ConcurrencyConfig.enable_memory_budget=True` 开启。
- 仅在 V3 多 worker 场景下推荐开启。

---

#### 6.9.6 V3 策略：分布式队列

> V3 将单项目 pipeline 作为独立 task，通过 Celery/RQ 分发给多个 worker。
> 详细设计在 V3 阶段补充，本节仅给出演进路径。

```
┌────────────┐     ┌───────────┐     ┌────────────┐
│ Collector  │────▶│  Queue    │────▶│  Worker(s) │
│ (scheduled)│     │ (Redis/RQ)│     │ (N 实例)   │
└────────────┘     └───────────┘     └──────┬─────┘
                                            │
                                     ┌──────▼─────┐
                                     │  DB (PG)   │
                                     └────────────┘
```

- 每个 worker 从队列取一个 project_id，跑完整 analyze+score 后写库。
- Collector 仍为单实例，产出项目后入队而非直接执行。
- 利用 PG 行锁保证同一项目不被两个 worker 重复处理。
- 项目并发数 = worker 数 × 每个 worker 的并发配置（不推荐超 1）。

---

#### 6.9.7 错误隔离与部分失败

**基本原则**：**一个项目的失败绝不能阻断其他项目**。

| 故障场景 | 影响范围 | 处理方式 | 对评分的影响 |
| --- | --- | --- | --- |
| 单项目 analyze 超时 | 该项目 | 跳过该项目，`errors` 累积；已完成的 agent logs 已写入，正在执行的 agent logs 缺失 | 该项目无评分；logs 部分缺失 |
| 单项目 LLM fallback | 该项目该项 | 回退规则引擎 | 子分可能降低（规则 vs LLM） |
| 单项目 DB 写失败 | 该项目 | 重试 1 次，仍失败则跳过并记 error | 该项目无写入 |
| 同 run 内连续 N 项目 LLM fallback | 后续项目该 agent | 该 agent 跳过 LLM 熔断（§19.3） | 后续项目该子分走规则 |
| Collector 全量失败 | 整次 run | 回退 seed 数据（§10.2） | 无（有 seed 兜底） |
| DB 不可写 | 整次 run | 异常抛出，run 失败 | 无写入，run 标记 error |
| 内存超预算 | 后续项目 | 暂停接收新项目直到内存恢复 | 后续项目延迟处理 |

**实现**：每个项目 pipeline 包裹在 `try/except` 内，单项目异常被捕获为 `AgentError` 写入 `PipelineState.errors`，不向外传播。

---

#### 6.9.8 并发控制流程总图

```
POST /run(source="all", limit=50)
  │
  ▼
Collector.collect()              # 串行，单源限流
  │
  ▼ (N 个 RawProject)
Dedup + Enrich                    # 串行（依赖全局 dedup_key）
  │
  ▼
asyncio.Semaphore(max_concurrent_projects)  ←── 入口
  │
  ├─ Project-1 ─── asyncio.gather(4 agents) ─── Scorer ─── DB.write
  │                       └─ LLM Semaphore (独立)
  ├─ Project-2 ─── asyncio.gather(4 agents) ─── Scorer ─── DB.write
  │                       └─ LLM Semaphore (独立)
  ├─ Project-3 ─── ...
  │
  最多 N 个项目同时，受 Semaphore 控制
  │
  ▼
Sort + Output
```

---

#### 6.9.9 监控指标

| 指标 | 类型 | 标签 | 含义 |
| --- | --- | --- | --- |
| `airdrop_concurrency_active_projects` | gauge | — | 当前正在处理的并发项目数 |
| `airdrop_concurrency_semaphore_waits_total` | counter | `semaphore_name` | 等待信号量的次数 |
| `airdrop_concurrency_project_timeouts_total` | counter | — | 单项目超时次数 |
| `airdrop_concurrency_memory_usage_percent` | gauge | — | 内存使用率（内存预算启用时） |
| `airdrop_concurrency_llm_semaphore_usage` | gauge | — | LLM Semaphore 当前利用率 (0–1) |
| `airdrop_concurrency_fetcher_semaphore_usage` | gauge | — | Fetcher Semaphore 当前利用率 (0–1) |

---

#### 6.9.10 配置项变更影响评估

> 修改并发参数时需考虑以下联动影响：

| 变更 | 影响 | 参考关联 |
| --- | --- | --- |
| `max_concurrent_projects ↑` | 内存↑、CPU↑、DB 写队列↑、LLM 调用↑ | LLM 预算（§19.4） |
| `llm_semaphore_size ↑` | LLM 成本↑、延迟↓（LLM 不排队） | LLM 预算（§19.4） |
| `fetcher_semaphore_size ↑` | 外部源负载↑ | fetcher 熔断阈值（§10.1） |
| `project_timeout_seconds ↓` | 超时跳过↑、数据覆盖率↓ | 容错矩阵（§10.2） |
| `batch_size ↑` | 总耗时↑、一次 run 可能在 cron 周期内未完成 | 性能预算（§23.3） |

---

#### 6.9.11 与相关设计的集成点

| 相关设计 | 集成方式 |
| --- | --- |
| **fetcher 熔断**（§10.1） | fetcher Semaphore 与熔断复合：熔断开启时不占用 Semaphore 直接降级 |
| **LLM 预算**（§19.4） | LLM Semaphore 与预算联动：当日预算耗尽则 Semaphore 关闭不再放行 |
| **错误降级**（§7.6） | 单项目超时/异常 → 该项目所有 agent 字段为 None → 走 §7.6 缺失降级 |
| **Scheduler**（§11） | APScheduler 触发时若前一次 run 未完成，则跳过本轮。注意：若前一次 run 部分完成（部分项目已写入），跳过后未完成项目需等到下一 cron 周期才处理 → 数据新鲜度可能延迟 24h。V2 可考虑增量 run（§6.9.12） |
| **DB 事务**（§6.9.12） | 并发项目写 DB 在 SQLite WAL 下单写者序列化；PG 行锁（V2） |

---

#### 6.9.12 补充设计：Pipeline 事务边界（接 P0 缺失 #2）

> 本节同属于上一轮查缺补漏 P0 级 #2（事务边界与部分失败补偿），因与并发模型紧密耦合，一并在此定义。

**事务边界定义**：

```
┌─ Collect ── 无事务（外部数据不保证一致性）
│
├─ Dedup ──── 读 old_data（projects 表）
│
├─ Analyze ── 每个 agent 写 logs 表（独立行，不开启事务）
│     └── 如果 Scorer 失败，logs 已写入但 project 未更新
│     └── 容忍：logs 多了一些孤立的行，无副作用
│
├─ Score ──── 纯计算，内存中完成，不落库
│
└─ Write ──── BEGIN TRANSACTION | END TRANSACTION
      ├── Upsert projects 表（单行）
      ├── Insert project_history 行（V2）
      └── COMMIT（全部成功）| ROLLBACK（任一步失败）
```

**策略**："最终一致性"，而非强事务。
- **为什么不用强事务？** analyze 阶段可能含 LLM 调用（3–15s），长事务会导致 SQLite WAL 膨胀；logs 表允许孤立行是故意设计——它们不影响评分正确性，仅用于调试与回测。
- **Collect→Analyze→Score** 阶段不开启 DB 事务（防止长事务锁定 SQLite）。
- **Write** 阶段开启事务，一次性写入 `projects` + `project_history`（V2）。
- 如果 Write 阶段失败（如 DB 不可写），则该项目**不回滚已写入的 logs**（logs 业务上允许孤立行），整个 run 标记为部分成功。
- 即使 `POST /run` 客户端断连（超时 60s），服务端 Write 事务仍会正常提交（参见 §6.9.4）。
- `POST /run` 响应中的 `inserted`/`updated`/`failed` 仅在 Write 成功后才累加。

### re-score 的事务边界
`POST /re-score/{id}` 跳过 collect 阶段，事务边界与 run 的 Write 阶段一致：
- **analyze** → 写 logs（独立 INSERT，不开启事务）
- **score** → 纯内存计算
- **write** → `BEGIN; UPDATE projects SET ... WHERE id=?; INSERT INTO project_history ...; COMMIT`
- `re-score` **不重新计算** `raw_signals_hash`（保持原值不变），因此下次 run 检测 hash 不变 → 跳过该项目。这符合预期（re-score 是为立即更新评分，不影响数据采集）。

**失败重入语义**：
- 下一轮 run（cron 或手动触发）对所有项目重新完整执行 `collect→analyze→score→write`。
- 基于 §6.2.3 幂等性，同项目写入 `projects` 表是 upsert 语义，不会产生重复行。
- 失败项目的 `updated_at` 在 Write 阶段更新，部分成功的项目（logs 写了但 project 没更新）在下轮 run 中 `raw_signals_hash` 不变 → 跳过 analyze → 不会产生更新的 `updated_at` → 可被监控发现异常。

### competition 子分的读取偏差（Read Skew）

并发场景下，competition 子分基于写入时刻的 DB 快照计算，存在已知的读取偏差：
- 项目 A 评分时基于当时的 DB 状态（例：同 sector 5 个项目）算出 competition=75
- 项目 B 在项目 A **写入后** 基于 6 个项目算出 competition=75（仍同档）
- 但如果项目 A 恰好是让计数跨档的第 N 个项目，则 B 的 competition 会因 A 的存在而降档

这是**故意设计**：分数反映的是写入时刻的快照，不是最终一致性视图。同一 run 内不同项目的 competition 计数可能有 1 的差异。V2 如需精确排序可在 run 末尾统一重算 competition。

### Scheduler 与部分失败的交互

APScheduler 触发时若前一次 run 未完成（§6.9.11），则跳过本轮。但若前一次 run **部分完成**（30/50 项目已写入）：
- 余下 20 个项目要等到下一 cron 周期（通常 24h 后）才处理
- 数据新鲜度最多延迟 24h
- 监控可通过 `airdrop_concurrency_active_projects` 观察执行中状态

**V2 可选增强**：检测前一次 run 是否部分完成（`logs` 表中 `run_id` 对应的项目 < limit），若是则触发一次增量 run——只处理该次 run 中未写入的项目。

### 监控

| 查询 | 目的 | 告警条件 |
| --- | --- | --- |
| `SELECT count(*) FROM logs l WHERE NOT EXISTS (SELECT 1 FROM projects p WHERE p.id=l.project_id) AND l.timestamp > datetime('now', '-1 day')` | 孤立 logs 行数 | >0 → warning |
| `SELECT run_id, count(DISTINCT project_id) as cnt FROM logs WHERE timestamp > datetime('now', '-1 day') GROUP BY run_id HAVING cnt < (SELECT count(*) FROM logs l2 WHERE l2.run_id=run_id)` | 检测部分完成的 run | 存在 → info |

---

## 7. 评分决策引擎算法（详细数学）

### 7.1 子分（0–100）汇总
| 子项 | 权重 | 来源 | 计算 |
| --- | --- | --- | --- |
| airdrop_signal | 20% | Collector.raw_signals | `has_points & airdrop_hint` → 100；仅其一 → 60；无 → 20 |
| narrative_timing | 20% | Narrative | `heat_score×100 × 时点系数` |
| team_reputation | 15% | Team | `team.score×100` |
| risk | 15% | Risk | `(1-token_risk)×100 × sybil_factor` |
| tokenomics | 15% | Tokenomics | `(1-risk)×100` |
| competition | 15% | Orchestrator | 同赛道项目数 `n`：≤3→100, 4–8→75, 9–15→55, >15→40 |

### 7.2 加权总分
```
score = Σ(sub_i × weight_i)   # 取整 0-100
```

### 7.3 标签与建议
```
score >= 70  → label=FARM,      recommendation=FARM
50<=score<70 → label=WATCH,     recommendation=WATCH
score < 50   → label=IGNORE,    recommendation=IGNORE
```

### 7.4 reason 生成规则
- 取贡献最高的 2–3 个子项，映射为自然语言理由：
  - narrative early + heat 高 → "early narrative, high heat"
  - airdrop_signal 满 → "strong airdrop signal"
  - competition 低 → "low competition"
  - team 低分 → "team risk: anonymous / previous failure"
- 明确输出**反面信号**（如 `team risk`、`high unlock pressure`），保证可解释。

### 7.5 竞争度（competition）来源
- MVP：当前 `projects` 表中同 `sector` 项目数量归一化。
- V2：结合外部新项目增速（DefiLlama 增量）。

### 7.5.1 竞争度缓存与增量计数策略（Competition Cache）

> 本节点定义 competition 子分的缓存与增量计数机制，解决「每次评分全表 `COUNT(*)` 随数据量增长退化」的问题。
>
> 对应 ADR：[ADR-010](adr/ADR-010-competition-cache.md)。

#### 问题陈述

每次评分需要 `SELECT COUNT(*) FROM projects WHERE sector=?`（§7.5），50k 项目时全表扫描耗时不可忽略。
- 50k 项目均匀分布在 ~20 个赛道 → 每条 COUNT 扫描 ~2,500 行，约 20–50ms
- V2 并发 10 项目 × 各自 COUNT → 200–500ms 在 counting 上
- re-score 单项目时仍需 COUNT 全库竞争度

#### 设计原则

1. **近似值可接受**：competition 子分只有 4 档（100/75/55/40），±1 项目计数不改变子分。
2. **最终一致性**：缓存允许短时间滞后，下一轮 run 自动修正。
3. **演进优先**：MVP 直接 COUNT（50 项目无压力）→ V2 启用缓存。
4. **写时更新**：项目 INSERT/UPDATE/DELETE 时更新缓存，而非读时重算。

---

#### 演进策略

| 阶段 | 策略 | 实现 | 适用规模 |
| --- | --- | --- | --- |
| **MVP** | 直接 `COUNT(*)` | SQL `SELECT sector, COUNT(*) FROM projects GROUP BY sector` | ≤1k 项目 |
| **V2（基本缓存）** | 进程内 LRU + 惰性失效 | Python dict + 过期 TTL（默认 5min） | ≤50k 项目，单进程 |
| **V2（增强缓存）** | DB `sector_counts` 物化表 + 触发器增量更新 | PostgreSQL 物化表 + trigger（V2 切 PG 后） | ≤50k 项目，多进程 |
| **V3** | Redis Sorted Set 或计数器 | Redis `ZINCRBY sector:count 1 "L2"` | 500k+ 项目，分布式 |

---

#### 方案一：进程内 LRU 缓存（V2 单进程）

```python
# app/cache.py
from collections import OrderedDict
import time

class SectorCountCache:
    """进程内 LRU 缓存，存储 sector → count 映射"""
    
    def __init__(self, maxsize: int = 100, ttl_seconds: int = 300):
        self._cache: OrderedDict[str, tuple[int, float]] = OrderedDict()
        self._maxsize = maxsize
        self._ttl = ttl_seconds
        self._dirty = True  # 标记缓存需要刷新
    
    def get(self, sector: str) -> int | None:
        if sector not in self._cache:
            return None
        count, ts = self._cache[sector]
        if time.monotonic() - ts > self._ttl:
            del self._cache[sector]
            return None
        # LRU: move to end
        self._cache.move_to_end(sector)
        return count
    
    def set(self, sector: str, count: int):
        self._cache[sector] = (count, time.monotonic())
        self._cache.move_to_end(sector)
        if len(self._cache) > self._maxsize:
            self._cache.popitem(last=False)
    
    def invalidate(self, sector: str):
        """写入项目时使对应赛道缓存失效"""
        self._cache.pop(sector, None)
        self._dirty = True
    
    def refresh_all(self, db_cursor):
        """全量刷新：SELECT sector, COUNT(*) FROM projects GROUP BY sector"""
        rows = db_cursor.execute("SELECT sector, COUNT(*) FROM projects GROUP BY sector").fetchall()
        now = time.monotonic()
        self._cache.clear()
        for sector, count in rows:
            self._cache[sector] = (count, now)
        self._dirty = False
```

**使用方式**：
- 每次评分时调用 `cache.get(sector)`，miss 时回退 `COUNT(*)` 并更新缓存。
- 每次 Write 阶段更新 project 后调用 `cache.invalidate(sector)` 使该赛道计数失效。
- TTL 默认 300s（5min），保证下一轮 run 自动刷新。

**LRU 容量**：赛道数通常 ≤50（DefiLlama 约 30 个赛道），默认 maxsize=100 足够。

---

#### 方案二：DB `sector_counts` 物化表 + 增量更新（V2 PG）

##### 表结构

```sql
-- sector_counts 物化表（V2，存储实时赛道计数）
CREATE TABLE sector_counts (
    sector      TEXT PRIMARY KEY,       -- 标准化赛道名（§6.2.1 sector_key）
    count       INTEGER NOT NULL,       -- 该赛道的 projects 表行数
    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

##### 增量更新策略

| 事件 | SQL | 触发时机 |
| --- | --- | --- |
| INSERT projects | `UPDATE sector_counts SET count = count + 1 WHERE sector = ?` | Write 阶段 COMMIT 后 |
| DELETE projects | `UPDATE sector_counts SET count = count - 1 WHERE sector = ?` | 数据清理时 |
| 全量重建 | `INSERT OR REPLACE INTO sector_counts SELECT sector, COUNT(*) FROM projects GROUP BY sector` | 启动时 / 跨天首次 run |

##### PostgreSQL Trigger（V2 切 PG 后）

```sql
-- V2 PostgreSQL trigger 自动更新 sector_counts
CREATE OR REPLACE FUNCTION update_sector_count()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        INSERT INTO sector_counts (sector, count, updated_at)
        VALUES (NEW.sector, 1, NOW())
        ON CONFLICT (sector) DO UPDATE SET
            count = sector_counts.count + 1,
            updated_at = NOW();
        RETURN NEW;
    ELSIF TG_OP = 'DELETE' THEN
        UPDATE sector_counts SET count = count - 1, updated_at = NOW()
        WHERE sector = OLD.sector;
        RETURN OLD;
    ELSIF TG_OP = 'UPDATE' AND OLD.sector <> NEW.sector THEN
        -- 赛道变更：旧赛道 -1，新赛道 +1
        UPDATE sector_counts SET count = count - 1, updated_at = NOW() WHERE sector = OLD.sector;
        INSERT INTO sector_counts (sector, count, updated_at)
        VALUES (NEW.sector, 1, NOW())
        ON CONFLICT (sector) DO UPDATE SET
            count = sector_counts.count + 1,
            updated_at = NOW();
        RETURN NEW;
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_projects_sector_count
    AFTER INSERT OR DELETE OR UPDATE OF sector ON projects
    FOR EACH ROW EXECUTE FUNCTION update_sector_count();
```

##### 全量重建策略

| 场景 | 触发 | SQL |
| --- | --- | --- |
| 应用启动 | 首次缓存 miss | `REFRESH MATERIALIZED VIEW` 或 `INSERT OR REPLACE ... SELECT COUNT(*) ...` |
| 跨天首次 run | 每日 cron 执行 run 前 | 同启动 |
| 数据修复后 | 手动触发 | 同上 |
| 数据一致性检查 | 定期（每日 cron） | `SELECT sector, COUNT(*) FROM projects GROUP BY sector` 比对 sector_counts，差异 >1% 告警 |

---

#### MVP 策略：直接 COUNT

MVP 项目数 ≤ 1k，`SELECT COUNT(*) FROM projects WHERE sector=?` 在 SQLite 上耗时 <10ms，无需缓存。

```python
# MVP 直接 COUNT
def get_sector_count(db, sector: str) -> int:
    row = db.execute("SELECT COUNT(*) FROM projects WHERE sector = ?", (sector,)).fetchone()
    return row[0]
```

---

#### 并发安全

| 场景 | 进程内 LRU | DB sector_counts + trigger |
| --- | --- | --- |
| 并发写同一 sector | `invalidate()` 后下一读重建，无竞态 | PG trigger 在事务内串行，行锁保护 |
| 进程内缓存 stale | TTL 到期自动刷新 | N/A（trigger 实时更新） |
| 多进程实例 | 各进程独立缓存，不一致窗口 ≤ TTL | PG 行锁保证对账一致 |
| V3 Redis | Redis `INCR` 原子操作 | Redis 单线程保证原子 |

**核心保证**：缓存与 DB 的不一致窗口 ≤ TTL（默认 5min），且缓存值偏差不超过 ±1（并发写入时）。

---

#### 监控指标

| 指标 | 类型 | 标签 | 含义 |
| --- | --- | --- | --- |
| `airdrop_competition_cache_hits_total` | counter | `sector` | 缓存命中次数 |
| `airdrop_competition_cache_misses_total` | counter | `sector` | 缓存 miss 次数（回退 COUNT） |
| `airdrop_competition_cache_stale_entries` | gauge | — | 当前缓存中已过期的条目数 |
| `airdrop_competition_db_count_duration_seconds` | histogram | `sector` | COUNT 查询耗时（仅 miss 时） |
| `airdrop_competition_sector_count` | gauge | `sector` | 当前各赛道计数（便于监控赛道分布） |

---

#### 与 re-score 的集成

`POST /re-score/{id}` 需要重新计算 competition 子分。策略：
- **MVP**：直接 COUNT 全库（无缓存，50 项目无压力）。
- **V2（进程内 LRU）**：使用缓存（可能滞后 ≤ TTL）；如需精确值在 re-score 前调用 `cache.invalidate(sector)` 触发下一读重建。
- **V2（DB sector_counts）**：直接读 `sector_counts` 表（trigger 实时更新，无需特殊处理）。
- re-score 后如有 sector 变更（极少发生），同样触发缓存失效。

---

#### 设计取舍记录

1. **为什么不读时缓存（read-through cache）+ 写时更新？**
   - 写时更新（invalidate-on-write）比读时缓存更简单，不存在缓存击穿问题。
   - 写操作频率远低于读（每日 1 次 run vs 实时 Dashboard 查询），invalidate 开销可忽略。

2. **为什么不采用 Redis 作为 V2 默认缓存？**
   - 单进程场景下进程内 LRU 足够，引入 Redis 增加运维复杂度。
   - V3 多实例时才需要 Redis 共享缓存。

3. **增量计数精度风险**：
   - `UPDATE sector_counts SET count = count + 1` 在 trigger 中可能因异常跳过（如 trigger 内出错导致项目 INSERT 回滚，但一般事务内不会）。
   - 缓解：每日全量重建 `sector_counts` + 一致性比对告警。

---

### 7.6 缺失字段与降级策略
外部源常缺 tokenomics/team 数据，评分必须能优雅降级而非崩在 None：
| 缺失字段 | 降级子分 | 影响 | reason 标记 |
| --- | --- | --- | --- |
| `tokenomics_json` | tokenomics 子分 = 50（中性） | 仅该子项失真 | `"tokenomics data missing"` |
| `team_json` | team 子分 = 50（中性） | 仅该子项失真 | `"team data missing"` |
| `risk.token_risk` | token_risk = 0.5（中风险） | risk 子分走中性 | `"risk estimate uncertain"` |
| `narrative.heat_score` | heat_score = 0.5，timing=`early` | narrative 子分中性 | `"narrative heat unknown"` |
| `raw_signals` 全空 | airdrop_signal = 20 | 显著拉低总分 | `"no airdrop signal"` |

- **降级覆盖率上限**：若 4 个分析 agent 中 ≥3 个为缺失/降级，则该项目 `label` 强制降一档（FARM→WATCH，WATCH→IGNORE），并在 reason 追加 `"low data confidence"`，避免数据稀薄项目拿到虚高分。
- **缺失计数**写入 `meta.missing_count`，供 Dashboard 标灰与可解释性展示。

### 7.7 平滑与归一化
- 子分计算后统一 `clamp(x, 0, 100)`，避免浮点误差越界。
- 总分 `round()` 采用 `round-half-to-even`（Python 默认银行家舍入），保证大量样本下无系统性偏差。
- **不做** 子分曲线压缩（如 sigmoid）——保持线性可解释性；如未来需拉开中段分布，再在 V3 引入可配置映射函数并由 ADR 决议。

### 7.8 排序与 tie-break
`GET /projects` 默认按 `score DESC`，同分时依次按（均可在 SQL 层完成）：
1. `airdrop_signal` 子分（高优先，空投信号强者优先）——可在 `projects` 表冗余存储该子分或按 `reason` 不可排序时以 `confidence` 兜底
2. `narrative.heat_score`（热度高优先）——取自 `narrative_json` 无法 SQL 排序时，以 `confidence` 替代
3. `confidence`（数据完整者优先，高者优先；等价于 `meta.missing_count` 升序，因 `confidence = 1 - missing_count/4`）——**可在 SQL 层 `ORDER BY confidence DESC`**
4. `name` 升序（稳定字典序兜底）

> 实现说明：`airdrop_signal` 子分与 `narrative.heat_score` 存于 JSON 列，SQL 无法直接排序；推荐在 `projects` 表冗余 `airdrop_signal_subscore REAL` 列（或在 Scorer 写库时一并写入），使 tie-break 1–2 可在 SQL 层完成。若暂不冗余，则退化为 `ORDER BY score DESC, confidence DESC, name ASC`，保证排序始终在 SQL 层。

排序必须在 SQL 层完成（`ORDER BY score DESC, ... LIMIT`），避免内存排序随数据量增长。

### 7.9 权重校准流程（V2 引入，V3 闭环）
当前 §7.1 权重为经验初值，需可校准：
1. **样本采集**：V2 起在 `logs` 记录每项目最终 `label` 与用户反馈（§24）。
2. **离线回测**：维护 `backtest.py`，对历史项目用候选权重集重算，对比"用户事后标注"（FARM 是否真涨/真空投）计算命中率与误报率。
3. **网格搜索**：在权重空间（每项 0.05–0.40，Σ=1.0）做网格/贝叶斯优化，目标函数 = `recall(FARM) − 2×false_positive(FARM)`（惩罚误报）。
4. **灰度发布**：新权重写入 `config.weights_v2`，双跑对比 1 周再切默认。
5. **版本化**：`ScoreResult` 增加 `weight_version` 字段，回测可按版本溯源。
- MVP 阶段权重冻结在 §7.1 初值，不提供运行时调整接口，避免不可解释的评分漂移。

---

## 8. API 设计（FastAPI REST）

基址：`/api/v1`（文档用简写）。所有响应 `application/json`，统一包络：
```json
{ "ok": true, "data": ..., "error": null }
```

### 8.1 `POST /run`
 触发一次完整分析 pipeline。
 - 请求体：`{ "source": "all" | "seed" | "defillama" | "cryptorank", "limit": 50 }`（可选）
 - 响应：
 ```json
 { "ok": true,
   "data": { "analyzed": 23, "inserted": 18, "updated": 5, "failed": 0, "errors": [], "top_id": "uuid", "top_score": 83, "elapsed_ms": 1240 } }
 ```
 - 响应字段 `failed` 表示异常项目数（超时/异常），`errors` 列表含每个失败项目的 `project_id` 与 `reason`。
 - 异步：MVP 同步执行（项目量小）；V2 改为后台 task + 进度查询。

### 8.2 `GET /projects`
- Query：`?label=FARM&sector=L2&limit=50&order=DESC`
- 响应：`ProjectRecord[]`（不返回大体积 JSON 列可裁剪，前端按需拉详情）。

### 8.3 `GET /project/{id}`
- 响应：完整 `ProjectRecord`（含四个 agent 的 json 明细 + reason）。

### 8.4 `POST /re-score/{id}`
- 用最新规则/数据对该项目重算评分。
- 响应：更新后的 `ProjectRecord`。

### 8.5 `GET /insights`（V2 增强，MVP 可返回聚合）
 - 响应：`{ "hottest_narratives":[...], "risky_teams":[...], "score_distribution":{...} }`

### 8.6 其他端点（阶段归属，详细见 API_SPEC.md）
 - `POST /api/v1/feedback` / `GET /api/v1/feedback`：**V2**（用户反馈回流，§24.1）。
 - `POST /api/v1/events`：**V2**（隐式行为埋点，对应 `events` 表）。
 - `GET /api/v1/audit`：**V2**（审计日志查询，对应 `audit_logs` 表；MVP 无鉴权，本地使用）。
 - 端点总览与请求/响应样例以 [API_SPEC.md](API_SPEC.md) 为准。


### 8.7 错误码
- `400` 参数错误；`404` 项目不存在；`500` agent 执行失败（带 `logs` 定位）。
- 鉴权：MVP 无；V2 用 API Key / Bearer（环境变量 `API_KEY`）。

---

## 9. 前端 Dashboard 设计

### 9.1 页面结构
| 页面 | 内容 |
| --- | --- |
| **Dashboard** | Top ranked 项目卡片、score 分布图、FARM/WATCH/IGNORE 计数 |
| **Project Detail** | 完整 agent 分析、risk 拆解、narrative 阶段、reason 列表 |
| **Insight** | 最热叙事排行、高风险团队聚类、赛道分布 |

### 9.2 UI 核心指标
- Score（0–100，色阶：≥70 绿 / 50–69 黄 / <50 灰）
- Label（FARM / WATCH / IGNORE 徽章）
- Risk level（low/medium/high）
- Narrative stage（early/peak/late）

### 9.3 技术实现
- **MVP**：单页 `index.html` + 原生 `fetch` 调用 API，CDN 引入轻量图表库（如 Chart.js），零构建即可预览。
- **V2**：Next.js 14 App Router + Tailwind + TanStack Query，组件化、SSR。
- 关键交互：点击项目 → 拉 `/project/{id}` → 渲染四个 agent 明细卡。

---

## 10. 真实数据接入（V2 重点）

| 数据源 | 用途 | 接入方式 | 降级 |
| --- | --- | --- | --- |
| DefiLlama | 新协议/新项目 | 公开 REST（无需 key） | 失败→用种子数据 |
| CryptoRank | 项目库/TGE 日历 | API key（免费档） | 失败→跳过 |
| Twitter | 关键词热度/空投线索 | Twitter API v2 / 第三方 | 限流→缓存 |
| Dune | 链上指标/地址活跃 | Dune API（API key） | 失败→规则估计 |

- **成本**：默认 MVP 不调用任何付费 API；环境变量开启后才启用。
- **合规**：仅做公开数据聚合，不抓取需授权隐私数据。

### 10.1 统一 Fetcher 契约
所有外部调用走 `fetcher.get(url, cache_key, ttl, timeout)`，统一处理：
- **缓存**：按 `cache_key` 写入进程内 LRU + 可选磁盘层（`data/cache/`）。TTL 按数据源分级（见 §10.3）。
- **超时**：连接 5s / 读取 15s；超时即视为失败，不重试到死。
- **重试**：仅对 5xx / 网络错误重试，4xx（含 401/403/429）不重试（429 按 `Retry-After` 头等待后重试一次）。
- **退避**：指数退避 `base=1s, factor=2, max=30s, cap=3 次`，抖动 ±20% 避免惊群。
- **熔断**：滑动窗口（30s 内 10 次请求）错误率 >50% → 熔断 60s，期间直接走降级路径，不发请求。
- **可观测**：每次调用记 `fetcher_duration_seconds`、`fetcher_errors_total{source}`、`fetcher_circuit_open{source}`。

### 10.2 容错与降级矩阵
| 源 | 失败语义 | 降级路径 | 对评分影响 |
| --- | --- | --- | --- |
| DefiLlama | 新协议拉取失败 | 回退 `seed.py` 演示集 | 无（仍可跑通 pipeline） |
| CryptoRank | 项目库/TGE 失败 | 跳过该源，仅用 DefiLlama | coverage↓，单项目评分不变 |
| Twitter | 限流 429 | 走缓存（可能过期）→ 缓存 miss 则 `heat_score=0.5` 中性 | narrative 子分走中性（§7.6） |
| Dune | 链上指标失败 | `token_risk` 走规则估计（基于 raw_signals 启发式） | risk 子分不确定，reason 标 `"risk estimate uncertain"` |
| 任意源 | 熔断开启 | 该源在熔断窗口内全部走降级 | 同上对应行 |

### 10.3 缓存 TTL 策略
| 数据 | TTL | 理由 |
| --- | --- | --- |
| DefiLlama `/protocols` | 1h | 协议列表变化慢 |
| DefiLlama `/new` | 15min | 新项目需较新 |
| CryptoRank 项目库 | 6h | 日历级更新 |
| Twitter 热度 | 30min | 热度需及时但不至于打爆配额 |
| Dune 查询结果 | 1h | 查询本身昂贵，结果稳定 |

缓存 key 含查询参数 hash；命中时附加 `X-Cache: HIT/MISS/STALE` 响应头便于调试。

### 10.4 数据新鲜度与回填
- 每次 fetch 记 `fetched_at`；Dashboard 在数据 >2×TTL 时标"可能过期"。
- 支持手动 `POST /run?source=defillama&force_refresh=true` 绕过缓存（V2，需鉴权）。
- 历史项目 re-score 默认用缓存数据；如需最新可先清缓存再 re-score。

---

## 11. 运行流程与调度

1. 每日 cron trigger（如 08:00）
2. Collector 拉取项目（真实/V2）
3. 去重 + enrich
4. 每个项目进入 agent pipeline（analyze 并行）
5. 评分决策引擎汇总
6. 排序输出，写库
7. API + Dashboard 更新（V2 加 Telegram 推送）

- **本地**：`python run.py` 起服务；另开终端 `curl -X POST localhost:8000/api/v1/run`。
- **容器**：compose 内 `scheduler.py` 常驻触发，或宿主 cron 打容器内端口。

---

## 12. 演进路线（细化）

### 🟢 MVP（本阶段目标，可本地运行）
**交付物**：
- 后端：FastAPI + 7 个 agent（规则引擎）+ SQLite + REST API（§8.1–8.4）
- 前端：单页 HTML Dashboard（预览版）
- 数据：内置种子项目 + 可选 DefiLlama 公开接口
- 部署：Dockerfile + docker-compose
- 文档：README + 本 Roadmap
**退出标准**：`POST /run` 能跑通并写库；`GET /projects` 返回排序结果；Dashboard 可预览 Top 项目。

### 🟡 V2（增强）
- Twitter + Dune 真实数据接入（§10）
- 自动趋势识别（动态 heat_score）
- Telegram 推送每日 Top N
- Next.js 正式 Dashboard + `/insights`
- 切换 PostgreSQL + Alembic 迁移
- LLM 增强（可选插件，ADR-1）

### 🔴 V3（高级）
- 多钱包策略建议（基于风险/Sybil 难度）
- 自动 farming checklist 生成
- AI 持续学习（memory system：用户反馈回流重训权重）
- 多项目并发 pipeline + 队列
- 监控/告警（Prometheus + 异常检测）

---

## 13. 里程碑与排期（建议，按周）

| 周次 | 里程碑 | 交付 | 验收门 |
| --- | --- | --- | --- |
| W1 | 基础设施 | 目录结构、config/models/db、FastAPI 骨架、DB 建表、fetcher 骨架 | `/health` 200；`init_db()` 幂等 |
| W2 | Agent 核心 | Collector（含归一化去重）+ 4 分析 agent + Scorer + Orchestrator（规则引擎） | 单元测试全绿；LayerX golden 用例通过 |
| W3 | API + 前端 | REST 4 端点、单页 Dashboard、联调 | API 测试通过；Dashboard 可预览 Top |
| W4 | 部署 + 文档 + 可观测骨架 | Docker/compose、README、种子数据、structlog + `/metrics` 骨架、CI 流水线 | `docker compose up` 可用；CI 绿；MVP DoD（§17）达标 |
| W5 | LLM 集成（ADR-001） | `llm_enhance` 钩子、prompt 模板、降级链、成本控制 | LLM 开/关双路径测试通过；超预算自动停用 |
| W6 | 安全与合规硬化 | pip-audit 进 CI、SRI、鉴权骨架（API_KEY）、输入校验审计 | 安全扫描无高危；鉴权端点 401 用例通过 |
| W7–W8 | V2 数据 | DefiLlama/CryptoRank/Twitter/Dune 接入、容错矩阵、Next.js Dashboard | 4 源成功率 ≥95%（在线）；熔断/降级演练通过 |
| W9 | 可观测性完整 | Prometheus 全指标、Grafana 面板、告警规则、OpenTelemetry trace | 面板可观测所有 §20.2 指标；告警演练通过 |
| W10 | V2 数据层迁移 | Alembic、PostgreSQL、V2 新表（§5.4）、SQLite→PG 迁移脚本 | 切换零数据丢失；回滚演练通过 |
| W11 | 反馈与校准闭环 | feedback/events 表、backtest.py、权重灰度发布机制 | 样本 ≥200 触发首次校准；changelog 记录完整 |
| W12+ | V3 | 多钱包策略、memory 系统、多实例 HA、异常检测 | 按子项目单独验收 |

> 排期为单人集约估算；团队协作可压缩。每里程碑结束需通过对应验收门（§14 测试 + §17 DoD）方可进入下一阶段。
> **关键路径**：W1→W2→W3→W4（MVP 完成）→W5/W6 可并行→W7–W11（V2 渐进）→W12+（V3）。

---

## 14. 测试策略

### 14.1 测试金字塔
| 层 | 工具 | 覆盖目标 | 数量级 |
| --- | --- | --- | --- |
| 单元 | pytest | 每个 Agent `run()` + 评分公式 + 归一化/去重 | ~50 |
| 契约 | pytest | Agent 输入/输出 schema 对齐 Result 模型 | ~10 |
| 集成 | pytest + TestClient | Orchestrator 全链路 + 4 个 API 端点 | ~15 |
| 可解释性 | pytest | reason 规则、降级标记、tie-break | ~10 |
| 属性 | hypothesis | 评分边界/单调性/确定性 | ~5 |
| 回归 | pytest（golden） | 历史快照防漂移 | 持续积累 |

### 14.2 单元测试关键用例
- **Narrative**：early/growth/peak/mature 四 stage → timing 映射正确；heat_score 边界 0/1。
- **Team**：匿名团队 → score 扣 0.2 + flag；知名 VC → +0.2；多 flag 叠加截断 [0,1]。
- **Risk**：sybil_difficulty 三档 × farming_cost 三档组合；token_risk 缺失走 0.5。
- **Tokenomics**：`risk = vc×0.4+team×0.3+unlock×0.3` 公式断言；unlock_pressure 三档映射。
- **Scorer**：6 子项加权精确到 0.1；clamp [0,100]；round-half-to-even。
- **Collector**：归一化（`"Layer2 Finance"` vs `"layer2-finance"` 命中同 dedup_key）；UUID v5 跨 run 稳定。

### 14.3 契约测试（Agent 接口稳定性）
每个 Agent 必须通过 `tests/contracts/test_<agent>.py`：给定固定 `AgentContext` → 输出 dict 能通过对应 Result Pydantic 模型校验。任何字段变更先改契约测试，强制显式 breaking change。

### 14.4 可解释性测试（硬性规则）
- 每个 FARM 项目 `reason` ≥2 条且含 ≥1 正向。
- 每个 IGNORE 项目含 ≥1 反向信号。
- 缺失字段场景必含对应 `"* missing/uncertain"` 标记。
- `meta.missing_count ≥3` 时 label 必降一档。

### 14.5 属性测试（hypothesis）
- **边界**：任意合法输入 → `0 ≤ score ≤ 100`。
- **单调性**：固定其他子分，单个子分↑ → score 不↓。
- **确定性**：相同输入两次 run → 完全相同输出（含 reason 顺序）。
- **权重和**：`Σweight == 1.0`（配置加载时断言）。

### 14.6 Golden 回归集
`tests/golden/projects.jsonl` 维护 20+ 历史项目（含 LayerX 示例）的"输入→期望输出"快照。CI 跑 `pytest tests/golden` 对比，差异需人工 review 后更新快照（防隐性评分漂移）。

### 14.7 API 测试
- 4 端点 × 正常/异常路径（含 400/404/422/500）。
- `GET /projects` 过滤/排序/分页参数组合。
- `POST /run` 幂等性：同 source 连续调用不产生重复 id。

### 14.8 覆盖率门槛
- MVP：行覆盖率 ≥ 80%，关键模块（agents/scorer/orchestrator/db）≥ 90%。
- CI 在覆盖率下降 >3% 时告警（不阻断，供 review）。

---

## 15. 部署与运维
> 本地/Docker/环境变量/备份/健康检查的详细步骤见 [DEPLOYMENT.md](DEPLOYMENT.md)；值班/故障处理/恢复 runbook 见 [OPERATIONS.md](OPERATIONS.md)。本节聚焦 Roadmap 视角的发布与运维策略。

### 15.1 部署形态演进
| 阶段 | 形态 | 触发切换条件 |
| --- | --- | --- |
| MVP | 单容器 docker-compose（FastAPI + 静态前端 + SQLite） | — |
| V2 | compose 双服务（web + nginx 前端） + PostgreSQL | 数据量 >10k 项目 或 多用户 |
| V3 | 多实例 + 队列（Celery/RQ） + Prometheus | 并发 pipeline 或需要 HA |

### 15.2 CI/CD 流水线（GitHub Actions）
```
push/PR → lint(ruff) → test(pytest + coverage) → build(docker) → 发布(仅 main tag)
```
- **lint**：`ruff check` + `ruff format --check`，失败阻断。
- **test**：`pytest -q --cov`，覆盖率门槛见 §14.8。
- **build**：构建镜像并推送 `ghcr.io/<org>/airdrop-alpha:<sha>`；缓存 `pip` 与 docker layer。
- **发布**：仅 `main` 分支 + git tag `v*` 触发，更新 `latest` tag 并部署到演示环境。
- **冒烟**：部署后自动 `curl /health` + `POST /run?source=seed`，断言 `analyzed>0`。

### 15.3 数据库迁移与回滚
- MVP：`init_db()` 幂等建表，无迁移。
- V2：Alembic；每次迁移必须含 `upgrade` + `downgrade`，CI 跑 `alembic upgrade head` → `downgrade base` 验证可回滚。
- **回滚策略**：应用回滚优先于数据回滚；schema 迁移采用"先兼容双写 → 切读 → 删旧列"三步，保证应用可回退到上一版本而不依赖数据回滚。

### 15.4 配置管理（pydantic-settings）
`config.py` 集中管理，分三档优先级：环境变量 > `.env` > 代码默认值。关键配置组：
- `WeightsConfig`：6 项权重（Σ=1.0，启动断言）。
- `ThresholdsConfig`：FARM/WATCH 阈值（默认 70/50）。
- `SourcesConfig`：各数据源开关 + TTL + 超时。
- `LLMConfig`：模型名、temperature、预算上限、超时。
- `SchedulerConfig`：cron 表达式、并发数。
配置变更需在 PR 说明并更新 `.env.example`；运行时通过 `/health` 返回 `config_version` 便于排查。

### 15.5 日志与可观测
- structlog JSON 输出，含 `run_id`/`project_id`/`agent_name` 贯穿链路。
- 详细指标/追踪/告警见 §20。

### 15.6 备份与灾恢
- SQLite：每日 cron `cp` 到 `backups/`，保留 14 天。
- V2 PostgreSQL：`pg_dump` 每日 + WAL 归档。
- RPO ≤ 24h、RTO ≤ 1h（MVP 单机，可接受）。V3 提升到 RPO ≤ 1h。

---

## 16. 风险、开放问题与 ADR 索引

### 16.1 ADR 决议索引
| ADR | 标题 | 状态 | 摘要 |
| --- | --- | --- | --- |
| [ADR-001](adr/ADR-001-llm-default-off.md) | MVP 默认关闭 LLM | Accepted | 规则引擎默认；`OPENAI_API_KEY` 存在时启用可选插件，失败回退规则 |
| [ADR-002](adr/ADR-002-self-built-orchestrator.md) | 自研轻量 Orchestrator | Accepted | 对齐 LangGraph（state+node+reducer）；保留无痛迁移路径 |
| [ADR-003](adr/ADR-003-single-page-html-mvp.md) | MVP 前端单页 HTML | Accepted | 零构建预览；正式 Next.js 在 V2 |
| [ADR-004](adr/ADR-004-sqlite-to-postgres.md) | SQLite(WAL) → PostgreSQL | Accepted | MVP 零运维；V2 按 4 个触发条件切 PG |
| [ADR-005](adr/ADR-005-apscheduler-inprocess.md) | APScheduler 进程内调度 | Accepted | 容器自包含；多实例时 V3 用 leader election |
| [ADR-006](adr/ADR-006-weights-freeze.md) | 评分权重初值冻结与校准策略 | Accepted | MVP 权重冻结；V2 灰度校准 |
| [ADR-007](adr/ADR-007-multi-project-concurrency.md) | 多项目并发模型 | Accepted | 三级并行 + Semaphore + 事务边界 |
| [ADR-008](adr/ADR-008-user-system.md) | 用户系统与多租户隔离 | Accepted | 三阶段演进（匿名→API Key→JWT）+ RBAC + 行级隔离 |
| [ADR-009](adr/ADR-009-api-versioning.md) | API 版本管理策略 | Accepted | URL 前缀 + 版本生命周期（Alpha/Stable/Deprecated/Sunset）+ 90 天弃用窗口 |
| [ADR-010](adr/ADR-010-competition-cache.md) | 竞争度子分缓存与增量计数 | Accepted | 三阶段演进（直接 COUNT→LRU→物化表+Trigger） |
| [ADR-011](adr/ADR-011-mvp-chart-library.md) | MVP Dashboard 图表库选型 | Accepted | MVP 用 Chart.js 4.x CDN，三种图表类型；国内访问问题走降级方案 |

### 16.2 已知风险清单（Roadmap 评审更新 · 2026-07-08）

| # | 风险项 | 阶段 | 影响 | 缓解措施 | 状态 |
| --- | --- | --- | --- | --- | --- |
| 1 | Pydantic 模型与字典对齐偏差 | W1 | 后期返工代价大，字段不一致导致序列化失败 | 模型定义后立即跑契约测试（§14.3） | 🔵 监控中 |
| 2 | 归一化/去重逻辑边界 case 覆盖不足 | W2 | 同项目漏合并或不同项目误合并 | 前置 20+ 边界 case 测试集（大小写/Unicode/词表） | 🔵 监控中 |
| 3 | Chart.js CDN 国内访问不稳定 | W3 | Dashboard 图表无法加载 | 备选 ECharts 或本地打包（vendoring） | 🔵 监控中 |
| 4 | CI 流水线首次搭建踩坑 | W4 | GitHub Actions 权限/缓存/镜像推送配置复杂 | 参考官方模板；先跑通 lint+test，再叠加 build | 🔵 监控中 |
| 5 | Prompt 模板调优周期超预期 | W5 | 结构化输出 + evidence 抽取不稳定 | 先跑通 JSON schema 约束，再迭代调优 | 🔵 监控中 |
| 6 | API_KEY 鉴权中间件与 MVP 无鉴权模式切换冲突 | W6 | 鉴权中间件引入后本地调试受阻 | 环境变量开关控制（`API_KEY` 空则跳过校验） | 🔵 监控中 |
| 7 | Next.js Dashboard 学习曲线（App Router + Tailwind + TanStack） | W7–W8 | 前端进度滞后 | 先用最小可用组件跑通，再逐步完善 | 🔵 监控中 |
| 8 | backtest.py 网格搜索/贝叶斯优化实现复杂度 | W11 | 权重校准功能延期 | 先实现网格搜索，贝叶斯优化 V3 补充 | 🔵 监控中 |
| 9 | Memory 系统依赖 V2 数据积累（冷启动无数据） | W12+ | V3 memory 无数据可读 | V2 采集期提前埋点（§24.1），保证 3-6 个月数据量 | 🔵 监控中 |
| 10 | 外部源限流/故障（Twitter/Dune） | V2 | 数据覆盖率下降 | 容错矩阵见 §10、§19.4；缓存 + 熔断 + 降级 | 🔵 监控中 |
| 11 | SQLite 并发写 busy | MVP | 高频写入场景下性能退化 | WAL + 单写者 + V2 切 PG | 🔵 监控中 |
| 12 | LLM 成本失控 | V2 | 启用后调用频次不可控 | 预算/采样/缓存见 §19.5；超预算自动停用 | 🔵 监控中 |
| 13 | 数据质量（公开源缺失 tokenomics） | V2 | 评分准确性下降 | 规则引擎兜底（§22）；缺失字段降级策略（§7.6） | 🔵 监控中 |
| 14 | 评分偏差（权重需用户反馈校准） | V2+ | 评分系统性偏差 | §7.5 校准流程 + V3 memory（§24）；样本 ≥200 触发首次校准 | 🔵 监控中 |
| 15 | 合规风险 | 全周期 | 误抓隐私数据或违反 API ToS | 仅公开数据聚合（§21）；不存 PII；输出非投资建议声明 | 🔵 监控中 |

### 16.3 风险升级规则
- **🔵 监控中** → 常规跟踪，周会 review
- **🟡 升级** → 影响本里程碑交付，需 Tech Lead 介入
- **🔴 紧急** → 影响整体 Roadmap，需 ADR 决议或排期调整
- **✅ 已关闭** → 风险消除或缓解措施生效

> 新增风险由里程碑评审识别，经 Tech Lead 评估后纳入本表。每里程碑结束前 review 一次风险状态。

---

## 17. 验收标准（Definition of Done · MVP）
- [ ] `POST /run` 端到端跑通，写入 ≥ N 个项目到 `projects` 表
- [ ] 每个项目含合法 `score`(0-100)、`label`、`reason`（≥2 条）
- [ ] `GET /projects` 按 score 降序返回；过滤参数可用；tie-break 规则生效（§7.8）
- [ ] `GET /project/{id}` 返回四 agent 明细
- [ ] `POST /re-score/{id}` 正确更新评分；幂等（重复调用不产生新 id，§6.2.3）
- [ ] 缺失字段场景按 §7.6 降级，`meta.missing_count ≥3` 时 label 降一档
- [ ] 单页 Dashboard 可预览 Top 项目与分布
- [ ] `docker compose up` 可启动并访问；`/health` 返回 healthy
- [ ] `pytest` 全绿；行覆盖率 ≥ 80%（§14.8）
- [ ] golden 回归集（§14.6）通过
- [ ] 配置权重 `Σ=1.0` 启动断言通过（§15.4）
- [ ] README 含启动/使用/架构说明

> V2/V3 额外验收项随对应里程碑补充（LLM 降级测试、安全扫描、可观测性面板等，见 §19/§20/§21）。

---

## 18. ADR 决议记录（Architecture Decision Records）

> 完整 ADR 独立成文，存放于 [docs/adr/](adr/)。本节为索引摘要。
>
> 格式：背景 → 决策 → 理由 → 后果。新增 ADR 按序号追加；旧决策被推翻时标记 `Status: Superseded by ADR-0xx`，不删除原文。
>
> **ADR 交叉引用图谱**：所有 ADR 间的细化、依赖、引用、同层关系及交叉风险详见 [ADR_CROSS_REFERENCE.md](adr/ADR_CROSS_REFERENCE.md)。新增 ADR 时同步更新该文档。

| ADR | 标题 | 状态 | 摘要 |
| --- | --- | --- | --- |
| [ADR-001](adr/ADR-001-llm-default-off.md) | MVP 默认关闭 LLM | Accepted | 规则引擎默认；`OPENAI_API_KEY` 存在时启用可选插件，失败回退规则 |
| [ADR-002](adr/ADR-002-self-built-orchestrator.md) | 自研轻量 Orchestrator | Accepted | 对齐 LangGraph（state+node+reducer）；保留无痛迁移路径 |
| [ADR-003](adr/ADR-003-single-page-html-mvp.md) | MVP 前端单页 HTML | Accepted | 零构建预览；正式 Next.js 在 V2 |
| [ADR-004](adr/ADR-004-sqlite-to-postgres.md) | SQLite(WAL) → PostgreSQL | Accepted | MVP 零运维；V2 按 4 个触发条件切 PG |
| [ADR-005](adr/ADR-005-apscheduler-inprocess.md) | APScheduler 进程内调度 | Accepted | 容器自包含；多实例时 V3 用 leader election |
| [ADR-006](adr/ADR-006-weights-freeze.md) | 评分权重初值冻结与校准策略 | Accepted | MVP 权重冻结；V2 灰度校准 |
| [ADR-007](adr/ADR-007-multi-project-concurrency.md) | 多项目并发模型 | Accepted | 三级并行 + Semaphore + 事务边界 |
| [ADR-008](adr/ADR-008-user-system.md) | 用户系统与多租户隔离 | Accepted | 三阶段演进（匿名→API Key→JWT）+ RBAC + 行级隔离 |
| [ADR-009](adr/ADR-009-api-versioning.md) | API 版本管理策略 | Accepted | URL 前缀 + 版本生命周期（Alpha/Stable/Deprecated/Sunset）+ 90 天弃用窗口 |
| [ADR-010](adr/ADR-010-competition-cache.md) | 竞争度子分缓存与增量计数 | Accepted | 三阶段演进（直接 COUNT→LRU→物化表+Trigger） |
| [ADR-011](adr/ADR-011-mvp-chart-library.md) | MVP Dashboard 图表库选型 | Accepted | MVP 用 Chart.js 4.x CDN，三种图表类型；国内访问问题走降级方案 |

**何时新增 ADR**：架构级决策、权重/阈值初值冻结、有迁移成本的决策。详见 [docs/adr/README.md](adr/README.md)。

---

## 19. LLM 集成设计（ADR-001 落地）

### 19.1 启用条件与模型选择
- 仅当 `LLMConfig.enabled=true`（即 `OPENAI_API_KEY` 非空）时启用。
- **默认模型**：`gpt-4o-mini`（性价比，narrative/team 文本足够）；可选 `gpt-4o` 用于复杂研判。
- **调用模式**：同步阻塞 + 软超时（`deadline_ms`，默认 8s）；超时即回退规则引擎。

### 19.2 Prompt 契约（结构化输出）
所有 LLM 调用要求返回 **JSON**，用统一 schema 约束，避免自由文本解析：
```json
// Narrative LLM 增强示例
{
  "heat_score_adjustment": -0.1,   // 对规则 base_heat 的修正，[-0.3, 0.3]
  "timing_correction": null,       // 可选覆盖：early/peak/late
  "evidence": ["KOL 讨论量上升 40%", "新协议周环比 +5"]
}
```
- 修正值有界，防 LLM 单次调用把分数打飞。
- `evidence` 注入 reason，提升可解释性。
- Prompt 模板维护在 `agents/prompts/`，版本化（`prompt_version` 写入 logs）。

### 19.3 降级链
```
LLM 调用 → 解析成功 → 应用修正
        → 超时/4xx/5xx/JSON 解析失败 → 回退规则引擎结果
        → 记 AgentError(kind="llm_fallback") → 继续 pipeline
```
- 同一 run 内同一 agent 连续 3 次 fallback → 该 agent 在本次 run 后续项目直接跳过 LLM（熔断）。
- LLM 不可用**绝不**中断主流程，最终评分始终可产出。

### 19.4 成本与速率控制
| 控制点 | 策略 |
| --- | --- |
| 预算 | `LLMConfig.daily_budget_usd`（默认 $1）；超预算当日停用 LLM |
| 采样 | 非 FARM 候选项目以 30% 概率调用 LLM（省成本） |
| 缓存 | 相同 `(agent, prompt_hash)` 结果缓存 6h |
| 重试 | 不重试（LLM 调用昂贵，失败即回退） |
| 监控 | `llm_calls_total`、`llm_cost_usd_total`、`llm_fallback_total`（见 §20） |

### 19.5 可解释性
- LLM 修正后的结果与规则原值都写入 `logs.output`，可对比偏差。
- Dashboard 在 LLM 增强生效时显示小标记 "AI-enhanced"，点击可看 `evidence`。
- 权重校准（§7.9）需区分"规则 vs LLM"样本，避免混淆评估。

### 19.6 LLM 评估机制（V2+）

> 评估 LLM 增强是否真正提升评分质量，避免"为了用 LLM 而用 LLM"。

#### 19.6.1 评估维度

| 维度 | 指标 | 计算方式 |
|---|---|---|
| 准确率 | LLM 修正后 label 与用户反馈一致率 | `correct_labels / total_feedback` |
| 一致性 | 规则 vs LLM 输出差异度 | `mean(abs(llm_score - rule_score))` |
| 成本效率 | 每美元 LLM 调用带来的 label 提升 | `(llm_accuracy - rule_accuracy) / llm_cost_usd` |
| 覆盖率 | LLM 成功调用占比 | `llm_success / llm_attempts` |

#### 19.6.2 评估流程

```
1. 采集样本：feedback 表记录用户事后标注（outcome）
2. 触发条件：样本 ≥100（统计显著性）
3. 离线回测：
   a. 用历史数据分别跑"纯规则"和"规则+LLM"两遍
   b. 对比两组 label 与用户反馈的一致率
   c. 计算 LLM 带来的边际提升
4. 决策：
   - 提升 ≥5% → 保留 LLM 增强
   - 提升 <5% 或负提升 → 停用该 agent 的 LLM 增强
5. 版本化：每次评估记 `llm_eval_changelog`
```

#### 19.6.3 A/B 测试框架

```python
# config.py
class LLMConfig:
    enabled: bool = True
    ab_test_ratio: float = 0.5  # 50% 项目走 LLM，50% 走纯规则
    # 通过 project_id hash 分流，保证同一项目始终走同一分支

# 使用（用稳定哈希，避免 PYTHONHASHSEED 导致分流不稳定）
import hashlib
def should_use_llm(project_id: str) -> bool:
    if not LLMConfig.enabled:
        return False
    bucket = int(hashlib.md5(project_id.encode()).hexdigest(), 16) % 100
    return bucket < int(LLMConfig.ab_test_ratio * 100)
```

#### 19.6.4 评估面板（Grafana）

| 面板 | PromQL |
|---|---|
| LLM vs 规则准确率对比 | `airdrop_llm_accuracy / airdrop_rule_accuracy` |
| LLM 成本趋势 | `increase(airdrop_llm_cost_usd_total[1d])` |
| LLM 覆盖率 | `airdrop_llm_success_total / airdrop_llm_attempts_total` |
| 用户反馈一致率 | `airdrop_feedback_correct_labels / airdrop_feedback_total` |

#### 19.6.5 评估周期

- **每周**：自动跑一次离线回测（cron 周日 02:00）
- **每月**：人工审核评估报告，决定是否调整 LLM 策略
- **触发式**：用户 useless 反馈率 >30% 时立即评估

---

## 20. 可观测性设计

### 20.1 三支柱
| 支柱 | MVP | V2 | V3 |
| --- | --- | --- | --- |
| 日志 | structlog JSON → stdout | + Loki/Promtail 集中 | + 链路关联 |
| 指标 | 简易 `/metrics`（Prometheus 文本） | + Grafana 面板 | + 异常检测 |
| 追踪 | `run_id` 日志贯穿 | OpenTelemetry trace | + 分布式追踪 |

### 20.2 指标目录（Prometheus）
| 指标 | 类型 | 标签 | 含义 |
| --- | --- | --- | --- |
| `run_total` | counter | `source, status` | pipeline 触发次数 |
| `run_duration_seconds` | histogram | `source` | 端到端耗时分布 |
| `projects_analyzed_total` | counter | — | 累计分析项目数 |
| `agent_duration_seconds` | histogram | `agent, status` | 单 agent 耗时 |
| `agent_errors_total` | counter | `agent, kind` | agent 失败（含 llm_fallback） |
| `fetcher_duration_seconds` | histogram | `source` | 外部源拉取耗时 |
| `fetcher_errors_total` | counter | `source, code` | 拉取失败 |
| `fetcher_circuit_open` | gauge | `source` | 熔断状态（0/1） |
| `llm_calls_total` | counter | `agent, model` | LLM 调用 |
| `llm_cost_usd_total` | counter | `model` | LLM 累计成本 |
| `llm_fallback_total` | counter | `agent` | LLM 回退次数 |
| `db_write_errors_total` | counter | — | DB 写失败 |
| `projects_in_db` | gauge | `label` | 库内项目计数 |

### 20.3 链路追踪
- 每次 `POST /run` 生成 `run_id`（UUID），贯穿 Collector→各 Agent→Scorer→写库日志。
- V2 引入 OpenTelemetry：每个 agent 是一个 span，`run_id` 作为 trace 上下文。
- `GET /project/{id}` 可反向查 `logs` 表该项目的全部 agent 执行记录（已有 `project_id` 索引）。

### 20.4 告警规则（V2+）
| 规则 | 条件 | 严重度 |
| --- | --- | --- |
| pipeline 连续失败 | `increase(run_total{status="error"}[15m]) >= 2` | critical |
| DB 写入异常 | `increase(db_write_errors_total[5m]) > 0` | critical |
| 健康检查失败 | `/health` 连续 3 次失败 | critical |
| 外部源熔断 | `fetcher_circuit_open == 1` 持续 5min | warning |
| LLM 成本超预算 | `llm_cost_usd_total > daily_budget_usd` | warning |
| 分析耗时退化 | `histogram_quantile(0.95, run_duration_seconds) > 30` | warning |

### 20.5 Dashboard（Grafana，V2）
- 面板：每日 run 成功率、Top 项目数、P95 耗时、各 agent 耗时分布、外部源健康、LLM 成本曲线。
- 与前端 Dashboard 区分：运维面板给开发者，前端给最终用户。

---

## 21. 安全与合规细则

### 21.1 威胁模型（STRIDE 简化）
| 威胁 | 场景 | 缓解 |
| --- | --- | --- |
| Spoofing | 伪造 API 调用触发 /run | V2 Bearer 鉴权；MVP 仅本地/内网 |
| Tampering | 篡改评分结果 | DB 文件权限 + logs 留痕审计；re-score 留旧值版本 |
| Repudiation | 否认触发过 run | logs 表记录 `run_id`/触发源/时间 |
| Info Disclosure | 密钥泄漏 | 仅环境变量注入，禁入镜像/仓库 |
| DoS | 大量 /run 打爆 LLM/外部源 | 速率限制（§API 12）+ LLM 预算 + 缓存 |
| Elevation | 未授权改权重 | 配置仅代码+env，无运行时改权重接口（MVP） |

### 21.2 密钥管理
- 所有 key（`OPENAI_API_KEY`/`CRYPTORANK_API_KEY`/`TWITTER_BEARER`/`DUNE_API_KEY`/`API_KEY`）仅经环境变量注入。
- `.env` 在 `.gitignore`；`.env.example` 仅占位符。
- 镜像构建时不 baked 任何密钥；运行时 `docker run -e` 或 compose `env_file`。
- V2+ 推荐用容器 secret（docker secret / k8s secret）而非明文 env。

### 21.3 依赖安全
- `requirements.txt` 锁版本；CI 跑 `pip-audit`（或 `safety check`）扫描已知 CVE。
- 定期（月度）`pip-audit` + 升级；高危 24h 内修。
- 前端 CDN 资源加 SRI（Subresource Integrity）hash。

### 21.4 数据隐私与合规
- **仅聚合公开数据**：DefiLlama/CryptoRank/Twitter 公开推文/Dune 公开查询；不抓取需授权的私有数据。
- **不存储 PII**：不收集用户身份信息；Twitter 仅取公开聚合指标（讨论量/提及数），不存推文原文与作者。
- **不触碰用户资金**：系统不持有私钥、不执行链上交易（v1/v2）；V3 仅输出 checklist 建议。
- **地理合规**：默认不针对受限地区提供服务；如商用需评估当地证券/金融监管（输出非投资建议声明）。
- **数据保留**：`logs` 表保留 90 天后归档/清理（V2）；`projects` 永久保留供回测。

### 21.5 输入校验
- 所有 API 入参经 Pydantic 校验（422 自动）。
- `source` 枚举白名单；`limit` 上限 500；`id` 格式校验。
- 外部数据进库前做基本 schema 校验，脏数据记 `AgentError` 跳过而非崩溃。

---

## 22. 数据治理与质量框架

> 完整规范见 [DATA_QUALITY.md](DATA_QUALITY.md)。本节为摘要。

### 22.1 数据质量维度
| 维度 | 衡量 | 目标 |
| --- | --- | --- |
| 完整性 | 必填字段非空率 | projects 核心字段 100% |
| 准确性 | 与权威源对比偏差 | DefiLlama 协议名匹配 ≥95% |
| 时效性 | 数据 age 分布 | P50 < TTL，P95 < 2×TTL |
| 一致性 | 同项目跨源字段一致 | dedup 后冲突率 <5% |
| 唯一性 | dedup_key 重复 | 0（DB 唯一约束） |

### 22.2 来源可靠性与分级
给每个数据源一个 `reliability` 分（0–1），用于冲突仲裁与降级权重：
| 源 | reliability | 理由 |
| --- | --- | --- |
| seed | 1.0 | 人工 curated |
| DefiLlama | 0.9 | 公认协议库 |
| CryptoRank | 0.75 | 商业库，偶有延迟 |
| Twitter | 0.5 | 噪音大，仅作信号 |
| Dune | 0.8 | 链上可信，但查询质量依赖作者 |

- 多源同字段冲突时，取 `reliability` 最高源；同源取最新。
- `reliability` 写入 `raw_signals.sources[]`，供审计。

### 22.3 数据校验管道
```
fetch → schema validate → 业务校验 → 去重 → 入库
        ↓失败              ↓异常
        跳过+记 error      隔离到 quarantine 表（V2）
```
- MVP：校验失败记日志跳过；V2 引入 `quarantine` 表暂存脏数据供人工排查。

### 22.4 数据血缘
- 每个 `projects` 行可经 `logs` 表回溯：哪个 run、哪些 agent、哪些源数据、什么版本权重产出。
- `source` 字段 + `raw_signals.sources[]` + `logs.input` 构成完整血缘。
- V2 在 Dashboard 增加"数据来源"面板展示血缘。

### 22.5 数据质量监控
- 每日 run 后计算完整性/时效性指标，写入 `metrics`（见 §20）。
- 完整性 <80% 或时效性 P95 > 3×TTL → 告警。

---

## 23. 容量与性能规划

### 23.1 规模估算
| 指标 | MVP | V2 | V3 |
| --- | --- | --- | --- |
| 日新增项目 | 20–50 | 100–300 | 500+ |
| 库内累计项目 | <1k | <50k | >500k |
| 单次 run 项目数 | ≤50 | ≤300 | 队列分批 |
| 并发用户 | 1–5 | 10–50 | 100+ |

### 23.2 性能预算（单项目端到端）
| 阶段 | 预算 | 说明 |
| --- | --- | --- |
| Collector | 50ms | 种子/缓存命中 |
| 4 Agent 并行 | 800ms | 规则引擎；含 LLM 时 3–8s |
| Scorer | 20ms | 纯计算 |
| 写库 | 30ms | SQLite WAL |
| **合计（规则）** | **<1s** | 目标 <3s |
| **合计（含 LLM）** | **<15s** | 含超时回退 |

### 23.3 单次 run 性能预算
- 50 项目 × 1s = 50s（规则）→ 可接受（每日 cron）。
- 超过 100 项目需分批并发（V2 用 `asyncio.Semaphore` 限并发 10）。
- `/run` 同步执行上限 60s；超 60s 切后台 task（V2）。

### 23.4 存储
- 单项目记录 ~2KB（含 JSON 列）；50k 项目 ≈ 100MB。
- logs 表每 run 每项目 5 条 × 50 项目 × 365 天 ≈ 91k 行/年 ≈ 50MB → 90 天清理足够。
- SQLite 单文件 >1GB 时建议切 PG（V2 触发条件之一）。

### 23.5 扩展性预案
- **读扩展**：`GET /projects` 加 Redis 缓存（V2），TTL 60s。
- **写扩展**：多 writer 靠 PG 行锁（V2）；MVP 单 writer。
- **计算扩展**：V3 用 Celery/RQ 把单项目 pipeline 作为 task，水平扩 worker。

---

## 24. 用户反馈回流与 Memory 系统（V3 前瞻设计）

> 本节是 V3 的前向设计，MVP/V2 不实现，但数据采集需提前在 V2 落地，避免 V3 冷启动无数据。

### 24.1 反馈采集（V2 起埋点）
| 反馈类型 | 采集方式 | 存储 |
| --- | --- | --- |
| 隐式 | Dashboard 点击/停留/展开 reason | `events` 表（V2 新增） |
| 显式 | 项目卡「有用/无用」按钮、纠错提交 | `feedback` 表 |
| 事后标注 | 用户事后回填该项目是否真空投/真涨 | `feedback` 表 + `outcome` 字段 |

`feedback` 表（V2）：
```sql
CREATE TABLE feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT,
    user_id TEXT,                -- V2 匿名 token；V3 接登录
    signal TEXT,                 -- useful|useless|wrong_label|correct_outcome
    note TEXT,
    outcome TEXT,                -- airdropped|not_airdropped|pumped|dumped|null
    created_at TIMESTAMP
);
```

### 24.2 反馈 → 权重校准闭环
```
feedback(outcome) → 标注样本池 → backtest.py 回测 → 候选权重 → 灰度 → 切默认
```
- 见 §7.9 校准流程；反馈样本 ≥200 才触发首次校准（统计显著性）。
- 误报（label=FARM 但 outcome=not_airdropped）权重 2× 惩罚。

### 24.3 Memory 系统（V3）
- **作用**：跨 run 记忆项目演化（stage 变化、score 历史、用户偏好），支持"项目画像"而非单点评分。
- **设计**：
  - `project_history` 物化视图：每项目历史 score 序列、stage 迁移、label 变化。
  - `user_profile`：用户偏好赛道/风险偏好（从反馈推断），用于个性化排序。
  - LLM agent 可读取 memory 作为上下文（"该项目 3 个月前 stage=testnet，现 mainnet"）。
- **冷启动**：V2 采集期无 memory，规则引擎兜底；V3 上线时已有 3–6 个月数据。
- **隐私**：user_profile 仅存偏好向量，不存身份；可一键清除。

### 24.4 持续学习护栏
- 权重变更需 ADR + 灰度（§7.9），禁止全自动切默认。
- 反馈样本偏差（如只收 FARM 反馈）需重采样平衡，避免模型偏向。
- 每次权重切换记 `weight_changelog`（旧值/新值/触发样本数/指标对比）。

---

## 25. 用户系统与多租户设计（User System & Multi-Tenancy）

> 本节定义系统的用户模型、认证方式、角色权限、多租户数据隔离与用户偏好存储。对应 ADR：[ADR-008](adr/ADR-008-user-system.md)。
>
> 适用阶段：MVP（单用户无鉴权）→ V2（API Key + 匿名 token）→ V3（多用户 JWT + RBAC + 数据隔离）。

### 25.1 设计原则

1. **增量演进**：MVPC（单用户无鉴权）→ V2（API Key 鉴权 + 匿名 token）→ V3（全功能多用户 + RBAC），每一步向后兼容。
2. **数据最小化**：仅收集系统运作所需的用户信息，不存 PII（MVP/V2 完全不收集）。
3. **默认可关机**：未配置认证时降级到本地模式，不阻塞开发/演示。
4. **可审计**：所有用户操作关联 `user_id`，支持追溯。
5. **GDPR 就绪**：用户可导出、可删除自己的数据。

### 25.2 用户角色定义

| 角色 | 标识 | 权限 | 阶段 |
| --- | --- | --- | --- |
| **admin** | `role=admin` | 全部权限：触发 run、改配置、管理 API Key、管理用户 | V3 |
| **analyst** | `role=analyst` | 查看项目、提交反馈、事后标注、re-score | V3 |
| **viewer** | `role=viewer` | 只读 Dashboard，不可触发 run、不可提交反馈 | V3 |
| **anonymous** | `user_id=null`（MVP）/ 匿名 token（V2） | 查看 Dashboard（MVP）、提交反馈（V2） | MVP/V2 |

> MVP：单用户，等价于 admin 权限，**无鉴权**。
> V2：支持匿名 token + 管理员 API Key，两个角色。
> V3：完整 RBAC 三角色，OAuth2/JWT。

### 25.3 认证方式演进

| 阶段 | 方式 | 适用场景 | 安全等级 |
| --- | --- | --- | --- |
| MVP | 无认证（本地绑定 `127.0.0.1`） | 本地开发、单用户演示 | 最低（可接受） |
| V2 | API_KEY（Bearer Token）+ 匿名 token | 生产单用户、小团队部署 | 中 |
| V3 | JWT（OAuth2）+ API Key（可撤销） | 多用户 SaaS、企业部署 | 高 |

#### 25.3.1 MVP（当前）
- 无用户概念，无鉴权。
- `uvicorn` 仅绑定 `127.0.0.1`。
- 所有数据全局可见。
- `logs` 表的 `user_id` 字段留 NULL。

#### 25.3.2 V2（新增设计）

**管理员认证**：
- 保留现有的 `API_KEY` Bearer 鉴权（§8.6）。
- 中间件校验：所有 API（除 `/health`、`/metrics`、`/docs` 白名单）需 Bearer Token。
- Admin 端点的 run/re-score/audit 操作记录 `user="admin"`。

**匿名用户认证**：
- 前端首次访问 Dashboard 时，后端 `POST /api/v1/auth/anonymous` 返回一个匿名 token。
- 匿名 token：JWT 格式，payload 含 `{sub: "anon_<uuid>", role: "anonymous", exp}`。
- Token 存储在 localStorage，有效期 30 天，过期后自动刷新。
- 匿名用户可调用：`GET /projects`、`GET /project/{id}`、`GET /insights`、`POST /feedback`、`POST /events`。
- 匿名 user_id 写入 `feedback`/`events` 表的 `user_id` 字段。
- 每次请求通过 `Authorization: Bearer <anon_token>` 传递。

```
# 匿名 token 获取（V2）
POST /api/v1/auth/anonymous
→ { "ok": true, "data": { "token": "eyJ...", "user_id": "anon_uuid", "expires_at": "2026-08-07T08:00:00Z" } }
```

#### 25.3.3 V3（前瞻设计）

**注册与登录**：
- `POST /api/v1/auth/register`：email + password → 创建用户 + 返回 JWT。
- `POST /api/v1/auth/login`：email + password → 验证 + 返回 JWT。
- `POST /api/v1/auth/refresh`：refresh token → 返回新 JWT。
- `POST /api/v1/auth/logout`：吊销 refresh token。

**密码安全**：
- 密码使用 **bcrypt** 哈希（cost factor 12）。
- 密码最低复杂度：≥8 字符，含大小写字母 + 数字。
- 密码轮换提醒：每 90 天（可配置）。

**JWT 设计**：

| 字段 | 说明 |
| --- | --- |
| `sub` | 用户 UUID |
| `role` | admin / analyst / viewer |
| `iat` | 签发时间 |
| `exp` | 过期时间（access token 15min, refresh token 7 天） |
| `jti` | JWT ID（用于吊销检测） |

- Access token 有效期 15 分钟，refresh token 7 天。
- 后端维护一个 JWT 吊销列表（`blacklisted_jti`），用于 logout 或权限变更时立即使 token 失效。
- Docker 部署时通过 `JWT_SECRET` 环境变量注入密钥（≥256 位随机）。

**可撤销 API Key（V3 增强）**：
- 管理员可通过 UI/API 生成、列出、撤销 API Key。
- 每个 key 关联一个 `user_id` 和 `role`。
- 撤销后该 key 立即失效，不影响用户的其他 session。

```sql
-- API Key 表（V3）
CREATE TABLE api_keys (
    id          TEXT PRIMARY KEY,          -- key_<uuid>
    user_id     TEXT NOT NULL,
    name        TEXT NOT NULL,             -- 用户可读的 Key 名称，如 "CI Pipeline"
    key_hash    TEXT NOT NULL UNIQUE,      -- bcrypt hash of the raw key
    role        TEXT NOT NULL,             -- admin/analyst/viewer
    last_used_at TIMESTAMP,
    expires_at  TIMESTAMP,
    is_revoked  INTEGER DEFAULT 0,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_api_keys_user ON api_keys(user_id);
```

### 25.4 数据模型（V3 新增表）

#### 25.4.1 `users` 表

```sql
CREATE TABLE users (
    id              TEXT PRIMARY KEY,      -- UUID
    email           TEXT UNIQUE NOT NULL,
    password_hash   TEXT NOT NULL,         -- bcrypt hash
    display_name    TEXT,
    role            TEXT NOT NULL DEFAULT 'viewer',  -- admin|analyst|viewer
    is_active       INTEGER DEFAULT 1,
    preferences     TEXT,                  -- JSON: 偏好设置（见 §25.6）
    last_login_at   TIMESTAMP,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_users_email ON users(email);
CREATE INDEX idx_users_role  ON users(role);
```

#### 25.4.2 `sessions` 表（V3，refresh token 持久化）

```sql
CREATE TABLE sessions (
    id              TEXT PRIMARY KEY,      -- UUID
    user_id         TEXT NOT NULL,
    refresh_token_hash TEXT NOT NULL UNIQUE,
    ip              TEXT,
    user_agent      TEXT,
    expires_at      TIMESTAMP NOT NULL,
    revoked         INTEGER DEFAULT 0,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX idx_sessions_user ON sessions(user_id);
CREATE INDEX idx_sessions_expires ON sessions(expires_at);
```

#### 25.4.3 `blacklisted_jti` 表（V3，JWT 吊销）

```sql
CREATE TABLE blacklisted_jti (
    jti             TEXT PRIMARY KEY,
    expires_at      TIMESTAMP NOT NULL,   -- 与 token 的 exp 一致，到期可清理
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_blacklisted_expires ON blacklisted_jti(expires_at);
```

#### 25.4.4 现有表修改（V3）

现有 `feedback`、`events`、`audit_logs` 表的 `user_id` 字段从 TEXT（匿名 token）**不变**，V3 新增外键约束指向 `users(id)`（可为 NULL 保持匿名向下兼容）。

### 25.5 多租户数据隔离（V3）

> 本系统的核心数据（projects、logs、项目评分）是所有用户的公共数据——项目发现和评分不因用户不同而变化。多租户隔离仅适用于**用户私有数据**。

#### 25.5.1 隔离范围

| 数据 | 隔离策略 | 理由 |
| --- | --- | --- |
| `projects` | **全局共享** | 项目数据对所有用户一致 |
| `logs` | **全局共享** | 审计追踪与调试数据 |
| `feedback` | **行级隔离**（`user_id` 过滤） | 用户只能看到自己的反馈 |
| `events` | **行级隔离**（`user_id` 过滤） | 用户只能看到自己的行为记录 |
| `project_history` | **全局共享** | 项目演化历史对所有用户一致 |
| `api_keys` | **行级隔离**（`user_id` 过滤） | 用户只能管理自己的 API Key |
| `sessions` | **行级隔离**（`user_id` 过滤） | 用户只能看到自己的 session |
| `user_profile` | **用户级别** | 仅自己可见 |

#### 25.5.2 隔离实现

- **后端拦截**：所有涉及用户私有数据的查询自动附加 `WHERE user_id = ?`。
- **中间件注入**：`AuthMiddleware` 解析 JWT/API Key 后将 `user_id` 注入 request state，业务代码直接取用。
- **禁止绕过**：`GET /api/v1/feedback?project_id=xxx` 只能看到自己提交的反馈。
- **admin 特权**：admin 角色可查看所有用户的反馈（用于数据校准）。

```python
# 行级隔离示例（后端拦截）
@app.get("/api/v1/feedback")
async def list_feedback(request: Request):
    user = request.state.user
    query = "SELECT * FROM feedback"
    params = []
    
    if user.role != "admin":
        query += " WHERE user_id = ?"
        params.append(user.user_id)
    
    if request.query_params.get("project_id"):
        query += " AND project_id = ?" if "WHERE" in query else " WHERE project_id = ?"
        params.append(request.query_params["project_id"])
    
    return db.execute(query, params)
```

#### 25.5.3 个性化排序（US-016）

基于用户偏好对项目排序，不改变项目数据本身：

```python
# 用户偏好加权排序（在默认 score 排序基础上）
def personalize_sort(projects: list, user_profile: UserProfile) -> list:
    """基于用户偏好对项目排序，不影响 projects 表"""
    weight = {
        sector: user_profile.sector_preferences.get(sector, 1.0)
        for sector in set(p.sector for p in projects)
    }
    return sorted(projects, key=lambda p: (
        p.score * weight.get(p.sector, 1.0),
        p.confidence,
        p.name
    ), reverse=True)
```

- 个性化仅在 `GET /projects` 响应时前端或后端应用加权，**不改变 DB 中的 score**。
- 用户可关闭个性化恢复默认排序。
- V3 实现，MVP/V2 仅默认排序。

### 25.6 用户偏好存储

用户偏好以 JSON 存入 `users.preferences` 字段，简化 schema 演进：

```json
{
  "sector_preferences": {
    "L2": 1.2,        // 偏好权重，>1 = 偏好，<1 = 不偏好
    "Restaking": 0.8,
    "GameFi": 0.5
  },
  "risk_tolerance": 0.7,           // 0-1，0=保守，1=激进
  "preferred_stage": ["testnet"],  // 偏好阶段
  "notifications": {
    "telegram": "username_or_chatid",
    "new_farm_alert": true,
    "daily_digest": true
  },
  "language": "zh",               // 中/英
  "theme": "dark"                 // light/dark
}
```

API 端点（V3）：
- `GET /api/v1/user/preferences`：获取当前用户偏好
- `PUT /api/v1/user/preferences`：更新偏好（全量替换）
- `PATCH /api/v1/user/preferences`：更新偏好（增量合并）

### 25.7 API 鉴权中间件演进

```
# Middleware 策略对比

MVP: 无中间件 → 直接处理请求

V2: AuthMiddleware(API_KEY | anon_token)
  ├── /health, /metrics, /docs → 跳过
  ├── 请求头有 Authorization → 校验 API Key 或匿名 token
  │   ├── 合法 → request.state.user = {user_id, role}
  │   └── 非法 → 401
  └── 无 Authorization → 401（除白名单端点）

V3: AuthMiddleware(JWT | API_KEY | anon_token)  # 统一入口，三种方式兼容
  ├── 同 V2 白名单
  ├── JWT → 校验签名 + exp + jti blacklist
  ├── API Key → 校验 key_hash + is_revoked
  ├── 匿名 token → 同 V2
  └── 合法 → request.state.user = {user_id, role, auth_method}
```

### 25.8 速率限制与用户关联（V3）

| 限制维度 | MVP | V2 | V3 |
| --- | --- | --- | --- |
| 全局 | 不限制 | 60 req/min/IP | 120 req/min/IP |
| 按用户 | — | — | 200 req/min/user（登录用户），60 req/min/IP（匿名） |
| `/run` 限制 | 不限制 | 1 req/5min/IP | 1 req/5min/user |
| `/re-score` 限制 | 不限制 | 10 req/min/IP | 30 req/min/user |

- V3 速率限制中间件基于 `request.state.user.user_id`（登录用户）或 IP（匿名）。
- 超过限制返回 `429`，`Retry-After` 头指示等待秒数。
- 管理员不限制。

### 25.9 GDPR 合规与数据治理

| 功能 | API | 实现 | 阶段 |
| --- | --- | --- | --- |
| 数据导出 | `GET /api/v1/user/data` | 导出用户所有数据（反馈、events、preferences）为 JSON | V3 |
| 账户删除 | `DELETE /api/v1/user/account` | 删除用户及关联数据（反馈去标识化保留，events 删除） | V3 |
| 偏好清除 | `DELETE /api/v1/user/preferences` | 清除偏好设置 | V3 |
| Token 吊销 | `POST /api/v1/auth/logout` | 吊销当前 refresh token | V3 |
| 全设备登出 | `POST /api/v1/auth/logout/all` | 吊销用户所有 session | V3 |

**数据保留调整**（更新 §21.4）：

| 数据 | 原有保留期 | V3 调整 |
| --- | --- | --- |
| `feedback` | 永久 | 永久（用户删除时去标识化，`user_id` 置 NULL） |
| `events` | 180 天 | 180 天（用户删除时直接清理） |
| `sessions` | — | 过期后自动清理（cron 每日清理过期 session） |
| `blacklisted_jti` | — | JWT 过期后自动清理（cron 每日清理） |
| `api_keys` | — | 永久（撤销后保留审计追溯） |

### 25.10 新端点总览

| 方法 | 路径 | 阶段 | 鉴权 | 说明 |
| --- | --- | --- | --- | --- |
| POST | `/api/v1/auth/anonymous` | V2 | 无 | 获取匿名 token |
| POST | `/api/v1/auth/register` | V3 | 无 | 用户注册 |
| POST | `/api/v1/auth/login` | V3 | 无 | 用户登录（返回 JWT + refresh token） |
| POST | `/api/v1/auth/refresh` | V3 | Refresh Token | 刷新 access token |
| POST | `/api/v1/auth/logout` | V3 | JWT | 登出（吊销 refresh token） |
| POST | `/api/v1/auth/logout/all` | V3 | JWT | 全设备登出 |
| GET | `/api/v1/user/preferences` | V3 | JWT/API Key | 获取偏好 |
| PUT | `/api/v1/user/preferences` | V3 | JWT/API Key | 更新偏好（全量） |
| PATCH | `/api/v1/user/preferences` | V3 | JWT/API Key | 更新偏好（增量） |
| GET | `/api/v1/user/data` | V3 | JWT | 导出用户数据 |
| DELETE | `/api/v1/user/account` | V3 | JWT | 删除账户 |
| GET | `/api/v1/api-keys` | V3 | JWT | 列出用户的 API Key |
| POST | `/api/v1/api-keys` | V3 | JWT | 创建 API Key |
| DELETE | `/api/v1/api-keys/{id}` | V3 | JWT | 撤销 API Key |

### 25.11 与相关设计的集成点

| 相关设计 | 集成方式 |
| --- | --- |
| **feedback 表**（§5.4.1） | `user_id` 字段：MVP→NULL，V2→匿名 token，V3→users.id 外键（可为 NULL） |
| **events 表**（§5.4.2） | 同上 |
| **audit_logs 表**（§5.4.7） | `user` 字段：V2→`admin`/`anon_xxx`，V3→users.id 或 email |
| **SECURITY.md** §4 | 本设计是 SECURITY.md §4.3（V3 RBAC）的完整落地 |
| **SECURITY.md** §7.2 | 本设计 §25.9 实现 GDPR 删除权 |
| **USER_STORIES US-015** | audit_logs 表关联用户身份 |
| **USER_STORIES US-016** | 个性化排序通过 user_preferences 实现 |
| **FRONTEND_SPEC §11** | i18n 语言偏好存储在 user_preferences |
| **TASK_BREAKDOWN W11/W12** | W11 反馈闭环接入用户身份；W12 Memory 系统关联用户偏好 |

### 25.12 开放问题与风险

| # | 问题 | 影响 | 决策时机 |
| --- | --- | --- | --- |
| 1 | 匿名 token 是否需要绑定 IP？（防 token 被盗用） | 安全性 vs 用户体验 | V2 实施时 |
| 2 | V3 是否需要短信/2FA？ | 安全性 | V3 设计时评估 |
| 3 | 多租户是否需要独立数据库（每个租户一个 DB）？当前设计是行级隔离，但大型 SaaS 可能需要库级隔离 | 数据隔离强度 vs 运维成本 | V3 设计时评估 |
| 4 | 是否需要 OAuth2 第三方登录（Google/GitHub）？ | 用户体验 | V3 设计时评估 |
| 5 | `user_preferences` 字段用 JSON 还是独立列？ | JSON 方便演进但难查询 | 已决策用 JSON（§25.6） |

---

## 26. API 版本管理策略（API Version Management）

> 本节定义系统的 API 版本号策略、兼容性保证、弃用流程与 v1→v2 迁移路径。
>
> 对应 ADR：[ADR-009](adr/ADR-009-api-versioning.md)。

### 26.1 设计原则

1. **URL 前缀版本化**：版本编码在 URL 路径中（`/api/v1/`、`/api/v2/`），路径即契约。
2. **显式声明**：每个大版本明确定义 API 契约，版本变更必须 ADR 记录。
3. **向后兼容**：同一大版本内保持源兼容——字段仅增不减、响应仅扩不缩、参数仅加不改。
4. **可预测弃用**：每版本至少提供 90 天弃用窗口，期间新旧版本并行服务。
5. **无痛迁移**：v1→v2 迁移通过版本共存 + 迁移指南实现，用户选择时机切换。
6. **解耦内部版本**：API 版本号与评分权重版本（§7.9）、数据模型版本解耦。

### 26.2 API 版本生命周期

每个 API 大版本经历四个阶段：

```
Alpha（内部预览）→ Stable（正式发布）→ Deprecated（弃用期）→ Sunset（下架）
              ↓                      ↓                      ↓
    仅 dev 环境可用   文档标记"stable"     响应头含 Deprecation    返回 410 Gone
```

| 阶段 | 标识 | 可用性 | 文档标注 | 响应头 | 持续时间 |
| --- | --- | --- | --- | --- | --- |
| **Alpha** | `/api/v0/` | 仅 dev 环境 | "开发中，不稳定" | 无 | 不限（开发期内） |
| **Stable** | `/api/v1/` `/api/v2/` | 生产 | "当前稳定版" | 无 | 直到宣布弃用 |
| **Deprecated** | `/api/v1/` | 生产（并行） | "即将弃用，请迁移至 vN" | `Deprecation: version="v1"; sunset="..."` | 至少 90 天 |
| **Sunset** | `/api/v1/` | 关闭 | — | `410 Gone` + 文档链接 | 永久 |

> **例外**：MVP 阶段（当前 `/api/v1`）因无外部消费者，可直接升级到 V2 稳定版而无需弃用窗口。ADR-009 决定 MVP `/api/v1` 在 V2 发布时切换为 Deprecated 状态，30 天后 Sunset，以减少维护负担。

### 26.3 版本路径策略：URL Prefix

#### 选择理由

| 方式 | 示例 | 本系统选型 | 理由 |
| --- | --- | --- | --- |
| URL 前缀 | `/api/v1/projects` | **✅ 采用** | 显式、人类可读、缓存友好、无协商复杂度 |
| Accept 头 | `Accept: application/vnd.airdrop.v1+json` | ❌ 不采用 | 调试不便、浏览器/curl 默认不支持、中间件可能剥离 |
| Query 参数 | `/api/projects?version=1` | ❌ 不采用 | 缓存污染、URL 语义不清晰、SEO 不友好 |
| 子域名 | `v1.api.airdrop.com` | ❌ 不采用 | 运维成本高、SSL 证书管理复杂 |

#### 路由结构

```
/api/v1/run          # MVP/V2 稳定版
/api/v1/projects
/api/v1/project/{id}
/api/v1/re-score/{id}
/api/v1/insights
/api/v1/feedback       # V2 新增
/api/v1/events         # V2 新增
/api/v1/audit          # V2 新增
/api/v1/auth/*         # V2 新增（§25.10）

/api/v2/*              # 未来版本（预留）

/api/version           # 元端点：返回当前 API 版本信息
/health                # 无版本（基础设施 API）
/metrics               # 无版本（基础设施 API）
/docs                  # 无版本（自动文档，始终指向最新稳定版）
```

### 26.4 向后兼容性保证

同一大版本内（如整个 `/api/v1` 生命周期内）遵循：

| 维度 | 保证 | 反例（Breaking Change） |
| --- | --- | --- |
| **请求体** | 字段仅可添加（可选），不可删除必填字段 | 删除 `source` 必填字段 |
| **响应体** | 字段仅可添加，不可删除或改名已有字段 | `score` → `total_score` |
| **响应类型** | 字段类型不变 | `score` 从 int 变 string |
| **枚举值** | 仅可新增枚举值 | 删除 `defillama` 来源枚举 |
| **错误码** | 不改变已有错误语义 | 400→500 变更 |
| **端点路径** | 不改变 URL 结构 | `/project/{id}` → `/projects/{id}` |
| **默认行为** | 不改变无参数时的默认行为 | 默认排序从 score DESC 变 ASC |
| **速率限制** | 不降低现有限制配额 | 60 req/min → 30 req/min |

**例外审批**：因安全漏洞或数据完整性原因必须 breaking change 时，需 ADR 记录 + 至少 90 天弃用窗口 + 邮件/公告通知已知消费者。

### 26.5 弃用（Deprecation）与下架（Sunset）流程

#### 26.5.1 弃用触发条件

以下任一条件触发 API 大版本升级：

1. **Schema 突破兼容性**: 新功能需要修改响应结构且无法通过追加可选字段实现。
2. **安全加固**: 需要改变认证方式或加密协议。
3. **架构重构**: Agent/评分决策引擎重写导致响应语义变化。
4. **定期规划**: 按文档演进路线（§12）进入下一阶段。

#### 26.5.2 弃用流程（标准）

```
1. 发布新版 API（/api/v2）→ 旧版（/api/v1）进入 Deprecated
2. 旧版所有响应添加 HTTP 头：
   Deprecation: true
   Sunset: "2026-10-07T00:00:00Z"  (90 天后)
   Link: </api/v2>; rel="successor-version"
3. 文档标记旧版为 "即将弃用"，新版为 "推荐"
4. 文档发布《v1→v2 迁移指南》
5. 90 天后移除旧版路由 → 返回 410 Gone（含迁移链接）
6. 监控旧版调用量降为 0 后删除相关代码
```

> 监控指标：`api_version_calls_total{version="v1"}` 在 Sunset 前持续为 0 才可安全移除。

#### 26.5.3 弃用窗口（MVP 特殊处理）

| 场景 | 弃用窗口 | 理由 |
| --- | --- | --- |
| MVP→V2（标准） | 90 天 | 若已有外部消费者 |
| MVP→V2（无外部消费者） | 30 天 | MVP 阶段无外部用户，可缩短 |
| V2→V3 | 90 天 | 标准流程 |
| 安全紧急修复 | 0 天 | 立即 Sunset 旧版，新版当天上线 |

决策方式：V2 发布时应检查 `/api/v1` 日志，确认过去 30 天是否有非本地 IP 调用。如无，走 30 天快速弃用；如有，走 90 天标准弃用。

### 26.6 API 版本路由实现

#### 26.6.1 路由结构（FastAPI）

```
backend/app/
├── routers/
│   ├── v1/
│   │   ├── __init__.py       # APIRouter(prefix="/api/v1")
│   │   ├── run.py
│   │   ├── projects.py
│   │   ├── project.py
│   │   ├── rescores.py
│   │   ├── insights.py
│   │   └── ...               # V2 新增端点
│   └── v2/
│       └── ...               # V2 版本（待创建）
├── middleware/
│   ├── version_check.py       # 弃用检测中间件
│   └── sunset_handler.py      # 410 返回逻辑
└── main.py                    # include_router(v1.router)
```

```python
# main.py (MVP)
from app.routers import v1

app.include_router(v1.router)  # prefix="/api/v1"

# main.py (V2 双版本并行)
from app.routers import v1, v2

app.include_router(v1.router, deprecated=True)   # 自动添加 Deprecation 头
app.include_router(v2.router)                     # 最新稳定版
```

#### 26.6.2 弃用中间件

```python
# middleware/version_check.py
class APIVersionMiddleware:
    async def __call__(self, request, call_next):
        response = await call_next(request)
        
        # 如果是弃用版本，添加提示头
        if request.url.path.startswith("/api/v1"):
            response.headers["Deprecation"] = "true"
            response.headers["Sunset"] = "2026-10-07T00:00:00Z"
            response.headers["Link"] = '</api/v2>; rel="successor-version"'
        
        return response
```

#### 26.6.3 版本元端点

```
GET /api/version
→ {
    "current_version": "v1",
    "latest_version": "v2",
    "deprecated_versions": ["v1"],  # V2 发布后
    "sunset_versions": [],
    "stable_versions": ["v2"],
    "docs_url": "/docs"
}
```

### 26.7 v1→v2 迁移策略

> 本节仅在 V2 发版时启用，MVP 阶段仅做设计。

#### 26.7.1 触发 V2 的条件

以下任一条件满足时启动 V2 API 设计：
- §12 V2 里程碑完成（数据接入/Next.js Dashboard/PostgreSQL 迁移）
- 现有 `/api/v1` 需要 breaking change
- 外部集成者（Telegram bot、Webhook）需要 API 稳定契约

#### 26.7.2 双版本并行策略

| 阶段 | v1 状态 | v2 状态 | 时长 |
| --- | --- | --- | --- |
| **1. 发布 v2** | Stable | Alpha（可选）→ Stable | 发布当日 |
| **2. 并行运行** | Deprecated（Deprecation 头） | Stable | 90 天（标准）/ 30 天（MVP） |
| **3. v1 Sunset** | 410 Gone | Stable | 永久 |
| **4. v1 代码清理** | 移除 v1 路由 | Stable | Sunset 后 1 周 |

#### 26.7.3 典型 v1→v2 变化示例（假设）

| 变更项 | /api/v1 | /api/v2 | 说明 |
| --- | --- | --- | --- |
| 响应格式 | `{ "ok": true, "data": ... }` | 保持不变 | 兼容性好 |
| 分页 | `limit` 参数 | `page` + `per_page` + `total` | breaking |
| 筛选 | `?label=FARM` | `?filter[label]=FARM` | breaking |
| 鉴权 | `API_KEY` | JWT + `API_KEY` | 兼容（保留 `API_KEY` 但标记弃用） |
| 新增端点 | — | `POST /api/v2/subscribe` | 仅 v2 有 |

> **重要**：v2 并非全部端点都需 redesign。兼容部分（如响应包络）保持原样；需 breaking change 的部分（如分页、筛选语法）在 v2 统一改进。

#### 26.7.4 迁移指南要求

V2 发布时需同步撰写《v1→v2 API 迁移指南》，包含：

1. **变更摘要表**：每个端点的变化说明（无变化/参数变更/响应变更/新增）
2. **迁移示例**：常见操作的 v1 vs v2 curl 对比
3. **迁移检查清单**：
   - [ ] URL 前缀从 `/api/v1` 改为 `/api/v2`
   - [ ] 分页参数从 `limit` 改为 `page`/`per_page`
   - [ ] 筛选语法从 `?label=X` 改为 `?filter[label]=X`
   - [ ] 检查响应中是否有新字段需要处理
4. **回退说明**：v1 在弃用窗口内仍可用，消费者可在发现问题后切回 v1。

### 26.8 版本管理配置与监控

#### 26.8.1 版本配置

```python
# config.py
class APIVersionConfig:
    current_version: str = "v1"        # 当前默认版本
    latest_version: str = "v1"         # 最近稳定版本（V2 后与 current 不同）
    deprecated_versions: list[str] = []  # 已弃用但仍可用的版本
    sunset_versions: list[str] = []      # 已下架版本（仅用于监控）
    deprecation_window_days: int = 90    # 弃用窗口天数
    force_sunset_on_date: str | None = None  # 强制下架日期（格式："2026-10-07"）
```

#### 26.8.2 监控指标

| 指标 | 类型 | 标签 | 含义 |
| --- | --- | --- | --- |
| `api_version_calls_total` | counter | `version, endpoint, status` | 按版本和端点统计调用量 |
| `api_version_deprecated_calls_total` | counter | `version` | 已弃用版本的调用量（发现未迁移用户） |
| `api_sunset_blocked_requests_total` | counter | `version` | 返回 410 的请求数 |
| `api_version_migration_progress` | gauge | `from_version, to_version` | 迁移进度（v1 调用占比下降） |

#### 26.8.3 告警规则

| 规则 | 条件 | 严重度 |
| --- | --- | --- |
| 弃用版本仍有流量 | `increase(api_version_deprecated_calls_total[7d]) > 0` | warning（Sunset 前 30 天触发） |
| Sunset 后仍有请求 | `increase(api_sunset_blocked_requests_total[1d]) > 0` | info（通知消费者更新） |
| 新版本调用量为 0（发布 7 天后） | `increase(api_version_calls_total{version="v2"}[7d]) == 0` | warning（迁移未启动） |

### 26.9 内部版本与 API 版本解耦

系统存在多种"版本"，它们各自独立演进，不应混淆：

| 版本类型 | 表示方式 | 变更节奏 | 消费者 |
| --- | --- | --- | --- |
| **API 版本** | `/api/v1`、`/api/v2` | ~年级 | 外部 API 消费者 |
| **评分权重版本** | `weight_version` (projects 表) | 灰度→周级 | 内部 backtest + 评分决策引擎 |
| **数据模型版本** | SQL schema（Alembic 迁移） | 季度级 | 内部 DB 迁移 |
| **LLM Prompt 版本** | `prompt_version` (logs 表) | 迭代级 | 内部 agent |
| **应用版本** | Docker image tag (`v1.2.3`) | 发布级 | 运维 |

**关键约束**：
- 更新评分权重**不**需要新 API 版本（仅在 projects 表标记 `weight_version`）。
- 响应中新增字段（如 `weight_version`）**不**违反 v1 兼容性（§26.4 添加可选字段兼容）。
- 数据模型迁移**不**影响 API 响应（通过 DTO/View Object 隔离）。
- LLM Prompt 更新**不**影响 API 契约（prompt 结果只影响评分值而非响应结构）。

```
┌──────────────────────────────────────────┐
│  External Consumer                        │
│  sees: /api/v1/projects (stable contract)  │
└────────────┬─────────────────────────────┘
             │ HTTP
┌────────────▼─────────────────────────────┐
│  API Layer (FastAPI routers)               │
│  /api/v1/ → v1.router                      │
│  /api/v2/ → v2.router (future)             │
└────────────┬─────────────────────────────┘
             │
┌────────────▼─────────────────────────────┐
│  Service Layer (orchestrator, scorer)      │
│  Internal versions: weight_version,        │
│  prompt_version (invisible to API clients) │
└────────────┬─────────────────────────────┘
             │
┌────────────▼─────────────────────────────┐
│  Data Layer (SQLite → PG)                 │
│  Schema versions: Alembic migrations       │
└──────────────────────────────────────────┘
```

### 26.10 开放问题与风险

| # | 问题 | 影响 | 决策时机 |
| --- | --- | --- | --- |
| 1 | V2 是否需要改变响应包络（`{ok, data, error}`）？当前设计保留不变以降低迁移成本 | 兼容性 vs 改进空间 | V2 设计时（预计不变） |
| 2 | 是否需要在 API Gateway 层面做版本路由（Nginx/ Traefik 根据 URL 前缀分发到不同上游）？当前设计是应用层路由，但多实例场景可能需要网关层路由 | 灵活性 vs 复杂性 | V3 多实例部署时评估 |
| 3 | v1 代码维护成本：弃用期间是否继续修复 v1 的 bug？策略是仅修复 P0/P1 级别 bug，P2/P3 建议升级 v2 | 维护负担 vs 用户信任 | V2 发布时决定 |
| 4 | 是否需要 OpenAPI 多版本文档？FastAPI 默认只显示最新版本，可通过 `app.mount` 多实例或自定义 docs 路由实现 | 开发者体验 | V2 实施时评估 |

---

## 27. 与相关文档的集成

| 文档 | 集成方式 |
| --- | --- |
| **API_SPEC.md** | 应标注每个端点所属大版本（当前为 v1），并在 V2 发布时产生第二份 API_SPEC_v2.md 或标注变更 |
| **FRONTEND_SPEC.md** | 前端应通过环境变量 `NEXT_PUBLIC_API_VERSION` 配置 API 版本，V2 迁移时只需改变量值（若端点路径不变则不需要改） |
| **DEPLOYMENT.md** | V2 并行阶段需配置两个版本的部署（可选路径：同一容器双路由 vs 独立容器） |
| **TASK_BREAKDOWN.md** | 版本管理任务在 V2 阶段加入：弃用中间件、监控指标、迁移指南 |
| **SECURITY.md** | 版本管理对鉴权的影响：V2 新增 JWT 鉴权，v1 旧鉴权（API_KEY）在弃用窗口期间仍需保留 |

---

_文档版本：v1.11 · 基于《Web3 Airdrop Alpha Agent System（完整版工程方案）》拆解 · 规划阶段。v1.1 新增 ADR 决议、LLM/可观测性/安全合规/数据治理/容量性能/反馈 Memory 七章；v1.2 拆分 ADR 到独立目录、补 V2 表 DDL、调整排期、新增 OBSERVABILITY.md 与 SECURITY.md 专项规范；v1.3 新增 DATA_QUALITY.md / OPERATIONS.md / GLOSSARY.md 三份专项规范；v1.4 Roadmap 里程碑评审通过；v1.5 数据一致性核查修复；v1.6 新增 §6.9 多项目并发模型 + ADR-007；v1.7 修复 §6.9.12 事务边界 8 项遗漏 + API_SPEC.md 同步；v1.8 新增 §25 用户系统 + ADR-008；v1.9 新增 §26 API 版本管理策略 + ADR-009 + API_SPEC.md 标注；v1.10 新增 §7.5.1 竞争度缓存与增量计数策略 + ADR-010；**v1.11 第四轮跨文档一致性审查**：修复 GOLDEN_TEST_CASES.md reason_contains 与评分规则矛盾（#16）、API_SPEC.md 章节编号跳号（#17）、FRONTEND_SPEC.md 缺失 V2 设计特性（#18）、主设计文档 ADR 引用更新（#19）；升级主设计文档 v0.2、DESIGN_REVIEW_CHANGELOG.md v1.1。_
