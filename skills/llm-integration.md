# Skill：LLM 集成与降级

## 目标
为 Agent 接入 LLM 调用并实现优雅降级（fallback），遵循 docs/adr/ADR-001-llm-default-off.md、
docs/adr/ADR-016-llm-provider-round-robin.md 与 CONVENTIONS.md §8.2。

## 适用场景
- 新增需要 LLM 的 Agent（narrative/team/risk/tokenomics/scorer）
- 调整降级策略或预算控制
- 接入新的 LLM provider

## 输入要求
- 文件：`docs/adr/ADR-001-llm-default-off.md`、`docs/adr/ADR-016-llm-provider-round-robin.md`
- 文件：`backend/app/config.py`（LLM 配置与 `llm_providers` 解析）
- 文件：`backend/app/llm/client.py`（`llm_chat` / `llm_chat_simple`，多接口轮询）
- 文件：`backend/app/llm/budget.py`（日预算，真的会拦）
- 文件：`backend/app/agents/base.py`（`BaseAgent.llm_enhance` / `AgentError`）
- 文件：`prompts/`（模板在**仓库根目录**，不存在 `backend/app/agents/prompts/`）

## 执行步骤

### Step 1: 确认配置
- 操作：LLM 参数全部来自 `Settings`：
  `openai_api_key`、`openai_base_url`、`llm_model`（默认 `gpt-4o-mini`）、
  `llm_temperature`、`llm_max_tokens`、`llm_daily_budget_usd`（默认 1.0）、
  `llm_semaphore_size`（默认 5）、`enable_llm_enhancement`
- 验证：
  - 开关判据是 `settings.is_llm_enabled` = `enable_llm_enhancement and bool(llm_providers)`，
    不要自己重写判断
  - 多接口配置优先级：`OPENAI_*_N` → `LLM_*_N` → 单接口回退。一个 provider 生效需要
    http(s) 的 base_url + api_key + 至少一个模型，最多 10 provider × 10 模型
  - 无 key 时 `llm_providers` 为空 → 自动走规则降级

### Step 2: 接入调用
- 操作：走 `backend/app/llm/client.py` 的 `llm_chat(...)`（或 `llm_chat_simple`），
  不要在 agent 里直接 new OpenAI 客户端
- 验证：
  - 候选按 **provider × model 组合**做进程内 round-robin；调用开始时推进指针并旋转完整列表
  - 失败语义分级：连接类错误跳过该 provider 剩余模型；模型类错误只跳过当前模型；
    预算/账本/泄漏检测**立即停止**，不再重试
  - 多 worker 下不保证全局均衡（这是已知且接受的）

### Step 3: 实现降级
- 操作：agent 侧覆写 `llm_enhance(state, _prompt) -> str | None`；异常捕获后回退
  启发式/规则输出，记录 `logger.warning("agent.llm.fallback", ...)`
- 验证：
  - 抛错用 `AgentError(kind=...)`，`kind` 是自由字符串（现有取值如 `validation_error`、
    `llm_error`、`timeout`）；降级结果仍要满足 `recoverable` 与可解释性（§9.6）
  - 并发控制用 `llm_semaphore_size`（`base.py:161`）；异步锁**惰性创建**，
    不要在 import 期建（会绑到错误的 event loop）

### Step 4: 预算
- 操作：预算判定用 `budget.check_budget(budget_usd=...)`，消耗记账用 `budget.record_spend(...)`
- 验证：
  - 日预算**已经是真拦截**（不再是装饰性配置），拦截原因常量是 `budget_exceeded`
  - 金额用 `Decimal` + `usd_to_nano`/`nano_to_usd`，不要用 float 累加
  - `backend/tests/test_security_doc_parity.py` 会断言累计与拦截确实存在
    （`daily_spend` / `budget_exceeded`），删掉会变红

### Step 5: 测试
- 操作：测试写在
  `backend/tests/test_llm_failover.py`（轮询与错误分级）、
  `backend/tests/test_llm_budget_enforcement.py`（预算拦截）、
  `backend/tests/test_agent_budget_refusal.py`（agent 侧拒绝路径）
- 验证：
  - 不发起真实 LLM 请求，日志无密钥
  - 轮询相关测试之间用 `client._reset_round_robin_for_tests()` 重置指针，
    否则测试顺序会互相污染
  - 跑 `cd backend && ./venv/Scripts/python.exe -m pytest tests/test_llm_failover.py --no-cov -p no:cacheprovider -q`

## 输出
- 文件：`backend/app/agents/<agent>.py`（更新）
- 文件：`backend/app/llm/client.py` / `budget.py`（如涉及调用层）
- 文件：`backend/app/config.py`（如新增 LLM 参数）
- 文件：`backend/tests/test_llm_*.py`

## 检查清单
- [ ] LLM 配置来自 `Settings`，无硬编码，开关走 `is_llm_enabled`
- [ ] 调用走 `app/llm/client.py`，未绕过轮询与记账
- [ ] 并发受 `llm_semaphore_size` 约束，异步锁惰性创建
- [ ] 失败抛 `AgentError` 并有规则降级路径
- [ ] 预算判定/记账用 `app/llm/budget.py`，金额用 Decimal
- [ ] 测试覆盖成功 + 降级 + 预算拦截，无真实调用
- [ ] 未引用不存在的 `backend/app/agents/prompts/`

## 参考
- `docs/adr/ADR-001-llm-default-off.md`
- `docs/adr/ADR-016-llm-provider-round-robin.md`
- `CONVENTIONS.md §8.2 并发控制 / §9.6 可解释性`
- `backend/app/llm/client.py`（错误分级与轮询语义写在函数注释里）
