# ADR-014: 评分决策引擎回归规范 + 旁路机会引擎区间算法修正

- **Status**: Accepted
- **Date**: 2026-07-26
- **Deciders**: 架构 / 后端
- **技术栈**：Python / FastAPI / Pydantic v2
- **影响面**：评分算法（`score-v1.4`）、旁路决策引擎（`opportunity-v2.0`）、Golden 用例、`projects` 表写入列

---

## 背景

本轮引擎审查发现：代码在若干处与本仓库自己的书面规范不一致，且不一致的方向**系统性地惩罚证据更充分的项目**。这不是"权重需要重新校准"，而是"实现没有按规范执行"。逐条对照：

1. **跨源合并丢信号**（`utils/normalize.py`）。规范 `DATA_QUALITY.md §128` 要求"同字段多源冲突 → 取 reliability 最高源"，但实现是整条记录按来源优先级择一，把落选来源的**全部字段**丢弃。生产中最常见的形态是「信号丰富的任务门户源 + 信号稀疏的行情源」，两源合并后 23 个信号字段被清空、`source_count` 恒为 1。结果是：**多发现一个来源，分数反而下降**。实测把 galxe 记录与 defillama 记录合并，分数从 77/FARM 掉到 64/WATCH。

2. **Risk Agent 用错了 Tokenomics 字段**（`agents/risk.py`）。规范 `DATA_SCORING_DICT.md §5.7.2` 写明 `token_risk = 0.6 × tokenomics.risk + …`，实现取的是 `tokenomics.unlock_penalty`。二者不同：`risk` 按 §5.7.1 是 `vc_share×0.4 + team_share×0.3 + unlock_penalty×0.3`。该偏差此前被 Agent 执行顺序掩盖，上一轮修好顺序后才显形，方向与模型意图相反——高解锁压力项目 risk 子分被少扣 31.5 分，VC 集中项目反被多加 12 分。

3. **`airdrop_signal` 子分有两份实现**（`agents/scorer.py` 与 `agents/risk.py`）。同一信号组合在两处会算出不同结果：穷举 2304 种组合，666 种不一致。

4. **confidence 与规范不符**（`agents/scorer.py`）。规范 §3.5 定义 v1.3 口径 `0.35×Agent覆盖 + 0.65×可验证信号`；实现的系数是 0.40/0.60，并在 Agent 覆盖率满时加了 0.55 的下限。影响面要说准：Agent 缺失时旧公式仍可能 <0.5（缺 1–3 个 Agent 的下限依次为 0.45/0.20/0.10），但那是异常路径；**四个 Agent 全部成功的正常路径**下 confidence 恒 ≥0.55（穷举 256 种信号配置最低值恰为 0.5500）。于是 §6.1 的"confidence < 0.5 强制降档"只在 Agent 崩溃时生效，而它本意是防"可验证信号不足"——两者管的不是同一件事，信号再稀疏也降不了级。

5. **旁路引擎区间算法自相矛盾**（`opportunity/probability.py`）。`joint_probability` 的 `base` 按独立性假设取三因子相乘，端点却按逐分位连乘（`low×low×low`）。逐分位连乘只在三因子完全同向时成立，与 `base` 的独立性假设不可能同时为真。后果是可判定的：`decision` 用 `reward_probability.low >= 0.20` 作为 FARM 门槛，而「官方分发 + 积分制资格 + 未禁止多钱包」这一档的 `joint.low` 恒为 `0.55×0.50×0.60 = 0.1650`，**无论证据多强都跨不过门槛**。

6. **`TOO_EXPENSIVE` 在真实链路上不可达**（`opportunity/decision.py`）。成本超预算会让 `_derive_eligibility` 返回 `None`，进而把 `reward_probability` 塞进 `critical_unknowns`，于是被"证据不足"分支短路。用户看到的是"去补证据"，真实原因却是"这个项目对该画像太贵了"。270 项机会语料双跑证实：旧引擎产出 `NOT_FIT` 的数量为 **0**。

7. **`critical_unknowns` 两套命名只登记了一套**（`opportunity/decision.py`）。`build_inputs` 用无后缀名，`service.evaluate_row` 用模型字段名（带 `_usd`/`_hours`）。后者 8 个名字全部未登记，一律塌缩成通用码 `WAIT_MORE_EVIDENCE`，理由码失去区分度。

8. **证据新鲜度 90 天后不再衰减**（`opportunity/service.py`）。原阶梯 `>90 天` 一律 0.2 且永不再降，181 天、400 天与 5 年前的证据完全等价。

---

## 决策

**按规范修正实现，而非修改规范去迁就实现。** 具体：

| # | 变更 | 依据 |
| --- | --- | --- |
| 1 | `merge_raw_records` 改为**按字段类合并**：存在性布尔全源 OR；`github_stars`/`tvl_usd`/融资额全源 max；`github_recent_push_days` 全源 min；投资人列表全源并集；标量取"最高可信来源中的已知值"（`unknown`/空不覆盖已知值）。`source_count = max(1, 来源数, 已有值)` | `DATA_QUALITY.md §128`、§141 |
| 1b | `manual`/`api` 的显式取值**不参与** OR/max，直接采信 | 只有这两类来源能主张否定（见"理由"） |
| 1c | 合并排序键改为（优先级, 来源名, 记录内容规范序）；`merge_sources` 排序键加来源名 | 结果与输入顺序、与 `PYTHONHASHSEED` 无关 |
| 2 | `risk.py` 改用 `state.tokenomics.risk` | `DATA_SCORING_DICT.md §5.7.2` |
| 3 | 抽出 `agents/airdrop_signal.py` 作为唯一实现，scorer 与 risk 同时委托 | 消除双实现 |
| 4 | confidence 去掉 0.55/0.45 下限，严格按 `0.35×Agent覆盖 + 0.65×信号覆盖` | `DATA_SCORING_DICT.md §3.5`（v1.3 口径） |
| 5 | `joint_probability` 端点改为**相对不确定度平方和合成**，并以逐分位连乘为地板/天花板；`base=0` 时端点保留连乘值 | 与 `base` 的独立性假设自洽，且恒为旧区间的子集 |
| 6 | 新增 `_determinate_misfit()`，在 `critical_unknowns` 短路**之前**（但在三个 BLOCK 判定**之后**）判定"已确知不符合画像"的硬约束，并要求 `hard_cost_confirmed_minimum`（observed/derived + 来源等级 ≥ B） | `DATA_SCORING_DICT.md` Opportunity v2 gates；门槛与 `_derive_eligibility`、`weekly_time_confirmed_minimum` 一致 |
| 7 | `_UNKNOWN_REASON_CODES` 同时登记两套命名，且同一事实的两个别名映射到同一码 | 理由码可区分 |
| 8 | 新鲜度阶梯**只延长尾部**：`≤180 天` 仍为 0.2（与原行为一致），`≤365 天` 0.1，此后 0.05 | 任何年龄的 freshness 都 ≤ 原值，只收紧不放宽 |

配套：`ScoreResult.weight_version` 改为从 `settings.weight_version` 读取（此前硬编码，与 `WEIGHT_CALIBRATION.md §1.2` "每次生效权重必须有 weight_version" 的可审计意图相悖）；`TokenomicsResult.risk` 改为 `computed_field`，公式在模型层唯一定义，并加 `model_validator(mode="before")` 丢弃传入的 `risk` 以保持 `model_dump()` 可回放（`extra="forbid"` + computed_field 否则无法往返，任何从 `tokenomics_json` 回放的路径都会硬失败）；新增 `projects.sub_scores` 列承载子分快照，`repository.save` 的 UPSERT 以 `COALESCE(EXCLUDED.x, projects.x)` 写入 `weight_version` 与 `sub_scores`。

**不复用 `raw_signals` 存子分**：该列存的是采集到的**输入**信号（`scripts/seed.py` 与 `raw_signals_hash` 均按此语义写入），子分是**输出**，两者形状不兼容；且 Scorer 失败时 `sub_scores` 为空，若直接覆盖会把上一次成功评分的快照抹成空壳，故用 `COALESCE` 保留。

**存量数据不做全库重算**（遵循 `WEIGHT_CALIBRATION.md §5`「历史行保留旧 weight_version，不强制全库重算」）。是否重算交由运维决策，双跑报告见下。

---

## 理由

| 备选方案 | 被否理由 |
| --- | --- |
| 保持实现不变，改规范去描述现状 | 规范里被违反的三条恰好都是**保护性规则**（多源加权、低置信降档、成本超预算判 IGNORE）。把它们改成"现状"等于正式放弃保护，且第 1 条会固化"证据越多分越低"这一与产品目标反向的行为 |
| 只修 1–4（主引擎），旁路引擎留待以后 | 第 5、6 条是**结构性不可达**而非精度问题：中档规则栈永远拿不到 FARM、`NOT_FIT` 永远产不出。留着会让旁路引擎的灰度数据全程无效，越晚修沉没的观测越多 |
| 用逐分位连乘但下调 FARM 门槛 | 治标：门槛是按概率语义定的，为迁就错误的区间算法去改门槛，会让门槛数值失去可解释性；且区间宽度虚高 1.6 倍的问题依然存在 |
| **按规范修正实现** | 每条修改都能指到规范的具体章节；修改方向与规范一致，无需重新论证模型意图；改动全部有双跑量化与回归测试锚定 |

区间算法的选择另做了独立验证：以最佳规则栈（0.65/0.78/0.90 × 0.65/0.80/0.90 × 0.75/0.88/0.95）为例，40 万次独立三角分布抽样的真实 p10–p90 为 **0.4528–0.5953**；逐分位连乘给出 0.3169–0.7695（两端都落在约 0% 的尾部）；平方和合成给出 0.3893–0.6664（仍偏保守，覆盖率 99.2%，但不再与 `base` 的假设冲突）。选保守而非无偏，是因为该区间下界直接驱动资金决策门槛。合成结果恒为逐分位连乘区间的子集，0.1 网格上穷举 2334 万组三元组验证：0 违例，且无一例出现"旧过 FARM 门槛、新过不了"。

合并规则中"只有 `manual`/`api` 能主张否定"这一条，来自对真实数据形状的核对而非偏好：抵达 `merge_raw_records` 的是**已归一化的整行**，缺失布尔一律填 `False`、缺失计数一律填 `0`。所以爬取源的 `False` 表示"我没看到"，不是"我核实了不存在"，与另一源的 `True` 之间不构成 §128 意义上的冲突。若把它当成冲突并按可信度裁决，行情源（`defillama`，优先级 3）的一片 `False` 会压掉任务门户源（`galxe`，优先级 6）的全部空投信号——实测该写法把合并路径的收益从 +19 分削到 +8 分，等于把本轮最主要的修复又还了回去。而 `manual`/`api` 是人工/一方系统的刻意输入，其 `False` 是真实断言，必须优先。

---

## 后果

### 正面

- 跨源合并不再惩罚证据：60 个走真实合并路径的项目全部由 WATCH 升到 FARM（+19 分），`source_count` 恢复真实值，`DATA_QUALITY.md §141` 的"≥2 源覆盖率"KPI 首次可测。
- `DATA_SCORING_DICT.md §6.1` 的低置信降档规则从"死规则"变为可触发（语料中 3 个项目 confidence < 0.5）。
- 旁路引擎中档规则栈重新可达 FARM（80 个项目跨过 `low >= 0.20` 门槛，其中 4 个最终判 ACTIONABLE）；`TOO_EXPENSIVE` 首次可达（90 个项目由"证据不足"更正为"太贵"）。

### 负面 / 限制

- **12 个 Golden 用例期望值全部变更**（见 §与 Golden 的关系）。这是语义修正的必然结果，不是用例放松：`test_golden_cases.py` 的 confidence 断言由"下限 ≥0.45"改为"与期望值偏差 ≤0.10"，实际是**收紧**。
- 主引擎双跑：264 项语料中 224 项（84.8%）分数变化，区间 −2..+19，均值 +6.20，中位 +2；80 项（30.3%）跨越标签边界（77 WATCH→FARM、2 IGNORE→WATCH、1 WATCH→IGNORE）。FARM 由 95 增至 172。**FARM 数量翻倍，下游若有按 FARM 数量设定的容量假设需重新评估。**
- 旁路引擎双跑：270 项语料中 94 项（34.8%）决策状态变化，其中 90 项 WATCH→IGNORE。旁路引擎不影响用户可见主分，但若已有基于旁路标签的告警需同步调整。
- confidence 分布整体下移下限（最小值 0.5500 → 0.4429），是去掉人为下限后的真实值。
- **区间收窄是双向的**：新 `high` 恒 ≤ 旧 `high`（可证：`Π(1+rᵢ) ≥ 1+Σrᵢ ≥ 1+√Σrᵢ²`），因此 `gross_reward.high < 30 → DUST_REWARD`（30 天 IGNORE）比以前更容易触发。这不是缺陷——旧 `high` 落在真实分布约 0% 的尾部，用一个虚高的乐观值去躲开 DUST 判定本就不成立——但"只会解锁 FARM"的说法是不完整的，它同样会产出新的 IGNORE。
- 新增 `projects.sub_scores` 列。现有库由 `init_db` 的 `_add_column_if_not_exists` 自动补列，无需手工迁移；旧行该列为空。

### 需配套的工作

- [x] `backend/app/utils/normalize.py` 字段类合并
- [x] `backend/app/agents/airdrop_signal.py`（新增，唯一实现）
- [x] `backend/app/agents/{risk,scorer,team,collector,orchestrator_simple}.py`
- [x] `backend/app/opportunity/{probability,decision,service}.py`
- [x] `backend/app/{models,repository,config}.py`、`routers/v1/funding.py`、`services/project_signals.py`
- [x] `backend/tests/golden/cases.py` 12 例期望值 + `test_golden_cases.py` 断言口径
- [x] `backend/scripts/dual_run_compare.py`（新增 `dump`/`diff` 与 `dump-opp`/`diff-opp`）
- [x] `backend/app/db.py` 新增 `projects.sub_scores` 列（DDL + `_add_column_if_not_exists`）
- [x] `docs/DATA_SCORING_DICT.md` §5.8 跨源合并语义、§5.9 持久化列、§6.1 confidence 口径、Opportunity v2 gates 补充
- [x] `docs/WEIGHT_CALIBRATION.md` §2 权重表与代码对齐
- [ ] 运维决策：是否对存量库执行一次全量 re-score（默认不执行）

### 迁移成本

存量数据无需迁移即可运行：`weight_version` 与 `sub_scores` 两列在旧行上为空，新写入才有值；`sub_scores` 列由 `init_db` 自动补齐。若选择全量重算，成本为一次 `POST /api/v1/rescore`（按 `WEIGHT_CALIBRATION.md §5` 的可选批量 re-score 运维接口），风险是全库标签一次性跳变——建议先在只读副本上跑 `scripts/dual_run_compare.py` 确认影响面。

---

## 关联

- 相关 ADR：ADR-006（权重冻结）
- 引用文档：`docs/DATA_SCORING_DICT.md` §3.5 / §5.7.1 / §5.7.2 / §6.1、`docs/DATA_QUALITY.md` §128 / §141、`docs/WEIGHT_CALIBRATION.md` §1.2 / §5 / §6
- 双跑工具：`backend/scripts/dual_run_compare.py`
- 回归锚点：`backend/tests/test_review_regressions.py`、`backend/tests/golden/`
