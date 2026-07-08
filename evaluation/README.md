# Evaluation — 评估

> 本目录存放项目评估相关内容，包括 LLM 评估、评分质量评估、用户反馈质量分析等。
>
> 参考：`docs/ENGINEERING_ROADMAP.md §19.6`（LLM 评估机制）

---

## 目录结构

```
evaluation/
├── README.md               # 本文档
├── llm/                    # LLM 评估报告
│   ├── 2026-07-08_benchmark.md
│   └── template_validation.py
├── scoring/                # 评分质量评估
│   └── backtest_results/   # 回测结果
└── feedback/               # 用户反馈质量分析
    └── user_satisfaction/
```

## 评估范围

| 评估类型 | 频率 | 工具 | 触发条件 |
| --- | --- | --- | --- |
| LLM 质量 | 每周 | `evaluation/llm/template_validation.py` | 周日 cron |
| 评分一致性 | 每次 run | 内置断言 | pipeline 完成后 |
| 权重校准 | 样本 ≥200 | `backtest.py` | V2 反馈闭环 |
| 数据质量 | 每日 | 完整性/时效性检查 | 每日 run 后 |

---

_文档版本：v1.0 · 2026-07-08_
