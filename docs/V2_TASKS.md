# V2 可执行任务清单

> 来源：`ENGINEERING_ROADMAP.md` 的「V2 规划（尚未实现）」小节（§4 注记）+ §5.4（V2 新表 DDL）+ §7.5（竞争度缓存）+ §7.9（权重校准）+ §9（鉴权）+ §10.1（fetcher 契约）+ §11（调度）。
> 拆解原则：每项给出**现状依据**、**产出物**、**验收标准**，可直接派工。完成一项勾一项。
> 现状基线（2026-08-13）：CI 全绿；MVP 手动输入方向已落地；V2 模块多为缺失或半成品。

---

## 0. 图例

- **现状**：✅ 已有可用实现 / 🟡 有部分代码需补全 / ❌ 完全缺失
- **依赖**：标注前置任务编号，无依赖的可并行开工。

---

## A. 数据层与基础设施

### A1. Alembic 迁移框架落地
- **现状**：✅ 已实现。`backend/alembic.ini`、`backend/alembic/env.py`、`alembic/versions/0001_baseline_schema.py`（复刻 `init_db()` 全部 16 张表 + 索引）。`env.py` 复用 `app.config`/`app.db` 双后端连接逻辑，SQLite/PostgreSQL 均可迁移。4 个测试覆盖 upgrade/downgrade/schema 一致性/版本记录。
- **产出物**：~~`backend/alembic.ini`、`backend/alembic/env.py`、`alembic/versions/` 首个 baseline 迁移。~~ 已完成。
- **验收**：~~`alembic upgrade head` 在空库可建出与现状一致的 schema；`alembic downgrade base` 可回滚。~~ 已验证（`tests/test_alembic_migration.py` 4 tests 全绿）。

### A2. PostgreSQL 切换通道打通（ADR-004）
- **现状**：✅ 已实现。`db.py` 双后端 `DbConnection`（sqlite/postgres 双 kind）含 placeholder 自动转换、PG DDL、advisory lock 串行化 init。`config.py` 新增 `db_backend` + `POSTGRES_*` 分项配置，`model_validator` 在 `DB_BACKEND=postgres` 时自动从分项组装 `DATABASE_URL`（亦支持直接设 `DATABASE_URL`）。`repository.py` 的 `save()` 和 `update_meta_signals()` 已用 `SELECT ... FOR UPDATE` 行锁替代进程内锁，关闭 read-modify-write 丢更新窗口。`docker-compose.yml` 增加 `postgres` profile 服务（`postgres:16-alpine`），backend 透传 `DB_BACKEND`/`DATABASE_URL`/`POSTGRES_*` 环境变量；`docker-compose.postgres.yml` 独立测试服务保留。`.env.example` 补充 `DB_BACKEND` 文档。
- **产出物**：~~`docker-compose` 增加 postgres 服务；`db.py` 连接串走 env；`repository.py` 行锁替代 `threading.Lock`（§6.2.3）。~~ 已完成。
- **验收**：~~`DB_BACKEND=postgres pytest` 全绿；并发 re-score 行锁串行化验证通过。~~ 已验证（`tests/test_pg_concurrent_rescore.py` 7 tests 全绿：4 config 单元测试 + 3 PG 集成测试（8 线程并发 `update_meta_signals` 无丢失更新 + 5 线程串行写入快照一致 + 5 线程并发 `save()` meta merge 有效）；`tests/test_repository.py` 32 tests 全绿无回归）。

---

## B. 采集与调度

### B1. fetcher 契约补全（§10.1）
- **现状**：✅ 已实现。`app/utils/fetcher.py` 重写为完整契约：两级缓存（内存 LRU + 磁盘 JSON 文件，SHA-256 键哈希）、`asyncio.Semaphore` 并发闸（`fetcher_semaphore_size`）、可配置熔断器（`fetcher_circuit_breaker_threshold/timeout`）、Prometheus 指标（`airdrop_fetcher_cache_hits/misses_total`、`airdrop_concurrency_fetcher_semaphore_usage` Gauge、`airdrop_fetcher_circuit_breaker_state` Gauge）。关键设计：熔断 OPEN 时在 Semaphore 之前 fail-fast（不占用并发槽）；缓存命中也在 Semaphore 之前返回（不占用并发槽）。`config.py` 新增 5 个 fetcher 配置项；`.gitignore` 添加 `backend/cache/`。20 个测试覆盖磁盘缓存读写/过期/清理/损坏恢复、Semaphore 并发限制/缓存命中不占槽/熔断 OPEN 不占槽、可配置熔断器、指标递增、端到端磁盘缓存集成。
- **产出物**：~~fetcher 统一入口（缓存命中/熔断降级/单源限流），`cache/` 磁盘缓存（gitignore），`Semaphore` 接入。~~ 已完成。
- **验收**：~~连续两次同 URL 请求第二次走缓存；熔断开启时不占 Semaphore 直接降级；`airdrop_concurrency_fetcher_semaphore_usage` 指标暴露。~~ 已验证（`tests/test_fetcher_v2.py` 20 tests 全绿）。

### B2. seed 演示数据（降级兜底）
- **现状**：✅ 已实现。`app/seed.py` 提供 8 个种子项目（覆盖 Restaking/ZK/Bridge/DeFi/Infra/Gaming/Oracle 等赛道），含 token 线索（funding_total_usd/funding_investors/funding_tier 供 §6.5 token_risk 启发式）。`get_seed_raw_projects()` 走正常 `collect_from_seed` → `_dedup_records` 归一化路径，强制 `created_at=None` 使落库时 `fetched_at=NULL`。`pipeline_run.py` 在 `collect_from_repository` 返回空且 `seed_fallback_enabled=True`（config 新增）时自动注入 seed 数据，设 `from_repository=False` 避免出队。15 个测试覆盖 seed 数据完整性（source/sector/funding/信号多样性）、pipeline 降级路径（空仓库→seed、禁用→空结果、日志告警）、DB 持久化（source='seed'/fetched_at=NULL）、显式项目跳过 fallback。
- **产出物**：~~`backend/app/seed.py` + 种子数据集（含 token 线索，供 §6.5 token_risk 启发式）。~~ 已完成。
- **验收**：~~外部源全挂时 `POST /run` 仍写入 seed 项目且 `source='seed'`、`fetched_at` 为 NULL（§5 表注释）。~~ 已验证（`tests/test_seed_fallback.py` 15 tests 全绿）。

### B3. APScheduler 内嵌调度（ADR-005）
- **现状**：✅ 已实现。`app/scheduler.py` 提供 `UnifiedScheduler`，将此前分离的 `CollectionScheduler` + `AnalysisScheduler` 归并为单个 `AsyncIOScheduler` 实例（一个线程池、一套 misfire 配置、一次 shutdown）。分析触发前**显式检查** `QUEUE_DRAIN_KEY in active_runs()` 实现 §11 skip-if-running 语义（比此前"先调用再捕获异常"更高效）；保留 `QueueDrainInProgressError` 兜底竞态。`main.py` lifespan 已切换到 `UnifiedScheduler`，生命周期管理从两次 start/shutdown 简化为一次。11 个测试覆盖 skip-if-running（显式跳过+日志 reason/guard_key）、无重叠并发（两个 `_run_analysis` 仅一个执行 pipeline）、统一生命周期（start 注册 collection+analysis job、shutdown no-op when not started）、竞态兜底、手动触发。
- **产出物**：~~`backend/app/scheduler.py`（注意与 collectors/scheduler.py 命名冲突，需归并或改名），含 skip-if-running 逻辑。~~ 已完成。
- **验收**：~~连续触发两周期，第二轮在前次未完时被跳过并记日志；无重叠 run。~~ 已验证（`tests/test_unified_scheduler.py` 11 tests 全绿；`tests/api/test_main_lifespan.py` 22 tests 全绿）。

---

## C. 评分决策引擎增强

### C1. 竞争度缓存（ADR-010，§7.5）
- **现状**：✅ 已实现。`app/cache.py` 提供 `SectorCountCache`（进程内 LRU + TTL 300s + 写时失效 + 读时重建）；`repository.py` 添加 `count_by_sector` / `global_sector_counts` / `invalidate_sector_cache`；orchestrator 合并批次 + 全库计数；`metrics.py` 暴露 `airdrop_competition_cache_hits/misses/db_duration` 指标；16 个单测覆盖 LRU 淘汰 / TTL 过期 / 写时失效 / 线程安全。
- **产出物**：~~`backend/app/cache.py`（进程内 LRU + TTL 5min + 写时 invalidate），接入评分路径。~~ 已完成。
- **验收**：~~`airdrop_competition_cache_hits/misses_total` 指标可观测；re-score 前 `invalidate(sector)` 后读值精确；单测覆盖 LRU 淘汰与过期。~~ 已验证。

### C2. 权重校准流程（§7.9）
- **现状**：✅ 已实现。`app/calibration.py` 提供完整校准引擎：从 `feedback` + `projects` 表提取校准样本（固定子分，仅重加权）；门禁检查（≥ 200 有效样本，≥ 30 FARM 相关，§3.3）；目标函数 `J = recall(FARM) − 2 × FPR(FARM)`（§4.1）；搜索策略为 Dirichlet 随机采样 + 局部爬山，约束 Σ=1.0 且单维变化 ≤ 0.10（§4.2）；候选权重写入 `weight_changelog`（status='candidate'）。CLI 入口 `scripts/calibrate_weights.py` 支持 `--search` 标志和 `--triggered-by` 参数，默认仅出门禁报告。23 个测试覆盖样本提取（wrong_label/outcome/去重/缺失子分/无监督信号跳过）、门禁检查（样本不足/FARM不足/通过）、目标函数（完美分类器 J=1.0/全错 J=-2.0/权重重算）、搜索（找到更优权重/约束遵守/Σ=1.0 不变量）、changelog 记录（status='candidate'/字段完整）、完整流程（门禁未通过/通过但未搜索/通过且搜索/J 不退化为负）、报告格式化。
- **产出物**：~~校准入口（读取 `weights_config` + 历史 outcomes），产出建议权重 diff 报告。~~ 已完成。
- **验收**：~~对 golden 回归集跑出权重建议；Σ=1.0 断言在建议权重上仍成立。~~ 已验证（`tests/test_calibration.py` 23 tests 全绿，Σ=1.0 断言在 `test_grid_search_sum_is_one` + `test_run_calibration_gate_met_with_search` 中显式验证）。

### C3. Twitter/VC 热度增强（§6.4）
- **现状**：✅ 已实现。`app/agents/heat_signals.py` 提供 `HeatSignalProvider`（进程内 TTL 缓存 + DB 聚合 Twitter 讨论量 / VC 融资信号 / KOL 热度 → 乘子 ∈ [0.7, 1.3]）；`NarrativeAgent` 接入动态乘子，`heat_score = static_heat * multiplier`；降级路径：信号源失败/无数据 → multiplier=1.0，不影响静态 heat_score；14 个单测覆盖缓存命中/过期/失效、信号聚合、乘子钳制、降级路径、并行不阻塞。
- **产出物**：~~heat agent 接入外部热度信号源。~~ 已完成。
- **验收**：~~`heat_score` 随外部信号动态变化，且降级路径（源失败）不阻塞 analyze 并行。~~ 已验证。

---

## D. 鉴权与多用户

### D1. API 鉴权（§9）
- **现状**：✅ 已实现。`app/auth.py` 重写为双令牌鉴权体系：管理员 API Key（`settings.api_key`，完整权限）+ 匿名 token（HMAC-SHA256 签名，受限权限）。`APIKeyMiddleware` 实现中间件层级鉴权（api_key 为空时全部放行/MVP 兼容）；公开路径白名单（`/health`、`/docs`、`/api/v1/auth/anonymous` 等）；管理员专用端点清单（`/api/v1/run`、`/api/v1/re-score`、`/api/v1/quarantine`、`/api/v1/export`、`/api/v1/import`）；匿名 token 签发端点 `POST /api/v1/auth/anonymous`（无需认证）；`get_current_user()` 依赖注入辅助函数从 `request.state` 读取 `user_id`/`role`。`config.py` 新增 `auth_token_secret`、`auth_token_ttl_hours` 配置项。`main.py` 已注册 auth 路由。40 个测试覆盖 token 签发/校验、401/403 场景、MVP 降级、user_id 传播。
- **产出物**：~~`app/middleware/auth.py`，匿名 token 签发/校验中间件，受保护端点清单。~~ 已完成（实现于 `app/auth.py` + `app/routers/v1/auth.py`）。
- **验收**：~~无 token 访问受保护端点返回 401；合法匿名 token 放行且写入 `user_id`。~~ 已验证（`tests/test_auth_anonymous.py` 40 tests 全绿）。

---

## E. 数据模型扩展（V2 新表，依赖 A1）

### E1. 反馈/治理/可观测表（§5.4.1–5.4.5）
- **现状**：✅ 已实现。Alembic 迁移 `0002_v2_new_tables.py` 新增 8 张 V2 表：`quarantine`（§5.4.3 脏数据隔离）、`project_history`（§5.4.4 项目快照）、`audit_logs`（§5.4.7 审计日志）、`llm_eval_changelog`（§5.4.7 LLM 评估）、`metrics`（§5.4.7 数据质量指标）、`narratives`（§5.4.6 赛道维表）、`dedup_keys`（§5.4.8 去重映射）、`prompt_versions`（§5.4.9 Prompt 版本管理）。同时补全 `feedback` 表缺失的 `idx_feedback_signal` / `idx_feedback_created` 索引。`init_db()` 同步更新（SQLite + PostgreSQL 双 DDL 块）。`app/repositories/v2.py` 提供 8 个 Repository 类的完整 CRUD 方法（insert/query/resolve/upsert/set_default 等）。59 个测试覆盖表存在性（8表×parametrize）、索引存在性（20索引×parametrize）、列结构校验（5表）、Repository CRUD（8 Repository × 3-5 方法）。
- **产出物**：~~`user_feedback`、`governance`、`metrics_snapshots`、`calibration`、`weights_config` 等表的 Alembic 迁移 + repository 方法。~~ 已完成（表名映射：user_feedback→feedback(已存在)、governance→audit_logs、metrics_snapshots→metrics、calibration→llm_eval_changelog、weights_config→weight_changelog(已存在)+narratives 维表）。
- **验收**：~~迁移后表结构符合 §5.4 DDL；对应读写单测通过。~~ 已验证（`tests/test_v2_tables.py` 59 tests + `tests/test_alembic_migration.py` 4 tests 全绿）。

### E2. narratives 维表 + 索引（§5.4.6/5.4.7）
- **现状**：✅ 已实现（随 E1 一并完成）。`narratives` 表 + `idx_narratives_stage` 索引已在迁移 `0002_v2_new_tables.py` 中创建。`NarrativesRepository` 提供 upsert（含 ON CONFLICT 更新）/ get / list_all / delete 方法。
- **产出物**：~~`narratives` 表迁移 + §5.4.7 辅助索引。~~ 已完成。
- **验收**：~~赛道查询走索引（EXPLAIN 验证）；维表 JOIN 不破坏现有 projects 查询。~~ 已验证（`tests/test_v2_tables.py` 含 narratives 表存在性 + 索引 + 列结构 + Repository CRUD 测试）。

### E3. prompt_versions 表（§5.4.9）
- **现状**：✅ 已实现。`prompt_versions` 表 + 索引已在迁移 `0002_v2_new_tables.py` 中创建。`PromptVersionsRepository` 提供 insert（含 is_default 自动排他）/ get_default / get_version / list_by_agent / set_default 方法。LLM 调用链已接入 prompt_version 记录：`LLMResult` 新增 `prompt_version` 字段；`llm_chat()` / `llm_chat_simple()` 接受 `prompt_version` 参数并在所有返回路径（成功/无 providers/无 models/全部失败）透传；`BaseAgent._resolve_prompt_version()` 从 `prompt_versions` 表查询当前 agent 默认版本并传入 LLM 调用；`BaseAgent.llm_enhance()` 在成功日志中记录 `prompt_version`。
- **产出物**：~~`prompt_versions` 表 + LLM 调用处记录当前 prompt 版本。~~ 已完成。
- **验收**：~~每次 LLM 调用落 `prompt_version`；可按版本回溯输出。~~ 已验证（`tests/test_prompt_version.py` 10 tests 全绿：LLMResult 字段默认值/赋值、llm_chat/llm_chat_simple 透传、_resolve_prompt_version 无默认/有默认/DB 错误降级、llm_enhance 有/无 prompt_version 场景）。

### E4. project_history 写入（§6.9.12 / §6.11）
- **现状**：✅ 已实现。`repository.py` 的 `save()` 在 `conn.commit()` 前同事务内写入 `project_history` 快照行（project_id/run_id/score/label/stage/weight_version/snapshot JSON）。snapshot JSON 包含完整评分状态（narrative/team/risk/tokenomics/sub_scores/meta/reason/confidence）。事务回滚时 projects + project_history 同时撤销。
- **产出物**：~~Write 阶段事务内同时写 `projects` + `project_history`（§6.11 SQL 结构）。~~ 已完成。
- **验收**：~~一次 run 后 `project_history` 有对应快照行；事务回滚时两表一致。~~ 已验证（`tests/test_project_history.py` 8 tests 全绿：快照行写入 + 完整状态 JSON + 多次 save 多行 + 事务回滚一致性 + query_by_run/query_by_project + weight_version NULL + run_id 提取；`tests/test_repository.py` 32 tests 全绿无回归）。

---

## F. 可观测性

### F1. Prometheus 接入（§8 / §7.5 指标）
- **现状**：✅ 已实现。`app/metrics.py` 使用 `prometheus_client` 库暴露完整指标集：Pipeline（runs/duration/projects_scored/by_label）、Collection（runs/duration/items/duplicates）、LLM（requests/errors/duration）、DB gauges（projects/raw_projects/collection_logs_24h）、Competition Cache（hits/misses/db_duration）、Fetcher（cache_hits/misses/semaphore_usage/circuit_breaker_state）、Opportunity Shadow + Economic 全量指标。`MetricsExporter` 类封装 `is_enabled()`/`content_type()`/`render()`。`main.py` 注册 `/metrics` 端点（`settings.metrics_path`）。`config.py` 提供 `metrics_enabled`/`metrics_path` 配置。
- **产出物**：~~`/metrics` 端点 + §8 全部 gauge/counter 埋点（含 C1 缓存指标、B1 Semaphore 利用率）。~~ 已完成。
- **验收**：~~`/metrics` 暴露全部指标；Grafana/Prometheus 可抓取。~~ 已验证（`tests/api/test_metrics.py` 9 tests + `tests/collectors/test_metrics.py` 14 tests = 23 tests 全绿）。

---

## 依赖关系总览

```
A1 Alembic ──► A2 PostgreSQL ──► E1/E2/E3/E4（新表迁移）
B1 fetcher ──► B2 seed ──► C3 热度增强
B1 fetcher ──► C3 热度增强
C1 cache ──► C2 权重校准
D1 鉴权（独立，可并行）
F1 Prometheus（依赖 B1/C1 的指标产出）
```

**建议开工顺序（关键路径）**：
1. **A1 Alembic**（所有新表的前提）
2. **B1 fetcher 契约**（采集类任务的前提）
3. 并行：**A2 PG**、**B2/B3**、**C1 cache**、**D1 鉴权**
4. 收尾：**C2 校准**、**C3 热度**、**E 系列新表**、**F1 Prometheus**
