# 数据质量规范

> 配套文档：`ENGINEERING_ROADMAP.md` §22、`ENGINEERING_ROADMAP.md` §7.6、`ENGINEERING_ROADMAP.md` §10。本文档定义数据质量的维度、指标、检测规则、修复流程与 SLA，供数据/后端/运维统一对齐。
>
> 核心目标：**保证评分可信**。评分依赖多源外部数据，任何质量退化都会直接污染评分输出；本规范把"数据好坏"从模糊判断变成可度量、可告警、可修复的工程问题。

---

## 1. 设计原则

1. **质量是评分的前提**：数据不可信时宁可降级（`ENGINEERING_ROADMAP.md` §7.6）也不输出虚高分。
2. **可度量**：每个维度有明确指标，进 Prometheus（OBSERVABILITY §3.2）。
3. **可追溯**：脏数据进 `quarantine` 表，不静默丢弃。
4. **可修复**：每类质量问题有明确处置流程与责任人。
5. **分级治理**：核心字段严控（100% 完整性），辅助字段宽松（80% 即可）。

---

## 2. 数据质量维度（6 维）

| 维度 | 定义 | 衡量方式 | 目标 |
| --- | --- | --- | --- |
| **完整性** | 必填字段非空率 | `non_null(field) / total` | 核心字段 100%，辅助 ≥80% |
| **准确性** | 与权威源对比偏差 | 抽样比对 DefiLlama 协议名 | ≥95% 匹配 |
| **时效性** | 数据 age 分布 | `now - fetched_at` P50/P95 | P50 < TTL，P95 < 2×TTL |
| **一致性** | 同项目跨源字段一致 | dedup 后冲突率 | <5% |
| **唯一性** | dedup_key 重复 | DB 唯一约束 + 抽样 | 0 重复 |
| **有效性** | 字段值在合法域 | schema 校验通过率 | ≥99% |

---

## 3. 字段分级与质量要求

### 3.1 核心字段（P0，严控）
| 字段 | 完整性 | 有效性 | 缺失影响 |
| --- | --- | --- | --- |
| `id` | 100% | UUID v5 格式 | 无法入库 |
| `name` | 100% | 非空、长度 1–100 | 无法入库 |
| `sector` | 100% | 在 `narratives` 词表内 | narrative agent 失败 |
| `score` | 100% | [0, 100] 整数 | 输出无效 |
| `label` | 100% | FARM/WATCH/IGNORE | 输出无效 |
| `reason` | 100% | ≥2 条 | 不可解释 |

### 3.2 关键字段（P1，努力保证）
| 字段 | 完整性 | 缺失降级 |
| --- | --- | --- |
| `raw_signals.has_points` | ≥90% | airdrop_signal 子分 60→20 |
| `raw_signals.airdrop_hint` | ≥90% | 同上 |
| `narrative_json.heat_score` | ≥80% | 走 0.5 中性 |
| `team_json.score` | ≥80% | 走 50 中性 |

### 3.3 辅助字段（P2，尽力而为）
| 字段 | 完整性 | 缺失影响 |
| --- | --- | --- |
| `tokenomics_json.vc_share` | ≥70% | tokenomics 子分中性 |
| `tokenomics_json.unlock_pressure` | ≥70% | 同上 |
| `risk_json.farming_cost` | ≥70% | reason 缺该条说明 |
| `url` | ≥90% | Dashboard 不显示链接 |

> 字段分级由 `config.field_tier` 维护，变更需 PR。

---

## 4. 质量指标（Prometheus）

> 全部指标已在 OBSERVABILITY §3.2 注册，此处给出业务语义。

| 指标 | 类型 | 标签 | 计算 | 告警阈值 |
| --- | --- | --- | --- | --- |
| `airdrop_data_completeness_ratio` | gauge | `field, tier` | `non_null / total`（每日 run 后） | P0 <1.0 / P1 <0.8 → warn |
| `airdrop_data_freshness_seconds` | gauge | `source` | `now - max(fetched_at)` | > 3×TTL → warn |
| `airdrop_data_validity_ratio` | gauge | `field` | schema 校验通过率 | <0.99 → warn |
| `airdrop_data_conflict_ratio` | gauge | `field` | dedup 冲突数 / 总 dedup | >0.05 → warn |
| `airdrop_quarantine_pending` | gauge | `source` | quarantine 未处理数 | >50 → warn |
| `airdrop_data_accuracy_match` | gauge | `source` | 抽样比对匹配率 | <0.95 → warn |

---

## 5. 检测规则

### 5.1 入库前校验（同步）
fetcher 结果进库前依次过：
```
1. schema 校验（Pydantic）      → 失败 → quarantine + skip
2. 业务校验（值域）              → 失败 → 截断 + warn
3. 去重校验（dedup_key 唯一）    → 冲突 → 仲裁 + 合并 sources
4. 引用完整性（sector 在词表内） → 失败 → quarantine + skip
```

### 5.2 入库后巡检（每日 run 后异步）
- **完整性扫描**：`SELECT CAST(SUM(CASE WHEN field IS NULL THEN 1 ELSE 0 END) AS REAL) / COUNT(*) FROM projects GROUP BY sector`
- **时效性扫描**：`SELECT max(fetched_at) FROM projects WHERE source=?`
- **唯一性扫描**：`SELECT dedup_key, count(*) FROM projects GROUP BY dedup_key HAVING count(*)>1`（应为 0）
- **异常值扫描**：score 落在 [0,100] 外、heat_score 落在 [0,1] 外

巡检结果写 metrics + 异常写 logs（event=`quality.scan.*`）。

### 5.3 抽样准确性校验（每日 10 个）
- 随机抽 10 个项目，回查 DefiLlama `/protocols` 对比 `name`/`sector`/`stage`。
- 匹配率写 `airdrop_data_accuracy_match`。
- 不匹配项写 `quarantine`（failure_reason=`accuracy_mismatch`）供 review。

---

## 6. 数据来源可靠性分级

> 与 `ENGINEERING_ROADMAP.md` §10.2 容错矩阵对齐，此处给出可靠性分定义。

| 源 | reliability | 理由 | 冲突仲裁优先级 |
| --- | --- | --- | --- |
| `seed` | 1.0 | 人工 curated | 最高 |
| `defillama` | 0.9 | 公认协议库 | 高 |
| `dune` | 0.8 | 链上可信 | 中高 |
| `cryptorank` | 0.75 | 商业库，偶有延迟 | 中 |
| `twitter` | 0.5 | 噪音大，仅作信号 | 低 |

**冲突仲裁规则**：
- 同字段多源冲突 → 取 `reliability` 最高源
- 同源多次抓取 → 取最新
- `reliability` 写入 `raw_signals.sources[]` 供审计

---

## 7. 脏数据处置流程

### 7.1 quarantine 表使用
- 任何 schema/业务/引用校验失败 → 写 `quarantine`（raw_data + failure_reason + source）
- 主流程跳过该记录，不阻塞其他项目
- 每日 run 后 `quarantine_pending > 50` 告警

### 7.2 修复路径
| failure_reason | 处理 | 责任 |
| --- | --- | --- |
| `schema_error` | 修 fetcher 解析逻辑 / Pydantic 模型 | 后端 |
| `business_error` | 截断值域 + warn；或修业务规则 | 后端 |
| `dedup_conflict` | 检查归一化规则 / 词表更新 | 数据 |
| `accuracy_mismatch` | 验证权威源；若是 fetcher 错则修；若是项目改名则更新 | 数据 |
| `reference_error` | 词表补同义映射 | 数据 |

### 7.3 处置 SLA
- P0 字段脏数据：24h 内修复或显式标注降级
- P1 字段：3 天内
- P2 字段：周度批量处理
- 30 天未处理自动清理（防堆积，但记日志保留追溯）

---

## 8. 数据新鲜度管理

### 8.1 TTL 策略（对齐 `ENGINEERING_ROADMAP.md` §10.3）
| 数据 | TTL | 触发告警 |
| --- | --- | --- |
| DefiLlama `/protocols` | 1h | age > 3h |
| DefiLlama `/new` | 15min | age > 45min |
| CryptoRank | 6h | age > 18h |
| Twitter 热度 | 30min | age > 90min |
| Dune 查询 | 1h | age > 3h |

### 8.2 过期数据处理
- 数据 age > 2×TTL：Dashboard 标"可能过期"小标记
- age > 3×TTL：该字段降级（heat_score 走 0.5 中性）+ 告警
- age > 7×TTL：re-score 不使用该字段，强制走中性

### 8.3 回填
- `POST /run?force_refresh=true`（V2，需鉴权）绕过缓存强制重拉
- 历史 re-score 默认用缓存；需最新数据时先清缓存再 re-score
- 缓存 miss 不阻塞，走降级路径

> **MVP 新鲜度豁免**：MVP 数据源为 `seed`（人工 curated，无 `fetched_at`），时效性指标 `airdrop_data_freshness_seconds` 与"数据 age"类告警在 MVP 阶段**不产出/不度量**（对应 OBSERVABILITY §3.2 标注 V2）。V2 接入 DefiLlama/CryptoRank 等真实源并填充 `projects.fetched_at` 后，新鲜度才纳入 SLA 与告警。

---

## 9. 数据血缘

### 9.1 血缘链路
```
外部源 → fetcher → schema 校验 → Collector (raw_signals) → Agent pipeline → projects 表
                                                                          ↓
                                                                       logs 表（每次 run 留痕）
```

### 9.2 可追溯信息
每个 `projects` 行可通过以下字段回溯：
- `source`：主来源
- `raw_signals.sources[]`：全部来源 + reliability
- `logs` 表 `WHERE project_id=?`：所有 agent 输入输出
- `project_history`（V2）：跨 run score/stage 变化

### 9.3 血缘展示
- V2 Dashboard 项目详情页加"数据来源"面板：列出 sources + fetched_at + reliability
- V3 支持点击某 agent 结果 → 展开 logs 原始输入输出

#### 9.3.1 血缘可视化方案（V2）

> Dashboard 项目详情页新增"数据来源"面板，展示完整血缘链路。

**面板内容**：
```
┌─────────────────────────────────────────────────────┐
│ 数据来源（Data Lineage）                              │
├─────────────────────────────────────────────────────┤
│ 项目: LayerX                                         │
│ 主来源: seed (reliability: 1.0)                       │
│ 采集时间: 2026-07-08 08:00:12 UTC                     │
├─────────────────────────────────────────────────────┤
│ 来源列表:                                             │
│ ● seed        reliability: 1.0  fetched: 08:00:12     │
│ ○ defillama   reliability: 0.9  fetched: 07:55:00     │
│ ○ cryptorank  reliability: 0.75 fetched: -- (未命中)    │
├─────────────────────────────────────────────────────┤
│ Agent 执行记录:                                       │
│ ✓ narrative   12ms   ✓ team   8ms                     │
│ ✓ risk        15ms   ✓ tokenomics   10ms              │
├─────────────────────────────────────────────────────┤
│ 评分权重版本: v1                                      │
└─────────────────────────────────────────────────────┘
```

**实现**：
- API：`GET /project/{id}` 返回 `lineage` 字段（含 sources + agent_executions）
- 前端：折叠面板，默认收起，点击展开
- 颜色编码：reliability ≥0.9 绿 / 0.7-0.9 黄 / <0.7 红

---

## 10. 数据质量 SLA

| 维度 | MVP | V2 | V3 |
| --- | --- | --- | --- |
| 完整性（P0 字段） | 100% | 100% | 100% |
| 完整性（P1 字段） | ≥80% | ≥90% | ≥95% |
| 准确性 | 不度量 | ≥95% | ≥97% |
| 时效性 P95 | 不度量（seed 数据无 fetched_at，见 §8.3） | < 1.5×TTL | < 1.2×TTL |
| 一致性冲突率 | <10% | <5% | <2% |
| quarantine 积压 | <100 | <50 | <20 |

- SLA 未达标触发告警（OBSERVABILITY §5.2）
- 连续 3 天某维度未达标 → 开 incident 复盘

---

## 11. 数据治理流程

### 11.1 词表维护
- `sector` 标准词表由 `narratives` 表（V2）维护，MVP 在 `config.SECTOR_ALIAS`
- 新赛道/同义映射变更：提 PR + 数据 review，避免归一化规则漂移
- 每月审计一次词表，剔除无项目命中的死词条

### 11.2 来源接入/下线
- 新增数据源需 ADR（说明 reliability、TTL、降级路径、成本）
- 下线数据源需评估对完整性/准确性的影响，必要时补替代源

### 11.3 质量月报（V2+）
- 每月自动生成数据质量月报：各维度达标率、quarantine 处理量、Top 脏数据源
- 月报复盘 → 产出改进项进 backlog

---

## 12. 与其他文档的关系

| 文档 | 关系 |
| --- | --- |
| `ENGINEERING_ROADMAP.md` §22 | 本规范的摘要与索引 |
| `ENGINEERING_ROADMAP.md` §7.6 | 缺失字段降级策略（本规范 §3 字段分级的实现） |
| `ENGINEERING_ROADMAP.md` §10 | 数据接入容错（本规范 §6 可靠性、§8 新鲜度的前置） |
| OBSERVABILITY §3.2 | 质量指标的 Prometheus 定义 |
| SECURITY §5.2 | 外部数据进库的 schema 校验 |
| DATA_SCORING_DICT | 字段含义字典（本规范 §3 字段分级引用） |
