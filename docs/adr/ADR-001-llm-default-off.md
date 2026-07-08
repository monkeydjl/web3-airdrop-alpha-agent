# ADR-001: MVP 默认关闭 LLM，作为可选插件

- **Status**: Accepted
- **Date**: 2026-07-08
- **Deciders**: 架构 / 产品

## 背景

LLM 可提升 Narrative/Team 文本研判质量，但引入：
- 外部依赖（OpenAI API 可用性、网络）
- 成本（按 token 计费，调用量不可控时易超支）
- 延迟（单次 1–8s，拖慢 pipeline）
- 不可解释性（自由文本输出难以审计与回归测试）

MVP 阶段首要目标是跑通 pipeline、保证可演示与可解释，而非追求最高研判质量。

## 决策

MVP 默认**规则引擎**（无外部依赖、可离线演示）。
当 `OPENAI_API_KEY` 存在且 `LLMConfig.enabled=true` 时，启用 LLM 增强作为**可选插件**：
- 每个 Agent 暴露 `llm_enhance()` 钩子
- LLM 失败/超时自动回退规则引擎，不中断主流程
- LLM 修正值有界，防单次调用打飞分数

## 理由

| 备选 | 否决理由 |
| --- | --- |
| 默认开 LLM | 离线无法演示、成本不可控、CI 不稳定 |
| 完全不接 LLM | 放弃质量增强空间，V2 仍要接，不如 MVP 就预留钩子 |
| **可选插件（本决策）** | 兼顾离线可演示 + 后续质量增强 |

## 后果

- `BaseAgent` 需暴露 `llm_enhance()` 钩子，子类按需 override。
- 需设计降级链与成本控制（见 Roadmap §19）。
- 测试需覆盖"LLM 开/关"两路径，golden 回归集需双版本快照。
- Prompt 模板版本化（`prompt_version` 写入 logs），便于回溯偏差。
- 权重校准（§7.9）需区分"规则 vs LLM"样本，避免混淆评估。
