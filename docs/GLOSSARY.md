# 术语表（Glossary）

> 本文档统一定义 Web3 Airdrop Alpha Agent System 涉及的业务、技术、角色术语，供跨文档对齐。新术语首次出现在其他文档时建议引用此处，避免歧义。
>
> 维护规则：术语变更需 PR review；废弃术语标记 `[deprecated]` 不删除，保留追溯。

---

## 1. 业务术语（空投/项目评估）

### Airdrop（空投）
项目方向符合条件的地址免费分发代币的行为。本系统目标是识别"有空投预期且值得参与"的项目。

### FARM / WATCH / IGNORE（评分标签）
本系统对项目的三档推荐标签（§7）：
- **FARM**：score ≥ 65（v1.1 默认；原 70），高确定性空投机会，建议积极交互
- **WATCH**：50 ≤ score < 65，有机会但不确定，持续观察
- **IGNORE**：score < 50，无价值或风险过高，不参与

### airdrop_signal（空投信号子分）
评分 6 子项之一，权重 0.20。基于 `raw_signals.has_points` 与 `airdrop_hint` 两项证据量化空投可能性（双真→100，仅其一→60，均否→20；见 DATA_SCORING_DICT §5.1）。

### narrative（赛道叙事）
评分 6 子项之一，权重 0.20。评估项目所处赛道的热度与时机，输出 `heat_score`（0–1）与 `timing`（early/peak/late）。

### heat_score（热度分）
0–1 浮点数，表示赛道当前热度。0=冷门，1=过热。由 Narrative Agent 综合 KOL 讨论量、协议增量、媒体报道等估算。

### narrative_stage（赛道阶段）
NarrativeResult 内部字段，取值 `early`/`growth`/`peak`/`mature`，表示赛道叙事成熟度。
- `early`：早期，红利窗口最佳
- `growth`：上升期，仍属早期红利
- `peak`：过热，红利递减
- `mature`：晚期/成熟，参与价值低

映射到 `timing` 时归为三态（详见 DATA_SCORING_DICT §5.2 映射表）。

### timing（时机判断）
Narrative Agent 输出，取值 `early`/`peak`/`late`（对齐 DATA_SCORING_DICT §5.2 时点系数）：
- early：早期/上升期（含 growth），红利窗口最佳。时点系数 1.0
- peak：过热，红利递减。时点系数 0.8
- late：晚期/成熟（含 mature），参与价值低。时点系数 0.5

> NarrativeResult 内部 `stage` 字段可保留 `growth`/`mature` 细粒度，但映射到 `timing` 时归为三态供评分使用。

### team（团队评估）
评分 6 子项之一，权重 0.15。评估团队可信度：匿名扣分、知名 VC 加分、过往成功项目加分。

### risk（风险评估）
评分 6 子项之一，权重 0.15。综合 sybil_difficulty（女巫防御难度）、farming_cost（交互成本）、token_risk（代币风险）。

### sybil_difficulty（女巫防御难度）
Risk Agent 输出 0–1：0=无防御（多账号易过），1=严防（多账号易被封）。越高越不利于多号参与。

### farming_cost（交互成本）
Risk Agent 输出 `low`/`medium`/`high`：交互所需资金/时间/技术门槛。low 最佳。

### token_risk（代币风险）
Risk Agent 输出 0–1：0=无风险（已上线/锁仓透明），1=高风险（VC 高占比/解锁压力/通胀高）。缺失走 0.5 中性。

### tokenomics（代币经济）
评分 6 子项之一，权重 0.15。评估代币分配合理性：VC 占比、团队占比、解锁压力。`risk = vc×0.4 + team×0.3 + unlock×0.3`。

### unlock_pressure（解锁压力）
Tokenomics Agent 输出 `low`/`medium`/`high`：近期代币解锁对价格的潜在冲击。

### competition（竞争度）
评分 6 子项之一，权重 0.15。同赛道项目数量归一化评分（见 `DATA_SCORING_DICT.md` §5.6），高竞争度稀释单项目空投价值。

### stage（项目阶段）
> ⚠️ **术语说明**：`stage` 在系统中用于两个不同上下文，需注意区分：
>
> **1. 项目阶段**（`projects.stage`）：项目生命周期阶段。
> - 取值：`testnet` / `mainnet` / `ideation`（以 ROADMAP §5.1 为准）
> - `testnet` 阶段参与成本最低、红利最大
>
> **2. 赛道阶段**（`NarrativeResult.stage`）：赛道叙事成熟度。
> - 取值：`early` / `growth` / `peak` / `mature`（DATA_SCORING_DICT §3.1）
> - 映射到 `timing` 字段时：`early`→`early`, `growth`→`early`, `peak`→`peak`, `mature`→`late`
>
> 两者同名但语义不同，通过上下文（表名/字段前缀）区分。

### RawProject（原始项目）
Collector Agent 产出的未评分项目对象，含 `id`/`name`/`sector`/`stage`/`raw_signals`。

### raw_signals（原始信号）
Collector 从各源采集的未加工证据：`has_points`（是否有点积分）、`airdrop_hint`（是否有空投暗示）、`sources[]`（来源列表含 reliability）等。评分公式仅使用 `has_points` 与 `airdrop_hint`（见 DATA_SCORING_DICT §5.1）。

### reason（评分理由）
每个评分结果必须含 ≥2 条人类可读的评分依据，正向/反向信号标注。是可解释性的核心。

### recommendation（参与建议）
`projects` 表与 `ScoreResult` 中 `recommendation` 字段当前与 `label` **恒等**（FARM→FARM / WATCH→WATCH / IGNORE→IGNORE），属冗余存储，保留是为 API 语义完整与 V3 个性化预留：V3 引入用户偏好/多钱包策略后，`recommendation` 可能偏离 `label`（如 label=FARM 但因用户风险偏好给出 WATCH 级建议）。MVP/V2 实现中二者始终相等，测试不得假设其分离。

### 决策推送（Outbound Notifier）`设计稿`
把系统内的评分决策变化与每日摘要经出站通道（Telegram Bot API / Discord Webhook）推送给用户的子系统。详见 ACTION_LOOP_DESIGN.md §2。

### 参与流水（Participation Tracker）`设计稿`
记录用户对每个项目「做到哪一步」的服务端任务状态机（plan + task 两级，按 `user_id` 隔离），替代前端的 localStorage 勾选。详见 ACTION_LOOP_DESIGN.md §3。

### 收益台账（ROI Ledger）`设计稿`
按项目记录参与投入（gas / 基础设施 / 时间）与产出（空投到账 / 未领取）的结构化账本；`airdrop_received` / `airdrop_missed` 事件作为权重校准的真值来源（`source=live|backtest` 分桶，不混算）。详见 ACTION_LOOP_DESIGN.md §4。

### 历史回测（Backtest）`设计稿`
把已知历史空投项目在「发币公告日 T0」**之前**公开可得的信息灌入评分决策引擎（规则引擎路径），检验当年是否会给出 FARM；用于引导权重校准的样本积累。用 T0 后信息构造样本视为无效。详见 ACTION_LOOP_DESIGN.md §4.4。

### 领取监控（Claim Watch）`设计稿`
对用户登记的自有钱包地址（admin-only）做链上事件匹配，命中且疑似代币到账时经决策推送提醒。启发式提示，不做金额确权。详见 ACTION_LOOP_DESIGN.md §5。

---

## 2. 技术术语（架构/工程）

### 评分决策引擎（Scoring Decision Engine）
本系统的评分子系统总称：由评分权重（Σ=1.0 启动断言，见 ADR-006）、LLM 增强（ADR-001 分级使用）与质量阈值（分析/置信度/缺字段降级）共同构成，决定项目如何被打分。默认打分路径为规则引擎；LLM 仅在配置 `OPENAI_API_KEY` 且开启功能开关后作为增强层叠加，失败自动回退规则引擎（ADR-001）。

### Agent（智能体）
本系统中指 pipeline 的一个处理节点，封装单一职责（Collector/Narrative/Team/Risk/Tokenomics/Scorer）。非 AI agent；MVP 为规则引擎，LLM 仅可选增强。

### Orchestrator（编排器）
协调 7 个 Agent 按 collect → analyze（并行）→ score 顺序执行的状态机。自研轻量实现（ADR-002），对齐 LangGraph 概念。

### PipelineState（流水线状态）
Orchestrator 中显式流转的状态对象（§6.1.1），含 project + 各 agent 结果 + errors + meta。Reducer 语义：`*_result` last-write-wins，`errors` list-extend。

### BaseAgent（Agent 基类）
所有 Agent 的抽象基类，定义 `run(context) -> result` 契约与可选 `llm_enhance()` 钩子（ADR-001）。

### dedup_key（去重键）
`f"{name_key}::{sector_key}"`，归一化后用于跨源去重。详见 §6.2.1。

### name_key / sector_key（归一化键）
- `name_key`：小写 → 去空格/连字符 → 剔除常见后缀 → NFKC
- `sector_key`：映射同义赛道到标准词表（如 `restake`/`restaking` → `Restaking`）

### reliability（来源可靠性分）
0–1 浮点，量化数据源可信度（§DATA_QUALITY §6）。冲突仲裁时取 reliability 最高的源。

### quarantine（脏数据隔离）
校验失败的外部数据暂存表（§5.4.3），不进主流程，待人工/规则修复后回填。

### run_id（运行 ID）
每次 `POST /run` 生成的 UUID，贯穿日志/指标/追踪，便于链路关联。

### weight_version（权重版本）
评分权重的版本标识，写入 `ScoreResult` 与 `project_history`，便于回测与溯源。

### LLM fallback（LLM 回退）
LLM 调用失败/超时/解析失败时自动回退规则引擎，不中断主流程（ADR-001）。

### circuit breaker（熔断器）
外部源故障率超阈值时熔断，期间直接走降级路径不发请求，窗口后半开探测恢复。

### golden set（黄金回归集）
`tests/golden/projects.jsonl` 维护的历史项目"输入→期望输出"快照，防止隐性评分漂移（§14.6）。

### backtest（回测）
用历史项目与候选权重重算评分，对比用户事后标注验证权重有效性（§7.9）。

### Memory system（记忆系统，V3）
跨 run 记忆项目演化与用户偏好的子系统，支持项目画像时间序列与个性化排序（§24.3）。

### DoD（Definition of Done，完成定义）
MVP 验收标准清单（§17），全部勾选才算 MVP 完成。

### ADR（Architecture Decision Record，架构决策记录）
架构级决策的正式记录，独立成文于 `docs/adr/`，四段式：背景→决策→理由→后果。

### Reducer（归约器）
LangGraph 概念，定义状态字段在 node 间的合并方式。本系统 `errors` 用 list-extend reducer 累积。

---

## 3. 角色与流程术语

### Primary on-call（值班负责人）
V2+ 响应 critical 告警的第一责任人，<30min 介入（OPERATIONS §1.1）。

### Data steward（数据管家）
负责 quarantine 处理、词表维护、数据质量治理的角色（OPERATIONS §1.1）。

### Release manager（发布经理）
决策发布窗口、授权回滚的角色（OPERATIONS §1.1）。

### postmortem（事后复盘）
P0/P1 事件后的无指责复盘，产出根因 + 改进项 + ADR/测试补强（SECURITY §9.2）。

### re-score（重评分）
对已有项目用最新数据重跑 analyze + score 的操作，不重新采集。幂等（§6.2.3）。

### force_refresh（强制刷新）
`POST /run?force_refresh=true` 绕过缓存强制重拉外部数据，V2 需鉴权。

---

## 4. 文档术语对照

| 缩写/术语 | 全称 | 定义位置 |
| --- | --- | --- |
| MVP | Minimum Viable Product | §1 |
| V2 / V3 | 版本 2 / 3 | §12 |
| SLA | Service Level Agreement | DATA_QUALITY §10 |
| RPO | Recovery Point Objective | OPERATIONS §6.4 |
| RTO | Recovery Time Objective | OPERATIONS §6.4 |
| TTL | Time To Live（缓存有效期） | §10.3 |
| PII | Personally Identifiable Information | SECURITY §7.2 |
| CVE | Common Vulnerabilities and Exposures | SECURITY §6.1 |
| SRI | Subresource Integrity | SECURITY §6.2 |
| STRIDE | 6 类威胁模型缩写 | SECURITY §2 |
| OTel | OpenTelemetry | `OBSERVABILITY.md` §4.2 |
| OTLP | OpenTelemetry Protocol | `OBSERVABILITY.md` §4.2 |
| RBAC | Role-Based Access Control | `ENGINEERING_ROADMAP.md` §25 / `SECURITY.md` §4.3 |
| JWT | JSON Web Token | ROADMAP §25.3.3 |
| API Key | API 密钥（可撤销） | ROADMAP §25.3.3 |
| API Deprecation | API 版本弃用（Deprecated 阶段） | ROADMAP §26.2 / ADR-009 |
| API Sunset | API 版本下架（Sunset 阶段） | ROADMAP §26.2 / ADR-009 |
| Breaking Change | 不向后兼容的 API 变更 | ROADMAP §26.4 |
| Migration Guide | V1→V2 迁移指南 | ROADMAP §26.7.4 |
| Sector Count Cache | 竞争度计数缓存（缓存同 sector 项目数） | ROADMAP §7.5.1 / ADR-010 |
| sector_counts | DB 物化表，存储各赛道实时项目计数 | ROADMAP §7.5.1 |
| Write-Through Invalidation | 写时失效策略：项目写入后使对应 sector 计数缓存失效 | ROADMAP §7.5.1 |

---

## 5. 阶段术语

### MVP（Minimum Viable Product）
最小可用版本。本系统 MVP 目标：单机 Docker 部署、规则引擎、7 Agent 跑通、单页前端预览。

### V2
生产化版本。引入真实数据源、LLM 增强、PostgreSQL、Next.js Dashboard、可观测性、鉴权。

### V3
规模化版本。多实例、用户系统（JWT+RBAC）、Memory 系统、多钱包策略、分布式调度、个性化推荐。

### admin / analyst / viewer（用户角色）
V3 引入的三种用户角色，见 ROADMAP §25.2：
- **admin**：全部权限，管理用户/API Key/配置
- **analyst**：查看项目、提交反馈、re-score、管理个人 API Key
- **viewer**：只读 Dashboard，不可触发 run/反馈

### anonymous_token（匿名令牌）
V2 引入的无状态 JWT，标识未登录用户。有效期 30 天，用于 feedback/events 关联用户行为，不要求注册。详见 ROADMAP §25.3.2。

### JWT（JSON Web Token，V3）
V3 用户认证方式。access token 15 分钟 + refresh token 7 天。payload 含 sub/role/iat/exp/jti。详见 ROADMAP §25.3.3。

### api_key（API 密钥，V3）
可撤销的长期密钥，bcrypt hash 存储，关联 user_id 和 role。用于 CI/CD 脚本调用。详见 ROADMAP §25.3.3。

### user_preferences（用户偏好，V3）
JSON 字段，含赛道偏好权重、风险容忍度、主题/语言设置。用于个性化排序。详见 ROADMAP §25.6。

### 行级数据隔离（Row-Level Isolation，V3）
用户私有数据按 user_id 自动过滤，后端中间件注入 `WHERE user_id = ?`。projects/logs 全局共享。详见 ROADMAP §25.5。
