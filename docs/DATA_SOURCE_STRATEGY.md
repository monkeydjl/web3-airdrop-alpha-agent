# Web3 Airdrop Alpha - 数据源策略（自动扫描视角）

**文档版本**: v3.0
**创建日期**: 2026-07-09
**重写日期**: 2026-08-23
**状态**: 已落地为实现（v2.0 起从规划转为现状记录）
**关联文档**: `SYSTEM_DIRECTION_CHANGE.md`、`OPERATIONS.md §4`、`DATABASE_DDL.md §2.13–2.19`、`SECURITY.md §10`、`.env.example`
**门禁**: `backend/tests/test_data_source_strategy_parity.py`

---

## 0. 这次重写改了什么（读之前先看这段）

上一版（v2.0，2026-07-09）是**方向规划稿**：当时 10 个采集器一个都还没写，
所以全文用「（计划实现位置）」标注每个类的落点，并列了一堆
「需同步新增」的配置字段。

**到 2026-08-23，这些东西大部分已经做完了**，于是那份文档从「规划」
变成了「与现实不符的描述」。具体失真见 §12，最要紧的四条：

1. **10 个采集器全部已实现**，但文档仍逐个标着「（计划实现位置）」，
   而且**文件名和类名全都不对**（例：文档说
   `collectors/defillama_collector.py`，真实是 `collectors/defillama.py`）。
   照文档去找代码，10 个路径 10 个都找不到。
2. **`discovery_score` 的统一公式是假的**。文档给了一条
   `0.4×tvl + 0.3×github + 0.2×twitter + 0.1×chain` 的全局公式 ——
   代码里**没有任何地方实现它**。真实情况是每个采集器各算各的
   （见 §5.4），权重和入参都不一样。
3. **`POST /re-score/{id}` 这个接口不存在**（46 个真实路由里没有它）。
4. **`evaluation/collection/` 目录不存在**，「每月输出采集质量报告」从未发生。

**本次重写的原则**：把「计划」改写成「现状 + 实测数字」，
凡是还没做的明确标 ❌ 并说清"没有它会怎样"，
不再让读者分不清哪句是已实现、哪句是构想。

> 顺带说明这份文档为什么烂了这么久：它长期挂在**编码损坏登记表**上
> （498 处中文字被截断成非法 UTF-8 字节），而"已登记为损坏"成了
> 没人再读它的理由。**登记豁免掩盖的不只是字节问题，还有内容问题。**
> 这一版同时修掉了字节和内容。

---

## 1. 执行摘要

系统主动从多数据源**自动扫描全网**，持续发现未空投的早期 Web3 项目。
采集调度器独立运行，把候选项目写入 `raw_projects` 表，
再由分析调度器触发多 Agent 评分。

外部数据源（DefiLlama / GitHub / CoinGecko / Twitter / 链上 / 任务平台等）
是**核心采集源**，不是"可选补充"。手动输入（UI / CSV / API / seed）
是**补充能力**，用于覆盖采集盲区。

**实测现状（2026-08-23，本地库）**：

| 事实 | 数字 |
|---|---|
| 已注册采集器 | **14 个**（2026-08-29 起加入 `discord` `reddit` `medium` `mirror` 四个 P2 源） |
| `.env` 开关 + Key 都就绪（`config_ready=true`） | **7 个**（`defillama` `github` `coingecko` `cryptorank` `etherscan` + P2 的 `medium` `mirror` 无需 Key 默认开） |
| `data_sources` 表有记录的源 | **5 个**（`defillama` `github` `coingecko` `cryptorank` `etherscan`） |
| `raw_projects` 累计 | **615 行**，dedup_key 全部互不重复 |
| `project_signals` 累计 | **2261 行** |
| `collection_logs` 累计 | **20 行** |
| 由采集入库的 `projects` | 288 行中 `defillama` 165 / `seed` 99 / `github` 16 / `manual` 7 / `import` 1 |

**别把「14 个已注册」读成「14 个在跑」**：一个源真正会跑需要同时满足
三条（开关 ∧ Key ∧ `data_sources.enabled`），详见 §4.1。

---

## 2. 数据源优先级矩阵

「已实现」= 代码里有对应 collector 类并注册进 registry。

| 数据源 | 优先级 | 已实现 | 接入方式 | 主要价值 | API 成本 |
|---|---|---|---|---|---|
| **DefiLlama** | P0 | ✅ | 自动采集（全量协议扫描） | 未发币状态、TVL、链、类别 | 免费，无需 Key |
| **GitHub** | P0 | ✅ | 自动采集（活跃度扫描 + 关键词搜索） | 技术活跃度、仓库信息 | 免费（需 Token 提额） |
| **CoinGecko** | P0 | ✅ | 自动采集（代币状态验证） | 市值、代币状态、上所 | 免费（Key 仅提额） |
| **Twitter/X** | P0 | ✅ ×2 | 自动采集（KOL 轮询 + 关键词搜索） | 早期信号、融资、测试网、积分 | $100/月起 |
| **Etherscan（链上）** | P1 | ✅ | 自动采集（事件密度 + 独立地址） | 真实链上活跃度 | 免费额度 |
| **Galxe** | P1 | ✅ | 自动采集（任务活动扫描） | 任务活动信号（空投前奏） | 需 Key |
| **Layer3** | P1 | ✅ | 自动采集（任务活动扫描） | 同上 | 需 Key |
| **CryptoRank** | P1 | ✅ | 自动采集（项目排名聚合） | 融资、排名 | 免费额度 / 付费 |
| **RootData** | P1 | ✅ | 自动采集（关键词检索） | 项目库补充 | 需 Key |
| **Alchemy Webhook** | P1 | ⚠️ 半 | 被动接收（`POST /api/v1/webhook/alchemy`） | 新合约事件 | 免费额度 |
| **Discord** | P2 | ✅ | 自动采集（Bot 读配置频道消息） | 社区活跃度 | 免费（需 Bot Token） |
| **Reddit** | P2 | ✅ | 自动采集（OAuth 关键词搜索） | 社区情绪 | 免费（需 OAuth App） |
| **Medium** | P2 | ✅ | 自动采集（RSS tag feed） | 路线图、公告 | 免费，无需 Key |
| **Mirror** | P2 | ✅ | 自动采集（Arweave GraphQL） | 路线图、公告 | 免费，无需 Key |
| **手动录入 / CSV 导入** | — | ✅ | `POST /api/v1/run`、`POST /api/v1/import/projects` | 覆盖采集盲区 | 免费 |
| **seed 策展** | — | ✅ | `scripts/seed.py` | 演示 / 测试基线 | 免费 |

> **P2 四个源（Discord / Reddit / Medium / Mirror）2026-08-29 起已实现**，
> 都是「内容里提到某项目」的二阶信号源，`discovery_score` 上限刻意压在
> 0.28（分析阈值 0.3 之下），只贡献 `project_signals`、不触发 LLM 分析。
> Discord 需 Bot Token、Reddit 需 OAuth App，都默认关闭；
> Medium（RSS）/ Mirror（Arweave 公开读）无需 Key、默认开启。
> **Alchemy Webhook 标「半」的含义**：接收端点、签名校验、状态查询都在
> （`/api/v1/webhook/alchemy` + `/status`），但它是被动接收，
> 不在 registry 里、不参与采集调度、`data_sources` 表里也没有它的记录。

---

## 3. 14 个采集器的真实落点

**上一版这张表的 10 个路径全是错的**（都写成
`{source}_collector.py` 并标「计划实现位置」）。真实文件与类名：

<!-- collector-files:begin -->

| source_id | 文件 | 类 |
|---|---|---|
| `defillama` | `backend/app/collectors/defillama.py` | `DefiLlamaCollector` |
| `github` | `backend/app/collectors/github.py` | `GitHubCollector` |
| `coingecko` | `backend/app/collectors/coingecko.py` | `CoinGeckoCollector` |
| `twitter_kol` | `backend/app/collectors/twitter.py` | `TwitterKolCollector` |
| `twitter_keyword` | `backend/app/collectors/twitter.py` | `TwitterKeywordCollector` |
| `etherscan` | `backend/app/collectors/etherscan.py` | `EtherscanCollector` |
| `galxe` | `backend/app/collectors/galxe.py` | `GalxeCollector` |
| `layer3` | `backend/app/collectors/layer3.py` | `Layer3Collector` |
| `cryptorank` | `backend/app/collectors/cryptorank.py` | `CryptoRankCollector` |
| `rootdata` | `backend/app/collectors/rootdata.py` | `RootDataCollector` |
| `discord` | `backend/app/collectors/discord.py` | `DiscordCollector` |
| `reddit` | `backend/app/collectors/reddit.py` | `RedditCollector` |
| `medium` | `backend/app/collectors/medium.py` | `MediumCollector` |
| `mirror` | `backend/app/collectors/mirror.py` | `MirrorCollector` |

<!-- collector-files:end -->

配套模块（不是采集器，别当成源）：`base.py`（`DataCollector` 抽象基类 +
`RawSignal` / `RawDiscovery` / `CollectorResult`）、`factory.py`
（`build_default_registry` / `get_default_registry`）、`registry.py`、
`scheduler.py`、`persistence.py`（`CollectionRepository`）、
`rate_limiter.py`（`TokenBucketRateLimiter`）、`metrics.py`、`noise.py`。

> 上一版还说速率限制器在 `backend/app/utils/rate_limiter.py` ——
> **那个路径不存在**，真实位置是 `backend/app/collectors/rate_limiter.py`。

---

## 4. 一个源要真的跑起来，需要三个条件同时成立

### 4.1 三条件

| 条件 | 在哪里 | 不满足时的表现 |
|---|---|---|
| ① `*_ENABLED=true` | `.env` / `app/config.py` | `is_enabled()` 返回 False，调度跳过 |
| ② 该源需要的 Key 已配 | `.env` | 同上（`is_enabled()` 同时检查 Key） |
| ③ `data_sources.enabled = 1` | 数据库（可在 `/ops` 页切） | 调度器读到 0 就跳过本轮 |

**危害形态**：三者缺一都不跑，但该源在
`GET /api/v1/collections/sources` 里**依然会被列出**，只是
`config_ready=false`。排查「为什么没发现新项目」时不看这一列，
就会去翻一个**从未运行过**的源的日志 —— 翻不到任何错误，
于是误判成"采集是好的，问题在分析侧"，方向整个跑偏。

完整的门控规则表（开关名 + 是否需要 Key + 具体 env 变量名）
见 `OPERATIONS.md §4.3`，那张表由门禁与 `is_enabled()` 源码逐项比对。

### 4.2 Twitter 的特殊之处

**两个采集器共用一个开关和一个 Token**：`TWITTER_ENABLED` +
`TWITTER_BEARER_TOKEN` 同时控制 `twitter_kol` 和 `twitter_keyword`，
没法只开一个。

`.env.example` 里还有 `TWITTER_API_KEY` / `TWITTER_API_SECRET` 两个键 ——
**采集器根本不读它们**，填了 twitter 依然不会跑。

### 4.3 本机实测就绪状态（2026-08-23，P2 源 2026-08-29 补充）

已配 Key：`GITHUB_TOKEN`、`CRYPTORANK_API_KEY`、`ETHERSCAN_API_KEY`、
`COINGECKO_API_KEY`。
未配：`TWITTER_BEARER_TOKEN`、`GALXE_API_KEY`、`LAYER3_API_KEY`、
`ROOTDATA_API_KEY`、`DISCORD_BOT_TOKEN`、`REDDIT_CLIENT_ID/SECRET`。

于是 `config_ready=true` 的是 5 个：
`defillama` `github` `coingecko` `cryptorank` `etherscan`。
（P2 的 `medium` `mirror` 无需 Key，`config_ready` 恒为 true，不算"配了 Key"。）

**代码默认值（完全不给 `.env`）下只有 5 个为 true**：
`defillama` `github` `coingecko` `medium` `mirror` —— 这五个的 `*_ENABLED`
默认是 `true`（前三个免费 P0，后两个免费 P2），其余 9 个默认 `false`
（都需 Key 或付费）。

---

## 5. 采集管道

### 5.1 六个阶段

```
采集调度器（APScheduler，每源独立 cron，UTC）
        │
        ▼
1. 拉取 (Fetch)        各 collector 的 collect() → CollectorResult
        │
        ▼
2. 归一化 (Normalize)  name_key / sector_key 标准化
        │
        ▼
3. 去重 (Deduplication) 按 dedup_key 合并多源命中，来源优先级仲裁
        │
        ▼
4. 新项目识别          噪音过滤 + discovery_score 初筛
        │              写入 raw_projects（processed=0）
        ▼
5. 信号聚合            多源信号写入 project_signals
        │
        ▼
6. 分析管道（独立 cron，不由采集触发）
                       Collector → Narrative → Team → Risk → Tokenomics
                       → Scorer → Orchestrator
```

> **第 5 步到第 6 步之间没有自动衔接。** `COLLECTION_AUTO_RUN_ENABLED`
> 默认 `false`，两条链各按自己的 cron 走。上一版文档写的
> 「`raw_projects` 新增 `processed=false` 记录 → 立即触发分析」**不成立**。

### 5.2 去重来源优先级（实测自 `app/utils/normalize.py` `SOURCE_PRIORITY`）

数字越小优先级越高，冲突时保留优先级高的那条记录的字段：

<!-- source-priority:begin -->

| 优先级 | 来源 |
|---|---|
| 0 | `manual` |
| 1 | `api` |
| 2 | `seed` |
| 3 | `defillama` |
| 4 | `coingecko` |
| 5 | `github`、`rootdata` |
| 6 | `cryptorank`、`galxe`、`layer3`、`etherscan` |
| 7 | `twitter_kol` |
| 8 | `twitter_keyword`、`discord`、`reddit`、`medium`、`mirror` |
| 9 | `twitter` |
| 99 | `unknown`（以及任何未登记的来源名） |

<!-- source-priority:end -->

> 上一版写的优先级链是 `seed > defillama > cryptorank > twitter` ——
> 方向对，但**漏掉了 `manual` 和 `api` 这两个最高优先级**，
> 也没写未知来源落 99。手动录入压过一切，这一点很重要：
> 你在 UI 里改的字段不会被下一轮采集覆盖掉。

### 5.3 噪音过滤（`app/collectors/noise.py`）

在写入 `raw_projects` 之前先过一遍硬规则，导出的判据是：
`CATEGORY_DENY`、`NAME_DENY_SUBSTRINGS`、`PARENT_DENY_SUBSTRINGS`、
`SLUG_DENY_PREFIXES`，以及
`is_listed_token_no_airdrop_signals` / `is_noise_project` /
`is_noise_protocol` / `is_noise_raw_project`。

其中 `is_listed_token_no_airdrop_signals` 只对
`coingecko` / `cryptorank` / `etherscan` / `alchemy_webhook` 生效 ——
这四个源会带回大量已上所代币，而已上所且没有任何空投信号的项目
对本系统没有价值。

### 5.4 `discovery_score`：**没有统一公式**（上一版最大的失真）

上一版给了一条全局公式：

```
discovery_score = 0.4 × tvl_score + 0.3 × github_score
                + 0.2 × twitter_score + 0.1 × chain_score
```

**代码里没有任何地方实现它。** 全仓搜不到 `twitter_score` 与
`chain_score`（`chain_score` 只在 DefiLlama 内部作为"链数量分"存在，
含义完全不同），也没有任何跨源汇总步骤。

真实情况：**每个采集器各算各的**，权重、入参、上限都不一样。

<!-- discovery-formula:begin -->

| source_id | 计算方式（实测自代码） | 上限 |
|---|---|---|
| `defillama` | TVL 40% + 7 日趋势 20% + 链数量 15% + 元数据完整度 15% + 社交 10% | 1.0 |
| `github` | stars 35% + forks 15% + 近期活跃 30% + 语言匹配 10% + 仓库成熟度 10%，再乘相关度 | `MAX_DISCOVERY_SCORE = 0.85`（关键词搜索命中压到 0.28） |
| `coingecko` | **固定 0.1**（只做代币状态验证，不参与发现排序） | 0.1 |
| `cryptorank` | 排名基准 + 排名加成 + 7 日动量（≤0.08）+ 成交量档（≤0.04） | `MAX_DISCOVERY_SCORE = 0.28` |
| `rootdata` | 0.35 + 融资质量 × 0.45 + 加成项，再夹到 [0.2, 0.85] | 0.85 |
| `etherscan` | `0.08 + (0.6×事件密度 + 0.4×独立地址) × 0.2` | `MAX_DISCOVERY_SCORE = 0.28` |
| `galxe` | 0.3 起，按奖励类型 / 状态累加 | 1.0 |
| `layer3` | 0.3 起，按奖励 / 链信息累加 | 1.0 |
| `twitter_kol` | 来源权重 0.3 + 信号类型权重 + 互动量 × 0.25 | 1.0 |
| `twitter_keyword` | 来源权重 0.1 + 信号类型权重 + 互动量 × 0.25 | 1.0 |

<!-- discovery-formula:end -->

**为什么几个源的上限被刻意压在 0.28**：分析阈值
`DISCOVERY_SCORE_ANALYSIS_THRESHOLD = 0.3`。上限低于阈值就意味着
**这个源单独永远不足以触发 LLM 分析**，只能贡献信号 ——
`cryptorank` / `etherscan` / GitHub 关键词搜索都属于这一档。
这是省 LLM 成本的设计，不是 bug。

**阈值行为**：

- `discovery_score ≥ 0.3` → 进入分析管道（写 `raw_projects`，`processed=0`）
- `discovery_score < 0.3` → 仅存信号，不触发分析

实测（615 行 `raw_projects`）：≥0.3 的 **106 行**，<0.3 的 **509 行**，
即 **83% 的采集记录只贡献信号、从不触发分析**。
这也是 `UNPROCESSED_RAW_RETENTION_DAYS=90` 这一档保留策略存在的原因 ——
它们永远不会被标记 `processed=1`，没有这一档就会无限累积。

### 5.5 各源实测产出（2026-08-23）

<!-- measured-yield:begin -->

| source_id | `raw_projects` 行数 | discovery_score 均值 | 区间 | 已 processed |
|---|---|---|---|---|
| `coingecko` | 268 | 0.1 | 0.1–0.1 | 0 |
| `cryptorank` | 226 | 0.2084 | 0.2–0.28 | 0 |
| `defillama` | 87 | 0.796 | 0.7295–0.92 | 87 |
| `github` | 30 | 0.3523 | 0.1342–0.744 | 19 |
| `etherscan` | 4 | 0.1135 | 0.094–0.16 | 4 未处理 |

<!-- measured-yield:end -->

读法：**`defillama` 是唯一稳定越过分析阈值的源**（均值 0.796，87/87 全部
进了分析），`github` 部分越线（19/30），
`coingecko` / `cryptorank` / `etherscan` 因为上限设计低于 0.3，
一条都没进分析 —— 它们的价值在 `project_signals` 里。

`project_signals` 分布：`coingecko/token_listed` 500、
`cryptorank/market_momentum` 400、`cryptorank/token_listed` 400、
`defillama` 的 `airdrop_hint`/`chain_activity`/`tvl` 各 300、
`github/github_activity` 51、`etherscan` 的 `chain_activity`/`gas_usage` 各 5。

---

## 6. 双调度模型

### 6.1 采集调度器：真实 cron（全部 UTC）

实测自 `settings`。`OPERATIONS.md §7.1` 有同一张表，由门禁逐条比对。

<!-- collection-cron:begin -->

| source_id | cron | 频率 |
|---|---|---|
| `defillama` | `0 8 * * *` | 每日 08:00 |
| `github` | `30 8 * * *` | 每日 08:30 |
| `coingecko` | `0 9 * * *` | 每日 09:00 |
| `cryptorank` | `15 9 * * *` | 每日 09:15 |
| `rootdata` | `45 9 * * *` | 每日 09:45 |
| `galxe` | `0 10 * * *` | 每日 10:00 |
| `layer3` | `30 10 * * *` | 每日 10:30 |
| `etherscan` | `0 */6 * * *` | 每 6 小时 |
| `twitter_kol` | `0 * * * *` | 每小时 |
| `twitter_keyword` | `*/15 * * * *` | 每 15 分钟 |
| `discord` | `0 */3 * * *` | 每 3 小时 |
| `reddit` | `30 * * * *` | 每小时 30 分 |
| `medium` | `0 */6 * * *` | 每 6 小时 |
| `mirror` | `30 */6 * * *` | 每 6 小时 30 分 |

<!-- collection-cron:end -->

调度器参数：`misfire_grace_time=3600`、`coalesce=True`、`max_instances=1`，
时区 UTC。

> 上一版这张表里 GitHub / CoinGecko 写的是「事件触发（跟随 DefiLlama）」——
> **不是**，它们各有独立 cron。另外上一版列的
> 「Twitter 实时流 webhook/stream」和「链上 webhook 实时」两行：
> Filtered Stream **从未实现**；链上 webhook 有接收端点，
> 但不在采集调度里（见 §2 的 Alchemy 说明）。

### 6.2 分析调度器

| 触发方式 | 真实情况 |
|---|---|
| 定时批量 | ✅ `CRON_EXPRESSION=0 8 * * *`（每日 08:00 UTC），一次最多 `ANALYSIS_RUN_LIMIT=100` 个项目 |
| 手动整批 | ✅ `POST /api/v1/run` |
| 采集完成后自动触发 | ❌ `COLLECTION_AUTO_RUN_ENABLED=false`，两条链解耦 |
| 单项目重跑 | ❌ **`POST /re-score/{id}` 这个接口不存在** |

> **`POST /re-score/{id}` 是幽灵接口。** 46 个真实路由里没有它。
> 鉴权表 `ADMIN_ONLY_PREFIXES` 里有 `/api/v1/re-score` 这个前缀，但它下面没有任何路由 ——
> 于是调用它会命中鉴权中间件先返回 403，而不是 404。**403 比 404 更能骗人**：
> 你会以为"接口在，只是我没权限"，然后去查 token，
> 而真相是这个接口根本不存在。

### 6.3 归档调度器

`ARCHIVE_CRON=0 3 * * *`（每日 03:00 UTC，在采集窗口 08:00–10:30 之前跑完，
避免和写入争锁）。

⚠️ **至今没有观测到一次真实执行**：`archive_runs` 表 0 行，
两张归档表也都是 0 行 —— 本地数据还没有记录超过保留期，
每次触发都"无事可做"。生产上这是一条**未验证路径**。

---

## 7. 采集表 Schema

上一版说「以下表为 v2.0 新增，当前 `DATABASE_DDL.md` **不含**这些表，
需后续同步」。**这件事已经做完了**：`DATABASE_DDL.md` §2.13–2.19
有全部 4 张采集表 + 2 张归档表 + `projects` 扩展字段的完整 DDL。
**以 `DATABASE_DDL.md` 为准，本节只列结构要点，不再重复 DDL。**

<!-- collection-tables:begin -->

| 表 | 实测行数 | 用途 | DDL 位置 |
|---|---|---|---|
| `data_sources` | 5 | 数据源注册表（运维开关 `enabled` 在这里） | `DATABASE_DDL.md §2.13` |
| `raw_projects` | 615 | 采集原始项目池 | `DATABASE_DDL.md §2.14` |
| `project_signals` | 2261 | 项目信号聚合 | `DATABASE_DDL.md §2.15` |
| `collection_logs` | 20 | 采集运行日志 | `DATABASE_DDL.md §2.16` |
| `raw_projects_archive` | 0 | `raw_projects` 归档 | `DATABASE_DDL.md §2.18` |
| `project_signals_archive` | 0 | `project_signals` 归档 | `DATABASE_DDL.md §2.19` |

<!-- collection-tables:end -->

比上一版的设计多出来的真实字段（上一版没有）：

- `raw_projects` 多了 `quarantined` / `quarantine_reason` ——
  隔离机制（`/api/v1/quarantine`）落地后加的。
- `projects` 的 4 个扩展字段都已存在：
  `discovery_source`、`discovered_at`、`auto_discovered`、`signal_count`。

---

## 8. API Key 管理

### 8.1 上一版的「需新增字段」清单已全部落地

上一版把 `GITHUB_TOKEN` / `ETHERSCAN_API_KEY` / `ALCHEMY_API_KEY` /
`ALCHEMY_WEBHOOK_URL` / `COINGECKO_API_KEY` / `GALXE_API_KEY` /
`LAYER3_API_KEY` 列为「计划新增」，并说
「当前 `config.py` 与 `.env.example` 均无上述字段」。

**这些字段现在全部存在**，`config.py` 和 `.env.example` 都有。
（其中 `ALCHEMY_API_KEY` 已于 2026-08-30 重命名为
`ALCHEMY_WEBHOOK_SIGNING_KEY` —— 它本来就只被 webhook 签名校验读取，
却顶着「API key」的名字，见 §8.2。）
配置模板的权威说明见 `.env.example` 本身与 `OPERATIONS.md §9.4`
（那一节记录了模板此前 47 处与代码不符的失真，以及现在钉住它的门禁）。

### 8.2 配了也不生效的键（别浪费时间）

| 键 | 真实情况 |
|---|---|
| `TWITTER_API_KEY` / `TWITTER_API_SECRET` | 采集器不读，只认 `TWITTER_BEARER_TOKEN`。 |
| `ALCHEMY_API_KEY` | **已改名**（2026-08-30）：现在是 `ALCHEMY_WEBHOOK_SIGNING_KEY`，只被 `POST /webhook/alchemy` 的 HMAC 签名校验读取。填 Alchemy 控制台该 webhook 的 **Signing key**，不是 Data APIs 的 API key —— 填错的话合法回调永远 401。 |

> `DUNE_API_KEY` 曾长期列在这张表里（配置字段在、collector 不存在）。
> 2026-09-03 **已彻底删除**该键：`config.py` 的 `dune_enabled` / `dune_api_key`
> 声明、`redact.py` 的脱敏登记、`.env.example` 模板行、`DATABASE_DDL.md` 的
> `data_sources` 种子行全部移除。留着一个"配了也不生效"的键，运维会以为需要去
> 申请这个 Key —— 一张诚实的"无效键清单"只是次优解，把键删掉才是解。
>
> `RATE_LIMIT_*` 三个键也曾列在这里并注明"HTTP 层限流未实现"，**该说法已过时**：
> `app/rate_limit.py` 是真实实现（全局配额 + `/run` 昂贵端点配额 + 429 与
> `Retry-After`），有 `test_review_regressions.py` 的伪造 `X-Forwarded-For`
> 绕过测试守着。

### 8.3 安全实践

- ✅ 所有 Key 存于 `.env`（不提交 git），模板为 `.env.example`
- ✅ 日志与接口输出经 `app/utils/redact.py` 脱敏
- ✅ Prompt Injection 防御（`SECURITY.md §10.1`）：外部数据进 LLM 前隔离
- ❌ **Key 使用量监控告警未实现**：`data_sources.api_calls_today` 字段在，
  但实测 5 个源全是 0，没有告警规则消费它

### 8.4 采集器速率限制（**已实现**，位置和上一版说的不一样）

真实位置 `backend/app/collectors/rate_limiter.py`
（上一版写的 `app/utils/rate_limiter.py` 不存在），
实现是令牌桶 `TokenBucketRateLimiter`，超限抛 `RateLimitExceededError`。

实测默认配置（`requests_per_second` / `burst` / `daily_limit`）：

<!-- rate-limits:begin -->

| source_id | req/s | burst | 日限额 |
|---|---|---|---|
| `defillama` | 2.0 | 5 | 无 |
| `github` | 1.0 | 3 | 无 |
| `cryptorank` | 1.0 | 3 | 无 |
| `rootdata` | 0.8 | 2 | 无 |
| `coingecko` | 0.5 | 2 | **10000** |
| `galxe` | 0.5 | 2 | 无 |
| `layer3` | 0.5 | 2 | 无 |
| `etherscan` | 0.2 | 2 | 无 |
| `twitter` | 0.2 | 1 | 无 |
| `twitter_kol` | 0.2 | 1 | 无 |
| `twitter_keyword` | 0.2 | 1 | 无 |
| `discord` | 0.5 | 2 | 无 |
| `reddit` | 0.5 | 2 | 无 |
| `medium` | 0.5 | 2 | 无 |
| `mirror` | 0.5 | 2 | 无 |

<!-- rate-limits:end -->

未列出的源回落到基准配置 `1.0 req/s` / `burst 5` / 无日限额。
`coingecko` 是唯一设了日限额的源（免费档额度最紧）。

---

## 9. 采集质量与故障降级

### 9.1 真实存在的告警阈值

上一版列了一套 6 维度「采集质量指标」（误报率 / 漏报率 / 信号新鲜度 /
源覆盖率 / 采集稳定性 / 去重准确率），并说每日/每周/每月分别统计。
**实际实现的只有 5 个阈值**，在
`app/collectors/metrics.py` 的 `CollectionMetrics.check_alerts()` 里，
逐源检查、命中就写一条 `collection.alert` 警告日志：

<!-- alert-thresholds:begin -->

| 指标 | 阈值 | 方向 |
|---|---|---|
| `success_rate` | 0.95 | 低于告警（且要求 `total_runs > 0`） |
| `avg_latency_ms` | 30000.0 | 高于告警 |
| `freshness_minutes` | 120.0 | 高于告警 |
| `coverage_rate` | 0.5 | 低于告警 |
| `duplicate_rate` | 0.5 | 高于告警 |

<!-- alert-thresholds:end -->

**上一版承诺但不存在的部分**：

| 上一版说的 | 真实情况 |
|---|---|
| 误报率 / 漏报率 / 去重准确率统计 | ❌ 无任何实现 |
| 「每月输出采集质量报告至 `evaluation/collection/`」 | ❌ **该目录不存在**（只有 `evaluation/llm/`），从未产出过报告 |
| 「人工抽检 50 个项目」流程 | ❌ 从未执行 |

`OPERATIONS.md §8.2` 有同一张阈值表，由门禁与
`check_alerts()` 源码比对。

### 9.2 故障降级：设计与实现的差距

上一版给了一张 4 级（L1 限流 / L2 故障 / L3 停服 / L4 付费超限）
× 7 个源的降级矩阵，还有 4 条全局降级规则。**这是设计意图，不是实现。**

真实实现的降级只有三层，且都是"局部跳过"而不是"全局切换模式"：

| 真实机制 | 在哪里 |
|---|---|
| 单源令牌桶限流，超限抛 `RateLimitExceededError` | `collectors/rate_limiter.py` |
| 单源采集失败记 `collection_logs.status`（`error` / `partial`），不影响其他源 | `collectors/persistence.py` |
| HTTP 层熔断（连续 5 次失败断开 60 秒）+ 缓存 | `utils/fetcher.py`（`FETCHER_CIRCUIT_BREAKER_*`） |

**不存在的**：「降级采集模式」、「维护模式」、
「单日发现 < 5 触发健康检查」这三条全局规则没有任何代码；
`collection_logs.status` 里确实有 `partial` 这个值（实测 `etherscan` 有 3 条），
但它只是单次运行的结果标记，不会触发任何模式切换。

**实测各源运行结果**（`collection_logs` 20 行）：

| source_id | success | partial | error |
|---|---|---|---|
| `defillama` | 3 | 0 | 1 |
| `coingecko` | 2 | 0 | 1 |
| `cryptorank` | 2 | 0 | 1 |
| `github` | 2 | 0 | 1 |
| `etherscan` | 3 | 3 | 1 |

> 每个源都恰好有 1 条 `error`：那是首次接入时的配置调试，不是持续故障。

### 9.3 LLM 成本降级：曾经是假的，2026-08-24 已补成真的

**当时的问题**：上一版说「LLM 付费超限（`LLM_DAILY_BUDGET_USD` 耗尽）→
自动降级为规则引擎」。实测 `LLM_DAILY_BUDGET_USD` **不拦截任何调用**，
也没有任何 token / 成本指标在统计用量。当时真实存在的成本闸门只有两个：

1. `/api/v1/run` 的频率限制（LLM 开启时 1 次/小时，关闭时 10 次/小时）
2. `LLM_DISCOVERY_SCORE_THRESHOLD=0.7`：只有 `discovery_score ≥ 0.7`
   的项目才启用 LLM（ADR-012 分级）

**现在**：预算真的会拦。每次成功调用的估算成本累加到 `llm_spend_daily` 表
（按 UTC 日），下一次调用在**发出任何网络请求之前**查当日累计，
超预算直接拒绝并降级回规则引擎。所以上面那句原始描述现在是准确的，
只是多了一个诚实的边界：它是**软上限**（拦截在调用前、成本在调用后才知道，
最后一次被放行的调用会推过预算线）。

这样一共是**三道闸门，管的是不同的轴**：

| 闸门 | 管什么 | 触发后的现象 |
|---|---|---|
| `/api/v1/run` 频率限制 | 请求**次数** | 429 |
| `LLM_DISCOVERY_SCORE_THRESHOLD` | 哪些项目**值得**走 LLM | 低分项目根本不进 LLM 路径 |
| `LLM_DAILY_BUDGET_USD` | 花了多少**钱** | 降级回规则引擎 + `llm.budget.exceeded` |

**这一节保留下来是因为它记录的失效模式值得警惕**：这个配置**被读了 3 处**，
搜一下像是实现了，比"完全没被读"更能骗过检查。
判据必须落在「有没有人在累计花费」上。见 `OPERATIONS.md §12.3`。

---

## 10. 数据保留策略

以 `DATABASE_DDL.md §6` 与 `.env.example` 为准，这里列实测生效值：

<!-- retention:begin -->

| 表 | 热数据 | 归档 | 归档表保留 | 配置项 |
|---|---|---|---|---|
| `raw_projects`（已立项 `processed=1`） | 30 天 | → `raw_projects_archive` | 180 天后删 | `RAW_PROJECTS_RETENTION_DAYS=30` |
| `raw_projects`（未过阈值 `processed=0`） | 90 天 | → `raw_projects_archive` | 180 天后删 | `UNPROCESSED_RAW_RETENTION_DAYS=90` |
| `project_signals` | 90 天 | → `project_signals_archive` | 365 天后删 | `PROJECT_SIGNALS_RETENTION_DAYS=90` |
| `collection_logs` | 90 天 | 不归档 | — | `COLLECTION_LOGS_RETENTION_DAYS=90` |
| `data_sources` | 永久（配置表） | — | — | — |
| `projects` | 永久 | — | — | — |

<!-- retention:end -->

归档表保留期：`RAW_ARCHIVE_RETENTION_DAYS=180`、
`SIGNALS_ARCHIVE_RETENTION_DAYS=365`（超期直接删除，无下一级归档）。

> **`processed=0` 单独一档的原因**（上一版没有这一档）：
> 未过分析阈值的记录永远不会被标记 `processed=1`，所以不满足
> 「已立项 30 天」那个条件。实测它们占 `raw_projects` 的 **83%**，
> 没有这一档就会无限累积（按当前速率 1 年约 16.8 万行 / 76 MB）。

⚠️ **归档从未真实执行过**（见 §6.3）：两张归档表和 `archive_runs` 全是 0 行。

---

## 11. 还没做的（**别当成能用的功能**）

> **2026-08-24 从这张表里移出一条**：「`LLM_DAILY_BUDGET_USD` 成本拦截 ❌
> 配置项存在但不生效」—— 已实现，见 §9.3。
> 留痕而不是直接删行：**读者分不清"修好了"和"被悄悄拿掉了"**，
> 而这张表的可信度是有限资源，一条假行会让人怀疑其余每一行。
>
> **2026-08-29 再移出一条**：「Discord / Medium / Mirror / Reddit collector ❌
> 无任何代码」—— 四个 P2 源已实现（见 §2 优先级矩阵与 §3 采集器表）。

| 项 | 状态 |
|---|---|
| Twitter Filtered Stream（实时流） | ❌ 未实现（需 Pro Tier） |
| 采集完成自动触发分析 | ❌ `COLLECTION_AUTO_RUN_ENABLED=false` |
| `POST /re-score/{id}` 单项目重跑 | ❌ **接口不存在**（前缀在鉴权表里，会先返回 403 —— 见 §6.2） |
| 误报率 / 漏报率 / 去重准确率统计 | ❌ 无实现 |
| `evaluation/collection/` 采集质量周报 | ❌ 目录不存在 |
| 4 级 × 7 源全局降级矩阵 | ❌ 仅有单源跳过 + HTTP 熔断（§9.2） |
| Key 用量监控告警 | ❌ `api_calls_today` 字段在但恒为 0，无告警消费 |
| 归档任务真实执行 | ⚠️ 逻辑与调度都在，但从未命中保留期 |
| Alchemy Webhook 纳入采集调度 | ⚠️ 端点在，但不在 registry / 不参与调度 |
| Dune collector | ❌ 不存在，且 2026-09-03 起 `DUNE_API_KEY` 配置字段也已删除（见 §8.2） |

---

## 12. 上一版本（v2.0）的失真记录

留着这一节是因为：**这些错误能存活这么久，靠的是"这个文件已经登记为
编码损坏，所以没人读它"**。登记豁免掩盖的不只是字节问题，还有内容问题。
写下来，也让门禁有反向断言的靶子。

### 12.1 10 个采集器路径全错，且全部标着「计划实现位置」

上一版对每个采集器写
`# backend/app/collectors/{source}_collector.py（计划实现位置）`。
真实文件**没有 `_collector` 后缀**，而且类名也不一样
（上一版的 `ChainCollector` / `QuestCollector` / `TwitterCollector`
对应的真实类是 `EtherscanCollector` / `GalxeCollector` + `Layer3Collector` /
`TwitterKolCollector` + `TwitterKeywordCollector`）。

**危害形态**：照文档去找代码，10 个路径 10 个都不存在 ——
读者会以为"采集器还没写"，于是重复实现一遍已经在跑的东西。
正确落点见 §3。

### 12.2 `discovery_score` 的统一公式不存在

上一版给了
`0.4×tvl + 0.3×github + 0.2×twitter + 0.1×chain`。
全仓搜不到 `twitter_score` / `chain_score` 这样的跨源汇总，
每个采集器各算各的（§5.4）。

**危害形态**：这条公式看起来足够具体，会让人以为可以靠调这 4 个权重
统一控制发现质量。真要调，得逐个改 10 个采集器里 10 套不同的算法 ——
而且几个源的上限被刻意压在 0.3 以下（成本设计），
不知道这件事就会误判成"这些源坏了"。

### 12.3 `POST /re-score/{id}` 是幽灵接口

46 个真实路由里没有它。而 `/api/v1/re-score` 前缀在
`ADMIN_ONLY_PREFIXES` 里，所以调用会先撞鉴权中间件返回 **403 而不是 404**。
**403 比 404 更能骗人**：你会以为接口在、只是权限不对，然后去查 token。

### 12.4 「事件触发」的调度关系是假的

上一版说 GitHub / CoinGecko「跟随 DefiLlama 事件触发」，
并说 `raw_projects` 新增记录会「立即触发分析」。
真实情况：每个源独立 cron（§6.1），采集与分析两条链**完全解耦**
（`COLLECTION_AUTO_RUN_ENABLED=false`）。

**危害形态**：以为"采集完就会自动分析"，于是采集跑完不见新评分时
去查分析 Agent 的 bug，而真相是分析调度器要等到自己的 cron 才跑。

### 12.5 速率限制器路径错

上一版写 `backend/app/utils/rate_limiter.py` —— 不存在。
真实位置 `backend/app/collectors/rate_limiter.py`（§8.4）。

### 12.6 「需同步新增」的清单其实早已完成

上一版有大量「（计划新增）」「需后续同步」的字段与表：
7 个 API Key 字段、4 张采集表、`projects` 4 个扩展字段、ADR-012。
**全部已完成**（ADR-012 就是 `docs/adr/ADR-012-system-direction-auto-scan.md`）。

**危害形态**：一份把已完成的事持续标为「待办」的文档，
会让人把时间花在重做上，也会让真正的待办（§11 那张表）失去可信度 ——
读者发现清单不准之后，会连准的部分一起不信。

### 12.7 6 维度采集质量体系与 4 级降级矩阵是设计稿

上一版把它们写得像现状（含具体告警阈值和"每月人工抽检 50 个项目"）。
真实实现见 §9.1 / §9.2：只有 5 个阈值 + 单源跳过 + HTTP 熔断。

### 12.8 保留策略缺了最重要的一档

上一版的保留矩阵只按"表"分档，没有区分
`processed=1` 与 `processed=0`。而实测 **83% 的采集记录永远不会
被标记 `processed=1`** —— 按上一版的规则它们不满足任何归档条件，
会无限累积。真实实现补了 `UNPROCESSED_RAW_RETENTION_DAYS=90` 这一档（§10）。

### 12.9 P2 源被写成「自动采集」

上一版（v2.0，2026-07-09）在优先级矩阵里把 Discord / Medium / Mirror /
Reddit 都填成「自动采集（RSS）」「自动采集（讨论爬取）」，读起来像已接入，
**那时四个源确实一行代码都没有**。到了 2026-08-29 这四个 P2 源才真正落地
（见 §2 矩阵与 §3 采集器表），本条失真记录随之失效但保留在此，
说明「文档写的是计划却读成现状」这类失效有多能骗人。

---

## 13. 关联文档

| 文档 | 关系 |
|---|---|
| `docs/adr/ADR-012-system-direction-auto-scan.md` | 方向反转决策（手动 → 自动扫描） |
| `docs/DATABASE_DDL.md` §2.13–2.19、§6 | 4 张采集表 + 2 张归档表的权威 DDL 与保留策略 |
| `docs/OPERATIONS.md` §4 | 采集运维：源门控规则表（§4.3）、cron（§7.1）、告警阈值（§8.2） |
| `docs/OPERATIONS.md` §9.4 | `.env.example` 的失真记录与门禁 |
| `docs/API_SPEC.md` | 采集相关接口：`/collections/sources`、`/collections/{id}/trigger`、`/discoveries` |
| `docs/SECURITY.md` §10 | 外部数据进 LLM 前的隔离要求 |
| `.env.example` | 全部采集配置的权威模板 |

---

_本文档所有数字、路径、类名、公式、cron、阈值均于 2026-08-23 实测取得；
由 `backend/tests/test_data_source_strategy_parity.py` 双向门禁钉住。_
