# ADR-015: 机会资格前置门（否决条件与打分分离）

- **Status**: Accepted
- **Date**: 2026-09-01
- **Deciders**: 架构 / 产品 / 数据（owner 已拍板；实现与实测结果见 §「实施结果」）
- **技术栈**：Python / 规则引擎
- **影响面**：评分算法、权重校准协议、API 响应契约、前端标签展示

---

## 背景

M2 的历史回测（`scripts/run_backtest.py`，19 条 2024–2025 样本）第一次让评分
引擎在有标注的数据上跑出可度量的结果。结果是**全部 19 个样本都被判 FARM**：

| 指标 | 实测值 |
| --- | --- |
| recall(FARM) | 1.00 |
| fpr(FARM) | **1.00** |
| label 分布 | `{FARM: 19}` |
| 分数区间 | 68 – 85（阈值 FARM ≥65） |

ADR-006 §4 定义的校准目标函数是 `recall(FARM) − 2×false_positive(FARM)`。
按实测值代入：`1.00 − 2×1.00 = −1.00`。**现模型在自己的目标函数下是负分** ——
它没有区分能力，只是把所有项目都推荐了一遍。

### 五个负样本的八维子分（实测）

```
name          tot lbl  | airdr  narra  team_   risk  token  compe  execu  trans
Aztec          77 FARM |    96     60     75     56     56    100     74    100
Farcaster      80 FARM |    71     60     95     65     56    100    100    100
Worldcoin      69 FARM |    20     60     95     55     56    100    100    100
Chainlink      68 FARM |    20     60     85     55     57    100    100    100
Monad          77 FARM |    96     60     75     56     56    100     74     94
```

**关键观察（这一条推翻了「压低 airdrop_signal 权重就能修」的直觉）**：
Chainlink 与 Worldcoin 的 `airdrop_signal` **已经是最低档 20 分**
（`airdrop_signal.py` 的封顶逻辑正确生效了），它们仍然拿到 68 / 69 分越过阈值。
原因是其余七维给它们 55–100 分：

- `narrative_timing` 在全部 19 个样本上**恒为 60**（原因已查清，见 §「不解决什么」第 3 条：
  数据集 sector 写法与 `SECTOR_PROFILE` 键名不匹配，19 个样本全部落到 `DEFAULT_PROFILE`）
- `competition` 大面积 100（`COMPETITION_MAP` 在 sector_count ≤3 时给满分，
  而回测样本的 sector 计数普遍很低）
- `transparency` 92–100、`execution` 除两例外全 100

于是真正的病因是：**加权求和把「有没有空投机会」和「项目质量好不好」
混成了一个分数，而后者的维度更多、分值更高，前者被淹没。**

Chainlink 是优质项目，所以它在「质量」维度上样样高分。但系统要回答的问题
不是「这项目好不好」，是「**这里有没有我能拿的空投**」。这两个问题不能共用
一个加权和 —— 一个已发币的蓝筹在第一个问题上满分，在第二个问题上是零。

### 如果不决策

回测报告会持续显示 fpr=100%，权重校准（ADR-006 §4，样本 ≥200 时触发）
一旦启动就会在一个**结构错误**的模型上拟合权重。调权重能把分数压下去，
但代价是把真正的机会一起压掉 —— recall 会随 fpr 一起掉，因为两类项目在
七个「质量维度」上的分布是重叠的。**这是模型结构问题，权重取值解决不了。**

---

## 决策

### 1. 引入「资格门」（Eligibility Gate），与打分分离

在 `ScorerAgent` 的打分之后、贴标签之前，插入一层**否决条件检查**。
资格门回答一个二元问题：*这个项目现在还存在可参与的空投机会吗？*

不通过资格门的项目**不能拿到 FARM**，无论加权分多高。

```
subscores → weighted_sum → score(0-100)
                              ↓
                      _score_to_label(score)
                              ↓
              ┌──────── 资格门（本 ADR 新增）────────┐
              │  否决 → 强制降级 + 记 veto_reason   │
              └────────────────┬───────────────────┘
                               ↓
                _apply_confidence_degradation（已有）
                               ↓
                            label
```

**落点选择**：`scorer.py` 已有 `_apply_confidence_degradation`（置信度 <0.5
时 FARM→WATCH），它就是一个「只改 label 不改 score」的后置钩子。资格门
沿用同一模式插在它之前 —— **不需要重构加权求和，改动面可控。**

### 2. 首批否决条件（v1，仅两条）

| 条件 | 判定 | 动作 | 理由 |
| --- | --- | --- | --- |
| `already_launched` | `no_token_yet == False` 且 无 `has_points_program` 且 无 `explicit_airdrop_mention` 且 无 `has_task_portal` | FARM → **IGNORE** | 已发币且无任何追加分配叙事 = 机会窗口已关闭。这与 `airdrop_signal.py:72` 的封顶条件**用同一个布尔表达式**，避免第三份判定漂移 |
| `no_participation_path` | 无 `has_testnet` 且 无 `has_points_program` 且 无 `has_task_portal` | FARM → **WATCH** | 没有任何可参与入口时，「值得关注」是诚实的上限；说 FARM 等于让用户去参与一个不存在的活动 |

**为什么只有两条**：这两条能从实测数据里验证（Chainlink / Worldcoin 命中
第一条）。Aztec / Farcaster / Monad 三个负样本**故意不覆盖** —— 它们的
false positive 来自另外三类原因，见 §「本 ADR 不解决什么」。

### 3. 否决必须留痕，且是分数之外的独立字段

- `ScoreResult` 新增 `veto: str | None`（否决条件名，如 `"already_launched"`）
- `score` **保持否决前的原值不变**。否决改 label 不改分。
  > 理由：分数是「模型怎么看这个项目」的记录，否决是「业务规则怎么裁决」。
  > 把分数改成 0 会丢掉「这是个 68 分的优质项目，只是机会窗口关了」这个信息，
  > 也会让回测无法区分「模型给低分」与「规则否决」两种情况。
- `reason` 列表**首位**插入人类可读的否决说明（前端已有 reason 展示位，零改动）
- 日志 `scorer.veto_applied`（事件名字面量，OBSERVABILITY parity 要求）

### 4. 校准协议变更（ADR-006 的补充，不是替代）

- 资格门**不参与权重校准**。它是业务规则，不是可拟合参数。
  > 否则会出现「为了优化目标函数把否决条件放宽」—— 那是用指标反向侵蚀规则。
- 权重校准的目标函数（ADR-006 §4）**在资格门之后计算**。
  即先过门再算 recall/fpr，这样权重优化的是「有机会的项目里怎么排序」，
  而不是「怎么把没机会的项目压下去」。
- 新增否决条件**必须走 ADR**（与权重变更同等级），并在 `weight_changelog`
  之外单独记 `veto_changelog`。理由：否决条件比权重更"硬"，一条错误的否决
  会让整类项目永久不可见，而错误的权重只是排序偏差。

### 5. 回测报告新增否决维度

`run_backtest.py` 的报告增加：
- 每个 case 的 `veto` 字段
- 摘要区 `veto_distribution`（各条件命中数）
- **`veto_false_negatives`**：被否决但实际发过空投的样本数 —— 这是资格门
  最危险的失效模式（把真机会永久挡掉），必须单独盯，不能混在 fpr 里

---

## 理由

| 备选方案 | 被否理由 |
| --- | --- |
| 调整权重（提高 `airdrop_signal` 权重 / 压低 `competition`） | **实测证伪**：Chainlink/Worldcoin 的 `airdrop_signal` 已经是最低档 20 分，仍拿 68/69。要靠权重把它们压到 65 以下，需把 `airdrop_signal` 权重提到极端值，代价是其余七维全部失去意义 —— 那不是校准，是把八维模型退化成一维 |
| 提高 FARM 阈值（65 → 更高） | 全样本分数区间 68–85，**正负样本完全重叠**（负样本 68–80，正样本 75–85）。任何阈值都无法分开；提到 81 会把 12 个真机会一起砍掉，recall 从 1.00 掉到 ~0.25 |
| 给 `airdrop_signal` 加乘性惩罚因子（如已发币时总分 ×0.5） | 分数变得不可解释：68×0.5=34 会被读成「模型认为这项目很差」，而事实是优质项目 + 机会关闭。且乘性因子仍是连续量，遇到 90 分的已发币项目照样越线 |
| 重构成两个独立分数（机会分 + 质量分） | 方向正确但改动面过大：动 `ScoreResult` 契约、`projects` 表、API 响应、前端全部展示位、golden 回归集全部锚点。**可作为 v2 演进方向**，但不该在修一个已知缺陷时一次性做完 |
| **资格门前置 + 打分保持不变（本决策）** | 用最小改动面表达「否决 ≠ 低分」这个语义。落点复用已有的 `_apply_confidence_degradation` 模式；分数字段不变则 golden 集与历史数据全部保持可比；否决条件与 `airdrop_signal.py` 复用同一布尔表达式，不引入第三份判定 |

---

## 后果

### 正面
- fpr 的两个已发币误报（Chainlink / Worldcoin）从 FARM 降到 IGNORE，
  预期 fpr 从 5/5 降到 3/5（0.60）；目标函数从 −1.00 升到 `1.00 − 2×0.60 = −0.20`
- 「已发币 = 无机会」从**可补偿的打分**变成**不可补偿的否决**，语义正确
- 权重校准启动前先修结构，避免在错误模型上拟合（ADR-006 §4 的前置条件）
- `veto` 字段让「为什么这个项目没推荐」可解释，而不是让用户对着一个分数猜

### 负面 / 限制
- **资格门是硬规则，误否决的代价比误打分高**。一条过宽的条件会让整类项目
  永久不可见，且不会体现在分数上（分数照样高）。因此必须有
  `veto_false_negatives` 指标常态监控
- `no_participation_path` 这条依赖采集字段的完整性。若 `has_testnet` 因采集
  缺失而为 False，会把有机会的项目误降为 WATCH。**缓解**：该条只降到 WATCH
  不降到 IGNORE，且 WATCH 仍在前端可见
- 不解决 `narrative_timing` 恒 60 与 `competition` 大面积 100 这两个
  **无区分度维度**的问题（见下）

### 本 ADR 不解决什么（明确划界，避免以为修完了）

回测的 5 个 false positive 里，**只有 2 个**由本 ADR 覆盖。其余三类需单独立项：

1. **Aztec / Monad（仍在测试网，尚未发币）**：分数 77，`airdrop_signal` 96。
   这两个**当下判 FARM 其实是合理的** —— 它们确实有测试网可参与、确实可能
   发币。标注为负样本是因为「截至数据集编制时还没发」。这是
   **时间敏感样本**的标注问题，不是引擎缺陷。修数据集，不是修引擎。
2. **Farcaster（明确表示不做代币激励）**：`airdrop_signal` 71。需要一个
   「官方否认」信号字段（如 `explicit_no_airdrop`），采集侧没有这个字段，
   属于数据源能力问题。
3. **`narrative_timing` 全样本恒 60 —— 根因已查清，是数据集缺陷 + 一个生产隐患**：

   `_calc_narrative_timing` 的输入完全来自 `SECTOR_PROFILE[sector]` 查表
   （`narrative.py:114`），与项目自身特征无关。`DEFAULT_PROFILE` 是
   `base_heat 0.60 × momentum 1.0 = 0.60`，`stage="growth"` → coeff 1.0 → **60.0**。

   实测比对：
   ```
   SECTOR_PROFILE 键: AI Bridge DAO DEX DeFi GameFi Gaming Infrastructure
                      L2 Layer2 Lending NFT Privacy Restaking ZK
   数据集 sector 值:  zk-rollup(5) interoperability(2) restaking modular-da
                      dex-aggregator l2 perp-dex modular-l2 privacy-rollup
                      modular-execution social identity oracle L1
   ```
   **19 个样本没有一个命中查表**（小写连字符 vs 大驼峰），全部落到默认档。
   这是 M2 编制数据集时的保真度缺陷 —— **修数据集，不是修引擎**。

   但它顺带暴露一个**生产路径隐患**：`SECTOR_PROFILE` 是大小写敏感的精确
   匹配，且未命中时**静默**走默认档（无 warning）。真实采集数据只要 sector
   写法与查表键不同（`"zk-rollup"` vs `"ZK"`），这一维的 0.15 权重就全部
   浪费在常数 60 上，而且没有任何信号提示。

   > **已修（2026-09-01，本 ADR 之后的独立改动）**。实测确认这不是理论隐患：
   > DefiLlama 的真实 category 大面积未命中 —— `Dexes` / `Rollup` /
   > `Liquid Restaking` / `RWA` 全部落默认档。
   >
   > 修法是 `narrative.py::resolve_sector_profile()`：三级查找（精确 → 别名表
   > → 大小写无关），未命中时返回 `(DEFAULT_PROFILE, None)`，让调用方能**区分
   > 「命中」与「走了默认档」**并打 `narrative.sector_profile_missing` WARNING。
   >
   > **归一刻意只做在查表侧，没有去扩 `utils.normalize.SECTOR_ALIAS`**：那个
   > 函数的产出进 `create_dedup_key()` → `generate_deterministic_id()`，sector
   > 是项目确定性 ID 的组成部分。把 `"Dexes"` 归一成 `"DEX"` 会让同一项目算出
   > 不同 UUID，既有行全部变孤儿、跨源去重失效。
   > `test_sector_profile_lookup.py::test_lookup_alias_is_not_wired_into_normalize_sector`
   > 是刻意的**反向**约束，防止后人顺手「统一」这两张表。
   >
   > 没有档位的新赛道（如 `RWA`）仍走默认档并告警 —— 硬塞进现有档位等于编造
   > 赛道热度，正确处置是去 `SECTOR_PROFILE` 补一档真实值。

4. **`competition` 大面积 100**：`COMPETITION_MAP` 在 sector_count ≤3 给满分，
   而回测的 sector 计数来自数据集自带字段而非真实竞品统计。是回测输入的
   保真度问题，也可能暴露 `COMPETITION_MAP` 分段过于宽松。
   注意它与第 3 条同源 —— sector 写法五花八门（14 个不同值 / 19 个样本），
   按 sector 分组统计自然每组都 ≤3 个。

### 需配套的工作
- [x] `backend/app/agents/eligibility.py`（新建）：否决条件判定，与
      `airdrop_signal.py` 复用同一布尔表达式（共享
      `is_already_launched_without_airdrop_path()`，`airdrop_signal.py` 的内联
      表达式已替换为该调用）
- [x] `backend/app/agents/scorer.py`：插入资格门调用，`ScoreResult` 加 `veto`
- [x] `backend/app/models.py`：`ScoreResult.veto` + `ProjectRecord.veto` 字段
- [x] `backend/app/repository.py` + `db.py` 双方言 + alembic 0008 + `DATABASE_DDL.md`：
      `projects.veto` 持久化（**三处同落**）
- [x] `db.py::init_db` 的 `_add_column_if_not_exists(db, "projects", "veto", "TEXT")`：
      **既有库的升级路径**。「三处同落」漏了这一处 —— 详见下面「实施中新发现的坑」
- [x] `backend/scripts/run_backtest.py`：报告加 `veto` / `veto_distribution` /
      `veto_false_negatives`
- [x] `backend/tests/agents/test_eligibility.py`（新建）：两条否决条件的正反断言 +
      「否决不改 score」断言 + 与 `airdrop_signal` 封顶条件的一致性断言
- [x] `backend/tests/test_backtest.py`：删除 `xfail(strict=True)` 的
      `test_known_engine_gap_already_launched_still_farm`，改为正向断言
      `test_already_launched_projects_are_vetoed_from_farm`
      （strict xfail 修好后会 XPASS 报错，这是设计意图）
- [x] `docs/OBSERVABILITY.md §2.2`：登记 `scorer.veto_applied`，更新事件计数
- [x] `docs/WEIGHT_CALIBRATION.md`：补 §4.1.1「资格门不参与拟合」
- [x] `docs/adr/README.md`：ADR-015 索引
- [x] `docs/ACTION_LOOP_DESIGN.md §6`：把「🔴 引擎缺陷」标记指向本 ADR

---

## 实施结果（2026-09-01 实测）

资格门与数据集 sector 归一化（§「不解决什么」第 3 条）在同一批改动中落地。
回测实测：

| 指标 | 决策前 | 决策后 |
| --- | --- | --- |
| recall(FARM) | 1.000 | 0.929 |
| fpr(FARM) | 1.000 | 0.400 |
| 目标函数 `recall − 2×fpr` | **−1.00** | **+0.129** |
| label 分布 | `{FARM: 19}` | `{FARM: 15, WATCH: 2, IGNORE: 2}` |
| veto 分布 | — | `{already_launched: 2, no_participation_path: 2}` |
| `veto_false_negatives` | — | **1** |

目标函数从负分转正 —— 模型第一次在自己的评价标准下具备区分能力。
Chainlink / Worldcoin 的 `score` 保持 68 / 69 **未变**，仅 label 降为
IGNORE 并带 `veto=already_launched`，验证了「否决改 label 不改分」。

sector 归一化后 `narrative_timing` 不再恒 60（实测 Manta 93.5 / Linea 90.2 /
Taiko 90.2 / Chainlink 84.0 / Farcaster 60.0），该维度的 0.15 权重恢复作用。
`social`（Farcaster）与 `identity`（Worldcoin）**刻意保留原写法**并接受
`DEFAULT_PROFILE` —— 硬塞进 DAO/Infrastructure 属于编造赛道热度。这两个
fallback 在 `test_sectors_hit_engine_profile_or_are_declared_fallbacks`
中显式登记，其余任何未登记写法都会红灯而非静默走默认档。

### 实施中新发现的坑：「三处同落」不够，是四处

原先的约定是新列要落「`db.py` 建表 DDL 双方言 + alembic migration +
`DATABASE_DDL.md`」。本次按此执行后，golden 回归集 **12 failed**：

```
repository.project.save_failed error='table projects has no column named veto'
→ RunResponse(status='failed')
```

根因：建表语句是 `CREATE TABLE IF NOT EXISTS`，**既有库表已存在就整条跳过**，
列永远补不上。既有库的升级路径是 `init_db` 里的
`_add_column_if_not_exists(...)`，这一处不在原约定里。

失效方式特别隐蔽的两点：

1. **CI 看不见**。CI 是全新 checkout，表由完整 DDL 现建，门禁全绿。只有已跑过
   的开发 / 生产库升级时才炸。
2. **报错点离根因很远**。表现是「升级后所有分析任务突然全挂」
   （`status="failed"`），而评分本身是成功的 —— 只是落不了库。

alembic migration **不能替代**这一处：`0008` 为了兼容滚动 baseline 做了列存在性
判断，且不是所有部署路径都跑 `alembic upgrade`。

已加回归测试 `tests/test_db_init.py::test_existing_database_reaches_full_column_parity_after_init`：
按**冻结的历史列形态**建表 → 跑 `init_db` → 要求列集合追平当前 DDL。快照冻结，
所以以后任何新列漏登记都会红灯，与具体是哪一列无关（已反向验证：临时注掉
`veto` 那行，测试报 `{'projects': ['veto']}`）。
约定同步写入 `OPERATIONS.md §3.5` 与 `DATABASE_DDL.md §2.17`。

### 已知遗留：`veto_false_negatives = 1`（Jupiter）

```
✗  70 WATCH    Jupiter    空投(large)  veto=no_participation_path
```

Jupiter 实际发过大额空投，被 `no_participation_path` 误否决。它的参与路径
是「历史交易行为」，而该规则依赖的三个字段（`has_testnet` /
`has_points_program` / `has_task_portal`）都表达不了这一点。

**这正是 §「负面 / 限制」第 2 条预警的失效模式**，且预设的缓解生效了 ——
只降到 WATCH 而非 IGNORE，机会仍在前端可见，recall 的 0.071 损失全部来自
这一条。处置方式（补「链上交易量/使用量」参与路径信号 vs 收窄规则适用
条件）属于业务约束调整，**待 owner 决策，不单方面放宽规则**。

### 迁移成本
- **历史数据不重算**。`projects.veto` 对既有行为 NULL，语义是「未经资格门评估」。
  重算需显式跑 `POST /run`，与「权重变更不追溯历史分数」（ADR-006 §3）口径一致。
- golden 回归集：`score` 字段不变 → 分数锚点全部保持。仅 label 断言中
  涉及已发币项目的需更新（预期 2 条）。
- 前端：`reason` 首位插入否决说明，复用现有展示位，**零改动**。
  若要单独高亮 `veto` 徽标，属于可选增强。

---

## 关联

- ADR-001（LLM 默认关）：资格门是纯规则判定，不依赖 LLM，与默认关闭一致
- ADR-006（权重冻结与校准）：本 ADR **补充**其 §4 校准协议，不替代。
  资格门在校准目标函数之前生效
- ADR-014（引擎规格一致性）：新增否决条件需同步规格文档
- `docs/ACTION_LOOP_DESIGN.md §6`：缺陷的最初记录
- `docs/WEIGHT_CALIBRATION.md`：校准协议
- 数据依据：`backend/data/backtest/airdrops_2024_2025.json`（19 条，
  `pending_expansion=true`）+ `scripts/run_backtest.py` 实测输出
