# 项目设计文档查缺补漏报告

> **范围**：`docs/` 下全部设计文档（含 ADR）+ 根目录 `CONVENTIONS.md`、`docker-compose.prod.yml`
> **阶段**：仍处于设计阶段，未进入工程实现
> **原则**：只列出"会导致实现不一致、集成失败或验收歧义"的缺口；不列主观优化建议。
>
> **状态更新（2026-07-08 第五轮复核）**：本报告初版列出的 18 项缺口经 `DESIGN_REVIEW_CHANGELOG.md` 四轮修复后已**全部解决**。下文每项标注当前状态（✅ 已修复 / ⚠️ 已修复但需注意 / 📌 留白待实现阶段定）。本报告保留作为历史记录与实现前 checklist，不再作为"待办清单"使用。

---

## 总体评价

文档体系已非常完整：主方案、Roadmap、API/前端/数据/评分/安全/运维/可观测/数据质量/术语表/ADR 等 32 份文档相互引用，`CROSS_REF_CHECK.md` 确认章节引用 0 问题、Markdown 链接 0 失效，`DESIGN_REVIEW_CHANGELOG.md` 已做四轮一致性修复。当前无 P0/P1 级阻塞缺口，剩余仅 P2 级"实现阶段再定"的有意留白。

---

## 一、P0 级缺口（实现前必须统一，否则会导致数据/接口不一致）

### 1.1 数据库 Schema 多处不一致：权威 DDL 尚未唯一 ✅ 已修复
> **当前状态**：`ENGINEERING_ROADMAP.md §5.4.3` quarantine 已改为 `project_id/raw_data/failure_reason/severity/status/resolved_at`，与 `DATABASE_DDL.md §2.5` 对齐，并标注"权威 DDL 以 DATABASE_DDL.md §2.5 为准"。`events` 表（§5.4.2）已用 `event_type/detail`，`project_history`（§5.4.4）已加 `snapshot` 列。全表对齐完成。

同一表在两份文档中的列定义不同，实现侧无法判断以哪份为准。

| 表 | `ENGINEERING_ROADMAP.md` 中的定义 | `DATABASE_DDL.md` 中的定义 | 影响 |
|---|---|---|---|
| `quarantine` | `source`, `raw_data`, `failure_reason`, `reviewed`（`§5.4.3`） | `project_id`, `raw_data`, `failure_reason`, `severity`, `status`, `resolved_at`（`DATABASE_DDL.md` §2.5） | 脏数据隔离表字段不一致，无法直接写 `init_db()` |
| `events` | `event`, `payload`（`§5.4.2`） | `event_type`, `detail`（`DATABASE_DDL.md` §2.3） | 埋点表列名不一致，前后端/Event 写入代码会漂移 |
| `project_history` | 无 `snapshot` 列（`§5.4.4`） | 有 `snapshot` JSON 列（`DATABASE_DDL.md` §2.6） | V3 memory 系统依赖快照，但 Roadmap 未体现 |

**建议**：以 `DATABASE_DDL.md` 为 schema 权威，同步回写 `ENGINEERING_ROADMAP.md §5.4.x`，并在 Roadmap 中明确“DDL 以 `DATABASE_DDL.md` 为准”。

### 1.2 Golden 用例的 `reason_contains` 与 `DATA_SCORING_DICT.md` 的规则不自洽 ✅ 已修复
> **当前状态**：`GOLDEN_TEST_CASES.md` 已升 v1.2，按 `DATA_SCORING_DICT.md §8` 完整 reason 生成表统一修订全部 `reason_contains`。GT-001 用 "credible team"（非旧值 "strong team"），GT-002 用 "late narrative"（§8.1 已补该规则），GT-005 改为 "moderate airdrop signal"（has_points=True, airdrop_hint=False → 子分 60），GT-013 用 "heated narrative, peak timing"，所有用例 reason 与公式自洽。

`DATA_SCORING_DICT.md §8` 只给出了 reason 生成的示例规则，未给出完整决策表；而 `GOLDEN_TEST_CASES.md` 中的期望 reason 与现有规则示例冲突。这会导致 Scorer 实现后 golden 测试无法通过。

| 用例 | 当前期望 `reason_contains` | 规则示例中的写法 | 问题 |
|---|---|---|---|
| GT-001 | `strong team` | `team.score > 0.7 → "credible team"` | 关键词不对应 |
| GT-002 | `anonymous team` | `team.risk_level = high → "team risk: anonymous / prior failure"` | 期望字符串与规则示例不一致 |
| GT-002 | `late narrative` | 无“late narrative”生成规则 | 未定义 |
| GT-005 | `no airdrop signal` | `raw_signals` 全空才生成 `"no airdrop signal"` | 该用例 `has_points=True`，不应生成 |
| GT-013 | `high competition` | 只有 `competition` 低时生成 `"low competition"` | 未定义 |
| GT-015 | `high risk` | 无 `"high risk"` 生成规则 | 未定义 |
| GT-016 | `[]` | `reason` 必须 ≥2 条 | 与硬性规则冲突 |

**建议**：在 `DATA_SCORING_DICT.md §8` 补全“正向/反向/缺失”三类 reason 的完整决策表（含阈值、字符串常量），再按该表统一修正 `GOLDEN_TEST_CASES.md`。

### 1.3 数据血缘面板缺少 API 契约 ✅ 已修复
> **当前状态**：`API_SPEC.md §6` `GET /project/{id}` 响应已含 `lineage` 对象（`sources[]`、`agent_executions[]`、`weight_version`），前端可直接实现数据来源面板与 Agent 执行记录展示。

`DATA_QUALITY.md §9.3.1` 与 `FRONTEND_SPEC.md §3.2` 都要求项目详情页展示“数据来源/Agent 执行记录”，并声明 `GET /project/{id}` 返回 `lineage` 字段。但 `API_SPEC.md §6` 的 `GET /project/{id}` 响应中**没有 `lineage` 字段**，前端无法直接实现该面板。

**建议**：在 `API_SPEC.md` 中明确 `lineage` 对象结构（`sources[]`、`agent_executions[]`、`weight_version`），或说明前端需从 `raw_signals.sources` + `logs` 自行组装。

---

## 二、P1 级缺口（会影响前后端、运维、测试对齐）

### 2.1 `API_SPEC.md` 章节重复与端点缺失 ✅ 已修复
> **当前状态**：`API_SPEC.md` 章节编号连续无重复（§11 GET /audit、§12 /health、§13 POST /events、§14 POST /auth/anonymous、§15 GET /version、§17 版本管理策略）。`/events`、`/auth/anonymous`、`/version` 均有完整请求/响应样例。

- **版本管理章节重复**：存在 `§11 版本管理` 和 `§15 版本管理` 两段几乎相同的内容（`DESIGN_REVIEW_CHANGELOG.md #17` 已提到，但文件未完全合并）。
- **缺少 `/api/v1/events` 详细规格**：`§3` 端点总览列出了 `POST /api/v1/events`，但正文没有请求/响应示例。
- **缺少 `/api/v1/auth/anonymous`**：`ADR-008` 和 `FRONTEND_SPEC.md §9` 都要求 V2 匿名 token 端点，但 `API_SPEC.md` 未定义。
- **缺少 `/api/version`**：`§11` 提到版本元端点，但 `§3` 端点总览未列出，也无请求/响应样例。

**建议**：合并重复章节，按 `ENGINEERING_ROADMAP.md §26` 补全上述端点规格。

### 2.2 `/health` 响应字段不一致 ✅ 已修复
> **当前状态**：`API_SPEC.md §12` `/health` 响应已含 `config_version` 字段：`{status, db, projects, config_version}`。

- `API_SPEC.md §12` 定义：`{status, db, projects}`
- `OPERATIONS.md §5.1` 和 `ENGINEERING_ROADMAP.md §15.4` 要求返回 `config_version` 用于配置变更排查。

**建议**：在 `API_SPEC.md` 中把 `config_version` 加入 `/health` 响应。

### 2.3 `GET /api/v1/projects` 查询参数缺失 ✅ 已修复
> **当前状态**：`API_SPEC.md §5` 已补 `stage`（可多选）与 `search`（项目名称模糊匹配，大小写不敏感）参数。

- `FRONTEND_SPEC.md §3.1` 和 `USER_STORIES.md US-002` 要求支持 `stage` 筛选和关键词搜索。
- `API_SPEC.md §5` 当前只有 `label`、`sector`、`limit`、`order`。

**建议**：补充 `stage`（可多选/单选）和 `search`（项目名称模糊匹配）参数及其响应示例。

### 2.4 `POST /api/v1/feedback` 请求体注释错误 ✅ 已修复
> **当前状态**：`API_SPEC.md §9` `outcome` 字段注释已改为 `// airdropped|not_airdropped|pumped|dumped`（正确，非 signal 枚举）。

`API_SPEC.md §9` 示例中 `outcome` 字段的注释为 `// useful|useless|wrong_label|correct_outcome`，这是 `signal` 的枚举，不是 `outcome` 的枚举。`GET /api/v1/feedback` 的 query 参数表中已正确写 `outcome` 为 `airdropped|not_airdropped|pumped|dumped`，正文却写错。

**建议**：修正 `outcome` 字段注释为 `airdropped|not_airdropped|pumped|dumped`。

### 2.5 `ENGINEERING_ROADMAP.md §16.1` ADR 索引不完整 ✅ 已修复
> **当前状态**：`§16.1` ADR 索引已含 ADR-001~010 全部 10 份，与 `§18` 索引、`adr/README.md` 索引三方一致。

`§16.1` 的 ADR 索引表只列到 `ADR-007`，缺少 `ADR-008`（用户系统）、`ADR-009`（API 版本）、`ADR-010`（竞争度缓存）。而 `§18` 索引已完整包含 10 份 ADR。

**建议**：将 `§16.1` 与 `§18` 同步为完整 10 份 ADR。

### 2.6 `ENGINEERING_ROADMAP.md §5.4` 未覆盖全部 V2 新增表 ✅ 已修复
> **当前状态**：`§5.4` 已扩展到 §5.4.9。§5.4.7 以索引表形式覆盖 `audit_logs`/`llm_eval_changelog`/`metrics`（指向 DATABASE_DDL §2.7/§2.9/§2.10）；§5.4.8 `dedup_keys`、§5.4.9 `prompt_versions` 均有索引说明。全部 12 张表在 `DATABASE_DDL.md` 有完整 DDL。

`DATABASE_DDL.md` 已定义 `audit_logs`、`llm_eval_changelog`、`metrics` 等表，但 `ENGINEERING_ROADMAP.md §5.4` 只列出 `feedback`、`events`、`quarantine`、`project_history`、`weight_changelog`、`narratives`，未提及上述三张表。

**建议**：在 `§5.4` 增加索引小节，指向 `DATABASE_DDL.md` 对应章节。

### 2.7 `OBSERVABILITY.md` 业务面板 PromQL 引用未注册指标 ✅ 已修复
> **当前状态**：`OBSERVABILITY.md §3.2` 指标目录已注册 `airdrop_narrative_heat_score`（gauge, label=`sector`）与 `airdrop_feedback_total`（counter, label=`signal`）。业务面板 §6.2 引用与指标目录一致。

`§6.2.1` 业务面板示例：

| 面板 | PromQL 示例 | 问题 |
|---|---|---|
| 赛道热度 | `airdrop_narrative_heat_score` by `sector` | 指标目录 `§3.2` 未注册 `airdrop_narrative_heat_score` |
| 用户反馈 | `increase(airdrop_feedback_total[1d])` | 未注册 `airdrop_feedback_total` |
| 评分趋势 | `topk(10, airdrop_projects_in_db)` | `airdrop_projects_in_db` 是按 `label` 的 gauge，无法按项目 topk |

**建议**：
- 补充注册 `airdrop_narrative_heat_score`（gauge，label=`sector`）和 `airdrop_feedback_total`（counter，label=`signal`）。
- 评分趋势面板改用 `project_history` 数据或新增 `airdrop_project_score` gauge（label=`project_id`，注意基数控制）。

### 2.8 `CONVENTIONS.md` ruff 配置与文字说明不一致 ✅ 已修复（第五轮）
> **当前状态**：`CONVENTIONS.md §6.1` ruff `select` 列表已补 `"S"`（bandit 安全规则），与 `SECURITY.md §8.1` 要求对齐。配置含注释说明 S 系列用途。

`§8.1` 文字说明要求使用 `ruff` 的 `S` 系列（bandit 安全规则），但同节给出的 `pyproject.toml` 示例中 `select` 列表缺少 `S`：

```toml
select = ["E", "F", "I", "N", "W", "UP", "B", "SIM", "ARG", "RUF"]
```

**建议**：若确实需要安全规则，补 `"S"`；若不需要，删除文字说明中的 `S` 系列描述。

---

## 三、P2 级/澄清项（实现细节可后续补充，但当前文档留白）

### 3.1 核心 Agent 规则内部映射未完全定义 📌 留白待实现阶段定
> **当前状态**：`DATA_SCORING_DICT.md §5.7` 已补 Tokenomics `unlock_penalty` 映射、Risk `token_risk` 启发式公式、Team 多 flag 叠加公式、Narrative `SECTOR_PROFILE` 初值表。这些是 MVP 推荐初值，`DESIGN_REVIEW_CHANGELOG.md` 明确标注为"有意留白"，W2 实现时按 golden 用例固化。非阻塞项。

以下规则在实现前必须给出数值映射，否则 W2 无法写出确定性的 Scorer/Agent：

| 规则 | 当前状态 | 建议落点 |
|---|---|---|
| Tokenomics `unlock_penalty` 低/中/高 → 数值 | 只给出 `risk = vc×0.4 + team×0.3 + unlock_penalty×0.3` | `DATA_SCORING_DICT.md` 或 `ENGINEERING_ROADMAP.md §6.6` |
| Risk `token_risk` 启发式估算（MVP） | 仅说“基于 raw_signals 启发式” | 同上 |
| Narrative `SECTOR_PROFILE` 表/基础热度 | 只提到存在，未给出具体 sector 列表 | `ENGINEERING_ROADMAP.md §6.3` 或 seed 数据约定 |
| Team 多 flag 叠加公式 | 只写“多 flag 叠加截断” | `DATA_SCORING_DICT.md §8` 扩展 |

这些属于 `DESIGN_REVIEW_CHANGELOG.md` 中提到的“有意留白”，但建议在 W2 开工前以“规则表”形式固化，避免开发者理解偏差。

### 3.2 其他小项 ✅ 已修复
> **当前状态**：逐项核实如下。

| 文件 | 问题 | 当前状态 |
|---|---|---|
| `USER_STORIES.md` US-001 | `IGNORE` 用红色，`FRONTEND_SPEC.md` MVP 用灰色，`DESIGN_TOKENS.md` V2 用红色 | ⚠️ MVP 灰色/V2 红色的差异已在 `FRONTEND_SPEC.md §2` 注明"MVP 落地以本表为准，V2 以 DESIGN_TOKENS 为准，互不覆盖"，属有意为之 |
| `DATA_QUALITY.md §5.2` | 巡检 SQL 写法错误 | ✅ 已改为 `SUM(CASE WHEN field IS NULL THEN 1 ELSE 0 END) AS REAL) / COUNT(*)` |
| `API_SPEC.md` | 错误码表含 `409 Conflict`，但无端点使用场景 | 📌 留白：409 预留给 V2 并发 re-score 冲突，实现阶段按需启用 |
| `TASK_BREAKDOWN.md` W12-01 | 依赖 `W11-00` 不存在 | ✅ 已改为 `W11-05` |
| 根目录 | 缺少 `README.md`/`Dockerfile`/`docker-compose.yml` | 📌 留白：设计阶段不产出，W4 实现里程碑产出 |
| `ENGINEERING_ROADMAP.md §8.6` | 两个 `§8.6` 重复 | ✅ 已修正，当前仅 1 个 §8.6（其他端点） |
| `docker-compose.prod.yml` | 引用未存在路径 | 📌 留白：实现阶段补对应文件/目录 |

---

## 四、建议处理顺序

1. **P0 优先**：统一 `quarantine`/`events`/`project_history` 的权威 DDL；敲定 `DATA_SCORING_DICT.md` 的 reason 生成规则并修正 golden 用例；补充 `lineage` API 契约。
2. **P1 次之**：合并 `API_SPEC.md` 重复章节，补充缺失端点（`events`、`auth/anonymous`、`version`），修正 `/health` 字段、`/projects` 参数、`feedback` 注释、ADR 索引、Observability 指标注册、`CONVENTIONS.md` ruff 配置。
3. **P2 最后**：补齐 Agent 内部数值映射、修正 SQL 示例、调整颜色/章节编号等。

---

## 五、结论

**当前状态（第五轮复核后）**：设计文档体系已具备进入实现阶段的一致性。P0/P1 级缺口全部解决，剩余仅 P2 级"有意留白"（Agent 规则精确阈值、CI workflow 内容、根目录工程文件等），这些按 `DESIGN_REVIEW_CHANGELOG.md` 约定在对应里程碑（W2/W4/W5）实现时固化即可，不阻塞 W1 启动。

文档间交叉引用经 `CROSS_REF_CHECK.md` 验证 0 失效；评分公式经 `GOLDEN_TEST_CASES.md` 16 个用例验证自洽；schema 经 `DATABASE_DDL.md` 统一为权威源。**可进入实现阶段。**
