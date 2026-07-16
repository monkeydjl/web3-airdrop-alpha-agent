# Opportunity v2.0 评分模型设计

> 状态：已确认设计
> 日期：2026-07-14
> 模型版本：`opportunity-v2.0`
> 默认画像：`low-cost-curated-multiwallet-v1`
> 适用窗口：未来 3-6 个月
> 相关文档：`DATA_SCORING_DICT.md`、`WEIGHT_CALIBRATION.md`、`IMPLEMENTATION_STATUS.md`

## 1. 目标与边界

### 1.1 决策目标

模型优先优化低成本精品多钱包用户的风险调整后收益，而不是单独优化项目质量、空投发生率或最高潜在奖励。

默认用户画像：

- 使用 3-10 个合规精品钱包。
- 每钱包累计不可退硬成本不超过 10 USDT。
- 每个项目的组合维护时间不超过每周 2 小时。
- 当前以零资金或极低资金参与为主，未来可增加资金档位。
- 只评估真实、差异化和可持续的参与，不提供规避反女巫检测的方法。
- 错误偏好保守，宁可漏掉部分机会，也优先避免推荐后亏损。

### 1.2 非目标

- 不预测或承诺确定收益。
- 不把融资额、叙事热度或未发币单独视为空投保证。
- 不提供绕过 KYC、唯一人格、多钱包限制或反女巫审查的方案。
- 不执行交易、签名、授权或自动 farming。
- 不以单一不透明总分替代证据和分项结果。

## 2. 总体架构

模型采用“硬门槛 + 概率链 + 奖励情景 + 成本风险 + 多维展示”的架构。

```text
原始证据
  -> 标准化因子
  -> 数据可判定性检查
  -> 安全、诚信、规则、成本硬门槛
  -> P_event x P_eligibility x P_survival
  -> 条件奖励三情景
  -> 风险调整净收益与时间效率
  -> FARM / WATCH / IGNORE
```

每个项目输出六组结果：

| 输出 | 回答的问题 | 是否直接决定 FARM |
|---|---|---|
| Eligibility Probability | 做任务后获得奖励的联合概率多大 | 是 |
| Reward Potential | 获得资格后的单钱包奖励区间多大 | 是 |
| Cost & Efficiency | 需要多少钱和时间，效率是否合适 | 是 |
| Loss Risk | 资金、资格、项目、稀释和流动性风险多大 | 是 |
| Project Quality | 项目是否真实、可靠且能持续运营 | 间接 |
| Evidence Confidence | 判断由多少可靠、完整、独立且新鲜的证据支持 | 是 |

`Project Quality` 高不等于会发空投。`Evidence Confidence` 低不等于项目差，而是系统暂时无法可靠判断。

## 3. 空投资格概率

### 3.1 概率链

```text
P_reward = P_event x P_eligibility x P_survival
```

- `P_event`：项目在 3-6 个月内发生空投、积分兑换或其他社区价值分配的概率。
- `P_eligibility`：正常真实参与的钱包满足奖励条件的概率。
- `P_survival`：满足表面条件后通过最终规则、反女巫和资格审查的概率。

三个概率分别输出 `low/base/high` 区间，不输出无依据的伪精确点值。

### 3.2 P_event 因子

强正向证据：

- 官方明确宣布空投、社区分配或积分兑换。
- 官方积分系统明确关联未来权益。
- Tokenomics 明确预留社区分配。
- 官方 Season、Epoch、快照或任务机制与奖励相关。
- 未来 3-6 个月存在 TGE、主网上线、Season 结束等可信催化剂。

辅助正向证据：

- 未发币且产品或测试网持续活跃。
- 项目有足够的运营能力活到兑现阶段。
- 同类产品有可比的社区分配历史。

负向证据：

- 已发币且没有后续奖励依据。
- 官方明确否认代币或空投。
- 积分长期无更新或 Season 无限延期。
- 项目停止开发、资金链异常或主要团队解散。

仅有未发币、高融资、任务平台活动、KOL 猜测或赛道热度时，不足以形成 FARM 所需的空投证据。

### 3.3 P_eligibility 因子

正向因素：

- 资格规则公开且任务定义清晰。
- 当前仍可参与，未错过快照。
- 必要任务可在成本和时间预算内完成。
- 任务与真实产品使用高度相关。
- 积分、等级或排名可追踪。
- 活动需要持续参与，但当前仍处早期窗口。

负向因素：

- 资格主要依赖未知快照。
- 需要高交易量、高余额或长期锁仓。
- 需要大量邀请、社交影响力或人工内容。
- 活动高度拥挤且进入时间明显过晚。
- 规则频繁变化或追溯增加门槛。

资格机制分类：

- `deterministic`：完成公开任务即可。
- `points_based`：按积分、排名或分位数分配。
- `behavioral`：按真实使用、活跃跨度和行为多样性判断。
- `opaque`：依赖未知快照或未公开内部模型。

### 3.4 P_survival 因子

正向因素：

- 官方允许同一用户管理多个钱包。
- 规则未禁止多钱包，但强调真实使用。
- 每个钱包具有真实、持续的产品使用记录。

负向因素：

- 官方历史上大规模清洗关联钱包。
- 规则包含模糊的批量、关联或自动化处罚条款。
- 奖励高度依赖邀请网络或社交图谱。
- 最终资格完全由未公开模型决定。

直接阻断当前画像：

- 明确规定一人一个钱包。
- 唯一人格证明或每资格独立 KYC。
- 明确禁止同一用户控制多个参与地址。
- 奖励按自然人而非钱包地址发放。

### 3.5 概率等级

| 等级 | 区间 | 含义 |
|---|---:|---|
| Very High | 80%-95% | 官方证据明确，主要剩执行风险 |
| High | 60%-80% | 多项强证据，仍有未确认条件 |
| Medium | 35%-60% | 逻辑合理，但关键条件未明确 |
| Low | 15%-35% | 主要依赖间接信号 |
| Very Low | 0%-15% | 存在反证或缺少基本条件 |

### 3.6 FARM 概率门槛

```text
P_event.low >= 50%
P_eligibility.low >= 50%
P_survival.low >= 60%
P_reward.low >= 20%
```

还必须至少有一条 A 级直接空投证据，或两条相互独立的 B 级证据，且不存在多钱包规则阻断项。

## 4. 奖励价值三情景

### 4.1 输出

每个项目输出单个合格钱包的条件可兑现奖励：

- `conservative`：低估估值和个人份额，高估稀释与兑现折价，用于控制 FARM。
- `base`：采用最可信的中位假设，用于排序。
- `optimistic`：采用合理上界，只展示上行空间，不能单独触发 FARM。

条件奖励不包含空投概率，后续才与 `P_reward` 相乘。

### 4.2 有 Tokenomics 时

```text
Community Distributable Value
= Expected Circulating Market Cap
x Community Allocation
x Current Distribution Release

Conditional Reward per Qualified Wallet
= Community Distributable Value
x Wallet Tier Share
/ Qualified Wallet Count
x Realization Haircut
```

### 4.3 无 Tokenomics 时

```text
Conditional Reward
= Comparable Airdrop Distribution
x Project Scale Adjustment
x Dilution Adjustment
x Qualification Tier Adjustment
x Realization Haircut
```

没有足够可比数据时，只输出奖励等级和极宽区间，不输出伪精确美元值，并禁止 FARM。

### 4.4 奖励池能力

- 社区分配比例、本期释放比例。
- 预计流通市值、协议收入和产品规模。
- 融资金额、轮次和投资方质量。
- TVL、交易量、收入和活跃用户。
- 同赛道历史空投规模。
- 是否存在多季奖励或已知链上奖励池。

融资只作为运营能力、潜在估值和解锁风险的底层事实，不在多个总分中重复加分。

### 4.5 用户稀释

- 总参与钱包和真实有效钱包数量。
- 参与增长速度。
- 任务门槛和免费任务占比。
- 热度、KOL 曝光和营销扩散。
- 积分分层、排名规则和巨鲸集中度。
- 用户进入时间与早期乘数。

叙事热度同时可能提高估值和参与稀释，必须双向建模。

### 4.6 用户份额能力

默认评估 `standard low-cost participant`，而不是排行榜前 1% 或巨鲸用户。

资格层级：

- `dust`：可能有资格，但奖励预计过低。
- `standard`：普通有效参与者。
- `premium`：高积分、高贡献或早期参与者。
- `unknown`：分配规则不明。

按交易量、TVL 或锁仓额分配时，低成本画像应显著降级。零成本任务能进入有效资格层、低成本积累活跃跨度或早期参与有明确乘数时，给予正向估计。

### 4.7 可兑现折价

```text
Realizable Reward = Nominal Reward x Realization Haircut
```

| 情况 | 建议系数 |
|---|---:|
| 即时解锁且流动性充足 | 0.80-0.95 |
| 即时解锁且流动性一般 | 0.60-0.80 |
| 分期解锁 | 0.40-0.70 |
| 估值高度不确定 | 0.30-0.60 |
| 不可转让积分或权益 | 0.00-0.30 |

领取 Gas、跨链成本、地域或 KYC 限制、小额无法经济领取等因素也必须进入可兑现价值。

### 4.8 多钱包组合

```text
Portfolio Reward != Reward per Wallet x Wallet Count
```

多钱包结果受共同规则变化、共同资格审查和共同项目失败事件影响。系统分别输出单钱包区间和组合区间，并以相关性折减估算有效合格钱包数。该折减只用于风险估计，不用于指导规避审查。

### 4.9 FARM 奖励门槛

```text
Base Expected Net Reward >= $30 per wallet
Conservative Realizable Reward > Hard Cost
Base Reward-to-Cost Ratio >= 3
Optimistic Scenario cannot be the main source of positive value
```

`$30` 是冷启动参数，后续以真实结果校准。

## 5. 成本、时间与风险调整收益

### 5.1 成本分类

| 类型 | 含义 | 处理 |
|---|---|---|
| Hard Cost | Gas、跨链费、任务费、领取费等不可退支出 | 直接扣除 |
| Capital at Risk | 可能因合约、脱锚或清算损失的本金 | 计算预期损失，并受安全门槛约束 |
| Capital Locked | 可取回但暂时不能使用的资金 | 计算流动性机会成本 |
| Time Cost | 研究、执行、维护和监控时间 | 独立展示，不默认折算时薪 |

### 5.2 硬成本

```text
Hard Cost
= Initial Interaction Cost
+ Maintenance Cost
+ Bridge and Swap Slippage
+ Claim Cost
+ Failed Transaction Buffer
```

输出最低可完成成本、推荐路径成本和最坏合理成本。推荐路径必须不超过每钱包 10 USDT；最坏合理成本明显超过 10 USDT 时不能直接 FARM。

### 5.3 资金风险

```text
Expected Capital Loss
= Capital at Risk
x P(Loss Event)
x Loss Given Event
```

重大资金安全问题不能被低期望损失平均掉，仍直接触发硬门槛。

```text
Liquidity Opportunity Cost
= Locked Capital
x Annual Opportunity Rate
x Locked Days / 365
```

第一版可展示机会成本区间，不强制固定统一年化率。

### 5.4 时间

```text
Total Time
= Shared Research Time
+ First Execution Time per Wallet x Wallet Count
+ Weekly Maintenance Time per Wallet x Wallet Count x Weeks
+ Claim and Exit Time
```

输出单钱包边际时间、组合共享时间、多钱包重复时间、总时间和每周维护时间。

```text
Expected Reward per Hour
= Risk-adjusted Expected Net Reward / Total Hours
```

时间效率独立展示，不设置固定时薪。组合每周维护超过 2 小时则不适配当前画像，最多 WATCH。

### 5.5 风险分类

- `Capital Security Risk`：本金、授权、合约、跨链和资产安全。
- `Eligibility Risk`：规则变化、快照、反女巫和资格取消。
- `Project Failure Risk`：停止开发、资金耗尽和团队失信。
- `Reward Dilution Risk`：参与增长、巨鲸、积分通胀和人均份额下降。
- `Liquidity Risk`：解锁、交易深度、领取和兑现困难。

每类风险输出等级、概率区间、影响、证据及是否触发硬门槛。

同一事实只能有一个主要计分归属。其他维度可引用该事实解释，但不能再次加减分。

### 5.6 净收益

```text
Expected Gross Reward
= P_reward x Conditional Realizable Reward

Expected Net Reward
= Expected Gross Reward
- Hard Cost
- Expected Capital Loss
- Liquidity Opportunity Cost
```

奖励稀释和兑现折价已经包含在条件奖励中，不得在净收益中重复扣除。

### 5.7 保守决策值

```text
Decision Value
= 50% x Conservative Net Reward
+ 40% x Base Net Reward
+ 10% x Optimistic Net Reward
```

```text
Capital Efficiency
= Decision Value / max(Hard Cost + Capital at Risk, minimum denominator)

Time Efficiency
= Decision Value / Total Hours
```

`Participation Priority` 由风险调整收益、时间适配和证据置信共同形成，只用于同标签内部排序，不得绕过硬门槛。

### 5.8 FARM 成本收益门槛

```text
Recommended Hard Cost <= $10 per wallet
Portfolio Weekly Maintenance <= 2 hours
Conservative Net Reward > $0 per wallet
Base Net Reward >= $30 per wallet
Base Reward-to-Cost Ratio >= 3
```

时间效率先用于排序。积累真实执行数据后，再决定是否增加固定门槛。

## 6. Project Quality

`Project Quality` 只衡量基本面，并作为项目存续概率、估值范围和失败风险的输入。

| 维度 | 权重 | 核心问题 |
|---|---:|---|
| 产品与真实需求 | 25% | 是否解决真实问题并产生持续使用 |
| 执行与增长 | 25% | 是否持续交付并形成健康增长 |
| 团队与治理 | 20% | 团队是否可信、能力匹配、权限合理 |
| 财务与可持续性 | 15% | 是否有资源活到兑现阶段 |
| 安全与透明度 | 15% | 资金与信息是否可验证且安全 |

### 6.1 产品与真实需求

优先观察可使用产品、用户留存、协议收入、真实链上活动、差异化和外部集成。只有官网、白皮书、测试网或合约痕迹时，不能自动视为高质量产品。

### 6.2 执行与增长

优先观察持续发布、路线图履约、用户留存、健康链上趋势、真实生态集成和事故响应。GitHub stars、最近 push、TVL 和合作海报不能独立代表执行质量。

### 6.3 团队与治理

优先观察可验证履历、历史交付、能力匹配、多签与关键权限、治理结构和事故处理。删除以下伪推断：

- `mainnet -> doxxed team`。
- `has URL -> non-anonymous team`。
- `recent funding -> tier-1 VC`。
- `high funding quality -> reliable team`。

### 6.4 财务与可持续性

观察融资、收入、资金消耗、国库、激励支出、最近融资时间和短期解锁压力。融资事实只在本维度形成基本面分，并作为其他模型的原始输入，不重复形成多个加分。

### 6.5 安全与透明度

观察审计范围、漏洞赏金、升级和暂停权限、多签、历史漏洞、跨链依赖、授权和退出机制，以及文档时效、官方渠道、Tokenomics、融资和链上指标的一致性。

有 Twitter、Discord 或白皮书只证明渠道存在，不代表内容透明或可信。

### 6.6 基本面门槛

FARM 至少要求：

```text
Project Quality >= 50
Project Failure Risk not high or critical
```

已确认跑路、挪用资金、重大造假、恶意合约、无法提款、未修复高危漏洞、冒充钓鱼、拒绝披露高度集中权限或主要团队解散时，直接阻断。

## 7. Evidence Confidence

### 7.1 分项置信度

分别计算：

- `event_confidence`
- `eligibility_confidence`
- `reward_confidence`
- `cost_confidence`
- `risk_confidence`
- `quality_confidence`

### 7.2 置信度组成

| 维度 | 权重 |
|---|---:|
| 来源可靠性 | 35% |
| 证据覆盖率 | 25% |
| 来源独立性 | 15% |
| 新鲜度与一致性 | 25% |

来源分级：

| 等级 | 来源 | 建议可信权重 |
|---|---|---:|
| A | 官方规则、官方文档、链上合约、正式 Tokenomics | 1.00 |
| B | 官方账号、官方合作平台、审计、可验证产品数据 | 0.80 |
| C | 可信研究、项目方访谈、可复核第三方数据 | 0.50 |
| D | 单一 KOL、社区传言、未验证截图 | 0.20 |
| U | 未知或无法验证 | 0.00 |

多个转载同一公告不算独立证据。冲突证据必须显式标记，优先采用等级更高、更新且可验证的来源，同时扩大区间并降低置信度。

### 7.3 事实类型

所有因子必须标记：

- `observed`：直接观测事实。
- `derived`：从事实确定性推导。
- `estimated`：基于历史或同类项目估计。
- `assumed`：缺数据时采用的保守假设。

`assumed` 不得表现为已知事实，也不能获得与官方数据相同的置信度。

### 7.4 不确定性处理

- 奖励、成本和概率缺失时扩大区间。
- FARM 使用区间下界，低置信度自然降低推荐概率。
- 多钱包规则、参与状态、硬成本、资金退出、空投依据或维护频率未知时，最多 WATCH。
- 缺失数据不默认填充中性 50 分。

### 7.5 总体置信度

```text
Overall Confidence
= 30% x min(critical confidences)
+ 70% x weighted_average(all confidences)
```

FARM 门槛：

```text
overall_confidence >= 0.65
event_confidence >= 0.70
eligibility_confidence >= 0.65
cost_confidence >= 0.70
risk_confidence >= 0.70
reward_confidence >= 0.50
```

## 8. 硬门槛与标签

### 8.1 内部状态

| 状态 | 含义 | 对外标签 |
|---|---|---|
| ACTIONABLE | 现在值得执行 | FARM |
| MONITOR | 有潜力，等待条件成熟 | WATCH |
| INSUFFICIENT_EVIDENCE | 关键证据不足 | WATCH |
| NOT_FIT | 不符合当前画像或收益要求 | IGNORE |
| BLOCKED | 安全、诚信或规则否决 | IGNORE + 风险警告 |

### 8.2 数据可判定性

至少需要确认官方身份、参与状态、可信空投逻辑、任务路径、硬成本、维护频率、多钱包规则、资金授权与退出方式，以及 3-6 个月内的潜在兑现催化剂。

关键项缺失时为 `INSUFFICIENT_EVIDENCE`。官方身份无法确认或入口疑似钓鱼时直接 `BLOCKED`。

### 8.3 一票否决

以下情况不能 FARM：

- 恶意合约、钓鱼、无法提款、重大未修复漏洞或高风险签名。
- 明确一人一钱包、唯一人格、独立 KYC 或禁止同一用户多地址。
- 没有满足要求的可信空投证据。
- 推荐路径硬成本超过 10 USDT，或组合每周维护超过 2 小时。
- 经可靠证据确认的跑路、挪用、履历造假、虚假融资、虚假合作或蓄意数据造假。

匿名团队本身不构成否决，但需要更强的产品、安全和链上证据。

### 8.4 FARM 完整条件

项目必须同时满足：

- 所有硬门槛通过。
- 概率门槛通过。
- 成本、净收益和收益成本比门槛通过。
- 置信度门槛通过。
- `Project Quality >= 50`。
- `Project Failure Risk` 不是 high 或 critical。
- 当前任务可执行且评分未过期。

### 8.5 WATCH 原因码

- `WAIT_TASK_OPEN`
- `WAIT_RULES`
- `WAIT_CATALYST`
- `WAIT_COST_DROP`
- `WAIT_MORE_EVIDENCE`
- `WAIT_EARLY_ENTRY`
- `REWARD_TOO_UNCERTAIN`
- `SINGLE_WALLET_ONLY`

每个 WATCH 项目必须包含升级为 FARM 的条件、下一次复查时间和需监控的官方信号。

### 8.6 IGNORE 和 BLOCKED 原因码

- `NEGATIVE_EXPECTED_VALUE`
- `DUST_REWARD`
- `TOO_EXPENSIVE`
- `TOO_TIME_INTENSIVE`
- `TOO_LATE`
- `NO_AIRDROP_CASE`
- `PROJECT_INACTIVE`
- `PROFILE_MISMATCH`
- `SAFETY_BLOCK`
- `INTEGRITY_BLOCK`
- `RULE_BLOCK`

### 8.7 排序

标签先由门槛决定，排序只在同标签内部执行。

FARM 排序：

1. `Decision Value` 降序。
2. 保守净收益降序。
3. 时间效率降序。
4. Overall Confidence 降序。
5. 下一截止时间升序。

WATCH 排序：

1. 升级 FARM 所需条件数量升序。
2. `P_event.base` 降序。
3. 潜在 `Decision Value` 降序。
4. 下一复查时间升序。

## 9. 小规模验证行动

新 FARM 项目采用风险控制流程：

```text
候选项目
  -> 研究与安全检查
  -> 1-2 个钱包试运行
  -> 记录真实成本、时间和任务状态
  -> 对比模型估计
  -> 决定是否扩展到 3-10 个钱包
```

扩展条件：

- 实际硬成本没有超过模型基准上界。
- 任务和规则与采集信息一致。
- 没有新增资金授权风险。
- 单钱包执行时间可接受。
- 多钱包规则没有新增冲突。
- 扩展后组合每周维护不超过 2 小时。
- 项目重评后仍满足 FARM 门槛。

任一条件失败时暂停扩展，FARM 降为 WATCH 并记录原因。该流程用于控制资金和时间风险，不用于规避反女巫检测。

## 10. 数据模型

### 10.1 Evidence

```text
evidence_id
project_id
factor_key
value
value_type
source_url
source_type
source_grade
observed_at
effective_at
expires_at
verification_status
independence_group
raw_snapshot_ref
```

原始证据只追加，不覆盖。新证据可以将旧证据标记为失效，但保留历史。

### 10.2 Factor Observation

```text
factor_key
normalized_value
value_range_low
value_range_high
observation_type
confidence
evidence_ids
calculated_at
valid_until
```

### 10.3 模型输出

每个概率、奖励、成本和风险输出保存 `low/base/high`、`confidence`、`model_version` 和 `factor_snapshot_id`。

核心输出包括：

- `P_event`、`P_eligibility`、`P_survival`、`P_reward`。
- 三档条件奖励。
- 成本区间、风险本金、预期损失、每周维护时间和总时间。
- Project Quality、五类风险和六类置信度。

### 10.4 决策结果

```text
decision_status
public_label
priority_score
blocker_codes
watch_reason_codes
ignore_reason_codes
decision_value
recommended_action
review_at
expires_at
scored_at
model_version
profile_version
```

### 10.5 真实执行与结果

```text
project_id
wallet_cohort_id
started_at
tasks_completed
actual_hard_cost
actual_time_minutes
eligibility_result
disqualification_reason
reward_received
reward_value_at_claim
realized_value
claim_cost
outcome_observed_at
```

系统不存储钱包私钥或敏感身份信息。钱包只使用本地匿名 cohort 标识。

## 11. 用户画像

默认画像：

```text
profile_id: low-cost-curated-multiwallet-v1
wallet_count: 3-10
hard_cost_limit_per_wallet: 10 USD
weekly_time_limit_per_project: 2 hours
evaluation_horizon: 3-6 months
strategy: compliant curated multi-wallet
loss_preference: conservative
```

未来可以新增零成本、低成本、中等资金和单钱包画像。同一项目针对不同画像可以产生不同标签，不需要修改底层证据。

## 12. 更新与过期

事件触发立即更新：

- 官方活动、多钱包、KYC 和反女巫规则。
- 快照、Season、截止时间和任务关闭。
- 合约地址、授权、提款和安全事件。
- Tokenomics、TGE、项目停止服务。

每日更新：

- 任务状态、Gas、跨链成本、参与人数、积分、排名、TVL、收入和公告。

每周更新：

- GitHub 与产品交付、路线图履约、用户留存、生态集成、稀释估计、Project Quality 和奖励情景。

每月或事件触发更新：

- 团队、融资、治理、审计、历史可比项目和模型参数。

默认有效期：

| 标签 | 有效期 |
|---|---|
| FARM | 24-72 小时 |
| WATCH | 7 天 |
| IGNORE | 30 天 |
| BLOCKED | 直到出现可信修复证据 |

关键证据过期后，FARM 进入 `STALE`，停止展示立即执行并触发重评。

## 13. 校准与验证

### 13.1 预测快照

每次评分冻结当时的模型版本、画像、因子快照、概率区间、奖励情景、成本、时间和标签。真实结果通过 outcome 追加，禁止覆盖历史预测。

### 13.2 安全与错误控制

首要指标：

- FARM 负净收益率。
- FARM 资金安全事件率。
- FARM 规则阻断遗漏率。
- FARM 成本超预算率。

初始目标：

```text
FARM negative net return rate < 20%
Severe capital safety false recommendation = 0
Explicit multi-wallet rule false recommendation = 0
Hard cost overrun rate < 15%
```

### 13.3 概率校准

分别验证 `P_event`、`P_eligibility`、`P_survival` 和 `P_reward`，使用 Brier Score、分箱校准、Expected Calibration Error 和可靠性图。

### 13.4 区间质量

验证真实奖励、成本和时间落入预测区间的比例、区间宽度、保守情景高估率和基准偏差。

### 13.5 排序质量

验证单位时间实际净收益、Top-K 实际净收益、FARM 相对 WATCH 的收益提升，以及 `Decision Value` 排序的收益单调性。

核心业务指标是用户每小时实际风险调整净收益。

### 13.6 校准样本

钱包不是完全独立样本。项目级验证是否发生分配、兑现时间、项目失败和安全事件；钱包 cohort 级验证资格率、审查通过率、成本、时间和奖励。

首次正式校准建议至少满足：

- 30-50 个已兑现或确认未兑现的独立项目。
- 200 个钱包 cohort 结果。
- 至少 3 个主要赛道。
- 覆盖 FARM、WATCH 和 IGNORE。
- 跨越完整的 3-6 个月窗口。

主观反馈只用于解释和体验优化，不能代替真实结果。

## 14. 与现有模型的迁移

| 当前因子 | 新归属 | 处理 |
|---|---|---|
| airdrop_signal | P_event + P_eligibility | 拆分，不再作为质量总分 |
| narrative_timing | 奖励估值 + 稀释 + 兑现窗口 | 双向建模 |
| team_reputation | Project Quality: 团队与治理 | 删除伪推断 |
| risk | 五类风险 | 拆分并去重 |
| tokenomics | 奖励兑现 + 流动性风险 | 无真实数据时不生成精确推测 |
| competition | 奖励稀释 | 改为实际参与竞争 |
| execution | Project Quality: 执行与增长 | 使用趋势与履约 |
| transparency | Project Quality + Evidence Confidence | 区分公开程度和可靠程度 |

废弃“同赛道项目数量等于空投竞争度”的定义。真正竞争因子是同一项目的参与钱包、有效资格钱包、积分增长、排名分布、巨鲸集中度和奖励池相对参与规模。

新模型使用独立版本：

```text
legacy model: score-v1.4
new model: opportunity-v2.0
profile: low-cost-curated-multiwallet-v1
```

这不是一次简单调权，不应覆盖现有 `weight_version=v1`。

## 15. 上线策略

采用 Shadow 模式：

1. 当前八维模型继续对用户可见，新模型旁路计算和保存。
2. 检查字段覆盖、证据不足比例、FARM 数量、区间解释和新旧分歧。
3. 界面并列展示旧分数和新机会评估，人工审核全部新 FARM。
4. 对少量项目执行 1-2 钱包验证并记录真实成本与时间。
5. 结果样本充分后校准，新模型成为主决策，旧模型退为 Project Quality 参考。

## 16. 完成定义

模型必须能对每个项目回答：

1. 为什么认为 3-6 个月内可能发生社区分配？
2. 低成本精品钱包为什么可能满足资格？
3. 多钱包规则和最终审查风险是什么？
4. 条件奖励的保守、基准和乐观区间是什么？
5. 单钱包和组合需要多少钱、多少时间？
6. 保守与基准净收益是多少？
7. 哪些是直接观测、推导、估计或假设？
8. 哪些风险会阻断参与？
9. 为什么是 FARM、WATCH 或 IGNORE？
10. 下一步行动、升级条件和复查时间是什么？
11. 真实结果如何验证当时预测？

满足以上要求，才视为 `opportunity-v2.0` 第一版评分设计完整。
