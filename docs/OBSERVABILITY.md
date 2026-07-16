# 可观测性设计规�?
> 配套文档：`ENGINEERING_ROADMAP.md` §20、`ENGINEERING_ROADMAP.md` §15.5。本文档定义日志、指标、追踪、告警的具体实现规范，供后端实现与运维部署直接照做�?
---

## 1. 设计原则

1. **三支柱分�?*：日志（结构化事件）+ 指标（聚合数值）+ 追踪（链路上下文），各司其职不混淆�?2. **贯穿 run_id**：每�?pipeline 触发生成 `run_id`，从 API 入口贯穿�?DB 写入，可在三者中双向查询�?3. **MVP 轻量**：structlog + 简�?`/metrics` 文本端点；不引入额外中间件即可本地观测�?4. **V2 生产�?*：Loki + Prometheus + Grafana + OpenTelemetry，容器化部署�?5. **不阻塞主流程**：观测代码失败不能中�?pipeline；指标采集用异步/采样�?
---

## 2. 日志规范

### 2.1 结构（structlog JSON�?每条日志必须含以下字段（缺省�?`null`）：
```json
{
  "timestamp": "2026-07-08T08:00:12.345Z",
  "level": "info",
  "event": "agent.run.start",          // 事件名，点分命名
  "run_id": "r-abc123",
  "project_id": "a1b2c3d4",
  "agent_name": "narrative",
  "duration_ms": 124,
  "error": null,
  "meta": { "llm_enabled": false, "weight_version": "v1" }
}
```

### 2.2 事件命名规范
`<scope>.<subject>.<verb>`，全小写点分�?| 事件 | 含义 | level |
| --- | --- | --- |
| `api.request.start` | API 请求进入 | info |
| `api.request.end` | API 请求完成 | info |
| `run.start` | pipeline 触发 | info |
| `run.end` | pipeline 完成 | info |
| `run.error` | pipeline 失败 | error |
| `agent.run.start` | agent 执行开�?| debug |
| `agent.run.end` | agent 执行完成 | info |
| `agent.run.error` | agent 执行失败 | error |
| `agent.llm.fallback` | LLM 回退规则 | warn |
| `fetcher.fetch.start` | 外部源拉�?| debug |
| `fetcher.fetch.error` | 拉取失败 | warn |
| `fetcher.circuit.open` | 熔断开�?| warn |
| `db.write.error` | DB 写失�?| error |
| `llm.budget.exceeded` | LLM 超预�?| warn |

### 2.3 级别使用
- `debug`：单 agent 内部步骤、fetcher 细节（生产默认关�?- `info`：run/agent 完成、API 请求
- `warn`：降级、熔断、回退、超预算（不中断但需关注�?- `error`：pipeline 失败、DB 写失败、agent 异常（需告警�?
### 2.4 采样
- `debug` 级别生产环境�?10% 采样（高 QPS 时降低噪音）�?- `error` 永不采样�?- 采样�?structlog processor 层实现，�?`run_id` 哈希保证�?run 日志一致采样�?
### 2.5 敏感信息
- 密钥/token **绝不**入日志；structlog processor 自动 redact `*_key`/`*_token`/`*_bearer`/`authorization` 字段�?- 用户 `note`（feedback）截�?200 字符再入日志，防超长/注入�?
---

## 3. 指标规范（Prometheus�?
### 3.1 暴露端点
- `GET /metrics`：Prometheus 文本格式，无鉴权（内网）�?- 命名遵循 [Prometheus naming](https://prometheus.io/docs/practices/naming/)：`<namespace>_<subsystem>_<name>_<unit>`�?- 本项�?namespace = `airdrop`，例：`airdrop_run_total`、`airdrop_agent_duration_seconds`�?
### 3.2 完整指标目录

#### Pipeline �?| 指标 | 类型 | 标签 | 含义 |
| --- | --- | --- | --- |
| `airdrop_run_total` | counter | `source, status` | pipeline 触发次数（status=success/error�?|
| `airdrop_run_duration_seconds` | histogram | `source` | 端到端耗时（buckets: 1,5,10,30,60,120,300�?|
| `airdrop_projects_analyzed_total` | counter | �?| 累计分析项目�?|
| `airdrop_projects_inserted_total` | counter | �?| 累计新增入库 |
| `airdrop_projects_updated_total` | counter | �?| 累计更新 |

#### Agent �?| 指标 | 类型 | 标签 | 含义 |
| --- | --- | --- | --- |
| `airdrop_agent_duration_seconds` | histogram | `agent, status` | �?agent 耗时 |
| `airdrop_agent_errors_total` | counter | `agent, kind` | 失败次数（kind=llm_fallback/timeout/exception�?|
| `airdrop_agent_skipped_total` | counter | `agent, reason` | 跳过次数（reason=missing_data/circuit_open�?|

#### Fetcher �?| 指标 | 类型 | 标签 | 含义 |
| --- | --- | --- | --- |
| `airdrop_fetcher_duration_seconds` | histogram | `source` | 外部源拉取耗时 |
| `airdrop_fetcher_errors_total` | counter | `source, code` | 拉取失败（code=4xx/5xx/timeout/network�?|
| `airdrop_fetcher_circuit_open` | gauge | `source` | 熔断状态（0/1�?|
| `airdrop_fetcher_cache_hits_total` | counter | `source` | 缓存命中 |

#### 采集层（v2.0，ADR-012�?> 自动扫描模式下采集管道的核心指标。对�?`DATA_SOURCE_STRATEGY.md §采集质量评估指标` �?`OPERATIONS.md §4.3`�?
| 指标 | 类型 | 标签 | 含义 |
| --- | --- | --- | --- |
| `airdrop_collection_total` | counter | `source, status` | 采集任务计数（status=success/error/partial/rate_limited�?|
| `airdrop_collection_duration_seconds` | histogram | `source` | 单次采集耗时 |
| `airdrop_collection_success_ratio` | gauge | `source` | 采集成功率（7 日滚动窗口） |
| `airdrop_collection_status` | gauge | `source, status` | 当前状态（0/1，status=idle/running/error/rate_limited�?|
| `airdrop_collection_api_calls` | counter | `source` | API 调用次数累计 |
| `airdrop_collection_api_calls_today` | gauge | `source` | 当日 API 调用数（每日 00:00 UTC 重置�?|
| `airdrop_collection_items_total` | counter | `source, type` | 采集项目计数（type=total/new/duplicate�?|
| `airdrop_collection_running` | gauge | `source` | 当前正在运行的采集任务数 |
| `airdrop_rate_limiter_tokens` | gauge | `source` | 令牌桶剩余令牌数 |
| `airdrop_discovery_score_distribution` | histogram | `source` | discovery_score 分布（buckets: 0.1,0.3,0.5,0.7,0.9�?|
| `airdrop_projects_discovered_total` | counter | `source` | 累计发现项目数（去重后进�?raw_projects�?|
| `airdrop_projects_analyzed_from_discovery_total` | counter | �?| 累计从自动发现进入分析管道的项目�?|
| `airdrop_collection_signal_freshness_seconds` | gauge | `source` | 信号新鲜度（信号产生到入库的延迟�?|

> **采集质量聚合指标**（每�?每月计算，写�?`evaluation/collection/`）：
> - 误报率、漏报率、源覆盖率、去重准确率——这些为离线计算的聚合指标，不作为实�?Prometheus 指标暴露，而是�?`evaluation/collection/YYYY-MM.md` 报告形式产出�?
#### LLM �?| 指标 | 类型 | 标签 | 含义 |
| --- | --- | --- | --- |
| `airdrop_llm_calls_total` | counter | `agent, model, status` | LLM 调用（status=success/fallback/timeout�?|
| `airdrop_llm_cost_usd_total` | counter | `model` | 累计成本 |
| `airdrop_llm_tokens_total` | counter | `model, direction` | token 用量（direction=in/out�?|
| `airdrop_llm_budget_remaining_usd` | gauge | �?| 当日剩余预算 |

#### DB �?| 指标 | 类型 | 标签 | 含义 |
| --- | --- | --- | --- |
| `airdrop_db_write_errors_total` | counter | �?| DB 写失�?|
| `airdrop_db_query_duration_seconds` | histogram | `operation` | DB 查询耗时 |
| `airdrop_projects_in_db` | gauge | `label` | 库内项目计数 |

#### API �?| 指标 | 类型 | 标签 | 含义 |
| --- | --- | --- | --- |
| `airdrop_http_requests_total` | counter | `method, path, status` | HTTP 请求计数 |
| `airdrop_http_request_duration_seconds` | histogram | `method, path` | HTTP 耗时 |

#### 业务层（V2 产品面板�?| 指标 | 类型 | 标签 | 含义 |
| --- | --- | --- | --- |
| `airdrop_narrative_heat_score` | gauge | `sector` | 各赛道当前热度（Narrative Agent 输出�?|
| `airdrop_feedback_total` | counter | `signal` | 用户反馈数（�?useful/useless/wrong_label/correct_outcome 拆分�?|
| `airdrop_project_score` | gauge | `project_id` | 项目当前 score（高基数标签，仅供业务面板趋势展示） |

> **注意**：`airdrop_project_score` 使用 `project_id` 标签，属于高基数指标。仅用于业务面板�?Top 10 趋势，不应在全局聚合查询中使用；V3 建议改用时序数据库或 Grafana 直连 `project_history` 表�?
#### 数据质量（每�?run 后更新）
| 指标 | 类型 | 标签 | 含义 |
| --- | --- | --- | --- |
| `airdrop_data_completeness_ratio` | gauge | `field` | 必填字段非空�?|
| `airdrop_data_freshness_seconds` | gauge | `source` | 数据 age P95�?*V2 才产�?*，依�?`projects.fetched_at`；MVP seed 数据不度量，�?`DATA_QUALITY.md` §8.3�?|

### 3.3 实现
- �?`prometheus_client`（Python）�?- MVP：进程内 collector；V2：接 Prometheus scrape�?0s interval）�?- histogram buckets 需覆盖实际分布，避免全部落同一�?bucket�?
### 3.4 标签基数控制
- 标签值必须有限集（如 `status` 只能 success/error）；禁止�?`project_id`/`run_id` 作标签（高基数爆炸）�?- 高基数信息走日志/追踪，不走指标�?
### 3.5 Opportunity Shadow

Opportunity v2.0 Shadow exposes these five metric families:

```text
airdrop_opportunity_shadow_projects_total{result}
airdrop_opportunity_shadow_assessments_total{status,public_label,model_version,profile_version}
airdrop_opportunity_shadow_duration_seconds
airdrop_opportunity_shadow_enabled
airdrop_opportunity_shadow_sample_rate
```

The `result` label allows exactly six bounded values: `eligible`, `sampled`, `attempted`, `saved`, `failed`, and `skipped`. The assessment `status`, `public_label`, `model_version`, and `profile_version` labels must also remain bounded enums or version constants. Never use project ID, assessment ID, URL, or error text as metric labels; send that high-cardinality context to structured logs instead.

Build alerts from the observed scheduling baseline rather than treating one threshold as universal production fact. For example:

- Calculate `failed / attempted` over a normal scheduling window, and evaluate it only when `attempted` increases.
- After increasing the sample rate, investigate when `sampled` or `attempted` increases but `saved` does not. Check assessment statuses and labels, logs, and database health.

Choose ratios and durations for each environment based on its normal volume and error budget.
---

## 4. 链路追踪

### 4.1 MVP（日志关联）
- `run_id` 贯穿：API 入口生成 �?传给 Orchestrator �?每个 agent �?写库�?- 每个 agent �?`logs` 表记录含 `run_id`，可反向�?`WHERE run_id=?` 重建链路�?- `GET /project/{id}` 可查该项目所有历�?run �?agent 执行记录�?
### 4.2 V2（OpenTelemetry�?- 引入 `opentelemetry-instrumentation-fastapi` 自动埋点�?- 每个 agent 是一�?span，`run_id` 作为 trace attribute�?- Span 结构�?  ```
  trace: run_id
  ├── span: orchestrator.collect
  ├── span: orchestrator.analyze (parallel)
  �?  ├── span: narrative.run
  �?  ├── span: team.run
  �?  ├── span: risk.run
  �?  └── span: tokenomics.run
  ├── span: scorer.score
  └── span: db.write
  ```
- 导出：OTLP �?Jaeger/Tempo（V2）�?- 采样：尾部采样（error 100% 采样，success 10%），降低成本�?
### 4.3 上下文传�?- `run_id` 注入 HTTP 响应�?`X-Run-Id`，便于前�?用户报障时定位�?- `POST /run` 返回 `run_id`；`GET /project/{id}` 响应含最�?`run_id`�?
---

## 5. 告警规则（V2+�?
### 5.1 告警分级
| 级别 | 响应 | 通知渠道 |
| --- | --- | --- |
| critical | 立即�?30min�?| PagerDuty/电话 |
| warning | 工作时间处理 | Slack/邮件 |
| info | 仅记录，不通知 | �?|

### 5.2 规则�?| 规则 | PromQL | 级别 | 说明 |
| --- | --- | --- | --- |
| pipeline 连续失败 | `increase(airdrop_run_total{status="error"}[15m]) >= 2` | critical | 2 次连续失败即告警 |
| DB 写入异常 | `increase(airdrop_db_write_errors_total[5m]) > 0` | critical | DB 是核心，任何写失败都需处理 |
| 健康检查失�?| `probe_success{job="health"} == 0 for 2m` | critical | blackbox exporter 探测 |
| 外部源熔�?| `airdrop_fetcher_circuit_open == 1 for 5m` | warning | 熔断持续 5min |
| LLM 成本超预�?| `airdrop_llm_cost_usd_total > daily_budget_usd` | warning | 当日成本超限 |
| 分析耗时退�?| `histogram_quantile(0.95, airdrop_run_duration_seconds) > 30` | warning | P95 > 30s |
| 数据完整性下�?| `airdrop_data_completeness_ratio < 0.8` | warning | 任一必填字段非空�?<80% |
| 数据过期 | `airdrop_data_freshness_seconds > 3 * ttl` | warning | 数据 age > 3×TTL |
| agent 错误�?| `rate(airdrop_agent_errors_total[10m]) / rate(airdrop_agent_duration_seconds_count[10m]) > 0.1` | warning | �?agent 错误�?>10% |
| **采集调度器停�?*（v2.0�?| `increase(airdrop_collection_total[2h]) == 0` | critical | 2 小时无任何采集任务执�?|
| **采集成功率低**（v2.0�?| `airdrop_collection_success_ratio < 0.9` | warning | 采集成功�?<90% |
| **采集源限流持�?*（v2.0�?| `airdrop_collection_status{status="rate_limited"} == 1 for 10m` | warning | 某源持续限流 10min |
| **发现项目数异�?*（v2.0�?| `increase(airdrop_projects_discovered_total[24h]) < 5` | warning | 日发现项�?<5（远低于 KPI 20/日） |
| **付费源配额接近上�?*（v2.0�?| `airdrop_collection_api_calls_today > 0.9 * api_limit` | warning | 当日 API 调用达限�?90% |
| **信号新鲜度差**（v2.0�?| `airdrop_collection_signal_freshness_seconds > 14400` | warning | 信号延迟 >4 小时 |

### 5.3 告警抑制与聚�?- 同一 `source`/`agent` 的告�?5min 内聚合，避免轰炸�?- critical 告警未确�?15min 自动升级通知渠道�?- 维护窗口期（手动标注）抑制非 critical 告警�?
### 5.4 Alertmanager 路由
```yaml
route:
  receiver: slack-default
  group_by: [alertname, source]
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h
  routes:
    - matchers: [severity="critical"]
      receiver: pagerduty
    - matchers: [severity="warning"]
      receiver: slack
```

---

## 6. Grafana Dashboard（V2�?
### 6.1 运维面板（给开发者）
- **概览�?*：今�?run 数、成功率、P95 耗时、库内项目数
- **Pipeline �?*：run_duration 直方图、按 source 拆分
- **Agent �?*：各 agent 耗时分布、错误率、跳过率
- **Fetcher �?*�? 源成功率、熔断状态、缓存命中率
- **LLM �?*：调用数、成本曲线、剩余预算、fallback �?- **DB �?*：写错误、查询耗时、按 label 项目计数
- **数据质量�?*：完整性、新鲜度

### 6.2 业务面板（给产品/运营，可选）
- 每日 Top 10 项目（score 趋势�?- FARM/WATCH/IGNORE 分布
- 赛道热度排行
- 用户反馈数（V2 后）

#### 6.2.1 业务面板详细规格（V2+�?
> Grafana 业务面板面向产品/运营，与运维面板区分�?
**面板�?*�?
| �?| 内容 | PromQL 示例 |
|---|---|---|
| 概览 | 今日新增项目数、FARM/WATCH/IGNORE 计数 | `airdrop_projects_in_db{label="FARM"}` |
| 评分趋势 | 每日 Top 10 项目 score 变化曲线 | `topk(10, airdrop_project_score)` by `project_id` |
| Label 分布 | FARM/WATCH/IGNORE 饼图 | `airdrop_projects_in_db` by `label` |
| 赛道热度 | 各赛�?heat_score 排行 | `airdrop_narrative_heat_score` by `sector` |
| 用户反馈 | 反馈数趋势（useful/useless 拆分�?| `increase(airdrop_feedback_total[1d])` by `signal` |
| 数据质量 | 完整�?新鲜度综合评�?| `airdrop_data_completeness_ratio` |

**面板变量**�?- `$time_range`：默认最�?7 �?- `$sector`：赛道筛选（全部/特定赛道�?- `$label`：标签筛选（全部/FARM/WATCH/IGNORE�?
**阈值告�?*�?- FARM 项目数日环比下降 >50% �?warning
- 用户 useless 反馈�?>30% �?warning（评分质量退化信号）

### 6.3 面板变量
- `$source`：数据源筛�?- `$agent`：agent 筛�?- `$time_range`：默认最�?24h

---

## 7. 本地调试观测

MVP 阶段无需部署 Loki/Prometheus，仍可观测：
- **日志**：`docker logs -f airdrop-alpha` 直接�?JSON；或 `python run.py 2>&1 | jq .` 美化�?- **指标**：`curl localhost:8002/metrics` 看文本格式输出�?- **链路**：查 SQLite `logs` �?`SELECT * FROM logs WHERE run_id=? ORDER BY timestamp`�?
---

## 8. 容量预估

| 信号�?| MVP 单日体量 | V2 单日体量 |
| --- | --- | --- |
| 日志 | ~5k 行（50 项目 × 5 agent × 2 事件�?| ~50k �?|
| 指标 | ~50 �?series | ~500 �?series |
| 追踪 span | 0（MVP �?OTel�?| ~500/day |

- 日志保留：本�?stdout 不持久；V2 Loki 保留 30 天热 + 90 天冷�?- 指标保留：Prometheus 默认 15 天；V3 接长期存储（Thanos/Mimir）�?- 追踪保留：Jaeger 默认 7 天�?