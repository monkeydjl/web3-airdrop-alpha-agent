# 数据与评分字典

> 配套文档：ENGINEERING_ROADMAP.md §5、§6、§7。本文档是字段含义与评分算法的**权威说明**，供后端实现、前端展示与测试断言统一参考。

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
| `confidence` | float | 0–1 | 数据完整度（非缺失分析 agent 数 / 4） |
| `weight_version` | str | — | 评分权重版本（默认 "v1"，ADR-006） |
| `reason` | list[str] | — | 决策理由（≥2 条） |

---

## 4. 评分权重表

| 子项 | 权重 | 来源 Agent |
| --- | --- | --- |
| `airdrop_signal` | 0.20 | Collector（`raw_signals`） |
| `narrative_timing` | 0.20 | Narrative |
| `team_reputation` | 0.15 | Team |
| `risk` | 0.15 | Risk |
| `tokenomics` | 0.15 | Tokenomics |
| `competition` | 0.15 | Orchestrator（同 sector 计数） |

---

## 5. 子分映射公式（均归一到 0–100）

### 5.1 airdrop_signal（20%）
| 条件 | 子分 |
| --- | --- |
| `has_points` 且 `airdrop_hint` | 100 |
| 仅其一为真 | 60 |
| 均为否 | 20 |

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

---

## 6. 总分计算
```
score = round( Σ subscore_i * weight_i )   # 截断到 [0,100]
```

## 6.1 confidence 计算
```
confidence = 非缺失分析 agent 数 / 4
```
> 4 个分析 agent（Narrative/Team/Risk/Tokenomics）中成功产出结果的比例。
> `confidence < 0.5`（≥3 个缺失）时 label 强制降一档（已在 `ENGINEERING_ROADMAP.md` §7.6 降级覆盖率上限实现）。
> 前端可用置信度环/图标展示，辅助用户判断评分可信度。

## 7. Label 阈值
| 区间 | label / recommendation |
| --- | --- |
| `score >= 70` | `FARM` |
| `50 <= score < 70` | `WATCH` |
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
