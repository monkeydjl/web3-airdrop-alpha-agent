# 评分业务知识

> 引用键：`KN:business:scoring`
> 来源：`docs/DATA_SCORING_DICT.md`
> 更新：2026-07-08

## 概述

评分系统是 Web3 Airdrop Alpha Agent System 的核心，用于评估早期项目的空投参与价值。

## 评分等级

| 等级 | 标签 | 分数范围 | 含义 |
| --- | --- | --- | --- |
| 1 | FARM | 70-100 | 建议积极参与空投 |
| 2 | WATCH | 50-69 | 建议观察，等待更多信号 |
| 3 | IGNORE | 0-49 | 建议忽略，风险大于收益 |

> 阈值以代码 `backend/app/agents/scorer.py` 的 `LABEL_THRESHOLDS = [(70,"FARM"),(50,"WATCH"),(0,"IGNORE")]` 为准。

## 评分子项（6 维）

| 子项 | 权重 | 来源 Agent | 说明 |
| --- | --- | --- | --- |
| airdrop_signal | 0.20 | Collector | 空投信号强度 |
| narrative_timing | 0.20 | Narrative | 赛道时机 |
| team_reputation | 0.15 | Team | 团队信誉 |
| risk | 0.15 | Risk | 综合风险 |
| tokenomics | 0.15 | Tokenomics | 代币经济 |
| competition | 0.15 | Scorer | 竞争度（反向） |

## 计算公式

```
score = Σ(sub_score_i × weight_i) × 100
```

## 降级规则

- 缺失字段 ≥ 3 → confidence < 0.5 → label 降一档
- LLM 调用失败 → 回退规则引擎
- 数据源不可用 → 使用缓存数据（TTL 内）

## Reason 生成规则

- FARM：≥ 2 条 reason，含 ≥ 1 正向信号
- WATCH：≥ 2 条 reason，混合正负信号
- IGNORE：≥ 2 条 reason，含 ≥ 1 反向信号
- 缺失字段必含 `"* missing/uncertain"` 标记

## 相关引用

- [KN:technical:agent-pipeline] — Agent 执行流程
- [KN:technical:concurrency] — 并发控制
- [KN:decision:ADR-006] — 权重冻结决策
