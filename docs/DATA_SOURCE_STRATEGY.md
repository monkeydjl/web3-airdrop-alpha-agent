# Web3 Airdrop Alpha - 数据源策略（自动扫描视角�?
**文档版本**: v2.0
**创建日期**: 2026-07-09
**更新日期**: 2026-07-09
**状�?*: 战略规划（自动扫描全网定位）
**关联文档**: `SYSTEM_DIRECTION_CHANGE.md`、`ENGINEERING_ROADMAP.md §6.2`、`DATABASE_DDL.md`、`SECURITY.md §10`、`.env.example`

---

## 📋 执行摘要

本文档定�?Web3 Airdrop Alpha Agent System �?*数据源策略（v2.0 自动扫描方向�?*�?
> **核心结论**：系统主动从多数据源**自动扫描全网**，持续发现未空投的早�?Web3 项目�?> 采集调度器独立运行，将候选项目写�?`raw_projects` 表，再由分析调度器触发多 Agent 评分�?
外部数据源（DefiLlama / Twitter / GitHub / 链上等）�?*核心采集�?*（非"可选补�?）。手动输入（UI/CSV/API/seed）降级为**补充能力**，用于覆盖采集盲区�?
本文档定义各数据源的接入方式、API 方案、数据结构、采集频率、速率限制、成本预估，以及采集管道、双调度模型、采集表 schema�?
---

## 🎯 数据源优先级矩阵

| 数据�?| 优先�?| 接入方式 | 主要价�?| API 成本 | 实现难度 |
|--------|--------|----------|----------|----------|----------|
| **DefiLlama** | P0 | 自动采集（全量协议扫描） | 未发币状态、TVL、链、类�?| 免费 | �?|
| **GitHub** | P0 | 自动采集（活跃度扫描�?| 技术活跃度、仓库信�?| 免费 | �?|
| **CoinGecko** | P0 | 自动采集（代币状态验证） | 市值、代币状态、上所 | 免费/付费 | �?|
| **Twitter/X** | P0 | 自动采集（VC/KOL + 关键词） | 早期信号、融资、测试网、积�?| $100/�?| �?|
| **链上数据** | P1 | 自动采集（新合约监控 + 地址活跃度） | 真实活跃度、新部署 | 免费/付费 | �?|
| **Galxe/Layer3** | P1 | 自动采集（任务平台扫描） | 任务活动信号（空投前奏） | 免费 | �?|
| **CryptoRank** | P1 | 自动采集（项目聚合） | 融资、评�?| 免费/付费 | �?|
| **Discord** | P2 | 自动采集（社区活跃度�?| 社区活跃�?| 免费 | �?|
| **Medium/Mirror** | P2 | 自动采集（RSS�?| 路线图、公�?| 免费 | �?|
| **Reddit** | P2 | 自动采集（讨论爬取） | 社区情绪 | 免费 | �?|
| **手动录入** | P1 | UI 表单（补充） | 覆盖采集盲区 | 免费 | �?|
| **CSV 导入** | P1 | 批量粘贴（补充） | 批量补充 | 免费 | �?|
| **seed 策展** | P2 | `scripts/seed.py` | 演示/测试基线 | 免费 | �?|

> 优先级含义：**P0 = MVP/V1 必须接入的核心采集源**；P1 = V1+ 增强；P2 = V2 完善。手动输入为补充能力�?
---

## 🔴 P0：核心采集源（MVP/V1 必须�?
### **1. DefiLlama（自动采集，P0�?*

**价�?*：权�?DeFi 数据，发�?�?TVL 但未发币"的早期项目（空投黄金信号）�?
**采集策略**:
- A. 全量协议扫描：每日拉�?`/protocols` 列表，识�?`has_token=false` 的协�?- B. TVL 阈值过滤：TVL > $1M 的未发币协议进入候选池
- C. 趋势监控�? �?TVL 增长 > 20% 的协议标记为"热度上升"

**技术实�?*:
```python
# backend/app/collectors/defillama_collector.py（计划实现位置）
class DefiLlamaCollector:
    """
    使用 DefiLlama API (免费，无 Key)
    - /protocols (所有协议列表，每日全量)
    - /protocol/{name} (协议详情)
    - /charts (TVL 历史)
    """
    async def fetch_all_protocols(self) -> list[dict]
    async def filter_unfunded_protocols(self, protocols: list[dict]) -> list[dict]
    async def get_protocol_detail(self, name: str) -> dict
    async def get_tvl_trend(self, protocol: str) -> dict
```

**API 方案**: 完全免费，无 Key，高可用。速率限制：无硬性限制，建议 �?10 req/s�?
**采集频率**: 每日 1 次全量扫描（cron `0 8 * * *`）�?
**关键数据**:
```json
{
  "protocol": "name",
  "tvl": 0,
  "chain": ["Ethereum", "Arbitrum"],
  "category": "Lending",
  "has_token": false,
  "tvl_change_7d": 0.0,
  "listed_at": "timestamp",
  "github": "owner/repo"
}
```

---

### **2. GitHub（自动采集，P0�?*

**价�?*：技术活跃度是项目质量的硬指标，识别"在积极开发但未发�?的项目�?
**采集策略**:
- A. �?DefiLlama 采集结果中提�?`github` 字段，拉取仓库活跃度
- B. 关键词搜索：`airdrop testnet points` 等，发现新仓�?- C. 活跃度评分：commit 频率 + 贡献者数 + 最近更新时�?
**技术实�?*:
```python
# backend/app/collectors/github_collector.py（计划实现位置）
class GitHubCollector:
    """
    使用 GitHub REST API + GraphQL API
    - Repo API (获取活跃度指�?
    - Search API (按关键词发现新仓�?
    """
    async def get_repo_metrics(self, owner: str, repo: str) -> dict
    async def search_web3_repos(self, query: str, sort: str = "updated") -> list[dict]
    async def calculate_activity_score(self, repo_data: dict) -> float
```

**API 方案**: 免费额度 5,000 请求/小时（认证）；GraphQL 批量查询 + 缓存�?
**采集频率**: 每日 1 次（跟随 DefiLlama 扫描后触发）�?
**关键指标**:
```json
{
  "repo": "owner/name",
  "stars": 0,
  "forks": 0,
  "commits_last_30d": 0,
  "contributors": 0,
  "last_commit": "timestamp",
  "language": "Solidity",
  "activity_score": 0.0
}
```

---

### **3. CoinGecko（自动采集，P0�?*

**价�?*：验证代币状态，排除已发币项目（避免对已流通代币做空投评分）�?
**采集策略**:
- A. �?DefiLlama 候选项目，查询 CoinGecko 验证是否已发�?- B. 已发币项目标记为 `has_token=true`，从候选池移除
- C. 未发币项目保留，进入分析管道

**技术实�?*:
```python
# backend/app/collectors/coingecko_collector.py（计划实现位置）
class CoinGeckoCollector:
    async def check_token_exists(self, project_name: str) -> bool
    async def get_market_data(self, coin_id: str) -> dict
```

**API 方案**: 免费 30 �?分钟；付�?$129/月（500 �?分钟）。初期免费足够�?
**采集频率**: 每日 1 次（跟随 DefiLlama + GitHub 后触发）�?
---

### **4. Twitter/X（自动采集，P0�?*

**价�?*：VC 投资公告、测试网上线、积分计划等第一手信号，是发现早期项目的最快来源�?
**采集策略**:
- A. **VC 账号监听**：`@a16z, @paradigm, @VitalikButerin, @cz_binance, @BinanceLabs, @coinbase, @panteracapital, @dragonfly_xyz, @polychaincap, @1kxnetwork` 等融资信�?- B. **KOL 账号监听**：Web3 领域 top 100 KOL、空投猎人社�?KOL、赛道专�?- C. **关键词实时搜�?*：`#airdrop #testnet #points #mainnet "points program" "no token yet" "TGE soon"`
- D. **Filtered Stream**（实时流）：监听关键词流，实时捕获新项目信号

**技术实�?*:
```python
# backend/app/collectors/twitter_collector.py（计划实现位置）
class TwitterCollector:
    """
    使用 Twitter API v2
    - User Tweets API (查询特定账号历史)
    - Search API (按关键词搜索)
    - Filtered Stream (实时流监�?
    """
    async def search_recent(self, query: str, max_results: int = 100) -> list[dict]
    async def get_account_tweets(self, account_id: str) -> list[dict]
    async def start_filtered_stream(self, rules: list[str]) -> AsyncIterator[dict]
    async def extract_project_signals(self, tweets: list[dict]) -> list[dict]
```

**API 方案**:
- Basic Tier: $100/�?(10,000 tweets/月读�?
- Pro Tier: $5,000/�?(1M tweets/月，Filtered Stream)
- 速率限制: 智能过滤 + 优先级队�?
**采集频率**:
- VC/KOL 账号：每小时轮询 1 �?- 关键词搜索：�?15 分钟 1 �?- Filtered Stream：持续运行（需 Pro Tier�?
**数据提取**:
```json
{
  "project_name": "从推文提�?,
  "twitter_handle": "@project",
  "signal_type": "funding/testnet/points",
  "raw_text": "原始推文",
  "engagement": {"likes": 0, "retweets": 0},
  "source_account": "@vc_account",
  "captured_at": "timestamp"
}
```

---

## 🟡 P1：增强采集源（V1+�?
### **5. 链上数据（自动采集，P1�?*

**价�?*：最真实的活跃度数据，发�?链上活跃但未发币"的项目�?
**采集策略**:
- A. **新合约部署监�?*：通过 Alchemy/Infura webhook 监听主流链的新合约部�?- B. **地址活跃度补�?*：对已知项目地址，拉取交互数、独立用户数
- C. **TVL 验证**：链上锁仓量�?DefiLlama 数据交叉验证

**支持�?*: Ethereum, Arbitrum, Optimism, Base, Polygon, zkSync, Scroll, Linea, Solana, Aptos, Sui

**技术实�?*:
```python
# backend/app/collectors/chain_collector.py（计划实现位置）
class ChainCollector:
    """
    数据�? Etherscan 系列 / Alchemy / Infura / Dune / The Graph
    """
    async def monitor_new_contracts(self, chain: str) -> AsyncIterator[dict]
    async def get_contract_activity(self, address: str) -> dict
    async def track_unique_users(self, address: str) -> dict
```

**API 方案**: Etherscan 免费 5 �?秒；Alchemy 免费 300M CU/�?+ webhook；Dune $399/月（可选）�?
**采集频率**: webhook 实时（新合约）；地址活跃度每�?1 次�?
---

### **6. Galxe / Layer3（自动采集，P1�?*

**价�?*：任务平台反映用户获取活动，是空投前奏强信号�?
**采集策略**:
- A. 扫描 Galxe/Layer3 新活动，识别"有任务但未发�?的项�?- B. 活动热度：参与人数、任务完成数

**技术实�?*:
```python
# backend/app/collectors/quest_collector.py（计划实现位置）
class QuestCollector:
    """Galxe GraphQL API / Layer3 API"""
    async def fetch_galxe_campaigns(self) -> list[dict]
    async def fetch_layer3_quests(self) -> list[dict]
```

**采集频率**: 每日 1 次�?
---

### **7. CryptoRank（自动采集，P1�?*

**价�?*：项目聚合平台，融资、评级数据，补充 DefiLlama 未覆盖的项目�?
**技术实�?*:
```python
# backend/app/collectors/cryptorank_collector.py（计划实现位置）
class CryptoRankCollector:
    async def fetch_funding_rounds(self) -> list[dict]
    async def get_project_rating(self, project: str) -> dict
```

**API 方案**: 免费 100 �?小时；付�?$99/月。已�?`.env.example` 配置 `CRYPTORANK_API_KEY`�?
---

### **8. 手动输入（补充能力，P1�?*

> 手动输入�?v1.x 的主路径降级�?v2.0 �?*补充能力**，用于覆盖采集盲区�?
**适用场景**:
- 采集源未覆盖的新项目（用户手动发现）
- 内部测试与演�?- API 用户直接调用

**输入方式**:
1. **手动录入（UI�?*：用户在 Dashboard 表单填写项目字段
2. **CSV/Excel 导入**：批量粘贴已筛选的项目清单
3. **单次 API 调用**：`POST /api/v1/run`（详�?`API_SPEC.md §4`�?4. **seed 策展数据**：`scripts/seed.py` 内置演示项目（已存在�?
**请求结构**（对�?`API_SPEC.md §4`，扁�?ProjectInput�?
```bash
curl -X POST http://localhost:8002/api/v1/run \
  -H 'Content-Type: application/json' \
  -d '{"projects":[{"name":"LayerX","url":"https://layerx.xyz","sector":"L2","stage":"testnet","has_testnet":true,"has_points_program":true,"no_token_yet":true,"recent_funding":true}],"enable_llm":false}'
```

> 注：`projects` 内为扁平 `ProjectInput` 字段（`has_testnet`/`has_points_program`/`no_token_yet`/`recent_funding`），非嵌�?`raw_signals`。`raw_signals` �?Collector 内部转换后的产物�?
---

## 🔄 采集管道（自动发现，v2.0 核心�?
```
┌─────────────────────────────────────────────────────────�?�? 采集调度器（独立 cron，按源不同频率运行）                �?�? DefiLlama 每日 · Twitter 每小�?实时�?· 链上 webhook   �?└──────────────────────────┬──────────────────────────────�?                           �?┌─────────────────────────────────────────────────────────�?�? 1. 拉取 (Fetch)                                         �?�? �?Collector 从数据源拉取原始数据                        �?└──────────────────────────┬──────────────────────────────�?                           �?┌─────────────────────────────────────────────────────────�?�? 2. 归一�?(Normalize)                                   �?�? name_key/sector_key 标准化（ROADMAP §6.2.1�?           �?└──────────────────────────┬──────────────────────────────�?                           �?┌─────────────────────────────────────────────────────────�?�? 3. 去重 (Deduplication)                                 �?�? �?dedup_key 合并多源命中（ROADMAP §6.2.1�?            �?�? 来源优先级：seed > defillama > cryptorank > twitter     �?└──────────────────────────┬──────────────────────────────�?                           �?┌─────────────────────────────────────────────────────────�?�? 4. 新项目识�?(Discovery Filter)                        �?�? 硬规则过滤（详见下方"新项目识别规�?�?                  �?�? 写入 raw_projects 表（processed=false�?                �?└──────────────────────────┬──────────────────────────────�?                           �?┌─────────────────────────────────────────────────────────�?�? 5. 信号聚合 (Signal Aggregation)                        �?�? 多源信号写入 project_signals �?                        �?�? 增强 raw_signals 字段                                   �?└──────────────────────────┬──────────────────────────────�?                           �?新项目入�?                           �?┌─────────────────────────────────────────────────────────�?�? 6. 分析管道 (Analysis Pipeline，既�?                   �?�? Collector �?Narrative �?Team �?Risk �?Tokenomics        �?�? �?Scorer �?Orchestrator                                 �?└──────────────────────────┬──────────────────────────────�?                           �?┌─────────────────────────────────────────────────────────�?�? 7. 结果展示 (Presentation)                              �?�? 评分结果 + 可解释理�?�?Dashboard                       �?└─────────────────────────────────────────────────────────�?```

### **新项目识别规则（Discovery Filter�?*

采集管道�?4 步的硬规则过滤具体定义如下：

#### **必备条件（必须全部满足）**

| 条件 | 阈�?| 数据来源 | 说明 |
|------|------|----------|------|
| 未发�?| `has_token=false` | CoinGecko 验证 | 排除已流通代币项�?|
| 有活跃度 | 任一以下活跃度指标达�?| 见下�?| 排除僵尸项目 |

#### **活跃度指标（任一达标即可�?*

| 指标 | 阈�?| 数据来源 | 权重 |
|------|------|----------|------|
| TVL | > $1M | DefiLlama | 高（DeFi 项目�?|
| GitHub 活跃�?| commits_last_30d �?10 �?contributors �?3 | GitHub | 高（技术项目） |
| Twitter 提及�?| 7 日内�?VC/KOL 提及 �?1 �?| Twitter | 中（早期信号�?|
| 链上交互�?| 30 日内独立地址 �?100 | 链上 | 中（应用层） |
| 任务平台活动 | Galxe/Layer3 有进行中活动 | 任务平台 | 中（空投前奏�?|

#### **排除规则（命中即排除�?*

| 排除条件 | 理由 |
|----------|------|
| 已发币且流通市�?> $1M | 已过空投窗口 |
| TVL 持续 30 �?< $100K | 僵尸项目 |
| GitHub 90 天无 commit | 停止开�?|
| 标记�?scam/rug pull | 安全风险（来自社区标记） |

#### **discovery_score 计算**

```
discovery_score = 0.4 × tvl_score + 0.3 × github_score + 0.2 × twitter_score + 0.1 × chain_score

其中�?  tvl_score    = min(tvl / 10M, 1.0)        # TVL $10M 满分
  github_score = min(commits_30d / 50, 1.0)  # 50 commits 满分
  twitter_score = min(mentions_7d / 10, 1.0) # 10 次提及满�?  chain_score   = min(unique_users_30d / 1000, 1.0)  # 1000 用户满分
```

- `discovery_score �?0.3` �?进入分析管道（写 `raw_projects`，`processed=false`�?- `discovery_score < 0.3` �?仅存信号，不触发分析（节�?LLM 成本�?
---

## �?双调度模�?
### **采集调度器（新增�?*

| 数据�?| 频率 | 触发方式 | 写入目标 |
|--------|------|----------|----------|
| DefiLlama | 每日 08:00 UTC | cron | `raw_projects` |
| GitHub | 每日（跟�?DefiLlama�?| 事件触发 | `project_signals` |
| CoinGecko | 每日（跟�?DefiLlama�?| 事件触发 | `project_signals` |
| Twitter VC/KOL | 每小�?| cron | `project_signals` |
| Twitter 关键�?| �?15 分钟 | cron | `project_signals` |
| Twitter 实时�?| 持续 | webhook/stream | `project_signals` |
| 链上 | 实时 | webhook | `project_signals` |
| Galxe/Layer3 | 每日 | cron | `project_signals` |

### **分析调度器（既有，增强）**

| 触发方式 | 说明 |
|----------|------|
| 新项目入�?| `raw_projects` 新增 `processed=false` 记录 �?立即触发分析 |
| 定时批量 | 每小�?cron 批量处理积压项目 |
| 手动重跑 | `POST /re-score/{id}` |

> �?v1.x 差异：v1.x 调度仅驱动分析，数据来自用户。v2.0 采集调度器持续发现新项目，分析调度器自动消费�?
---

## 🗄�?采集�?Schema（v2.0 新增，需同步 DATABASE_DDL.md�?
> ⚠️ 以下表为 v2.0 新增，当�?`DATABASE_DDL.md` **不含**这些表。需后续同步更新 `DATABASE_DDL.md`�?
### **data_sources（数据源注册表）**

```sql
CREATE TABLE data_sources (
    source_id TEXT PRIMARY KEY,          -- �?"defillama", "twitter", "github"
    source_type TEXT NOT NULL,            -- "api" / "stream" / "webhook" / "manual"
    source_name TEXT NOT NULL,
    enabled BOOLEAN DEFAULT TRUE,
    last_sync TIMESTAMP,
    sync_status TEXT,                     -- "idle" / "running" / "error" / "rate_limited"
    api_calls_today INTEGER DEFAULT 0,
    api_limit INTEGER,                    -- 每日限额
    config JSON,                          -- 源特定配�?    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### **raw_projects（采集原始项目池�?*

```sql
CREATE TABLE raw_projects (
    raw_id TEXT PRIMARY KEY,              -- 采集记录 id（非项目 id�?    source_id TEXT REFERENCES data_sources(source_id),
    dedup_key TEXT NOT NULL,              -- 归一化去重键（ROADMAP §6.2.1�?    raw_data JSON NOT NULL,               -- 原始采集数据
    discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    processed BOOLEAN DEFAULT FALSE,      -- 是否已进入分析管�?    processed_at TIMESTAMP,
    project_id TEXT,                      -- 关联 projects �?id（处理后回填�?    discovery_score REAL DEFAULT 0.0      -- 发现质量分（初筛用）
);

CREATE INDEX idx_raw_projects_dedup ON raw_projects(dedup_key);
CREATE INDEX idx_raw_projects_unprocessed ON raw_projects(processed) WHERE processed = FALSE;
```

### **project_signals（项目信号聚合）**

```sql
CREATE TABLE project_signals (
    signal_id TEXT PRIMARY KEY,
    project_id TEXT,                      -- 关联 projects 表（可为空，未建立关联时�?    dedup_key TEXT,                       -- 关联 raw_projects
    signal_type TEXT NOT NULL,            -- "tvl" / "github_activity" / "twitter_mention" / "chain_activity" / "quest"
    signal_source TEXT NOT NULL,          -- "defillama" / "github" / "twitter" / "chain" / "galxe"
    signal_data JSON NOT NULL,            -- 信号具体数据
    signal_strength REAL DEFAULT 0.0,     -- 信号强度�?-1�?    captured_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_signals_project ON project_signals(project_id);
CREATE INDEX idx_signals_type ON project_signals(signal_type, signal_source);
```

### **collection_logs（采集日志）**

```sql
CREATE TABLE collection_logs (
    log_id TEXT PRIMARY KEY,
    source_id TEXT REFERENCES data_sources(source_id),
    started_at TIMESTAMP NOT NULL,
    finished_at TIMESTAMP,
    items_collected INTEGER DEFAULT 0,
    items_new INTEGER DEFAULT 0,          -- 去重后的新项目数
    items_duplicate INTEGER DEFAULT 0,
    status TEXT,                          -- "success" / "error" / "partial" / "rate_limited"
    error_message TEXT
);
```

### **projects 表扩展字�?*

```sql
ALTER TABLE projects ADD COLUMN discovery_source TEXT;      -- 首次发现的来�?ALTER TABLE projects ADD COLUMN discovered_at TIMESTAMP;    -- 首次发现时间
ALTER TABLE projects ADD COLUMN auto_discovered BOOLEAN DEFAULT TRUE;  -- 是否自动发现（vs 手动�?ALTER TABLE projects ADD COLUMN signal_count INTEGER DEFAULT 0;        -- 关联信号�?```

---

## 🔑 API Key 管理

### **当前已配置的字段（见 `.env.example`�?*

```bash
# 已在 .env.example �?DEFILLAMA_BASE_URL=https://api.llama.fi
CRYPTORANK_API_KEY=
TWITTER_BEARER_TOKEN=
TWITTER_API_KEY=
TWITTER_API_SECRET=
DUNE_API_KEY=
```

### **v2.0 需新增的字段（需同步 `.env.example`�?*

```bash
# GitHub（计划新增）
GITHUB_TOKEN=

# 链上数据（计划新增）
ETHERSCAN_API_KEY=
ALCHEMY_API_KEY=
ALCHEMY_WEBHOOK_URL=

# CoinGecko（计划新增，可选付费）
COINGECKO_API_KEY=

# Galxe/Layer3（计划新增）
GALXE_API_KEY=
LAYER3_API_KEY=
```

> 注：当前 `backend/app/config.py` �?`.env.example` 均无上述字段，需后续同步添加�?
### **安全实践**
- �?所�?Key 存于 `.env`（不提交 git�?- �?提供 `.env.example` 模板
- �?Key 使用量监控告警（采集场景用量高，需密切监控�?- �?Prompt Injection 防御（`SECURITY.md §10.1`，外部数据进�?LLM 分析前需隔离�?
### **速率限制管理**

```python
# backend/app/utils/rate_limiter.py（计划实现位置）
class RateLimiter:
    """令牌桶：每个数据源独立限流，超限自动降级/排队"""
    async def acquire(self, source: str) -> bool
    async def wait_for_slot(self, source: str)
    async def get_usage(self, source: str) -> dict
```

| 数据�?| 速率限制 | 超限处理 |
|--------|----------|----------|
| DefiLlama | 10 req/s（自限） | 排队等待 |
| GitHub | 5,000 req/h | 排队等待 + 缓存 |
| CoinGecko | 30 req/min（免费） | 降级，跳过代币验�?|
| Twitter | �?Tier | 优先级队列，丢弃低价值查�?|
| Etherscan | 5 req/s | 排队等待 |

---

## 📊 预期成果

### **数据量预估（自动采集�?*

```
DefiLlama:    ~3,000 协议/日（全量），过滤�?~100-300 候�?�?GitHub:       ~500-1,000 仓库/日（按关键词�?Twitter:      ~1,000-5,000 推文/日（VC/KOL + 关键词）
链上:         ~100-500 新合�?日（主流链）
Galxe/Layer3: ~50-200 活动/�?─────────────────────────────────────
去重后新项目: ~50-200/�?进入分析管道: ~20-50/日（初筛后）
```

### **成本预估**

```
Twitter API Basic:       $100/月（必需�?CoinGecko (可选付�?:    $0-129/�?Dune (可�?:             $0-399/�?Alchemy (链上):          $0（免费额度足�?MVP�?服务�?                  $50-100/�?─────────────────────────────────
自动采集模式成本:        $150-700/�?```

### **性能目标**

```
采集延迟:      单源全量扫描 < 5 分钟
发现 �?分析:   新项目入队后 < 1 小时内完成评�?分析速度:      �?10 项目/分钟（批量并行）
去重准确�?    �?95%
系统可用�?    �?99%
```

---

## 🛡�?采集故障降级矩阵

自动扫描依赖外部 API，必须定义故障降级策略。按故障等级分为 4 级：

### **故障等级定义**

| 等级 | 定义 | 触发条件 | 影响范围 |
|------|------|----------|----------|
| **L1：限�?* | API 接近或达到速率限制 | 429 响应或令牌桶 < 10% | 单源采集中断 |
| **L2：故�?* | API 短时不可�?| 5xx 响应连续 �?3 次或超时 | 单源采集停止 |
| **L3：停�?* | API 长时不可�?| 故障持续 > 1 小时 | 单源采集停摆，影响发现覆�?|
| **L4：付费超�?* | 付费源额度耗尽 | 月度配额用尽 | 付费源停止（Twitter/链上�?|

### **降级矩阵（按数据�?× 故障等级�?*

| 数据�?| L1 限流 | L2 故障 | L3 停服 | L4 付费超限 |
|--------|---------|---------|---------|-------------|
| **DefiLlama** | 排队等待 | 跳过本轮，下轮重�?| 降级：仅�?CoinGecko+GitHub 发现 | 不适用（免费） |
| **GitHub** | 排队+缓存 | 跳过活跃度补�?| 降级：仅�?DefiLlama TVL 评估 | 不适用（免费额度足够） |
| **CoinGecko** | 降级：跳过代币验�?| 标记 `has_token=unknown`，放行进分析 | 同左 + 告警 | 切换�?Demo API�?0/min�?|
| **Twitter** | 优先级队�?| 跳过本轮关键词搜�?| 降级：仅保留 VC/KOL 轮询 | **停止 Twitter 采集**，仅保留其他�?|
| **链上（Etherscan�?* | 排队等待 | 跳过地址活跃度补�?| 降级：仅�?DefiLlama TVL 交叉验证 | 不适用（免费额度足够） |
| **链上（Alchemy webhook�?* | 不适用 | 重连 webhook | 告警，人工介�?| 切换�?Etherscan 轮询 |
| **Galxe/Layer3** | 跳过本轮 | 跳过本轮 | 降级：无任务平台信号 | 不适用（免费） |

### **全局降级规则**

| 触发条件 | 全局降级动作 |
|----------|-------------|
| �?3 个核心源（DefiLlama/GitHub/CoinGecko/Twitter）同�?L3 | 系统进入"降级采集模式"：仅保留 DefiLlama + GitHub，停止其他源；告�?|
| 所有采集源�?L3/L4 | 系统进入"维护模式"：停止采集调度器，仅响应手动输入与已有项目重跑；告警 |
| 单日发现项目�?< 5（远低于 KPI 20/日） | 触发采集健康检查，告警人工介入 |
| LLM 付费超限（`LLM_DAILY_BUDGET_USD` 耗尽�?| 自动降级为规则引擎（ADR-001 降级策略），LLM 采集继续 |

### **故障恢复**

- **自动恢复**：L1/L2 故障，下一�?cron 自动重试（指数退避）
- **人工介入**：L3/L4 故障，告�?+ 运维 runbook（`OPERATIONS.md §5` 采集故障处理�?- **数据补偿**：故障恢复后，对故障期间漏采的源做一次全量回�?
---

## 📦 数据保留策略

`raw_projects` / `project_signals` / `collection_logs` 数据量大，需明确保留与清理规则：

### **保留策略矩阵**

| �?| 热数据（在线查询�?| 温数据（归档�?| 冷数据（删除�?| 清理频率 |
|----|-------------------|---------------|---------------|----------|
| `raw_projects` | 30 �?| 30-180 天（迁移至归档表 `raw_projects_archive`�?| > 180 �?| 每日 cron |
| `project_signals` | 90 �?| 90-365 天（归档�?| > 365 �?| 每周 cron |
| `collection_logs` | 90 �?| 不归�?| > 90 天直接删�?| 每周 cron |
| `projects`（已分析�?| 永久 | 不适用 | 不适用 | 不清�?|
| `scores`/`logs`（评分记录） | 永久 | 不适用 | 不适用 | 不清�?|

### **归档机制**

```sql
-- 每日 cron 执行（凌晨低峰期�?
-- 1. raw_projects 归档�?0 天前未处理的采集记录
INSERT INTO raw_projects_archive SELECT * FROM raw_projects
WHERE discovered_at < datetime('now', '-30 days');
DELETE FROM raw_projects WHERE discovered_at < datetime('now', '-30 days');

-- 2. project_signals 归档�?0 天前信号
INSERT INTO project_signals_archive SELECT * FROM project_signals
WHERE captured_at < datetime('now', '-90 days');
DELETE FROM project_signals WHERE captured_at < datetime('now', '-90 days');

-- 3. collection_logs 清理�?0 天前日志直接删除
DELETE FROM collection_logs WHERE started_at < datetime('now', '-90 days');
```

### **存储预估**

| �?| 日增�?| 月增�?| 年增量（含归档） |
|----|--------|--------|------------------|
| `raw_projects` | ~200 行（50 项目 × 4 源） | ~6,000 �?| ~72,000 行（�?18K + 归档 54K�?|
| `project_signals` | ~1,000 �?| ~30,000 �?| ~360,000 行（�?90K + 归档 270K�?|
| `collection_logs` | ~30 行（每日每源 1 条） | ~900 �?| ~11,000 行（仅热，不归档�?|

> 单行平均 1KB，年增量�?450MB，SQLite 可承受。PostgreSQL 切换后无压力�?
---

## 📏 采集质量评估指标

�?去重准确�?外，采集场景需独立的采集质量指标体系：

### **采集质量 6 维度**

| 指标 | 定义 | 目标�?| 度量方式 | 告警阈�?|
|------|------|--------|----------|----------|
| **误报�?* | 不该进分析却进了的项目占�?| < 10% | 分析�?IGNORE �?+ discovery_score 虚高 | > 20% 触发规则调优 |
| **漏报�?* | 该发现却没发现的项目占比 | < 15% | 事后手动补充的项目中，采集源应覆盖但未覆盖的比例 | > 25% 触发源覆盖检�?|
| **信号新鲜�?* | 信号从产生到入库的延迟中位数 | < 1 小时 | `captured_at - 原始事件时间` | > 4 小时告警 |
| **源覆盖率** | 进入分析的项目中�?�?2 个源命中的比�?| �?30% | 多源命中项目�?/ 总分析项目数 | < 20% 告警源单一 |
| **采集稳定�?* | 采集成功�?| �?95% | `collection_logs.status='success'` 占比 | < 90% 告警 |
| **去重准确�?* | 1 - 误合并率 - 漏合并率 | �?95% | 人工抽检 + 多源 dedup_key 一致性校�?| < 90% 告警 |

### **质量评估流程**

1. **每日**：采集稳定性、信号新鲜度、源覆盖率自动统计（写入 `collection_logs` 聚合�?2. **每周**：误报率（通过 IGNORE 档反推）、去重准确率（人工抽检 50 个项目）
3. **每月**：漏报率（统计手动补充项目中应被自动发现的比例）
4. **每月**：输出采集质量报告至 `evaluation/collection/`（与 LLM 评估并列�?
### **质量不达标处�?*

- 误报率高 �?调高 `discovery_score` 阈值或收紧排除规则
- 漏报率高 �?增加数据源或扩大关键词覆�?- 信号新鲜度差 �?提高采集频率或切换实时流
- 源覆盖率�?�?接入更多交叉验证�?
---

## ⚠️ 风险与应�?
| 风险 | 影响 | 应对措施 |
|------|------|----------|
| 采集噪音（低质量项目�?| 浪费分析资源 | 硬规则初筛（TVL/活跃度阈值）+ Agent 深度分析 |
| API 限流 | 采集中断 | 速率限制�?+ 降级策略 + 重试机制 |
| API 成本超支 | 预算压力 | 成本监控告警 + 分级接入（免费源优先�?|
| 多源数据冲突 | 评分不一�?| 去重归一�?+ 来源优先级仲�?|
| 存储增长 | 数据库膨胀 | 数据保留策略（见上方"数据保留策略"章节�? 定期归档 |
| Prompt Injection | LLM 被劫�?| `SECURITY.md §10.1` 输入隔离 + 输出约束 |
| 虚假项目（采集误判） | 误报增多 | 多源交叉验证 + 技术指标硬过滤 |
| 单点源故�?| 发现覆盖下降 | 采集故障降级矩阵（见上方章节�? 多源冗余 |

---

## 🛣�?实施优先�?
### **MVP/V1 阶段（核心采集能力）**

```
1. 采集基础设施：采集表 + 采集调度�?+ 速率限制�?2. DefiLlama Collector（免费、高价值，首选）
3. GitHub Collector（活跃度，免费）
4. CoinGecko Collector（代币验证，免费�?5. 新项目识别规则（未发�?+ 活跃度过滤）
6. 采集 �?分析自动衔接
```

验证：系统每日自动发�?20-50 个候选项目并产出评分

### **V1+ 阶段（实时信号增强）**

```
7. Twitter Collector（VC/KOL 监听，付费）
8. 链上 Collector（新合约监控，webhook�?9. Galxe/Layer3 Collector（任务信号）
10. CryptoRank Collector（融资数据）
```

提升：实时早期信�?+ 链上活跃度验�?
### **V2 阶段（完善与社区信号�?*

```
11. Twitter Filtered Stream（实时流，需 Pro Tier�?12. Discord/Medium/Reddit Collector（社区信号）
13. 采集质量优化（信号权�?+ 去噪模型�?```

完善：全维度信号覆盖 + 实时�?
---

## 🔗 关联文档影响清单（需同步对齐�?
| 文档 | 影响�?| 对齐动作 |
|------|--------|----------|
| `ENGINEERING_ROADMAP.md §6.2` | 数据源以手动输入为主 | 重写为自动采集为�?|
| `DATABASE_DDL.md` | 当前无采集表 | 新增 4 张采集表 + projects 扩展字段 |
| `SECURITY.md §10.2` | Collector 禁止外部 HTTP | 调整为允许采集源白名�?HTTP |
| `.env.example` | 缺采集源配置 | 补充 GitHub/链上/CoinGecko/Galxe �?key |
| `backend/app/config.py` | 缺采集源配置字段 | 同步新增配置字段 |
| `API_SPEC.md` | �?`/run` 手动输入 | 补充 `/discoveries` 查询自动发现项目 |
| `docs/adr/` | 无方向反�?ADR | 新增 ADR-012 |

---

## �?下一步行�?
1. **新增 ADR-012**：记录方向反转决策（手动 �?自动扫描�?2. **同步 DATABASE_DDL.md**：新增采集表 schema
3. **同步 .env.example + config.py**：新增采集源配置字段
4. **同步 ENGINEERING_ROADMAP.md §6.2**：数据源章节重写
5. **实现采集基础设施**：采集调度器 + 速率限制�?+ 采集表迁�?6. **接入 DefiLlama Collector**：首个核心采集源

---

*更新�?2026-07-09 · v2.0 由方向反转为自动扫描全网定位，保留手动输入作为补充能�?
