# Skill：Agent 类实现

## 目标
新增或修改一个分析 Agent，遵循 `BaseAgent` 契约：读 `PipelineState`、写自己的 result 字段、错误进 `state.errors` 而不抛异常。

## 适用场景
- 添加新的分析 Agent
- 修改现有 Agent 的评分/判定逻辑
- 给 Agent 增加 LLM 增强路径

## 现状速览（先看这张表再动手）

| 事项 | 现状 |
|---|---|
| 基类 | `BaseAgent`，`backend/app/agents/base.py:244`；构造签名 `__init__(self, name: str)` |
| 唯一必须实现的方法 | `async def run(self, state: PipelineState) -> PipelineState`（base.py:259） |
| 可选钩子 | `async def llm_enhance(self, state: PipelineState, _prompt: str) -> str \| None`（base.py:273） |
| 返回值 | `PipelineState` 本身，**不是**独立的结果对象 |
| 状态对象 | `PipelineState`（base.py:174，dataclass）：`project` / `context` / 四个 result 字段 / `score` / `label` / `confidence` / `veto` / `reason` / `sub_scores` / `weight_version` / `errors` |
| 共享上下文 | `AgentContext`（base.py:148）：`run_id` / `enable_llm` / `llm_model` / `llm_discovery_score_threshold` / `max_concurrent_projects` / `llm_semaphore_size` |
| 输入数据 | `RawProject`（base.py:49，dataclass），注意字段是 **snake_case** |
| 错误载体 | `AgentError`（base.py:29，**dataclass 不是异常类**）：`agent_name` / `kind` / `message` / `project_id` / `timestamp` |
| 输出模型 | `backend/app/models.py` 的 `NarrativeResult` / `TeamResult` / `RiskResult` / `TokenomicsResult`，均为 `ConfigDict(frozen=True, extra="forbid")` |
| 注册位置 | `backend/app/agents/orchestrator_simple.py:65-68` 的 `__init__`，并在 `_run_single_project` 里调度 |
| 测试目录 | `backend/tests/agents/test_<name>.py`（现 15 个文件） |
| 覆盖率 | CI 与本地都是 `--cov-fail-under=80`，**没有「Agent 单独 90%」这条门槛** |

> **契约与路线图不一致，以代码为准。** `docs/ENGINEERING_ROADMAP.md §6.1` 里画的仍是
> `def run(self, context: AgentContext) -> AgentResult`，那是设计阶段的形态。
> 真实的 `AgentResult`（`agents/orchestrator.py:55`）属于另一条 LangGraph 风格编排，
> 跟 `BaseAgent` 无关。照路线图写会直接被 `@abstractmethod` 挡下。

> **`run()` 约定不抛异常。** 基类 docstring 写死了 "Should NOT raise"。异常跑出去会被
> `_run_agent`（`orchestrator_simple.py:241`）记成 `outcome="error"` 后继续往上抛给 gather，
> 整批项目的编排会受影响。正确姿势是 `state.add_error(...)` 后照常返回 state。

## 输入要求
- 文件：`backend/app/agents/base.py`（`RawProject` / `AgentContext` / `PipelineState` / `AgentError` / `BaseAgent`）
- 文件：`backend/app/models.py`（输出模型定义处）
- 文件：`backend/app/agents/orchestrator_simple.py`（装配与调度）
- 文件：`docs/DATA_SCORING_DICT.md`（评分规则，若改动影响打分）
- 信息：Agent 职责、读哪些 `RawProject` 字段、写哪个 result 字段

## 执行步骤

### Step 1: 定义输出模型
- 操作：在 `backend/app/models.py` 加一个 `XxxResult(BaseModel)`
- 验证：`model_config = ConfigDict(frozen=True, extra="forbid")` —— 四个现有 Result 模型全都这么写，别漏
- 说明：字段名用 snake_case，与后端传输约定一致，前端也按 snake_case 消费；frozen 意味着构造后不可改，agent 里要一次算完再 new

### Step 2: 实现 Agent 类
- 操作：`backend/app/agents/<name>.py` 里 `class XxxAgent(BaseAgent)`，`__init__` 调 `super().__init__("<name>")`
- 验证：只实现 `run(self, state: PipelineState) -> PipelineState`
- 说明：`super().__init__` 会同时建好 `self.logger`（`structlog.get_logger(f"agent.{name}")`），
  所以日志事件前缀天然是 `agent.<name>`，不用自己拼；真正落盘的通用事件是 `agent.started` / `agent.completed`

### Step 3: 加 LLM 增强（可选）
- 操作：在 `run()` 里调 `await self.llm_enhance(state, prompt)`，返回 `None` 时走规则引擎
- 验证：双重开关 —— `state.context.enable_llm` 为 True **且** `state.project.discovery_score >= state.context.llm_discovery_score_threshold`（默认 0.7，ADR-012）；不满足时基类打 `llm.skipped_by_score` 直接返回 `None`
- 说明：基类里的 `llm_enhance` **刻意用完整的 `llm_chat()` 而不是 `llm_chat_simple()`**，
  因为 simple 版丢掉 `refused_reason`，会让「预算拦下（预期降级）」和「接口全挂（要告警）」长得一模一样。
  自己另起炉灶调 LLM 时会踩同一个坑

### Step 4: 错误处理
- 操作：`except` 分支里 `state.add_error(AgentError(agent_name=self.name, kind=..., message=..., project_id=state.project.id))`
- 验证：不 `raise`
- 说明：`add_error()` 会自动打 `pipeline.agent_error`（WARNING 级，带 `agent` / `kind` / `message`）。
  `kind` **没有枚举约束**，代码里实际用的是 `validation_error` / `llm_error` / `timeout` 这几个字符串，
  新增取值要同步文档

### Step 5: 接入编排
- 操作：`orchestrator_simple.py` 的 `__init__` 里加一行 `self.xxx = XxxAgent()`，并在 `_run_single_project` 里纳入调度
- 验证：调度统一走 `_run_agent(...)`，它负责耗时与三态 outcome（`error` / `skipped` / `success`）指标
- 说明：`skipped` = 正常返回但产出字段是 `None`（跑了但没结果）。所以「跑完没写 result 字段」
  不会报错，只会静默降级成 skipped —— 排查时先查这个指标而不是翻日志

### Step 6: 编写测试
- 操作：`backend/tests/agents/test_<name>.py`
- 验证：覆盖正常 / 规则降级 / 异常三态；异常路径断言的是 `state.errors` 有内容，不是 `pytest.raises`
- 命令：
  ```bash
  cd backend && ./venv/Scripts/python.exe -m pytest tests/agents/test_<name>.py \
    --no-cov -p no:cacheprovider -q
  ```
- 说明：测试目录只有 `backend/tests/conftest.py` 一个 conftest，**没有** `db` / `sample_project` / `app_client` 这类 fixture，
  要自己构造 `RawProject` 和 `AgentContext`

## 输出
- 文件：`backend/app/agents/<name>.py`
- 文件：`backend/app/models.py`（新增 `XxxResult`）
- 文件：`backend/app/agents/orchestrator_simple.py`（装配）
- 文件：`backend/tests/agents/test_<name>.py`

## 检查清单
- [ ] 继承 `BaseAgent` 且 `super().__init__(name)` 已调
- [ ] `run()` 签名是 `(self, state: PipelineState) -> PipelineState`
- [ ] 输出模型 `frozen=True, extra="forbid"`
- [ ] 全路径不抛异常，错误进 `state.errors`
- [ ] LLM 路径有规则降级，且识别 `discovery_score` 阈值分流
- [ ] 已在 `orchestrator_simple.py` 装配并纳入 `_run_agent` 调度
- [ ] 测试覆盖正常/降级/异常，异常断言 `state.errors`
- [ ] 若动到评分口径，同步 `docs/DATA_SCORING_DICT.md` 并跑 `backend/tests/golden/test_golden_cases.py`
- [ ] 覆盖率按全仓 80% 门禁，不另设 90%

## 参考
- `backend/app/agents/base.py`（`RawProject:49` / `AgentError:29` / `AgentContext:148` / `PipelineState:174` / `BaseAgent:244`）
- `backend/app/agents/risk.py`（一个完整的可抄实现：规则判定 + LLM 增强 + 错误收口）
- `backend/app/agents/orchestrator_simple.py`（装配与 `_run_agent` 指标）
- `backend/app/models.py`（四个 Result 模型）
- `docs/DATA_SCORING_DICT.md`
- `docs/ENGINEERING_ROADMAP.md §6`（**注意 §6.1 的契约已过时，以 base.py 为准**）
- `CONVENTIONS.md §7 错误处理` / `§10 日志规范`
