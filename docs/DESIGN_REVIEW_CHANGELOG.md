# 设计文档查缺补漏 Changelog

> 本文档记录 2026-07-08 对 `docs/` 全部设计文档（28 份，含 6 份 ADR）的查缺补漏修正。
> 触发：项目处于规划阶段，未进入工程实现。所有改动均为文档层面，未触及任何代码。
> 两轮审查：第一轮修明显错误/不一致；第二轮做系统性一致性 + 逻辑/实现层核查。

---

## 审查方法

1. 通读全部文档，建立跨文档引用图。
2. 用脚本按 `DATA_SCORING_DICT.md §5` 公式重算全部 golden 用例，比对 `expected`。
3. 交叉比对两处 DDL（ROADMAP §5 / DATABASE_DDL）、端点阶段归属、色值、字段字典与 API 响应。
4. 推演 agent 数据依赖与并行策略、排序 tie-break 的 SQL 可行性、MVP 种子数据能否产出非中性评分。

---

## 第一轮：明显错误与不一致（2026-07-08）

| # | 文件 | 问题 | 修正 |
|---|---|---|---|
| 1 | `GOLDEN_TEST_CASES.md` | 13 个用例 `expected.score/label` 与评分公式不符（GT-002/004/005/006/007/008/009/010/011/012/013/014/015）；GT-009 双缺失误判降级；部分 reason 与评分依据不自洽 | 按 §5/§12 公式重算回填；GT-009 改回 FARM（双缺失未达 ≥3 降级）；reason 修正；文档升 v1.1 |
| 2 | `docs/adr/`（缺失） | `adr/README.md` 与 ROADMAP 索引列 ADR-006，但文件不存在 | 新建 `ADR-006-weights-freeze.md`（权重初值冻结 + V2 校准闭环） |
| 3 | `ENGINEERING_ROADMAP.md §5.2` | `logs` 表 DDL 缺 `run_id` 列，但与 §6.1.1/§20.3/链路追踪全依赖 `logs.run_id` 矛盾 | 补 `run_id TEXT NOT NULL` + `idx_logs_run` 索引 |
| 4 | `API_SPEC.md` §5/§6/§10；`DATA_SCORING_DICT.md` §1 | `ProjectRecord` 响应缺 `confidence` 字段，但 FRONTEND_SPEC/USER_STORIES 要求展示 | 列表与详情响应均加 `confidence`；字段字典补行 |
| 5 | `API_SPEC.md` §3；`ENGINEERING_ROADMAP.md` §8；`TASK_BREAKDOWN.md` | 端点阶段归属混乱：`/insights`/`/audit`/`/events` 阶段标注不一致；缺 `/events` 端点；`/run` 响应字段（top_score/elapsed_ms）两处不符 | 端点总览加阶段列；补 `/events`；`/audit`/`/feedback`/`/events` 标 V2；`/insights` 标 MVP 基础聚合+V2 增强；补 W3-05 insights、W11-02b audit 任务 |
| 6 | `FRONTEND_SPEC.md` §2；`DESIGN_TOKENS.md` | 色值冲突（主色 #2563eb vs #6366F1 等） | 两份文档互相注明：MVP 单页用 FRONTEND_SPEC 色板，V2 Next.js 用 DESIGN_TOKENS 品牌色 |
| 7 | `ENGINEERING_ROADMAP.md` §8.1；`TASK_BREAKDOWN.md` W3-01；`GLOSSARY.md` | `/run` 响应字段两处不一致；`recommendation` 与 `label` 冗余无说明 | `/run` 响应统一含 top_score/elapsed_ms；GLOSSARY 加 `recommendation` 术语（当前与 label 恒等，V3 才分离） |
| 8 | `DATABASE_DDL.md` §2.1；`ENGINEERING_ROADMAP.md` §5.1；`DATA_QUALITY.md` §10/§8.3；`OBSERVABILITY.md` §3.2 | `projects` 表缺 `fetched_at` 列；新鲜度指标/ SLA 依赖它但 MVP seed 无此概念未豁免 | `projects` 表补 `fetched_at`（V2 填充，MVP NULL）；SLA/告警明确 MVP 不度量新鲜度 |

---

## 第二轮：系统性一致性 + 逻辑/实现层（2026-07-08）

| # | 文件 | 问题 | 修正 |
|---|---|---|---|
| 9 | `ENGINEERING_ROADMAP.md` §5.1 | `projects` 表 DDL 漏 5 个字段（`confidence`/`weight_version`/`raw_signals`/`meta`/`raw_signals_hash`），与 DATABASE_DDL §2.1 不一致 | 补回并对齐索引 |
| 10 | `DATABASE_DDL.md` §2.x | `narratives` 维表（`ENGINEERING_ROADMAP.md` §5.4.6 声明为 V2 表）全文无 `CREATE TABLE` 语句 | 补 `DATABASE_DDL.md` §2.6b `narratives` 建表 |
| 11 | `ENGINEERING_ROADMAP.md` §5.4 | `dedup_keys`/`prompt_versions` 在 DDL 有定义但 ROADMAP 未索引 | 补 §5.4.7/§5.4.8 说明（标注可选/对齐 LLM prompt 版本化） |
| 12 | `ENGINEERING_ROADMAP.md` §6.5 | Risk engine 的 `token_risk` 依赖 Tokenomics 输出，但 §6.8 声明 analyze 阶段 4 agent 并行 —— 数据依赖与并行策略矛盾 | 明确 Risk 独立从 raw_signals 启发式估算 `token_risk`，不阻塞并行；两 agent 各自产出供不同子分 |
| 13 | `ENGINEERING_ROADMAP.md` §6.2.4（新增）；`TASK_BREAKDOWN.md` W4-03 | MVP 种子数据只约定 `raw_signals`，但 4 个分析 agent 需 heat_score/team_score/vc_share 等字段；未约定则 MVP 全走缺失降级、confidence 极低、演示无价值 | 新增 §6.2.4 种子数据字段契约；W4-03 验收要求携带分析字段且 confidence=1.0 |
| 14 | `ENGINEERING_ROADMAP.md` §7.8；`DATA_SCORING_DICT.md` §11 | tie-break 第 3 级用 `meta.missing_count`（JSON 列内），无法在 SQL 层排序，与"排序必须在 SQL 层"矛盾 | 改用独立列 `confidence` 排序；建议冗余 `airdrop_signal_subscore` 列以支持 1–2 级 SQL 排序 |
| 15 | `ENGINEERING_ROADMAP.md` §19.6.3 | A/B 测试用 `hash(project_id)`，Python `hash()` 受 PYTHONHASHSEED 影响，分流跨进程不稳定 | 改用 `hashlib.md5(project_id)` 稳定哈希 |

---

## 已验证通过的交叉一致性

- ADR 索引（6 份）↔ 实际文件（6 份）一致。
- `projects` / `logs` 两处 DDL 字段现已完全对齐（含 run_id / confidence / weight_version / raw_signals / meta / raw_signals_hash / fetched_at）。
- 所有 V2 表（feedback/events/quarantine/project_history/weight_changelog/narratives/audit_logs/llm_eval_changelog/metrics/dedup_keys/prompt_versions）在 DATABASE_DDL 均有建表语句。
- 文档内 `.md` 相对链接无断链。
- 目录结构承诺的 9 个模块（scheduler/fetcher/seed/backtest/prompts/db/config/models/orchestrator）均有对应设计章节覆盖。
- 降级阈值自洽：`≥3 缺失` ⇔ `confidence < 0.5`，与 label 强制降档规则一致。

---

## 仍属有意为之的留白（非缺陷，实现阶段决定）

1. LLM prompt 模板完整文本（§19.2 仅定义 schema，W5 实现时填充）。
2. Next.js 组件级 TS 接口（FRONTEND_SPEC 仅到组件规格，V2 实现时定）。
3. 各 agent 规则引擎完整判定阈值表（§6 给公式，部分边界值在 W2 + golden 中固化）。
4. CI/CD workflow 文件具体内容（DEPLOYMENT/OPERATIONS 仅给片段）。
5. `re-score` 单项目时 competition 子分是否重算全库（设计取舍，V2 校准处理）。
6. `logs` 表 `AgentError.kind` 枚举未集中定义（散见 §6.1.3 / OBSERVABILITY，实现时统一）。

---

## 进入实现前的建议

- **W2（Scorer/Agent）启动时**：把规则引擎的精确阈值表补一份落到 `DATA_SCORING_DICT.md`，作为 golden 测试的权威锚点。
- **W4（seed）启动时**：按 §6.2.4 约定构造种子数据，确保 MVP 演示评分非中性（confidence=1.0）。
- golden 用例现已与公式自洽，可直接作为 Scorer 的契约测试基准。

---

# 第四轮审查：ADR-007~010 引入后的一致性（2026-07-08）

| # | 文件 | 问题 | 修正 |
|---|---|---|---|
| 16 | `GOLDEN_TEST_CASES.md` GT-004/005/006 | 边界用例 `reason_contains` 为空数组，但 DATA_SCORING_DICT §8 要求每个项目至少含 2 条 reason（FARM 含 ≥1 正向，IGNORE 含 ≥1 反向） | 根据输入数据推导合理的 reason 期望：GT-004 FARM 补 "strong airdrop signal" + "early narrative"；GT-005 WATCH 补 "early narrative" + "no airdrop signal"；GT-006 WATCH 补 "strong airdrop signal" + "early narrative" |
| 17 | `API_SPEC.md` | 章节编号跳号（§10→§11 数据模型→错误码），缺版本管理独立章节；§15 版本管理在速率限制之后，逻辑顺序不合理 | 新增 §11 版本管理独立章节（原 §15 内容前置），原错误码表改回 §12，原速率限制改 §13，原版本管理 §15 移除；章节编号连续 |
| 18 | `FRONTEND_SPEC.md` | 缺失 V2 设计特性：confidence 指示、反馈 UI、匿名 token 认证交互、数据来源面板、Agent 执行记录、Admin 审计页、用户偏好页等；字段映射表缺 `confidence` | 补全 `FRONTEND_SPEC.md` §3.2 置信度/反馈/来源面板/Agent 记录；新增 `FRONTEND_SPEC.md` §3.2a V2 反馈区、`FRONTEND_SPEC.md` §3.2b V3 扩展区、`FRONTEND_SPEC.md` §3.4 用户/Admin 页面；字段映射表补 `confidence`；`FRONTEND_SPEC.md` §7 交互补反馈/Auth/Admin 交互；`FRONTEND_SPEC.md` §9 技术实现补 V2 鉴权与 i18n 集成 |
| 19 | `Web3 Airdrop Alpha Agent System.md` | 主设计文档版本 v0.1，ADR 引用仅指向 §18；ADR-007/008/009/010 已集成到 Roadmap 但主文档未引用 | 升级 v0.2，引用指向 `docs/adr/` 目录含 ADR-001~010 |

## 第四轮审查验证通过的交叉一致性

- ADR-008（用户系统 §25）与 FRONTEND_SPEC.md：已补全 V2/V3 前台交互描述 ✅
- ADR-009（API 版本管理 §26）与 API_SPEC.md §11：版本管理独立章节已对齐 ✅
- ADR-010（竞争度缓存 §7.5.1）与 DATA_SCORING_DICT.md §5.6：引用链完整 ✅
- GOLDEN_TEST_CASES.md 所有用例 reason_contains 现与 DATA_SCORING_DICT.md §8 规则对齐 ✅
- FRONTEND_SPEC.md 字段映射表完整性：与 DATA_SCORING_DICT.md §1 字段字典一致 ✅

---

_本文档版本：v1.3 · 2026-07-08 · 新增第五轮（DESIGN_GAP_ANALYSIS 状态核对与收尾）——覆盖 #20~#21，确认前四轮 18 项缺口已全部解决。_

# 第五轮审查：DESIGN_GAP_ANALYSIS 状态核对与收尾（2026-07-08）

| # | 文件 | 问题 | 修正 |
|---|---|---|---|
| 20 | `CONVENTIONS.md §6.1` | ruff `select` 列表缺 `"S"`，与 `SECURITY.md §8.1` 要求 S 系列（bandit）冲突 | 补 `"S"` 并加注释说明用途 |
| 21 | `DESIGN_GAP_ANALYSIS.md` | 报告列出的 18 项缺口经四轮修复后已全部解决，但报告本身未更新状态，读者会误以为问题仍存在 | 每项加 ✅ 已修复/📌 留白 标注与"当前状态"说明；结论改为"可进入实现阶段" |

## 第五轮验证通过

- 逐项核实 `DESIGN_GAP_ANALYSIS.md` 18 项缺口的当前真实状态：17 项已在前四轮修复，1 项（CONVENTIONS ruff）本轮修复。
- `CROSS_REF_CHECK.md` 32 文件扫描 0 引用问题、0 链接失效。
- ADR 索引三方一致：`adr/README.md` ↔ `ROADMAP §16.1` ↔ `ROADMAP §18`，均含 ADR-001~010。
- `DATABASE_DDL.md` 12 张表 DDL 完整，`ROADMAP §5.4` 已索引全部表并标注"权威以 DATABASE_DDL 为准"。
- `GOLDEN_TEST_CASES.md` v1.2 全部 16 用例 reason 与 `DATA_SCORING_DICT.md §8` 规则自洽。
- API_SPEC 端点齐全（含 /events、/auth/anonymous、/version、lineage、config_version、stage/search 参数）。

## 结论

设计文档体系一致性已达进入实现阶段标准。剩余仅"有意留白"项（Agent 精确阈值表、CI workflow 内容、根目录工程文件），按里程碑在 W2/W4/W5 实现时固化即可。

---
