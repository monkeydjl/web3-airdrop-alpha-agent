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
- **现状**：❌ 当前 schema 由 `db.py` 启动时 `CREATE TABLE IF NOT EXISTS` 直建，无版本化迁移。Roadmap §5.3 明确「V2 引入 Alembic」。
- **产出物**：`backend/alembic.ini`、`backend/alembic/env.py`、`alembic/versions/` 首个 baseline 迁移（复刻现有 schema）。
- **验收**：`alembic upgrade head` 在空库可建出与现状一致的 schema；`alembic downgrade base` 可回滚；CI 加迁移冒烟步骤。

### A2. PostgreSQL 切换通道打通（ADR-004）
- **现状**：🟡 `db.py` 已抽象 `DbConnection`（sqlite/postgres 双 kind），但 V2 需真正跑通 PG 连接串 + 事务语义差异。依赖 A1。
- **产出物**：`docker-compose` 增加 postgres 服务；`db.py` 连接串走 env；`repository.py` 行锁替代 `threading.Lock`（§6.2.3）。
- **验收**：`DB_BACKEND=postgres pytest` 全绿；并发 re-score 行锁串行化验证通过。

---

## B. 采集与调度

### B1. fetcher 契约补全（§10.1）
- **现状**：🟡 `app/utils/fetcher.py` 已有 195 行（重试/缓存雏形）。需对齐 §10.1 完整契约：磁盘缓存目录、熔断、限流、`fetcher_semaphore_size` 并发闸。
- **产出物**：fetcher 统一入口（缓存命中/熔断降级/单源限流），`cache/` 磁盘缓存（gitignore），`Semaphore` 接入。
- **验收**：连续两次同 URL 请求第二次走缓存；熔断开启时不占 Semaphore 直接降级；`airdrop_concurrency_fetcher_semaphore_usage` 指标暴露。

### B2. seed 演示数据（降级兜底）
- **现状**：❌ 当前为手动输入方向，无 seed 模块；但 §10.2「Collector 全量失败回退 seed」依赖它。Roadmap §4 注记列为 V2 项。
- **产出物**：`backend/app/seed.py` + 种子数据集（含 token 线索，供 §6.5 token_risk 启发式）。
- **验收**：外部源全挂时 `POST /run` 仍写入 seed 项目且 `source='seed'`、`fetched_at` 为 NULL（§5 表注释）。

### B3. APScheduler 内嵌调度（ADR-005）
- **现状**：🟡 `app/collectors/scheduler.py` 已有 185 行（采集调度）；本项指 `POST /run` 的定时触发器（当前外部 cron/手动）。§11「前一次未完成则跳过」语义。
- **产出物**：`backend/app/scheduler.py`（注意与 collectors/scheduler.py 命名冲突，需归并或改名），含 skip-if-running 逻辑。
- **验收**：连续触发两周期，第二轮在前次未完时被跳过并记日志；无重叠 run。

---

## C. 评分决策引擎增强

### C1. 竞争度缓存（ADR-010，§7.5）
- **现状**：❌ 无 `app/cache.py`，评分时直接 `COUNT(*)`。§7.5 给了完整 LRU 实现样板。
- **产出物**：`backend/app/cache.py`（进程内 LRU + TTL 5min + 写时 invalidate），接入评分路径。
- **验收**：`airdrop_competition_cache_hits/misses_total` 指标可观测；re-score 前 `invalidate(sector)` 后读值精确；单测覆盖 LRU 淘汰与过期。

### C2. 权重校准流程（§7.9）
- **现状**：❌ 校准为 V2 引入、V3 闭环。依赖 C1（校准需重算 competition）。
- **产出物**：校准入口（读取 `weights_config` + 历史 outcomes），产出建议权重 diff 报告。
- **验收**：对 golden 回归集跑出权重建议；Σ=1.0 断言在建议权重上仍成立。

### C3. Twitter/VC 热度增强（§6.4）
- **现状**：❌ heat_score 当前静态。§6.4 V2 增强：实时爬讨论量/VC 公告/KOL 泛滥度。依赖 B1（fetcher）。
- **产出物**：heat agent 接入外部热度信号源。
- **验收**：`heat_score` 随外部信号动态变化，且降级路径（源失败）不阻塞 analyze 并行。

---

## D. 鉴权与多用户

### D1. API 鉴权（§9）
- **现状**：🟡 `app/auth.py` 仅 48 行（雏形），无 `middleware/`。V2 用匿名 token（§5.4.2 `user_id` 注释：V2 匿名 token，V3 接登录）。
- **产出物**：`app/middleware/auth.py`，匿名 token 签发/校验中间件，受保护端点清单。
- **验收**：无 token 访问受保护端点返回 401；合法匿名 token 放行且写入 `user_id`。

---

## E. 数据模型扩展（V2 新表，依赖 A1）

### E1. 反馈/治理/可观测表（§5.4.1–5.4.5）
- **现状**：❌ 未建表。MVP 阶段就需在 V2 前明确 schema（§5.4 引言）。
- **产出物**：`user_feedback`、`governance`、`metrics_snapshots`、`calibration`、`weights_config` 等表的 Alembic 迁移 + repository 方法。
- **验收**：迁移后表结构符合 §5.4 DDL；对应读写单测通过。

### E2. narratives 维表 + 索引（§5.4.6/5.4.7）
- **现状**：❌ 赛道元数据维表缺失（§3.1 已预留 `(V2) narratives 维表`）。
- **产出物**：`narratives` 表迁移 + §5.4.7 辅助索引。
- **验收**：赛道查询走索引（EXPLAIN 验证）；维表 JOIN 不破坏现有 projects 查询。

### E3. prompt_versions 表（§5.4.9）
- **现状**：❌ Prompt 版本管理缺失（V2 起）。
- **产出物**：`prompt_versions` 表 + LLM 调用处记录当前 prompt 版本。
- **验收**：每次 LLM 调用落 `prompt_version`；可按版本回溯输出。

### E4. project_history 写入（§6.9.12 / §6.11）
- **现状**：🟡 schema 注释提及 project_history（V2），Write 阶段当前只写 `projects`。
- **产出物**：Write 阶段事务内同时写 `projects` + `project_history`（§6.11 SQL 结构）。
- **验收**：一次 run 后 `project_history` 有对应快照行；事务回滚时两表一致。

---

## F. 可观测性

### F1. Prometheus 接入（§8 / §7.5 指标）
- **现状**：🟡 structlog + 简易 metrics 已有；V2 接 Prometheus。§8 列出 `airdrop_*` 指标全集。
- **产出物**：`/metrics` 端点 + §8 全部 gauge/counter 埋点（含 C1 缓存指标、B1 Semaphore 利用率）。
- **验收**：`/metrics` 暴露全部指标；Grafana/Prometheus 可抓取。

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
