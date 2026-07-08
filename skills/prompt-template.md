# Skill：Prompt 模板编写

## 目标
为 Agent 编写版本化的 LLM Prompt 模板，存放于 `backend/app/agents/prompts/` 与 `prompts/`，遵循 prompts/README.md。

## 适用场景
- 新增 Agent 的 prompt
- 调优现有 prompt 输出结构
- 修复 prompt 导致的 schema 错误

## 输入要求
- 文件：`prompts/README.md`（模板规范）
- 文件：`backend/app/agents/prompts/`（代码侧加载）
- 文件：`prompts/agents/<team|narrative>/v1_*.json`（示例）
- 信息：Agent 职责、期望 JSON 结构

## 执行步骤

### Step 1: 定义模板结构
- 操作：创建 `prompts/agents/<agent>/v1_<name>.json`，含 `system`/`user` 模板与 `output_schema`
- 验证：文件名 `v1_<name>.json`，版本前缀便于回滚

### Step 2: 约束输出
- 操作：在模板中要求模型严格输出 JSON，字段与 `backend/app/models.py` 对应模型一致
- 验证：`extra="forbid"` 模型能解析；枚举/范围与模型 `Field` 约束匹配

### Step 3: 代码加载
- 操作：在 `backend/app/agents/<agent>.py` 从 `agents/prompts/` 读取并填充变量（jinja/str.format）
- 验证：变量填充用安全方式，不拼接可执行内容

### Step 4: 测试校验
- 操作：在 `tests/unit/` 用 mock LLM 响应验证 prompt 产出可被模型解析
- 验证：`schema_error` 时能定位到 prompt 问题

## 输出
- 文件：`prompts/agents/<agent>/v1_<name>.json`
- 文件：`backend/app/agents/prompts/`（同步或软链）
- 文件：`tests/unit/test_<agent>_prompt.py`

## 检查清单
- [ ] 文件名带版本前缀 `v1_`
- [ ] 输出 schema 与 Pydantic 模型一致
- [ ] 代码侧安全填充变量
- [ ] 单测验证可解析
- [ ] prompts/README.md 已记录约定

## 参考
- `prompts/README.md`
- `prompts/agents/team/v1_team_analysis.json`
- `backend/app/agents/prompts/`
