# 评分权重校准协议（Weight Calibration Protocol）

> 引用：ADR-006、`DATA_SCORING_DICT.md`、`ENGINEERING_ROADMAP.md` §7.9 / §24、`feedback` 表、`GOLDEN_TEST_CASES.md`
> 阶段：V2 校准窗口（MVP 权重冻结）
> 更新：2026-07-13

---

## 1. 原则（继承 ADR-006）

1. **MVP / 当前默认权重冻结为 v1**，仅能通过代码 PR 变更，**无**运行时调权 API。
2. 每次生效权重必须有 **`weight_version`**（写入 `ScoreResult` / `projects.weight_version`）。
3. 校准必须 **可审计**：`weight_changelog` 记录旧值、新值、样本、指标。
4. **Golden 是回归锚点**：新权重上线前 Golden 全量必须通过或显式修订用例并记 ADR。

---

## 2. 当前冻结权重（v1.2 八维）

| 子项 | 权重 |
|------|------|
| airdrop_signal | 0.18 |
| narrative_timing | 0.15 |
| execution | 0.13 |
| team_reputation | 0.12 |
| risk | 0.12 |
| tokenomics | 0.10 |
| competition | 0.10 |
| transparency | 0.10 |

> v1 曾为六维（0.20/0.20/0.15×4）。v1.2 增加 `execution` 与 `transparency`，与
> `DATA_SCORING_DICT.md §4` 一致。本表随代码同步，**以 `config.py` 为准**。

配置：`backend/app/config.py` 中 `weight_*` 字段；启动校验 Σ=1.0（容差按代码）。

`weight_version` 默认取自 `settings.weight_version`（当前 `"v1.2"`）。此前该值硬编码在
`agents/scorer.py`，配置改了、落库版本号不变，与 §1.2「每次生效权重必须有 weight_version」
的可审计意图相悖；ADR-014 改为从配置读取，并补齐了 `repository.save` UPSERT 中缺失的
`weight_version` 与 `raw_signals` 两列（此前重算后这两列仍留旧值）。

---

## 3. 反馈数据契约

### 3.1 信号与 outcome

| 字段 | 取值 | 用途 |
|------|------|------|
| `signal` | `useful` / `useless` / `wrong_label` / `correct_outcome` | 用户对当次评分的态度 |
| `correct_label` | `FARM`/`WATCH`/`IGNORE`（wrong_label 时） | 监督信号 |
| `outcome` | `airdropped` / `not_airdropped` / `pumped` / `dumped` | 事后事实（延迟标注） |
| `note` | 自由文本 | 审计，不直接进目标函数 |

### 3.2 样本计入规则

| 条件 | 是否计入校准样本 |
|------|------------------|
| `wrong_label` + 有效 `correct_label` | ✅ 强监督 |
| `outcome` 非空 | ✅ 结果监督 |
| 仅 `useful` / `useless` | 🟡 弱信号（权重 0.3，或仅用于分层分析） |
| 同一 user+project 7 日内重复 | 只保留最新一条 |
| 匿名刷量（若未来有 user_id） | 需速率限制后再计 |

### 3.3 首次校准门槛

| 门槛 | 值 | 说明 |
|------|-----|------|
| 最小有效样本 | **≥ 200** | ADR-006；`wrong_label`+`outcome` 合计优先 |
| 其中 FARM 相关 | 建议 ≥ 30 | 避免全 IGNORE 偏置 |
| 时间窗 | 建议最近 90 天 | 叙事周期漂移 |

未达标：**禁止**切换默认 `weight_version`；可离线实验但不合并主配置。

---

## 4. 目标函数与搜索

### 4.1 主目标（与 ADR-006 一致）

```
J = recall(FARM) − 2 × false_positive_rate(FARM)
```

定义（在带 `correct_label` 或可映射 outcome 的集合上）：

- **FARM 召回**：真实应为 FARM 的样本中，系统预测为 FARM 的比例
- **FARM 假阳**：预测 FARM 但真实非 FARM 的比例

辅助监控（不单独作为切换条件，但报告必出）：

- WATCH 混淆矩阵
- 分数分布漂移（KS 或分位对比）
- 与 v1 的 label 翻转率（同项目重算）

### 4.2 搜索空间（V2 初版）

- 六个权重：单纯形 Σ=1.0，每维步长 0.05，或 Dirichlet 随机 + 局部爬山
- **禁止**单次任维变化 &gt; 0.10（相对 v1）——防止剧烈漂移；更大变更需新 ADR
- 阈值（FARM/WATCH 分界）若与权重联调，变更必须写入 changelog 与 Golden

### 4.3 离线流程

```
1. 导出 feedback + 对应 projects 快照（含子分，便于重加权）
2. 固定 Agent 子分，仅重算加权总分与 label（快路径）
3. 网格/随机搜索最大化 J
4. 对候选权重跑 Golden 全量
5. 记录候选 → weight_changelog 状态=candidate
6. 灰度双跑 ≥ 7 天（见 §5）
7. 达标则 PR 改 config 默认 + weight_version=v2（或 v1.1）
```

工具位置：`backend/scripts/calibrate_weights.py`（`make calibrate`）。

- 默认：样本门禁报告，**不改**生产权重
- 样本不足（默认 &lt;200）：`RESULT: GATE_NOT_MET`
- 达标后：`--search` 记录 baseline 到 `weight_changelog`（全量子分重加权需后续 snapshot）

---

## 5. 灰度与切换门禁

| 阶段 | 要求 |
|------|------|
| Shadow | 新权重只写旁路字段或日志，不改用户可见 label |
| 双跑 ≥ 1 周 | 对比 J、FARM 量、用户 wrong_label 率 |
| 切换 | PR + Review；更新 ADR-006 索引或新 ADR；changelog `status=active` |
| 回滚 | 保留上一 `weight_version` 配置；一键回退 config + 可选批量 re-score |

切换后：

- 新 run 使用新权重
- 历史行保留旧 `weight_version`（**不**强制全库重算；提供批量 re-score 运维接口可选）

---

## 6. 与 Golden 的关系

| 情况 | 处理 |
|------|------|
| 新权重导致 Golden 失败 | **默认不合并**；若规则语义故意变更 → 先改 `DATA_SCORING_DICT` + Golden 期望 + 记 ADR |
| 仅数值边界 flaky | 收紧用例或固定 seed，禁止静默改权重过关 |
| 冷启动无反馈 | 继续 v1；用 seed + Golden 守回归 |

### 6.1 已执行的 Golden 修订记录

| 日期 | 触发 | 处理 |
|------|------|------|
| 2026-07-26 | ADR-014：实现回归规范（跨源合并、`tokenomics.risk`、confidence 口径、`airdrop_signal` 单一实现） | 12 个 Golden 用例期望值全部修订；`test_golden_cases.py` 的 confidence 断言由「下限 ≥0.45」改为「与期望值偏差 ≤0.10」（**收紧**，非放松）。权重未变，变的是子分算法与规范的一致性 |

> 该次修订严格按本节协议执行：先改 `DATA_SCORING_DICT`（§5.8、§6.1、Opportunity v2 gates）→
> 再改 Golden 期望 → 记 ADR-014，并附 264 项 / 270 项双跑对比数据。

---

## 7. weight_changelog 最小字段

| 字段 | 含义 |
|------|------|
| `from_version` / `to_version` | 如 v1 → v2 |
| `weights_json` | 六维新权重 |
| `sample_size` | 有效样本数 |
| `metrics_json` | J、recall、FPR、Golden pass |
| `triggered_by` | human / scheduled_job |
| `created_at` | UTC |

---

## 8. 冷启动与功能开关

| 项 | 约定 |
|----|------|
| 无反馈期 | 始终 `weight_version=v1` |
| `enable_feedback_system` | 控制反馈 API/UI；校准脚本可直读 DB |
| 埋点 | 详情页反馈 + 可选 events；保证 W11 前样本可积累 |

---

## 9. 检查清单（首次校准发布）

- [ ] 有效样本 ≥ 200
- [ ] 离线 J 相对 v1 提升，且 FPR 未恶化超协议阈值
- [ ] Golden 100% 或已文档化修订
- [ ] changelog 已写
- [ ] 灰度 ≥ 7 天报告附件
- [ ] config 与 `DATA_SCORING_DICT` §4 同步
- [ ] MEMORY / IMPLEMENTATION_STATUS 更新 weight_version

---

## 10. 非目标

- 运行时用户自调权重
- 无监督纯 LLM 定权
- 用单日反馈热更新生产权重

---

_文档版本：v1.1 · 2026-07-14 · 校准脚本骨架已落地_
