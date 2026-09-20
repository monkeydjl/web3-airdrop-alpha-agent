# 数据与评分字典

> 配套文档：ENGINEERING_ROADMAP.md §5、§6、§7。本文档是字段含义与评分算法的**权威说明**，供后端实现、前端展示与测试断言统一参考。

---

## Opportunity v2 FARM gates

- `official_identity` is tri-state: verified `true` is known, verified `false` produces `SAFETY_BLOCK`, and missing/unresolved evidence remains `WATCH`.
- FARM requires `hard_cost_usd.high <= 10`; a high envelope above 10 is `WATCH/WAIT_COST_DROP`, while `low > 10` is structural `IGNORE/TOO_EXPENSIVE`.
- FARM requires all five risk dimensions: capital security, eligibility, project failure, reward dilution, and liquidity.
- `capital_at_risk_usd` requires direct evidence even when explicitly zero. Missing exposure is a critical unknown and never defaults to zero.

### 判定顺序（v2.0，ADR-014）

已确知不符合画像的硬约束（`hard_cost_usd.low` 超上限、已确认的最小维护工时超上限）
**先于**"证据不足"判定，但仍**后于** `SAFETY_BLOCK` / `INTEGRITY_BLOCK` / `RULE_BLOCK`。
原因：成本超预算会让资格概率无法派生，进而把 `reward_probability` 计入 `critical_unknowns`，
若先判证据不足，用户会被告知"去补证据"，而真实原因是"太贵了"，且 `TOO_EXPENSIVE`
在真实链路上永不可达（270 项语料双跑中旧引擎产出 `NOT_FIT` 的数量为 0）。

**"已确知"必须带来源等级门槛**：`resolve_factor` 不设来源等级下限，一条 `U` 档
（权重 0）的 `assumed` 成本记录也能填满 `hard_cost_usd`。因此该判定要求
`hard_cost_confirmed_minimum` —— `observation_type ∈ {observed, derived}` 且
来源等级 ≥ B，与 `_derive_eligibility` 对成本的门槛、以及
`weekly_time_confirmed_minimum` 对工时的门槛完全一致。达不到这一档的成本证据
仍走"证据不足"（复核期 7 天），而不是 `IGNORE`（复核期 30 天）。

### 联合概率区间（v2.0，ADR-014）

三因子（event / eligibility / survival）在**独立性假设**下合成：

```
base     = event.base × eligibility.base × survival.base
rel_low  = sqrt( Σ ((base_i − low_i)  / base_i)² )
rel_high = sqrt( Σ ((high_i − base_i) / base_i)² )
low      = clamp(base × (1 − rel_low),  Π low_i,  base)      # 下界不得低于逐分位连乘
high     = clamp(base × (1 + rel_high), base,     Π high_i)  # 上界不得高于逐分位连乘
```

端点**不得**逐分位连乘（`low×low×low`）：那只在三因子完全同向时成立，与 `base` 依赖的
独立性假设不可能同时为真，且会让「官方分发 + 积分制资格 + 未禁止多钱包」这一档的
`joint.low` 恒为 0.1650，永远跨不过 FARM 门槛 `reward_probability.low >= 0.20`。

但逐分位连乘的结果仍作为**兜底端点**：它是完全同向假设下的区间，在独立性假设下必然更宽，
因此可安全用作下界的地板与上界的天花板。缺了这层兜底，当某因子 `low = 0` 导致相对不确定度
之和超过 100% 时，`base × (1 − rel_low)` 会变成负数并被夹到 0——比连乘还悲观，
与"只收紧不放宽"的前提自相矛盾。0.1 网格上穷举 2334 万组三元组验证：0 违例。

任一因子 `base = 0` 时联合期望为 0，但端点保留连乘值 `(Π low_i, 0, Π high_i)`。
`base = 0` 只说明"最可能不发生"，不代表乐观端也是 0；强行把 `high` 归零会让
`gross_reward.high` 随之为 0，经 `DUST_REWARD` 门槛把项目误判成 30 天 `IGNORE`。
`survival = forbidden`（0/0/0）时 `Π high_i = 0`，仍正确退化为点 `(0, 0, 0)`。

### 证据新鲜度阶梯（v2.0，ADR-014）

| 证据年龄 | freshness |
| --- | --- |
| ≤ 7 天 | 1.0 |
| ≤ 30 天 | 0.8 |
| ≤ 90 天 | 0.5 |
| ≤ 180 天 | 0.2 |
| ≤ 365 天 | 0.1 |
| > 365 天 | 0.05 |

前四档为原有值，v2.0 只**延长尾部**（此前 >90 天一律 0.2 且永不再降，5 年前的证据与
半年前等价）。任何年龄的 freshness 都 ≤ 原值，该阶梯只收紧、不放宽任何结论。

---

## 1. `projects` 表字段字典

| 字段 | 类型 | 含义 | 来源 Agent | 示例 |
| --- | --- | --- | --- | --- |
| `id` | TEXT PK | 项目唯一标识（uuid） | Collector | `a1b2c3d4` |
| `name` | TEXT | 项目名称 | Collector | `LayerX` |
| `url` | TEXT | 官网地址 | Collector | `https://layerx.xyz` |
| `sector` | TEXT | 赛道（L2/Restaking/DeFi…） | Collector | `L2` |
| `stage` | TEXT | 阶段：`testnet`/`mainnet`/`ideation` | Collector | `testnet` |
| `score` | INT | 综合评分 0–100 | Scorer | `83` |
| `label` | TEXT | `FARM`/`WATCH`/`IGNORE` | Scorer | `FARM` |
| `recommendation` | TEXT | 参与建议（同 label） | Scorer | `FARM` |
| `confidence` | REAL | 数据完整度 0–1（非缺失分析 agent 数 / 4） | Scorer | `1.0` |
| `reason` | TEXT(JSON) | 决策理由数组 | Scorer | `["early narrative","strong airdrop signal"]` |
| `narrative_json` | TEXT(JSON) | NarrativeResult | Narrative | `{"sector":"L2","stage":"growth","heat_score":0.82,"timing":"early"}` |
| `team_json` | TEXT(JSON) | TeamResult | Team | `{"score":0.72,"risk_level":"medium","flags":["previous failed project"]}` |
| `risk_json` | TEXT(JSON) | RiskResult | Risk | `{"sybil_difficulty":"high","farming_cost":"medium","token_risk":0.68}` |
| `tokenomics_json` | TEXT(JSON) | TokenomicsResult | Tokenomics | `{"vc_share":0.25,"team_share":0.2,"unlock_pressure":"high","risk":0.75}` |
| `source` | TEXT | 数据来源 | Collector | `seed` / `defillama` / `cryptorank` |
| `created_at` | TS | 首次写入时间（UTC） | DB | `2026-07-08 08:00:12` |
| `updated_at` | TS | 末次更新时间（UTC） | DB | `2026-07-08 09:10:00` |

---

## 2. `logs` 表字段字典

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `id` | INT PK | 自增 |
| `project_id` | TEXT | 关联项目（可为空，表示全局事件） |
| `agent_name` | TEXT | 产生该日志的 Agent 名 |
| `input` | TEXT(JSON) | Agent 输入上下文 |
| `output` | TEXT(JSON) | Agent 输出结果 |
| `error` | TEXT(JSON) | Agent 错误信息（AgentError），成功时为 NULL |
| `duration_ms` | INT | 执行耗时（毫秒） |
| `timestamp` | TS | 写入时间 |

> 用途：可解释性追溯、调试、V3 memory 系统回流。

---

## 3. Agent 输出字段字典

### 3.1 NarrativeResult（赛道周期）
| 字段 | 类型 | 取值 | 含义 |
| --- | --- | --- | --- |
| `sector` | str | 赛道名 | 对应项目赛道 |
| `stage` | str | `early`/`growth`/`peak`/`mature` | 生命周期阶段（注意：映射到 `timing` 时 growth→early, mature→late） |
| `heat_score` | float | 0–1 | 叙事热度 |
| `timing` | str | `early`/`peak`/`late` | 当前时点（早/峰/晚） |

### 3.2 TeamResult（团队信誉）
| 字段 | 类型 | 取值 | 含义 |
| --- | --- | --- | --- |
| `score` | float | 0–1 | 信誉分（高=可信） |
| `risk_level` | str | `low`/`medium`/`high` | 风险等级 |
| `flags` | list[str] | 见下 | 风险标签 |

常见 `flags`：`anonymous team`、`previous failed project`、`wash-trading VC`、`doxxed team`、`tier-1 vc backed`。

### 3.3 RiskResult（风险模型）
| 字段 | 类型 | 取值 | 含义 |
| --- | --- | --- | --- |
| `sybil_difficulty` | str | `low`/`medium`/`high` | 女巫攻击（批量刷号）难度 |
| `farming_cost` | str | `low`/`medium`/`high` | 参与空投成本（gas+时间） |
| `token_risk` | float | 0–1 | 代币结构风险（高=危险） |

### 3.4 TokenomicsResult（代币经济）
| 字段 | 类型 | 取值 | 含义 |
| --- | --- | --- | --- |
| `vc_share` | float | 0–1 | VC 占比 |
| `team_share` | float | 0–1 | 团队占比 |
| `unlock_pressure` | str | `low`/`medium`/`high` | 解锁抛压 |
| `risk` | float | 0–1 | 综合代币风险（高=危险） |

### 3.5 ScoreResult（核心决策）
| 字段 | 类型 | 取值 | 含义 |
| --- | --- | --- | --- |
| `score` | int | 0–100 | 综合评分 |
| `label` | str | `FARM`/`WATCH`/`IGNORE` | 分级 |
| `recommendation` | str | 同 label | 建议 |
| `confidence` | float | 0–1 | **证据完整度**（v1.3）：0.35×Agent 覆盖 + 0.65×可验证信号（官网/文档/仓库/社媒/任务入口/合约·TVL/多源） |
| `weight_version` | str | — | 评分权重版本（默认 "v1"，ADR-006） |
| `reason` | list[str] | — | 决策理由（≥2 条） |

---

## 4. 评分权重表（v1.2，八维）

| 子项 | 权重 | 来源 / 含义 |
| --- | --- | --- |
| `airdrop_signal` | 0.18 | 未发币 / 积分 / 测试网 / **明确空投表述** |
| `narrative_timing` | 0.15 | Narrative 叙事时机 |
| `team_reputation` | 0.12 | Team 团队信誉 |
| `risk` | 0.12 | Risk 风险 |
| `tokenomics` | 0.10 | Tokenomics 代币结构 |
| `competition` | 0.10 | 同赛道拥挤度 |
| `execution` | 0.13 | **GitHub 活跃 / 路线图 / TVL 推进** |
| `transparency` | 0.10 | **白皮书·文档 / Twitter·Discord / 官网** |

> v1 曾为六维（0.20/0.20/0.15×4）。v1.2 增加执行力与透明度，避免「只看是否未发币」过于片面。

| 子项（历史 v1） | 权重 | 来源 Agent |
| --- | --- | --- |
| `airdrop_signal` | 0.20 | Collector（`raw_signals`） |
| `narrative_timing` | 0.20 | Narrative |
| `team_reputation` | 0.15 | Team |
| `risk` | 0.15 | Risk |
| `tokenomics` | 0.15 | Tokenomics |
| `competition` | 0.15 | Orchestrator（同 sector 计数） |

---

## 5. 子分映射公式（均归一到 0–100）

### 5.1 airdrop_signal（18%，v1.2）

> v1.2：`airdrop_hint` 以 `no_token_yet` 为主；纳入 `has_testnet`；**明确空投表述** `explicit_airdrop_mention` +12；近期融资 +5（有空投相关信号时）。

| 条件 | 子分 |
| --- | --- |
| `has_points` 且 `no_token_yet` | 100（封顶） |
| `no_token_yet` 且 `has_testnet` | 85 |
| 仅 `has_points` 或仅 `no_token_yet` | 60 |
| 仅 `has_testnet` | 40 |
| 均为否 | 20 |
| + 明确空投表述 | +12 |
| + 近期融资（且存在空投相关信号） | +5 |
| 已上市且无积分/无明确空投 | 最高约 35 |

### 5.1b execution（13%，v1.2 新增）

| 信号 | 加分（约） |
| --- | --- |
| 有 GitHub | +12 |
| stars 档位（50/200/1000） | +4～+18 |
| 近 14/45/90 天有更新 | +18 / +12 / +6；>180 天 −10 |
| 公开路线图 | +10 |
| 测试网 | +8 |
| TVL 档位 | +4～+12 |

### 5.1c transparency（10%，v1.2/v1.3）

| 信号 | 加分（约） |
| --- | --- |
| 白皮书 | +18（仅文档 +12） |
| 路线图 | +8 |
| Twitter / Discord | +10 / +8 |
| GitHub / 官网 | +8 / +6 |
| 任务入口 | +6 |
| 多源 ≥2 / ≥3 | +6 / +12 |
| 实名团队 | +6；匿名且无文档 −12 |

### 5.1d 空投可验证路径（并入 airdrop_signal，v1.3）

| 信号 | 加分 |
| --- | --- |
| `has_task_portal`（Galxe/Layer3/Quest 等） | +14 |
| `explicit_airdrop_mention` | +10 |
| `source_count` ≥2 / ≥3（且有空投相关信号） | +3 / +6 |

### 5.1e 路线图履约（并入 execution，v1.3）

| `roadmap_delivery` | 效应 |
| --- | --- |
| `aligned` | +16（路线图 + 测试网/TVL/近期提交） |
| `partial` | +8 |
| `unclear` | −8（纸面路线图、无交付） |
| `has_contract` | +10 |

### 5.1f 融资质量（v1.4，RootData / 结构化字段）

| 字段 | 含义 |
| --- | --- |
| `funding_total_usd` | 累计融资金额 |
| `funding_rounds` | 轮次数 |
| `funding_investors` / `funding_lead_investors` | 投资方 |
| `funding_tier` | `tier1` / `tier2` / `tier3` / `unknown` / `none` |
| `funding_quality` | 0–1 综合（金额 + 轮次 + 投资方档位 + 新近度） |

计入：`team_reputation`（blend）、`airdrop_signal`（高质量融资加成）、`transparency`；Team flags：`tier-1 vc backed` / `reputable vc backed`。

数据源：RootData 采集器（需 API key）或 raw 手动字段。

### 5.2 narrative_timing（20%）
```
base      = heat_score * 100
coeff     = {early:1.0, peak:0.8, late:0.5}[timing]
subscore  = base * coeff
```

> **stage → timing 映射表**（NarrativeResult 内部 `stage` 字段为细粒度，映射到 `timing` 供评分使用）：
>
> | NarrativeResult.stage | → timing | 时点系数 | 含义 |
> | --- | --- | --- | --- |
> | `early` | `early` | 1.0 | 早期，红利窗口最佳 |
> | `growth` | `early` | 1.0 | 上升期，仍属早期红利 |
> | `peak` | `peak` | 0.8 | 过热，红利递减 |
> | `mature` | `late` | 0.5 | 晚期/成熟，参与价值低 |
>
> 详见 GLOSSARY `stage` 术语说明。

### 5.3 team_reputation（15%）
```
subscore = team.score * 100
risk_level 映射: score<0.4→high, 0.4–0.7→medium, >0.7→low
```

### 5.4 risk（15%）
```
sybil_factor = {high:1.0, medium:0.85, low:0.70}[sybil_difficulty]
subscore     = (1 - token_risk) * 100 * sybil_factor
```
> `token_risk` 由 Risk Agent 综合 Tokenomics 产出（见 §3.3）。

### 5.5 tokenomics（15%）
```
subscore = (1 - tokenomics.risk) * 100
```

### 5.6 competition（15%）
基于同 `sector` 项目数 `n`：
```
n <= 3      -> 100
4  <= n <= 8  -> 75
9  <= n <= 15 -> 55
n  > 15      -> 40
```
（平滑备选：`max(40, 100 - (n-1)*8)`）

> **分组口径：按规范键，不按 `sector` 原始写法**（2026-09-02 修复，见
> ADR-015 §「不解决什么」第 4 条）。同一逻辑赛道在真实采集里有多种写法
> （DefiLlama `"Dexes"` / CryptoRank `"DEX"` / github 推断 `"dex"` /
> 衍生品所 `"Derivatives"`），按原始写法分组会把一个赛道拆成多组、每组计数
> 偏小，`n <= 3` 命中率虚高 → **系统性偏乐观**。
>
> 分组用 `narrative.canonical_sector_key()`，与 `resolve_sector_profile()`
> 共用别名表。`_calculate_sector_counts()`（计数侧）与 `_calc_competition()`
> （查表侧）**必须同口径** —— 不一致会全部 miss 后静默退到中性 50。
>
> 未知赛道各自独立成组（返回 trim 后原值，不塌成 `None`），否则 `RWA` 与
> `SocialFi` 会互相算成竞品。全库计数走 `repository.canonical_sector_counts()`
> （一次 `GROUP BY` + Python 侧折叠），**不能**用 `WHERE sector = ?` 精确匹配。
>
> `sector` 本身**不被改写** —— 它参与 `generate_deterministic_id()`。

> **性能优化**：competition 子分使用缓存计数而非每次实时 `COUNT(*)`，详见 [ENGINEERING_ROADMAP.md §7.5.1](ENGINEERING_ROADMAP.md)。
> - MVP：直接 `COUNT(*)`（项目数 ≤1k）。
> - V2：进程内 LRU 缓存（写时失效，TTL 300s）或 DB `sector_counts` 物化表（PG trigger 增量更新）。
> - V3：Redis 原子计数器。
> - 缓存与 DB 不一致窗口 ≤ TTL（默认 5min），且偏差不超过 ±1。

---

## 5.7 子项内部映射细节（MVP 规则初值）

以下数值映射在 W2 实现前必须确定；当前为推荐初值，后续可通过 ADR 调整。

### 5.7.1 Tokenomics `unlock_pressure` → `unlock_penalty`

| `unlock_pressure` | `unlock_penalty` |
| --- | --- |
| `low` | 0.15 |
| `medium` | 0.35 |
| `high` | 0.65 |

Tokenomics Agent 输出的 `risk = vc_share × 0.4 + team_share × 0.3 + unlock_penalty × 0.3`。

### 5.7.2 Risk `token_risk` 启发式（MVP）

MVP 无真实链上数据时，Risk Agent 按以下启发式估算 `token_risk`：

```
token_risk = 0.6 × tokenomics.risk
           + 0.2 × (1 - airdrop_signal_subscore / 100)
           + 0.2 × stage_factor

stage_factor = { mainnet: 0.15, testnet: 0.35, ideation: 0.55 }[project.stage]
```

> 若 Tokenomics 数据缺失，则 `tokenomics.risk` 取 0.5（中风险），并标记 `"risk estimate uncertain"`。

### 5.7.3 Team 多 flag 叠加

```
base = 0.5
adjustments = {
    "anonymous team":          -0.25,
    "previous failed project": -0.30,
    "tier-1 vc backed":        +0.25,
}
team.score = clamp(base + sum(adjustments[flag] for flag in flags), 0.0, 1.0)
```

`team.risk_level` 由 `team.score` 推导：
- `score < 0.4` → `high`
- `0.4 ≤ score ≤ 0.7` → `medium`
- `score > 0.7` → `low`

### 5.7.4 Narrative `SECTOR_PROFILE`（MVP 内嵌词表）

MVP 用 `config.SECTOR_PROFILE` 维护赛道基础热度与动量；V2 迁移到 `narratives` 表。初值如下：

| sector | base_heat | momentum |
| --- | --- | --- |
| L2 | 0.75 | +0.05 |
| Restaking | 0.70 | +0.08 |
| DeFi | 0.60 | -0.02 |
| GameFi | 0.50 | -0.05 |
| NewSector（兜底） | 0.50 | 0.00 |

`heat_score = clamp(base_heat + momentum × recency_factor, 0.0, 1.0)`，其中 `recency_factor` 由该赛道近期新增项目数/外部讨论量估算（V2 引入真实数据源后可动态调整）。

### 5.8 跨源合并语义（v1.4，ADR-014）

`DATA_QUALITY.md §128` 规定"同字段多源冲突 → 取 reliability 最高源"，但未规定**不冲突时**如何处理。
早期实现按来源优先级整条择一，把落选来源的全部字段一并丢弃，导致"多发现一个来源、分数反而下降"。

关键前提：抵达 `merge_raw_records` 的是**已归一化的整行**，缺失布尔一律填 `False`、缺失计数一律填 `0`。
因此对爬取类来源，`False` / `0` 的含义是"**这个源没看到**"，不是"这个源核实了它不存在"——
"我没看到"与"我看到了"之间不构成 §128 意义上的冲突。据此分两类：

| 字段类 | 合并策略 | 字段 |
| --- | --- | --- |
| 存在性布尔 | 全源 **OR**（任一源观测到即为真） | `has_testnet`、`has_points_program`、`no_token_yet`、`recent_funding`、`has_docs`、`has_whitepaper`、`has_roadmap`、`has_github`、`has_twitter`、`has_discord`、`explicit_airdrop_mention`、`has_task_portal`、`has_contract` |
| 规模型数值 | 全源 **max** | `github_stars`、`tvl_usd`、`funding_total_usd`、`funding_rounds`、`funding_quality` |
| "距今天数"型数值 | 全源 **min**（越小越新） | `github_recent_push_days` |
| 列表 | 全源**并集** | `funding_investors`、`funding_lead_investors` |
| 标量 | 取**最高可信来源中的已知值**（取值本身即断言，冲突是真冲突，严格按 §128）；`unknown` / 空串 / `None` / 空容器不覆盖已知值 | `url`、`sector`、`stage`、`description`、`funding_tier`、`funding_last_date`、`roadmap_delivery`、`sybil_friction` |

**否定断言的例外**：`manual` 与 `api` 是刻意输入而非抓取产物，其 `False` / `0` 是真实断言，
一旦对某字段给出显式取值即直接采信，不参与 OR / max。否则一条 twitter 噪声就能把人工确认的
"已发币"翻回 `no_token_yet=True`，把 `airdrop_signal` 从 20 顶到 100。

`source_count = max(1, 参与合并的来源数, 记录中已有值)`。此前恒为 1，使 §166/§175 的多源加成永不生效、
`DATA_QUALITY.md §141` 的"≥2 源覆盖率 ≥30%"周 KPI 无法测量。

合并结果与输入顺序**无关**：排序键为（来源优先级, 来源名, 记录内容规范序）。仅按优先级排序时，
同档来源（`github`/`rootdata` 同为 5，`cryptorank`/`galxe`/`layer3`/`etherscan` 同为 6）的胜出者
取决于上游 `ORDER BY discovery_score DESC, discovered_at DESC` 的偶然顺序。

来源可信度顺序见 `utils/normalize.SOURCE_PRIORITY`（`galxe`/`layer3`/`etherscan` 于 v1.4 补入）。

### 5.9 评分输出的持久化列（v1.4，ADR-014）

| 列 | 内容 | 写入方 |
| --- | --- | --- |
| `weight_version` | 生效权重版本（`WEIGHT_CALIBRATION §1.2`） | Scorer |
| `sub_scores` | 八维子分快照（`WEIGHT_CALIBRATION §4.3` 步骤 1 的离线重加权所需） | Scorer |
| `raw_signals` | 采集到的**输入**信号 | 采集/seed |
| `raw_signals_hash` | 上列的哈希 | 采集/seed |

`sub_scores` 为独立列，不复用 `raw_signals`：后者是输入、前者是输出，形状不兼容。
两列在 UPSERT 中以 `COALESCE(EXCLUDED.x, projects.x)` 写入——Scorer 失败时二者为空，
不得用空壳覆盖上一次成功评分的快照。

---

## 6. 总分计算
```
score = round( Σ subscore_i * weight_i )   # 截断到 [0,100]
```

## 6.1 confidence 计算（v1.3 口径，与 §3.5 一致）
```
agent_coverage  = 非缺失分析 agent 数 / 4          # Narrative / Team / Risk / Tokenomics
signal_coverage = 已验证信号数 / 可验证信号总数    # 官网·文档·仓库·社媒·任务入口·合约/TVL·多源
confidence      = 0.35 × agent_coverage + 0.65 × signal_coverage
```
> **无下限。** 早期实现在 Agent 覆盖率满时给结果加了 0.55 的地板。影响面要说准：
> Agent 缺失时旧公式仍可能 < 0.5（缺 1–3 个 Agent 的下限依次为 0.45 / 0.20 / 0.10），
> 但那是异常路径；**四个 Agent 全部成功的正常路径**下 confidence 恒 ≥ 0.55
> （穷举 256 种信号配置最低值恰为 0.5500）。结果是降档保护只在 Agent 崩溃时生效，
> 而它本意是防"可验证信号不足"——两者管的不是同一件事。
> ADR-014 移除该地板；语料双跑显示 confidence 下限由 0.5500 回落到 0.4429，
> 信号稀疏的项目首次可触发降档。
>
> `confidence < 0.5` 时 label 强制降一档（`ENGINEERING_ROADMAP.md` §7.6 降级覆盖率上限）。
> 前端可用置信度环/图标展示，辅助用户判断评分可信度。
>
> 旧口径 `confidence = 非缺失分析 agent 数 / 4`（v1.2 及以前）已废弃，仅作历史参考。

## 7. Label 阈值
| 区间 | label / recommendation |
| --- | --- |
| `score >= 65` | `FARM`（v1.1） |
| `50 <= score < 65` | `WATCH` |
| `score < 50` | `IGNORE` |

---

## 8. reason 生成规则

### 8.1 候选 reason 字符串

每个子项在满足条件时生成一条候选 reason：

| 子项 | 条件 | 候选 reason（精确字符串） |
| --- | --- | --- |
| `airdrop_signal` | 子分 = 100 | `"strong airdrop signal"` |
| `airdrop_signal` | 子分 = 60 | `"moderate airdrop signal"` |
| `airdrop_signal` | 子分 = 20 | `"no airdrop signal"` |
| `narrative_timing` | `timing=early` 且子分 ≥ 70 | `"early narrative, high heat"` |
| `narrative_timing` | `timing=early` 且子分 < 70 | `"early narrative"` |
| `narrative_timing` | `timing=peak` 且子分 ≥ 70 | `"heated narrative, peak timing"` |
| `narrative_timing` | `timing=peak` 且子分 < 70 | `"peak narrative"` |
| `narrative_timing` | `timing=late` 且子分 ≥ 70 | `"mature narrative, late timing"` |
| `narrative_timing` | `timing=late` 且子分 < 70 | `"late narrative"` |
| `team_reputation` | `team.score ≥ 70` | `"credible team"` |
| `team_reputation` | `team.risk_level = high` | `"team risk: anonymous or prior failure"` |
| `risk` | `risk.token_risk > 0.6` | `"elevated token structure risk"` |
| `tokenomics` | `tokenomics.risk > 0.6` | `"high token unlock pressure"` |
| `competition` | `n ≤ 3` | `"low competition"` |
| `competition` | `n > 15` | `"high competition"` |
| 缺失 | `narrative_json` 缺失/降级 | `"narrative heat unknown"` |
| 缺失 | `team_json` 缺失/降级 | `"team data missing"` |
| 缺失 | `risk.token_risk` 缺失 | `"risk estimate uncertain"` |
| 缺失 | `tokenomics_json` 缺失/降级 | `"tokenomics data missing"` |
| 低置信度 | ≥3 个分析 agent 缺失/降级 | `"low data confidence"` |

> **注意**：`team.risk_level` 由 `team.score` 推导（见 `DATA_SCORING_DICT.md §5.3`），而非直接信任输入字段；golden 用例中若 score 与 risk_level 不一致，以 score 推导为准。

### 8.2 选择算法

1. 对每个子项计算 `impact = |subscore - 50|`，表示该子项偏离中性的程度。
2. 所有缺失标记（`"... data missing"`）和 `"low data confidence"` 为**强制出现**，必须包含在最终 reason 列表中。
3. 其余候选 reason 按 `impact` 降序、同 `impact` 时按 `§8.1` 表格中的优先级（靠上优先）排序。
4. 在强制标记之外，按排序选取前 3 条正向/反向 reason；若候选不足 3 条，则全部选取。
5. 校验约束：
   - **FARM** 项目最终列表必须至少含 1 条正向 reason；
   - **IGNORE** 项目最终列表必须至少含 1 条反向 reason；
   - 若不满足，用排序中最高优先级的正向/反向候选替换最后一条非强制 reason。
6. 最终 `reason` 列表长度 ≥ 2。缺失/降级场景下长度可能超过 3，此时前端默认展示前 3 条，其余折叠。

### 8.3 与缺失降级的衔接

缺失字段产生的标记（如 `"tokenomics data missing"`）和 `"low data confidence"` 不受 `impact` 排序影响，必须出现。例如：

- `tokenomics_json` 缺失时，即使其他子项全部是正向，reason 也必须包含 `"tokenomics data missing"`。
- ≥3 个分析 agent 缺失/降级时，必须追加 `"low data confidence"`。

这保证了可解释性：用户能直接看到哪些数据缺失导致评分被降级。

---

## 9. 缺失字段降级策略（对齐 `ENGINEERING_ROADMAP.md` §7.6)

外部源常缺 tokenomics/team 数据，评分必须能优雅降级：

| 缺失字段 | 降级子分 | 影响 | reason 标记 |
| --- | --- | --- | --- |
| `tokenomics_json` | tokenomics 子分 = 50（中性） | 仅该子项失真 | `"tokenomics data missing"` |
| `team_json` | team 子分 = 50（中性） | 仅该子项失真 | `"team data missing"` |
| `risk.token_risk` | token_risk = 0.5（中风险） | risk 子分走中性 | `"risk estimate uncertain"` |
| `narrative.heat_score` | heat_score = 0.5，timing=`early` | narrative 子分中性 | `"narrative heat unknown"` |
| `raw_signals` 全空 | airdrop_signal = 20 | 显著拉低总分 | `"no airdrop signal"` |

**降级覆盖率上限**：若 4 个分析 agent 中 ≥3 个为缺失/降级，则该项目 `label` 强制降一档（FARM→WATCH，WATCH→IGNORE），并在 reason 追加 `"low data confidence"`。

**缺失计数**写入 `meta.missing_count`，供 Dashboard 标灰与可解释性展示。

---

## 10. 平滑与归一化（对齐 `ENGINEERING_ROADMAP.md` §7.7)

- 子分计算后统一 `clamp(x, 0, 100)`，避免浮点误差越界。
- 总分 `round()` 采用 **round-half-to-even**（Python 默认银行家舍入），保证大量样本下无系统性偏差。
- **不做**子分曲线压缩（如 sigmoid）——保持线性可解释性。

---

## 11. 排序 tie-break（对齐 `ENGINEERING_ROADMAP.md` §7.8)

`GET /projects` 默认按 `score DESC`，同分时依次按：
1. `airdrop_signal` 子分（高优先，空投信号强者优先）
2. `narrative.heat_score`（热度高优先）
3. `confidence`（数据完整者优先，高者优先；等价于 `meta.missing_count` 升序）
4. `name` 升序（稳定字典序兜底）

排序在 SQL 层完成（`ORDER BY score DESC, confidence DESC, name ASC LIMIT`）；`airdrop_signal` 子分与 `heat_score` 存于 JSON 列，如需在 SQL 层参与 tie-break 1–2，推荐在 `projects` 表冗余 `airdrop_signal_subscore REAL` 列（见 `ENGINEERING_ROADMAP.md` §7.8）。

---

## 12. 完整示例计算（LayerX）

输入（来自 Agents）：
- `raw_signals = {has_points:true, airdrop_hint:true}`
- `Narrative = {heat_score:0.82, timing:"early"}`
- `Team = {score:0.72}`
- `Risk = {token_risk:0.68, sybil_difficulty:"high"}`
- `Tokenomics = {risk:0.75}`
- 同 sector（L2）项目数 `n = 4`

| 子项 | 计算 | 子分 | 权重 | 贡献 |
| --- | --- | --- | --- | --- |
| airdrop_signal | 双真 | 100 | 0.20 | 20.0 |
| narrative_timing | 0.82×100×1.0 | 82 | 0.20 | 16.4 |
| team_reputation | 0.72×100 | 72 | 0.15 | 10.8 |
| risk | (1−0.68)×100×1.0 | 32 | 0.15 | 4.8 |
| tokenomics | (1−0.75)×100 | 25 | 0.15 | 3.75 |
| competition | n=4 → 75 | 75 | 0.15 | 11.25 |

```
score = round(20.0+16.4+10.8+4.8+3.75+11.25) = round(67.0) = 67
label = WATCH  (50 <= 67 < 70)
reason = ["strong airdrop signal", "early narrative, high heat", "high token unlock pressure"]
```

> 说明：尽管叙事与空投信号强，但 token 结构与风险子分偏低，综合落入 WATCH。该结果体现了"多维加权、不可被单维误导"的设计意图。
