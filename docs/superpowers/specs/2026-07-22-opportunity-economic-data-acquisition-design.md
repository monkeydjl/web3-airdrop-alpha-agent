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

复用现有 DefiLlama、CoinGecko、CryptoRank collector 的既有采集与持久化路径，在 **CollectorResult / RawDiscovery 已成功写入之后**，由 **EconomicSnapshotWriter** 对每个 **schema-valid** 且命中 **raw_data 白名单** 的行，追加写入不可变经济快照；在内存中构造 **frozen NormalizedObservation**；在存在 `raw_projects(source_id, dedup_key).project_id` **精确绑定** 时生成 **immutable EvidenceRecord**；由新的 **economic resolver** 产出只读经济代理投影。

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
| `tvl_change_7d_ratio` | DefiLlama | 以 **冻结 fixture 合同** 规定的 provider unit 归一为 ratio（1.0=100%） | 对 unit 做猜测、启发式或运行时自适应 |

DefiLlama `change_7d`：fixture 合同必须先声明并断言 unit 与归一结果；若实际行与 fixture 合同不一致或 unit 无法按合同解析，该行 **schema-invalid**，不写 snapshot，**禁止猜测**。

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
        ↓  仅当 raw_projects(source_id, dedup_key) 精确 project_id 绑定
[immutable EvidenceRecord]
        ↓
[economic resolver → 只读经济代理投影]
        ↓
[workflow 安全投影：Evidence 可读字段；raw_snapshot_ref 不公开]
```

- **RawDiscovery.raw_data**：仅 provider-native 白名单字段行，**不是**完整 HTTP body。
- **NormalizedObservation**：内存 frozen 合同；**无** `items` / `identity_links` / `observation` 持久化表。
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
| `run_id` | daily = 含 UTC 日期的稳定 run 标识；manual = UUID |
| `source_id` | 与现有 collector / RawDiscovery 一致 |
| `dedup_key` | **原样保存** `RawDiscovery.dedup_key`；用于 `raw_projects(source_id, dedup_key).project_id` 精确绑定与 post-link **replay** |
| `provider_entity_id` | **明确取** `RawDiscovery.raw_id`；禁止改用展示名 / symbol / name |
| `payload_sha256` | 对键排序后的 canonical 白名单 payload JSON 的 SHA-256（§5.0） |
| `payload_json` | 仅白名单 raw_data 经 normalizer 后的 canonical 表示 |
| `collected_at` | 采集完成时间（UTC） |
| `source_url` | 去查询凭据后的 URL；禁止 query 中的 key/token |
| 唯一约束 | `(snapshot_id)` 全局唯一；同 run 重试依赖 `snapshot_id` insert-if-absent |

**dedup_key 硬门槛**：`RawDiscovery.dedup_key` 缺失、空字符串或仅空白 → 该行 **schema-invalid**，**不写** snapshot，记 `opportunity_economic_snapshots_total{result="schema_invalid"}`。

**禁止** 存：API key、Authorization、钱包地址、用户身份、完整 HTTP 响应 envelope。

---

## 5. 标识与幂等

### 5.0 `schema_version` 与 SHA-256 framing（冻结）

- **`schema_version` 唯一合法值**：`opportunity-economic-snapshot-v1`。
- **通用 hash framing**（`snapshot_id` 与 `evidence_id` **均**使用，仅组件列表不同）：
  1. 按公式参数 **固定顺序** 组成 JSON **字符串数组**（每个分量已是字符串；数值类分量先规范为字符串再入组）。
  2. 序列化：`json.dumps(array, ensure_ascii=False, separators=(',', ':'))`，编码 **UTF-8**。
  3. **禁止** Unicode 非规范替代表示、禁止数字的非规范替代（科学计数法、前导零、`+` 前缀、非半偶入后的多余形式等）；分量字符串必须已是 canonical 形态。
  4. 对 UTF-8 字节做 **SHA-256**，输出 **小写 64 位 hex**。
- **`payload_sha256`**：对白名单 payload 对象做 **键排序**（递归对象键字典序）后的 canonical JSON（同样 `ensure_ascii=False`、`separators=(',', ':')`、UTF-8），再 SHA-256 小写 64 hex。该 hex 字符串作为 `snapshot_id` 公式中的 `payload_sha256` 分量。

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

- **同 run 重试**：相同五元组 → 相同 `snapshot_id` → **insert-if-absent**（主键冲突视为成功，返回已有行）；不产生第二行。
- **跨日相同 payload**：`run_id` 含新的 UTC 日期 → **必须**产生新 `snapshot_id` 与新历史行（审计「当时所见」）。
- **manual trigger**：`run_id` 为 UUID，与 daily 命名空间隔离，但仍走同一 Writer 与同一 hash 公式。

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

- 无 `project_id` 绑定时 **不生成** Evidence，**保留** snapshot（绑定键为 snapshot 上保存的 `source_id` + `dedup_key`）。

### 5.3 经济证据幂等写入（不改通用 `add_evidence`）

- **不改变** 通用 `add_evidence` 的既有冲突语义与调用约定。
- **新增** 经济证据专用 repository 方法（名称实现自定，语义冻结为 **insert-if-absent by `evidence_id`**）：
  - SQLite 与 PostgreSQL **均**以 `evidence_id` 主键冲突为成功路径：返回 **已有等价行**，metrics 记 `duplicate`。
  - 若同 `evidence_id` 已存在但 **内容与待写 Evidence 不等价**（factor 值、`value_type`、`independence_group`、`raw_snapshot_ref`、`source_grade`、`verification_status` 等合同字段任一不同）：**必须失败**（抛错/记错误 metrics），**禁止**静默覆盖、禁止更新就地改写。
  - replay 与同 run 重试均只走该方法，不走会改变通用冲突语义的路径。

### 5.4 重放边界

| 场景 | 行为 |
|------|------|
| 同 run 采集失败重试 | 不重复外部请求原则由上层 scheduler 保证；Writer 对已成功 snapshot 幂等 insert-if-absent |
| project pipeline 事后建立 `project_id` | **post-link replay**：用 snapshot 上的 `source_id`+`dedup_key` 查 `raw_projects` 精确 `project_id`，再 Observation→Evidence；不重新请求 provider |
| flag 关闭 | 停止 Writer / Evidence emit / resolver 挂载；历史表保留；legacy/workflow 字节级不变 |
| payload 字段缺失 | 该 factor 不写 0；不生成该 factor 的 Evidence |
| 无 `dedup_key` | schema-invalid；无 snapshot |

---

## 6. 身份绑定（唯一允许路径）

- **只接受** `raw_projects(source_id, dedup_key).project_id` 的 **精确绑定**；`dedup_key` 来自 snapshot 列原样值。
- 无绑定：snapshot 保留；**不入** Evidence；待 project pipeline 建立 `project_id` 后 **replay**。
- **严禁** symbol / name / slug fuzzy match、编辑距离、别名表猜测。
- 代码路径 **不得** 实现「尝试 fuzzy 再拒绝」分支；禁止 fuzzy 由 **测试** 证明（仅精确查询存在/不存在）。
- 身份解析指标：`opportunity_economic_identity_resolution_total{source,result}`，`result` **仅** `linked` \| `unlinked`（§13）。

---

## 7. EvidenceRecord 合同（严格沿用枚举）

### 7.1 枚举冻结

| 字段 | 允许值 | MVP 取值规则 |
|------|--------|----------------|
| `source_grade` | 仅 `A` / `B` / `C` / `D` / `U` | MVP 固定 **`C`** |
| `verification_status` | 仅 `verified` / `partially_verified` / `unverified` / `conflicted` / `invalidated` | **仅当** schema 通过 **且** 精确 `project_id` 绑定时生成 **`verified`** Evidence；否则不生成 |
| `source_type` | 本闭环使用 | DefiLlama：`public_aggregator`；CoinGecko / CryptoRank：`public_market_data` |
| `independence_group` | 字符串 | DefiLlama：`defillama-protocols`；CoinGecko 与 CryptoRank：**同为** `market-aggregators`（**不得**计为两个独立证明） |
| `raw_snapshot_ref` | opaque | `econ-snapshot:<snapshot_id>`；workflow **不公开** |
| `independence_group` 字段 | 必填 | 供 resolver 组内/组间规则使用 |
| `value_type` | 见 §7.2 | 与 factor 一一对应，禁止混用旧 number normalizer 产出 |

### 7.2 冻结 factor 全集与 `value_type`

| factor_key | 来源 | EvidenceRecord.value_type | 值形态与 normalizer |
|------------|------|---------------------------|---------------------|
| `tvl_usd` | DefiLlama | `string` | usd：canonical Decimal string，scale=8，`ROUND_HALF_EVEN` |
| `tvl_change_7d_ratio` | DefiLlama | `string` | ratio：canonical Decimal string；**1.0 = 100%**；来源映射见 §2.1 |
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

1. 校验 `dedup_key` 非空；`provider_entity_id := RawDiscovery.raw_id`；校验 provider schema（白名单键、§2.1 来源字段、专用 normalizer、`value_type`）。
2. 任一步失败 → 只记 `collection_logs` / `data_sources` / metrics（`schema_invalid` 等）；**跳过**该行，不写 snapshot。
3. 成功 → 构造键排序 canonical payload → `payload_sha256` → `snapshot_id` → **insert-if-absent**；写入列含 **原样 `dedup_key`**。
4. 构造内存 **frozen NormalizedObservation**：携带 `snapshot_id`、`source_id`、`dedup_key`、`provider_entity_id`、规范化 factor map（含 `value_type`）、`collected_at`、`source_url`（已消毒）。
5. 若 `OPPORTUNITY_ECONOMIC_EVIDENCE_EMIT_ENABLED` 为 true：用 `(source_id, dedup_key)` 精确查 `project_id`；有则经 §5.3 方法生成 Evidence；无则 `identity_resolution=unlinked` 并结束该行。

### 8.2 NormalizedObservation

- **仅内存**；不落库。
- frozen：创建后字段不可变；供 Evidence 构建与 offline verifier 对齐。

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

Resolver **仅**在 `OPPORTUNITY_ECONOMIC_RESOLVER_ENABLED=true` 时向投影层输出。

---

## 10. 只读经济代理投影与 `economics_data_mode`

### 10.1 投影

只读结构（内部服务对象 / workflow 安全视图）包含：

- 各 factor 的 resolved 值或 `unknown`
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

---

## 11. 调度、Trigger、API 与 UI

| 能力 | MVP 规则 |
|------|----------|
| 每日调度 | 挂到现有 scheduler 同一 collection 任务之后置 Writer |
| 手动 trigger | 复用现有 collections trigger 接口与鉴权 |
| 状态/健康 | 复用现有 logs / health；本闭环额外只暴露 Prometheus 指标（§13） |
| 新 API | **零** |
| 前端 / 管理页 | **零改动** |
| workflow | 仅安全投影 Evidence 业务字段；**禁止**下发 `raw_snapshot_ref` |
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
| `OPPORTUNITY_ECONOMIC_RESOLVER_ENABLED` | `false` | `false` 时不向投影层输出 economic mode/factor |

**灰度顺序（强制）**：`snapshot` → `evidence` → `resolver`。
即：不得在 `OPPORTUNITY_ECONOMIC_SNAPSHOT_ENABLED=false` 时开启 evidence/resolver；不得在 `OPPORTUNITY_ECONOMIC_EVIDENCE_EMIT_ENABLED=false` 时开启 resolver 依赖本闭环 Evidence 的路径。验收必须覆盖 **全部新 flag 默认 false** 时 legacy/workflow **字节级不变**。

回滚：将上述 flag 置回 `false` 并卸下调度挂载；表与历史保留。

### 12.2 局部失败

- 单 provider / 单行 schema 失败：**不影响** 其他行、其他 source 的 snapshot。
- Evidence 写入失败（含同 id 内容冲突）：记录 metrics + logs；**不删除** 已成功 snapshot；**不**静默覆盖。
- Resolver 冲突：该 factor 投影 `unknown`，**不**回写篡改 Evidence。

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

---

## 14. 安全

- API key 与请求凭据：**不得**进入 payload、log、hash 输入、`source_url`。
- snapshot **只**存 raw_data 白名单与 §4 列；含原样 `dedup_key`、`provider_entity_id=raw_id`。
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
| RawDiscovery.raw_data 白名单行 | 持久化（既有） | 既有规则 |
| opportunity_economic_snapshots | 持久化新表 | 行级不可变；只追加；含 `dedup_key` |
| NormalizedObservation | 内存 frozen | 不可变 |
| EvidenceRecord | 既有 Evidence 存储路径 + 经济专用 insert-if-absent | immutable；同 id 内容冲突失败 |
| 经济代理投影 | 只读计算视图 | 随 Evidence 集合重算 |

Decimal（`value_type=string` 的 usd/supply/ratio）：**scale 8**，`ROUND_HALF_EVEN`，序列化为 **canonical 十进制字符串**（无科学计数法；与本闭环专用 normalizer 强制统一，不经旧 int/float number normalizer）。

Hash：一律 §5.0 framing；`schema_version` 恒为 `opportunity-economic-snapshot-v1`。

---

## 17. 测试与 Offline Verifier

### 17.1 必须覆盖的验收用例

1. **跨日同 payload 两快照**：相邻 UTC 日、相同白名单 payload → 两个不同 `snapshot_id`，两行历史。
2. **同 run 幂等**：同一 `run_id` 重复 Writer → snapshot 行数不增；metrics `duplicate`。
3. **post-link replay**：先 unlinked snapshot（有 `dedup_key` 无 `project_id`），后写入精确 `raw_projects` 行，replay 后 Evidence 出现且 `evidence_id` 稳定。
4. **无 fuzzy match**：仅有 symbol 相同、无 `raw_projects(source_id,dedup_key)` 精确行 → 零 Evidence；`identity_resolution=unlinked`；代码路径无 fuzzy 分支（静态/测试证明）。
5. **昨日今日不冲突**：同 project 连续两日不同 price → resolver 取最新未过期，**不** conflict。
6. **proxy 不进 direct economics**：仅有闭环 Evidence 时 `_DIRECT_ECONOMICS_FACTORS` 完整性仍为假；`economics_data_mode` 不得为 `DIRECT_AVAILABLE`。
7. **人工 direct FARM 不降级**：既有 direct Evidence 场景下 decide/FARM 路径与 flag 全 false 时一致。
8. **flag 默认 false**：全部 `OPPORTUNITY_ECONOMIC_*` 默认关闭时 legacy score/label 与 workflow 关键路径 **字节级不变**。
9. **SQLite / PG DDL 等价**：`init_db()` 双分支均可幂等创建同名表与同逻辑约束。
10. **network-free verifier**：离线夹具重放 raw_data → 断言 `schema_version`、hash framing、`snapshot_id`/`evidence_id`、mode、`market-aggregators` 不双计。
11. **无 dedup_key → schema-invalid**：不写 snapshot。
12. **CoinGecko ratio**：仅 `price_change_percentage_24h/100`；夹具含绝对美元 `price_change_24h` 时不得被采用。
13. **CryptoRank ratio**：`percent_change_24h`/`7d` 除以 100。
14. **DefiLlama change_7d**：fixture 合同 unit 满足则归一 ratio；不满足 → schema-invalid。
15. **evidence 同 id 内容冲突**：必须失败，不得覆盖。
16. **专用 normalizer**：usd/supply/ratio 为 string；`market_rank` 为 number；`chains_json` 为排序数组 json；`token_unlisted_proxy` 为 bool。
17. **灰度顺序**：仅 snapshot 开 / snapshot+evidence / 三者全开 的分层行为符合 §12.1。
18. **source flag 与既有 provider enabled 双真**：仅一侧为 true 时该 source 不写 snapshot。

### 17.2 Offline Verifier 职责

- 输入：冻结 fixture（无网络），含 DefiLlama `change_7d` unit 合同。
- 校验：§5.0 hash、白名单剥离、凭据不泄漏、ratio 语义与 §2.1 映射、缺失不写 0、CG/CR 不双计独立组、mode 三态、`dedup_key`/`raw_id` 列、value_type 与专用 normalizer。
- 退出码：合同破坏非 0。

---

## 18. 与现有模块的集成边界

| 模块 | 集成方式 |
|------|----------|
| DefiLlama/CG/CR collector | 只读其已持久化 RawDiscovery；不改采集 URL 语义 |
| scheduler / collections trigger | 复用入口；后置 Writer |
| collection_logs / data_sources | 失败与状态复用 |
| Evidence 存储 | 通用 `add_evidence` 语义不变；经济路径走专用 insert-if-absent |
| decide / score / label | 不引用 proxy 门槛；不读 raw_snapshot_ref |
| workflow | 只读安全投影 |

---

## 19. 实施顺序（无分叉算法）

1. `init_db()` 双分支 additive DDL（含 `dedup_key`、`provider_entity_id` 列）。
2. §5.0 hash framing + 专用 normalizer + §2.1 字段映射。
3. EconomicSnapshotWriter + metrics（依赖 `OPPORTUNITY_ECONOMIC_SNAPSHOT_ENABLED` 与 source 双 flag）。
4. 精确绑定查询 + 经济专用 Evidence insert-if-absent（依赖 `OPPORTUNITY_ECONOMIC_EVIDENCE_EMIT_ENABLED`）。
5. economic resolver + `economics_data_mode`（依赖 `OPPORTUNITY_ECONOMIC_RESOLVER_ENABLED`）。
6. scheduler/trigger 后置挂载；**灰度严格** snapshot → evidence → resolver。
7. 单元/集成/双库 DDL/offline verifier 全绿（含 §17.1 全部用例）。
8. 回滚只关 flag；表与历史保留。

---

## 20. 验收签字清单（书面复核用）

复核人确认下列语句均为 **是** 后方可进入实现：

- [ ] MVP 仅新增 `opportunity_economic_snapshots`；无 Alembic/down migration；列含原样 `dedup_key`，`provider_entity_id=RawDiscovery.raw_id`。
- [ ] `schema_version=opportunity-economic-snapshot-v1`；hash 使用 §5.0 framing；跨日/同 run 幂等正确。
- [ ] snapshot → 内存 Observation → Evidence → 只读投影链路完整；经济 Evidence 专用 insert-if-absent；同 id 内容冲突失败。
- [ ] 三 provider 能力、§2.1 映射与 factor/`value_type` 表与本文一致；专用 normalizer；无钱包/积分/解锁/空投。
- [ ] 身份仅精确 `project_id`；禁止 fuzzy；identity result 仅 `linked`|`unlinked`。
- [ ] CG 与 CR 同属 `market-aggregators`。
- [ ] proxy 永不进入 direct economics；不改 decide/calibration/workflow 状态机；不改通用 `add_evidence` 冲突语义。
- [ ] 零新 API、零前端；`raw_snapshot_ref` 不公开。
- [ ] 全部 `OPPORTUNITY_ECONOMIC_*` 默认 false；source 双 flag；灰度 snapshot→evidence→resolver。
- [ ] Prometheus 指标与 result 闭集符合 §13。
- [ ] 安全：凭据不进 payload/log/hash/source_url。
- [ ] 验收用例 §17.1 全部强制。
- [ ] 首期成功口径仅为「可审计经济代理闭环」，不声称真实稀释/估值/奖励补齐。
- [ ] 文档状态仍为「待用户书面规格复核」。

---

## 21. 结语（冻结声明）

本规格为 **冻结设计**：参数、枚举、hash framing、`schema_version`、独立性组、mode 三态、flags 默认与灰度、指标与验收集均已闭合。任何扩展 factor、新 API、校准接入或 UI，必须 **另立规格** 并显式声明对本文的差分；在差分规格生效前，实现与评审以本文为唯一准绳。

**文档状态：待用户书面规格复核。**
