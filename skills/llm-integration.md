# Skill：LLM 集成与降级

## 目标
为 Agent 接入 LLM 调用并实现优雅降级（fallback），遵循 docs/adr/ADR-001-llm-default-off.md 与 CONVENTIONS.md §8.2。

## 适用场景
- 新增需要 LLM 的 Agent（narrative/team/scorer）
- 调整降级策略或预算控制
- 接入新的 LLM provider

## 输入要求
- 文件：`docs/adr/ADR-001-llm-default-off.md`
- 文件：`backend/app/config.py`（LLMConfig）
- 文件：`backend/app/agents/base.py`（BaseAgent / AgentError）
- 文件：`backend/app/agents/prompts/`（prompt 模板）

## 执行步骤

### Step 1: 配置 LLM
- 操作：从 `Settings` 读取 `openai_api_key`/`llm_model`/`daily_budget_usd`（pydantic-settings）
- 验证：默认 `llm_model="gpt-4o-mini"`，无 key 时自动走规则降级

### Step 2: 接入调用
- 操作：在 agent 中用独立 `llm_semaphore` 控制并发（§8.2），`await` 调用 LLM
- 验证：LLM 调用包在 `try/except`，失败抛 `AgentError(kind="llm_fallback")`

### Step 3: 实现降级
- 操作：捕获异常后回退到启发式/规则输出，记录 `logger.warning("agent.llm.fallback", ...)`
- 验证：降级结果仍满足 `AgentError.recoverable` 与可解释性要求（§9.6）

### Step 4: 预算与测试
- 操作：在 `tests/unit/test_<agent>.py` 用 mock LLM 测成功/降级两路；预算超限走降级
- 验证：测试不发起真实 LLM 请求，日志无密钥

## 输出
- 文件：`backend/app/agents/<agent>.py`（更新）
- 文件：`backend/app/config.py`（如新增 LLM 参数）
- 文件：`tests/unit/test_<agent>.py`

## 检查清单
- [ ] LLM 配置来自 `Settings`，无硬编码
- [ ] 使用独立 `llm_semaphore` 并发控制
- [ ] 失败抛 `AgentError(kind="llm_fallback")`
- [ ] 降级输出满足可解释性（§9.6）
- [ ] 单测覆盖成功 + 降级，无真实调用

## 参考
- `docs/adr/ADR-001-llm-default-off.md`
- `CONVENTIONS.md §8.2 并发控制 / §9.6 可解释性`
- `backend/app/agents/base.py`
