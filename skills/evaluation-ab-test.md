# Skill：权重校准与效果评估

## 目标
评估评分策略变更的效果（新权重 vs 冻结权重、LLM 增强 vs 规则降级），遵循
`docs/WEIGHT_CALIBRATION.md` 与 `docs/adr/ADR-006-weights-freeze.md`。

> **现状提醒（旧文档骗过人）**：
> - 仓库里**没有 `evaluation/experiments/`、也没有 `evaluation/results/`**。
>   `evaluation/` 目前只有 `README.md` 和 `llm/template_validation.py`
>   （`evaluation/README.md` 里画的 `scoring/`、`feedback/` 也还不存在）。
> - **没有按请求分流的 A/B 框架**。本仓真正在跑的是**离线权重校准**
>   （`backend/app/calibration.py`）+ **live/backtest 分桶回测**，不是线上流量实验。
> - 权重不在 `config.py` 里：真相源是 `backend/app/agents/scorer.py` 的
>   `WEIGHTS` 与 `LABEL_THRESHOLDS`。

## 适用场景
- 评估候选权重是否优于冻结权重（ADR-006）
- 对比 LLM 增强 vs 规则降级的产出质量
- 上线前用历史样本回测

## 输入要求
- 文件：`docs/WEIGHT_CALIBRATION.md` §3–§7（目标函数与门禁的真相源）
- 文件：`docs/adr/ADR-006-weights-freeze.md`
- 文件：`backend/app/calibration.py`（校准引擎）
- 目录：`backend/app/opportunity/calibration/`（`loader` / `metrics` / `outcomes` / `advice` / `report`）
- 文件：`backend/app/agents/scorer.py`（`WEIGHTS`、`LABEL_THRESHOLDS`）

## 校准引擎的硬性事实
| 项 | 值 | 位置 |
| --- | --- | --- |
| 最小有效样本 | `MIN_VALID_SAMPLES = 200` | `app/calibration.py` |
| 其中 FARM 相关 | `MIN_FARM_SAMPLES = 30` | 同上 |
| 单维最大变化 | `MAX_DIM_CHANGE = 0.10` | 同上 |
| 搜索步长 | `SEARCH_STEP = 0.05` | 同上 |
| 随机采样数 | `DIRICHLET_SAMPLES = 2000` | 同上 |
| 目标函数 | `J = recall(FARM) − 2 × false_positive_rate(FARM)` | 同上 / WEIGHT_CALIBRATION.md §4 |
| 约束 | Σ权重 = 1.0 | 同上 |
| 候选落地 | 写 `weight_changelog` 表，`status='candidate'` | 同上 |
| 就绪查询 | `GET /api/v1/feedback/calibration/status` → `calibration_ready` | `routers/v1/feedback.py` |

**校准只重加权，不改子分**：样本里的子分是固定的，搜索空间只有权重向量。

## 执行步骤

### Step 1: 确认样本够
- 操作：查 `GET /api/v1/feedback/calibration/status`，看 `calibration_ready`
- 验证：门禁不满足就别跑搜索 —— 200/30 这两个数字是刻意设的，
  `feedback.py` 里还专门防了「伪造 ID 灌满门禁」的路子，不要绕过它

### Step 2: 跑校准
- 操作：调 `app/calibration.py` 的搜索入口，产出候选权重
- 验证：
  - 候选必须满足 Σ=1.0 且单维变化 ≤ 0.10
  - 结果写进 `weight_changelog`（`status='candidate'`），**不直接替换 `WEIGHTS`**

### Step 3: 分桶回测
- 操作：用 `backend/app/opportunity/calibration/` 下的模块做 live / backtest 分桶对比
- 验证：live 桶与 backtest 桶分别看指标，别把两个桶的样本混起来算平均

### Step 4: 埋点与归因
- 操作：structlog `agent.*` / `pipeline.*` 事件带上分组标签；指标沿用 `airdrop_*` 命名（§14）
- 验证：事件名先从代码确认再写文档，调用点保留字面量（本仓反复踩过这条）

### Step 5: 决策与落地
- 操作：显著优于对照才把候选提升为生效权重；结论写进
  `docs/WEIGHT_CALIBRATION.md` 或新 ADR
- 验证：
  - 改 `WEIGHTS` / `LABEL_THRESHOLDS` 会牵动 golden 测试
    （`backend/tests/golden/test_golden_cases.py`）与校准相关测试，必须一起过
  - ADR-006 是「冻结」决策，替换冻结值属于决策变更，要有 ADR 记录

## 输出
- 文件：`backend/app/calibration.py` / `backend/app/opportunity/calibration/*`（如改算法）
- 文件：`backend/app/agents/scorer.py`（如替换权重）
- 文件：`docs/WEIGHT_CALIBRATION.md`（结论与新基线）
- 文件：`docs/adr/ADR-0XX-*.md`（如构成决策变更）

## 检查清单
- [ ] 未引用不存在的 `evaluation/experiments/` / `evaluation/results/`
- [ ] 对照组是 ADR-006 冻结权重
- [ ] 样本门禁（≥200 有效、≥30 FARM）真实满足，未绕过
- [ ] 候选满足 Σ=1.0 且单维变化 ≤ 0.10
- [ ] 候选先入 `weight_changelog`，未直接改生效权重
- [ ] live / backtest 分桶未混算
- [ ] golden 与校准测试全绿
- [ ] 结论文档化

## 参考
- `docs/WEIGHT_CALIBRATION.md`
- `docs/adr/ADR-006-weights-freeze.md`
- `backend/app/calibration.py`（常量与目标函数都在文件头）
- `CONVENTIONS.md §14 Prometheus 指标`
