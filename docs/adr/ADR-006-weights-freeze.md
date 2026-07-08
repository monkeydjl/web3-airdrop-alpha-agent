# ADR-006: 评分权重初值冻结与校准策略

- **Status**: Accepted
- **Date**: 2026-07-08
- **Deciders**: 架构 / 产品 / 数据

## 背景

评分引擎的 6 个子分权重（airdrop_signal / narrative_timing / team_reputation / risk / tokenomics / competition）初值如何确定，以及后续能否、何时、如何调整，是直接影响评分可信度与可解释性的架构级决策。MVP 阶段没有任何真实反馈数据，权重若频繁变动会导致：

- 历史评分不可比（同一项目昨天 FARM 今天 IGNORE，无法回溯）；
- golden 回归集（§14.6）失去锚点，隐性评分漂移无法发现；
- 用户对系统信任度下降（"评分为什么变"无法解释）。

同时，初值只是经验估计，必然需要随用户反馈校准（§7.9 / §24）。需要明确"何时冻结、何时开放、如何开放"。

## 决策

1. **MVP 权重冻结在经验初值**，由 `config.WeightsConfig` 硬编码，启动断言 `Σ=1.0`：
   | 子项 | 权重 |
   | --- | --- |
   | airdrop_signal | 0.20 |
   | narrative_timing | 0.20 |
   | team_reputation | 0.15 |
   | risk | 0.15 |
   | tokenomics | 0.15 |
   | competition | 0.15 |

2. **MVP 不提供任何运行时改权重接口**（与 SECURITY §2 Elevation of Privilege 缓解一致）。权重变更必须改代码 + PR + 本 ADR 索引。

3. **权重版本化**：`ScoreResult.weight_version`（默认 `"v1"`）与 `projects.weight_version` 字段记录所用权重版本，回测可按版本溯源（§5.4.4 `project_history`、§5.4.6 `weight_changelog`）。

4. **校准窗口在 V2 打开**，流程（§7.9）：
   - 采集用户反馈与事后标注（feedback 表）；
   - `backtest.py` 离线重算候选权重，目标函数 `recall(FARM) − 2×false_positive(FARM)`；
   - 新权重写入 `config.weights_v2` **灰度双跑对比 ≥1 周**；
   - 样本 ≥200 才触发首次校准（统计显著性）；
   - 每次切换必记 `weight_changelog`（旧值/新值/触发样本数/指标对比），禁止无声漂移。

5. **任何权重默认值 / 阈值初值变更都需新增或更新 ADR**（见 adr/README.md「何时新增 ADR」）。

## 理由

| 备选 | 否决理由 |
| --- | --- |
| MVP 即开放运行时调权 | 无数据支撑易引入系统性偏差；破坏 golden 集锚点与可解释性 |
| 初值用 LLM/数据驱动自动定权 | MVP 无反馈数据，自动定权即拟合噪声；且不可审计 |
| 权重变更无需 ADR / 灰度 | 不可回溯、不可对比，评分漂移无法归因 |
| **冻结初值 + V2 校准闭环（本决策）** | MVP 评分稳定可解释；V2 有数据后科学校准，全程留痕 |

## 后果

- MVP 评分偏差只能通过改代码修复，需 PR review，不能热改（可接受，因 MVP 阶段本就迭代快、数据少）。
- 权重版本字段贯穿 DB / logs / 回测，实现时必须写入（DATABASE_DDL §2.1 已含 `weight_version`）。
- V2 校准需提前埋点（§24.1 feedback/events 表），否则冷启动无样本。
- 首次正式校准（V2，样本 ≥200）是明确里程碑，对应 TASK_BREAKDOWN W11。
