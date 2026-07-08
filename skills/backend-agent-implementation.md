# Skill：Agent 类实现

## 目标
实现新的分析 Agent 类，遵循 BaseAgent 契约，产出结构化输出。

## 适用场景
- 添加新的分析 Agent（如 Security Agent）
- 修改现有 Agent 逻辑
- 添加 LLM 增强功能

## 输入要求
- 文件：`backend/app/agents/base.py`（BaseAgent 定义）
- 文件：`docs/DATA_SCORING_DICT.md`（评分规则）
- 信息：Agent 职责、输入数据、输出格式

## 执行步骤

### Step 1: 定义输出模型
- 操作：在 `backend/app/models.py` 中添加 Agent 输出 Pydantic 模型
- 验证：模型包含 `model_config = ConfigDict(frozen=True, extra="forbid")`

### Step 2: 实现 Agent 类
- 操作：继承 `BaseAgent`，实现 `run()` 方法
- 验证：方法签名 `async def run(self, project: RawProject, context: AgentContext) -> AgentResult`

### Step 3: 添加降级逻辑
- 操作：LLM 调用失败时回退规则引擎
- 验证：降级路径有日志记录

### Step 4: 编写测试
- 操作：单元测试 + 契约测试
- 验证：覆盖正常/降级/异常路径

## 输出
- 文件：`backend/app/agents/<name>.py`
- 文件：`backend/app/models.py`（新增输出模型）
- 文件：`tests/unit/test_<name>_agent.py`
- 文件：`tests/contracts/test_<name>_contract.py`

## 检查清单
- [ ] 继承 BaseAgent
- [ ] 输出模型 frozen + extra="forbid"
- [ ] 有 LLM 降级逻辑
- [ ] 错误使用 AgentError
- [ ] 单元测试覆盖率 ≥ 90%
- [ ] 日志事件名遵循 `agent.*` 格式

## 参考
- `docs/ENGINEERING_ROADMAP.md §6 Agent 设计`
- `CONVENTIONS.md §7 错误处理`
- `backend/app/agents/base.py`
