# Opportunity 经济数据采集闭环设计

| 字段 | 值 |
|------|-----|
| 文档标题 | Opportunity 经济数据采集闭环设计 |
| 日期 | 2026-07-22 |
| 状态 | 待用户书面规格复核 |
| 适用范围 | Web3 Airdrop Alpha Agent System · Opportunity 经济代理数据闭环 MVP |
| 成功定义 | 形成可审计的「provider-native 不可变 snapshot → frozen NormalizedObservation → immutable EvidenceRecord → 只读经济代理投影」闭环；不声称补齐真实稀释、估值或空投奖励 |

---

## 1. 目标与非目标

### 1.1 目标

复用现有 DefiLlama、CoinGecko、CryptoRank collector 的既有采集与持久化路径，在 **CollectorResult / RawDiscovery 已成功写入之后**，由 **EconomicSnapshotWriter** 对每个 **schema-valid** 且命中 **raw_data 白名单** 的行，追加写入不可变经济快照；在内存中构造 **frozen NormalizedObservation**；仅当 **linked** 双条件同时满足时生成 **immutable EvidenceRecord**：(1) `raw_projects(source_id, dedup_key)` 精确返回非空 `project_id`；(2) `projects` 表已存在同 id 的权威项目行。任一不满足均为 **unlinked**，不生成 Evidence；由新的 **economic resolver** 产出只读经济代理投影。

每日调度与手动 trigger **必须**复用现有 scheduler / collections trigger；**禁止**为本闭环单独再发一遍外部 HTTP 请求。legacy `projects.score` / `label`、Opportunity `decide`、calibration、action workflow 状态机 **字节级行为保持不变**（在相关 flag 关闭时验收为字节级不变；flag 开启时仍不得改动上述模块的判定门槛与状态迁移）。

### 1.2 非目标（冻结）

- 不采集、不推断、不落库：参与钱包、积分、社区分配、代币解锁、空投奖励金额或份额。
- 不新增永真 FARM block、不新增 decision 分支、不放宽现有 FARM 直接经济证据门。
- MVP 不新增对外 API、不改前端、不改管理页；不引入 Alembic 或 down migration。
- 不修改 Calibration loader / report / schema；future feature 必须另立规格。
- 禁止 symbol / name fuzzy match；禁止用通用 `resolve_factor` 将「昨日与今日的正常市值/价格变化」判为冲突。
- 运行时 **不存在** fuzzy 尝试分支；禁止 fuzzy 由测试证明。

### 1.3 首期成功含义（唯一口径）

首期成功 **仅** 表示：「可审计经济代理闭环」已落地并可验收。
**绝不** 声称已补齐真实稀释、完全估值或空投奖励。缺失字段保持 **不写伪值 / 投影 unknown**；现有 FARM 直接证据门槛 **不得放宽**。

---

## 2. Provider 能力事实表（冻结）

下列能力为闭环唯一事实基线。三方数据源 **均不提供** 参与钱包、积分、社区分配、解锁、空投奖励。

| Provider | 鉴权 | 覆盖范围 | 可写入 factor 白名单 | 明确不可用 |
|----------|------|----------|---------------------|------------|
| DefiLlama | 无业务 key 依赖（按现有 collector） | 协议 TVL 视图 | `tvl_usd`, `tvl_change_7d_ratio`, `chains_json`, `token_unlisted_proxy`（由 no-token / 等价字段推导的 **proxy**） | 市值、成交量、流通/总供应、市场排名、价格涨跌幅、钱包/积分/解锁/空投 |
| CoinGecko | 按现有 collector | **仅前 250 已上市币** | `market_cap_usd`, `price_usd`, `volume_24h_usd`, `circulating_supply`, `market_rank`, `price_change_24h_ratio` | TVL/chains、total_supply、7d 涨跌、钱包/积分/解锁/空投 |
| CryptoRank | **需要 API key**（仅现有 collector 注入；禁止进入 snapshot payload / log / hash / source_url） | **仅已上市币** | `market_cap_usd`, `price_usd`, `volume_24h_usd`, `circulating_supply`, `total_supply`, `market_rank`, `price_change_24h_ratio`, `price_change_7d_ratio` | TVL/chains、钱包/积分/解锁/空投 |

**token_unlisted 必须以 proxy 形式存在**：字段键为 `token_unlisted_proxy`，语义为「聚合器侧未上市/无代币标记的代理信号」，**永不**升级为直接经济证据。

### 2.1 涨跌幅与 change 字段来源映射（冻结）

| factor_key | Provider | 唯一允许的 raw_data 来源与换算 | 禁止 |
|------------|----------|--------------------------------|------|
| `price_change_24h_ratio` | CoinGecko | **只取** `raw_data.price_change_percentage_24h / 100` → ratio（1.0=100%） | **绝不**取绝对美元字段 `price_change_24h` 或其别名 |
| `price_change_24h_ratio` | CryptoRank | `raw_data.percent_change_24h / 100` → ratio | 使用未除以 100 的百分点原值直接入库 |
| `price_change_7d_ratio` | CryptoRank | `raw_data.percent_change_7d / 100` → ratio | 同上 |
| `tvl_change_7d_ratio` | DefiLlama | **只取** `raw_data.change_7d` 作为 ratio 数值（1.0=100%），**且** `raw_data.change_7d_unit` **必须精确等于** 字面量 `"ratio"` | unit 缺失、`None`、空串或任何非 `"ratio"` 值；对 unit 做猜测、启发式、百分比↔ratio 自适应换算 |

DefiLlama `change_7d` / `change_7d_unit`（冻结）：

- Collector 写入 `RawDiscovery.raw_data` 时 **必须始终** 包含键 `change_7d_unit`，且值 **固定为字面量** `"ratio"`（不得省略、不得写百分比 unit、不得运行时推断）。
- Snapshot 路径的 normalizer **仅接受** `change_7d_unit == "ratio"`（字符串精确相等）。
- 若 `change_7d_unit` **缺失**、为 `None`、为空、或为其他任何值 → 该行 **整行 schema-invalid**，**不写** snapshot，**禁止猜测** unit 或做自适应归一。
- 离线 fixture 必须断言：`change_7d_unit` 字面量 `"ratio"` + 对应 ratio 语义；破坏即失败。

### 2.2 Collector 经济 raw_data 与 legacy 数值路径（冻结）

DefiLlama、CoinGecko、CryptoRank 三方 **经济相关** 写入 `RawDiscovery.raw_data` 的批准字段：

1. **保留 provider `None`**：provider 对某经济字段返回缺失/`None` 时，raw_data **原样保留 `None`**（或按既有「键存在值为 None」语义落库），**禁止**在写入 raw_data 前用数值 `0` 抹掉缺失。
2. **真实数值 0 与 `None` 分离**：provider 给出的实际 `0` **必须保留为 0**；不得与缺失混淆。
3. **legacy 行为不变**：既有 legacy 过滤、signal strength、discovery score **不得**改为读取「已被抹零的 raw_data」。它们继续使用 **独立的局部数值变量**，对缺失做 **fallback `0`**，从而在 raw_data 保留 `None` 后仍保持既有判定与计分行为不变。
4. DefiLlama 额外：`change_7d_unit` 按 §2.1 始终写入字面量 `"ratio"`（该键本身不是「可 None 的经济度量值」；它是强制 unit 标注）。

---

## 3. 架构闭环（不可变数据流）

```
[现有 daily scheduler / 手动 collections trigger]
        ↓  复用，不新增外部请求
[现有 DefiLlama | CoinGecko | CryptoRank collector]
        ↓
[CollectorResult 持久化 → RawDiscovery.raw_data 白名单行]
        ↓  schema-valid 才继续（含非空 dedup_key）
[EconomicSnapshotWriter → opportunity_economic_snapshots INSERT]
        ↓  内存 only
[frozen NormalizedObservation]
        ↓  仅当 linked：raw_projects 精确非空 project_id 且 projects 同 id 权威行存在
[immutable EvidenceRecord]
        ↓
[economic resolver → 内部只读经济代理投影（不进 API）]
        ↓
[既有 workflow 响应不变：Evidence 可读字段；raw_snapshot_ref 不公开；无 economic_proxy 字段]
```

- **RawDiscovery.raw_data**：仅 provider-native 白名单字段行，**不是**完整 HTTP body；经济字段保留 provider `None`（§2.2）；DefiLlama 强制含 `change_7d_unit="ratio"`（§2.1）。
- **`payload_json`**：snapshot 上的 **provider-native canonical 对象**（§4.3），**不是** NormalizedObservation 的 factor map。
- **NormalizedObservation**：内存 frozen 合同；**无** `items` / `identity_links` / `observation` 持久化表；合法构造仅 Writer 内存路径与 §5.5.1 重建。
- **经济代理投影**：内部服务对象 only（§10）；**禁止**写入 `OpportunityWorkflowProjection` 或 v1 workflow 响应体。
- **失败路径**：仅写入现有 `collection_logs` / `data_sources` / metrics；**禁止**写入伪 snapshot。

---

## 4. 存储：`opportunity_economic_snapshots`（MVP 唯一新表）

### 4.1 DDL 策略

- SQLite 与 PostgreSQL **均**在现有 `init_db()` 双分支中做 **additive、idempotent** DDL（`CREATE TABLE IF NOT EXISTS` + 必要索引 `IF NOT EXISTS`）。
- **无** Alembic；**无** down migration。
- 回滚策略：**只关闭 flags 与调度挂载**；表与历史行 **保留**。

### 4.2 表语义（冻结列职责）

| 列/字段角色 | 规则 |
|-------------|------|
| `snapshot_id` | 主键；见 §5 |
| `schema_version` | 固定常量 **`opportunity-economic-snapshot-v1`**（见 §5.0）；参与全部 hash |
| `run_id` | **daily** = 既有稳定 **UTC 日期** 命名空间（与现有调度一致的含 UTC 日期稳定 run 标识）；**manual** = 冻结格式 **`manual:<uuid>`**；两命名空间 **隔离且不可碰撞**（§5.1） |
| `source_id` | 与现有 collector / RawDiscovery 一致 |
| `dedup_key` | **原样保存** `RawDiscovery.dedup_key`；用于 `raw_projects(source_id, dedup_key)` 精确映射与 post-link **replay** |
| `provider_entity_id` | **明确取** `RawDiscovery.raw_id`；禁止改用展示名 / symbol / name |
| `payload_sha256` | 对 **恰好** §4.3 定义的 `payload_json` 对象做键排序 canonical JSON 后的 SHA-256（§5.0）；输入 **不是** factor map |
| `payload_json` | **provider-native canonical 对象**（§4.3）：原批准 raw 键、仅白名单、省略 `None`、保留真实数值 0、DefiLlama 含 `change_7d_unit`；**禁止**称为 normalized factor payload |
| `collected_at` | 采集完成时间（UTC） |
| `source_url` | 去查询凭据后的 URL；禁止 query 中的 key/token |
| 唯一约束 | `(snapshot_id)` 全局唯一；同 run 重试依赖 `snapshot_id` insert-if-absent |

**dedup_key 硬门槛**：`RawDiscovery.dedup_key` 缺失、空字符串或仅空白 → 该行 **schema-invalid**，**不写** snapshot，记 `opportunity_economic_snapshots_total{result="schema_invalid"}`。

**禁止** 存：API key、Authorization、钱包地址、用户身份、完整 HTTP 响应 envelope。

### 4.3 `payload_json` 合同（冻结）

`payload_json` 是 snapshot 行上的 **provider-native 不可变内容**，并作为 `payload_sha256` 的 **唯一** 哈希输入。定义为：

1. **来源**：自该行 `RawDiscovery.raw_data` 按 provider **原批准 raw 键白名单** 裁剪得到的对象；键名保持 **provider-native 原始键**（例如 DefiLlama 的 `tvl` / `change_7d` / `change_7d_unit` / `chains` / `no_token_yet` 等；CoinGecko / CryptoRank 同理使用其 raw 键），**不是** Evidence/`factor_key` 名（如 `tvl_usd`）。
2. **仅白名单**：只含批准 raw 键；**无**完整 HTTP body、**无** envelope、**无** URL、**无**凭据、**无**未批准键。
3. **省略 `None`**：值为 `None` 的白名单字段 **不得** 出现在 `payload_json` 中（键整体省略）。
4. **保留真实数值 0**：provider 给出的数值 `0` **必须保留**；不得因「省略空值」而删除真实 0。
5. **DefiLlama `change_7d_unit`**：schema-valid 行的 `payload_json` **必须包含** `change_7d_unit`，且值为字面量 `"ratio"`（与 §2.1 一致；若 unit 不合规则整行不写 snapshot，故不会出现「无 unit 的合法 payload」）。
6. **序列化**：对对象做 **递归对象键字典序排序** 后，`json.dumps(obj, ensure_ascii=False, separators=(',', ':'))`，编码 **UTF-8**。
7. **`payload_sha256`**：对 **恰好** 上述 canonical JSON 的 UTF-8 字节做 SHA-256，输出 **小写 64 位 hex**；**禁止**对任何其他对象（含 NormalizedObservation factor map、经 Decimal 字符串化后的 factor 载荷）计算并冒充本列。
8. **命名禁令**：`payload_json` **不是**、也 **不得称为**「normalized factor payload」。专用 normalizer 仅用于内存 `NormalizedObservation` / Evidence 的 factor 值；其输出 **不** 写入 `payload_json`。

---

## 5. 标识与幂等

### 5.0 `schema_version` 与 SHA-256 framing（冻结）

- **`schema_version` 唯一合法值**：`opportunity-economic-snapshot-v1`。
- **通用 hash framing**（`snapshot_id` 与 `evidence_id` **均**使用，仅组件列表不同）：
  1. 按公式参数 **固定顺序** 组成 JSON **字符串数组**（每个分量已是字符串；数值类分量先规范为字符串再入组）。
  2. 序列化：`json.dumps(array, ensure_ascii=False, separators=(',', ':'))`，编码 **UTF-8**。
  3. **禁止** Unicode 非规范替代表示、禁止数字的非规范替代（科学计数法、前导零、`+` 前缀、非半偶入后的多余形式等）；分量字符串必须已是 canonical 形态。
  4. 对 UTF-8 字节做 **SHA-256**，输出 **小写 64 位 hex**。
- **`payload_sha256`**：输入对象 **必须恰好是** §4.3 的 `payload_json`（provider-native 白名单对象；省略 `None`；保留真实 0；DefiLlama 含 `change_7d_unit`）。对该对象做 **键排序**（递归对象键字典序）后的 canonical JSON（同样 `ensure_ascii=False`、`separators=(',', ':')`、UTF-8），再 SHA-256 小写 64 hex。该 hex 字符串作为 `snapshot_id` 公式中的 `payload_sha256` 分量。**禁止**对 normalized factor map 或其他派生结构计算本哈希。

### 5.1 `snapshot_id`

公式分量顺序（字符串数组）：

```
[
  schema_version,       // "opportunity-economic-snapshot-v1"
  run_id,
  source_id,
  provider_entity_id,   // RawDiscovery.raw_id
  payload_sha256        // 小写 64 hex
]
```

→ 按 §5.0 framing 得 `snapshot_id`。

规则：

- **同 run 重试**：相同五元组 → 相同 `snapshot_id` → **insert-if-absent**（主键冲突后判定 duplicate / content_conflict）；不产生第二行。
- **snapshot duplicate 等价（冻结）**：同 `snapshot_id` 已存在时，仅当 **除 `collected_at` 以外** 的全部冻结合同字段均等价（含 canonical `payload_json`）才视为 **duplicate**：返回 **已持久化的不可变行** 与 `inserted=False`；**零 UPDATE**；**原存 `collected_at` 保持权威**（重试侧 `finished_at` / `collected_at` 漂移仅为重试元数据，不得覆盖）。任一其它冻结字段不同 → **`EconomicSnapshotContentConflict`**（失败且不覆盖）。
- **跨日相同 payload**：daily `run_id` 含新的 UTC 日期 → **必须**产生新 `snapshot_id` 与新历史行（审计「当时所见」）。
- **`run_id` 命名空间（冻结）**：
  - **daily**：保持既有稳定 **UTC 日期** 命名空间（与现有 scheduler 日批 run 标识一致；含 UTC 日期分量，跨日必变）。
  - **manual**：冻结为 **`manual:<uuid>`**（字面前缀 `manual:` + UUID 字符串；实现可注入 `uuid_factory` 以便确定性测试）。
  - daily 与 manual **不得碰撞**（前缀/形态隔离）；manual 不得使用裸 UUID 或 daily 形态。
  - 两类 run 仍走同一 Writer 与同一 hash 公式；身份绑定规则（§6）不变。

### 5.2 `evidence_id`

公式分量顺序（字符串数组）：

```
[
  schema_version,       // "opportunity-economic-snapshot-v1"
  snapshot_id,
  project_id,
  factor_key
]
```

→ 按 §5.0 framing 得 `evidence_id`。

- 未满足 linked 双条件时 **不生成** Evidence，**保留** snapshot（绑定键为 snapshot 上保存的 `source_id` + `dedup_key`）。linked 要求：(1) `raw_projects(source_id, dedup_key)` 精确返回非空 `project_id`；(2) `projects` 表已存在同 id 的权威项目行。

### 5.3 经济证据幂等写入（不改通用 `add_evidence`）

- **不改变** 通用 `add_evidence` 的既有冲突语义与调用约定。
- **新增** 经济证据专用 repository 方法（名称实现自定，语义冻结为 **insert-if-absent by `evidence_id`**）：
  - SQLite 与 PostgreSQL **均**以 `evidence_id` 主键冲突为成功路径：返回 **已有等价行**，metrics 记 `duplicate`。
  - 若同 `evidence_id` 已存在但 **内容与待写 Evidence 不等价**（factor 值、`value_type`、`independence_group`、`raw_snapshot_ref`、`source_grade`、`verification_status` 等合同字段任一不同）：**必须失败**（抛错/记错误 metrics），**禁止**静默覆盖、禁止更新就地改写。
  - replay 与同 run 重试均只走该方法，不走会改变通用冲突语义的路径。
- **双后端冲突验收（冻结）**：insert-if-absent 的 **insert / duplicate / content_conflict** 三种路径 **必须** 各有 **SQLite 与 PostgreSQL** 显式测试（共六条独立断言或参数化 backend 维度）。仅测 SQLite 或仅靠抽象 mock **不满足** 验收；两后端对「同 id 内容冲突必须失败且不覆盖」的行为必须一致。

### 5.4 重放边界

| 场景 | 行为 |
|------|------|
| 同 run 采集失败重试 | 不重复外部请求原则由上层 scheduler 保证；Writer 对已成功 snapshot 幂等 insert-if-absent |
| 现有采集持久化已写确定性 `raw_projects.project_id`；分析 pipeline 的 `ProjectRepository.save` 提交 `projects` 权威行后 | **post-link replay**（§5.5）：仅在显式 `enabled=true` 时，用 snapshot 行经 §5.5 重建 helper 得到 `NormalizedObservation`，再精确 identity → Evidence；不重新请求 provider |
| `OPPORTUNITY_ECONOMIC_EVIDENCE_EMIT_ENABLED=false`（或传入 `enabled=false`） | post-link replay **整函数 no-op**：不读 snapshot 列表用于 emit、不重建 Observation、不写 Evidence、不改 metrics 计数语义以外的业务状态 |
| flag 关闭（snapshot / resolver） | 停止 Writer / resolver 挂载；历史表保留；legacy/workflow 字节级不变 |
| payload 字段缺失 | 该 factor 不写 0；不生成该 factor 的 Evidence |
| 无 `dedup_key` | schema-invalid；无 snapshot |

### 5.5 Post-link replay 与 snapshot→NormalizedObservation 重建（冻结）

**挂载点**：分析 pipeline 的 `ProjectRepository.save` 在 **成功 commit** 权威 `projects` 行之后、返回已提交结果之前，调用 post-link replay。replay 异常 **不得** rollback 已提交的 project；仅记录 bounded log 后仍返回已提交结果。

**显式 `enabled` 合同（禁止隐式读 Settings 于 repository 层）**：

```
replay_economic_snapshots_for_project(
    project_id: str,
    *,
    conn: <existing DbConnection>,
    enabled: bool,
) -> EconomicEvidenceSummary | None
```

- `enabled` **必须**由调用方从 **`OPPORTUNITY_ECONOMIC_EVIDENCE_EMIT_ENABLED`**（settings 字段 `opportunity_economic_evidence_emit_enabled`）**推导为布尔**后传入；repository / replay 实现 **不**自行打开 Settings 旁路。
- **`enabled is False`**：**立即返回**（允许返回 `None` 或全零 summary，实现二选一但须在测试中固定），**零** snapshot 列表查询用于 emit、**零** Observation 重建、**零** Evidence 写入、**零** identity metrics 副作用（与「do nothing」等价）。
- **`enabled is True`**：按 project 关联的精确 identity 拉取已有 snapshot 行 → 对 **每一行** 调用 §5.5.1 重建 helper → 仅当重建成功且 linked 双条件满足时，经 §5.3 insert-if-absent emit Evidence；**禁止** HTTP / 二次 collect。

#### 5.5.1 `observation_from_snapshot`（名称实现可等价，语义冻结）

在 **任何** Evidence emit 之前，必须经本 helper 将持久化 snapshot 行重建为内存 **frozen `NormalizedObservation`**。合同：

| 步骤 | 规则 |
|------|------|
| 输入 | 单行 `opportunity_economic_snapshots` 记录（至少含 `snapshot_id`、`schema_version`、`source_id`、`dedup_key`、`provider_entity_id`、`payload_json`、`payload_sha256`、`collected_at`、`source_url`） |
| schema 校验 | `schema_version` **精确等于** `opportunity-economic-snapshot-v1`；否则该行失败 |
| payload 完整性 | 对行内 `payload_json` 按 §4.3 再算 SHA-256，**必须**等于行内 `payload_sha256`；否则该行失败 |
| 白名单 / normalizer | 仅用该 `source_id` 的批准 raw 键与专用 normalizer 从 `payload_json` 构造 factor map；DefiLlama 仍要求 `change_7d_unit=="ratio"` 等 §2.1 规则 |
| 输出成功 | frozen `NormalizedObservation`：`snapshot_id`、`source_id`、`dedup_key`（原样）、`provider_entity_id`、规范化 factor map、`collected_at`、消毒后 `source_url` |
| 输出失败 | **不**抛出以中断整次 replay 的未捕获异常到 `ProjectRepository.save` 成功路径；该行记为 **重建失败 / skipped**，**不** emit Evidence，**继续**下一 snapshot 行 |
| 禁止 | 重新请求 provider；用 symbol/name fuzzy 补全 identity；把 factor map 写回 `payload_json`；在 `enabled=false` 时调用本 helper |

**失败隔离（冻结）**：

1. 单行重建失败 → 跳过该行 Evidence；其它 snapshot 行继续。
2. 单行 identity unlinked → 零 Evidence for 该行；snapshot 保留。
3. 单行 Evidence content_conflict / 写入异常 → metrics `content_conflict`（或错误日志）；**不**删除 snapshot；继续后续行。
4. 整次 replay 外层异常（调用方仍应尽量局部化）→ `ProjectRepository.save` **不** rollback 已 commit 的 project。

---

## 6. 身份绑定（唯一允许路径）

- **linked** 须同时满足双条件：(1) `raw_projects(source_id, dedup_key)` 精确返回非空 `project_id`（`dedup_key` 来自 snapshot 列原样值）；(2) `projects` 表已存在同 id 的权威项目行。任一不满足均为 **unlinked**，不生成 Evidence。
- unlinked：snapshot 保留；**不入** Evidence。现有采集持久化已写确定性 `raw_projects.project_id`；分析 pipeline 的 `ProjectRepository.save` 提交 `projects` 权威行后触发 **post-link replay**（§5.5：`enabled` 来自 `OPPORTUNITY_ECONOMIC_EVIDENCE_EMIT_ENABLED`；false 时整函数 no-op）。
- **严禁** symbol / name / slug fuzzy match、编辑距离、别名表猜测。
- 代码路径 **不得** 实现「尝试 fuzzy 再拒绝」分支；禁止 fuzzy 由 **测试** 证明（仅精确查询存在/不存在；`projects` 权威行存在/不存在）。
- 身份解析指标：`opportunity_economic_identity_resolution_total{source,result}`，`result` **仅** `linked` \| `unlinked`（§13）。

---

## 7. EvidenceRecord 合同（严格沿用枚举）

### 7.1 枚举冻结

| 字段 | 允许值 | MVP 取值规则 |
|------|--------|----------------|
| `source_grade` | 仅 `A` / `B` / `C` / `D` / `U` | MVP 固定 **`C`** |
| `verification_status` | 仅 `verified` / `partially_verified` / `unverified` / `conflicted` / `invalidated` | **仅当** schema 通过 **且** linked 双条件同时满足时生成 **`verified`** Evidence；否则不生成 |
| `source_type` | 本闭环使用 | DefiLlama：`public_aggregator`；CoinGecko / CryptoRank：`public_market_data` |
| `independence_group` | 字符串 | DefiLlama：`defillama-protocols`；CoinGecko 与 CryptoRank：**同为** `market-aggregators`（**不得**计为两个独立证明） |
| `raw_snapshot_ref` | opaque | `econ-snapshot:<snapshot_id>`；workflow **不公开** |
| `independence_group` 字段 | 必填 | 供 resolver 组内/组间规则使用 |
| `value_type` | 见 §7.2 | 与 factor 一一对应，禁止混用旧 number normalizer 产出 |

### 7.2 冻结 factor 全集与 `value_type`

| factor_key | 来源 | EvidenceRecord.value_type | 值形态与 normalizer |
|------------|------|---------------------------|---------------------|
| `tvl_usd` | DefiLlama | `string` | usd：canonical Decimal string，scale=8，`ROUND_HALF_EVEN` |
| `tvl_change_7d_ratio` | DefiLlama | `string` | ratio：canonical Decimal string；**1.0 = 100%**；要求 raw `change_7d_unit` **精确** `"ratio"`，否则整行 schema-invalid；来源映射见 §2.1 |
| `chains_json` | DefiLlama | `json` | **排序后不可变数组**（元素字典序排序后的 frozen list）；非字符串糊弄 |
| `token_unlisted_proxy` | DefiLlama | `bool` | 严格布尔；键名必须带 `_proxy` |
| `market_cap_usd` | CG / CR | `string` | usd canonical Decimal string scale8 HALF_EVEN |
| `price_usd` | CG / CR | `string` | usd canonical Decimal string scale8 HALF_EVEN |
| `volume_24h_usd` | CG / CR | `string` | usd canonical Decimal string scale8 HALF_EVEN |
| `circulating_supply` | CG / CR | `string` | supply canonical Decimal string scale8 HALF_EVEN |
| `total_supply` | **仅 CryptoRank** | `string` | supply canonical Decimal string scale8 HALF_EVEN |
| `market_rank` | CG / CR | `number` | **非负整数**（JSON number / 语言层 int）；拒绝负值与非整数 |
| `price_change_24h_ratio` | CG / CR | `string` | ratio canonical Decimal string；映射见 §2.1 |
| `price_change_7d_ratio` | **仅 CryptoRank** | `string` | ratio canonical Decimal string；映射见 §2.1 |

**专用 normalizer（冻结）**：为上述 factor 增加 **本闭环专用** normalizer 函数族（至少覆盖 `usd`/`supply`/`ratio`→`string`、`market_rank`→`number`、`chains_json`→`json` 数组、`token_unlisted_proxy`→`bool`）。
**禁止** 复用「只接受 Python `int`/`float` 并写入旧 number 语义」的既有 number normalizer 处理 usd/supply/ratio 的 Decimal 字符串合同，也禁止用旧 normalizer 处理 `chains_json` / `token_unlisted_proxy`。

**缺失不写 0、不写空字符串占位 Evidence。**
`source_url`：**去除查询凭据**后再入库与展示给内部审计通道。

### 7.3 可扩展边界

- 允许扩展 `FACTOR_SCHEMAS` / `SUPPORTED_FACTOR_KEYS` **注册表**（新键必须有 schema、`value_type`、专用 normalizer 与 provider 映射）。
- **禁止** 将任何本闭环 proxy factor 加入：`CRITICAL_KEYS`、`_CONFIDENCE_FACTORS`、`_DIRECT_ECONOMICS_FACTORS`、`OpportunityInputs` 或 `decide` 门槛集合。
- **proxy 不能满足** `conditional_reward` / `hard_cost` 等直接经济证据要求。

---

## 8. EconomicSnapshotWriter 与 NormalizedObservation

### 8.1 Writer 触发点

现有 collector 完成 **CollectorResult + RawDiscovery 持久化** 之后同步调用 Writer（同一进程内）；**不**另开网络 client。

对每一行：

1. 校验 `dedup_key` 非空；`provider_entity_id := RawDiscovery.raw_id`；校验 provider schema（白名单 **raw** 键、§2.1 来源字段含 DefiLlama `change_7d_unit=="ratio"`、专用 normalizer、`value_type`）。
2. 任一步失败 → 只记 `collection_logs` / `data_sources` / metrics（`schema_invalid` 等）；**跳过**该行，不写 snapshot。
3. 成功 → 按 §4.3 自 raw_data 构造 **provider-native** `payload_json`（仅批准 raw 键；**省略 `None`**；**保留真实 0**；DefiLlama 含 `change_7d_unit`）→ 对 **恰好该对象** 计算 `payload_sha256` → `snapshot_id` → **insert-if-absent**；写入列含 **原样 `dedup_key`**。`payload_json` **不是** factor map。
4. 构造内存 **frozen NormalizedObservation**：携带 `snapshot_id`、`source_id`、`dedup_key`、`provider_entity_id`、经专用 normalizer 得到的规范化 factor map（含 `value_type`）、`collected_at`、`source_url`（已消毒）。factor map **仅内存**，不回写 `payload_json`。
5. 若 `OPPORTUNITY_ECONOMIC_EVIDENCE_EMIT_ENABLED` 为 true：先按 `(source_id, dedup_key)` 精确取 `raw_projects` 的 `project_id`，再验证 `projects` 表已存在同 id 的权威行；双条件均满足才经 §5.3 方法 emit Evidence；否则 `identity_resolution=unlinked` 并结束该行。

### 8.2 NormalizedObservation

- **仅内存**；不落库。
- frozen：创建后字段不可变；供 Evidence 构建与 offline verifier 对齐。
- **两条合法构造路径（仅此）**：(1) Writer 在 snapshot insert/duplicate 成功后于内存直接构造；(2) post-link replay 经 §5.5.1 `observation_from_snapshot` 自持久化行重建。禁止第三条「半构造 / 跳过校验」路径在 emit 前使用。

### 8.3 Writer 与 Evidence 的 `enabled` 边界

| 调用方 | 传入 Writer / Emitter / Replay 的布尔 | 来源 |
|--------|----------------------------------------|------|
| 集成层 `process_persisted_collection` | Writer `enabled=True` 仅当 §12.3 **三真门** 通过；否则不调用 Writer | 集成层计算，**非** Task 1 schema |
| 同上 | Emitter `enabled=` **`opportunity_economic_evidence_emit_enabled`** 原样布尔 | 集成层从 Settings 读取后传入 |
| `ProjectRepository.save` post-link | Replay `enabled=` **`opportunity_economic_evidence_emit_enabled`** 原样布尔 | 调用方推导后传入；false → §5.5 no-op |

Writer / Emitter / Replay **均不**在内部重新打开「三真门」或 Settings 旁路改写调用方传入的 `enabled`。

---

## 9. Economic Resolver（新建，专用）

对每个 `project_id`、每个 `factor_key`：

1. **按 `independence_group` 分组**。
2. 组内：先选 **最新且未过期** 的 Evidence；若时间戳相同，按 **固定 source priority** 决胜（冻结顺序）：
   `defillama`（仅 TVL 类 factor） > `coingecko` > `cryptorank`（市值类）；同 source 再比 `snapshot_id` 字典序稳定决胜。
3. **组间**：比较各独立组胜出值；若超过 **固定数值容差**（金额/数量 string：相对容差 `1e-8` 与绝对容差 `1e-8` 的联合判定；ratio string：绝对容差 `1e-8`；`chains_json` 数组 / `token_unlisted_proxy` bool / `market_rank` number：必须完全一致）则 **一律 `unknown`（冲突）**，不写平均、不写偏置选边。
4. **CoinGecko 与 CryptoRank 同属 `market-aggregators`**，组内已合并，**不得**再当两组独立证明抬升置信。
5. **禁止**调用通用 `resolve_factor` 处理本闭环市值/价格时序：昨日与今日的正常变化 **不得** 被标为 conflict；时序通过「最新未过期」表达，历史 snapshot 仅审计。

过期规则（冻结）：Evidence 自 `collected_at` 起 **48 小时** 内视为未过期；超时不参与组内竞选，可被更新 snapshot 的 replay 替代。

Resolver **仅**在 `OPPORTUNITY_ECONOMIC_RESOLVER_ENABLED=true` 时向 **内部**投影调用方输出（§10）；**即使** resolver 开启，也 **不得** 改变 v1 workflow API 响应体或 `OpportunityWorkflowProjection` 字段集。

---

## 10. 只读经济代理投影与 `economics_data_mode`（内部服务对象）

### 10.1 投影边界（冻结 — 无 workflow / API 字段扩展）

经济代理投影是 **内部服务对象 only**（例如 resolver 产出的 frozen `EconomicProxyProjection` / 等价结构），供内部服务、offline verifier 与后续 **另立规格** 的消费方使用。

**明确禁止（MVP）：**

- **禁止** 向 `OpportunityWorkflowProjection` 增加 `economic_proxy`、`economics_data_mode` 或 **任何** 新字段。
- **禁止** 修改现有 **v1 workflow API** 响应体形状（含 model 字段、serializer 输出键、service 组装进 response 的结构、router 返回模型）。
- **禁止** 为「flag 开启时可选挂载经济段」而改变 `model_dump` / JSON 键集合；flag 开或关，**既有** workflow 响应键与值语义相对本闭环 **必须** 保持可验收的基线一致（本闭环不得通过扩 response 表面「安全投影」）。
- workflow 继续只暴露 **既有** Evidence 安全业务字段；**禁止** 下发 `raw_snapshot_ref`。

内部投影结构（**不**进入 API / `OpportunityWorkflowProjection`）可包含：

- 各 factor 的 resolved 值或缺失/冲突表示
- `economics_data_mode`：闭集 **`PROXY_ONLY` | `DIRECT_AVAILABLE` | `UNKNOWN`**

### 10.2 mode 判定（冻结）

| mode | 条件 |
|------|------|
| `DIRECT_AVAILABLE` | **仅镜像** 现有 `_DIRECT_ECONOMICS_FACTORS` 完整性规则为真（人工或其他既有 direct 通道）；**provider proxy 永不**使本 mode 成立 |
| `PROXY_ONLY` | 存在至少一个本闭环 verified proxy Evidence，且 `DIRECT_AVAILABLE` 为假 |
| `UNKNOWN` | 无可用 proxy Evidence，且 direct 不完整 |

- 不新增永真 FARM block。
- 已有 **人工 direct evidence** 仍按 **原规则** 可 FARM；本闭环 **不得降级** 该路径。
- proxy **永不升级** 为 direct economics。

### 10.3 API 边界验收（跨层，非仅 router diff）

验收 **必须** 在下列 **四层路径** 上证明「无经济字段泄漏 / 无响应体扩展」，**不得** 仅用 `git diff` 扫描 router 文件代替：

| 层 | 断言 |
|----|------|
| model | `OpportunityWorkflowProjection`（及 workflow 相关 Pydantic 模型）**无** `economic_proxy` / `economics_data_mode` 字段定义 |
| serializer | `model_dump` / `model_dump(mode="json")` / 既有序列化辅助的键集 **不含** 上述经济字段；与 flag 全 false 基线字节或键集一致 |
| service | `OpportunityWorkflowService.get_project_workflow`（及等价组装路径）**不**把内部 `EconomicProxyProjection` 并入返回的 workflow 投影对象 |
| router | v1 workflow 相关 route 的 response_model / 返回 body **无** 新键；无新 route |

静态 diff 扫描 router 可作为 **补充**，**不能** 替代对 model / serializer / service 的运行时或契约测试。

---

## 11. 调度、Trigger、API 与 UI

| 能力 | MVP 规则 |
|------|----------|
| 每日调度 | 挂到现有 scheduler 同一 collection 任务 **persist 成功之后** 后置集成入口（§18.1）；内含 Writer；**不**新增外部 HTTP |
| 手动 trigger | 复用现有 collections trigger 接口与鉴权；persist 成功后同一集成入口；响应体与 HTTP 状态在 Writer/Emitter 失败时与基线 **字节级不变** |
| 状态/健康 | 复用现有 logs / health；本闭环额外只暴露 Prometheus 指标（§13） |
| 新 API | **零** |
| 前端 / 管理页 | **零改动** |
| workflow / v1 响应 | **不**扩展 `OpportunityWorkflowProjection` 或 v1 workflow 响应体（§10.1）；既有 Evidence 安全字段规则不变；**禁止**下发 `raw_snapshot_ref` |
| 复杂 UI / unlinked 查询 API | 不在本 MVP 范围；须另立规格后实现 |

---

## 12. 配置 Flags 与局部失败

### 12.1 Flags（名称、默认值、生效条件冻结）

全部 `OPPORTUNITY_ECONOMIC_*` **新 flag 默认 `false`**。

| Flag | 默认 | 作用与生效条件 |
|------|------|----------------|
| `OPPORTUNITY_ECONOMIC_SNAPSHOT_ENABLED` | `false` | 总开关；`false` 时不写 snapshot、不挂 Writer |
| `OPPORTUNITY_ECONOMIC_SOURCE_DEFILLAMA_ENABLED` | `false` | DefiLlama 分支；**必须** 本 flag **且** 既有 DefiLlama provider enabled 开关均为 `true` 才写入该 source |
| `OPPORTUNITY_ECONOMIC_SOURCE_COINGECKO_ENABLED` | `false` | CoinGecko 分支；**必须** 本 flag **且** 既有 CoinGecko provider enabled 均为 `true` |
| `OPPORTUNITY_ECONOMIC_SOURCE_CRYPTORANK_ENABLED` | `false` | CryptoRank 分支；**必须** 本 flag **且** 既有 CryptoRank provider enabled 均为 `true` |
| `OPPORTUNITY_ECONOMIC_EVIDENCE_EMIT_ENABLED` | `false` | `false` 时只允许 snapshot（在 snapshot 总开关开启时），不写 Evidence |
| `OPPORTUNITY_ECONOMIC_RESOLVER_ENABLED` | `false` | `false` 时不向 **内部** 投影调用方输出 economic mode/factor；**无论 true/false 均不得** 扩展 workflow/API 响应体（§10） |

**灰度顺序（强制）**：`snapshot` → `evidence` → `resolver`。
即：不得在 `OPPORTUNITY_ECONOMIC_SNAPSHOT_ENABLED=false` 时开启 evidence/resolver；不得在 `OPPORTUNITY_ECONOMIC_EVIDENCE_EMIT_ENABLED=false` 时开启 resolver 依赖本闭环 Evidence 的路径。验收必须覆盖 **全部新 flag 默认 false** 时 legacy/workflow **字节级不变**。

回滚：将上述 flag 置回 `false` 并卸下调度挂载；表与历史保留。

### 12.2 局部失败

- 单 provider / 单行 schema 失败：**不影响** 其他行、其他 source 的 snapshot。
- Evidence 写入失败（含同 id 内容冲突）：记录 metrics + logs；**不删除** 已成功 snapshot；**不**静默覆盖。
- Resolver 冲突：该 factor 投影 `unknown`（内部对象），**不**回写篡改 Evidence。
- Writer / repository / emitter **构造失败** 或单次 run 异常：按 §18.1 **逐 provider / 逐 run 隔离**；**不得**泄漏连接、**不得**改变 legacy `CollectorResult` 持久化成功语义与响应。

### 12.3 Provider 三真门（三重门）— **归属集成任务**

对某一 `source_id` 是否调用 Writer，**仅**当下列三者 **同时** 为 true（conjunction）：

| source | 三真条件 |
|--------|----------|
| `defillama` | `OPPORTUNITY_ECONOMIC_SNAPSHOT_ENABLED` ∧ `OPPORTUNITY_ECONOMIC_SOURCE_DEFILLAMA_ENABLED` ∧ 既有 `defillama` provider enabled |
| `coingecko` | `OPPORTUNITY_ECONOMIC_SNAPSHOT_ENABLED` ∧ `OPPORTUNITY_ECONOMIC_SOURCE_COINGECKO_ENABLED` ∧ 既有 `coingecko` provider enabled |
| `cryptorank` | `OPPORTUNITY_ECONOMIC_SNAPSHOT_ENABLED` ∧ `OPPORTUNITY_ECONOMIC_SOURCE_CRYPTORANK_ENABLED` ∧ 既有 `cryptorank` provider enabled |

**任务边界（冻结）**：

- **三真门 helper**（例如 `economic_source_enabled(source_id, settings_obj) -> bool`）**属于集成任务**（实现计划中 scheduled/manual integration / `economic_integration` 层），**不属于** schema / config / frozen-models 的 Task 1。
- Task 1 **仅**登记六个 `bool` flag 默认 `False` 与（若有）灰度 validator；**禁止** 在 Task 1 实现三真门 helper 或 provider enabled 合取逻辑。
- Writer **只**消费调用方传入的 `enabled: bool`；**不**在 Writer 内重算三真门。

---

## 13. 可观测性（Prometheus，标签闭集）

### 13.1 指标名（固定）

- `opportunity_economic_snapshots_total{source,result}`
- `opportunity_economic_observations_total{source,result}`
- `opportunity_economic_evidence_total{source,result}`
- `opportunity_economic_identity_resolution_total{source,result}`
- `opportunity_economic_run_duration_seconds{source}`
- `opportunity_economic_last_success_unixtime{source}`

### 13.2 `source` 闭集

`defillama` | `coingecko` | `cryptorank`

### 13.3 `result` 闭集

| 指标 | result 允许值 |
|------|----------------|
| snapshots | `inserted` \| `duplicate` \| `schema_invalid` \| `skipped_flag_off` |
| observations | `built` \| `skipped_no_snapshot` |
| evidence | `emitted` \| `skipped_no_project` \| `duplicate` \| `skipped_flag_off` \| `content_conflict` |
| identity_resolution | `linked` \| `unlinked` |

**删除** `rejected_fuzzy_attempt`：运行时无 fuzzy 尝试分支，故无对应 result。

**禁止** `project` / `symbol` / `id` 等高基标签。

### 13.4 Metrics 测试 helper（冻结 — 禁止伪验证）

Prometheus 验收 **必须** 使用 **精确 helper** 读取 Counter/Histogram/Gauge 的 **sample 数值与 label set**，例如（语义冻结，名称可等价）：

```
metric_sample_value(metric, **label_kwargs) -> float
metric_label_sets(metric) -> frozenset[tuple[tuple[str, str], ...]]
```

规则：

1. 断言 **前后 delta** 或绝对 sample value（对 Counter 优先 `before/after` 差值）。
2. 断言 label 组合 **恰好** 落在 §13.2 / §13.3 闭集内。
3. **`metric.labels(...).inc()` 可调用性、或裸 `Counter.labels()` 不抛异常，均不算验证通过。**
4. 非法 `source` / `result` 必须在生产封装处 `raise`；测试覆盖非法标签拒绝，而非静默吞掉。

---

## 14. 安全

- API key 与请求凭据：**不得**进入 payload、log、hash 输入、`source_url`。
- snapshot **只**存 §4.3 `payload_json`（provider-native 白名单、省略 `None`、保留 0）与 §4 列；含原样 `dedup_key`、`provider_entity_id=raw_id`；**不**存 normalized factor payload。
- **无** 钱包 / 用户 / 身份 PII。
- 公共 workflow：**不暴露** `raw_snapshot_ref`。
- CryptoRank key 仅存在于现有 collector 密钥配置通道。

---

## 15. Calibration / Workflow / Legacy

- Calibration loader、report、schema：**完全不改**。
- future calibration 使用经济代理：必须 **另立规格**。
- action workflow 状态机、Opportunity `decide`、legacy `projects.score` / `label`：**不变**。
- 本闭环输出不得写入会改变 score/label 的旁路。

---

## 16. 数据合同摘要

| 合同 | 形态 | 可变性 |
|------|------|--------|
| RawDiscovery.raw_data 白名单行 | 持久化（既有 + §2.1/§2.2） | 经济字段保留 provider `None`；DL 强制 `change_7d_unit="ratio"`；legacy 局部 fallback 0 |
| opportunity_economic_snapshots | 持久化新表 | 行级不可变；只追加；含 `dedup_key`；`payload_json` 为 §4.3 provider-native 对象 |
| NormalizedObservation | 内存 frozen | 不可变；factor map **不**进入 `payload_json` |
| EvidenceRecord | 既有 Evidence 存储路径 + 经济专用 insert-if-absent | immutable；同 id 内容冲突失败 |
| 经济代理投影 | 内部只读计算视图（非 API / 非 `OpportunityWorkflowProjection` 字段） | 随 Evidence 集合重算 |

Decimal（`value_type=string` 的 usd/supply/ratio）：**scale 8**，`ROUND_HALF_EVEN`，序列化为 **canonical 十进制字符串**（无科学计数法；与本闭环专用 normalizer 强制统一，不经旧 int/float number normalizer）。上述 Decimal 合同仅约束 **Observation/Evidence factor**，**不**把 `payload_json` 改写成 Decimal 字符串 factor 载荷。

Hash：一律 §5.0 framing；`schema_version` 恒为 `opportunity-economic-snapshot-v1`；`payload_sha256` 仅对 §4.3 `payload_json`。

`run_id`：daily = 既有稳定 UTC 日期命名空间；manual = **`manual:<uuid>`**；不可碰撞。

---

## 17. 测试与 Offline Verifier

### 17.1 必须覆盖的验收用例

1. **跨日同 payload 两快照**：相邻 UTC 日、相同 §4.3 白名单 `payload_json` → 两个不同 `snapshot_id`，两行历史（daily `run_id` 日期分量变化）。
2. **同 run 幂等**：同一 `run_id` 重复 Writer → snapshot 行数不增；metrics `duplicate`。
3. **post-link replay**：先有 `raw_projects` 映射及非空 `project_id`、但无 `projects` 行 → 零 Evidence；再插入/保存同 id 的 `projects` 权威行 → 在 `enabled=true` 时经 §5.5.1 重建 Observation 后产生稳定 `evidence_id`；`enabled=false` 时 `ProjectRepository.save` 后 **零** Evidence、**零** emit 副作用。
4. **无 fuzzy match**：即使 symbol 相同，或仅有 `raw_projects` 的 `project_id` 但无 `projects` 同 id 行 → 零 Evidence；`identity_resolution=unlinked`；代码路径无 fuzzy 分支（静态/测试证明）。
5. **昨日今日不冲突**：同 project 连续两日不同 price → resolver 取最新未过期，**不** conflict。
6. **proxy 不进 direct economics**：仅有闭环 Evidence 时 `_DIRECT_ECONOMICS_FACTORS` 完整性仍为假；`economics_data_mode` 不得为 `DIRECT_AVAILABLE`。
7. **人工 direct FARM 不降级**：既有 direct Evidence 场景下 decide/FARM 路径与 flag 全 false 时一致。
8. **flag 默认 false**：全部 `OPPORTUNITY_ECONOMIC_*` 默认关闭时 legacy score/label 与 workflow 关键路径 **字节级不变**。
9. **SQLite / PG DDL 等价**：`init_db()` 双分支均可幂等创建同名表与同逻辑约束。
10. **network-free verifier**：离线夹具重放 raw_data → 断言 `schema_version`、hash framing、`snapshot_id`/`evidence_id`、mode、`market-aggregators` 不双计、§4.3 `payload_json`/`payload_sha256` 一致。
11. **无 dedup_key → schema-invalid**：不写 snapshot。
12. **CoinGecko ratio**：仅 `price_change_percentage_24h/100`；夹具含绝对美元 `price_change_24h` 时不得被采用。
13. **CryptoRank ratio**：`percent_change_24h`/`7d` 除以 100。
14. **DefiLlama `change_7d_unit`**：raw_data **必须**含字面量 `change_7d_unit="ratio"`；normalizer **仅**接受精确 `"ratio"`；缺失、`None` 或其他值 → 整行 schema-invalid；禁止猜测/自适应换算。
15. **evidence 同 id 内容冲突**：必须失败，不得覆盖；**SQLite 与 PostgreSQL 双后端** 均覆盖 insert / duplicate / content_conflict（§5.3）。
16. **专用 normalizer**：usd/supply/ratio 为 string；`market_rank` 为 number；`chains_json` 为排序数组 json；`token_unlisted_proxy` 为 bool；其输出 **不** 写入 `payload_json`。
17. **灰度顺序**：仅 snapshot 开 / snapshot+evidence / 三者全开 的分层行为符合 §12.1。
18. **source 三真门**：snapshot flag ∧ source flag ∧ 既有 provider enabled；任一侧为 false 时该 source 不写 snapshot；helper 归属 **集成任务**（§12.3），非 Task 1。
19. **raw_data 保留 provider `None`**：DefiLlama / CoinGecko / CryptoRank 经济白名单字段在 raw_data 中保留 `None`；legacy 过滤、signal strength、discovery score 使用 **独立局部数值变量** 并对缺失 fallback `0`，行为与改前一致。
20. **`payload_json` 合同**：对象仅为原批准 raw 键白名单；省略 `None`；保留真实数值 0；DefiLlama 含 `change_7d_unit`；`payload_sha256` 对 **恰好** 该对象计算；**不是** normalized factor payload / factor map。
21. **`run_id` 命名空间**：manual 精确为 `manual:<uuid>`；daily 为既有稳定 UTC 日期命名空间；二者形态隔离、不可碰撞。
22. **replay `enabled=false` no-op**：`ProjectRepository.save` 传入 `enabled=false` 时零 Evidence、零 §5.5.1 重建副作用。
23. **`observation_from_snapshot` 校验与隔离**：`schema_version` 精确匹配、`payload_sha256` 与 §4.3 重算一致；单行失败不阻断其它行、不 rollback 已提交 project。
24. **内部投影不进 API**：`OpportunityWorkflowProjection` / v1 workflow 响应 **无** `economic_proxy` 等新字段；§10.3 四层（model/serializer/service/router）均有验收，非仅 router diff。
25. **Prometheus sample helper**：metrics 测试经 §13.4 helper 断言 sample value 与 label set；裸 `Counter.labels()` **不**算通过。
26. **连接所有权与构造失败隔离**：§18.1；单 provider/run 的 Writer/Emitter/repository 构造或运行失败不泄漏连接、不破坏 legacy 采集结果。

### 17.2 Offline Verifier 职责

- 输入：冻结 fixture（无网络），含 DefiLlama `change_7d_unit` 字面量 `"ratio"` 合同，以及 raw 字段 `None` / 真实 `0` 对照夹具。
- 校验：§5.0 hash、§4.3 `payload_json`/`payload_sha256` 字节一致、白名单剥离、凭据不泄漏、ratio 语义与 §2.1 映射（含 unit 精确 `"ratio"`）、缺失不写 factor 0、CG/CR 不双计独立组、mode 三态（**内部**投影）、`dedup_key`/`raw_id` 列、value_type 与专用 normalizer、`run_id` 命名空间、replay enabled 门控与重建 helper 合同。
- 退出码：合同破坏非 0。
- verifier **不得** 要求或假设 v1 workflow API 响应含经济投影字段。

---

## 18. 与现有模块的集成边界

| 模块 | 集成方式 |
|------|----------|
| DefiLlama/CG/CR collector | 只读其已持久化 RawDiscovery；不改采集 URL 语义；经济 raw_data 保留 provider `None`（legacy 局部 fallback 0）；DefiLlama 强制写入 `change_7d_unit="ratio"` |
| scheduler / collections trigger | 复用入口；persist **成功后** 调用集成层；manual `run_id=manual:<uuid>`；daily 既有 UTC 日期命名空间；三真门 helper 在此层（§12.3） |
| collection_logs / data_sources | 失败与状态复用 |
| Evidence 存储 | 通用 `add_evidence` 语义不变；经济路径走专用 insert-if-absent；双后端冲突测试（§5.3） |
| decide / score / label | 不引用 proxy 门槛；不读 raw_snapshot_ref |
| workflow / v1 API | **不**扩展 `OpportunityWorkflowProjection` 或响应体；内部 resolver 投影仅服务内使用（§10） |
| `ProjectRepository.save` | commit 后 post-link replay（§5.5）；`enabled` 来自 evidence flag |

### 18.1 调度 / 手动集成：连接所有权、关闭行为与构造失败隔离（冻结）

**连接所有权**

| 路径 | 连接生命周期 |
|------|----------------|
| **Scheduled**（`main` lifespan / `on_collection`） | 使用 lifespan **已有**共享 `DbConnection`（或项目既有等价连接）。集成层构造的 `EconomicSnapshotRepository` / `EconomicSnapshotWriter` / `OpportunityRepository` / `EconomicEvidenceEmitter` **借用**该连接，**禁止**在集成路径内 `close()` / `dispose()` 共享连接。 |
| **Manual**（collections trigger） | 使用该请求/上下文 **既有**连接（与 persist 相同 owner）。request-scoped 的 repository/writer/emitter **借用**同一连接；**禁止**在集成结束时关闭仍由上层 owner 管理的连接。 |
| **Post-link replay** | 使用 `ProjectRepository.save` 传入的 **同一** `conn`；replay **不得**关闭该连接。 |

**关闭行为**

- 集成层 / Writer / Emitter / Replay **从不**拥有「创建并关闭」共享连接的职责。
- 若某实现为隔离测试打开 **私有**临时连接，则 **必须** 在该私有作用域 `try/finally` 中关闭，且 **不得** 替换或关闭生产路径上的共享连接。
- 禁止在异常路径上双重 close 或把已关闭连接交回 scheduler。

**构造与运行失败隔离（per provider / per run）**

1. 单次 scheduled source 回调或单次 manual trigger 中，Writer / Emitter / economic repository **构造失败** 或 `process` / `emit` 抛错：捕获并 bounded log（无凭据），**返回/继续** 既有 legacy 成功路径。
2. **不得** 因经济路径失败而：回滚已成功的 `persist_collection_result`、改变 HTTP 状态、改变 `CollectionTriggerResponse`（或等价）的 `model_dump` 字节、跳过其它 source 的调度、抑制既有 optional auto-analysis 的基线门控语义（除非基线本身已定义且与经济无关）。
3. 构造失败 **不得** 泄漏半开连接（私有连接必须 finally 关闭；共享连接不得被 close）。
4. 多 source 并行/串行调度时，source A 的经济失败 **不得** 污染 source B 的 `CollectorResult` 或经济状态。
5. post-link replay 失败 **不得** rollback 已 commit 的 `projects` 行（§5.5）。

**集成顺序（冻结）**

1. `collector.collect` **恰好一次**（既有路径）。
2. `persist_collection_result` **恰好一次**；失败 → **零** Writer / Emitter 调用。
3. 仅 persist 成功后：`economic_source_enabled` 三真门；通过则 `writer.process(..., enabled=True)` 一次；再对 `summary.observations` 逐条 `emitter.emit(..., enabled=evidence_flag)`。
4. 然后既有 optional analysis / pipeline（若有）。

---

## 19. 实施顺序（无分叉算法）

实现计划 Tasks **1–9** 各对应 **一次** local commit（§21 冻结 subject）；Task 10 **仅验证、无 commit**。依赖顺序：

1. **Task 1 — flags + frozen models + hash**：六个 flag 默认 false + §5.0 framing + 冻结模型。**不含** 三真门 helper（§12.3）。
2. **Task 2 — dual-backend DDL + snapshot repository**：`init_db()` 双分支 additive DDL（含 `dedup_key`、`provider_entity_id`）；snapshot insert-if-absent。
3. **Task 3 — provider normalizers**：§2.1/§2.2 映射、§4.3 `payload_json` 裁剪、专用 normalizer。
4. **Task 4 — metrics + non-networking Writer**：§13 指标 + §13.4 sample helper 测试；Writer 只消费 `enabled: bool`；含 `observation_from_snapshot` 或与 Writer 对称的重建原语供 Task 5 复用。
5. **Task 5 — Evidence insert-if-absent + dual identity + post-link replay**：§5.3 双后端冲突测试；§5.5 `enabled` + §5.5.1 重建；`ProjectRepository.save` hook。
6. **Task 6 — economic resolver（内部投影）**：`economics_data_mode` 与 factor 解析；**不**改 workflow 模型/API。
7. **Task 7 — scheduled/manual 集成**：§12.3 三真门 helper、§18.1 连接所有权与失败隔离、run_id 命名空间、`process_persisted_collection`。
8. **Task 8 — workflow 边界保护（非扩字段）**：**禁止** 向 `OpportunityWorkflowProjection` 添加 `economic_proxy`；验收 §10.3 四层边界 + flag 全 false 字节级基线；可将内部 resolver 保留为 service-private 调用 **仅当** 不改变任何对外响应体（MVP 推荐：**零** workflow 响应接线，仅回归测试锁边界）。
9. **Task 9 — network-free verifier + fixtures + status**：§17 全绿后才可改 `docs/IMPLEMENTATION_STATUS.md`。
10. **Task 10 — 完整验证门**（§21）：无文件修改、无 commit/push。

回滚：只关 flag、卸挂载；表与历史保留。**无** 依赖新增、**无** Alembic/migration 文件。

---

## 20. 验收签字清单（书面复核用）

复核人确认下列语句均为 **是** 后方可进入实现：

- [ ] MVP 仅新增 `opportunity_economic_snapshots`；无 Alembic/down migration；列含原样 `dedup_key`，`provider_entity_id=RawDiscovery.raw_id`。
- [ ] `schema_version=opportunity-economic-snapshot-v1`；hash 使用 §5.0 framing；跨日/同 run 幂等正确。
- [ ] `payload_json` 为 §4.3 provider-native 白名单对象（省略 `None`、保留真实 0、DL 含 `change_7d_unit`）；`payload_sha256` 对该对象计算；**不是** normalized factor payload。
- [ ] daily `run_id` 为既有稳定 UTC 日期命名空间；manual 为 `manual:<uuid>`；命名空间不可碰撞。
- [ ] 三 provider 经济 raw_data 保留 provider `None`；legacy 过滤/signal strength/discovery score 用局部数值 fallback 0，行为不变。
- [ ] snapshot → 内存 Observation → Evidence → **内部**只读投影链路完整；经济 Evidence 专用 insert-if-absent；同 id 内容冲突失败且 **SQLite+PostgreSQL** 双测。
- [ ] post-link replay 接受显式 `enabled`（源自 `OPPORTUNITY_ECONOMIC_EVIDENCE_EMIT_ENABLED`）；false 时 no-op；emit 前必须经 §5.5.1 重建且失败隔离。
- [ ] 三 provider 能力、§2.1 映射（含 DL unit 精确 `"ratio"`）与 factor/`value_type` 表与本文一致；专用 normalizer；无钱包/积分/解锁/空投。
- [ ] 身份同时要求 `raw_projects` 精确映射和 `projects` 权威行存在；禁止 fuzzy；identity result 仅 `linked`|`unlinked`。
- [ ] CG 与 CR 同属 `market-aggregators`。
- [ ] proxy 永不进入 direct economics；不改 decide/calibration/workflow 状态机；不改通用 `add_evidence` 冲突语义。
- [ ] 零新 API、零前端；**不**向 `OpportunityWorkflowProjection` 或 v1 workflow 响应添加 `economic_proxy`/任何经济字段；§10.3 四层边界验收。
- [ ] `raw_snapshot_ref` 不公开。
- [ ] 全部 `OPPORTUNITY_ECONOMIC_*` 默认 false；**三真门 helper 归属集成任务**（非 Task 1）；灰度 snapshot→evidence→resolver。
- [ ] Prometheus 指标与 result 闭集符合 §13；测试使用 §13.4 sample/label helper，裸 `Counter.labels()` 无效。
- [ ] 调度/手动集成冻结连接所有权与 close 行为；构造/运行失败 per provider/run 隔离，不泄漏连接、不破坏 legacy 采集结果（§18.1）。
- [ ] 安全：凭据不进 payload/log/hash/source_url。
- [ ] 验收用例 §17.1 全部强制（含 19–26）。
- [ ] 最终实现门禁符合 §21（base `80f6643`、至多两笔路径约束文档序曲 + 恰好九个实现 commit subject、subject/path 配对、路径 allowlist、无依赖/migration、`PYTHONPYCACHEPREFIX` compileall、local only / 无 push）。
- [ ] 首期成功口径仅为「可审计经济代理闭环」，不声称真实稀释/估值/奖励补齐。
- [ ] 文档状态仍为「待用户书面规格复核」。

---

## 21. 最终实现计划门禁（冻结）

本门禁约束 **实现计划 Task 10** 与合并前验证；与架构、测试、集成边界、§19 顺序一致。

### 21.1 Base commit

- **Base commit（冻结）**：`80f6643`（完整 hash 以仓库该前缀解析的唯一 commit 为准；实现与 diff 范围均相对此 base 的 feature 历史）。
- 静态边界与 changed-path 证明基于 **`80f6643..HEAD`**（含下文冻结的文档序曲与九个实现 commit），**不得**仅用脏工作树 diff 声称历史干净。
- **Local only / 禁止 push**：`80f6643..HEAD` 全程与 Task 10 验证均在本地完成；门禁通过 **不** 授权 remote push。

### 21.2 文档序曲（冻结；`80f6643..HEAD` 已含 / 可含）

因 base 之后 **已经** 存在为实现做准备的文档提交，门禁 **冻结** 下列 **至多两** 笔 **documentation-prelude**（文档序曲）commit。它们 **不是** 实现 commit，**不计入** §21.3 的九个 IMPLEMENTATION subject。

| # | 允许的 commit subject（精确字面） | 允许的 changed path（该 commit **仅** 可改此路径；恰好 1 个文件） |
|---|----------------------------------|------------------------------------------------------------------|
| P1 | `docs: reconcile economic acquisition with collector contracts` | `docs/superpowers/specs/2026-07-22-opportunity-economic-data-acquisition-design.md` |
| P2 | `docs: plan opportunity economic data acquisition` | `docs/superpowers/plans/2026-07-22-opportunity-economic-data-acquisition.md` |

规则（冻结）：

1. **Subject/path 配对**：P1/P2 仅在 **subject 与上表完全一致** 且 **该 commit 的 changed paths 恰好为对应单路径** 时，方可作为序曲排除；禁止「任意 `docs:` commit」或「任意文档路径」被过滤掉。
2. **无其它序曲**：`80f6643..HEAD` 中 **不得** 出现除 P1、P2 以外的任何非实现 commit（含其它 docs、chore、fixup、merge、空 commit）。
3. **位置**：P1 与/或 P2（若存在）**仅** 允许出现在实现序列 **之前**；**不得** 夹在 Tasks 1–9 实现 commit 之间或之后。
4. **缺省允许**：序曲可为 0、1 或 2 笔（仅限上表）；缺省不降低九个实现 subject 的强制要求。

### 21.3 恰好九个实现 commit subject（Tasks 1–9）

在 **排除且仅排除** §21.2 两笔路径约束文档序曲之后，相对 base 的实现历史 **必须恰好** 剩余下列 **九** 个 IMPLEMENTATION commit subject（顺序与 §19 一致；**local only，禁止 push**；禁止 squash 绕过门禁）：

1. `feat(opportunity): economic flags, frozen models, canonical hash`
2. `feat(opportunity): add dual-backend opportunity economic snapshots repository`
3. `feat(opportunity): add provider economic normalizers`
4. `feat(opportunity): add economic snapshot metrics and writer`
5. `feat(opportunity): economic evidence insert-if-absent, dual identity link, post-link replay`
6. `feat(opportunity): economic time-series resolver and snapshot source_id batch lookup`
7. `feat(opportunity): wire economic snapshots into persisted collection paths`
8. `feat(opportunity): add safe economic workflow projection`
9. `test(opportunity): add network-free economic verifier`

说明：第 8 条 subject 保持实现计划字面稳定，但 **语义以本文 §10 / §19 为准**——「safe」= **不扩展** workflow/API 响应体、锁边界与回归，**不是** 添加 `economic_proxy` 字段。

计数口径（冻结）：

- `|commits(80f6643..HEAD)|` = `|prelude ∩ {P1,P2}|` + `9`（prelude 子集基数 0–2）。
- 排除序曲后的 subject 列表 **必须** 与上列 1–9 **逐字、同序** 相等。
- Task 10：**零** 额外 commit（含空 commit）；验证后工作树干净。

### 21.4 Changed-path allowlist

相对 base（`80f6643..HEAD` 并集），允许修改/新增的路径 **仅** 为：

1. **文档序曲专用（仅对应 §21.2 配对 commit 可引入）**：
   - `docs/superpowers/specs/2026-07-22-opportunity-economic-data-acquisition-design.md`（**仅** P1）
   - `docs/superpowers/plans/2026-07-22-opportunity-economic-data-acquisition.md`（**仅** P2）
2. **实现路径**：实现计划 Exact File Map 所列出的 opportunity-economic 相关文件（config flags、db DDL、`app/opportunity/economic_*`、metrics、repository hook、main/collections 接线、workflow **边界测试与必要的无字段 diff**、verifier/fixtures）。
3. **Task 9 条件**：`docs/IMPLEMENTATION_STATUS.md`（仅当 §17 全绿后由 Task 9 更新；**不是** 文档序曲）。

**禁止** 将设计规格或计划文档计入任意实现 commit 的 changed paths；二者 **仅** 可经由 P1/P2 出现在历史中。

**禁止出现在 diff 中**：

- 任何 dependency 清单变更（如 `requirements.txt`、`pyproject.toml` 依赖段、lockfile）
- 任何 Alembic 或 migration 脚本
- `frontend/` / `frontend-next/`
- `decision.py`、calibration 包生产逻辑（除被明确列为禁止修改）
- 新 API route 或响应字段
- 密钥、`.env*`（除既有 `.env.example` 且本闭环 **不**要求改之）
- 除 §21.2 配对序曲与上述 allowlist 以外的任何路径

### 21.5 无依赖 / 无 migration

- **无** 新第三方依赖。
- **无** Alembic revision、**无** down migration、**无** 手工 migration 目录新增。
- DDL **仅** 经现有 `init_db()` 双分支 additive SQL。

### 21.6 `compileall` 与 `PYTHONPYCACHEPREFIX`

Task 10（及本地等价门禁）执行 compileall 时 **必须** 将 `PYTHONPYCACHEPREFIX` 设为 **临时目录**，避免污染仓库树：

```powershell
# 从 repo root；临时目录示例
$env:PYTHONPYCACHEPREFIX = Join-Path $env:TEMP ("pycache-opportunity-economic-" + [guid]::NewGuid().ToString("N"))
python -m compileall -q backend/app backend/scripts backend/tests
Remove-Item -Recurse -Force $env:PYTHONPYCACHEPREFIX -ErrorAction SilentlyContinue
```

- **Expected**：exit code 0。
- **禁止** 在未设置 `PYTHONPYCACHEPREFIX` 时对上述路径 compileall 并留下 `__pycache__` 脏工作树后声称门禁通过。

### 21.7 其它 Task 10 验证（摘要）

- **Commit 历史审计（强制，非可选过滤）**：
  1. 枚举 `git log --format=%s 80f6643..HEAD`（或等价 old→new 顺序）。
  2. 对每一 commit：若 subject ∈ {P1,P2}，则 **必须** 用 `git show --name-only --pretty=format: <commit>`（或等价）验证 changed paths **恰好** 等于 §21.2 表中对应单路径；配对失败 → 门禁失败。
  3. 剔除通过配对的序曲后，剩余 subject **必须** 恰好为 §21.3 的九条且同序。
  4. **禁止**「删除所有 `docs:` subject」或「忽略 docs 路径」等宽松过滤代替配对证明。
  5. 全历史 changed-path 并集 ⊆ §21.4 allowlist。
- Tasks 1–9 聚焦测试全绿 → 完整 `backend` pytest 全绿 → offline verifier `RESULT: PASS`。
- 只读 Ruff（无 `--fix`）。
- `git diff --check` 无错误。
- 工作树干净；**local only，无 push**。

---

## 22. 结语（冻结声明）

本规格为 **冻结设计**：参数、枚举、hash framing、`schema_version`、独立性组、mode 三态、flags 默认与灰度、指标与验收集、post-link `enabled`/重建合同、内部投影边界、集成连接所有权、以及 §21 实现门禁均已闭合。任何扩展 factor、新 API、workflow 响应字段、校准接入或 UI，必须 **另立规格** 并显式声明对本文的差分；在差分规格生效前，实现与评审以本文为唯一准绳。

**文档状态：待用户书面规格复核。**
