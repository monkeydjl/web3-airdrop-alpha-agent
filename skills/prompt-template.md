# Skill：Prompt 模板编写

## 目标
编写/维护版本化的 LLM Prompt 模板，遵循 `prompts/README.md`。

> **路径与现状（先读这段，否则改完 CI 必红）**
> - 模板只存在**仓库根目录的 `prompts/`**。不存在 `backend/app/agents/prompts/`，
>   也不要新建或做软链。
> - 目前**运行时代码不读这些 JSON**。`backend/app/agents/base.py` 的
>   `llm_enhance(state, _prompt)` 收的是已拼好的字符串，prompt 版本从
>   `prompt_versions` 表解析（`_resolve_prompt_version()` → `repositories/v2.py`）。
>   模板文件的唯一消费方是 `evaluation/llm/template_validation.py`。
> - **硬门禁**：`backend/tests/test_security_doc_parity.py` 断言 `system_prompt`
>   与 `output_schema` 这两个符号在 `backend/app` 里**一处都没有**（`_GHOST_SYMBOLS`）。
>   所以「让后端加载模板 JSON」不是随手能加的：真要做，必须同时更新
>   `docs/SECURITY.md` §10/§11 与该测试的清单 —— 那条断言变红正是提醒你同步文档，
>   不是禁止实现。

## 适用场景
- 新增 Agent 的 prompt 模板
- 调优现有 prompt 的输出结构
- 修复模板结构校验（`--validate-templates-only`）报出的问题

## 输入要求
- 文件：`prompts/README.md`（模板规范：命名、元数据、变量、生命周期、安全约束）
- 文件：`prompts/agents/team/v1_team_analysis.json`（可直接照抄的完整样例）
- 文件：`evaluation/llm/template_validation.py`（校验规则的真相源）
- 信息：Agent 职责、期望 JSON 结构、对应的 Pydantic 模型名

## 现有模板清单
```
prompts/
├── agents/
│   ├── narrative/v1_heat_score.json
│   ├── team/v1_team_analysis.json
│   ├── risk/v1_risk_assessment.json
│   └── tokenomics/v1_tokenomics_analysis.json
└── system/v1_orchestrator_planner.json
```

## 执行步骤

### Step 1: 定义模板结构
- 操作：创建 `prompts/agents/<agent>/v1_<name>.json`，顶层字段固定为
  `_meta`、`system_prompt`、`user_prompt_template`、`output_schema`、`fallback`
- 验证：
  - 文件名 `v<数字>_<snake_case>.json`，版本前缀便于回滚
  - `_meta` 至少含 `version`、`agent`、`prompt_key`、`description`、`created_at`、
    `updated_at`、`author`、`model`、`temperature`、`max_tokens`、`schema`、`status`
  - `_meta.schema` 写对应的 Pydantic 模型名（如 `NarrativeLLMOutput`）
  - `_meta.status` 走 README §7 生命周期：`draft` → `testing` → `stable` → `deprecated`

### Step 2: 约束输出
- 操作：`output_schema` 用 JSON Schema 描述返回结构，字段与
  `backend/app/models.py` 对应模型一致
- 验证：
  - `extra="forbid"` 的模型能解析；枚举/数值范围与模型 `Field` 约束匹配
  - 数值必须给上下界（如 `heat_score_adjustment ∈ [-0.3, 0.3]`）
  - `user_prompt_template` 至少含一个 `{snake_case}` 占位符，否则校验会报
    「无变量占位符」
  - `system_prompt` 非空，且不含可疑指令片段（脚本会扫 prompt injection 标记）

### Step 3: 结构校验
- 操作：跑
  `"C:/.../python.exe" evaluation/llm/template_validation.py --validate-templates-only`
  （不需要 API key）
- 验证：全部模板通过。这一步是 CI 之外唯一能验证模板文件本身的手段

### Step 4: 版本落库与测试
- 操作：prompt 版本的注册/默认版本切换走 `prompt_versions` 表
  （`backend/app/repositories/v2.py`）；相关测试在
  `backend/tests/test_prompt_version.py` 与 `backend/tests/test_v2_tables.py`
- 验证：`./venv/Scripts/python.exe -m pytest tests/test_prompt_version.py --no-cov -p no:cacheprovider -q`
- 说明：**不要**为了「测 prompt」在 `backend/app` 里新增读取模板 JSON 的代码 ——
  见文首硬门禁

## 输出
- 文件：`prompts/agents/<agent>/v1_<name>.json`
- 文件：`prompts/README.md`（新增 agent 目录时同步目录树与 §5 变量表）
- 文件：`backend/tests/test_prompt_version.py`（如涉及版本逻辑）

## 检查清单
- [ ] 文件落在根目录 `prompts/` 下，未新建 `backend/app/agents/prompts/`
- [ ] 文件名带版本前缀 `v1_`，`_meta` 字段齐全
- [ ] `output_schema` 与 Pydantic 模型一致，数值有上下界
- [ ] `user_prompt_template` 有 `{}` 占位符，`system_prompt` 非空
- [ ] 模板内无 API Key/密码等敏感信息
- [ ] `--validate-templates-only` 通过
- [ ] `prompts/README.md` 已同步
- [ ] 未在 `backend/app` 引入 `system_prompt` / `output_schema` 符号

## 参考
- `prompts/README.md`
- `prompts/agents/team/v1_team_analysis.json`
- `evaluation/llm/template_validation.py`
- `backend/app/agents/base.py`（`llm_enhance` 与 `_resolve_prompt_version`）
- `backend/tests/test_security_doc_parity.py`（ghost 符号清单及其用意）
