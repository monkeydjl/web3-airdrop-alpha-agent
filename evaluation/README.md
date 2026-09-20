# Evaluation — 评估

> 本目录存放项目评估相关内容，包括 LLM 评估、评分质量评估、用户反馈质量分析等。
>
> 参考：`docs/ENGINEERING_ROADMAP.md §19.6`（LLM 评估机制）

---

## 目录结构

```
evaluation/
├── README.md               # 本文档
└── llm/                    # LLM 评估与模板校验工具
    └── template_validation.py
```

> **各评估模块实际位置说明**：
> - **历史回测与样本回填**：脚本位于 `backend/scripts/run_backtest.py` 与 `backend/scripts/backfill_historical_samples.py`；历史样本库位于 `backend/data/backtest/airdrops_2024_2025.json`。
> - **权重与机会校准**：校准核心引擎位于 `backend/app/calibration.py`；校准与验证脚本位于 `backend/scripts/calibrate_weights.py`、`backend/scripts/calibrate_opportunity.py`、`backend/scripts/verify_opportunity_calibration.py`。
> - **用户反馈质量闭环**：通过数据库 `feedback` 表与 API 端点 `GET/POST /api/v1/feedback` 持久化流转。

## 评估范围

| 评估类型 | 频率 | 工具 | 触发条件 |
| --- | --- | --- | --- |
| LLM 质量 | 每周 | `evaluation/llm/template_validation.py` | 周日 cron |
| 评分一致性 | 每次 run | 内置断言 | pipeline 完成后 |
| 权重校准 / 回测 | 样本 ≥200 (回测样本 50 条) | `backend/scripts/run_backtest.py` / `backend/app/calibration.py` | V2 反馈闭环 / 历史验证 |
| 数据质量 | 每日 | 完整性/时效性检查 | 每日 run 后 |

---

_文档版本：v1.1 · 2026-09-20_
