# Skill：日志追踪分析

## 目标
通过 structlog 结构化日志与唯一 run_id/project_id 串联，定位 pipeline/agent 异常与性能瓶颈，遵循 CONVENTIONS.md §10。

## 适用场景
- 某次 run 结果异常排查
- 某 agent 超时/降级分析
- 端到端延迟归因

## 输入要求
- 文件：`logs/`（运行日志）
- 文件：`CONVENTIONS.md §10 日志规范`
- 文件：`docs/OBSERVABILITY.md`（指标/事件名）
- 信息：run_id / project_id / 时间窗口

## 执行步骤

### Step 1: 收集关联日志
- 操作：按 `run_id` 过滤 `logs/`，串联 `pipeline.*` → `agent.*` → `db.*` → `api.*` 事件
- 验证：事件名遵循 `层级.动词过去式`（§10.2），如 `agent.run.completed`

### Step 2: 定位异常
- 操作：grep `level=error/warning`，重点看 `agent.llm.fallback`、`pipeline.write.failed`（含 `exc_info`）
- 验证：`AgentError.kind` 字段用于分类（llm_fallback/pipeline_error/timeout/schema_error）

### Step 3: 性能归因
- 操作：提取各事件 `duration_ms`，对照 `docs/PERFORMANCE_BENCHMARK.md` 找超阈值环节
- 验证：结合 `airdrop_*_duration_seconds` 指标（§14）

### Step 4: 输出结论
- 操作：给出根因与修复建议（指向具体 agent/db 文件），必要时写 issue
- 验证：结论含可复现路径（run_id + 时间）

## 输出
- 文件：排查结论（issue / 文档片段）
- 文件：`logs/`（原样，不修改）

## 检查清单
- [ ] 按 run_id 串联全链路事件
- [ ] 事件名符合 `层级.动词过去式`
- [ ] 识别 `AgentError.kind` 类别
- [ ] 对比性能基线
- [ ] 结论含可复现 run_id

## 参考
- `CONVENTIONS.md §10 日志规范 / §14 指标`
- `docs/OBSERVABILITY.md`
- `docs/PERFORMANCE_BENCHMARK.md`
