# Skill：A/B 测试配置（V2）

## 目标
为 V2 评分/推荐策略配置 A/B 测试，对比不同权重或 Agent 组合的效果，遵循 docs/evaluation 与 ADR-006-weights-freeze.md。

## 适用场景
- 评估新权重集 vs 冻结权重（ADR-006）
- 对比 LLM 增强 vs 规则降级
- 上线前小流量验证

## 输入要求
- 文件：`docs/adr/ADR-006-weights-freeze.md`
- 文件：`evaluation/`（评估脚本/数据）
- 文件：`backend/app/config.py`（权重配置）
- 信息：实验组/对照组、指标、流量比

## 执行步骤

### Step 1: 定义实验
- 操作：在 `evaluation/experiments/` 定义 YAML/JSON 配置：分组、权重集、流量分配
- 验证：对照组使用 `WeightsConfig` 冻结值（ADR-006），实验组为候选值

### Step 2: 注入变体
- 操作：在 `backend/app/config.py` 支持按请求/`experiment_id` 加载权重变体
- 验证：默认仍走冻结权重，不影响主路径

### Step 3: 埋点与指标
- 操作：用 structlog `agent.*`/`pipeline.*` 事件记录分组标签，指标对齐 `airdrop_*`（§14）
- 验证：日志含 `experiment_id` 标签，便于归因

### Step 4: 评估与决策
- 操作：跑 `evaluation/` 脚本对比准确率/可解释性（§9.6），结果写入 ADR 或评估文档
- 验证：显著优于对照才考虑替换冻结权重

## 输出
- 文件：`evaluation/experiments/<name>.yaml`
- 文件：`backend/app/config.py`（变体加载）
- 文件：`evaluation/results/<name>.md`

## 检查清单
- [ ] 对照组为 ADR-006 冻结权重
- [ ] 默认路径不受影响
- [ ] 日志含 `experiment_id` 标签
- [ ] 指标对齐 `airdrop_*` 命名
- [ ] 结论文档化

## 参考
- `docs/adr/ADR-006-weights-freeze.md`
- `evaluation/`
- `CONVENTIONS.md §14 Prometheus 指标`
