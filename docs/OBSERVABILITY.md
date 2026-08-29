# 可观测性设计规范

> 本文档描述**当前代码实际实现的**日志、指标、追踪、告警行为，
> 每一条都在 2026-08-23 对着运行中的后端与 `backend/app/` 源码核对过。
> 凡属"计划中但尚未实现"的部分，一律集中放在 §9，并明确标注 **未实现**。
>
> 上一版本的本文档列出了 39 个指标名，其中 **35 个在代码里根本不存在**；
> 列出的 15 个日志事件名，**一个都不存在**。照它写告警规则或日志查询会全部落空。
> 因此本次按实测重写，并加了机器化回归（`backend/tests/test_observability_doc_parity.py`）
> 把文档与代码钉在一起。

---

## 1. 设计原则

1. **三支柱分工**：日志（结构化事件）+ 指标（聚合数值）+ 追踪（链路上下文）各司其职。
2. **不阻塞主流程**：观测代码失败不能中断业务。代码里每处指标更新都包在
   `try/except` 里，失败只记一条 `metrics.gauge_update_failed` 之类的警告。
3. **密钥绝不落日志**：脱敏在 structlog processor 层强制执行（§2.5），
   不依赖调用方自觉。
4. **有界标签**：指标标签只用闭合词表（枚举 / 版本常量），
   高基数信息（project_id、URL、错误原文）走日志，不走指标（§3.4）。
5. **文档只写实测为真的**：这是本次重写立的规矩。一个不存在的指标名比没有文档更坏 ——
   读者照它写 PromQL，面板永远空白，而 Prometheus 对不存在的指标**不报错**，
   只返回空结果集。

---

## 2. 日志规范

日志实现在 `backend/app/utils/redact.py` 的 `configure_logging()`，
基于 [structlog](https://www.structlog.org/)。

### 2.1 实际输出的字段

structlog 的 processor 链固定注入三个字段，其余字段由调用点按需传入：

| 字段 | 来源 | 是否必然存在 |
| --- | --- | --- |
| `event` | `logger.info("事件名")` 的第一个位置参数 | 是 |
| `level` | `add_log_level` processor | 是 |
| `timestamp` | `TimeStamper(fmt="%Y-%m-%d %H:%M:%S")` | 是 |
| 其它 | 调用点的关键字参数 | 否 |

实测一条真实日志行（`LOG_FORMAT=json`）：

```json
{"agent": "narrative", "duration_ms": 12.5, "run_id": "r-1",
 "api_key": "***REDACTED***", "nested": {"token": "***REDACTED***"},
 "event": "agent.completed", "level": "info",
 "timestamp": "2026-08-23 12:21:10"}
```

注意时间戳格式是 `YYYY-MM-DD HH:MM:SS`（本地时间、无毫秒、无时区后缀），
**不是** ISO-8601 带 `Z` 的形式。写日志解析规则时按前者。

> **`run_id` 不是每条日志都有。** 全仓 287 处 logger 调用里只有 19 处传了 `run_id`。
> 想按 run 重建链路，可靠来源是 `logs` 表（§4.1），不是 stdout 日志。

调用点最常传的字段（按出现次数）：`error` 93、`project_id` 44、`source_id` 34、
`run_id` 19、`reason` 11、`project_count` 10、`cutoff` 10、`error_type` 10。

### 2.2 事件命名

实际命名是 **`<namespace>.<verb>`**，全小写点分。全仓共 **269 个不同事件名**、
**57 个命名空间**；段数分布：2 段 211 个、3 段 52 个、4 段 5 个、1 段 1 个。

事件最多的命名空间：

| 命名空间 | 事件数 | 例 |
| --- | --- | --- |
| `unified_scheduler` | 23 | `unified_scheduler.started` |
| `api` | 22 | `api.request.completed`、`api.run.failed` |
| `orchestrator` | 20 | `orchestrator.pipeline_start` |
| `collector` | 18 | `collector.noise_quarantined` |
| `pipeline` | 12 | `pipeline.completed` |
| `collection_scheduler` | 12 | `collection_scheduler.metrics_alert_failed` |
| `archive` | 10 | `archive.raw_projects.archived` |
| `app` | 10 | `app.startup`、`app.shutdown` |

**别按老文档写查询**：它列的 `run.start`、`agent.run.start`、`db.write.error`、
`fetcher.fetch.start` 等 14 个事件名**全部不存在**。
真实对应事件示例：`orchestrator.pipeline_start`、`agent.started`、`agent.completed`、
`circuit_breaker.opened`、`collection.alert`。完整清单以 `backend/app/` 源码为准；
`test_observability_doc_parity.py` 会保证本文档列出的每个事件名都真实存在。

> `llm.budget.exceeded` 是这批名字里**唯一一个后来变成真的**的：
> 2026-08-24 实现日预算拦截时，实现方按原来的设计意图用了同一个事件名
> （另有 `llm.refused_by_budget`、`llm.budget.ledger_unavailable`、
> `llm.budget.record_failed`）。所以它已从"虚构"清单移出。

### 2.3 级别使用

实测调用分布：`info` 153 处、`error` 63 处、`warning` 58 处、`debug` 12 处、
`exception` 1 处。**代码里没有任何一处用 `warn`** —— structlog 的方法名是
`warning`（`warn` 虽是别名，但仓内未使用）。

| 级别 | 实际用途 |
| --- | --- |
| `debug` | fetcher 缓存命中、限流等待、逐条抓取失败等细节 |
| `info` | 生命周期完成事件（run / agent / 采集 / 归档 / 调度）、API 请求完成 |
| `warning` | 降级、熔断打开、LLM 单次尝试失败、采集阈值告警 |
| `error` | pipeline 失败、DB 写失败、调度器回调失败、未捕获异常 |

`LOG_LEVEL` 环境变量**现已真正生效**（`wrapper_class=make_filtering_bound_logger`）。
实测：`WARNING` 下只输出 warning/error；`ERROR` 下只输出 error。
非法值（拼错、留空）退回 `INFO`，**不会**降级成 DEBUG ——
"配置写错反而把全部 debug 日志放出来"是必须避免的方向。

> 此前 `LOG_LEVEL` 只传给了 uvicorn（`main.py` 的 `uvicorn.run(log_level=...)`），
> 应用自身的 structlog 完全不看它，`LOG_LEVEL=WARNING` 下 12 处 `logger.debug`
> 照样全量输出。一个"设了但不生效"的开关比没有开关更糟：运维以为噪音已压掉。

### 2.4 采样

**未实现。** processor 链里没有任何采样逻辑，日志按级别过滤后全量输出。
老文档描述的"debug 10% 采样、按 run_id 哈希保证同 run 一致"是设计意图，
不是现状。要压低量，当前唯一手段是调 `LOG_LEVEL`。

### 2.5 敏感信息脱敏（已实现且已验证）

`redact_processor` 做两件事，**递归**下探容器（最多 4 层，防环状结构）：

1. **按字段名**：字段名匹配 `api_key` / `apikey` / `token` / `bearer` /
   `authorization` / `password` / `secret` / `dsn`（带前后缀边界）时，
   值整体替换为 `***REDACTED***`。
2. **按取值**：把 `settings` 上 15 个已知密钥字段的**实际值**替换成 `***`，
   并对 query 串里 `?api_key=` / `?token=` 之类做兜底正则脱敏。

实测（见 §2.1 的日志样例）：顶层 `api_key` 与嵌套 `nested.token` 都被替换。

两个容易写错、已在代码里固定下来的点：

- **`redact_processor` 必须排在 `format_exc_info` 之后**。traceback 是在那一步
  才被渲染成字符串塞进 event_dict 的；排在之前等于什么都没脱敏 ——
  而 `exc_info=True` 的调用点恰恰是 httpx / psycopg 异常（含完整 URL 与 DSN）
  的主要来源。`test_redaction_runs_after_exception_rendering` 钉住这个顺序。
- **必须递归**。把密钥放进嵌套字典的写法在只看顶层时会整个漏过去。

> **用户 `note` 截断到 200 字符：未实现。** 全仓没有任何相应的截断逻辑。
> feedback 的 note 若被写进日志，会原样进去。

### 2.6 落盘

`LOG_FILE` 非空时，同一行同时写 stdout 与该文件（`_TeeWriter`），
**共用同一条 processor 链**，所以文件行同样经过脱敏。
落盘时强制 JSON 渲染 —— console 渲染带 ANSI 颜色与对齐补白，会污染文件行，
而 JSON 行可直接被 Promtail/Loki 按字段解析。

---

## 3. 指标规范（Prometheus）

实现在 `backend/app/metrics.py`，用 `prometheus_client`。

### 3.1 暴露端点

- `GET /metrics`，Prometheus 文本格式（`text/plain; version=0.0.4; charset=utf-8`）。
- 路径由 `METRICS_PATH` 配置（默认 `/metrics`）。
- `METRICS_ENABLED=false` 时该端点返回 **404** 与
  `{"ok": false, "error": {"code": "METRICS_DISABLED"}}`，而不是 200 空响应。
- **无鉴权**：实测无凭据请求 `/metrics` 返回 200。
  部署时必须靠网络层（内网 / nginx 白名单）限制访问；
  `configs/observability/prometheus/prometheus.yml` 的抓取目标是
  `airdrop-web:8002`（compose 内网名）。
- 命名空间为 `airdrop`，Opportunity 经济栈另用 `opportunity_economic` 前缀。

### 3.2 完整指标目录（44 个，实测全量）

下表由 `backend/app/metrics.py` 的注册表直接导出。
**Counter 在 `/metrics` 输出里带 `_total` 后缀**（`prometheus_client` 自动追加），
写 PromQL 时用带后缀的名字；Histogram 另有 `_bucket` / `_count` / `_sum`。

#### Pipeline（4）

| 指标 | 类型 | 标签 | 含义 |
| --- | --- | --- | --- |
| `airdrop_pipeline_runs_total` | counter | `trigger, status` | 评分流水线运行次数 |
| `airdrop_pipeline_duration_seconds` | histogram | — | 端到端耗时（buckets 0.1,0.5,1,2.5,5,10,30,60） |
| `airdrop_projects_scored_total` | counter | — | 累计评分项目数 |
| `airdrop_projects_by_label_total` | counter | `label` | 按最终标签分组的评分数 |

#### Agent（2）

| 指标 | 类型 | 标签 | 含义 |
| --- | --- | --- | --- |
| `airdrop_agent_runs_total` | counter | `agent, result` | 分析 agent 执行结果计数 |
| `airdrop_agent_duration_seconds` | histogram | `agent` | 单 agent 墙钟耗时（buckets 0.001…10） |

`result` 闭合为 `success` / `error` / `skipped`（定义在 `metrics.py::AGENT_RESULTS`）：
`success` = agent 正常返回且产出结果字段；`error` = agent 抛异常；
`skipped` = 正常返回但产出字段为 None（跑了但没有可输出结果）。
埋点在 `agents/orchestrator_simple.py` 的 `_run_agent`（narrative/team/tokenomics/risk）
与 scorer 分支。这条取代了老文档把错误/跳过拆成两个独立 counter 的写法
（老名字仍列在 §3.3，确实不存在）。

#### 采集（4）

| 指标 | 类型 | 标签 | 含义 |
| --- | --- | --- | --- |
| `airdrop_collection_runs_total` | counter | `source_id, status` | 采集运行次数 |
| `airdrop_collection_duration_seconds` | histogram | `source_id` | 单次采集耗时（buckets 0.5,1,2.5,5,10,30,60,120） |
| `airdrop_collection_items_total` | counter | `source_id` | 各源发现的原始条目数 |
| `airdrop_collection_duplicates_total` | counter | `source_id` | 各源重复条目数 |

#### 旁路机会引擎 Shadow（5）

| 指标 | 类型 | 标签 | 含义 |
| --- | --- | --- | --- |
| `airdrop_opportunity_shadow_projects_total` | counter | `result` | 按批次结果计数 |
| `airdrop_opportunity_shadow_assessments_total` | counter | `status, public_label, model_version, profile_version` | 落库的影子评估 |
| `airdrop_opportunity_shadow_duration_seconds` | histogram | — | 选中批次耗时（buckets 0.01…30） |
| `airdrop_opportunity_shadow_enabled` | gauge | — | 影子评估是否开启（0/1） |
| `airdrop_opportunity_shadow_sample_rate` | gauge | — | 配置的确定性采样率 |

`result` 标签恰好六个闭合取值，由 `OPPORTUNITY_SHADOW_PROJECT_RESULTS` 常量约束：
`eligible`、`sampled`、`attempted`、`saved`、`failed`、`skipped`。

#### Opportunity 经济栈（6）

| 指标 | 类型 | 标签 | 含义 |
| --- | --- | --- | --- |
| `opportunity_economic_snapshots_total` | counter | `source, result` | 经济快照 |
| `opportunity_economic_observations_total` | counter | `source, result` | 内存观测构建 |
| `opportunity_economic_evidence_total` | counter | `source, result` | 证据产出 |
| `opportunity_economic_identity_resolution_total` | counter | `source, result` | 身份解析 |
| `opportunity_economic_run_duration_seconds` | histogram | `source` | 写入/处理耗时 |
| `opportunity_economic_last_success_unixtime` | gauge | `source` | 最近一次产出 ≥1 观测的 Unix 时间 |

`source` 闭合为 `defillama` / `coingecko` / `cryptorank`；
各 `result` 词表见 `metrics.py` 的 `OPPORTUNITY_ECONOMIC_*_RESULTS` 常量。

#### LLM（10）

| 指标 | 类型 | 标签 | 含义 |
| --- | --- | --- | --- |
| `airdrop_llm_requests_total` | counter | `model` | LLM 请求数（成功与失败都计入 —— 错误率的分母必须是尝试次数） |
| `airdrop_llm_errors_total` | counter | `model` | LLM 请求失败数 |
| `airdrop_llm_duration_seconds` | histogram | — | LLM 请求耗时（buckets 0.5,1,2.5,5,10,30） |
| `airdrop_llm_cost_usd_total` | counter | `model`, `basis` | 估算花费（美元）。`basis` 见下 |
| `airdrop_llm_tokens_total` | counter | `model`, `direction` | token 用量，`direction` = `prompt` / `completion` |
| `airdrop_llm_budget_blocked_total` | counter | `reason` | 调用前被预算拒绝的次数。`reason` 见下 |
| `airdrop_llm_spend_record_failures_total` | counter | — | 钱花了但账没记上的次数（见下方警告） |
| `airdrop_llm_budget_usd` | gauge | — | 当前配置的日预算（0 = 不限额） |
| `airdrop_llm_spend_today_usd` | gauge | — | 当日（UTC）累计估算花费 |
| `airdrop_llm_secret_leak_detected_total` | counter | — | LLM 输出因含密钥被丢弃的次数（SECURITY §10.5） |

> ⚠️ **前三个指标在 2026-08-24 之前从未被递增过一次。**
> 它们注册了、暴露在 `/metrics` 里、被本文档记录、还有一条 `HighLLMErrorRate`
> 告警建立在其上 —— 但代码里没有任何递增点。
> **一个存在但永不增长的指标，在面板上是平直的 0 线、在告警里是永不触发，
> 两者看起来都像"系统很健康"。** 这比指标名写错更坏：名字写错时查询查不到数据，
> 还有机会被发现。现在 `app/llm/client.py` 在每次尝试后递增。

`basis` 闭合为三个值（定义在 `app/llm/pricing.py`），它回答"这笔账是怎么算出来的"：

| `basis` | 含义 | 该关注什么 |
| --- | --- | --- |
| `table` | 命中价格表，且接口返回了真实 `usage` | 正常 |
| `fallback_price` | 模型不在价格表里，按 `LLM_FALLBACK_PRICE_PER_1M_USD` 兜底价估 | 占比高说明价格表该补新模型了；金额偏高是有意的（宁可高估） |
| `estimated_tokens` | 接口**没返回 `usage`**，token 数按字符估的 | 占比高说明连输入量都不确定，预算精度下降 |

`reason` 闭合为（定义在 `app/llm/budget.py`）：`budget_exceeded`（当日花超）、
`ledger_unavailable`（账本读不出来 → fail closed 拒绝调用）。
后者上涨是**基础设施问题**，不是预算配置问题 —— 先查 DB 可写性。

> ⚠️ `airdrop_llm_spend_record_failures_total` 上涨的含义要特别注意：
> **这些花费永远不会计入预算**。记账发生在 LLM 已成功返回之后，为了记账失败
> 而丢弃一个已经付过钱的结果是纯亏损，所以实现上不抛异常、只记指标。
> 但累积起来就是预算静默失效 —— 这个指标是唯一能看到它的地方。

成本指标的准确性边界：价格表是**手工维护的近似值**，会过时。
用途是"够准地估出能触发熔断的量级"，**不是账单核对**，真实账单以各家控制台为准。

#### DB gauge（3）

| 指标 | 类型 | 标签 | 含义 |
| --- | --- | --- | --- |
| `airdrop_db_projects_total` | gauge | — | 当前已评分项目数 |
| `airdrop_db_raw_projects_total` | gauge | — | 待评分的原始项目数 |
| `airdrop_db_collection_logs_24h_total` | gauge | — | 近 24 小时采集日志条数 |

这三个是**周期刷新的 gauge**，不是实时查询。刷新失败记
`metrics.gauge_update_failed`。

#### 数据质量（2）

| 指标 | 类型 | 标签 | 含义 |
| --- | --- | --- | --- |
| `airdrop_data_freshness_seconds` | gauge | `source_id` | 距上一次成功同步的秒数 |
| `airdrop_data_completeness_ratio` | gauge | `source_id` | 必填字段覆盖率（0-1） |

计算逻辑在 `app/collectors/metrics.py::CollectionMetrics`（`get_freshness` /
`get_coverage_rate`），在 `check_alerts` 每次遍历数据源时顺手 set 进来 ——
数据质量 gauges 与告警判断共用同一份 snapshot，不会各算各的出现口径漂移。
`freshness` 为 None（从未成功同步）时不写 freshness gauge，只写完整性。

#### Fetcher / 缓存 / 并发（7）

| 指标 | 类型 | 标签 | 含义 |
| --- | --- | --- | --- |
| `airdrop_fetcher_cache_hits_total` | counter | — | HTTP 抓取缓存命中 |
| `airdrop_fetcher_cache_misses_total` | counter | — | 缓存未命中（触发真实请求） |
| `airdrop_fetcher_circuit_breaker_state` | gauge | — | 熔断状态：0=CLOSED / 1=HALF_OPEN / 2=OPEN |
| `airdrop_concurrency_fetcher_semaphore_usage` | gauge | — | 当前占用信号量的在途 HTTP 请求数 |
| `airdrop_competition_cache_hits_total` | counter | — | 赛道计数缓存命中 |
| `airdrop_competition_cache_misses_total` | counter | — | 赛道计数缓存未命中（触发 DB COUNT） |
| `airdrop_competition_cache_db_duration_seconds` | histogram | — | 缓存未命中时 `COUNT(*)` 耗时 |

> **熔断状态是单个无标签 gauge，不是按源拆分的。** 想区分是哪个源熔断，
> 看日志 `circuit_breaker.opened`（带 `source_id`）。

#### API（1）

| 指标 | 类型 | 标签 | 含义 |
| --- | --- | --- | --- |
| `airdrop_http_requests_total` | counter | `method, status_class` | API 处理的请求数 |

`status_class` 是**分档**值（`2xx`/`3xx`/`4xx`/`5xx`），不是具体状态码 ——
这是刻意的基数控制。**没有 HTTP 耗时 histogram**：请求耗时只进日志
（`api.request.completed` 的 `duration_ms` 字段）。

#### 从 §3.3「不存在」清单里移出的两个（2026-08-24）

`airdrop_llm_cost_usd_total` 与 `airdrop_llm_tokens_total` 曾被列在下面那份
"代码里一个都没有"的清单里。日预算拦截实现后它们成了真实注册的指标
（见上面的 LLM 段），所以从清单里移出。

**把一个真实存在的指标列进"不存在"清单，会让人放弃一个可用的指标 ——
这份纠错清单本身就成了新的谎言。** 清单的可信度是有限资源：
一条假行会让读者怀疑其余每一行。
`test_observability_doc_parity.py` 的 `test_ghost_list_contains_no_real_metric`
就是为了让这种反向错误在 CI 里变红，而不是靠人复读发现。

那批名字里的"剩余预算"指标（老文档写的是 llm budget remaining usd 那个名字，
这里不写成 `airdrop_` 开头的完整形式，否则本节会被门禁当成"文档声称它存在"）
**仍然不存在**，且是有意不做的：实现暴露的是 `airdrop_llm_budget_usd` 与
`airdrop_llm_spend_today_usd` 两个 gauge，剩余额度在查询侧相减得出。
多暴露一个第三个数，就多一个会与前两个漂移的来源。

### 3.3 老文档虚构、代码中不存在的指标（30 个）

以下名字在上一版文档里出现过，代码里**一个都没有**。列在这里是为了让照旧文档
写过查询的人一眼对上，不要再找：

`airdrop_run_total`、`airdrop_run_duration_seconds`、`airdrop_projects_analyzed_total`、
`airdrop_projects_inserted_total`、`airdrop_projects_updated_total`、
`airdrop_agent_errors_total`、`airdrop_agent_skipped_total`、
`airdrop_fetcher_duration_seconds`、`airdrop_fetcher_errors_total`、`airdrop_fetcher_circuit_open`、
`airdrop_collection_total`、`airdrop_collection_success_ratio`、`airdrop_collection_status`、
`airdrop_collection_api_calls`、`airdrop_collection_api_calls_today`、`airdrop_collection_running`、
`airdrop_collection_signal_freshness_seconds`、`airdrop_rate_limiter_tokens`、
`airdrop_discovery_score_distribution`、`airdrop_projects_discovered_total`、
`airdrop_projects_analyzed_from_discovery_total`、`airdrop_llm_calls_total`、
`airdrop_llm_budget_remaining_usd`、
`airdrop_db_write_errors_total`、`airdrop_db_query_duration_seconds`、`airdrop_projects_in_db`、
`airdrop_http_request_duration_seconds`、`airdrop_narrative_heat_score`、
`airdrop_feedback_total`、`airdrop_project_score`。

**2026-08-24 从这张清单里移出了两个 LLM 成本/token 指标** —— 移出记录见上一小节，
那里说明了为什么"把真指标写成假指标"和反过来一样有害。
（移出的名字**故意不在这一节里重复**：本节整块会被 CI 门禁当作"这些都不存在"
来核对，在这里写出一个真实指标名会让门禁立刻变红 —— 这正是它该做的事。）

**为什么这比写错更危险**：Prometheus 查一个不存在的指标**不报错**，
返回空结果。面板上是一条空曲线、一个「No data」，看起来像"系统很安静"，
而不是"你查的东西不存在"。基于它的告警规则同理 —— 永远不会触发，
于是给人一种被监控着的错觉。

### 3.4 标签基数控制

- 标签值必须是有限闭合集。`metrics.py` 用模块级常量（frozenset / tuple）
  把 Opportunity 相关词表写死，不允许运行时拼字符串。
- **禁止**用 `project_id` / `run_id` / URL / 错误原文作标签。
  这类信息走日志（`project_id` 是第二高频日志字段，44 处）。
- `airdrop_http_requests_total` 只按 `method` 与 `status_class` 拆 ——
  按具体 path 拆会随路由参数爆炸。

---

## 4. 链路追踪

### 4.1 `logs` 表（已实现，当前唯一可用的链路来源）

SQLite / PostgreSQL 的 `logs` 表按 run 记录执行明细：

| 列 | 说明 |
| --- | --- |
| `run_id` | 形如 `api-run-20260814-080002-332488` 或 `run-seed` |
| `project_id` | 单项目粒度记录时填，pipeline 级为 NULL |
| `agent_name` | pipeline 级记录填 `pipeline` |
| `input` / `output` | JSON 文本，含 trigger、状态、计数、top_score、影子评估统计 |
| `error` / `duration_ms` / `timestamp` | — |

实测本地库 196 行。按 run 重建：`SELECT * FROM logs WHERE run_id = ? ORDER BY timestamp`。

> **`metrics` 表是死表。** 结构存在（`run_id, metric_name, metric_value, detail, timestamp`），
> `MetricsRepository` 也实现了 insert / 查询，但**全仓只有测试调用它**，
> 生产代码没有任何写入点，实测 0 行。要么接上，要么删掉 ——
> 留着会让人以为指标有历史留存。

### 4.2 OpenTelemetry（代码就绪，本地未启用）

`backend/app/tracing.py` 实现了完整的 OTLP 管线，但 **OTel 依赖是可选的
（`requirements-otel.txt`），本地 venv 未安装**，实测
`_OTEL_AVAILABLE=False`、`setup_tracing()` 返回 `False`，
tracer 退化为 no-op。这是刻意的：本地开发与测试不需要装 OTel。

启用条件（两个都要满足）：

1. `OTEL_ENABLED=true`
2. OTel 包已安装（生产镜像的 observability profile）

任一不满足时**静默退化为 no-op**，只在"开关开了但包没装"这一种情况下
记一条 `tracing.unavailable`。

实际的手动 span 名（`start_as_current_span`）：

| span | 位置 |
| --- | --- |
| `airdrop.pipeline.run` | 根 span，一次 pipeline 运行 |
| `airdrop.project` | 单项目 |
| `airdrop.agent.{agent_name}` | 每个 agent 阶段（动态名） |
| `airdrop.agent.scorer` | 打分阶段 |

自动埋点：FastAPI（排除 `/health`、`/metrics`、`/version`）、httpx、sqlite3、psycopg。
导入失败只记 `tracing.instrumentation_partial`，不中断启动。

相关配置：`OTEL_ENABLED`（默认 false）、`OTEL_ENDPOINT`（默认
`http://otel-collector:4317`）、`OTEL_SERVICE_NAME`（默认 `airdrop-alpha`）、
`OTEL_SAMPLE_RATE`（默认 1.0）。

### 4.3 上下文传递

**`X-Run-Id` 响应头未实现。** 实测所有响应只有一个自定义头：
`X-Disclaimer`（免责声明，SECURITY.md §7.5 要求）。
`run_id` 出现在 `POST /run` 的响应体里，不在头里。

---

## 5. 告警

系统里有**两套互不相同**的告警机制，别混为一谈。

### 5.1 Prometheus 告警规则（已就位，10 条）

文件：`configs/observability/prometheus/alert_rules.yml`，
由 `prometheus.yml` 的 `rule_files` 加载，路由到 `alertmanager:9093`。
**已核对：这些规则引用的指标名全部真实存在，无幽灵指标。**

| 告警 | 表达式要点 | 级别 |
| --- | --- | --- |
| `PipelineConsecutiveFailures` | 15min 内 `airdrop_pipeline_runs_total{status="failed"}` 增量 ≥2 | critical |
| `PipelineFailureRate` | 5min 内持续出现失败 | warning |
| `NoProjectsDiscovered` | 24h 内 `airdrop_projects_scored_total` 增量为 0，持续 6h | warning |
| `DBGaugeStale` | `airdrop_db_projects_total` 超 24h 未刷新 | warning |
| `HighLLMErrorRate` | 5min 内 `airdrop_llm_errors_total` 有增长 | warning |
| `LLMBudgetExhausted` | 15min 内 `airdrop_llm_budget_blocked_total{reason="budget_exceeded"}` 有增长 | warning |
| `LLMBudgetLedgerUnavailable` | 同上但 `reason="ledger_unavailable"` | critical |
| `LLMSpendNotRecorded` | 1h 内 `airdrop_llm_spend_record_failures_total` 有增长 | critical |
| `HighAPIErrorRate` | `airdrop_http_requests_total{status_class="5xx"}` 速率 > 0.1/s | critical |
| `BackendDown` | `up{job="airdrop-backend"} == 0` 持续 1min | critical |

> `HighLLMErrorRate` 值得单独说一句：它**在 2026-08-24 之前永远不可能触发** ——
> 规则本身没问题，但它依赖的 `airdrop_llm_errors_total` 从注册起就没有任何
> 递增点。**一条永不触发的告警和"一切正常"看起来完全一样。**
> 递增点补上后它才真的在工作。

> 三条预算相关告警的级别差异是有理由的：
> - `LLMBudgetExhausted` = warning：这是**设计好的降级**（退回规则引擎），不是故障。
>   但必须能看见，否则"解读质量突然变差"会被当成模型问题排查半天。
> - `LLMBudgetLedgerUnavailable` = critical：账本读不出来是**基础设施问题**
>   （DB 锁 / 磁盘满 / 表缺失），不是预算配置问题。
> - `LLMSpendNotRecorded` = critical：钱花了但账没记上，**预算正在静默失效**。
>   记账失败被有意做成不抛异常（为记账失败而丢弃已付费的结果是纯亏损），
>   代价就是它只在这个指标里可见。

> 老文档那张告警表里的 PromQL **全部引用不存在的指标**（见 §3.3 的清单）。
> 那些规则装上去也永远不会触发。

### 5.2 采集阈值告警（代码内，走日志不走 Prometheus）

`backend/app/collectors/metrics.py` 的 `check_alerts()` 按源逐个比对五个阈值，
命中就记 `collection.alert` 日志（coverage_rate 那条是 `info`，其余 `warning`）：

| 指标 | 阈值 | 命中条件 | 级别 |
| --- | --- | --- | --- |
| `success_rate` | 0.95 | 低于且窗口内有运行 | warning |
| `avg_latency_ms` | 30000 | 高于 | warning |
| `freshness_minutes` | 120 | 高于 | warning |
| `coverage_rate` | 0.5 | 低于 | info |
| `duplicate_rate` | 0.5 | 高于 | warning |

每条告警日志带 `source_id` / `metric` / `value` / `threshold` / `severity`。
调度器调用失败记 `unified_scheduler.metrics_alert_failed` /
`collection_scheduler.metrics_alert_failed`。

**这套阈值写在代码里，不可配置**，也不经 Alertmanager ——
要接告警通道，得靠 Loki 对 `collection.alert` 事件做日志告警。

---

## 6. Grafana

`configs/observability/grafana/dashboards/airdrop-system-overview-v2.json`
是一份**真实存在且可用**的面板（Grafana v2 dashboard schema，
标题 `Web3 Airdrop Alpha - System Overview`），10 个面板 / 12 条查询。
**已核对：全部查询引用的指标真实存在。**

| 面板 | 查询要点 |
| --- | --- |
| Pipeline Run Rate | `sum(rate(airdrop_pipeline_runs_total[5m])) by (trigger)` |
| Error Rate | LLM 请求/错误速率与百分比 |
| Projects Scored (24h) | `sum(increase(airdrop_projects_scored_total[24h]))` |
| DB Projects / Raw | `airdrop_db_projects_total`、`airdrop_db_raw_projects_total` |
| Collection Items by Source | `sum(rate(airdrop_collection_items_total[5m])) by (source_id)` |
| Opportunity Shadow Assessments | `sum(airdrop_opportunity_shadow_assessments_total)` |
| Fetcher Concurrency | `airdrop_concurrency_fetcher_semaphore_usage` |
| Circuit Breaker State | `airdrop_fetcher_circuit_breaker_state` |
| Recent Logs (Errors) | Loki 查询 |
| Recent Traces | Jaeger 数据源 |

数据源与面板 provider 配置在同目录的 `datasource.yml` / `dashboard-provider.yml`。

**没有业务面板。** 老文档那张业务面板规格表（评分趋势、赛道热度、
用户反馈趋势）依赖的三个指标都不存在（见 §3.3），面板本身也不存在。

---

## 7. 本地调试观测

不需要部署任何监控栈：

- **日志**：`LOG_FORMAT=json` 时直接是 JSON 行，`python run.py 2>&1 | jq .` 可美化；
  `LOG_FORMAT=console` 走 structlog 的彩色渲染。要落盘设 `LOG_FILE`。
- **指标**：`curl localhost:8002/metrics` 看文本输出（无需鉴权）。
- **链路**：查 `logs` 表，`SELECT * FROM logs WHERE run_id = ? ORDER BY timestamp`。
- **压噪音**：`LOG_LEVEL=WARNING`（现已生效，见 §2.3）。

---

## 8. 部署形态

`docker-compose.prod.yml` 定义了完整的监控栈服务：
`prometheus`、`alertmanager`、`grafana`、`loki`、`promtail`、`otel-collector`、`jaeger`，
配置分别在 `configs/observability/` 与 `docker/loki/`。

抓取目标 `airdrop-web:8002`（compose 内网名），15s 间隔，10s 超时。
`external_labels` 固定 `cluster=airdrop-alpha`、`environment=production` ——
如果 staging 也用这份配置，标签会**谎报为 production**，需按环境覆盖。

---

## 9. 未实现（设计意图，不是现状）

集中列在这里，避免与前面的实测内容混读：

| 项 | 状态 |
| --- | --- |
| 日志采样（debug 10%、按 run_id 哈希一致采样） | 未实现，processor 链无采样 |
| 用户 `note` 入日志前截断 200 字符 | 未实现 |
| `X-Run-Id` 响应头 | 未实现，只有 `X-Disclaimer` |
| `run_id` 贯穿每条日志 | 部分：287 处调用里 19 处带 `run_id` |
| LLM 成本 / token / 预算指标 | ✅ **2026-08-24 已实现**（6 个新指标，见 §3.2），本行保留为移出记录 |
| Agent 粒度指标（耗时、错误、跳过） | ✅ **2026-08-29 已实现**（`airdrop_agent_runs_total` + `airdrop_agent_duration_seconds`，见 §3.2 Agent 段），本行保留为移出记录 |
| 数据质量指标（完整性、新鲜度） | ✅ **2026-08-29 已实现**（`airdrop_data_completeness_ratio` + `airdrop_data_freshness_seconds`，见 §3.2 数据质量段），本行保留为移出记录 |
| 采集配额 / 限流令牌 / 信号新鲜度指标 | 未实现 |
| HTTP 请求耗时 histogram | 未实现，耗时只在日志字段 |
| 业务面板（评分趋势、赛道热度、反馈趋势） | 未实现，依赖的三个指标都不存在 |
| `metrics` 表写入 | 表与仓储都在，但无生产调用方，实测 0 行 |
| 告警抑制 / 分组升级策略 | Alertmanager 侧配置存在，未验证过真实触发 |

**加任何一项时，请连带更新本文档与 `backend/tests/test_observability_doc_parity.py`** ——
那套测试会解析本文档里的指标名与事件名，与代码注册表比对，
文档写了代码没有（或反过来）都会让 CI 变红。

---

_本文档所有数字与行为均于 2026-08-23 实测（§2.2 / §3.2 / §3.3 / §7 / §9 的
LLM 相关内容于 2026-08-24 随日预算拦截实现更新）。指标目录导出自
`backend/app/metrics.py` 注册表；事件名扫描自 `backend/app/` 下全部 logger 调用；
`/metrics`、`/health`、`/version` 与日志级别行为通过真实请求与子进程验证。_
