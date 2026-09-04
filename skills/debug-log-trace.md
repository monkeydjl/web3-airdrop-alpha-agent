# Skill：日志追踪分析

## 目标
用 structlog 结构化日志 + `logs` 表定位 pipeline / agent 异常与性能瓶颈。
真相源是 `docs/OBSERVABILITY.md`（已按实测校正过），本文件只讲怎么查。

## 适用场景
- 某次 run 结果异常排查
- 某 agent 超时 / 降级分析
- 端到端延迟归因

## 现状速览（先看这张表再动手）

| 事项 | 现状 |
|---|---|
| 配置入口 | `backend/app/utils/redact.py` 的 `configure_logging()`，由 `backend/app/main.py` 在模块层调用 |
| 输出格式 | `LOG_FORMAT=json` 走 `JSONRenderer`，`console` 走 `ConsoleRenderer`；**设了 `LOG_FILE` 一律强制 JSON**，不看 `LOG_FORMAT` |
| 落盘 | `LOG_FILE` 默认空 = 只写 stdout；设了才落盘，且带轮转（`LOG_MAX_BYTES` 10MB、`LOG_BACKUP_COUNT` 5） |
| 必然存在的字段 | 只有 `event` / `level` / `timestamp` 三个由 processor 注入，其余全靠调用点显式传 |
| 时间戳 | `YYYY-MM-DD HH:MM:SS`，本地时间、无毫秒、无时区后缀 —— **不是** ISO-8601 |
| 脱敏 | `redact_processor` 递归脱敏，且排在 `format_exc_info` **之后**，traceback 也过一遍 |
| 链路来源 | **DB 的 `logs` 表**（OBSERVABILITY §4.1）；stdout 日志里的链路是断的 |
| OTel | 代码就绪但本地 no-op（依赖在 `requirements-otel.txt`，venv 未装） |

> **别按 `run_id` grep stdout 日志。** 全仓只有约 19 处 logger 调用传了 `run_id`，
> 也没有任何 `bind_contextvars` 做自动透传 —— 实测 27192 行落盘日志里带 `run_id` 的只有 254 行。
> 按 run 重建链路要查 `logs` 表；stdout 里真正能串起来的键是 `project_id`（实测 4480 行带它）。

## 输入要求
- 文件：`docs/OBSERVABILITY.md`（§2 日志 / §4 链路 / §7 本地调试 / §9 未实现）
- 文件：`CONVENTIONS.md §10 日志规范`（**注意**：§10.2 的键前缀表是约定目标，不等于现状，见下表）
- 文件：`docs/PERFORMANCE_BENCHMARK.md`（§2 性能目标 / §5.2 性能基线）
- 数据：stdout 日志或 `LOG_FILE` 落盘文件；DB 的 `logs` 表
- 信息：run_id / project_id / 时间窗口

## 事件名对照（照约定表抄 grep 会查空）

| 文档里写的 | 代码里实际的 |
|---|---|
| `agent.run.completed` | `agent.completed`（另有 `agent.started`，均在 `agents/base.py`） |
| `agent.llm.fallback` | 不存在；LLM 失败走 `llm.failed` / `llm.no_response` |
| `pipeline.write.failed` | 不存在；写库失败是 `orchestrator.db_save_failed` / `repository.project.save_failed` |
| `db.*` | **一个都没有**，`backend/app/db.py` 里零 logger 调用；DB 侧事件落在 `repository.*` |
| `fetcher.*` | 实际前缀是 `fetch.*`（`fetch.cache_hit` / `fetch.retry` / `fetch.circuit_open` / `fetch.failed`） |
| `api.*` | 真实存在，22 个，主要来自 `main.py`（如 `api.request.completed`） |

命名规则本身没问题：`<namespace>.<verb>`，全小写点分，全仓 331 个事件名 / 66 个命名空间。

> **改事件名有门禁。** `backend/tests/test_observability_doc_parity.py::test_documented_event_counts_match_reality`
> 会逐一比对 OBSERVABILITY.md 里写的事件总数与命名空间数。新增或删除事件必须同步改文档里的数字，
> 且要用与该测试同源的正则重算，别凭印象填。

## 执行步骤

### Step 1: 先确认日志到底在哪
- 操作：`cd backend && ./venv/Scripts/python.exe -c "from app.config import settings; print(bool(settings.log_file), settings.log_format, settings.log_level)"`
- 验证：没设 `LOG_FILE` 就别翻 `logs/` —— 那里的 `backend.log` 是历史遗留（未被 git 跟踪），`aga.log` 是 pytest 输出，不是 structlog
- 说明：本地起服务是 `uvicorn app.main:app --reload --host 0.0.0.0 --port 8002`（Makefile `dev` 目标），日志默认只走 stdout

### Step 2: 按 run 重建链路（唯一可靠路径）
- 操作：`SELECT * FROM logs WHERE run_id = ? ORDER BY timestamp`
- 验证：pipeline 级记录的 `agent_name` 填 `pipeline`、`project_id` 为 NULL；单项目粒度的记录才有 `project_id`
- 说明：`metrics` 表是死表 —— 结构与 `MetricsRepository` 都在，但生产代码没有写入点，实测 0 行，别指望它有历史留存

### Step 3: 在日志里定位异常
- 操作（JSON 落盘）：`grep '"level": "error"' <logfile> | tail -20`
- 操作（stdout 直连）：`uvicorn app.main:app --port 8002 2>&1 | jq 'select(.level=="error")'`
- 验证：`level` 是 JSON 键，写成 `level=error` 一行也匹配不到；console 渲染下也不是 `key=value` 形式
- 重点事件：`pipeline.agent_error`（agent 唯一的错误出口，WARNING 级）、`orchestrator.node_failed` / `orchestrator.project_failed` / `orchestrator.db_save_failed`、`llm.failed` / `llm.ledger_fail_closed` / `llm.secret_leak_discarded`、`analysis_scheduler.run_failed`
- 说明：只有 error 级带 `exc_info=True`（全仓 34 处），warning 级看不到 traceback 是设计如此

### Step 4: 归类 agent 错误
- 操作：看 `pipeline.agent_error` 的 `kind` 字段
- 验证：`AgentError` 在 `backend/app/agents/base.py:29`，是 **dataclass 不是异常类**，字段为 `agent_name` / `kind` / `message` / `project_id` / `timestamp`
- 说明：`kind` 没有枚举约束，代码注释给的取值是 `validation_error` / `llm_error` / `timeout`；`BaseAgent.run()` 约定**不抛异常**，错误一律进 `state.errors`，所以「日志没报错」不等于「没出错」——要交叉看 `agent.completed` 的 `has_error` 字段

### Step 5: 性能归因
- 操作：提取 `duration_ms`（`agent.completed` 与 `api.request.completed` 都带），对照 `docs/PERFORMANCE_BENCHMARK.md`
- 操作：`curl localhost:8002/metrics`（无需鉴权）看直方图
- 验证：真实存在的耗时指标是 `airdrop_pipeline_duration_seconds`、`airdrop_agent_duration_seconds`（带 `agent` 标签）、`airdrop_llm_duration_seconds`、`airdrop_http_request_duration_seconds`、`airdrop_collection_duration_seconds`
- 说明：**没有慢查询日志**，DB 层完全没埋点；要测 DB 只能临时计时，或看 `airdrop_competition_cache_db_duration_seconds`

### Step 6: 输出结论
- 操作：给出根因与修复建议，指到具体文件行
- 验证：结论含可复现路径（run_id + 时间窗口 + 复现命令）

## 输出
- 文件：排查结论（issue / PR 描述 / 文档片段）
- 数据：`logs/` 与 `logs` 表原样，不修改

## 检查清单
- [ ] 先确认日志出口（stdout 还是 `LOG_FILE`），没设就不翻 `logs/`
- [ ] 链路用 `logs` 表重建，不靠 stdout 里的 `run_id`
- [ ] grep 写法匹配 JSON 键（`"level": "error"`），不是 `level=error`
- [ ] 引用的事件名在代码里 grep 得到，别照 CONVENTIONS §10.2 的约定表抄
- [ ] 区分 `state.errors` 与抛异常：agent 不抛，日志安静不等于没错
- [ ] 性能结论对照 PERFORMANCE_BENCHMARK，且用真实指标名
- [ ] 若顺手改了事件名，同步 OBSERVABILITY.md 的数字并跑 `test_observability_doc_parity.py`

## 参考
- `docs/OBSERVABILITY.md`（§2 日志规范 / §4 链路追踪 / §7 本地调试观测 / §9 未实现）
- `docs/PERFORMANCE_BENCHMARK.md`
- `CONVENTIONS.md §10 日志规范`、`§14 Prometheus 指标命名`
- `backend/app/utils/redact.py`（`configure_logging()` / `redact_processor`）
- `backend/app/agents/base.py`（`AgentError` / `_log_start` / `_log_complete`）
- `backend/tests/test_observability_doc_parity.py`


