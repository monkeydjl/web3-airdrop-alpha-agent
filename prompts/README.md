# ──────────────────────────────────────────────
# Prompt Management System
# ──────────────────────────────────────────────
# 本目录管理 LLM Prompt 模板的版本化、分类、评估与生命周期。
# Prompt 是 AI Agent 系统的核心资产，需像代码一样管理。
#
# 目录结构（v1.1 — 已有实际文件的 Prompt）：
#   prompts/
#   ├── README.md                          # 本文档
#   ├── agents/                            # Agent 级 Prompt
#   │   ├── narrative/                     # ✅ Narrative Agent Prompt
#   │   │   └── v1_heat_score.json         # 热度评分 Prompt v1
#   │   ├── team/                          # ✅ Team Agent Prompt
#   │   │   └── v1_team_analysis.json      # 团队分析 Prompt v1
#   │   ├── risk/                          # ✅ Risk Agent Prompt
#   │   │   └── v1_risk_assessment.json    # 风险评估 Prompt v1
#   │   └── tokenomics/                    # ✅ Tokenomics Agent Prompt
#   │       └── v1_tokenomics_analysis.json # 代币经济 Prompt v1
#   ├── system/                            # 系统级 Prompt（Orchestrator、Planner）
#   │   └── v1_orchestrator_planner.json   # ✅ Orchestrator 计划 Prompt v1
#   （评估脚本与报告位于 evaluation/llm/，不在本目录下）
#
# 注：✅ 表示该目录已有实际 Prompt 文件
# ──────────────────────────────────────────────

---

## 1. Prompt 管理原则

1. **Prompt 即代码**：Prompt 模板需版本化管理、review、测试，不得随意修改。
2. **结构化输出**：所有 LLM Prompt 要求返回 JSON schema，避免自由文本解析。
3. **版本化**：每个 Prompt 文件含 `version` 元数据，prompt 版本写入 `logs` 表 `prompt_version` 字段。
4. **降级安全**：Prompt 模板解析失败时，自动回退规则引擎。

---

## 2. 目录结构与命名规范

```
prompts/
├── agents/
│   ├── narrative/
│   │   ├── v1_heat_score.json     # 热度评分 Prompt v1
│   │   ├── v1_heat_score.md       # Prompt 说明文档
│   │   └── v2_heat_score.json     # 热度评分 Prompt v2
│   ├── team/
│   │   └── v1_team_analysis.json
│   ├── risk/
│   │   └── v1_risk_assessment.json
│   └── tokenomics/
│       └── v1_tokenomics_analysis.json
└── system/
    ├── v1_orchestrator_planner.json
    └── v1_summarizer.json

# 注：评估脚本与报告位于 evaluation/llm/（非 prompts/ 子目录）
#   evaluation/llm/
#   ├── template_validation.py
#   └── YYYY-MM-DD_benchmark.md
```

**命名规范**：`<version>_<description>.json`

| 元素 | 规则 | 示例 |
| --- | --- | --- |
| 版本 | `v<数字>` | `v1`, `v2` |
| 描述 | `snake_case` | `heat_score`, `team_analysis` |
| 扩展 | `.json`（模板）, `.md`（说明） | `v1_heat_score.json` |

---

## 3. Prompt 元数据规范

每个 Prompt JSON 文件包含元数据块：

```json
{
  "_meta": {
    "version": "v1",
    "agent": "narrative",
    "prompt_key": "heat_score",
    "description": "评估赛道热度分数与时机修正",
    "created_at": "2026-07-08",
    "updated_at": "2026-07-08",
    "author": "system",
    "model": "gpt-4o-mini",
    "temperature": 0.3,
    "max_tokens": 512,
    "schema": "NarrativeLLMOutput"
  },
  "system_prompt": "你是一个 Web3 赛道分析专家...",
  "user_prompt_template": "Analyze the following project sector: {sector}\n\nRaw signals: {raw_signals}",
  "output_schema": {
    "type": "object",
    "properties": {
      "heat_score_adjustment": {
        "type": "number",
        "minimum": -0.3,
        "maximum": 0.3,
        "description": "对规则 base_heat 的修正"
      },
      "timing_correction": {
        "type": ["string", "null"],
        "enum": ["early", "peak", "late", null]
      },
      "evidence": {
        "type": "array",
        "items": { "type": "string" },
        "minItems": 1,
        "maxItems": 5
      }
    },
    "required": ["heat_score_adjustment", "evidence"]
  }
}
```

---

## 4. Prompt 分类

| 分类 | 用途 | 示例 |
| --- | --- | --- |
| **Agent Prompt** | Agent 级推理 | Narrative 热度评分、Team 信誉分析 |
| **System Prompt** | 系统级任务 | Orchestrator 计划生成、结果摘要 |
| **Evaluation Prompt** | Prompt 评估 | 对比规则 vs LLM 输出质量 |

---

## 5. 变量规范

| 变量 | 来源 | 示例值 |
| --- | --- | --- |
| `{sector}` | `RawProject.sector` | `L2`, `Restaking` |
| `{raw_signals}` | `RawProject.raw_signals` (JSON) | `{"has_points": true}` |
| `{team_data}` | 来自 fetcher 的团队数据 | `{"anon": true}` |
| `{tokenomics_data}` | 来自 fetcher 的代币数据 | `{"vc_share": 0.25}` |

- 变量使用 `{snake_case}` 占位符格式。
- 所有变量在调用前必须替换，不得在 Prompt 中保留未替换的变量。

---

## 6. Prompt 评估

### 6.1 评估维度

| 维度 | 衡量方式 | 目标 |
| --- | --- | --- |
| 结构遵从率 | JSON schema 校验通过率 | ≥ 95% |
| 修正合理性 | 修正值在范围内比例 | 100% |
| 证据质量 | evidence 条数 ≥ 1 | 100% |
| 规则一致性 | 与规则引擎偏差幅度 | mean < 0.1 |

### 6.2 评估流程

1. 采集 100 个项目的 LLM 输出样本
2. 运行 `evaluation/llm/template_validation.py`
3. 输出评估报告到 `evaluation/llm/`
4. 每周自动评估一次（cron 周日 02:00）

---

## 7. 生命周期

| 阶段 | 状态 | 可用性 | 切换条件 |
| --- | --- | --- | --- |
| **开发** | `draft` | 仅 dev | 编写中 |
| **测试** | `testing` | 仅 test | 样本评估通过 |
| **稳定** | `stable` | 生产 | A/B 测试通过 |
| **弃用** | `deprecated` | 生产（逐步切换） | 新版本替代 |
| **删除** | `archived` | 不可用 | 弃用 90 天后 |

---

## 8. 安全约束

- Prompt 中不得包含 API Key、密码等敏感信息。
- 变量值中可能包含用户输入，需在填充前做基本转义（防 prompt injection）。
- 输出 schema 必须限制数值范围（如 `heat_score_adjustment ∈ [-0.3, 0.3]`）。

---

_文档版本：v1.0 · 2026-07-08_
