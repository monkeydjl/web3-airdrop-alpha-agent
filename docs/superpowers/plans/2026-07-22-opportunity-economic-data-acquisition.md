# Opportunity Economic Data Acquisition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 复用现有 DefiLlama / CoinGecko / CryptoRank collector 已成功持久化的 `CollectorResult` / `RawDiscovery`，形成 **provider-native immutable snapshot → frozen `NormalizedObservation` → immutable `EvidenceRecord` → internal-only read-only economic proxy projection** 的可审计闭环。本计划不声称覆盖真实稀释、完整估值或空投奖励全量计算。

**Architecture:** Writer 仅在现有 collector **persist 成功之后**消费已落库结果（不二次 `collect`、不新建网络 client、不发起第二次 provider HTTP）；唯一新表 `opportunity_economic_snapshots` 为 append-only。Collector **Option A**：经济 `raw_data` 保留 provider `None`，legacy 过滤/signal strength/discovery score 用局部数值 fallback `0`；DefiLlama 强制 `change_7d_unit="ratio"`；`payload_json` 为 provider-native 白名单对象（省略 `None`、保留真实数值 `0`）。Identity **仅精确**双条件（`raw_projects(source_id, dedup_key)` 非空 `project_id` + `projects` 同 id 权威行），禁止 fuzzy；post-link replay 为纯本地、显式 `enabled` 门控，emit 前必须 `observation_from_snapshot`。Resolver 输出 **内部 only** 投影，**零** `OpportunityWorkflowProjection` / v1 workflow 响应字段；manual `run_id` 为 `manual:<uuid>`；三真门 helper 归属 Task 7；DDL/Evidence 冲突路径要求 dual-backend（SQLite+PG）测试；零新依赖 / migration / API。

**Tech Stack:** Python 3.11；FastAPI（现有 integration surface；**零新 API**）；Pydantic v2 frozen models；`sqlite3` / PostgreSQL via 现有 `DbConnection` / `init_db`；`prometheus_client`；`structlog`；`Decimal` / `json` / `hashlib`；`pytest`；Ruff；`compileall`；PowerShell / git；**无新依赖**。

## Global Constraints

1. 实现工作全部交给 Grok；严格按依赖与 commit 顺序执行。
2. Tasks 1–9：每 Task 完成后 **local commit 一次且 no push**；Task 10 **无 commit**。
3. 六个 feature flags **完整名字**，类型 `bool`，默认 `False`：
   - `opportunity_economic_snapshot_enabled`
   - `opportunity_economic_source_defillama_enabled`
   - `opportunity_economic_source_coingecko_enabled`
   - `opportunity_economic_source_cryptorank_enabled`
   - `opportunity_economic_evidence_emit_enabled`
   - `opportunity_economic_resolver_enabled`
4. **三真门**（global snapshot flag ∧ matching source flag ∧ existing provider enabled）**helper 归属 Task 7** 集成层；Task 1 只登记 flags 与灰度 validator，不实现三真合取；Writer 只消费调用方传入的 `enabled: bool`。
5. 灰度与 validator 强制链路：**snapshot → evidence → resolver**（上游关则下游不得伪开）。
6. **零新 API / route / response field**；零 `frontend` / `frontend-next`；**零 dependency 新增**；**零 Alembic / down migration**。
7. 不改 legacy `projects.score` / `label`、Opportunity decide、direct economics 门槛、confidence、calibration loader / report / schema、action workflow state / transition。
8. **唯一新表** `opportunity_economic_snapshots` 且 **append-only**；rollback 只关 flags、保留历史行。
9. Identity **仅精确匹配**：`raw_projects(source_id, dedup_key)` 精确非空 `project_id` 且 `projects` 同 id 权威行存在；禁止 symbol / name / slug fuzzy 及任何尝试 fuzzy 的代码分支。
10. 禁止第二次 provider HTTP、网络 client、collector 二次 collect；Writer **只消费已 persisted result**。
11. secret / API key / token / `Authorization` 不得进入 payload / log / hash / `source_url` / stdout；`source_url` 去除完整 query 与 fragment。
12. 绝不读取 `.env`、`.env.*`（除 `.env.example`）、pem / key / secrets 目录。
13. 不修改或不读取 `.workbuddy/memory/**`、`memory/**`、`.claude/**`。
14. 测试与 verifier 全 **network-free**；冻结 fixtures、fixed UTC clock、注入 UUID。
15. **Option A**：三 provider 经济 `raw_data` **保留 provider `None`**；legacy 过滤 / signal strength / discovery score 使用**局部数值变量 fallback `0`**（不得把 raw 缺失抹成 0）；真实数值 `0` 与 `None` 分离。
16. DefiLlama collector **必须始终**写入 `change_7d_unit` 字面量 `"ratio"`；normalizer **仅**接受精确 `"ratio"`；缺失 / `None` / 其他值 → 整行 schema-invalid，禁止猜测或自适应换算。
17. `payload_json` 为 **provider-native 白名单**对象：仅批准 raw 键；**省略 `None`**；**保留真实数值 0**；DefiLlama 含 `change_7d_unit`；**不是** normalized factor map。
18. manual `run_id` 冻结为 **`manual:<uuid>`**；daily 为既有稳定 UTC 日期命名空间；二者形态隔离、不可碰撞。
19. 经济代理投影 **内部 only**；**禁止**向 `OpportunityWorkflowProjection` 或 v1 workflow 响应体增加 `economic_proxy` / 任何经济字段（Task 8 仅边界回归测试，**零** production `workflow.py` / `workflow_service.py` 字段接线）。
20. post-link replay 接受显式 `enabled`（源自 `opportunity_economic_evidence_emit_enabled`）；`enabled=false` 整函数 no-op；emit 前必须经 `observation_from_snapshot` 重建。
21. Evidence insert-if-absent 的 insert / duplicate / content_conflict **必须**各有 **SQLite 与 PostgreSQL** 双后端显式测试；DDL 幂等同理 dual-backend。
22. `dedup_key` / `raw_id` **原样**传递；Observation/Evidence factor 缺失 **不补 0**。
23. hash / schema / `value_type` / provider whitelist 严格遵循冻结设计。
24. `docs/IMPLEMENTATION_STATUS.md` **仅**在 Task 9 verifier pytest 与 CLI 全绿后更新。
25. 失败 **局部隔离**，不删除已成功 snapshot。
26. 禁止越出 **Exact File Map** 所列路径。

---

## Dependency and Commit Order

| Order | Deliverable | Depends on | Local commit |
|------:|-------------|------------|--------------|
| 1 | flags + frozen models + canonical hash | none | `feat(opportunity): economic flags, frozen models, canonical hash` |
| 2 | dual-backend DDL + snapshot repository | 1 | `feat(opportunity): add dual-backend opportunity economic snapshots repository` |
| 3 | provider normalizers | 1 | `feat(opportunity): add provider economic normalizers` |
| 4 | metrics + non-networking writer | 1–3 | `feat(opportunity): add economic snapshot metrics and writer` |
| 5 | evidence insert-if-absent + dual identity + post-link replay | 1–4 | `feat(opportunity): economic evidence insert-if-absent, dual identity link, post-link replay` |
| 6 | time-series resolver + snapshot `source_id` batch lookup | 1, 2, 5 | `feat(opportunity): economic time-series resolver and snapshot source_id batch lookup` |
| 7 | scheduled / manual post-persist integration | 1–5 | `feat(opportunity): wire economic snapshots into persisted collection paths` |
| 8 | workflow-safe projection | 6, 7 | `feat(opportunity): add safe economic workflow projection` |
| 9 | network-free verifier + fixtures + status gate | 1–8 | `test(opportunity): add network-free economic verifier` |
| 10 | full verification | 1–9 | No commit — verification only; confirm clean worktree |

所有 commit 均为 **local / no push**；不得 squash 以绕过 dependency gates。

## Exact File Map

| Path | Action and owner | Responsibility |
|------|------------------|----------------|
| `backend/app/config.py` | Modify T1 | 仅六个 economic flags 与灰度/validator 约束 |
| `backend/app/opportunity/economic_models.py` | Create T1; Modify T6 | snapshot / factor / observation / hash 冻结模型；T6 追加 resolver DTO |
| `backend/app/db.py` | Modify T2 | SQLite/PG 唯一表 `opportunity_economic_snapshots` 与索引，additive idempotent DDL |
| `backend/app/opportunity/economic_repository.py` | Create T2; Modify T5, T6 | snapshot insert/get；identity/list；`source_id` batch lookup |
| `backend/app/opportunity/economic_normalizers.py` | Create T3 | provider whitelist / registry / sanitize / DefiLlama·CG·CR normalizers；`canonical_provider_payload` |
| `backend/app/collectors/defillama.py` | Modify T3 | 经济 `raw_data` 保留 provider `None`；局部 legacy 数值 fallback `0`；始终写入 `change_7d_unit="ratio"` |
| `backend/app/collectors/coingecko.py` | Modify T3 | 经济 `raw_data` 保留 provider `None`；局部 legacy 数值 fallback `0` |
| `backend/app/collectors/cryptorank.py` | Modify T3 | 经济 `raw_data` 保留 provider `None`；局部 legacy 数值 fallback `0` |
| `backend/app/metrics.py` | Modify T4 | 仅六个闭环 Prometheus metrics |
| `backend/app/opportunity/economic_writer.py` | Create T4 | 非联网 Writer：gate + normalize + append snapshot |
| `backend/app/opportunity/economic_evidence.py` | Create T5 | emitter / summary / post-link replay（`enabled` 显式门控） |
| `backend/app/opportunity/repository.py` | Modify T5 | 仅 economic Evidence insert-if-absent（SQLite+PG 双后端）；generic `add_evidence` 不变 |
| `backend/app/repository.py` | Modify T5 | `ProjectRepository(economic_replay_enabled=False)` 显式 bool；post-commit replay hook；不读 Settings |
| `backend/app/agents/orchestrator_simple.py` | Modify T7 | 唯一 pipeline 调用方接线：`ProjectRepository(economic_replay_enabled=settings.opportunity_economic_evidence_emit_enabled)`；repository 永不读 Settings |
| `backend/app/opportunity/economic_resolver.py` | Create T6 | 纯 resolver / read-only projection |
| `backend/app/opportunity/economic_integration.py` | Create T7 | 纯 gates / exact `daily_run_id`·`manual_run_id` / 已持久化结果集成入口 |
| `backend/app/main.py` | Modify T7 | scheduled：respects `create_app(db_override=None)` — `app_conn = db_override` when provided (borrowed, never closed by lifespan) else `get_connection()` (app-owned, closed exactly once at shutdown); same `app_conn` 注入 Collection/Economic/Opportunity repos + Writer + Emitter |
| `backend/app/routers/v1/collections.py` | Modify T7 | manual：request-scoped 单连接注入 Collection + 全部 economic repos/emitter；`finally` 仅关一次；无 API surface 变更 |
| `backend/app/opportunity/workflow.py` | No production modifications | Task 8 uses only boundary tests in `backend/tests/opportunity/test_workflow.py` and `backend/tests/api/test_opportunity.py` |
| `backend/app/opportunity/workflow_service.py` | No production modifications | Task 8 uses only boundary tests in `backend/tests/opportunity/test_workflow.py` and `backend/tests/api/test_opportunity.py` |
| `backend/scripts/verify_opportunity_economic.py` | Create T9 | network-free verifier CLI |
| `docs/IMPLEMENTATION_STATUS.md` | Modify T9 | 仅 verifier pytest + CLI 全绿后更新状态 |
| `backend/tests/opportunity/test_economic_models.py` | Create T1 | flags / frozen models / hash 单测 |
| `backend/tests/test_db_init.py` | Modify T2 | dual-backend DDL 幂等与索引断言 |
| `backend/tests/opportunity/test_economic_repository.py` | Create T2; Modify T5, T6 | snapshot 仓储；identity/list；batch lookup |
| `backend/tests/opportunity/test_economic_normalizers.py` | Create T3 | whitelist / sanitize / 三 provider normalizer；`canonical_provider_payload`；missing/non-ratio 整行 invalid |
| `backend/tests/collectors/test_defillama.py` | Modify T3 | None vs 0；`change_7d_unit`；legacy signal/score 不变 |
| `backend/tests/collectors/test_coingecko.py` | Modify T3 | None vs 0；legacy signal/score 不变 |
| `backend/tests/collectors/test_cryptorank.py` | Modify T3 | None vs 0；legacy signal/score 不变 |
| `backend/tests/opportunity/test_economic_writer.py` | Create T4 | gate / metrics / 无网络 writer |
| `backend/tests/opportunity/test_economic_evidence.py` | Create T5 | emit / dual identity / replay；`enabled=False` 返回 exactly `None` + 零 query/reconstruction/Evidence/metrics；per-row 隔离 |
| `backend/tests/opportunity/test_repository.py` | Modify T5 | economic insert/duplicate/content_conflict 双后端（SQLite+PG recording）；generic `add_evidence` 不变 |
| `backend/tests/test_repository.py` | Modify T5 | post-commit replay；`enabled=False` no-op；borrow/own conn close 语义 |
| `backend/tests/opportunity/test_economic_resolver.py` | Create T6 | 最新未过期 / independence_group / projection |
| `backend/tests/opportunity/test_economic_integration.py` | Create T7 | gates / exact run ids / persisted-result 集成；construction/process/emit 失败隔离 |
| `backend/tests/api/test_main_lifespan.py` | Modify T7 | scheduled post-persist + `db_override` borrowed-usable vs production-owned close-once + 构造失败隔离 |
| `backend/tests/api/test_collections.py` | Modify T7 | manual post-persist + request-scoped conn 单次 close + 构造失败隔离；无 API 形状变化 |
| `backend/tests/test_pipeline_run.py` | Modify T7 | pipeline：显式 `economic_replay_enabled` 接线 + offline post-link replay 回归 |
| `backend/tests/opportunity/test_workflow.py` | Modify T8 | workflow/API boundary regression: prove no economic fields on workflow projection / dump / service |
| `backend/tests/api/test_opportunity.py` | Modify T8 | v1 GET workflow response baseline + resolver-flag-on still zero economic fields; router `projection.model_dump` covered |
| `backend/tests/fixtures/opportunity_economic/defillama.json` | Create T9 | DefiLlama 冻结 fixture |
| `backend/tests/fixtures/opportunity_economic/coingecko.json` | Create T9 | CoinGecko 冻结 fixture |
| `backend/tests/fixtures/opportunity_economic/cryptorank.json` | Create T9 | CryptoRank 冻结 fixture |
| `backend/tests/scripts/test_verify_opportunity_economic.py` | Create T9 | verifier 脚本 network-free 测试 |
| Files: None — verification only | Task 10 | 全量验证；不改文件、不 commit；确认 clean worktree |

### Task 1: Flags、frozen models 与 canonical hash
**Files:**
- Modify **backend/app/config.py:171**
- Create **backend/app/opportunity/economic_models.py**
- Test **backend/tests/opportunity/test_economic_models.py**

**Interfaces:**
- `opportunity_economic_snapshot_enabled`、`opportunity_economic_source_defillama_enabled`、`opportunity_economic_source_coingecko_enabled`、`opportunity_economic_source_cryptorank_enabled`、`opportunity_economic_evidence_emit_enabled`、`opportunity_economic_resolver_enabled`：每个字段类型都是 bool、每个默认值都是 False
- Pydantic `model_validator` 强制 `evidence_emit`⇒`snapshot`、`resolver`⇒`evidence`
- Task 7 owns `economic_source_enabled`; Task 1 only defines six flags and upstream validator
- `SCHEMA_VERSION: Final[str] = "opportunity-economic-snapshot-v1"`
- `ValueType = Literal["bool", "number", "string", "json"]`（禁止 boolean/null）
- `EconomicSnapshotRow` Pydantic frozen 精确 10 字段：`snapshot_id`，`schema_version` 固定 Literal，`run_id`，`source_id`，`dedup_key`，`provider_entity_id`，`payload_sha256`，`payload_json`，`collected_at`，`source_url`
- `NormalizedFactor` Pydantic frozen 精确 11 字段：`factor_key`，`value`，`value_type`，`unit`，`source_type`，`source_grade: Literal["A","B","C","D","U"] = "C"`，`verification_status: Literal["verified","partially_verified","unverified","conflicted","invalidated"] = "verified"`，`independence_group`，`source_url`，`observed_at`，`expires_at`
- `NormalizedObservation` frozen 精确 7 字段：`snapshot_id`，`source_id`，`dedup_key`，`provider_entity_id`，`factors: tuple[NormalizedFactor, ...]`，`collected_at`，`source_url`；payload/value 深冻结；dedup 空白 invalid、合法原样；`provider_entity_id = raw_id`
- `canonical_json_bytes(value: Any) -> bytes`：递归 thaw / sort_keys / ensure_ascii=False / compact / noNaN / UTF-8
- `hash_string_array(parts: Sequence[str]) -> str`：array 拒非 str、固定顺序、SHA256 小写 64
- `payload_sha256(payload: Mapping[str, Any]) -> str`：hash the exact §4.3 provider-native canonical payload object (whitelist, omit None, preserve real zero, include Defi unit), not arbitrary payload/no-delete-fields
- `build_snapshot_id(*, run_id: str, source_id: str, provider_entity_id: str, payload_sha256_hex: str) -> str` 五项数组
- `build_evidence_id(*, snapshot_id: str, project_id: str, factor_key: str) -> str` 四项数组
- 不改 add_evidence / API / UI / legacy

- [ ] **1. 写失败测试**（2–5min）：settings 六默认 + 两非法灰度 + 合法全开（仅六 flags 与上游灰度/rollout validator；不含三 source 三真门真值表；`economic_source_enabled` deferred to Task 7）；Factor 样例 `tvl_usd` / value 字符串 `1.50000000` / `value_type` `string` / unit `usd` / `source_type` `public_aggregator` / C / verified / `defillama-protocols` 且逐字枚举闭集、深冻结；Row+Obs 完整字段 / schema 拒错 / dedup / raw_id / factors tuple 冻结；hash Unicode / MappingProxy / payload 变化 / 非 str / 小写 64 / 两个 ID 数组。必须覆盖上述 4 函数族断言。
- [ ] **2. 红跑**（2–5min）：`Set-Location backend; python -m pytest tests/opportunity/test_economic_models.py -q` → Expected **FAIL**
- [ ] **3. 最小实现**（2–5min）：config:171 六 flag + 两 validator；economic_models 冻结模型 + 深冻结 + 五函数 + SCHEMA_VERSION / ValueType 闭集，精确内容无占位。
- [ ] **4. 绿跑**（2–5min）：同命令 → Expected **PASS**
- [ ] **5. 回归**（2–5min）：`Set-Location backend; python -m pytest tests/opportunity -q` → Expected **PASS**
- [ ] **6. Commit**（2–5min）：`git add backend/app/config.py backend/app/opportunity/economic_models.py backend/tests/opportunity/test_economic_models.py`；`git commit -m "feat(opportunity): economic flags, frozen models, canonical hash"`

### Task 2: 双后端 DDL 与 snapshot repository

**Files:** `backend/app/db.py:220,461,716`；Create `backend/app/opportunity/economic_repository.py`；Modify `backend/tests/test_db_init.py`；Test `backend/tests/opportunity/test_economic_repository.py`

**Interfaces:**
- 唯一表 opportunity_economic_snapshots 十列：snapshot_id TEXT PRIMARY KEY；schema_version TEXT NOT NULL；run_id TEXT NOT NULL；source_id TEXT NOT NULL；dedup_key TEXT NOT NULL CHECK(length(trim(dedup_key))>0)；provider_entity_id TEXT NOT NULL；payload_sha256 TEXT NOT NULL；payload_json TEXT NOT NULL；source_url TEXT NOT NULL；collected_at SQLite TIMESTAMP NOT NULL / PG TIMESTAMPTZ NOT NULL
- CREATE INDEX IF NOT EXISTS idx_opportunity_economic_snapshots_run_source ON opportunity_economic_snapshots(run_id,source_id)；CREATE INDEX IF NOT EXISTS idx_opportunity_economic_snapshots_identity ON opportunity_economic_snapshots(source_id,dedup_key)；CREATE INDEX IF NOT EXISTS idx_opportunity_economic_snapshots_collected ON opportunity_economic_snapshots(collected_at DESC)
- `init_db(conn: Any = None) -> None`：仅接受 `None` / raw `sqlite3.Connection` / `DbConnection`；SQLite 路径不得作为参数。
- SQLite 测试硬写法：`raw = sqlite3.connect(':memory:')`；`raw.row_factory = sqlite3.Row`；`conn = DbConnection(raw, kind='sqlite')`；`init_db(conn)` 连续两次；绝不传路径。
- PG 硬写法：`events: list[tuple[Any, ...]] = []`；`connection = _RecordingPostgresConnection(events)`；`init_db(connection)`；`sqls = [event[1] for event in events if event[0] == 'execute']`；`events` 绝非 dict，无分支。
- 唯一模型：`app.opportunity.economic_models.EconomicSnapshotRow`。
- 接口: `class EconomicSnapshotContentConflict(RuntimeError)`，`EconomicSnapshotRepository.__init__(self,conn:Any=None)->None`，`close(self)->None`，`__enter__(self)->EconomicSnapshotRepository`，`__exit__(self,exc_type:Any,exc:Any,tb:Any)->None`，`get(self,snapshot_id:str)->EconomicSnapshotRow|None`，`insert_if_absent(self,snapshot:EconomicSnapshotRow)->tuple[EconomicSnapshotRow,bool]`
- **repository 行为**：主键冲突后比较 existing 与输入的冻结合同字段时 **忽略仅 `collected_at`**；其余字段（含 canonical `payload_json`）全部等价 → `(existing, False)`（返回已持久化不可变行；**原存 `collected_at` 保持权威**，零 UPDATE）；任一其它冻结字段不同 → rollback 并抛 `EconomicSnapshotContentConflict`。`collected_at` 单独漂移是重试元数据，不得记为 content conflict。
- **测试覆盖**：SQLite/PG parity 逐项断言十列、NOT NULL、dedup CHECK、三索引名及列完全一致；覆盖 duplicate 等价、同 ID 内容不同冲突、以及 **同 ID 仅 `collected_at` 漂移 → duplicate 且不覆盖原时间戳**（双后端）。


- [ ] **DDL 红测试**：在 `tests/test_db_init.py` 断言十列、`dedup_key` CHECK、三索引 `IF NOT EXISTS`、SQLite 双 `init_db(conn)` 幂等、PG `events` 为 `list[tuple]` 且 `sqls` 来自 `event[0]=='execute'`。PowerShell exact：`Set-Location backend; python -m pytest tests/test_db_init.py -q -k economic_snapshot`。Expected FAIL（缺表/列/索引或 `init_db` 未接 `DbConnection`）。
- [ ] DDL最小实现：CREATE TABLE IF NOT EXISTS opportunity_economic_snapshots + idx_opportunity_economic_snapshots_run_source / idx_opportunity_economic_snapshots_identity / idx_opportunity_economic_snapshots_collected — Expected PASS
- [ ] **repo 红测试**：新建 `tests/opportunity/test_economic_repository.py`，用 `build_snapshot_id`+`payload_sha256`+`SCHEMA_VERSION` 覆盖 get/insert 幂等、跨 run 两行、空白 dedup 拒绝、首尾空格原样、external conn close 后仍 execute。PowerShell exact：`Set-Location backend; python -m pytest tests/opportunity/test_economic_repository.py -q`。Expected FAIL。
- [ ] **repo 最小实现**，写冲突逐字段比较，并绿跑 exact Set-Location backend; python -m pytest tests/opportunity/test_economic_repository.py -q，Expected PASS
- [ ] **回归**：`Set-Location backend; python -m pytest tests/test_db_init.py tests/opportunity/test_economic_repository.py -q` Expected PASS。
- [ ] **独立 commit** `git add backend/app/db.py backend/app/opportunity/economic_repository.py backend/tests/test_db_init.py backend/tests/opportunity/test_economic_repository.py` `git commit -m "feat(opportunity): add dual-backend opportunity economic snapshots repository"`

### Task 3: Provider 专用 normalizers + Option A collectors

**Files:**
- Create `backend/app/opportunity/economic_normalizers.py`
- Test `backend/tests/opportunity/test_economic_normalizers.py`
- Modify `backend/app/collectors/defillama.py`
- Modify `backend/app/collectors/coingecko.py`
- Modify `backend/app/collectors/cryptorank.py`
- Modify `backend/tests/collectors/test_defillama.py`
- Modify `backend/tests/collectors/test_coingecko.py`
- Modify `backend/tests/collectors/test_cryptorank.py`

**Collector Option A（每个 collector 必须具体落实，禁止把 raw 缺失抹成 0）：**
- 三 provider 经济 `raw_data` **保留 provider `None`**（键可存在且值为 `None`，或键缺失；不得用 `0` 替换缺失）。
- 现有过滤 / signal strength / discovery score 逻辑改用**局部 legacy 数值变量**，对缺失做 fallback `0`；**真实数值 `0` 仍为 `0`**，与 `None` 分离。
- DefiLlama collector **必须始终**在经济 `raw_data` 写入 `change_7d_unit` 字面量 `"ratio"`（无论 `change_7d` 为数值、`0` 或 `None`）。
- 不得改变非经济字段形状；不得二次 HTTP；不得新建 client。

**Interfaces:** `from app.opportunity.economic_models import NormalizedFactor, NormalizedObservation`；不得定义其他 factor 模型。`EconomicNormalizationError(ValueError)`。`DEFILLAMA_CHANGE_7D_PROVIDER_UNIT: Final[Literal["ratio"]] = "ratio"`。`normalize_decimal_string(value: Any, *, nonnegative: bool) -> str`：`Decimal(str(value)).quantize(Decimal("0.00000001"), ROUND_HALF_EVEN)`，拒 bool/空/非有限，固定 8 位无科学计数。`normalize_ratio_string(value: Any, *, divisor: Decimal = Decimal("1")) -> str`。`normalize_market_rank(value: Any) -> int` 严格非负整数，拒 bool/负/小数。`normalize_chains_json(value: Any) -> tuple[str, ...]` 严格非空字符串数组、strip、拒空/重复、字典序。`normalize_strict_bool` 只接受 bool。

- 只读 registry：`PROVIDER_RAW_FIELD_KEYS: Mapping[str, frozenset[str]]`，外层用 `MappingProxyType`、内层用 `frozenset`；精确值为 `defillama={"tvl","change_7d","change_7d_unit","chains","no_token_yet"}`，`coingecko={"market_cap","current_price","total_volume","circulating_supply","market_cap_rank","price_change_percentage_24h"}`，`cryptorank={"market_cap","price","volume_24h","circulating_supply","total_supply","rank","percent_change_24h","percent_change_7d"}`。

- **`canonical_provider_payload(source_id: str, raw_data: Mapping[str, Any]) -> dict[str, Any]`**：
  - 仅输出 `PROVIDER_RAW_FIELD_KEYS[source_id]` 中**已出现且值非 `None`** 的 provider-native 键；
  - **保留真实数值 `0`**（`0` 不是 `None`，必须进入 payload）；
  - **省略 `None`** 与未批准键；
  - DefiLlama：**要求** payload 含精确 `change_7d_unit == "ratio"`（与 `DEFILLAMA_CHANGE_7D_PROVIDER_UNIT` 一致）；缺失 / `None` / 其他值 → 整行 schema-invalid（`EconomicNormalizationError`），禁止猜测或自适应换算；
  - 该函数返回对象是 **`payload_sha256` 的唯一输入**（Task 1 `payload_sha256` / Task 4 `payload_json` 必须与此对象一致，而不是任意 raw dump 或 factor map）。

- 核心接口：`sanitize_source_url(url:str)->str` 用 `urlsplit`/`urlunsplit`，拒非 `http(s)` 和 userinfo，删除整个 query/fragment；`normalize_provider_payload(*,source_id:str,raw_data:Mapping[str,Any],source_url:str,observed_at:datetime,expires_at:datetime)->tuple[NormalizedFactor,...]`，内部先经 `canonical_provider_payload`（或等价白名单裁剪）再做 **factor normalization mapping**，只用消毒 URL，按 `factor_key` 排序，缺失不补，invalid 整行抛错，结果供 `NormalizedObservation.factors`。
- metadata：11 字段/C/verified；usd 类 `unit=usd`，ratio 类 `unit=ratio`；`supply`/`market_rank`/`chains_json`/`token_unlisted_proxy` `unit=None`；DL `source_type` `public_aggregator`/`group` `defillama-protocols`；CG/CR `public_market_data`/`group` `market-aggregators`。
- DL 白名单完整一行（**含 unit 键**）：`tvl`→`tvl_usd` string unit usd；`change_7d`→`tvl_change_7d_ratio` string unit ratio divisor1；`change_7d_unit` 必须精确 `"ratio"`（进入 canonical payload，不映射为 factor）；`chains`→`chains_json` json；`no_token_yet`→`token_unlisted_proxy` bool。缺失 `change_7d_unit` / 非 `"ratio"` → **整行** schema-invalid。
- CG 白名单完整一行：`market_cap`/`current_price`/`total_volume`→`market_cap_usd`/`price_usd`/`volume_24h_usd` string unit usd；`circulating_supply`→`circulating_supply` string unit None；`market_cap_rank`→`market_rank` number；仅 `price_change_percentage_24h`/100→`price_change_24h_ratio` string unit ratio，绝不采用 `price_change_24h`。

- **CR 白名单**：`market_cap`→`market_cap_usd`、`price`→`price_usd`、`volume_24h`→`volume_24h_usd`、`circulating_supply`→`circulating_supply`、`total_supply`→`total_supply`（均为非负 string）；`rank`→`market_rank`（number）；`percent_change_24h`→`price_change_24h_ratio`（string，/100）；`percent_change_7d`→`price_change_7d_ratio`（string，/100）。

- **Normalizer 测试合同**：tuple `NormalizedFactor`/`Observation`、11 字段、类型/单位/metadata、三 provider **factor mapping** 保持不变、`ROUND_HALF_EVEN`、缺失不补、invalid/unknown；逐项断言 `PROVIDER_RAW_FIELD_KEYS` 只有三 source、每个 `frozenset` 与上述 raw 键完全相等（**DefiLlama 含 `change_7d_unit`**）且 registry 不可变；`canonical_provider_payload`：省略 `None`、保留真实 `0`、只含白名单键、输出即 `payload_sha256` 输入；DefiLlama `change_7d_unit` **缺失 / `None` / 非 `"ratio"`** → 整行 `EconomicNormalizationError`；`sanitize_source_url` 含 `api_key`/`token` query 与 fragment 的输入后这些内容不出现在 `Factor.source_url` 及任何下游 hash/log 输入。

- **Collector 测试合同（RED/GREEN）**：每个 provider 证明（1）provider 缺失 → 经济 `raw_data` 对应字段为 `None` 或键缺失，**不是** `0`；（2）provider 真实 `0` → `raw_data` 为 `0`；（3）局部 legacy 数值 fallback 后既有 filtering / signal strength / discovery score **与改前行为一致**；（4）DefiLlama 每条经济 `raw_data` 恒有 `change_7d_unit == "ratio"`。

- [ ] **Collector 红测试**：扩展 `tests/collectors/test_defillama.py` / `test_coingecko.py` / `test_cryptorank.py` 覆盖 None vs 0、legacy signal/score 不变、DL unit；PowerShell exact `Set-Location backend; python -m pytest tests/collectors/test_defillama.py tests/collectors/test_coingecko.py tests/collectors/test_cryptorank.py -v`；Expected FAIL（2–5min）
- [ ] **Collector 最小实现**：三 collector Option A（raw 保留 `None`；局部 legacy 变量 fallback `0`；DL 始终 `change_7d_unit="ratio"`）（2–5min）
- [ ] **Collector 绿跑**：同 collector 命令 Expected PASS（2–5min）
- [ ] **Normalizer 红测试**：写 `test_economic_normalizers.py` 覆盖上述断言与边界（含 `canonical_provider_payload`、missing/non-ratio 整行 invalid）；PowerShell exact `Set-Location backend; python -m pytest tests/opportunity/test_economic_normalizers.py -v`；Expected FAIL（2–5min）
- [ ] **Normalizer 最小实现**：`economic_normalizers.py` 含 registry、`canonical_provider_payload`、白名单 factor mapping、共享 normalize_*、整行失败语义、`factor_key` 排序返回 tuple（2–5min）
- [ ] **Normalizer 绿跑**：同 normalizer 命令 Expected PASS（2–5min）
- [ ] **回归**：`Set-Location backend; python -m pytest tests/opportunity/test_economic_models.py tests/opportunity/test_economic_normalizers.py tests/collectors/test_defillama.py tests/collectors/test_coingecko.py tests/collectors/test_cryptorank.py -v` — Expected PASS
- [ ] `git add backend/app/opportunity/economic_normalizers.py backend/tests/opportunity/test_economic_normalizers.py backend/app/collectors/defillama.py backend/app/collectors/coingecko.py backend/app/collectors/cryptorank.py backend/tests/collectors/test_defillama.py backend/tests/collectors/test_coingecko.py backend/tests/collectors/test_cryptorank.py`；`git commit -m "feat(opportunity): add provider economic normalizers"`

### Task 4: 精确 metrics 与 non-networking writer

**Files:**
- Modify `backend/app/metrics.py:89`
- Create `backend/app/opportunity/economic_writer.py`
- Test `backend/tests/opportunity/test_economic_writer.py`

**Goal:** 落地 opportunity-economic 的闭集 Prometheus metrics 与纯本地、非联网 `EconomicSnapshotWriter`：只消费已持久化 `CollectorResult.items`，append snapshot 并在 insert/duplicate 成功后构造内存 `NormalizedObservation`；不触网、不写 Evidence/Identity（留给 Task 5）；`enabled: bool` 由调用方传入，writer 不读 `Settings`。

---

#### Interfaces（逐字闭集）

| 维度 | 允许值 |
|------|--------|
| `source` | `defillama` \| `coingecko` \| `cryptorank` |
| snapshots `result` | `inserted` \| `duplicate` \| `schema_invalid` \| `skipped_flag_off` |
| observations `result` | `built` \| `skipped_no_snapshot` |
| evidence `result` | `emitted` \| `skipped_no_project` \| `duplicate` \| `skipped_flag_off` \| `content_conflict` |
| identity `result` | `linked` \| `unlinked` |

**六 metrics 全名与类型（无 `project` / `symbol` / `id` labels；禁止 `rejected_fuzzy_attempt`）：**

1. `opportunity_economic_snapshots_total` — **Counter** — labels: `source`, `result`
2. `opportunity_economic_observations_total` — **Counter** — labels: `source`, `result`
3. `opportunity_economic_evidence_total` — **Counter** — labels: `source`, `result`
4. `opportunity_economic_identity_resolution_total` — **Counter** — labels: `source`, `result`
5. `opportunity_economic_run_duration_seconds` — **Histogram** — labels: `source`
6. `opportunity_economic_last_success_unixtime` — **Gauge** — labels: `source`

- 非法 `source` / `result` 严格 `raise`。
- Task 4 writer 只调用 snapshots / observations / duration / last-success；evidence 与 identity 的 Counter 仅定义，调用归 Task 5。

**测试 metrics 辅助合同（精确签名；inspect Prometheus samples / label sets）：**

```python
def metric_sample_value(metric, **label_kwargs) -> float: ...
def metric_label_sets(metric) -> frozenset[frozenset[tuple[str, str]]]: ...
```

- `metric_sample_value`：从 Prometheus metric 的 **samples** 中按完整 label 匹配读取数值（Counter/Histogram/Gauge 均适用）；用于断言绝对值与 **delta**（`after - before`）。
- `metric_label_sets`：返回该 metric 已出现 sample 的 **闭集 label 集合**（每个 sample 的 label 键值对构成一个 `frozenset[tuple[str, str]]`，再整体装入外层 `frozenset`）。
- 测试 **必须** 用上述 helpers 断言 metric **值/增量** 与 **闭集 labels**；**明确禁止** 把裸 `Counter.labels(...)`（或仅 `.inc()` 调用存在性）当作有效验证——那只创建 child，不证明 sample 值或 label 闭集。

**writer 精确接口：**

- `def utc_now() -> datetime`：返回 UTC-aware `datetime`（`timezone.utc`）。
- `@dataclass(frozen=True) class EconomicWriteSummary` 精确字段如下：

```python
source_id: str
run_id: str
observations: tuple[NormalizedObservation, ...]
snapshots_inserted: int
snapshots_duplicate: int
schema_invalid: int
skipped_flag_off: int
```

- `EconomicSnapshotWriter(repository: EconomicSnapshotRepository, *, now_factory: Callable[[], datetime] = utc_now)`。
- `process(result: CollectorResult, *, run_id: str, enabled: bool) -> EconomicWriteSummary`。
- 禁止 `write` 方法；禁止以 `tuple` 直接返回摘要；禁止 writer 读取 `Settings`。
- `enabled` 由 Task 7 在计算 **总开关 + source 开关 + provider 开关** 三真后传入；writer 只消费 `enabled: bool`（`enabled=False` / `True` 合同不变）。
- 只处理 `result.items`；**非联网**（无 HTTP / 无 network client / 无 collector 二次 collect）；不调用 Evidence；不调用 identity。

**重建 helper（insert/duplicate 后内存 observation；Task 5 复用）：**

```python
def observation_from_snapshot(
    snapshot: EconomicSnapshotRow,
    *,
    normalizer=normalize_provider_payload,
) -> NormalizedObservation: ...
```

- **用途：** 从已落库 `EconomicSnapshotRow` 重建七字段 `NormalizedObservation`，供 writer 在 **repository 返回 inserted / duplicate 之后** 构造 in-memory observation，并被 **Task 5 post-link replay** 复用（同一 helper，禁止第二套重建逻辑）。
- **调用时机：** 仅在 snapshot insert/duplicate 成功路径调用；**`enabled=False` 时 `process` 永不调用** `observation_from_snapshot`（亦零 repo 写、`observations=()`）。
- **不 emit Evidence：** 本 helper 只返回 observation；失败隔离在单行，**不**触发 Evidence / identity metrics。
- **校验（任一失败 → 抛错 / 该行 schema-invalid 隔离，不污染其它行）：**
  1. `snapshot.schema_version` **精确等于** `SCHEMA_VERSION`（字面量 `opportunity-economic-snapshot-v1`）；否则 schema mismatch。
  2. `snapshot.payload_json` 必须可再经 **provider-native 白名单**（Task 3 `PROVIDER_RAW_FIELD_KEYS` / `canonical_provider_payload` 等价）重建；重建对象与存库 `payload_json` 在 canonical 序列化下 **hash 全等**（`payload_sha256` 与 `payload_json` 字节一致）；hash mismatch → 失败。
  3. DefiLlama：`change_7d_unit` 必须精确 `"ratio"`（`DEFILLAMA_CHANGE_7D_PROVIDER_UNIT`）；缺失 / `None` / 其他值 → invalid unit，整行失败。
  4. `source_url` 经 `sanitize_source_url`（去 query/fragment、拒非 http(s)/userinfo）；消毒结果用于 observation/factor；失败 → 该行隔离。
  5. 调用注入的 `normalizer`（默认 `normalize_provider_payload`）得到 `factors` tuple；组装 `NormalizedObservation`（`snapshot_id` / `source_id` / `dedup_key` / `provider_entity_id` / `factors` / `collected_at` / `source_url`）。
- **单行隔离：** 一行 reconstruction 失败只使该行 observation 不进入 `summary.observations`（writer 路径记 `schema_invalid` 或 observation `skipped_no_snapshot` 按下方 process 语义），**不** emit Evidence，**不**删除已成功 snapshot，继续下一行。

**`process` 语义（逐条硬约束）：**

1. **`enabled is False`：** 不调用 repository 任何写入；**不调用** `observation_from_snapshot`；`observations=()`；`skipped_flag_off=len(result.items)`；`snapshots_inserted=snapshots_duplicate=schema_invalid=0`；对每个 item 记 snapshot 侧 `skipped_flag_off` 与 observation 侧 `skipped_no_snapshot`（计数仅进 `skipped_flag_off`）。
2. **`enabled is True`：** 仅遍历 `result.items`（空列表合法：全计数 0、`observations=()`）。
3. **`collected_at`：** `result.finished_at if result.finished_at is not None else now_factory()`；若 naive 则规范为 UTC aware；若已 aware 则 `astimezone(timezone.utc)`。
4. **`expires_at`：** `collected_at + timedelta(hours=48)`。
5. **每行固定：** `dedup_key` / `raw_id` / `url` 来自 item 原样字段语义；`url` **去掉整个 query 与 fragment**（仅保留 scheme/netloc/path）；`sanitize` / normalizer / 预校验失败 → 仅该行 `schema_invalid += 1`，observation `skipped_no_snapshot`，**继续下一行**，不抛。
6. **repository 异常 / 内容冲突：** 仅走现有 logs / data_sources 局部失败路径 + 该行 observation `skipped_no_snapshot`；**不**记 snapshot `schema_invalid`；**不**改 `summary.schema_invalid`；**不**删除已成功写入的 snapshot；继续下一行。
7. **`dedup_key` / `raw_id`：** 原样传入 repository（不做二次改写）。
8. **`payload_json`：** 必须是 **provider-native** `RawDiscovery.raw_data` **白名单键** 的 canonical 对象（使用 Task 3 的只读 `PROVIDER_RAW_FIELD_KEYS[source_id]` 裁剪实际存在的 raw 键，并复用 `canonical_provider_payload` / normalizer 路径）；**绝不是** `factor_key → value` / `value_type` 结构；**无**完整 `raw_data` 全量 dump、**无** envelope、**无** URL、**无**凭据。
9. **`payload_sha256` / hash：** 与上述 canonical `payload_json` 对象字节一致（同一规范化序列化后再哈希）。
10. **repository 返回 inserted / duplicate 之后** 才调用 `observation_from_snapshot(snapshot)` 构造七字段 `NormalizedObservation`（仅内存，不写 Evidence）；成功则 observation result **一律 `built`**；`summary.snapshots_inserted` / `snapshots_duplicate` 与 repo 结果一一对应递增；若 reconstruction 失败（hash/schema/unit 等）→ 该行隔离、**不**把 observation 加入 summary、**不** emit Evidence，已 insert 的 snapshot 行保留。
11. **metrics：** `duration` 包裹整个 `process`；仅当本轮产生至少一条 observation 时记 `last-success`；writer **不**调用 evidence metrics / identity metrics。

**Tests 锁定（精确断言，无模糊）：**

- `EconomicWriteSummary` 字段名与类型精确：`source_id`, `run_id`, `observations`, `snapshots_inserted`, `snapshots_duplicate`, `schema_invalid`, `skipped_flag_off`。
- `process` signature 精确：`(self, result, *, run_id, enabled)` → `EconomicWriteSummary`；无 `write`。
- `now_factory` fallback：`finished_at is None` 时用注入时钟；返回 UTC aware。
- UTC 规范化：naive → UTC；aware 非 UTC → 转 UTC。
- `enabled=False`：repo 调用次数 0；**`observation_from_snapshot` 调用次数 0**；summary 计数与空 `observations` 如上。
- 只消费 `result.items`（不读其他 collector 字段做写入源）。
- `payload_json` 仅为 `PROVIDER_RAW_FIELD_KEYS[source_id]` 中实际存在的 provider-native keys；无额外键；hash 与该对象一致。
- 逐行隔离：单行 sanitize/normalizer 失败只增 `schema_invalid`，其它行仍可 inserted/duplicate。
- repo 异常 / 内容冲突：**不**增 `schema_invalid`；已写 snapshot 保留；该行 observation `skipped_no_snapshot`。
- insert / duplicate 后 observation result 均为 `built`（经 `observation_from_snapshot`）。
- **metrics helpers：** 用 `metric_sample_value` / `metric_label_sets` 断言 Counter/Histogram/Gauge 的 **值与 delta** 以及 **闭集 labels**；文档与测试注释必须写明：**bare `Counter.labels()` is invalid verification**（不得仅断言 labels child 存在）。
- **`observation_from_snapshot` RED/GREEN：** hash mismatch、schema_version mismatch、DefiLlama invalid `change_7d_unit`、以及 per-row isolation（坏行失败不 emit Evidence、不阻断好行 built）。
- 无网络；不触发 Evidence；不触发 identity metrics。

**TDD 执行清单：**

- [ ] **metrics 红：** 在 `test_economic_writer.py` 写 `test_economic_metric_contracts`（及 metrics helpers 合同）：六 metric 名/类型/label 闭集；`metric_sample_value(metric, **label_kwargs) -> float` 与 `metric_label_sets(metric) -> frozenset[...]` 可 inspect samples；断言值/delta 与闭集 labels；**显式声明 bare `Counter.labels()` 不是有效验证**。`Set-Location backend; python -m pytest tests/opportunity/test_economic_writer.py::test_economic_metric_contracts -v` — Expected **FAIL**。
- [ ] **metrics 实现：** `backend/app/metrics.py` 六 metric + 测试 helpers 路径绿。`Set-Location backend; python -m pytest tests/opportunity/test_economic_writer.py::test_economic_metric_contracts -v` — Expected **PASS**。
- [ ] **writer 红：** `test_writer_process_contract` + `observation_from_snapshot` 合同：`enabled` bool、非联网、insert/duplicate 后重建、`enabled=False` 永不调 reconstruction；hash mismatch / schema mismatch / invalid unit / per-row isolation 失败路径。`Set-Location backend; python -m pytest tests/opportunity/test_economic_writer.py::test_writer_process_contract -v` — Expected **FAIL**。
- [ ] **reconstruction 红：** 独立用例覆盖 `observation_from_snapshot`：`schema_version` 精确匹配失败、`payload_json` 白名单/hash 不等、DefiLlama non-ratio unit、`source_url` sanitize、单行失败不 emit Evidence。`Set-Location backend; python -m pytest tests/opportunity/test_economic_writer.py -k "observation_from_snapshot or reconstruction" -v` — Expected **FAIL**。
- [ ] **writer + reconstruction 实现：** `economic_writer.py` 含 non-networking `EconomicSnapshotWriter.process(..., enabled: bool)`、`observation_from_snapshot(...)`、insert/duplicate 后仅内存 built。`Set-Location backend; python -m pytest tests/opportunity/test_economic_writer.py -v` — Expected **PASS**。
- [ ] **四文件回归：** `Set-Location backend; python -m pytest tests/opportunity/test_economic_models.py tests/opportunity/test_economic_normalizers.py tests/opportunity/test_economic_repository.py tests/opportunity/test_economic_writer.py -v` — Expected **PASS**。
- [ ] **Commit：** `git add backend/app/metrics.py backend/app/opportunity/economic_writer.py backend/tests/opportunity/test_economic_writer.py; git commit -m "feat(opportunity): add economic snapshot metrics and writer"`。

### Task 5: Economic Evidence insert-if-absent、双条件 identity 与 post-link replay

#### Files
| 操作 | 路径 |
|------|------|
| Create | `backend/app/opportunity/economic_evidence.py` |
| Create | `backend/tests/opportunity/test_economic_evidence.py` |
| Modify | `backend/app/opportunity/repository.py` |
| Modify | `backend/tests/opportunity/test_repository.py` |
| Modify | `backend/app/opportunity/economic_repository.py` |
| Modify | `backend/tests/opportunity/test_economic_repository.py` |
| Modify | `backend/app/repository.py` |
| Modify | `backend/tests/test_repository.py` |

#### Interfaces（锁定签名与类型）
- `OpportunityRepository.add_economic_evidence_if_absent(self, evidence: EvidenceRecord) -> tuple[EvidenceRecord, bool]`：`True` 仅新插入；语义等价已有返回 `(existing, False)`；同 `evidence_id` 且 `model_dump(mode="json")` 不全等抛 `EconomicEvidenceContentConflict`（**永不覆盖**既有行）；不改 `add_evidence`。
- **双后端强制**：insert / duplicate / content_conflict（同 id 内容不等 → 抛冲突且行内容不变）必须在 **SQLite** 与 **PostgreSQL recording backend** 上各有显式测试；generic `add_evidence` 行为完全不变（含 duplicate → `sqlite3.IntegrityError` / 等价既有语义）。
- `EconomicSnapshotRepository.find_linked_project_id(source_id: str, dedup_key: str) -> str | None`：仅 `raw_projects(source_id, dedup_key)` 且 `project_id` 非空且 `projects.id` 存在。
- `EconomicSnapshotRepository.list_by_identity(source_id: str, dedup_key: str) -> tuple[EconomicSnapshotRow, ...]`。
- `EconomicEvidenceEmitter.__init__(conn: Any, snapshot_repository: EconomicSnapshotRepository, evidence_repository: OpportunityRepository)`。
- `EconomicEvidenceEmitter.emit(observation: NormalizedObservation, *, enabled: bool) -> EconomicEvidenceSummary`。
- **冻结 replay 签名（逐字）**：
  ```python
  def replay_economic_snapshots_for_project(
      project_id: str,
      *,
      conn: Any,
      enabled: bool,
  ) -> EconomicEvidenceSummary | None: ...
  ```
- **`enabled=False` 整函数立即 no-op**：立即返回 **exactly `None`**（不是零计数 summary；签名仍为 `EconomicEvidenceSummary | None`），且 **零 snapshot query**、**零 `observation_from_snapshot`**、**零 Evidence 读写**、**零 identity/evidence metric 副作用**（不 inc 任何 evidence/identity Counter sample）。
- **`enabled=True` replay 路径**：按 `project_id` SELECT raw identity → `list_by_identity` → 每行 `observation_from_snapshot` → insert-if-absent；**per-row reconstruction 失败 catch/isolate 并 continue**（坏行不阻断后续行）；无 HTTP；不改 snapshot / 既有 Evidence 内容。
- `EconomicEvidenceSummary` frozen：`emitted, duplicates, unlinked, conflicts, skipped_flag_off: int`。
- `EvidenceRecord`：`app.opportunity.models`，frozen，字段仅：`evidence_id, project_id, factor_key, value, value_type, observation_type, source_url, source_type, source_grade, observed_at, effective_at, expires_at, verification_status, independence_group, raw_snapshot_ref, supersedes_evidence_id`。
- 表列：`opportunity_evidence` 16 业务列 + `created_at`；`raw_projects` 列锁定；`projects` 主键 `id`；snapshot 表 `opportunity_economic_snapshots`；Task2 repo 用 `self._db`，`OpportunityRepository` 用 `self._conn`。
- Task 1 独占六个 economic flags；本任务 **不修改 Settings**；emitter 与 replay **只消费调用方传入的显式 `enabled: bool`**，**禁止**读 Settings。
- Task4：`observation_from_snapshot`（replay 必须复用，禁止第二套重建逻辑）。

#### `ProjectRepository` 显式 replay 门控（冻结）
- **精确构造**：`ProjectRepository.__init__(self, conn: Any = None, *, economic_replay_enabled: bool = False)`。
- 将显式 bool **存入** `self._economic_replay_enabled`（或等价私有字段）；**默认 `False`** 使每一个既有调用方在未传参时保持 post-commit **no-op** 行为。
- **`save` 签名保持不变**：`save(self, state: PipelineState) -> dict`（不得新增 `enabled` 参数）。
- **调用时机**：成功 **commit 之后**、**return 已提交 dict 之前**，以 **同一 borrowed/owned conn** 调用：
  ```python
  replay_economic_snapshots_for_project(
      project_id,
      conn=conn,  # 与 save 当前事务/连接同一 borrowed 或 owned conn
      enabled=self._economic_replay_enabled,
  )
  ```
- **外层 replay 失败**（任意未吞异常）：`logger.warning`（无 secret），**绝不 rollback 已提交 project**，仍返回已提交 dict。
- **连接关闭所有权不变**：仅当 `ProjectRepository` **拥有**该连接时在既有 `finally` 路径 close；borrowed conn **不得**被 replay 或 save 的新逻辑关闭。
- **禁止** `ProjectRepository` 读取 `Settings` / `get_settings` / 任何 flag 字段；生产侧由 **Task 7** 在 `backend/app/agents/orchestrator_simple.py` 构造：
  `ProjectRepository(economic_replay_enabled=settings.opportunity_economic_evidence_emit_enabled)`（本 Task 不改 orchestrator；Exact File Map T7 行已登记）。

#### 不变量（全任务）
- 专用路径复用 `add_evidence` 的 `value_json` 序列化与真实 16 字段 INSERT，`ON CONFLICT DO NOTHING`；命中后 SELECT 16 字段反序列化 `EvidenceRecord`，`model_dump(mode="json")` 全等则返回既有且不改行；**同 id 内容不等 → 抛 `EconomicEvidenceContentConflict`、rollback 当次写、永不覆盖**。
- `evidence_id = build_evidence_id` 完整 64hex；`raw_snapshot_ref = econ-snapshot:<snapshot_id>`。
- 12 factor 闭集与 `value_type`：`tvl_usd/tvl_change_7d_ratio/market_cap_usd/price_usd/volume_24h_usd/circulating_supply/total_supply/price_change_24h_ratio/price_change_7d_ratio`→`string`；`chains_json`→`json`；`token_unlisted_proxy`→`bool`；`market_rank`→`number`。
- 白名单：DL 仅前 4；CG 仅 market_cap/price/volume/circulating/rank/24h；CR 仅 market_cap/price/volume/circulating/total/rank/24h/7d。value 已 canonical，不重做 Decimal。
- Evidence：`source_grade=C`，`verification_status=verified`，`observation_type=observed`，`effective_at=collected`，`expires_at=collected+48h`；DL：source_type=public_aggregator，independence_group=defillama-protocols；CG/CR：source_type=public_market_data，independence_group=market-aggregators。
- identity 任一失败：保留 snapshot、`unlinked++`、零 Evidence；禁止 fuzzy。
- metrics：evidence 闭集 `emitted/skipped_no_project/duplicate/skipped_flag_off/content_conflict`；identity `linked/unlinked`。
- replay：仅 SELECT raw identity → `list_by_identity` → `observation_from_snapshot` → insert-if-absent；无 HTTP；不改 snapshot/既有 Evidence；per-row reconstruction 失败 isolate+continue；`enabled=False` 立即返回 exactly `None`（见上）。
- `ProjectRepository.save`：commit 后 return 前 `replay(..., enabled=self._economic_replay_enabled)`；外层异常 `logger.warning` 仍返回已提交 dict；close 仅既有 ownership finally。

---

### TDD 红阶段

- [ ] **1红 — economic Evidence insert / duplicate / content_conflict 双后端 + generic `add_evidence` 不变**
- **文件**：`backend/tests/opportunity/test_repository.py`
- **函数**（可拆分，但必须覆盖下列断言；命名可含 `sqlite` / `postgres` / `recording`）：
  - `test_add_economic_evidence_if_absent_insert_duplicate_conflict_sqlite`
  - `test_add_economic_evidence_if_absent_insert_duplicate_conflict_postgres_recording`（或等价 PG recording backend 用例）
  - 且至少一处断言 generic `add_evidence` 同 id duplicate 仍为既有 `IntegrityError`/失败语义、**未被** insert-if-absent 改写
- **必须断言（SQLite 与 PG recording 各一遍）**：
  1. **insert**：新 `evidence_id` → `(record, True)`，行存在
  2. **duplicate**：同 id 且 `model_dump(mode="json")` 全等 → `(existing, False)`，行内容不变
  3. **content_conflict**：同 id 且内容不全等 → 抛 `EconomicEvidenceContentConflict`，**既有行永不被覆盖**（读回与冲突前一致）
  4. **generic `add_evidence`**：行为与本任务前一致（含同 id 冲突/Integrity 路径）
- **命令**：
```powershell
cd backend; python -m pytest tests/opportunity/test_repository.py -k "add_economic_evidence_if_absent or add_evidence" -q
```
- **Expected FAIL**：`OpportunityRepository` 无 `add_economic_evidence_if_absent`；`EconomicEvidenceContentConflict` 未定义；双后端 insert/duplicate/conflict 与永不覆盖断言无法成立。

- [ ] **2红 — identity 四组合 + 同 symbol 但 dedup 不等零 link**
- **文件**：`backend/tests/opportunity/test_economic_repository.py`
- **函数**：`test_find_linked_project_id_dual_condition_and_list_by_identity`
- **命令**：
```powershell
cd backend; python -m pytest tests/opportunity/test_economic_repository.py::test_find_linked_project_id_dual_condition_and_list_by_identity -q
```
- **Expected FAIL**：`find_linked_project_id` / `list_by_identity` 不存在；四组合（raw 无/project 无、raw 有 project_id 空、project_id 非空但 `projects.id` 不存在、双条件满足）与“同 symbol 不同 dedup_key 返回 `None` 且 list 按 identity 隔离”无法通过。

- [ ] **3红 — emitter 12 factor / value_type / provider 白名单 / ref / id / flag / metrics + replay `enabled=False` 整函数 no-op**
- **文件**：`backend/tests/opportunity/test_economic_evidence.py`
- **函数**：
  - `test_economic_evidence_emitter_factors_whitelist_ref_id_flag_metrics`
  - `test_replay_economic_snapshots_for_project_enabled_false_is_immediate_noop`（或等价命名）
- **`enabled=False` 断言（必须）**：调用 `replay_economic_snapshots_for_project(project_id, conn=conn, enabled=False)` 后：
  - 返回值 **exactly `None`**（`assert result is None`；禁止接受零计数 summary 替代；签名仍为 `EconomicEvidenceSummary | None`）
  - 零 snapshot 相关 SELECT/query（mock/spy conn 或 repository）
  - 零 `observation_from_snapshot` 调用
  - 零 Evidence insert / 零 `add_economic_evidence_if_absent`
  - 零 identity/evidence metric sample 增量
- **另覆盖**：per-row reconstruction 失败 isolate+continue（好行仍可 emit；坏行不阻断）。
- **命令**：
```powershell
cd backend; python -m pytest tests/opportunity/test_economic_evidence.py -q
```
- **Expected FAIL**：`economic_evidence.py` 不存在；冻结 `enabled` 参数的 replay 签名未实现；emitter 合同与 no-op 断言失败。

- [ ] **4红 — post-link save replay：稳定 id、无 HTTP、外层失败不丢 project、`enabled=False` no-op、borrow/own conn close**
- **文件**：`backend/tests/test_repository.py`
- **函数**（可拆分）：
  - `test_project_save_replays_economic_snapshots_stable_id_no_http_on_error`
  - `test_project_save_replay_enabled_false_noop`（`ProjectRepository(conn, economic_replay_enabled=False)` 或默认；commit 后零 snapshot query / 零 Evidence / 零 metrics）
  - `test_project_save_replay_connection_borrow_and_own_close_semantics`：
    - **owned**：`ProjectRepository()` 无外部 conn 时，save 结束仍按既有 ownership 在 `finally` close
    - **borrowed**：外部传入 conn 时，save/replay **不** close 该 conn；结束后仍可 execute
- **命令**：
```powershell
cd backend; python -m pytest tests/test_repository.py -k "project_save_replay or economic_snapshots" -q
```
- **Expected FAIL**：`ProjectRepository.__init__` 无 `economic_replay_enabled`；`save` 未在 commit 后以 `enabled=self._economic_replay_enabled` 调冻结签名 replay；no-op / close 语义 / 稳定 id / 外层失败仍返回已提交 dict 无法成立。

---

### 绿阶段（按文件精确变更，无 SQL/代码）

- [ ] **G1 `backend/app/opportunity/repository.py` + 测**
- **改**：新增 `EconomicEvidenceContentConflict`；新增 `add_economic_evidence_if_absent`。
- **复用**：`add_evidence` 的 `value_json` 序列化与 16 字段 INSERT 形状；`ON CONFLICT DO NOTHING`。
- **读回**：冲突未插则 SELECT 16 字段 → `EvidenceRecord` → `model_dump(mode="json")` 全等则 `(existing, False)`；不全等抛冲突并 rollback；**永不 UPDATE/覆盖**。
- **保持**：`add_evidence` 签名与 duplicate→`IntegrityError`（或既有失败语义）**完全不变**。
- **双后端**：SQLite 真连 + PostgreSQL recording backend 各跑 insert / duplicate / content_conflict。
- **Expected PASS**：
```powershell
cd backend; python -m pytest tests/opportunity/test_repository.py -k "add_economic_evidence_if_absent or add_evidence" -q
```

- [ ] **G2 `backend/app/opportunity/economic_repository.py` + 测**
- **改**：`EconomicSnapshotRepository.find_linked_project_id`、`list_by_identity`；连接 `self._db`。
- **不变量**：仅 `(source_id, dedup_key)` 双等值；`project_id` 非空且 `projects.id` 存在才返回 id；禁止 symbol-only/fuzzy；`list_by_identity` 只返回该 identity 的 snapshot 元组。
- **断言 I/O**：四组合与“同 symbol 不同 dedup→`None`/空 list 或无交叉”；满足时返回精确 `project_id` 与对应 snapshot 元组。
- **Expected PASS**：
```powershell
cd backend; python -m pytest tests/opportunity/test_economic_repository.py::test_find_linked_project_id_dual_condition_and_list_by_identity -q
```

- [ ] **G3 `backend/app/opportunity/economic_evidence.py` + 测**
- **新建**：`EconomicEvidenceSummary`、`EconomicEvidenceEmitter`、`replay_economic_snapshots_for_project(project_id, *, conn, enabled)`（冻结签名）。
- **flag 边界**：本模块 **不** 读取或重定义 Settings；只执行 `emit(..., enabled=bool)` 与 `replay(..., enabled=bool)` 的显式参数。
- **emit 步骤语义**：`enabled=False`→`skipped_flag_off++`、零写；`find_linked_project_id` 失败→`unlinked++`、零 Evidence、snapshot 保留；成功则按 provider 白名单从 observation 抽闭集 factor，组 `EvidenceRecord`（C/verified/observed/effective=collected/expires+48h；DL/CG/CR 的 source_type 与 independence_group；`evidence_id=build_evidence_id` 64hex；`raw_snapshot_ref=econ-snapshot:<snapshot_id>`；`project_id` 已 link），调 `add_economic_evidence_if_absent`；`True`→`emitted++`，`False`→`duplicates++`，冲突→`conflicts++` 并计入 `content_conflict` metric；不重做 Decimal。
- **replay**：
  - `enabled=False` → **立即** 返回 exactly `None`（不是零计数 summary；零 snapshot query、零 `observation_from_snapshot`、零 Evidence、零 identity/evidence metrics）
  - `enabled=True` → SELECT raw identity → `list_by_identity` → 每行 `observation_from_snapshot` → insert-if-absent；**per-row reconstruction 失败 catch/isolate 并 continue**；无 HTTP；不改 snapshot/既有 Evidence
- **Expected PASS**：
```powershell
cd backend; python -m pytest tests/opportunity/test_economic_evidence.py -q
```

- [ ] **G4 `backend/app/repository.py` + 测**
- **改**：
  - `ProjectRepository.__init__(conn: Any = None, *, economic_replay_enabled: bool = False)` 存储 `self._economic_replay_enabled`
  - `save(state)` 签名不变；成功 commit 后、return 前：`replay_economic_snapshots_for_project(project_id, conn=conn, enabled=self._economic_replay_enabled)`（同一 borrowed/owned conn）
  - 外层 replay 异常 → `logger.warning`，**不** rollback 已提交 project，仍返回 dict
  - close **仅**既有 ownership `finally`；borrowed 不 close
  - **禁止**读 Settings
- **测试**：`sample_state` + `db_conn`；link 前零 Evidence；`economic_replay_enabled=True` 时 save 后稳定 `evidence_id`、无 HTTP；外层 replay 抛错 project 仍在；`economic_replay_enabled=False`（默认）整路径 no-op；borrow/own close 语义。
- **Expected PASS**：
```powershell
cd backend; python -m pytest tests/test_repository.py -k "project_save_replay or economic_snapshots" -q
```

- [ ] **回归**
```powershell
cd backend; python -m pytest tests/opportunity/test_repository.py tests/opportunity/test_economic_repository.py tests/opportunity/test_economic_evidence.py tests/test_repository.py -q
```

---

- [ ] **Commit（单一提交）**
```powershell
git add backend/app/opportunity/economic_evidence.py backend/tests/opportunity/test_economic_evidence.py backend/app/opportunity/repository.py backend/tests/opportunity/test_repository.py backend/app/opportunity/economic_repository.py backend/tests/opportunity/test_economic_repository.py backend/app/repository.py backend/tests/test_repository.py
git commit -m "feat(opportunity): economic evidence insert-if-absent, dual identity link, post-link replay"
```

**Commit 文件清单说明**：本 Task 仅上述 8 路径；`backend/app/agents/orchestrator_simple.py` 归 **Task 7**（Exact File Map T7 已登记生产 `ProjectRepository(economic_replay_enabled=settings.opportunity_economic_evidence_emit_enabled)`），**不得**进入本 commit。

### Task 6: Economic time-series resolver and snapshot source_id batch lookup

## Goal
Add a pure economic factor resolver that projects verified, in-window `EvidenceRecord`s into a deep-frozen `EconomicProxyProjection` over exactly 12 keys, plus a repository batch method to resolve `snapshot_id → source_id` for `econ-snapshot:` refs. No writes. No service/evidence/decision/calibration/workflow/API/frontend/settings changes.

#### Files

**Create**
- `backend/app/opportunity/economic_resolver.py`
- `backend/tests/opportunity/test_economic_resolver.py`

**Modify**
- `backend/app/opportunity/economic_repository.py`
- `backend/tests/opportunity/test_economic_repository.py`
- `backend/app/opportunity/economic_models.py` — only if the DTOs below are absent

**Forbidden**
- service, evidence, decision, calibration, workflow, API, frontend, settings
- generic `resolve_factor`
- writes to any repository
- `raw_snapshot_ref` on resolver output
- average / bias of conflicting values

## Interfaces

```python
EconomicSnapshotRepository.source_ids_by_snapshot_id(snapshot_ids: Collection[str]) -> dict[str, str]

EconomicResolver(snapshot_repository).resolve(project_id: str, records: Sequence[EvidenceRecord], *, now: datetime) -> EconomicProxyProjection

project_economics_data(project_id: str, *, evidence_repository: OpportunityRepository, snapshot_repository: EconomicSnapshotRepository, direct_available: bool, now: datetime, enabled: bool) -> EconomicProxyProjection | None
```

## DTOs (legal exact shapes)

```python
EconomicsDataMode = Literal["PROXY_ONLY", "DIRECT_AVAILABLE", "UNKNOWN"]

@dataclass(frozen=True)
class ResolvedEconomicFactor:
    factor_key: str
    value: Any | None
    value_type: Literal["bool", "number", "string", "json"]
    evidence_id: str | None
    conflicted: bool

@dataclass(frozen=True)
class EconomicProxyProjection:
    factors: Mapping[str, ResolvedEconomicFactor]
    economics_data_mode: EconomicsDataMode
```

- `factors` mapping and all nested JSON values must be deep-frozen.
- Exactly 12 keys always present in `factors` (see Keys).

## EvidenceRecord — exact fields (only these)

`evidence_id`, `project_id`, `factor_key`, `value`, `value_type`, `observation_type`, `source_url`, `source_type`, `source_grade`, `observed_at`, `effective_at`, `expires_at`, `verification_status`, `independence_group`, `raw_snapshot_ref`, `supersedes_evidence_id`

### Explicitly reject
`id`, `source_id`, `raw_value`, `confidence`, `notes`, `verified`, `invalid`, `collected_at`

## Exact 12 keys

1. `tvl_usd`
2. `tvl_change_7d_ratio`
3. `chains_json`
4. `token_unlisted_proxy`
5. `market_cap_usd`
6. `price_usd`
7. `volume_24h_usd`
8. `circulating_supply`
9. `total_supply`
10. `market_rank`
11. `price_change_24h_ratio`
12. `price_change_7d_ratio`

## Resolution rules

### Filter (per record)
- `project_id` matches
- `factor_key` is one of the 12 keys
- `verification_status == "verified"`
- `effective_at <= now`
- `expires_at is not None` and `expires_at > now` (equality with `now` is expired — exclude)
- Task 5 sets `expires_at` to collected time plus 48 hours; resolver uses explicit `expires_at` without inventing `collected_at`

### Snapshot refs
- Only nonempty `raw_snapshot_ref` values that use the `econ-snapshot:` prefix are considered for provider mapping
- One batch call: `source_ids_by_snapshot_id`
- Snapshot ids with no mapping entry are excluded from provider-dependent ranking
- Provider identity comes only from that mapping (never from evidence fields)
- Exact lowercase provider mapping only

### Tie priority (after latest `effective_at` within factor / independence group)
- DefiLlama-class keys (`tvl_usd`, `tvl_change_7d_ratio`, `chains_json`, `token_unlisted_proxy`): prefer `defillama`
- Market-class keys (`market_cap_usd`, `price_usd`, `volume_24h_usd`, `circulating_supply`, `total_supply`, `market_rank`, `price_change_24h_ratio`, `price_change_7d_ratio`): prefer `coingecko`, then `cryptorank`
- Same provider: lexical order of snapshot id (stable)

### Independence groups
- CoinGecko and CryptoRank share one market-aggregators independence group for conflict detection among market sources
- Same-group yesterday/today values are time series and not conflict

### Value agreement (no average / no bias)
- Money / supply numeric: agree iff `abs(a - b) <= max(Decimal("1e-8"), Decimal("1e-8") * max(abs(a), abs(b)))`
- Ratio numeric: agree iff `abs(a - b) <= Decimal("1e-8")`
- JSON / bool / int: exact equality

### Factor outcomes
| Case | value | evidence_id | conflicted |
|------|-------|-------------|------------|
| Absence | `None` | `None` | `false` |
| Conflict (disagreement after grouping) | `None` | `None` | `true` |
| Resolved | typed value | stable winning `evidence_id` | `false` |

- Never emit `raw_snapshot_ref` on output factors
- No generic `resolve_factor` API

### `project_economics_data`
- `enabled is false` → return `None`; zero repository calls
- `enabled is true` → load evidence once for `project_id`, then resolve
- Mode:
  - `DIRECT_AVAILABLE` iff `direct_available` is true
  - else `PROXY_ONLY` iff at least one usable resolved factor (`value is not None` and `conflicted is false`)
  - else `UNKNOWN`
- No writes

### `source_ids_by_snapshot_id`
- Input: collection of snapshot ids
- Empty input returns an empty dict with zero query
- Nonempty ids use `self._db` for exactly one batch SELECT from `opportunity_economic_snapshots` mapping `snapshot_id` to `source_id`
- Unknown ids omitted
- Output: `dict[str, str]` mapping present ids only (missing ids omitted)
- Batch lookup only; pure read

## TDD checklist

- [ ] **Repository RED**

  `python -m pytest backend/tests/opportunity/test_economic_repository.py -k "source_ids_by_snapshot_id" -q`

  Expected FAIL

  Empty input returns an empty dict with zero query; nonempty ids use `self._db` for exactly one batch SELECT from `opportunity_economic_snapshots` mapping `snapshot_id` to `source_id`; unknown ids omitted

- [ ] Implement `source_ids_by_snapshot_id`

- [ ] **Repository GREEN**

  `python -m pytest backend/tests/opportunity/test_economic_repository.py -k "source_ids_by_snapshot_id" -q`

  Expected PASS

  Empty input returns an empty dict with zero query; nonempty ids use `self._db` for exactly one batch SELECT from `opportunity_economic_snapshots` mapping `snapshot_id` to `source_id`; unknown ids omitted

- [ ] **Resolver RED**

  `python -m pytest backend/tests/opportunity/test_economic_resolver.py -q`

  Expected FAIL

- [ ] Implement DTOs (if absent), `EconomicResolver.resolve`, `project_economics_data`

- [ ] **Resolver GREEN**

  `python -m pytest backend/tests/opportunity/test_economic_resolver.py -q`

  Expected PASS

- [ ] **Regression**

  `python -m pytest backend/tests/opportunity/test_economic_repository.py backend/tests/opportunity/test_economic_resolver.py -q`

  Expected PASS

  `python -m pytest backend/tests/opportunity -k "service or decision" -q`

  Expected PASS

- [ ] **Commit (no push)**

  ```powershell
  git add backend/app/opportunity/economic_resolver.py backend/tests/opportunity/test_economic_resolver.py backend/app/opportunity/economic_repository.py backend/tests/opportunity/test_economic_repository.py
  # only if DTOs were added/changed:
  git add backend/app/opportunity/economic_models.py
  git commit -m "feat(opportunity): economic time-series resolver and snapshot source_id batch lookup"
  ```

## PowerShell gates (exact)

```powershell
# Repository RED
python -m pytest backend/tests/opportunity/test_economic_repository.py -k "source_ids_by_snapshot_id" -q
# Expected FAIL

# Repository GREEN
python -m pytest backend/tests/opportunity/test_economic_repository.py -k "source_ids_by_snapshot_id" -q
# Expected PASS

# Resolver RED
python -m pytest backend/tests/opportunity/test_economic_resolver.py -q
# Expected FAIL

# Resolver GREEN
python -m pytest backend/tests/opportunity/test_economic_resolver.py -q
# Expected PASS

# Regression
python -m pytest backend/tests/opportunity/test_economic_repository.py backend/tests/opportunity/test_economic_resolver.py -q
# Expected PASS

python -m pytest backend/tests/opportunity -k "service or decision" -q
# Expected PASS
```

## One commit
Message: `feat(opportunity): economic time-series resolver and snapshot source_id batch lookup`

Files: four required paths always staged; `economic_models.py` only when DTOs were added; no push.
### Task 7: Scheduled/manual integration and end-to-end post-link replay verification

Wire economic snapshot writing into the already-persisted collection paths (scheduled `on_collection` and manual `trigger_collection`) using a pure, non-networking integration layer; wire the sole pipeline caller so post-link replay receives an explicit `economic_replay_enabled` bool; freeze connection ownership so scheduled lifespan respects existing `create_app(db_override=None)` (`app_conn = db_override` when provided/borrowed, else `get_connection()` app-owned and closed once) and manual request-scoped paths still close exactly once. No new routes, endpoints, response fields, schedulers, jobs, tables, frontend, provider clients, external requests, dependencies, collect calls, or configuration fields.

#### Files

**Create**
- `backend/app/opportunity/economic_integration.py`
- `backend/tests/opportunity/test_economic_integration.py`

**Modify**
- `backend/app/main.py`
- `backend/app/routers/v1/collections.py`
- `backend/app/agents/orchestrator_simple.py`
- `backend/tests/api/test_main_lifespan.py`
- `backend/tests/api/test_collections.py`
- `backend/tests/test_pipeline_run.py`

**Do not modify**
- `backend/app/config.py` and all config tests (Task 1 owns all six flags and rollout validation)
- `backend/app/repository.py` (Task 5 owns `ProjectRepository` implementation: `__init__(..., economic_replay_enabled: bool = False)`, post-commit `replay_economic_snapshots_for_project`, borrow/own close semantics; **repository never reads Settings**)
- Any other pipeline production module besides `backend/app/agents/orchestrator_simple.py` — **`orchestrator_simple.py` is the only pipeline caller wiring change** in Task 7: pass `ProjectRepository(economic_replay_enabled=settings.opportunity_economic_evidence_emit_enabled)`; do not reimplement replay or edit `ProjectRepository.save`

#### Interfaces

**Locked existing writer (do not redefine)**
- `EconomicSnapshotWriter(repository, *, now_factory=...).process(result, *, run_id, enabled) -> EconomicWriteSummary`
- `EconomicWriteSummary.observations` is the frozen, deterministic sequence of `NormalizedObservation` values built from successfully persisted snapshots.

**Locked Task 5 emitter (consume, do not redefine)**
- `EconomicEvidenceEmitter(conn, snapshot_repository, evidence_repository)`
- `EconomicEvidenceEmitter.emit(observation: NormalizedObservation, *, enabled: bool) -> EconomicEvidenceSummary`

**Locked Task 5 `ProjectRepository` (consume at pipeline caller only; do not redefine)**
- `ProjectRepository(conn: Any = None, *, economic_replay_enabled: bool = False)` stores the explicit bool; **never** reads `Settings` / `get_settings` / flag fields.
- Task 7 production wiring in `orchestrator_simple.py` only:
  `ProjectRepository(economic_replay_enabled=settings.opportunity_economic_evidence_emit_enabled)`
  (or equivalent with the same explicit keyword and the same settings field).

**Constants and pure helpers in `economic_integration.py`**
- `ECONOMIC_SOURCES = frozenset({'defillama', 'coingecko', 'cryptorank'})`
- **Scheduled `daily_run_id` exact form:** `daily_run_id(source_id: str, finished_at: datetime) -> str`

  Returns **exactly** `daily:<UTC_DATE>:<source_id>` where `<UTC_DATE>` is the UTC calendar date of `finished_at` in `YYYY-MM-DD` (e.g. `daily:2026-07-22:defillama`). Same UTC date + source → stable id; different UTC date → different id.
- **Manual `manual_run_id` exact form:** `manual_run_id(*, uuid_factory: Callable[[], UUID] = uuid.uuid4) -> str`

  Returns **exactly** `manual:<uuid>` (e.g. `manual:550e8400-e29b-41d4-a716-446655440000`); inject `uuid_factory` for deterministic tests. Default factory calls are unique. Daily and manual forms are isolated namespaces (no collision).
- `economic_source_enabled(source_id: str, settings_obj: Settings) -> bool`

  True only for the exact triple conjunction of the matching source:
  - `defillama`: `opportunity_economic_snapshot_enabled` and `opportunity_economic_source_defillama_enabled` and `defillama_enabled`
  - `coingecko`: `opportunity_economic_snapshot_enabled` and `opportunity_economic_source_coingecko_enabled` and `coingecko_enabled`
  - `cryptorank`: `opportunity_economic_snapshot_enabled` and `opportunity_economic_source_cryptorank_enabled` and `cryptorank_enabled`

  Unsupported `source_id` is false. Conjunction only; do not reimplement Task 1 `model_validator` or define `validate_economic_rollout`.
- `process_persisted_collection(result: CollectorResult, *, run_id: str, writer: EconomicSnapshotWriter, emitter: EconomicEvidenceEmitter, settings_obj: Settings) -> EconomicWriteSummary | None`

  Synchronous, non-networking:
  - unsupported source or false triple gate → return `None`, zero writer and emitter calls
  - enabled source → `summary = writer.process(result, run_id=run_id, enabled=True)` exactly once; writer exception logs bounded (credential-free), returns `None`, and makes zero emitter calls
  - if the writer returns no summary, return `None` with zero emitter calls
  - for each observation in deterministic `summary.observations`, call the same injected emitter exactly once as `emitter.emit(observation, enabled=settings_obj.opportunity_economic_evidence_emit_enabled)`; never construct an emitter inside the loop
  - **evidence flag false still writes snapshot then emits `enabled=False`:** when the triple gate is true, writer still runs with `enabled=True` (snapshots persist); then every observation is still passed to `emit(..., enabled=False)` so Task 5 records `skipped_flag_off` and writes zero Evidence
  - isolate/log an emitter exception per observation, retain the snapshot and writer summary, and continue remaining observations; return `summary`
  - never collect, never re-persist, never HTTP

#### Connection ownership (frozen)

**Scheduled lifespan (`main.py`) — respects existing `create_app(db_override=None)`**
- `app_conn = db_override` when `db_override` is provided (**borrowed**; lifespan **never** closes it); else `app_conn = get_connection()` (**app-owned**; lifespan closes **exactly once** on shutdown).
- Pass that same `app_conn` into: `CollectionRepository`, `EconomicSnapshotRepository`, `OpportunityRepository`, `EconomicSnapshotWriter` (via its repository), and `EconomicEvidenceEmitter`.
- Borrowed repositories / writer / emitter **never** `close` / `dispose` / context-exit `app_conn`.
- Construct shared snapshot repository, writer, opportunity repository, and emitter **once** for the app lifetime; reuse the emitter for every observation (never construct per item).

**Manual trigger (`collections.py::trigger_collection`)**
- Obtain **one request-scoped connection**.
- Pass that same connection into `CollectionRepository` and **all** economic repositories / writer / emitter used for this request.
- Close the connection **exactly once** in a `finally` block; **no double close** (borrowed economic objects must not close it).
- One request-scoped emitter (not per observation).

**Tests**
- Injected `db_override` remains usable after lifespan exit; production-owned (`get_connection()`) connection closes exactly once at shutdown.
- Private test connections close only in their owner scope (fixture/test that opened them); production borrow paths under test must leave the owner connection usable after the call returns.

#### Path contracts

**Scheduled path (`main.py`)**
- Existing async `on_collection(source_id, result)`:
  1. `CollectionRepository.persist_collection_result` first
  2. only after persist succeeds: `process_persisted_collection` exactly once with `run_id=daily_run_id(result.source_id, result.finished_at)` (**exact** `daily:<UTC_DATE>:<source_id>`), the injected writer, and the injected emitter
  3. then optional `execute_analysis_pipeline` as today
- Persist failure → zero writer and emitter calls.
- `CollectionScheduler` still runs `collector.collect` **exactly once**.
- Persist **exactly once**.
- Economic construction / process / emit failures are provider-local: bounded log only; **cannot** rollback successful persist, suppress optional auto-analysis, affect other scheduled sources, or leak connections.

**Manual path (`collections.py::trigger_collection`)**
- Keep `collector.collect` **exactly once** and persist **exactly once**.
- Only after persist succeeds: construct/inject one request-scoped economic stack on the request connection (never one emitter per observation), then call `process_persisted_collection` with `run_id=manual_run_id(...)` (**exact** `manual:<uuid>`), writer, and emitter before optional `execute_analysis_pipeline`.
- Persist failure → zero writer and emitter calls.
- Economic construction / process / emit failures → HTTP status and `CollectionTriggerResponse.model_dump` **byte-identical** to baseline; do not suppress optional auto-analysis; do not leak the request connection (still closed exactly once in `finally`).

**Pipeline path (`orchestrator_simple.py` + `test_pipeline_run.py`)**
- Sole production change for pipeline: construct `ProjectRepository(economic_replay_enabled=settings.opportunity_economic_evidence_emit_enabled)` so post-link replay after `save` commit receives the explicit bool; **repository itself never reads Settings**.
- Task 5 already owns replay implementation; Task 7 only wires the caller.
- Tests in `test_pipeline_run.py`: after authoritative project save, evidence comes from existing snapshots without HTTP/provider collect; flag-off serialized pipeline dict equals frozen baseline; explicit `economic_replay_enabled` wiring is asserted (not Settings reads inside the repository).

**Baseline / gate constraints**
- All six flags false → byte-identical scheduled/manual/pipeline baseline outputs and zero writer/emitter calls.
- Source-gate tests cover all three flags per provider and unsupported sources.
- Daily ID: same UTC date stable; cross-date changes; exact form `daily:<UTC_DATE>:<source_id>`.
- Manual ID: deterministic injected UUID; unique default calls; exact form `manual:<uuid>`.
- Integration proves writer receives the already-persisted `CollectorResult`; order is collect once → persist once → writer once → each `summary.observations` item through the same emitter → optional analysis; no second external/network request.
- With snapshot enabled and evidence disabled: **snapshot still writes**, then emitter receives `enabled=False` for every observation and Task 5 records `skipped_flag_off`.
- With snapshot and evidence enabled, an already exactly-linked authoritative project receives immediate Evidence from scheduled/manual collection without waiting for another `ProjectRepository.save`; an unlinked observation retains its snapshot and emits zero Evidence.
- Illegal rollout order remains Task 1 validator only; Task 7 consumes a valid `Settings` instance.

#### Constructor / process / emit failure isolation (required tests)

For **each** economic provider (`defillama`, `coingecko`, `cryptorank`) and for **each** run path (scheduled daily + manual), tests must prove that failures during economic **construction** (repository/writer/emitter setup), **process** (`writer.process` / `process_persisted_collection`), or **emit** (`emitter.emit`) are:
- bounded-logged (credential-free; no secret / token / full Authorization)
- unable to **rollback** a successful `persist_collection_result`
- unable to change HTTP status or `CollectionTriggerResponse.model_dump` bytes (manual path)
- unable to suppress optional analysis
- unable to affect other sources (scheduled path)
- unable to leak connections (production-owned closed once on shutdown; injected `db_override` never closed by lifespan and remains usable after; request-scoped still closed once in `finally`; private test conns closed only in owner scope)

Collect remains **exactly once**; persist remains **exactly once**.

#### Implementation steps (TDD)

- [ ] **RED — unit integration helpers and pure gates**

  Add failing tests in `backend/tests/opportunity/test_economic_integration.py` for:
  - `ECONOMIC_SOURCES` membership
  - `daily_run_id` same-UTC-date stability, cross-date change, **exact** form `daily:<UTC_DATE>:<source_id>`
  - `manual_run_id` with injected UUID → **exact** form `manual:<uuid>`; default factory uniqueness
  - `economic_source_enabled` exact triple conjunctions: defillama requires `opportunity_economic_snapshot_enabled` plus `opportunity_economic_source_defillama_enabled` plus `defillama_enabled`; coingecko requires `opportunity_economic_snapshot_enabled` plus `opportunity_economic_source_coingecko_enabled` plus `coingecko_enabled`; cryptorank requires `opportunity_economic_snapshot_enabled` plus `opportunity_economic_source_cryptorank_enabled` plus `cryptorank_enabled`; unsupported source false
  - `process_persisted_collection`: gate false / unsupported → `None` and zero writer/emitter calls; gate true → writer once with supplied result, exact `run_id`, `enabled=True`, followed by the same emitter once per ordered `summary.observations`
  - evidence flag true/false passes exact emitter `enabled` bool; **false still writes snapshots then `emit(..., enabled=False)`**, zero Evidence, Task 5 `skipped_flag_off`; writer failure gives zero emitter calls
  - emitter failure preserves snapshot/returned summary and continues later observations; emitter object is reused rather than constructed per item
  - real integration fixture: existing exact raw identity plus authoritative project receives immediate Evidence; unlinked identity retains snapshot with zero Evidence
  - prove no collect/persist/HTTP inside integration
  - construction/process/emit failure isolation unit contracts where applicable (bounded log; no rollback of prior success; continue/isolate)

- [ ] **RED — scheduled lifespan, connection ownership, and `on_collection` order**

  Extend `backend/tests/api/test_main_lifespan.py` (and related collection tests) so they fail until:
  - lifespan respects `create_app(db_override=None)`: `app_conn = db_override` when provided (borrowed, never closed by lifespan) else `get_connection()` (app-owned, closed exactly once at shutdown); pass same `app_conn` to `CollectionRepository`, `EconomicSnapshotRepository`, `OpportunityRepository`, Writer, Emitter; borrowed objects never close it
  - tests prove injected `db_override` remains usable after lifespan; production-owned connection closes once at shutdown
  - lifespan injects shared snapshot repository/writer/evidence repository/emitter once
  - persist success → one `process_persisted_collection` with exact `daily_run_id` form, writer, and reused emitter; its observations emit before optional analysis
  - persist failure → zero writer/emitter calls
  - flags all false → baseline-identical callback completion and zero writer/emitter calls
  - **per provider**: construction / process / emit failures bounded-log, cannot rollback successful persist, cannot suppress optional auto-analysis, cannot affect other sources, cannot leak `app_conn` (owned closes once; borrowed `db_override` never closed by lifespan); collect once and persist once still hold

- [ ] **RED — manual trigger order, request-scoped connection, and response identity**

  Extend `backend/tests/api/test_collections.py` so they fail until:
  - one request-scoped connection passed to `CollectionRepository` and all economic repositories/emitter; closed **exactly once** in `finally`; no double close
  - collect once, persist once, then integration once with exact `manual_run_id` form, one request-scoped emitter, and writer observations emitted before optional analysis
  - persist failure → zero writer/emitter calls
  - **per provider**: construction / process / emit failures → HTTP status and `CollectionTriggerResponse.model_dump` byte-identical to baseline; do not suppress optional auto-analysis; no connection leak
  - flags all false → baseline-identical manual response and zero writer/emitter calls
  - no second network/provider collect

- [ ] **RED — pipeline post-link offline replay + explicit settings wiring**

  In `backend/tests/test_pipeline_run.py` (and production `orchestrator_simple.py` under GREEN):
  - assert production constructs `ProjectRepository(economic_replay_enabled=settings.opportunity_economic_evidence_emit_enabled)` (explicit bool from Settings at the **caller** only)
  - `ProjectRepository` / `repository.py` **never** reads Settings (Task 5 ownership; no Task 7 edits to repository implementation)
  - after authoritative project save, evidence comes from existing snapshots without HTTP/provider collect
  - flag-off serialized pipeline dict equals frozen baseline
  - private test connections close only in their owner scope

  Offline-replay baseline assertions may already pass in RED because Task 5 is implemented; the **required** RED failure is missing orchestrator wiring / integration surface until GREEN.

- [ ] **RED verification command (must fail)**

  From repository root:

```powershell
python -m pytest backend/tests/opportunity/test_economic_integration.py backend/tests/api/test_main_lifespan.py backend/tests/api/test_collections.py backend/tests/test_pipeline_run.py -q
```

  **Expected FAIL:** missing `economic_integration` module/symbols; scheduled/manual paths do not pass Task 4 observations through the reused Task 5 emitter; connection ownership, constructor-failure isolation, immediate linked Evidence, evidence-off-still-writes-snapshot-then-`enabled=False`, exact run-id forms, or gate assertions fail; pipeline caller does not yet pass explicit `economic_replay_enabled=settings.opportunity_economic_evidence_emit_enabled`. Task 5 offline-replay baseline assertions may already pass and are not the sole required RED failure cause.

- [ ] **GREEN — implement pure integration layer**

  Create `backend/app/opportunity/economic_integration.py` with the exact interfaces above (including exact `daily_run_id` / `manual_run_id` forms). Consume valid `Settings` only; do not redefine rollout validation. Keep `process_persisted_collection` synchronous and non-networking: writer once (`enabled=True` when gated on), then ordered `summary.observations` through the same emitter with the exact evidence-enabled bool (**false → still snapshot write path then `emit(..., enabled=False)`**); isolate writer/emitter failures with bounded credential-free logs and retain successful snapshots.

- [ ] **GREEN — wire scheduled path + freeze connection ownership via `create_app(db_override=None)`**

  In `backend/app/main.py` lifespan: `app_conn = db_override` when provided (borrowed, never closed by lifespan) else `app_conn = get_connection()` (app-owned, closed exactly once at shutdown); pass the same `app_conn` to `CollectionRepository`, `EconomicSnapshotRepository`, `OpportunityRepository`, `EconomicSnapshotWriter`, and `EconomicEvidenceEmitter`; borrowed objects never close it. In `on_collection`: after successful persist only, call `process_persisted_collection(..., run_id=daily_run_id(result.source_id, result.finished_at), writer=..., emitter=..., settings_obj=settings)`, then existing optional pipeline. Preserve `collector.collect` exactly once and persist exactly once. Isolate construction/process/emit failures per provider as specified.

- [ ] **GREEN — wire manual path + freeze request-scoped connection**

  In `backend/app/routers/v1/collections.py::trigger_collection`: obtain one request-scoped connection; pass it to `CollectionRepository` and all economic repositories/emitter; after successful persist only, call `process_persisted_collection(..., run_id=manual_run_id(), writer=..., emitter=..., settings_obj=settings)` before the existing optional pipeline; close the connection **exactly once** in `finally` (no double close). Preserve collect once and persist once. Construction/process/emit failure must not alter HTTP status or response dump bytes.

- [ ] **GREEN — wire pipeline caller only**

  In `backend/app/agents/orchestrator_simple.py`: pass `ProjectRepository(economic_replay_enabled=settings.opportunity_economic_evidence_emit_enabled)`. Do not edit `backend/app/repository.py`. Do not reimplement replay.

- [ ] **GREEN verification command (must pass)**

  From repository root:

```powershell
python -m pytest backend/tests/opportunity/test_economic_integration.py backend/tests/api/test_main_lifespan.py backend/tests/api/test_collections.py backend/tests/test_pipeline_run.py -q
```

  **Expected PASS:** all new/updated assertions green; run IDs exact (`daily:<UTC_DATE>:<source_id>`, `manual:<uuid>`); gates conjunction-correct; collect once / persist once / writer once / same-emitter-per-observation order proven; evidence flag false still writes snapshot then `emit(enabled=False)`; linked projects receive immediate Evidence; connection ownership (`create_app(db_override=None)`: injected `db_override` remains usable after lifespan; production-owned closes once at shutdown; request-scoped once in `finally`; no double close; test owner-scope closes); per-provider construction/process/emit isolation; pipeline explicit `economic_replay_enabled` wiring; offline post-link and flag-off baseline hold.

- [ ] **Regression (must pass)**

  From repository root:

```powershell
python -m pytest backend/tests/opportunity/test_economic_integration.py backend/tests/api/test_main_lifespan.py backend/tests/api/test_collections.py backend/tests/test_pipeline_run.py -q
python -m pytest backend/tests/opportunity/ backend/tests/api/test_collections.py backend/tests/api/test_main_lifespan.py -q
```

  **Expected PASS:** focused Task 7 suites plus existing collection/lifespan/pipeline coverage remain green; all-flags-false paths stay byte-identical to baseline; zero unintended writer/emitter calls when gated off; Task 4 observations reach Task 5 emission; post-link offline replay remains intact; no connection leaks.

- [ ] **Commit (one local commit, no push)**

  Stage only the exact Task 7 file list:

```powershell
git add backend/app/opportunity/economic_integration.py backend/tests/opportunity/test_economic_integration.py backend/app/main.py backend/app/routers/v1/collections.py backend/app/agents/orchestrator_simple.py backend/tests/api/test_main_lifespan.py backend/tests/api/test_collections.py backend/tests/test_pipeline_run.py
git commit -m "feat(opportunity): wire economic snapshots into persisted collection paths"
```

  Do not push. Exact commit subject must remain `feat(opportunity): wire economic snapshots into persisted collection paths`. Exact file list is the eight paths above (Create two + Modify six, including `orchestrator_simple.py` and `test_pipeline_run.py`).
### Task 8: Workflow/API boundary protection (no production wiring)

**Goal.** Task 8 is **boundary regression protection only**. Prove that the existing workflow model, serializer, service, and v1 GET workflow API remain free of economic surface: no `economic_proxy`, no `economics_data_mode`, and no new economic fields on `OpportunityWorkflowProjection` or the HTTP response body — for **all economic flags false** and also when **`opportunity_economic_resolver_enabled` is true**. Task 6 `EconomicProxyProjection` / `project_economics_data` stay **service-private / offline**; this task does **not** wire them into workflow or the API.

**Hard boundary (must not violate):**
- **Do not modify** any production file, including:
  - `backend/app/opportunity/workflow.py`
  - `backend/app/opportunity/workflow_service.py`
  - any router production module (e.g. opportunity v1 router)
  - any other app production module
- **Do not** add `economic_proxy` / `economics_data_mode` / economic section types to `OpportunityWorkflowProjection`
- **Do not** change `build_workflow_projection` signature or output
- **Do not** call or expose Task 6 resolver / `project_economics_data` / `EconomicProxyProjection` from workflow service or API
- Internal economic resolver remains Task 6 only; no workflow wiring in this task

#### Files (only these two; Modify tests only)

| Action | Path |
|--------|------|
| Modify | `backend/tests/opportunity/test_workflow.py` |
| Modify | `backend/tests/api/test_opportunity.py` |

**Forbidden:** create/modify `workflow.py`, `workflow_service.py`, routers, settings, resolver, repositories, or any other production path.

#### Interfaces under test (read-only; do not change production)

- `OpportunityWorkflowProjection` — existing frozen workflow DTO; must **not** gain `economic_proxy`, `economics_data_mode`, or any new economic field
- `build_workflow_projection(...)` — existing keyword-only signature and return type **unchanged**
- `OpportunityWorkflowService.get_project_workflow` (or equivalent path that returns the workflow projection) — must not call economic resolver / `project_economics_data` and must not attach economic fields on the projection
- v1 GET workflow router path — response body must stay baseline-identical under all-flags-false and must **not** gain economic keys when `opportunity_economic_resolver_enabled` is true
- Router serializes via `projection.model_dump` (or equivalent existing dump); tests must cover that **direct** dump path, not only service-layer dumps

**Baseline identity definition** (use for key-set and body equality):

```python
json.dumps(projection.model_dump(mode='json'), sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
```

and/or exact HTTP response JSON key set / body equality against a captured pre-Task-8 baseline (all six economic flags default false).

#### Required proof surface (TDD must cover all layers)

Tests must prove **across model / serializer / service / router** (behavioral assertions are primary; static scan is supplemental only):

1. **Model:** `OpportunityWorkflowProjection` has **no** field named `economic_proxy`, `economics_data_mode`, or any newly introduced economic field (introspect model fields / annotations).
2. **Serializer:** `model_dump(mode='json')` (and Python mode if used) key set is **baseline-identical** — no new economic keys at any nesting level under the contract under test.
3. **`build_workflow_projection`:** signature (inspect / call with existing kwargs only) and output shape are **unchanged**; dump key set matches baseline.
4. **Service:** `OpportunityWorkflowService` response projection path does **not call** and does **not expose** economic resolver / `project_economics_data` / `EconomicProxyProjection` (monkeypatch spies record **zero** calls under flag-off and under `opportunity_economic_resolver_enabled=True`).
5. **API — all economic flags false:** v1 GET workflow response body is **exact baseline** (status + JSON body / canonical dump bytes as defined above).
6. **API — resolver flag true:** with `opportunity_economic_resolver_enabled=True` (other economic flags may remain false or as needed for a valid Settings instance), v1 GET workflow response body still does **not** gain `economic_proxy`, `economics_data_mode`, or other economic fields; remains free of new economic surface relative to baseline key set.
7. **`raw_snapshot_ref`:** remains **absent** from the full workflow dump and from the v1 GET workflow response body (must not appear as a new top-level or nested key introduced by economic wiring; existing evidence item contracts stay as today).
8. **Router direct dump:** cover the router path that returns `projection.model_dump(...)` (or the project’s existing dump call) so API serialization is proven end-to-end, not only unit-level service dumps.
9. **Static router diff / token scan** (optional supplemental): may scan router / workflow modules for forbidden tokens (`economic_proxy`, `project_economics_data`, `EconomicProxyProjection`, `economics_data_mode`) as **extra** defense — **not** the sole proof; behavioral tests above are required.

#### TDD steps

- [ ] **RED — write failing boundary tests first** (tests only; no production implementation)

  In `backend/tests/opportunity/test_workflow.py` cover at least:
  - Model field set: no `economic_proxy` / `economics_data_mode` / new economic fields on `OpportunityWorkflowProjection`
  - `model_dump(mode='json')` key set baseline-identical
  - `build_workflow_projection` signature and output unchanged vs baseline
  - Service path: monkeypatched economic resolver / `project_economics_data` → **zero** calls when building workflow; returned projection dump has no economic keys
  - Full workflow dump: `raw_snapshot_ref` absent under the boundary contract (does not appear as economic leakage on the projection)

  In `backend/tests/api/test_opportunity.py` cover at least:
  - v1 GET workflow: all six economic flags false → response body **exact baseline**
  - v1 GET workflow: `opportunity_economic_resolver_enabled=True` → response still has **no** `economic_proxy` / `economics_data_mode` / new economic fields (key set does not grow economic surface)
  - Router uses / returns `projection.model_dump` path: assert dumped body keys match baseline contract
  - `raw_snapshot_ref` absent from response body under the same boundary assertions
  - Optional: static token scan of router/workflow production sources as **supplemental only**

  Until the boundary suite is fully written and wired into the two test modules, RED may fail on missing assertions/imports; once tests exist against current production (which already must not wire economics), the intended long-term state is green **without** production changes. If RED is used to introduce new strict assertions that temporarily fail due to incomplete test helpers only, fix **tests only** — never production code.

- [ ] **RED command** (from repository root; Expected FAIL until boundary tests exist / helpers assert correctly):

```powershell
python -m pytest backend/tests/opportunity/test_workflow.py backend/tests/api/test_opportunity.py -q --tb=short
```

  Expected FAIL (missing/incomplete boundary tests or failing new assertions in test modules only).

- [ ] **GREEN — boundary test implementation only (no production implementation)**

  Complete and stabilize tests solely in:
  - `backend/tests/opportunity/test_workflow.py`
  - `backend/tests/api/test_opportunity.py`

  Do **not** edit `workflow.py`, `workflow_service.py`, routers, or any production file. GREEN means the boundary suite passes against **unchanged** production code that correctly omits economic workflow surface.

- [ ] **GREEN command** (from repository root; Expected PASS):

```powershell
python -m pytest backend/tests/opportunity/test_workflow.py backend/tests/api/test_opportunity.py -q --tb=short
```

  Expected PASS

- [ ] **Regression commands** (from repository root; Expected PASS):

```powershell
python -m pytest backend/tests/opportunity/test_workflow.py backend/tests/api/test_opportunity.py backend/tests/opportunity/test_service.py backend/tests/opportunity/test_decision.py backend/tests/opportunity/test_calibration_loader.py backend/tests/test_pipeline_run.py -q --tb=short
```

  Expected PASS

- [ ] **One local commit** (stages **exactly** the two Task 8 test files; no production files; no push):

```powershell
git add backend/tests/opportunity/test_workflow.py backend/tests/api/test_opportunity.py
git commit -m "feat(opportunity): add safe economic workflow projection"
```

  Exact commit subject must remain `feat(opportunity): add safe economic workflow projection`. Exact staged paths: the two test files only.

### Task 9: Network-free Opportunity economic verifier（验收 Tasks 1–8）

**Goal:** 新增 network-free 的 economic 闭环验收脚本与冻结 fixture，通过 **26** 个稳定 case id（设计规格 §17.1 全矩阵 `17.1.01`–`17.1.26`）验收既有 Tasks 1–8 生产接口的正确性；在 verifier 测试与 CLI 全绿后，再更新 `docs/IMPLEMENTATION_STATUS.md`。不实现/修复 Task 8 workflow，不修改 production workflow 模块，不复制 production normalizer/resolver/workflow 算法，不改 app 生产模块，不 push。

**Files:**
- Create: `backend/scripts/verify_opportunity_economic.py`
- Create: `backend/tests/fixtures/opportunity_economic/defillama.json`
- Create: `backend/tests/fixtures/opportunity_economic/coingecko.json`
- Create: `backend/tests/fixtures/opportunity_economic/cryptorank.json`
- Create: `backend/tests/scripts/test_verify_opportunity_economic.py`
- Modify: `docs/IMPLEMENTATION_STATUS.md`（仅当 verifier 测试与 CLI 全绿后，在「3. 后端模块」表新增下述精确状态行）

**Interfaces:**
- `backend/scripts/verify_opportunity_economic.py`
  - `CASE_IDS: tuple[str, ...]`：值**精确**为下列 26 项，顺序与内容冻结，不多不少、不可重排、不可改写：
    ```python
    CASE_IDS: tuple[str, ...] = (
        "17.1.01", "17.1.02", "17.1.03", "17.1.04", "17.1.05", "17.1.06",
        "17.1.07", "17.1.08", "17.1.09", "17.1.10", "17.1.11", "17.1.12",
        "17.1.13", "17.1.14", "17.1.15", "17.1.16", "17.1.17", "17.1.18",
        "17.1.19", "17.1.20", "17.1.21", "17.1.22", "17.1.23", "17.1.24",
        "17.1.25", "17.1.26",
    )
    ```
  - `run_verification() -> dict[str, bool]`
    - 返回键必须精确覆盖且仅覆盖 `CASE_IDS` 中的 26 个稳定 case id（键排序输出时按字典序）
    - 每个值为该 case 是否通过（`True`/`False`）
  - `main(argv: list[str] | None = None) -> int`
    - 仅当 `run_verification()` 的键集精确等于 `CASE_IDS` 且全部值为 `True` 时返回 `0`；缺键、多键、任一 `False` 或异常均返回非 `0`
    - 成功时向 stdout 打印排序后的结果键值，末行精确为 `RESULT: PASS`；状态行必须体现 **26/26**（例如 `passed=26 failed=0 total=26` 或等价可机读形式）
    - 失败时末行精确为 `RESULT: FAIL`；状态行反映实际 `passed`/`failed`/`total=26`；合同异常或任一 mismatch 返回非 `0`；失败仅打印 bounded exception type，不泄露 fixture 路径细节、payload 全文、credential canary 或真实环境 secret
- 测试模块：`backend/tests/scripts/test_verify_opportunity_economic.py`
  - 覆盖 CLI exit code、case 完整性（精确 26 键 = `CASE_IDS`）、hash/fixture mismatch、异常路径、AST import denylist、socket connect 失败哨兵、§17.1 **二十六项**矩阵与 §17.2 参数化断言
- 惯例对齐（只读参考，不修改）：`backend/scripts/verify_opportunity_calibration.py`、`backend/scripts/verify_opportunity_shadow.py`、`backend/tests/scripts/test_verify_*.py`

**Network-free 硬约束（verifier 与测试必须同时满足）:**
- 只重放冻结 `raw_data` fixture，不读真实环境数据库，不发 HTTP
- 使用临时 SQLite 与/或事务，并在 case 结束时清理
- 不导入、不实例化 `requests` / `httpx` / `aiohttp` / `urllib.request` / `socket` client
- 不导入 collectors 中会发请求的采集入口；只调用既有 Tasks 1–8 的生产接口（Writer、schema、hash framing、resolver、mode、flag 门控、metrics helper、observation_from_snapshot、集成层连接所有权路径等）完成 replay 与断言
- 测试必须用 AST import denylist 扫描 `verify_opportunity_economic.py` 与被其直接导入的测试辅助路径，禁止网络客户端模块
- 测试必须注册 socket connect 失败哨兵：若发生出站 connect 尝试则 case 失败
- Task 9 **只验收**既有 Tasks 1–8 生产接口；禁止在 verifier 内复制 production normalizer/resolver/workflow 算法；禁止实现或修复 Task 8 workflow；禁止修改 production workflow 或任何 app 生产模块

**冻结 fixture 合同:**
- `backend/tests/fixtures/opportunity_economic/defillama.json`
  - 明确 DefiLlama `change_7d` 的 **provider unit 合同**（fixture 内标注/承载 unit 元数据，使 case `17.1.14` 可区分「匹配 → ratio」与「不匹配 → schema_invalid」）
  - 含 `None` 与真实数值 `0` 对照样本，供 case `17.1.19` / `17.1.20` 证明 raw 保留 `None`、legacy 局部 fallback `0`、payload 省略 `None` 且保留真实 `0`
  - 含 `change_7d_unit` 字面量 `"ratio"` 路径，供 `17.1.14` / `17.1.20`
  - 含额外未知键与 credential canary（例如 query/body 风格的 `api_key`/`token` 诱饵字段），用于证明 provider-native whitelist 剥离
- `backend/tests/fixtures/opportunity_economic/coingecko.json`
  - 同时包含百分比字段 `price_change_percentage_24h` 与绝对美元字段 `price_change_24h`，供 case `17.1.12` 证明仅百分比路径生效
  - 含 `None` 与真实 `0` 对照样本（`17.1.19` / `17.1.20`）
  - 含未知键与 credential canary
- `backend/tests/fixtures/opportunity_economic/cryptorank.json`
  - 含 `percent_change_24h` 与 `percent_change_7d`，供 case `17.1.13` 证明两个百分点 raw 值均除以 `100`
  - 含 `None` 与真实 `0` 对照样本（`17.1.19` / `17.1.20`）
  - 含未知键与 credential canary
- 最终 verifier stdout / 测试断言输出 **不得** 打印 canary 明文

**§17.1 聚合测试矩阵（26 项，每项必须有独立 case id 与测试引用，禁止「覆盖上述」式省略）:**

| Case id | 验收点 | 测试引用（`test_verify_opportunity_economic.py`） |
|---|---|---|
| `17.1.01` | 跨 UTC 日、同 payload 产生不同 `snapshot_id`，写入两行历史 | `test_case_17_1_01_cross_utc_day_same_payload_two_history_rows` 或参数化 `case_id="17.1.01"` |
| `17.1.02` | 同 run 重复 Writer：行数不增，且 duplicate metric 递增/记录 | `test_case_17_1_02_same_run_duplicate_writer_no_row_growth` 或参数化 `case_id="17.1.02"` |
| `17.1.03` | post-link replay：先仅有 `raw_projects` 映射且 `project_id` 非空但无 `projects` 权威行 → 零 Evidence；补权威 `projects` 后稳定 `evidence_id` | `test_case_17_1_03_post_link_replay_zero_then_stable_evidence` 或参数化 `case_id="17.1.03"` |
| `17.1.04` | symbol 相同或仅 raw project id、仍无权威 `projects` → unlinked 零 Evidence；静态证明无 fuzzy 分支 | `test_case_17_1_04_unlinked_no_fuzzy_branch` 或参数化 `case_id="17.1.04"`（含 AST/源码静态断言无 fuzzy match 路径） |
| `17.1.05` | 连续两日不同 price resolver：取最新未过期且不 conflict | `test_case_17_1_05_two_day_price_resolver_latest_non_expired` 或参数化 `case_id="17.1.05"` |
| `17.1.06` | 仅 proxy Evidence 时 direct 完整性为假且 mode 非 `DIRECT_AVAILABLE` | `test_case_17_1_06_proxy_only_not_direct_available` 或参数化 `case_id="17.1.06"` |
| `17.1.07` | 既有人工 direct FARM 在新闭环关闭时不降级 | `test_case_17_1_07_manual_direct_farm_not_downgraded` 或参数化 `case_id="17.1.07"` |
| `17.1.08` | 六个 `OPPORTUNITY_ECONOMIC` flags 默认 `false` 时，legacy score/label/workflow 关闭输出与 canonical bytes 逐字节相等 | `test_case_17_1_08_six_flags_default_false_canonical_bytes` 或参数化 `case_id="17.1.08"` |
| `17.1.09` | SQLite 与 `RecordingPostgresConnection` DDL 同表同约束，且 `init_db` 幂等 | `test_case_17_1_09_sqlite_and_recording_pg_ddl_idempotent` 或参数化 `case_id="17.1.09"` |
| `17.1.10` | 冻结 `raw_data` replay 校验 `schema_version`、hash framing、`snapshot_id`/`evidence_id`、mode；CG 与 CR 同属 `market-aggregators` 不双计；并参数化覆盖 §17.2 全项 | `test_case_17_1_10_frozen_raw_replay_schema_hash_mode_no_double_count` + `test_section_17_2_parametrized`（`case_id="17.1.10"` 为入口） |
| `17.1.11` | 空 `dedup_key` → `schema_invalid` 且无 snapshot | `test_case_17_1_11_empty_dedup_key_schema_invalid_no_snapshot` 或参数化 `case_id="17.1.11"` |
| `17.1.12` | CoinGecko 仅 `price_change_percentage_24h / 100`，忽略绝对美元 `price_change_24h` | `test_case_17_1_12_coingecko_percentage_only` 或参数化 `case_id="17.1.12"` |
| `17.1.13` | CryptoRank `percent_change_24h` 与 `percent_change_7d` 均除以 `100` | `test_case_17_1_13_cryptorank_percentages_div_100` 或参数化 `case_id="17.1.13"` |
| `17.1.14` | DefiLlama fixture unit 合同匹配才写入 ratio；不匹配 → `schema_invalid` | `test_case_17_1_14_defillama_unit_contract` 或参数化 `case_id="17.1.14"` |
| `17.1.15` | 同 `evidence_id` 内容冲突 → 失败且不覆盖既有行 | `test_case_17_1_15_evidence_id_content_conflict_no_overwrite` 或参数化 `case_id="17.1.15"` |
| `17.1.16` | 专用 normalizer：`usd`/`supply`/`ratio` 为 string，`market_rank` 为 number，`chains_json` 为排序 array 的 json，`token_unlisted_proxy` 为 bool | `test_case_17_1_16_specialized_normalizer_types` 或参数化 `case_id="17.1.16"` |
| `17.1.17` | 灰度分层：snapshot-only；snapshot+evidence；三者全开，行为分层正确 | `test_case_17_1_17_gray_release_layered_flags` 或参数化 `case_id="17.1.17"` |
| `17.1.18` | source flag 与既有 provider enabled 必须双真，否则不写 snapshot | `test_case_17_1_18_source_and_provider_dual_true` 或参数化 `case_id="17.1.18"` |
| `17.1.19` | collector raw `None` vs 真实数值 `0`：经济 `raw_data` 保留 provider `None`；legacy 过滤 / signal strength / discovery score 使用**局部**数值 fallback `0`（不得把 raw 缺失抹成 0）；真实 `0` 与 `None` 可区分 | `test_case_17_1_19_raw_none_vs_actual_zero_legacy_local_fallback` 或参数化 `case_id="17.1.19"` |
| `17.1.20` | provider-native `payload_json`：仅批准 raw 键白名单；**省略** `None`；**保留**真实数值 `0`；DefiLlama 含 `change_7d_unit`；`payload_sha256` 对**恰好**该对象计算（hash exact）；**不是** normalized factor map | `test_case_17_1_20_payload_json_whitelist_omit_none_keep_zero_defi_unit_hash` 或参数化 `case_id="17.1.20"` |
| `17.1.21` | manual `run_id` 精确为 `manual:<uuid>`；daily 为既有稳定 UTC 日期命名空间；二者形态隔离、不可碰撞 | `test_case_17_1_21_manual_run_id_vs_daily_namespace` 或参数化 `case_id="17.1.21"` |
| `17.1.22` | post-link replay `enabled=false`：**零** snapshot/Evidence 查询副作用、**零** `observation_from_snapshot` 重建、**零** Evidence 写入、**零** economic metrics 递增（整函数 no-op） | `test_case_17_1_22_replay_enabled_false_zero_side_effects` 或参数化 `case_id="17.1.22"` |
| `17.1.23` | `observation_from_snapshot`：`schema_version` 精确匹配、`payload_sha256` 与 §4.3 重算一致；单行 schema/hash 失败隔离，不阻断其它行、**不** rollback 已提交 project | `test_case_17_1_23_observation_from_snapshot_schema_hash_per_row_isolation` 或参数化 `case_id="17.1.23"` |
| `17.1.24` | 内部 only 投影：**无** `OpportunityWorkflowProjection` / v1 workflow 响应字段泄漏；§10.3 **四层**证明 — model / serializer / service / router（不得仅 router diff）；verifier **不**修改 production workflow | `test_case_17_1_24_internal_projection_no_workflow_v1_fields_four_layer` 或参数化 `case_id="17.1.24"` |
| `17.1.25` | metrics 必须经 sample value / label-set helper 断言（`metric_sample_value` / `metric_label_sets` 或等价）；裸 `Counter.labels()` 可调用或不抛 **不算**通过 | `test_case_17_1_25_metrics_sample_value_label_helper_not_bare_labels` 或参数化 `case_id="17.1.25"` |
| `17.1.26` | scheduled / manual 连接所有权与 close 合同（借用共享/请求连接，集成层禁止 close 共享连接）；Writer/Emitter/repository **构造**或 `process`/`emit` 失败隔离：不泄漏连接、不破坏 legacy 采集结果、不 rollback 已成功 persist | `test_case_17_1_26_connection_ownership_close_and_construct_process_isolation` 或参数化 `case_id="17.1.26"` |

**§17.2（挂在 case `17.1.10` 与参数化断言，必须逐项可失败；与 01–18 并存，不替代 19–26）:**
- §5.0 数组 framing 顺序、UTF-8、compact JSON、lowercase 64-hex SHA256
- provider-native whitelist 剥离（未知键与 credential canary 不得进入 payload/hash）
- URL query 中的 `api_key`/`token` 等 credential 不进入 payload、hash、log、stdout
- 缺失字段不补 `0`
- CG/CR 同组 `market-aggregators` 不双计
- mode 闭集：`PROXY_ONLY` \| `DIRECT_AVAILABLE` \| `UNKNOWN`
- `dedup_key` 与 `raw_id` 原样保留
- `value_type` 的 ValueType 闭集：`bool` / `number` / `string` / `json`，以及专用类型约束（`usd`/`supply`/`ratio` string、`market_rank` number、`chains_json` 排序 array json、`token_unlisted_proxy` bool）

**测试对 `main` 失败路径的强制证明:**
- 删除 `run_verification()` 返回字典中任意一个 case 键 → `main` 返回 `1`
- 将任意 case 值改为 `False` → `main` 返回 `1`
- 额外键 / 非 `CASE_IDS` 键集 → `main` 返回 `1`
- hash / fixture mismatch → `main` 返回 `1`
- 人为触发合同异常 → `main` 返回 `1`，且 stdout 仅 bounded exception type，无 fixture 全文、无 canary、无 credential
- 键集长度或集合不等于 26 / `CASE_IDS` → 测试与 `main` 均失败

**Steps:**
- [ ] **TDD 红：先写测试与冻结 fixture 骨架，实现前必须失败**
  - 创建 `backend/tests/fixtures/opportunity_economic/defillama.json`（含 `change_7d` unit 合同、`None`/真实 `0` 对照、未知键、credential canary）
  - 创建 `backend/tests/fixtures/opportunity_economic/coingecko.json`（含 `price_change_percentage_24h` 与 `price_change_24h`、`None`/真实 `0` 对照、未知键、canary）
  - 创建 `backend/tests/fixtures/opportunity_economic/cryptorank.json`（含 24h/7d 百分比、`None`/真实 `0` 对照、未知键、canary）
  - 创建 `backend/tests/scripts/test_verify_opportunity_economic.py`：
    - AST import denylist + socket connect 失败哨兵
    - 对 `CASE_IDS` 与 `run_verification()` 键集精确等于冻结 26-tuple（`17.1.01`–`17.1.26`）的断言
    - §17.1 **二十六项**各自 test 或 `pytest.mark.parametrize` 的 `case_id`（含独立 19–26）
    - §17.2 参数化断言（挂在 `17.1.10`；保留 01–18 与 §17.2，不因 19–26 省略）
    - 删除 case / 改 `False` / 额外键 / hash-fixture mismatch / 异常 → `main` 返回 `1` 的负向测试
    - 断言 stdout 末行 `RESULT: PASS`/`RESULT: FAIL`，状态行 **26/26** 或等价 `total=26`，且失败不打印 canary
  - 创建最小可导入的 `backend/scripts/verify_opportunity_economic.py` 桩（`CASE_IDS`/`run_verification`/`main` 签名齐全，但故意不满足 26 case 全 True，保证红灯）
  - 红跑命令：
    ```powershell
    Set-Location backend; python -m pytest tests/scripts/test_verify_opportunity_economic.py -q
    ```
    Expected: **FAIL**
- [ ] **实现 `backend/scripts/verify_opportunity_economic.py`（仅验收，不复制算法，不改 production workflow）**
  - 冻结 `CASE_IDS` 为精确 26-tuple `17.1.01`–`17.1.26`（见 Interfaces）
  - 实现 `run_verification() -> dict[str, bool]`：为 `17.1.01`–`17.1.26` 各构造临时 SQLite/事务环境，重放对应冻结 `raw_data`，调用既有 Tasks 1–8 生产接口完成断言，写入布尔结果
  - 实现 `main(argv: list[str] | None = None) -> int`：调用 `run_verification()`，按键排序打印结果与 **26/26** 状态行，全部 `True` 则 `RESULT: PASS` 并返回 `0`，否则 `RESULT: FAIL` 并返回非 `0`；捕获异常时只打印 bounded exception type
  - 全程无 HTTP、无真实 DB、无网络客户端导入/实例化；临时库/事务必须清理
  - 明确处理 01–18 既有验收点，以及独立 19–26：raw `None` vs 真实 `0` 与局部 legacy fallback、`payload_json` 白名单/省略 None/保留 0/Defi unit/hash exact、`manual:<uuid>` vs daily 命名空间、replay `enabled=false` 零副作用、`observation_from_snapshot` schema/hash 与 per-row 隔离、四层 internal-only 投影边界、metrics sample/label helper（裸 `Counter.labels` 无效）、scheduled/manual 连接所有权/close 与构造/`process` 失败隔离
  - **禁止**在 verifier 内复制 normalizer/resolver/workflow 算法；**禁止**修改 production workflow 或 app 生产模块
- [ ] **TDD 绿：测试全绿**
  ```powershell
  Set-Location backend; python -m pytest tests/scripts/test_verify_opportunity_economic.py -q
  ```
  Expected: **PASS**
- [ ] **CLI 全绿**
  ```powershell
  Set-Location backend; python scripts/verify_opportunity_economic.py
  ```
  Expected: exit code `0`，状态行 **26/26**（或 `passed=26 failed=0 total=26`），末行 `RESULT: PASS`
- [ ] **负向退出码测试仍 PASS**（包含于 pytest 套件；删除 case / False / 额外键 / mismatch / 异常均使 `main` 返回 `1`）
- [ ] **仅在上述全绿后**，在 `docs/IMPLEMENTATION_STATUS.md` 的「3. 后端模块」表新增精确一行 `| Opportunity economic data acquisition | app/opportunity/economic_* + scripts/verify_opportunity_economic.py | ✅ | Network-free verifier §17.1 26/26；frozen fixtures；CLI PASS |`；不得提前改状态文件
- [ ] **状态更新后重跑两条命令确认仍绿**
  ```powershell
  Set-Location backend; python -m pytest tests/scripts/test_verify_opportunity_economic.py -q
  Set-Location backend; python scripts/verify_opportunity_economic.py
  ```
  Expected: pytest **PASS**；CLI exit `0`、状态行 **26/26**，末行 `RESULT: PASS`
- [ ] **独立 commit（不 push）**
  ```powershell
  git add backend/scripts/verify_opportunity_economic.py backend/tests/fixtures/opportunity_economic/defillama.json backend/tests/fixtures/opportunity_economic/coingecko.json backend/tests/fixtures/opportunity_economic/cryptorank.json backend/tests/scripts/test_verify_opportunity_economic.py docs/IMPLEMENTATION_STATUS.md
  git commit -m "test(opportunity): add network-free economic verifier"
  ```
  明确：**不 push**

**Done criteria:**
- 文件边界精确：上述 5 个 Create + 1 个 Modify 状态文件；无 app 生产模块改动；无 production workflow 修改
- `CASE_IDS` 精确冻结为 26-tuple `("17.1.01", …, "17.1.26")`；`run_verification() -> dict[str, bool]` 键精确等于 `CASE_IDS`；`main` 仅全 True 返回 `0`；输出键排序；状态行 **26/26**；末行 `RESULT: PASS` 或 `RESULT: FAIL`
- network-free 可证明：AST denylist + socket connect 哨兵；无 requests/httpx/aiohttp/urllib.request/socket client；不读真实环境 DB；不发 HTTP
- 冻结 fixture 含未知键、credential canary、`None`/真实 `0` 对照，且最终输出不打印 canary；DefiLlama `change_7d` unit 合同可驱动 ratio vs `schema_invalid`
- §17.1 **二十六项**（保留 01–18，独立新增 19–26）与 §17.2（经 `17.1.10` 参数化）均有可独立失败的测试引用
- 删除 case / 改 False / 额外键 / hash-fixture mismatch / 异常 → `main` 返回 `1`，失败只打印 bounded exception type
- verifier **不**复制 production 算法、**不**修改 production workflow
- pytest 与 CLI 全绿后才更新 `docs/IMPLEMENTATION_STATUS.md`（状态文案含 **26/26**），再重跑确认，最后以消息 `test(opportunity): add network-free economic verifier` 独立 commit，且不 push
- 无占位内容；无省略生产逻辑的空实现；Python tuple 类型中的 `...` 仅在类型语法合法处使用

### Task 10: 完整验证与提交前检查

**Goal:** 在不实现、不修改任何功能代码的前提下，按固定顺序完成：冻结 base `80f6643` 的 **强制历史审计**（仅允许路径配对的 P1/P2 文档序曲 + 恰好九个 §21.3 实现 subject）、§21.4 changed-path allowlist 与禁止面证明、Tasks 1–9 聚焦测试、完整 backend pytest、offline verifier、带唯一临时 `PYTHONPYCACHEPREFIX` 的 compileall（清临时目录且仓库无 pycache 脏）、只读 Ruff、静态边界证明、`git diff --check 80f6643..HEAD` 与工作树、最终工作树干净与 **无 Task 10 commit / 无 push** 确认；任一失败立即停止，回到对应 Task 1–9 修复并重跑本套验证，不得在 Task 10 修代码、不得更新状态文档、不得产生功能 commit / 空 commit / push。

**Files:** None — verification only

**Interfaces:**
- 所有命令均从 **repo root**（本 worktree 根）开始执行。
- 凡 `Set-Location backend` 进入 backend 的命令块，块末必须 `Set-Location ..` 复位到 repo root。
- 任一命令 exit code 非 0，或任一条静态断言失败：立即停止本 Task，回到对应 Task 1–9 修复；修复后先跑该 Task 聚焦测试，再完整重跑 Task 10 全套。
- **禁止**在 Task 10 修改功能代码、创建/修改任何文件、更新 `docs/IMPLEMENTATION_STATUS.md`、制作 Task 10 验收 commit、空 commit 或 push。
- **冻结审计 base（字面）:** `80f6643`。历史 / diff / allowlist / 边界证明均基于 **`80f6643..HEAD`**（外加工作树干净检查）；**不得**用 Task 1 父提交、脏工作树 diff 或其它派生 base 代替字面 `80f6643`。
- **强制历史审计（非可选过滤）:** `git log --reverse 80f6643..HEAD`；P1/P2 必须 subject+单路径精确配对后才可排除；禁止「删除所有 `docs:`」「忽略 docs 路径」等宽松过滤。
- 不得将合法 `urllib.parse` sanitize 误判为网络访问。

**Steps:**

- [ ] **A. 强制历史审计（冻结 base `80f6643`；P1/P2 配对 + 恰好九个 §21.3 subject + §21.4 allowlist）**
  ```powershell
  # 从 repo root；审计 base 字面冻结，禁止替换
  $task10Base = "80f6643"
  $resolvedBase = git rev-parse --verify "$task10Base^{commit}"
  if ($LASTEXITCODE -ne 0 -or -not $resolvedBase) { throw "Frozen base 80f6643 does not resolve" }
  Write-Host "TASK10_BASE=$resolvedBase"

  # 工作树必须干净（验证开始前）
  $statusBefore = git status --short
  if ($statusBefore) { throw "Worktree not clean before audit:`n$statusBefore" }

  # 强制：old→new 顺序枚举 80f6643..HEAD（不得改用其它 range）
  $rawLog = @(git log --reverse --format="%H`t%s" "$task10Base..HEAD")
  if ($LASTEXITCODE -ne 0) { throw "git log --reverse 80f6643..HEAD failed" }
  if ($rawLog.Count -eq 0) { throw "Expected commits after 80f6643; history empty" }

  $p1Subject = "docs: reconcile economic acquisition with collector contracts"
  $p1Path = "docs/superpowers/specs/2026-07-22-opportunity-economic-data-acquisition-design.md"
  $p2Subject = "docs: plan opportunity economic data acquisition"
  $p2Path = "docs/superpowers/plans/2026-07-22-opportunity-economic-data-acquisition.md"

  # §21.3 恰好九个实现 subject（顺序冻结；local only / no push）
  $expectedImplSubjects = @(
    "feat(opportunity): economic flags, frozen models, canonical hash",
    "feat(opportunity): add dual-backend opportunity economic snapshots repository",
    "feat(opportunity): add provider economic normalizers",
    "feat(opportunity): add economic snapshot metrics and writer",
    "feat(opportunity): economic evidence insert-if-absent, dual identity link, post-link replay",
    "feat(opportunity): economic time-series resolver and snapshot source_id batch lookup",
    "feat(opportunity): wire economic snapshots into persisted collection paths",
    "feat(opportunity): add safe economic workflow projection",
    "test(opportunity): add network-free economic verifier"
  )

  # §21.4 allowlist = 文档序曲专用路径 + Exact File Map 实现路径 + Task 9 status
  $allowlist = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
  @(
    $p1Path,
    $p2Path,
    "docs/IMPLEMENTATION_STATUS.md",
    "backend/app/config.py",
    "backend/app/opportunity/economic_models.py",
    "backend/app/db.py",
    "backend/app/opportunity/economic_repository.py",
    "backend/app/opportunity/economic_normalizers.py",
    "backend/app/collectors/defillama.py",
    "backend/app/collectors/coingecko.py",
    "backend/app/collectors/cryptorank.py",
    "backend/app/metrics.py",
    "backend/app/opportunity/economic_writer.py",
    "backend/app/opportunity/economic_evidence.py",
    "backend/app/opportunity/repository.py",
    "backend/app/repository.py",
    "backend/app/agents/orchestrator_simple.py",
    "backend/app/opportunity/economic_resolver.py",
    "backend/app/opportunity/economic_integration.py",
    "backend/app/main.py",
    "backend/app/routers/v1/collections.py",
    "backend/scripts/verify_opportunity_economic.py",
    "backend/tests/opportunity/test_economic_models.py",
    "backend/tests/test_db_init.py",
    "backend/tests/opportunity/test_economic_repository.py",
    "backend/tests/opportunity/test_economic_normalizers.py",
    "backend/tests/collectors/test_defillama.py",
    "backend/tests/collectors/test_coingecko.py",
    "backend/tests/collectors/test_cryptorank.py",
    "backend/tests/opportunity/test_economic_writer.py",
    "backend/tests/opportunity/test_economic_evidence.py",
    "backend/tests/opportunity/test_repository.py",
    "backend/tests/test_repository.py",
    "backend/tests/opportunity/test_economic_resolver.py",
    "backend/tests/opportunity/test_economic_integration.py",
    "backend/tests/api/test_main_lifespan.py",
    "backend/tests/api/test_collections.py",
    "backend/tests/test_pipeline_run.py",
    "backend/tests/opportunity/test_workflow.py",
    "backend/tests/api/test_opportunity.py",
    "backend/tests/fixtures/opportunity_economic/defillama.json",
    "backend/tests/fixtures/opportunity_economic/coingecko.json",
    "backend/tests/fixtures/opportunity_economic/cryptorank.json",
    "backend/tests/scripts/test_verify_opportunity_economic.py"
  ) | ForEach-Object { [void]$allowlist.Add($_) }

  $forbiddenPathRegex = [regex]'(?i)(^|/)(requirements\.txt|pyproject\.toml|poetry\.lock|Pipfile(\.lock)?|uv\.lock|package-lock\.json|yarn\.lock|pnpm-lock\.yaml|Cargo\.lock)$|(^|/)(alembic/|migrations?/)|(^|/)(frontend|frontend-next)(/|$)|(^|/)backend/app/opportunity/decision\.py$|(^|/)backend/app/opportunity/calibration(/|$)|(^|/)\.env'
  $implSubjectsSeen = New-Object System.Collections.Generic.List[string]
  $preludePhase = $true
  $seenP1 = $false
  $seenP2 = $false

  foreach ($line in $rawLog) {
    if (-not $line) { continue }
    $parts = $line -split "`t", 2
    if ($parts.Count -ne 2) { throw "Malformed git log line: $line" }
    $commitHash = $parts[0]
    $subject = $parts[1]
    $paths = @(git show --name-only --pretty=format: $commitHash | Where-Object { $_ -and $_.Trim() -ne "" })
    if ($paths.Count -eq 0) { throw "Commit $commitHash has no changed paths (empty commit forbidden)" }

    foreach ($p in $paths) {
      if ($forbiddenPathRegex.IsMatch($p)) {
        throw "Forbidden path in $commitHash ($subject): $p"
      }
      if (-not $allowlist.Contains($p)) {
        throw "Path outside §21.4 allowlist in $commitHash ($subject): $p"
      }
    }

    if ($subject -eq $p1Subject) {
      if (-not $preludePhase) { throw "P1 must appear only before implementation commits" }
      if ($seenP1) { throw "Duplicate P1 prelude commit" }
      if ($paths.Count -ne 1 -or $paths[0] -ne $p1Path) {
        throw "P1 path mismatch: expected exactly [$p1Path], got [$($paths -join ', ')]"
      }
      $seenP1 = $true
      continue
    }
    if ($subject -eq $p2Subject) {
      if (-not $preludePhase) { throw "P2 must appear only before implementation commits" }
      if ($seenP2) { throw "Duplicate P2 prelude commit" }
      if ($paths.Count -ne 1 -or $paths[0] -ne $p2Path) {
        throw "P2 path mismatch: expected exactly [$p2Path], got [$($paths -join ', ')]"
      }
      $seenP2 = $true
      continue
    }

    # 非 P1/P2：必须进入实现序列；禁止其它 docs/chore/fixup/merge/空 subject 序曲
    $preludePhase = $false
    if ($subject -notin $expectedImplSubjects) {
      throw "Non-implementation commit not allowed (only validated P1/P2 may be excluded): $commitHash $subject"
    }
    if ($paths -contains $p1Path -or $paths -contains $p2Path) {
      throw "Implementation commit must not touch design/plan docs: $commitHash $subject"
    }
    $implSubjectsSeen.Add($subject) | Out-Null
  }

  if ($implSubjectsSeen.Count -ne 9) {
    throw "Expected exactly 9 implementation commits after excluding validated P1/P2, got $($implSubjectsSeen.Count)"
  }
  for ($i = 0; $i -lt 9; $i++) {
    if ($implSubjectsSeen[$i] -ne $expectedImplSubjects[$i]) {
      throw "§21.3 subject order mismatch at index $i : expected '$($expectedImplSubjects[$i])', got '$($implSubjectsSeen[$i])'"
    }
  }

  # 并集 allowlist 再证一遍（全历史 name-only）
  $allChanged = @(git diff --name-only "$task10Base..HEAD")
  foreach ($p in $allChanged) {
    if (-not $p) { continue }
    if ($forbiddenPathRegex.IsMatch($p)) { throw "Forbidden path in 80f6643..HEAD union: $p" }
    if (-not $allowlist.Contains($p)) { throw "Union path outside §21.4 allowlist: $p" }
  }

  # 显式拒绝面：dependency/lockfile、Alembic/migration、frontend、decision/calibration、新 route/响应字段
  $depDiff = git diff --name-only "$task10Base..HEAD" -- `
    requirements.txt pyproject.toml poetry.lock Pipfile Pipfile.lock uv.lock `
    package-lock.json yarn.lock pnpm-lock.yaml Cargo.lock
  if ($depDiff) { throw "Dependency/lockfile changes forbidden:`n$depDiff" }
  $migrationDiff = git diff --name-only "$task10Base..HEAD" -- alembic "**/migrations/**" "**/migration/**"
  if ($migrationDiff) { throw "Alembic/migration changes forbidden:`n$migrationDiff" }
  $frontendDiff = git diff --name-only "$task10Base..HEAD" -- frontend frontend-next
  if ($frontendDiff) { throw "Frontend changes forbidden:`n$frontendDiff" }
  $decisionCalibrationDiff = git diff --name-only "$task10Base..HEAD" -- `
    backend/app/opportunity/decision.py backend/app/opportunity/calibration
  if ($decisionCalibrationDiff) { throw "decision/calibration changes forbidden:`n$decisionCalibrationDiff" }

  $routerAdditions = (git diff --unified=0 "$task10Base..HEAD" -- backend/app/routers) -join "`n"
  if ($routerAdditions -match '(?m)^\+\s*@router\.(get|post|put|patch|delete)\b') {
    throw "Routers diff must not add route decorators"
  }
  if ($routerAdditions -match '(?m)^\+\s*(async\s+)?def\s+') {
    throw "Routers diff must not add route functions"
  }
  foreach ($field in @("economic_proxy", "economics_data_mode", "raw_snapshot_ref")) {
    if ($routerAdditions -match ('(?m)^\+.*' + [regex]::Escape($field))) {
      throw "Routers diff must not add response field: $field"
    }
  }

  Write-Host "HISTORY AUDIT: PASS (prelude P1=$seenP1 P2=$seenP2; 9 implementation subjects in order)"
  ```
  **Expected PASS:**
  - `git log --reverse 80f6643..HEAD` 可枚举；base 字面 `80f6643` 可 resolve。
  - 仅允许（0–2 笔）路径配对序曲：**P1** subject 精确为 `docs: reconcile economic acquisition with collector contracts` 且 **恰好** 改 `docs/superpowers/specs/2026-07-22-opportunity-economic-data-acquisition-design.md`；**P2** subject 精确为 `docs: plan opportunity economic data acquisition` 且 **恰好** 改 `docs/superpowers/plans/2026-07-22-opportunity-economic-data-acquisition.md`；二者若存在须在实现 commit **之前**。
  - 排除且仅排除通过配对的 P1/P2 后，剩余 subject **恰好** 为 §21.3 九条且 **同序**。
  - 无其它非实现 commit；每笔 commit 的 changed paths ⊆ §21.4 allowlist；并集无 dependency/lockfile、Alembic/migration、frontend、decision/calibration；routers 无新 route / 经济响应字段。
  - 起始工作树干净。
  **失败语义:** 任一 `throw` → 停止；回对应 Task 1–9（历史/序曲问题先修 commit 图，不得在 Task 10 补 commit 或 push）。

- [ ] **B. 依次运行 Tasks 1–9 聚焦测试（严格按 Task 顺序）**
  ```powershell
  # 从 repo root
  Set-Location backend

  # Task 1
  python -m pytest tests/opportunity/test_economic_models.py -q

  # Task 2
  python -m pytest tests/test_db_init.py -q -k economic_snapshot
  python -m pytest tests/opportunity/test_economic_repository.py -q

  # Task 3
  python -m pytest tests/opportunity/test_economic_normalizers.py tests/collectors/test_defillama.py tests/collectors/test_coingecko.py tests/collectors/test_cryptorank.py -q

  # Task 4
  python -m pytest tests/opportunity/test_economic_writer.py -q

  # Task 5
  python -m pytest tests/opportunity/test_repository.py tests/opportunity/test_economic_repository.py tests/opportunity/test_economic_evidence.py tests/test_repository.py -q

  # Task 6
  python -m pytest tests/opportunity/test_economic_repository.py tests/opportunity/test_economic_resolver.py -q

  # Task 7
  python -m pytest tests/opportunity/test_economic_integration.py tests/api/test_main_lifespan.py tests/api/test_collections.py tests/test_pipeline_run.py -q

  # Task 8
  python -m pytest tests/opportunity/test_workflow.py tests/api/test_opportunity.py tests/opportunity/test_service.py tests/opportunity/test_decision.py tests/opportunity/test_calibration_loader.py tests/opportunity/test_calibration_report.py tests/opportunity/test_calibration_metrics.py tests/opportunity/test_calibration_economics.py tests/opportunity/test_calibration_decisions.py tests/opportunity/test_calibration_outcomes.py tests/opportunity/test_calibration_advice.py -q

  # Task 9
  python -m pytest tests/scripts/test_verify_opportunity_economic.py -q

  Set-Location ..
  ```
  **Expected PASS（各组 exit 0，零 failed）:**

  | 组 | Expected PASS | 失败映射 |
  |---|---|---|
  | Task 1 | `test_economic_models` 全部通过 | → Task 1 |
  | Task 2 | `economic_snapshot` 筛选与 `test_economic_repository` 全部通过 | → Task 2 |
  | Task 3 | `test_economic_normalizers` + `test_defillama` / `test_coingecko` / `test_cryptorank` 全部通过 | → Task 3 |
  | Task 4 | `test_economic_writer` 全部通过 | → Task 4 |
  | Task 5 | repository / economic_repository / economic_evidence / test_repository 全部通过 | → Task 5 |
  | Task 6 | economic_repository + economic_resolver 全部通过 | → Task 6 |
  | Task 7 | economic_integration + main_lifespan + collections + pipeline_run 全部通过 | → Task 7 |
  | Task 8 | model / serializer / service / router boundary tests（`test_workflow` + `test_opportunity`）及 listed service / decision / calibration* 全部通过 | → Task 8 |
  | Task 9 | `test_verify_opportunity_economic` 全部通过（含 AST denylist / socket 哨兵 / credential canary） | → Task 9 |

  **失败语义:** 当前组非 0 即停；`Set-Location ..` 若尚未执行须先复位；回对应 Task 修复后重跑该组再重跑 Task 10 全套。Task 10 **不**修测试或实现。

- [ ] **C. 完整 backend pytest**
  ```powershell
  # 从 repo root
  Set-Location backend
  python -m pytest -q
  Set-Location ..
  ```
  **Expected PASS:** exit 0，零 failed。
  **失败语义:** 非 0 → 按失败用例归属回 Task 1–9 修复；**不是** Task 10 的实现机会。

- [ ] **D. Offline verifier**
  ```powershell
  # 从 repo root
  Set-Location backend
  python scripts/verify_opportunity_economic.py
  Set-Location ..
  ```
  **Expected PASS:** exit 0，且输出末行精确为 `RESULT: PASS`。
  **失败语义:** 非 0 或末行非 `RESULT: PASS` → 回 **Task 9**。

- [ ] **E. compileall（唯一临时 `PYTHONPYCACHEPREFIX` under TEMP；清临时；无仓库 pycache 脏）**
  ```powershell
  # 从 repo root；必须设置唯一临时前缀，禁止污染仓库树
  $task10Base = "80f6643"
  $pycachePrefix = Join-Path $env:TEMP ("pycache-opportunity-economic-" + [guid]::NewGuid().ToString("N"))
  $env:PYTHONPYCACHEPREFIX = $pycachePrefix
  try {
    python -m compileall -q backend/app backend/scripts backend/tests
    if ($LASTEXITCODE -ne 0) { throw "compileall failed with exit $LASTEXITCODE" }
  } finally {
    Remove-Item -Recurse -Force $pycachePrefix -ErrorAction SilentlyContinue
    Remove-Item Env:\PYTHONPYCACHEPREFIX -ErrorAction SilentlyContinue
  }
  # 验证仓库无 pycache / .pyc 变更
  $pycacheDirty = @(git status --short -- backend | Where-Object { $_ -match '__pycache__|\.pyc\b' })
  if ($pycacheDirty.Count -gt 0) {
    throw "Repository pycache dirty after compileall:`n$($pycacheDirty -join "`n")"
  }
  $pycacheDiff = git diff --name-only "$task10Base..HEAD" | Where-Object { $_ -match '(^|/)__pycache__/|\.pyc$' }
  if ($pycacheDiff) { throw "History must not contain pycache paths:`n$pycacheDiff" }
  Write-Host "COMPILEALL: PASS (temp PYTHONPYCACHEPREFIX removed; no repo pycache changes)"
  ```
  **Expected PASS:** compileall exit 0；临时目录已删除；`git status` 无 backend pycache/`.pyc` 脏；`80f6643..HEAD` 无 pycache 路径。
  **失败语义:** 非 0 或 pycache 脏 → 按语法错误模块回对应 Task；Task 10 **禁止**提交 `__pycache__` 或省略 `PYTHONPYCACHEPREFIX`。

- [ ] **F. Ruff 只读 lint（不得 `--fix`）**
  ```powershell
  # 从 repo root（Ruff 配置存在于 root pyproject / Makefile）
  python -m ruff check backend/app backend/scripts backend/tests
  ```
  **Expected PASS:** exit 0。
  **失败语义:** 非 0 → 回引入违规的对应 Task 修复；Task 10 **禁止** `ruff check --fix` 或手改以“通过 lint”。

- [ ] **G. 静态边界证明（可复制 PowerShell，不写文件；基于字面 `80f6643..HEAD`）**
  ```powershell
  # 从 repo root；base 字面冻结为 80f6643（与 Step A 一致）
  $task10Base = "80f6643"
  $resolvedBase = git rev-parse --verify "$task10Base^{commit}"
  if ($LASTEXITCODE -ne 0 -or -not $resolvedBase) { throw "Frozen base 80f6643 does not resolve" }

  # G1. 确认九个 §21.3 subject 仍在 80f6643..HEAD（实现序列存在性；序曲细节以 Step A 为准）
  $subjectsNow = @(git log --reverse --format="%s" "$task10Base..HEAD")
  $expectedImplSubjects = @(
    "feat(opportunity): economic flags, frozen models, canonical hash",
    "feat(opportunity): add dual-backend opportunity economic snapshots repository",
    "feat(opportunity): add provider economic normalizers",
    "feat(opportunity): add economic snapshot metrics and writer",
    "feat(opportunity): economic evidence insert-if-absent, dual identity link, post-link replay",
    "feat(opportunity): economic time-series resolver and snapshot source_id batch lookup",
    "feat(opportunity): wire economic snapshots into persisted collection paths",
    "feat(opportunity): add safe economic workflow projection",
    "test(opportunity): add network-free economic verifier"
  )
  $implOnly = @($subjectsNow | Where-Object {
    $_ -ne "docs: reconcile economic acquisition with collector contracts" -and
    $_ -ne "docs: plan opportunity economic data acquisition"
  })
  if ($implOnly.Count -ne 9) { throw "Expected 9 implementation subjects in 80f6643..HEAD, got $($implOnly.Count)" }
  for ($i = 0; $i -lt 9; $i++) {
    if ($implOnly[$i] -ne $expectedImplSubjects[$i]) {
      throw "Implementation subject mismatch at $i"
    }
  }

  # G2. frontend / frontend-next 零 diff
  $frontendDiff = git diff --name-only "$task10Base..HEAD" -- frontend frontend-next
  if ($frontendDiff) { throw "Forbidden frontend changes:`n$frontendDiff" }

  # G3. decision.py 与整个 calibration 零 diff
  $decisionCalibrationDiff = git diff --name-only "$task10Base..HEAD" -- backend/app/opportunity/decision.py backend/app/opportunity/calibration
  if ($decisionCalibrationDiff) { throw "Forbidden decision/calibration changes:`n$decisionCalibrationDiff" }

  # G4. API 允许 Task 7 在既有 collections.py 内接线，但不得增加 route/API surface 或响应字段
  $routerAdditions = (git diff --unified=0 "$task10Base..HEAD" -- backend/app/routers) -join "`n"
  if ($routerAdditions -match '(?m)^\+\s*@router\.(get|post|put|patch|delete)\b') {
    throw "Routers diff must not add route decorators"
  }
  if ($routerAdditions -match '(?m)^\+\s*(async\s+)?def\s+') {
    throw "Routers diff must not add route functions"
  }
  foreach ($field in @("economic_proxy", "economics_data_mode", "raw_snapshot_ref")) {
    if ($routerAdditions -match ('(?m)^\+.*' + [regex]::Escape($field))) {
      throw "Routers diff must not add response field: $field"
    }
  }

  # G5. 六个完整 flag 字段均精确 `: bool = False`
  $flagNames = @(
    "opportunity_economic_snapshot_enabled",
    "opportunity_economic_source_defillama_enabled",
    "opportunity_economic_source_coingecko_enabled",
    "opportunity_economic_source_cryptorank_enabled",
    "opportunity_economic_evidence_emit_enabled",
    "opportunity_economic_resolver_enabled"
  )
  $configText = Get-Content -Raw backend/app/config.py
  foreach ($flagName in $flagNames) {
    $pattern = [regex]::Escape($flagName) + "\s*:\s*bool\s*=\s*False"
    $matches = [regex]::Matches($configText, $pattern)
    if ($matches.Count -ne 1) { throw "Expected one bool False default for $flagName, got $($matches.Count)" }
  }
  $flagDefaultLines = @(rg -n "opportunity_economic_(snapshot_enabled|source_defillama_enabled|source_coingecko_enabled|source_cryptorank_enabled|evidence_emit_enabled|resolver_enabled)\s*:\s*bool\s*=\s*False" backend/app/config.py)
  if ($flagDefaultLines.Count -ne 6) { throw "Expected exactly six economic bool False defaults" }

  # G6. SQLite / PG 中唯一新表名均为 opportunity_economic_snapshots
  $economicDdl = @(rg -o "CREATE TABLE IF NOT EXISTS opportunity_economic_[a-z_]+" backend/app/db.py)
  $economicTableNames = @($economicDdl | ForEach-Object {
    if ($_ -match "opportunity_economic_[a-z_]+$") { $Matches[0] }
  })
  $uniqueEconomicTableNames = @($economicTableNames | Sort-Object -Unique)
  if ($economicTableNames.Count -ne 2) { throw "Expected two economic CREATE TABLE declarations, got $($economicTableNames.Count)" }
  if ($uniqueEconomicTableNames.Count -ne 1 -or $uniqueEconomicTableNames[0] -ne "opportunity_economic_snapshots") {
    throw "Only opportunity_economic_snapshots may be added"
  }

  # G7. 新 economic 路径、workflow 接线与 verifier 无网络 import/client；合法 urllib.parse 不匹配
  $filesToScan = @()
  $filesToScan += Get-ChildItem backend/app/opportunity -Recurse -File -Filter "*economic*.py" -ErrorAction SilentlyContinue
  foreach ($path in @(
    "backend/app/opportunity/workflow.py",
    "backend/app/opportunity/workflow_service.py",
    "backend/scripts/verify_opportunity_economic.py"
  )) {
    if (Test-Path $path) { $filesToScan += Get-Item $path }
  }
  $forbiddenImport = '(?m)^\s*(import\s+(requests|httpx|aiohttp|urllib\.request|socket)\b|from\s+(requests|httpx|aiohttp|urllib\.request|socket)\b)'
  $forbiddenClient = '(?m)(requests\.(get|post|put|delete|request|Session)\s*\(|httpx\.(get|post|Client|AsyncClient)\s*\(|aiohttp\.ClientSession\s*\(|urllib\.request\.(urlopen|Request)\s*\(|socket\.(socket|create_connection)\s*\()'
  foreach ($file in @($filesToScan | Sort-Object FullName -Unique)) {
    $source = Get-Content -Raw $file.FullName
    if ($source -match $forbiddenImport) { throw "Forbidden network import in $($file.FullName)" }
    if ($source -match $forbiddenClient) { throw "Forbidden network client in $($file.FullName)" }
  }

  # G8. Task 9 tests 保留 AST denylist、socket 哨兵与 credential canary 证明
  $verifierTestPath = "backend/tests/scripts/test_verify_opportunity_economic.py"
  if (-not (Test-Path $verifierTestPath)) { throw "Missing verifier tests" }
  $verifierTestText = Get-Content -Raw $verifierTestPath
  foreach ($keyword in @("denylist", "socket", "canary", "credential")) {
    if ($verifierTestText -notmatch $keyword) { throw "Verifier tests missing $keyword proof" }
  }

  # G9. dependency / migration 再证
  $depDiff = git diff --name-only "$task10Base..HEAD" -- requirements.txt pyproject.toml poetry.lock Pipfile Pipfile.lock uv.lock package-lock.json yarn.lock pnpm-lock.yaml
  if ($depDiff) { throw "Dependency/lockfile changes forbidden:`n$depDiff" }
  $migrationDiff = git diff --name-only "$task10Base..HEAD" -- alembic
  if ($migrationDiff) { throw "Alembic/migration changes forbidden:`n$migrationDiff" }

  Write-Host "STATIC BOUNDARY PROOF: PASS"
  ```
  **Expected PASS:** 脚本完整跑通，无 `throw`，并打印 `STATIC BOUNDARY PROOF: PASS`：
  - base 字面 `80f6643` 可解析；九个实现 subject 在排除 P1/P2 后同序；
  - frontend、decision、calibration、dependency/lockfile、Alembic 在 `80f6643..HEAD` 零 diff；
  - routers 无新增 route decorator/function/经济响应字段；
  - 六 flags 均为 `bool = False` 且恰好六行；
  - SQLite / PG 只有 `opportunity_economic_snapshots` 两个 DDL 声明；
  - economic/workflow/verifier 无网络 import 或 client；Task 9 测试保留无网络、无凭据泄漏证明。
  **失败语义:** 任一 `throw` → 按边界回对应 Task（flags → 1，表 → 2，API → 7，workflow → 8，verifier/credential → 9；decision/calibration/frontend/dependency/migration → 回引入该 diff 的 Task）；Task 10 不修改文件消除失败。

- [ ] **H. `git diff --check`（字面 `80f6643..HEAD` + 工作树）**
  ```powershell
  # 从 repo root；base 字面冻结，禁止 Task1^ 派生
  $task10Base = "80f6643"
  git rev-parse --verify "$task10Base^{commit}" | Out-Null
  if ($LASTEXITCODE -ne 0) { throw "Frozen base 80f6643 does not resolve" }
  git diff --check "$task10Base..HEAD"
  if ($LASTEXITCODE -ne 0) { throw "git diff --check 80f6643..HEAD failed" }
  git diff --check
  if ($LASTEXITCODE -ne 0) { throw "git diff --check (worktree) failed" }
  ```
  **Expected PASS:** 两条 `git diff --check`（`80f6643..HEAD` 与工作树）均无输出且 exit 0。
  **失败语义:** 空白/冲突标记问题 → 回引入该文件的 Task；Task 10 不修。

- [ ] **I. 最终 `git status --short`**
  ```powershell
  # 从 repo root
  git status --short
  ```
  **Expected PASS:** **空输出**（干净工作树；无 pycache 残留）。
  **失败语义:** 有输出 → 说明验证过程产生了不应存在的改动或遗留脏文件；停止，**不得**为清洁工作树而 commit；回查来源 Task。

- [ ] **J. 无额外 commit / 无 push 确认（不 commit、不 push）**
  ```powershell
  # 从 repo root；再次对照冻结历史，确认无 Task 10 验收 commit
  $task10Base = "80f6643"
  git log --reverse --oneline "$task10Base..HEAD"
  git status --short
  # 明确不执行: git commit / git push / 空 commit
  ```
  **Expected PASS:** `git log --reverse 80f6643..HEAD` 仍为「可选 P1/P2 + 恰好九个 §21.3 subject」；**无** Task 10 验收/空 commit；`git status --short` 仍为空。
  **Task 10 锁定结论:** **无额外 commit，无 push；确认 Tasks 1–9 各自 commit 后工作树干净。**
  **明确禁止:** 不运行 `git commit`；不 `git push`；不更新 `docs/IMPLEMENTATION_STATUS.md`；不创建/修改任何文件；不制作 Task 10 验收 commit。

**失败总则（适用于 A–J）:** 保留完整失败输出 → 映射回 Task 1–9 修复 → 运行该 Task 聚焦测试 → **完整重跑 Task 10 全套** → 仍不得在 Task 10 修代码、不得更新状态、不得制作 Task 10 验收 commit 或 push。
