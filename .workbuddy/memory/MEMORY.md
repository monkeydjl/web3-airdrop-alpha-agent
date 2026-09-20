# 项目记忆：Web3 Airdrop Alpha Agent System

> 2026-09-04 · 分支 `feat/action-loop-m2`，远程默认分支为 `master`。本记忆于 2026-09-04 精简改写，**改写前的详细踩坑版仅存于 git 历史**（`git show 5a32a0e:.workbuddy/memory/MEMORY.md`），排查历史问题时优先取回原版。

## 红线与验证门禁
- 只提供 FARM/WATCH/IGNORE 决策参考；禁止交易、代签、自动 farming、托管资金/KYC。真相源：代码与 `docs/` 优先；禁读写 `.env`/`.env.*`（`.env.example` 除外）。
- 每次 commit/reset 后运行 `sh .git/sync-head-ref.sh`；远程比对用 `git ls-remote --heads origin <branch>`，不要信陈旧本地远程 ref。
- 后端命令统一用 `backend/venv/Scripts/python.exe -m ...`；pytest 加 `--no-cov -p no:cacheprovider`。CI 是环境受限删除类测试的最终判定，勿改断言迁就沙箱。
- DB 新列必须同步双言 DDL、`init_db` 补列、Alembic、`DATABASE_DDL.md` 与回归测试；路由显式级联，无 SQL 外键。
- 全仓扫描必须以仓库根目录为 cwd，使用 `git ls-files --full-name`，并断言覆盖关键目录。事件名文档必须先从代码确认，调用点保留字面量；文档枚举/事件标识不要用反引号包裹。
- `.gitignore` 需覆盖 `.env`、`.env.*`、`.env copy/backup/_bak/-old` 及密钥文件，同时保留 `.env.example` 可见；用 Git 自身检查规则。
- `except` 清理动作套 `contextlib.suppress`；异步锁惰性创建；测试避免裸属性表达式（Ruff B018）。
- `data/pytest_tmp` 必须排除全仓编码扫描。`${VAR:?中文提示}` 是 Shell 必填参数语法，不应被乱码检测器误报。

## 已交付与当前语义
- M1 推送审计/参与流水；M2/F3 ROI、6 API、Portfolio、live/backtest 分桶回测。校准门槛 live ≥200、FARM ≥30。
- ADR-015 资格门：score 与 veto 分离，`already_launched` 优先于参与路径，FARM→IGNORE/WATCH；参与路径为 testnet、points、task_portal、explicit_airdrop_mention。新增 `explicit_no_airdrop` 否决项（ADR-015 §2 落地），官方明确否认空投时 FARM→IGNORE 且信号分压至 ≤10。sector/competition 使用规范化查表与 `canonical_sector_counts()`，未知 sector 保留原值并告警。
- 多钱包策略建议（US-019 / Roadmap W12-01）：`app/services/multi_wallet_strategy.py` + `GET /api/v1/projects/{id}/multi-wallet-strategy` + 前端 `MultiWalletStrategyPanel`；基于 sybil_factor、部署阶段与 Perp 成本画像自适应输出推荐钱包梯度（single/cluster/medium）、资金预算预估、每周时间投入与 4 项防女巫隔离准则（资金零关联、时间离散化、环境隔离、行为差异化）。严格坚守红线：纯建议辅助，无私钥管理与自动化代投。
- V3 Memory 系统（Roadmap §24.3 / §25.5.3 / W12-02）：
  - 项目演化时间轴（`project_history`）：`app/services/project_memory.py` + `GET /api/v1/projects/{id}/timeline` + 前端 `ProjectTimelinePanel`；计算评分时序走势（rising/falling/stable/insufficient_data）、StdDev 波动率、阶段跨越里程碑（如 testnet→mainnet），生成 LLM 演化记忆上下文。
  - 用户偏好画像（`user_profile`）：`app/services/user_memory.py` + `GET/DELETE /api/v1/user-profile`；从用户全域多维交互（feedback/interactions/watchlist/project_skips）自适应推断赛道偏好权重向量与风险偏好；支持 `GET /api/v1/projects?personalized=true` 动态重排序（不污染底层基准评分）；支持 GDPR 合规一键清除画像。
- V3 异常检测与质量告警引擎（Roadmap §12 / §22 / TASK_BREAKDOWN W12-04）：
  - 核心服务：`app/services/anomaly_detection.py` + `GET /api/v1/anomalies` + 前端 `AnomalyDetectionPanel`（集成在 `/ops` 运维台）；
  - 覆盖评分漂移（均值偏离基线 >15 分、FARM 占比 >40% 或归零、0 分激增 >30%）与数据质量（P0 核心字段 100% 完整性违背、P1 ≥80%、隔离区积压超限 >50、采集源 72h 时效性超时）；
  - 聚合总体健康状态（healthy / warning / critical），输出 structlog `quality.scan.*` 事件与 60s 缓存。
- V3 用户认证子系统（ADR-008 §V3 / Roadmap §25.3.3 / TASK_BREAKDOWN W12-06）：
  - 架构设计：基于 JWT (HS256) + bcrypt (cost factor 12) + Refresh Token 多端会话持久化 + JTI 吊销黑名单机制；
  - 核心模块：`app/auth.py` + `app/repositories/user.py` + `app/routers/v1/auth.py` + Alembic `0011_user_auth_tables.py`；
  - API 矩阵：`POST /auth/register`（首个用户自举为 admin，后续默认 viewer）、`POST /auth/login`、`POST /auth/refresh`、`POST /auth/logout`（单设备吊销）、`POST /auth/logout/all`（全设备登出）、`GET /auth/me`（当前身份）；
  - 向后兼容：保留 V2 HMAC 匿名 Token 格式与管理员 API Key 鉴权，写操作端点总数从 37 扩展至 42，门禁全部通过。
- V3 RBAC 中间件与权限控制（ADR-008 §2 / Roadmap §25.2, §25.7 / TASK_BREAKDOWN W12-07）：
  - 四角色模型：`admin`（全局全部权限）、`analyst`（可读写 feedback/events/watchlist/interactions 及 re-score，禁止 admin 系统运维与写操作）、`viewer`（只读仪表盘/AI简报/通知，禁止写操作与 re-score/run）、`anonymous`（受限读写公开与交互端点）；
  - 中间件实现：`app/auth.py:check_role_permission` + `require_role` 依赖注入 + `APIKeyMiddleware.dispatch` 统一角色边界拦截；违规返回 403 `FORBIDDEN` 并记录 `auth.rbac_denied` 审计日志；
  - 兼容与修复：`GET /auth/me` 适配匿名 token 返回 401，178 项测试全量通过。
- V3 用户偏好子系统（ADR-008 §25.6, §25.10 / TASK_BREAKDOWN W12-08）：
  - 数据模型：遵循 ROADMAP §25.6 JSON 规范，持久化存入 `users.preferences`；涵盖赛道偏好权重、风险偏好容忍度、偏好阶段、通知配置与主题语言，支持额外属性自由扩展；
  - API 矩阵：`GET /user/preferences`（默认值回退）、`PUT /user/preferences`（全量替换）、`PATCH /user/preferences`（字段级覆盖与字典浅合并）、`DELETE /user/preferences`（重置回退，GDPR 隐私遗忘权）；
  - 鉴权与隔离：仅限认证用户（JWT / API Key），匿名访问返回 401，多用户严格行级隔离；写端点从 42 扩展至 45，全量安全与一致性门禁 100% 通过。
- V3 API Key 管理与可撤销凭证（ADR-008 §25.3.3, §25.10 / TASK_BREAKDOWN W12-09）：
  - 架构设计：高安全与高性能 $O(1)$ 检索架构，采用 `ak_{key_id_hex}_{secret}` 格式，数据库仅存储 bcrypt 哈希（cost factor 12），明文密钥仅在创建时展示一次；
  - 核心模块：`app/repositories/api_key.py` + `app/routers/v1/api_keys.py` + Alembic `0012_api_keys_table.py`；
  - API 矩阵：`GET /api-keys`（脱敏列表，admin 可 `?all=true`）、`POST /api-keys`（非 admin 越权防护）、`DELETE /api-keys/{key_id}`（按用户隔离撤销）；
  - 中间件集成：`APIKeyMiddleware` 扩展支持动态 API Key 鉴权并自动更新 `last_used_at`；写端点从 45 扩展至 47，全量门禁与测试 100% 通过。
- V3 行级数据隔离（ADR-008 §4 / Roadmap §25.5 / TASK_BREAKDOWN W12-10）：
  - 隔离边界：用户私有数据（`feedback`、`events`、`watchlist`、`project_skips`、`interactions`）按 `user_id` 严格隔离；核心项目事实数据（`projects`、`logs`、`project_history`）保持全局共享；
  - 过滤机制：`app/services/user_scope.py:build_user_scope_filter` 统一生成 SQL 过滤子句；非管理员强制绑定当前身份并阻断 query/body 参数越权伪造；管理员默认查看全量并支持 `?user_id=` 过滤；
  - API 矩阵：新增 `GET /api/v1/events` 埋点查询端点；`GET /feedback/{project_id}`、`GET /events`、`GET /watchlist`、`GET /interactions` 全面支持行级隔离；全量 161 项测试 100% 通过。
- V3 GDPR 合规与数据治理（ADR-008 §6 / Roadmap §25.9, §25.10 / TASK_BREAKDOWN W12-11）：
  - 核心模块：`app/routers/v1/user_data.py` + `UserRepository:delete_user`；
  - 数据导出：`GET /api/v1/user/data`（已认证用户结构化导出全部个人资料、偏好、feedback、events、watchlist、skips、interactions、api_keys，排除密码与密钥哈希）；
  - 账户注销：`DELETE /api/v1/user/account`（去标识化 feedback.user_id=NULL 以维持校准样本池，硬删除 events/watchlist/skips 等私有数据，当前 JWT JTI 记入 blacklisted_jti，撤销 session/api_keys，释放注册邮箱）；
  - 门禁与对齐：写端点从 47 扩展至 48，自服务写端点从 31 扩展至 32，全仓日志事件数增至 377 个，全量 186 项测试 100% 通过。
- V3 用户系统全链路集成测试（TASK_BREAKDOWN W12-12 / ADR-008）：
  - 测试套件：`backend/tests/api/test_user_system_e2e.py`，完整覆盖 8 阶段多用户全生命周期（注册自举、认证会话、多设备登出、偏好 CRUD、API Key 鉴权与撤销、RBAC 屏障、行级隔离、GDPR 数据导出与账户删除去标识化）及 3 组并发边界测试；
  - 验收闭环：用户系统子项目（W12-06 ~ W12-12）全部完成验收，全仓 136 项用户与门禁测试 100% Green。
- V3 多实例 HA 与 Leader Election（Roadmap §24.3 / ADR-005 / TASK_BREAKDOWN W12-03）：
  - 核心架构：基于数据库单例心跳租约的分布式选主服务 `LeaderElector`（`app/services/leader_election.py`），支持原子竞选、自动续约、租约过期抢占与优雅退让（`step_down`）；
  - 调度器动态绑定：在 `app/main.py:lifespan` 中根据 Leader 身份动态启动/停止 `UnifiedScheduler`，确保多实例集群下仅有单一活跃 Leader 运行定时调度与写入，杜绝重复采集与写冲突；
  - 状态查询 API：`GET /api/v1/ha/status`（公开只读），输出集群选主状态、Leader 标识、租约到期时间与心跳配置；
  - 门禁与对齐：全仓日志事件数增至 385 个，命名空间增至 72 个，API SPEC §53 对齐，全量门禁 100% 通过。
- V3 全链路集成测试（TASK_BREAKDOWN W12-05 / Roadmap §24.3, §25.5.3）：
  - 测试套件：`backend/tests/api/test_v3_core_e2e.py`，完整覆盖 6 阶段全链路端到端生命周期：
    1. 多实例 HA 集群选举与互斥租约（Alpha=Leader, Beta=Follower）；
    2. 多钱包参与策略建议（高女巫 L2、轻量 Infra 集群、已发币否决）；
    3. 项目演化历史时间轴与时序评分走势；
    4. 用户交互（feedback/watchlist/skips）动态推断偏好画像、个性化加权重排（`projects?personalized=true`）与 GDPR 一键清除；
    5. 异常检测引擎全量巡检（评分均值漂移、FARM 偏斜、0 分集中爆发、采集源时效性）；
    6. 高负载下 Leader 主动退让与 Follower 瞬时接管故障转移（Failover）；
  - 边界测试覆盖空数据库冷启动与非 HA 单机模式兼容性；全量测试与 4 项核心文档一致性门禁 100% Green。
- `no_token_yet` 是**反向证据**，按 AND 合并（不在 `_MERGE_BOOL_OR` 里）：True=该源没看到代币（弱），False=看到了（强）。只有 `_TOKEN_STATUS_SOURCES` 参与投票，文本类来源的缺省翻平不投票。此前 OR 合并会让已发币项目以 pre-TGE 身份通过资格门。
- LLM：配置优先级为 `OPENAI_*_N` → `LLM_*_N` → 单接口回退；provider 必须有 http(s) URL、key、至少一个 model，最多 10×10。候选按 provider×model 组合进程内 round-robin，调用开始推进指针并旋转完整列表；连接错误跳过 provider 剩余模型，模型错误仅跳过当前模型，预算/账本/泄漏检测立即停止。`is_llm_enabled` 与有效 provider 一致。多 worker 不保证全局均衡。
- LLM 主要文件：`backend/app/config.py`、`backend/app/llm/client.py`、`backend/app/routers/v1/llm.py`、`backend/tests/test_llm_failover.py`、`docs/adr/ADR-016-llm-provider-round-robin.md`。

## 前端中文化（2026-09-04 已完成静态层）
- 已中文化 10 个文件的显示层文案：InteractionPanel、OpportunityWorkflowPanel、RoiLedger、lib/api.ts、lib/export.ts、ops、portfolio、project/[id]、insights、settings。协议契约零改动。
- 边界：API 路由、环境变量、HTTP 头、后端枚举传输值、模型/版本号、品牌名、扩展名、输入前缀（tx:）一律保留原文；枚举走「传输值保留 + 显示层映射表」。
- 三条硬经验：中文不能套 `is-mono` 等宽类；健康状态要先判 ok 再回退后端 status，否则永远显示英文；`_STATE_FIXTURES` 等编译期类型夹具不是文案、不可翻译。
- 验证基线：前端 lint/typecheck/20 tests/build(12 页)/audit 0 漏洞，后端前后端一致性门禁 84 passed（enum/field/flag parity + structure + terminology）。改枚举映射后必须跑后端这 5 个文件。
- 遗留：ActionQueue、ParticipationTasks、评分理由、证据字段、blocker code 等**动态 API 值仍为英文**，需后端 zh 字段/locale 参数，前端静态替换无法解决。

## 文档维护（skills/ 已于 2026-09-05 全量对齐）
- `skills/` 23 份文档曾大批量引用不存在的路径/命令（照写会落在不被构建测试的位置且不报错）。现已逐条订正，维护约定固化在 `skills/README.md` 顶部：**改前 `git ls-files` 确认路径存在，改完跑 `test_check_terminology.py` + `test_encoding_mojibake.py`**。
- 易记错的三条现状：覆盖率只有 80% 一条线（无「关键模块 90%」）；mypy 是 `mypy app --config-file pyproject.toml`（只跑 app、非 `--strict`）；依赖无 `.lock` 文件，门禁是 `test_requirements_pinning.py` 的 `==` pin。
- 文档类改动跑这些 parity 门禁：`api_spec` / `observability` / `security` / `operations` / `env_example` / `adr_index` / `frontend_field|enum|flag` / `toolchain_version` / `data_source_strategy`。
- `test_security_doc_parity.py` 有**反向断言**：`system_prompt`、`output_schema` 等 6 个符号在 `backend/app` 里必须一处没有。把「待实现」做成「已实现」时必须同步改它。

## 其他
- **依赖必须锁到传递依赖层**：`anyio`、`starlette` 未锁曾让 CI 整套后端测试在收集阶段崩（本机装旧版看不到）。判据：collection error + 秒级失败 + 无覆盖率产物 = 环境/依赖问题而非业务代码。门禁 `backend/tests/test_requirements_pinning.py` 钉住，不要放宽 CI 的 `-W error::DeprecationWarning`。
- **当日记忆日志不进版本控制**：`.git/info/exclude` 忽略 `/.workbuddy/memory/*.md`，不要用 `git add -f` 强推；MEMORY.md 因已 tracked 不受影响。
- 历史数据回填与校准试验引擎（2026-09-20 落地）：
  - 历史种子回填：`backend/scripts/backfill_historical_samples.py`，从历史已知空投库中加载 50 个真实已知项目，通过 `SimpleOrchestrator(enable_llm=False)` 评分并注入 `projects`（完整 8 维 `sub_scores`）与 `feedback`（真实发币结果），解决 Web3 空投反馈延迟大、冷启动难积累的问题；支持 `--expand-to-gate` 扩充；
  - 校准试验引擎：`app/calibration.py` 与 `scripts/calibrate_weights.py` 支持 `--force`。标准生产门禁（live ≥ 200、FARM ≥ 30）严格保持阻断；指定 `--force` 时允许在门限未达标时执行 Dirichlet 采样与爬山搜索，生成候选权重写入 `weight_changelog`（标记 `force_experiment`，`status='candidate'`）。
- F4 监控钱包与空投到账闭环（2026-09-20 落地）：
  - 后端：`backend/app/routers/v1/watched_wallets.py` + `claim_watch.py`，自有地址登记（小写归一、形状校验、不可变），Alchemy Webhook 匹配 ERC20 到账并生成 `airdrop_candidate` 站内通知与推送；26 项测试 100% 通过；
  - 前端：`frontend-next/components/WatchedWalletsPanel.tsx`，支持监控地址录入校验、启停切换（PATCH）、删除（DELETE）、所属链/备注展示与一键复制；集成至 `settings/page.tsx`；
  - 通知中心：`notifications/page.tsx` 扩展 `airdrop_candidate` 类型与「疑似到账」专属 Tab，打通链上到账到站内通知闭环。
- 安全与上线加固（2026-09-20 落地）：
  - P1-5 代理越权修复：`frontend-next/proxy.ts` 移除管理路径自动代签，未带凭据交由后端 401/403 拦截；`frontend-next/lib/api.ts` 自动读取 `localStorage`/`sessionStorage` 附加用户凭证；
  - P1-4 异步事件循环阻塞消除：`backend/app/auth.py`（bcrypt & JWT 黑名单查询）、`backend/app/routers/v1/collections.py`（持久化与经济计算）、`backend/app/scheduler.py`、`backend/app/collectors/scheduler.py`、`backend/app/pipeline_run.py` 均通过 `await asyncio.to_thread(...)` 将同步 DB 与密集计算调度至线程池；
  - 反代限流与采集白名单：确认 `TRUSTED_PROXY_COUNT` 与 `domain_allowlist.py` 严格生效，180 项前后端安全与回归测试 100% 通过。
- 动态 API 内容中文化（任务 #42，2026-09-20 落地）：
  - 前端映射层：`frontend-next/lib/format.ts` 建立 `reasonZh`（覆盖 40+ 条权威正反理由及否决项）、`blockerCodeZh`/`severityZh`/`reasonActionZh`（阻断项与升级条件）、`recommendedActionZh`（4 类核心行动）、`factorKeyZh`（15+ 证据因子）、`freshnessZh`/`sourceTypeZh`/`verificationStatusZh`；
  - 前端组件接入：`ProjectCard.tsx`、`app/project/[id]/page.tsx`、`OpportunityWorkflowPanel.tsx` 全面呈现中文；
  - 后端模型与路由：`app/opportunity/decision.py` 增补中文常量，`app/opportunity/workflow.py` 投影模型增补 `*_zh` 伴随字段并自动赋值，`routers/v1/projects.py` 的 `list_projects` 与 `get_project` 同步输出 `reason_zh`；清理 `db.py` 用户表中遗留的 SQL 外键约束，全仓对齐无外键规范；1,110 项前后端测试 100% 通过。
- 文档漂移修正与清理（2026-09-20 落地）：
  - `docs/ENGINEERING_ROADMAP.md §6.1` 对齐 `BaseAgent.run(state)` 与 `AgentContext`（`run_id`/`enable_llm`/`llm_model`/`llm_discovery_score_threshold`/`max_concurrent_projects`/`llm_semaphore_size`）现状；
  - `.github/PULL_REQUEST_TEMPLATE.md`、`CONVENTIONS.md`、`CONTRIBUTING.md`、`skills/review-code-review.md`、`skills/backend-agent-implementation.md` 统一移除 `.lock.txt` 与「关键模块 ≥ 90%」漂移；
  - `evaluation/README.md` 修正实际目录结构并对齐回测/校准脚本真实路径；
  - 修复 `backend/app/services/user_scope.py` 文档字符串中问号紧贴句号引发的编码门禁误报；全仓文档一致性与编码门禁 100% 通过。
- 防 PUA 与保本止损引擎（Anti-PUA & Capital Preservation Engine，2026-09-20 落地）：
  - 核心算法：`backend/app/services/anti_pua.py` 纯确定性函数（`calculate_fatigue_index` 4 维权重、`classify_capital_friction_tier` 4 级摩擦、`evaluate_exit_advisory` 4 类恶化指标）；
  - 决策门禁：`app/opportunity/decision.py` 拦截疲劳指数 ≥ 0.70 降级为 `WATCH`（`PUA_FATIGUE_WARNING`），超限重资本标记 `IGNORE`（`HEAVY_CAPITAL_LOCKUP`），触发恶化预警直接终止交互（`EXIT_RECOMMENDED`）；
  - 投影与通知：`app/opportunity/workflow.py` 在 `OpportunitySummaryProjection` 注入中英文分析，`app/notify/evaluator.py` 联动生成 `exit_advisory` 紧急预警事件；
  - 前端视觉呈现：`ProjectCard.tsx` 动态呈现「零资金成本」「PUA预警」「建议撤退」徽标；`app/project/[id]/page.tsx` 顶部显示撤退与疲劳警示横幅；`OpportunityWorkflowPanel.tsx` 嵌入撤退预警框与摩擦等级；
  - 1,079 项全栈单元、契约与前端规范测试 100% 通过。
- 零成本 Telegram 免费公开频道采集器（2026-09-20 落地）：
  - 核心设计：基于 Telegram 官方公开免鉴权 Web 预览端点（`https://t.me/s/{channel}`）抓取最新消息，无需 API Key、无需手机号/Bot 登录，彻底规避商业 API 高昂费用与封号风险；
  - 轻量解析：使用 Python 标准库 `html.parser.HTMLParser`（`TelegramWebParser`）解析，不引入新依赖，严格遵守版本锁定门禁；
  - 信号与控费：复用 `content_signals.py` 提取早期空投信号（`testnet`、`points`、`funding`、`tge`、`airdrop` 等）；遵照 P2 内容源规范，`discovery_score` 封顶于 0.28（低于 0.30 LLM 触发阈值），只存 `project_signals`，不消耗 LLM 预算；
  - 全流程接轨：`backend/app/config.py` 登记配置；`scheduler.py` 登记 cron（`0 */4 * * *`）；`rate_limiter.py` 登记 0.5 req/s、burst 2；`factory.py` 注册 `TelegramChannelCollector`；`normalize.py` 设置 `SOURCE_PRIORITY["telegram"] = 8`；`domain_allowlist.py` 登记 `t.me`；
  - 文档与契约：`docs/DATA_SOURCE_STRATEGY.md` 与 `test_data_source_strategy_parity.py` 100% 同步，85 项后端测试与前端类型检查全部通过。
- 零成本 Farcaster 公开免费 Hub 采集器（2026-09-20 落地）：
  - 核心设计：基于 Farcaster 开放协议公共 Hubble 节点（`https://hub.pinata.cloud/v1/castsByParent`）读取频道的最新 Casts，无需 API Key、无需账号登录或 Signer 私钥，零 API 成本捕获海外真实 Founder/Dev 高信噪比早期 Alpha；
  - 协议解析：解析 Farcaster Epoch 秒数偏移、从 `castAddBody.text` 与 `embeds` 提取正文与项目链接，复用 `content_signals.py` 识别空投/Alpha 信号并限制 `discovery_score <= 0.28`，不消耗 LLM 预算；
  - 全流程接轨：`config.py` 登记配置、`scheduler.py` 登记 cron（`0 */4 * * *`）、`rate_limiter.py` 登记 0.5 req/s、burst 2、`factory.py` 注册 `FarcasterCollector`、`normalize.py` 设置 `SOURCE_PRIORITY["farcaster"] = 8`、`domain_allowlist.py` 登记 `hub.pinata.cloud`；
  - 文档与契约：`docs/DATA_SOURCE_STRATEGY.md` 与 `test_data_source_strategy_parity.py` 100% 同步，94 项后端测试与前端类型检查全部通过。
- 项目存活率与融资硬检验门禁（Runway & Viability Gate，2026-09-21 落地）：
  - 核心算法：`backend/app/services/viability_gate.py` 纯确定性评估服务，识别三类致命风险：`UNBACKED_POINTS_MACHINE`（零融资且无背书的纯积分盘）、`LOW_FUNDING_UNVIABLE`（公开融资 < $3M 且无 Tier-1/Tier-2 机构背书）、`RUNWAY_DEPLETED`（小额融资已超 18 个月且代码/TVL 停摆）；Tier-1 VC（Paradigm、a16z、Polychain 等）背书可豁免小额融资限制；
  - 决策门禁：`app/opportunity/decision.py` 在 `decide()` 实施短路拦截逻辑，纯积分盘直接定性为 `IGNORE`（`NOT_FIT`，理由码 `LOW_RUNWAY_RISK`），微额融资与跑道耗尽降级为 `WATCH`（`MONITOR`），彻底杜绝在空手套白狼或即将停服的项目上浪费 gas 与流动性；
  - 投影与数据流：`app/opportunity/models.py` 与 `workflow.py` 在 `OpportunitySummaryProjection` 注入 `viability_tier`、`viability_tier_zh` 与 `viability_advisory`；`routers/v1/projects.py` 增补 `low_runway_risk` 中文映射；
  - 前端视觉呈现：`ProjectCard.tsx` 动态展示「存活预警」徽标；`app/project/[id]/page.tsx` 顶部呈现「项目存活与跑道预警」横幅；`OpportunityWorkflowPanel.tsx` 呈现存活率徽标（资金充裕/跑道观察/存活预警）与详细评估卡片；
- 全库存活门禁批量洗牌与零成本测试网优先推荐体系（2026-09-21 落地）：
  - 批量诊断与洗牌脚本：`backend/scripts/audit_viability.py`，全库扫描诊断 338 个项目存活率与跑道硬指标，支持 `--dry-run` 与 `--apply`，自动归类 `viable`（59）、`borderline`（271）、`unviable`（8），清洗无背书纯积分盘及跑道耗尽项目；修复 Windows 控制台 GBK 编码并统一解析 `backend/data/airdrop.db` 真实路径；
  - 存活分档修复：`backend/app/services/viability_gate.py` 将零/未知融资且无 Tier-1/Tier-2 机构背书、未开启积分盘的早期项目准确分流至 `borderline`（跑道观察）而非误判为 `viable`；
  - 零成本测试网推荐：`backend/app/repository.py` 新增 `is_zero_cost_opportunity()`，综合检验测试网信号、存活率等级与无重资本锁仓限制，`list_projects` 支持 `zero_cost_only: bool = False` 过滤；`routers/v1/projects.py` 暴露 `zero_cost_only` API 参数与过滤器回显；
  - 零成本水龙头指引：`backend/app/services/participation_tasks.py` 自动为测试网项目生成 `testnet-faucet-guide` 任务（优先级 1、必须、零成本说明）；前端 `ParticipationTasks.tsx` 动态展示「零资金成本提示」横幅；
  - 前端工作台交互：`frontend-next/app/page.tsx` 顶部工具栏增加「🛡️ 零资金成本」快速筛选 Chip，支持与「全部」互斥切换与重置；
  - 单元测试与验证：新增 `test_audit_viability.py` 与 `test_zero_cost_priority.py`，全量测试 100% 通过。
- 零成本三大核心基础设施引擎（2026-09-21 落地）：
  - 多免费源信号交叉印证与共识引擎：`backend/app/services/signal_correlation.py` 纯确定性聚合 Telegram、Farcaster、GitHub、RSS、CoinGecko 信号，计算 14 天共识等级（high/medium/single/none）并赋予免 Token 加成；`repository.py` 自动装配，`routers/v1/projects.py` 开放 `GET /api/v1/projects/{id}/signals-consensus`；`ProjectCard.tsx` 呈现「🎯 3源共识」与「🔗 双源印证」徽标；
  - 免 Key 公共 EVM RPC 探测器：`backend/app/services/public_rpc_verifier.py` 接入 Sepolia、Arbitrum、Base、Optimism、Polygon、Berachain、Ethereum Mainnet 公共节点，通过 `eth_getCode` 与 `eth_getTransactionCount` 探测合约真实部署与活跃度；开放 `GET /api/v1/onchain/chains` 与 `POST /api/v1/onchain/verify`，并提供 `backend/scripts/verify_onchain_liveness.py` CLI 工具；
  - 测试网水龙头 24h 冷却与任务日历：`backend/app/services/faucet_registry.py` 收录主流免 Key 优质水龙头，`faucet_claims` 本地表追踪打卡与倒计时；开放 `GET /api/v1/faucets`、`POST/DELETE /api/v1/faucets/{id}/claim`；前端交付 `FaucetTrackerPanel.tsx`，并在 `ParticipationTasks.tsx` 测试网横幅提供快捷入口；
  - 门禁与契约：`docs/API_SPEC.md` 对齐 51 个写端点（35 匿名可调），`test_admin_only_rules.py`、`test_api_spec_parity.py`、`test_frontend_enum_parity.py`、`test_check_terminology.py` 187 项全仓测试 100% 通过。
- 测试网水龙头独立专页与项目详情多源共识卡片闭环（2026-09-21 落地）：
  - 独立水龙头中心页面：`frontend-next/app/faucets/page.tsx`，设立零成本交互三大法则看板，全屏集成 `FaucetTrackerPanel`，支持网络过滤、倒计时与一键打卡；
  - 全局主导航：`frontend-next/components/Nav.tsx` 引入 `Droplets` 图标，新增「水龙头」(`/faucets`) 入口；
  - 详情页多源共识卡片：`frontend-next/app/project/[id]/page.tsx` 新增多源共识视觉卡片，展示共识等级、测试网印证、Alpha 确定性加成比例、独立来源与信号类型；
  - 验证：前端 `npm run typecheck`、`npm test` (20/20)、后端 4 大门禁与功能测试（69 passed）全部通过，远程已推送至 `ede0a92`。
- 免 Key 公共 RPC 链上存活性探测器全前端集成（2026-09-21 落地）：
  - 核心组件：`frontend-next/components/OnChainVerifierPanel.tsx`，免 Key 支持 7 大网络（Sepolia/Arbitrum/Base/Optimism/Polygon/Berachain/Ethereum），输入 EVM 地址一键探测合约/EOA 状态、字节码大小、Nonce 与 RPC 延迟；内置 Uniswap V3 与 WETH9 体验样本；
  - 双端集成：升级 `/faucets` 页面为「测试网水龙头与链上中心」，并在 `/project/[id]` 详情页接入 `pd-onchain` 折叠面板与右侧锚点导航；
  - 验证：前端 `typecheck`、`test` (20/20)、后端 46 项 RPC 探测与门禁测试全部通过，远程已推送至 `0380ca3`。
- 前端格式化与零成本数据源单元测试补全（2026-09-21 落地）：
  - 单元测试：`frontend-next/lib/format.test.ts`，涵盖 `labelZh`、`stageZh`、`lifecycleStageZh`、`timingZh`、`sourceZh`（重点覆盖 Telegram 与 Farcaster 零成本渠道）、`riskLevelZh`、`teamTypeZh`、`tierZh`、`reasonZh`（存活率与决策理由）、`viabilityTierZh` 与 `capitalFrictionTierZh`；
  - 测试执行器：`test.mjs` 引入 `format.test.ts`，Node 24 原生支持无需子进程，全量 34 项前端单测全绿；
  - 验证：前端 `typecheck`、`test` (34 passed)、后端 72 项术语与编码测试全部通过，远程已推送至 `c44aff2`。
- 前端依赖漏洞优先通过 `frontend-next/package.json` 的 `overrides`；改依赖后跑五项门禁。
- 遗留：无阻断性业务功能或文档漂移遗留。



