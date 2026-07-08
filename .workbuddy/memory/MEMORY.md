# 项目记忆：Web3 Airdrop Alpha Agent System

## 工作模式约定
- 用户要求"先写文档，后写代码"。在获得明确"开始写代码 / 开始写 production repo"指令前，只做文档，不生成实现代码。
- 设计文档与 roadmap 已就绪；实现阶段的入手点是 `ENGINEERING_ROADMAP.md` 与 `docs/` 下四份规范。

## 项目定位
- 多智能体 Web3 早期项目识别 + 空投参与决策系统；不做交易执行、不碰用户资金。
- MVP 用规则引擎（无外部 LLM 依赖），可选 LLM 增强；SQLite；FastAPI；单页 HTML Dashboard（V2 换 Next.js）。

## 关键文档
- 设计文档：`Web3 Airdrop Alpha Agent System.md`
- 路线图：`ENGINEERING_ROADMAP.md`（v1.3，规划阶段）
- 规范：`docs/API_SPEC.md`、`docs/DEPLOYMENT.md`、`docs/FRONTEND_SPEC.md`、`docs/DATA_SCORING_DICT.md`、`docs/OBSERVABILITY.md`、`docs/SECURITY.md`、`docs/DATA_QUALITY.md`、`docs/OPERATIONS.md`、`docs/GLOSSARY.md`
- ADR：`docs/adr/`（ADR-001~005 独立成文 + README 索引 + 模板）

## Roadmap v1.2 设计阶段增量（2026-07-08，二次推进）
- 拆分 ADR 到独立目录 `docs/adr/`（5 份 ADR + README 索引 + 模板），Roadmap §18 改为索引摘要。
- §5.4 补 V2 新增表 DDL：feedback/events/quarantine/project_history/weight_changelog/narratives。
- §13 排期表重排：W1–W4 MVP、W5 LLM、W6 安全、W7–W8 V2 数据、W9 可观测、W10 数据层迁移、W11 反馈校准、W12+ V3；每行附验收门。
- 新增 `docs/OBSERVABILITY.md`：日志结构/事件命名/采样/敏感信息、Prometheus 完整指标目录、OpenTelemetry 追踪、9 条告警规则、Grafana 面板、容量预估。
- 新增 `docs/SECURITY.md`：STRIDE 威胁模型、密钥管理与轮换、API 鉴权（MVP/V2/V3）、输入校验、依赖/镜像安全、数据隐私与合规（GDPR/OFAC/保留期）、安全测试清单、事件响应 P0–P3 流程。
- 仍处规划阶段，未写实现代码；待"开始写 production repo"再进入实现。

## Roadmap v1.3 设计阶段增量（2026-07-08，三次推进）
- 新增 `docs/DATA_QUALITY.md`：6 维质量框架、P0/P1/P2 字段分级、Prometheus 指标、入库前/后检测、quarantine 处置 SLA、TTL 新鲜度、血缘、SLA 里程碑、治理流程。
- 新增 `docs/OPERATIONS.md`：值班角色、日/周/月检查项、部署发布回滚、8 类故障处理手册（run 失败/DB 锁/熔断/LLM 超预算/项目不增长/质量退化/健康检查/评分异常）、配置变更、备份恢复演练、监控面板、安全事件决策树、容量管理、紧急联系人。
- 新增 `docs/GLOSSARY.md`：业务术语（FARM/airdrop_signal/heat_score/timing 等）、技术术语（Agent/Orchestrator/PipelineState/dedup_key/reliability/quarantine 等）、角色术语、文档缩写对照、阶段术语。
- Roadmap §15 引用 OPERATIONS.md、§22 引用 DATA_QUALITY.md、§0 配套规范清单扩到 10 项；版本号 → v1.3。
- 文档体系成型，仍处规划阶段，未写实现代码。

## Roadmap v1.3 设计阶段第五轮复核（2026-07-08，用户更新文档后）
- 用户自行扩展了大量文档：ADR-006~010、CROSS_REF_CHECK、DATABASE_DDL、DESIGN_GAP_ANALYSIS、DESIGN_REVIEW_CHANGELOG、DESIGN_TOKENS、GOLDEN_TEST_CASES、PERFORMANCE_BENCHMARK、TASK_BREAKDOWN、USER_STORIES；Roadmap 扩到 §27（含用户系统 §25、API 版本管理 §26、集成 §27）。
- 用户做了 4 轮审查 + 交叉引用检查，已修复 18 项缺口中的 17 项。
- 第五轮复核：逐项核实 18 项缺口真实状态，修复最后 1 项（CONVENTIONS.md ruff 补 "S"），更新 DESIGN_GAP_ANALYSIS 各项状态标注，DESIGN_REVIEW_CHANGELOG 加第五轮记录。
- 结论：文档体系一致性已达进入实现阶段标准。剩余仅"有意留白"项（Agent 精确阈值、CI workflow、根目录工程文件），按里程碑在 W2/W4/W5 实现时固化。
- 仍处规划阶段，未写实现代码。
