# 采集 → 分析交接规范（Collection → Analysis Handoff）

> 引用：ADR-012、`SYSTEM_DIRECTION_CHANGE.md`、`DATA_SOURCE_STRATEGY.md`、`DATABASE_DDL.md`、`backend/app/collectors/*`、`backend/app/routers/v1/run.py`
> 阶段：MVP/V1（自动扫描）
> 更新：2026-07-13
> 目的：把「发现」与「评分」之间的契约写死，避免实现各写各的。

---

## 1. 管道总览

```
多源 Collector.collect()
        │
        ▼
persist → data_sources / raw_projects / project_signals / collection_logs
        │
        │  过滤：processed=0 AND discovery_score >= analysis_threshold
        ▼
CollectorAgent.collect_from_repository()  ──►  list[RawProject]
        │
        ▼
Orchestrator（Narrative → Team → Risk → Tokenomics → Scorer）
        │
        ▼
projects 表 + logs；mark raw_projects.processed=1
```

双调度（配置在 `config.py`）：

| 调度 | 职责 | 典型频率 |
|------|------|----------|
| 采集调度 | 拉源、写 raw | 按源 cron（如 DefiLlama `0 8 * * *`） |
| 分析触发 | 对未处理 raw 跑评分 | 定时 / 手动 `POST /api/v1/run`（无 projects body）/ 采集后串联 |

手动输入：`POST /api/v1/run` 带 `projects[]` → **不走** raw 队列，直接 seed 分析（补充路径）。

---

## 2. discovery_score 阈值（权威）

| 配置项 | 默认 | 含义 |
|--------|------|------|
| `discovery_score_analysis_threshold` | **0.3** | 低于此值的 raw **不进入**分析管道（可仍落库作信号） |
| `llm_discovery_score_threshold` | **0.7** | 达到分析门槛后，仅 ≥ 此值且 LLM 开启时走 LLM 增强（ADR-012） |

分级行为：

| discovery_score `s` | 落库 | 进入分析 | LLM（若 enable） |
|---------------------|------|----------|------------------|
| `s < 0.3` | 可写 raw / 信号 | **否** | 否 |
| `0.3 ≤ s < 0.7` | 是 | **是**，规则引擎 | 否 |
| `s ≥ 0.7` | 是 | **是** | 可（预算内） |

实现锚点：

- 取队列：`CollectionRepository.get_unprocessed_raw_projects(min_discovery_score=…)`
- 自动 run：`run.py` 使用 `settings.discovery_score_analysis_threshold`，`limit=100`
- LLM 门：`agents/base.py` / AgentContext 中的 `llm_discovery_score_threshold`

各 Collector 必须输出 **0–1** 的 `discovery_score`（DefiLlama 示例：TVL 40% + 7d 趋势 20% + 多链 15% + 元信息 15% + 社交 10%）。跨源分数**不可直接横向比绝对值**，但共用同一阈值；新源接入时在本文附录登记公式版本。

---

## 3. 入队与出队契约

### 3.1 写入 raw_projects（采集侧）

必填逻辑字段（概念层，列名以 DDL/代码为准）：

| 字段 | 规则 |
|------|------|
| `source_id` | 注册于 `data_sources` |
| `dedup_key` | 源内去重键（见 §4） |
| `raw_data` | JSON；应含 name/url/sector/stage 便于分析 |
| `discovery_score` | float 0–1 |
| `discovered_at` | UTC |
| `processed` | 默认 0 |
| `project_id` | 可选；合并到已有项目时回填 |

同 `(source_id, dedup_key)` 再采：更新 `raw_data` / `discovery_score` / 时间戳（心跳），**不**无故把已 `processed=1` 清零，除非策略显式「重开分析」（当前默认不重开）。

### 3.2 读取未处理队列（分析侧）

```sql
-- 语义等价于 persistence.get_unprocessed_raw_projects
WHERE processed = 0 AND discovery_score >= :min_score
ORDER BY discovery_score DESC, discovered_at DESC
LIMIT :limit
```

默认：`min_score = discovery_score_analysis_threshold`，`limit = 100`（与 `/run` 一致；可配置化时保持单点默认）。

### 3.3 标记已处理

分析成功写入 `projects` 后：

- 调用 `mark_raw_project_processed(raw_id=…, project_id=…)`
- 设置 `processed=1`、`processed_at`、关联 `project_id`
- **失败策略**：单项目 Orchestrator 失败 → 该 raw **不** mark processed（允许重试）；整批部分失败 → 仅成功项 mark（实现须保证按项，而非整批一刀切）

### 3.4 触发时机

| 触发 | 行为 |
|------|------|
| `POST /api/v1/collections/.../trigger` | 只采集 + 持久化，**默认不**自动全量评分（可后续加 feature flag「采集后自动 /run」） |
| `POST /api/v1/run` 无 projects | 从 raw 队列取批评分 |
| Dashboard「运行自动采集评分」 | 先 trigger 已启用源，再 `/run`（前端串联） |
| 分析 cron | 应等价于空 body `/run` 或内部同一服务函数 |

**SLA 目标**（产品 KPI，`SYSTEM_DIRECTION_CHANGE`）：发现 → 评分中位延迟 **&lt; 1h**。实现上至少保证：每日采集后有一次分析触发；或小时级分析 cron。

---

## 4. 去重与字段合并

### 4.1 键

| 范围 | 键 | 用途 |
|------|-----|------|
| 源内 | `(source_id, dedup_key)` | raw 表唯一心跳 |
| 跨源 / 项目 | `normalize(name) + sector`（见 `utils/normalize.py`） | 合并到同一 `projects.id` |

`dedup_key` 由 Collector 生成；名称归一：NFKC、小写、去多余空白/连字符；sector 走 `SECTOR_ALIAS`。

### 4.2 冲突解决（字段谁赢）

| 字段 | 规则 |
|------|------|
| `name` / `url` | 优先：手动录入 > 元数据更完整的源 > 先到源；URL 以可解析 https 为准 |
| `sector` | 归一后冲突 → 保留非 Other/空的一侧；双有效冲突记 log，默认保留先写入 projects 的值 |
| `stage` | 取「更靠后生命周期」需谨慎；MVP：**较高 discovery_score 源**覆盖 |
| 信号 | `project_signals` **追加**，不互相覆盖 |
| `discovery_score` | 跨源合并进分析时：取 **max** 作为 LLM/队列优先级参考，并在 raw_data 保留各源分 |

误合并 / 漏合并目标：去重准确率 ≥ 95%（周检，抽检）。

### 4.3 CoinGecko 等「验证源」

已发币验证可写低 `discovery_score`（如 0.1）作信号，**不**应单独把已发币项目抬进 FARM 队列；分析管道靠阈值自然过滤。

---

## 5. 失败、重试与隔离

| 场景 | 处置 |
|------|------|
| 采集 HTTP/限流失败 | `collection_logs.status=error`；源 `sync_status` 更新；下次 cron 重试 |
| 单条解析失败 | 记日志，跳过该条，不阻断批次 |
| 脏数据 / 校验失败 | 进入 quarantine（若表已启用）；否则 skip + log；**不** mark 为成功 processed |
| 分析 Agent 超时/异常 | 项目级错误计数 +1；raw 保持 unprocessed |
| 连续 N 次分析失败（建议 N=5） | 运维告警；可选人工 mark 或丢入 quarantine |
| 保留期 | `raw_projects_retention_days` 默认 30；已 processed 可归档 `raw_projects_archive` |

重试退避：采集侧沿用各源 `retry` + rate limiter；分析侧重跑 unprocessed 即可，**禁止**对同一 raw 无限并发双跑（单实例用 DB `processed` 条件更新防重）。

---

## 6. 可观测与 KPI 映射

| KPI（方向文档） | 度量来源 |
|-----------------|----------|
| 每日新发现候选 | `raw_projects` 当日 `discovered_at` 计数 |
| 进入分析数 | 当日 `processed` 翻转或 `/run` scored_count |
| 采集成功率 | `collection_logs.status='success'` 占比 |
| 发现→评分延迟 | `processed_at - discovered_at` 中位数 |
| 多源命中率 | 同 dedup/跨源 project 关联 ≥2 source 占比 |

建议指标名（与 OBSERVABILITY 对齐时注册）：

- `airdrop_raw_projects_unprocessed`（gauge）
- `airdrop_collection_runs_total{source,status}`
- `airdrop_handoff_queue_latency_seconds`（histogram）

---

## 7. API 与实现检查清单

- [x] `get_unprocessed_raw_projects` + `mark_raw_project_processed`
- [x] `/run` 空 body 走 repository
- [x] 阈值配置项存在
- [x] 分析 cron（`SCHEDULER_ENABLED` + `CRON_EXPRESSION`）与采集 cron 双调度（`main.py` 启动）
- [x] 部分失败仅 mark 成功项（`pipeline_run.mark_successful_raw_projects` + 测试）
- [x] 采集后可选 auto-run：`COLLECTION_AUTO_RUN_ENABLED`（默认 false）
- [ ] quarantine 全链路与 SLA 工单

---

## 8. 附录：源与 score 公式版本（登记表）

| source_id | 公式摘要 | 代码 |
|-----------|----------|------|
| defillama | TVL/趋势/多链/元信息/社交加权 | `collectors/defillama.py` |
| github | 活跃度启发 | `collectors/github.py` |
| coingecko | 验证向，低分 | `collectors/coingecko.py` |
| twitter | 信号启发 | `collectors/twitter.py` |
| etherscan | 合约活跃 | `collectors/etherscan.py` |
| galxe / layer3 | 任务/活动 | 对应文件 |

新源 PR 必须：更新本表 + 单测 discovery_score 边界 + 是否计入 analysis 队列。

---

_文档版本：v1.0 · 2026-07-13_
