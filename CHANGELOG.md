# Changelog

> 所有显著变更均记录在此文件。
> 格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)，
> 版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

---

## [Unreleased]

### Security — 上线复核 P0 修复（2026-08-20）

- **修复 `/api/v1/settings/config` 明文泄露 LLM API Key**（严重）：该端点直接返回 `settings.llm_providers`，其中含 `api_key` 原文。配合公开的 `POST /api/v1/auth/anonymous`（任何人可领匿名 token），构成**零凭证窃取 OpenAI/DeepSeek 密钥**的完整链路（已实测复现）。现改为只返回 `has_api_key` 布尔值，与 `/llm/status` 的脱敏口径一致
- **`/api/v1/settings` 收入管理员权限**（`ADMIN_ONLY_PREFIXES`）：运行时配置快照含 CORS 白名单、DB 后端、全部阈值与 cron，属运维信息，不应对匿名角色开放。修复后匿名 token 访问返回 403，管理员 200
- **移除 `NEXT_PUBLIC_API_KEY` 客户端兜底**（`frontend-next/lib/api.ts`）：`NEXT_PUBLIC_*` 会被内联进浏览器 bundle，任何访客都能在 DevTools 读到管理员密钥。鉴权统一由服务端 `proxy.ts` 注入，密钥不出服务端
- **生产环境 CORS 增加 localhost 校验**：`CORS_ORIGINS` 含 `localhost`/`127.0.0.1` 时拒绝启动，避免生产忘配导致真实前端域名被全部挡掉（表现为"上线后所有接口跨域失败"）

### Fixed — 上线复核 P0/P1 修复（2026-08-20）

- **修复容器按官方文档启动必然 CrashLoop**（阻断）：`docker-compose.yml` 的 `environment:` 白名单未透传 `AUTH_TOKEN_SECRET`，而镜像内无 `.env`（被 `.dockerignore` 排除）、也没有 `env_file:`；`APP_ENV` 默认为 `production` 时生产自检强制要求该值 → `docker compose up -d --build` 100% 起不来。现补 `env_file: [.env]`，与 `docker-compose.prod.yml` 对齐。已用真实容器验证：修复前拒绝启动，修复后 `Up (healthy)` 且 `/health` 返回 healthy
- **修复两层缓存 TTL 边界判定**（`app/utils/fetcher.py`）：内存与磁盘层都用 `time.time() - ts > ttl`，`ttl=0`（语义为"不缓存"）时因 `0 > 0` 为 False 而返回本该过期的数据。Windows 时钟分辨率约 15.6ms，实测 20 次里 14 次命中脏数据。改为 `>=`
- **移除 `/collections` 整页虚构数据**：原页面零 API 调用，展示 9 个不存在的项目（Nova Protocol / Poly Oracle 等）配虚构评分与「官方确认 Q3 空投」类假情报，对空投决策系统属误导性金融信息。现接入既有但从未被前端使用的 `GET/DELETE /api/v1/watchlist`，取消收藏为真实写入
- **移除 `/archive` 整页虚构数据**：原页面展示虚构归档记录、「命中率 99.2%」、「已归档 38.6 GB」，且所有开关为 `onChange={() => {}}`。现只展示 `/settings/config` 里真实的保留期配置，并明确标注「暂无运行历史接口」
- **移除 `/settings` 假保存按钮**：`handleSave` 只弹「配置已保存」toast 而不写任何东西，旁边却写着「修改将在保存后写入 .env 并热加载」，自相矛盾。整页改为明确的只读快照（标题标注「只读」，输入框改文本展示，开关 `disabled`），删除保存按钮
- **移除 `/ops` 假调度块与假配额**：`SCHEDULER_JOBS` 写死 4 个后端根本不存在的 job 及其「成功 · 182 条」等执行结果，开关空操作、「立即执行」无 onClick；`SOURCE_QUOTAS` 写死各源配额用量。现改为展示 `/settings/config` 的真实调度配置，配额改用后端真实的 `api_calls_today`
- **移除项目详情页恒为「排名第 1」**：`const rank = 1` 写死，任何项目都显示第 1 名
- **采集源缺凭证时启动告警**：`GITHUB_ENABLED=true` 但 `GITHUB_TOKEN` 为空时，GitHub 源静默不跑（`is_enabled()` 返回 False），而 execution 维度占 13% 权重会永久缺失。现在启动日志显式 warning
- **`dashboard.py` 影子块异常不再静默 `pass`**：改记 debug 日志，避免真实 SQL/schema 故障被吞掉、面板恒显 0 而无从排查

### Changed — 工程门禁与配置一致性（2026-08-20）

- **CI 三道门修复至全绿**：`ruff check` 由 99 errors → 0（62 项自动修复，其余逐条判断）；`ruff format` 由 31 文件待重排 → 全部合规；`mypy app` 由 7 errors → 0
- **`sqlite3.Row` 的 SIM118 加豁免**：`"col" in row.keys()` 是列存在性检查的唯一正确写法（`in row` 检查的是**值**），照 ruff 建议改会让所有可选列静默变 None——已在 `pyproject.toml` 注明原因
- **统一两份 `pyproject.toml` 的口径**：`backend/pyproject.toml` 的 version 1.0.0→0.1.0、requires-python >=3.10→>=3.11、mypy python_version 3.13→3.12（对齐 CI 与 Dockerfile 的 3.12），并补上此前缺失的 `--cov-fail-under=80`（pytest 从 `backend/` 运行时用的正是这份配置，等于本地跑测试完全不校验覆盖率）
- **`.env.example` 补关键提示**：`AUTH_TOKEN_SECRET` 标注生产必填（为空则容器 CrashLoop）+ 生成命令；`CORS_ORIGINS` 标注生产必须改真实域名

### Added — Portfolio/Settings 真实化 + middleware 迁移（2026-07-26）

- **Portfolio 页接入真实 API**：去掉全部 mock 数据，改为读取 `GET /interactions/summary` + `GET /interactions`；KPI、校准矩阵、分布、记录表全部真实数据
- **Settings 页接入真实配置**：新增 `GET /api/v1/settings/config` 只读端点，返回运行时配置快照（密钥只返回布尔值）；前端 Settings 页从硬编码默认值改为回填真实运行时值
- **Next.js middleware → proxy 迁移**：`middleware.ts` 重命名为 `proxy.ts`（Next.js 16 约定），消除 deprecation warning

### Added — 通知中心增强：评分变化 + 已读持久化（2026-07-26）

- **评分变化通知**：从 `project_history` 对比同项目最新两条快照，生成 `score` 类型通知（升/降/标签变化）
- **已读状态持久化**：新增表 `notification_reads` + `POST /api/v1/notifications/read`（支持 ids / all）；刷新后已读状态保留
- **前端通知中心**：点击单条 / 「全部已读」会调用后端持久化；并修正 `apiFetch` 解包 `data` 后的字段读取

### Added — 通知中心真实化（2026-07-26）

- **新增 `GET /api/v1/notifications` 聚合端点**：返回今日新 FARM/WATCH 机会 + 采集器失败告警
- **通知中心页接入真实数据**：去掉写死 mock，改为读取上述端点；空库时显示空状态而不是假项目

### Added — Dashboard 今日流水线真实化（2026-07-26）

- **新增 `GET /api/v1/dashboard/overview` 聚合端点**：一次返回今日采集运行数、今日新增项目数、发现队列待处理数、影子引擎今日评估数
- **Dashboard「今日流水线」卡片接入真实数据**：原先写死的 `sampled 3 / saved 3 / 待处理 12` 等假数据，改为读取真实采集运行、发现队列与影子评估计数

### Added — 上线审核 P1 项（GO_LIVE_AUDIT_REPORT，2026-07-26）

- **所有 API 响应携带 `X-Disclaimer` 响应头**（`Not investment advice...`，SECURITY.md §7.5 合规要求）
- **新增 HTTP 请求计数指标** `airdrop_http_requests_total`（按方法 + 状态码分档）
- **告警规则补充**：`HighAPIErrorRate`（5xx > 0.1/s，critical）+ `PipelineConsecutiveFailures`（15 分钟 ≥ 2 次失败，critical）；`airdrop_pipeline_runs_total` 新增 `status` 标签（started/completed/failed）
- **生产自检新增 AUTH_TOKEN_SECRET 校验**：生产环境该值为空会拒绝启动（否则匿名 token 每次重启后失效）

### Fixed — 上线审核阻断项修复（GO_LIVE_AUDIT_REPORT，2026-07-26）

- **删除冲突的 `backend/Dockerfile`**：它与正确的 `docker/Dockerfile` 并存且被 `docker-compose.yml` 默认引用，但其 Python 3.14 + 不完整的 COPY 会让 `docker compose up --build` 构建失败；统一引用 `docker/Dockerfile`
- **统一 Python 版本到 3.12**：此前 CI 用 3.13、Dockerfile 用 3.11、本地为 3.14，三处不一致可能引入「CI 通过但生产失败」的幽灵问题；现 CI（ci.yml / security.yml）和 docker/Dockerfile 统一为 3.12

### Fixed — 系统审查（采集链路 / 流水线 / 安全 / 前端，2026-07-26）

详见 `SYSTEM_AUDIT_REPORT.md`。真实库（702 项目 / 1040 原始记录）实测：7 项可验证信号里 6 项命中率为 0%。

**采集链路**
- **DefiLlama 补齐字段映射**：`description`（文本判断的唯一来源，缺失导致 `has_docs`/`has_roadmap`/`explicit_airdrop_mention` 全语料恒为 False）、`tvl_usd`、`has_twitter`/`has_github`
- **跨源合并首次可发生**：galxe/layer3/etherscan/twitter/coingecko 不再臆造赛道（写死 `Quest`/`On-chain`/`Unknown`/`DeFi` 会让 dedup_key 与真实赛道永不相撞，真实库 `source_count>=2` 恒为 0%）；新增"赛道未知分组并入同名已知分组"（仅唯一匹配时）
- **信号补充源不再被阈值挡在门外**：coingecko(0.1)/etherscan/cryptorank(≤0.28) 低于分析阈值 0.3，此前从不进入合并；现在同 dedup_key 已有记录过线时，低分佐证一并载入，且 `limit` 改为约束项目数而非原始行数
- **Twitter 正文参与解析**：推文载荷在 `raw_data["text"]`，此前不在取值范围内，两个 twitter 源贡献恒为零
- **修正阶段与代币推断**：TVL 分档判 testnet 造成 31.8% 项目误标；`_is_unlisted` 改为"真实 ticker > gecko_id"，并把 DefiLlama 的 `"-"` 哨兵值（真实库 658/1040 条）排除在 ticker 之外
- **GitHub 赛道整词匹配**：`"ai" in desc` 会命中 blockchain/chain/mainnet；改存 `pushed_at` 而非会被 star 顶新的 `updated_at`
- **CoinGecko 不再拿币种图标当官网**
- **合并容忍 naive/aware 时间戳混用**：`min()` 抛 TypeError 会中断整批采集

**流水线与调度**
- **持久化失败不再报成功**：状态改到落库之后再定；出队判据从"内存评分成功"改为"确实写进 projects"，此前整批丢失且队列已清空、DB 与 metrics 均无痕迹
- **每次运行落持久记录**（`LogRepository.log_run` 此前定义了却从无调用方）
- **cron 传 timezone**：预构造的 `CronTrigger` 不继承 `scheduler.timezone`，`TIMEZONE` 配置被静默忽略；`misfire_grace_time` 由默认 1 秒改为 1 小时 + `coalesce`

**安全（对照 `docs/SECURITY.md`）**
- **500 响应不再回显异常原文**（psycopg 异常带 DSN 含库密码，httpx 异常带 `?apikey=`）
- **安装 structlog 脱敏 processor**（§3.3 要求但全仓库无 `structlog.configure()`）：按字段名脱敏、递归容器，且排在 traceback 渲染**之后**
- **`APP_ENV` 归一化**：`Production`/`PRODUCTION`/`prod`/`"production "` 此前全部绕过生产安全校验
- **API_KEY 长度下限 32**（§4.2；原实现只校验非空）
- **接入限流**（§4.2/§10.4，三个配置项此前无人读取）：按 IP 滑动窗口 + 429/Retry-After，昂贵端点分档；默认不采信可伪造的 `X-Forwarded-For`，新增 `TRUSTED_PROXY_COUNT`
- **输入长度与取值域上限**：feedback 的 note 实测 20MB 直接落库；funding 的 NaN 会写进 meta 再报 500
- **移除根目录 nginx.conf 的 CORS 通配**：`Access-Control-Allow-Origin: *` + 自动放行预检 + `always`（连 401 都带），且与后端同名头重复导致白名单失效
- `/health` 降级时返回 503（探针按状态码判活）

**前端**
- **采集按钮失效**：后端返回嵌套 `status.enabled`，前端读顶层 `enabled` → 启用列表恒为空；同一错位让 Ops 页全部显示"已禁用"
- **Insights 页 `热度 NaN`**：读错字段名（`heat_score` vs `avg_heat_score`）
- **失败请求不再渲染成空数据成功**；Nav 的接口状态改为三态（检测中/在线/异常），并改探 `/health`
- **项目详情页加代次守卫**：重评后的刷新可能被慢的旧响应覆盖，把分数写回重评之前

### Fixed — 评分决策引擎回归规范（ADR-014，2026-07-26）
- **跨源合并不再丢信号**（`utils/normalize.py`）：原按来源优先级整条择一，落选来源的 23 个信号字段被清空、`source_count` 恒为 1，导致「多发现一个来源分数反而下降」。改为按字段类合并（存在性布尔 OR / 数值 max·min / 列表并集 / 标量取最高可信已知值），并给 `manual`/`api` 显式取值以否决权（唯二能主张否定的来源）；合并结果与输入顺序、与 `PYTHONHASHSEED` 均无关。见 `DATA_SCORING_DICT.md §5.8`
- **Risk Agent 改用 `tokenomics.risk`**（`agents/risk.py`）：原误取 `unlock_penalty`，与 `DATA_SCORING_DICT.md §5.7.2` 不符，方向与模型意图相反（高解锁压力少扣 31.5 分、VC 集中反加 12 分）
- **`airdrop_signal` 子分统一到 `agents/airdrop_signal.py`**：原在 scorer 与 risk 各有一份实现，2304 种信号组合中 666 种结果不一致
- **confidence 去掉 0.55/0.45 人为下限**（`agents/scorer.py`）：四个 Agent 全部成功的正常路径下 confidence 恒 ≥0.55，`confidence < 0.5 强制降档` 只在 Agent 崩溃时生效，而它本意是防「可验证信号不足」
- **`weight_version` 改为从配置读取**；新增 `projects.sub_scores` 列承载子分快照（不复用 `raw_signals`——那一列存的是采集**输入**信号），UPSERT 以 `COALESCE` 写入，评分失败时不覆盖上一次的好快照
- **`TokenomicsResult` 可往返**：`computed_field` + `extra="forbid"` 曾使 `model_dump()` 无法回放，任何从 `tokenomics_json` 重建的路径都会硬失败
- **`tier-1 vc backed` 误判修正**（`agents/team.py`）：`funding_quality <= 0` 时不再打 tier-1 标记
- **融资文本匹配收紧**（`agents/collector.py`）："hourly funding rate"、"raised the block gas limit" 等不再误判为融资事件
- **信号缺失判定修正**（`services/project_signals.py`）：布尔 `False` 与数值 `0` 是有效观测，不再当作缺失，消除单向棘轮

### Fixed — 旁路机会引擎（ADR-014，`opportunity-v2.0`）
- **联合概率区间算法**（`opportunity/probability.py`）：端点由逐分位连乘（`low×low×low`，与 `base` 的独立性假设自相矛盾）改为相对不确定度平方和合成，并以逐分位连乘为地板/天花板，保证新区间恒为旧区间的子集（0.1 网格穷举 2334 万组验证）。原算法使「官方分发 + 积分制资格」档的 `joint.low` 恒为 0.1650，永远跨不过 FARM 门槛 0.20。`base=0` 时端点不再一并归零，避免经 `DUST_REWARD` 误判 IGNORE
- **`TOO_EXPENSIVE` 恢复可达**（`opportunity/decision.py`）：已确知超预算的判定前移到「证据不足」短路之前（仍后于三个 BLOCK 判定），并要求来源等级 ≥ B 且为 observed/derived，避免一条 U 档道听途说把项目钉成 30 天 IGNORE。此前 270 项语料中旧引擎产出 `NOT_FIT` 的数量为 0，用户被告知「去补证据」而真实原因是「太贵了」
- **理由码不再塌缩**（`opportunity/decision.py`）：补齐 `service.evaluate_row` 使用的 8 个 `_usd`/`_hours` 后缀命名，此前一律映射为通用码 `WAIT_MORE_EVIDENCE`
- **证据新鲜度延长衰减尾部**（`opportunity/service.py`）：原 >90 天一律 0.2 且永不再降；现 ≤180 天 0.2、≤365 天 0.1、此后 0.05（只收紧，任何年龄都 ≤ 原值）

### Added
- `backend/app/agents/airdrop_signal.py` — `airdrop_signal` 子分唯一实现
- `backend/scripts/dual_run_compare.py` — 新旧引擎双跑对比（`dump`/`diff` 主引擎，`dump-opp`/`diff-opp` 旁路引擎）
- `backend/tests/test_review_regressions.py` — 74 条回归测试（每条对应一处已确认并修复的缺陷）
- `backend/app/rate_limit.py` — 按 IP 限流中间件
- `backend/scripts/backfill_meta_signals.py` — 从 raw_projects / project_signals 回填历史行的 meta.signals
- `SYSTEM_AUDIT_REPORT.md`
- `docs/adr/ADR-014-engine-spec-conformance.md`
- 工程基础设施完整搭建（P0/P1 全部完成）
- `pyproject.toml` — 项目元数据 + ruff/mypy/pytest 配置
- `.env.example` — 全量环境变量模板
- `.gitignore` — 完整的忽略规则
- `.editorconfig` — 跨编辑器格式统一
- `Makefile` — 开发常用命令
- `backend/app/` — FastAPI 应用骨架（config/db/main/models）
- `agents/` — 15 个详细 Agent 定义文件（Planner/Architect/Backend/Researcher/Frontend/Database/DevOps/Prompt/Reviewer/Security/Performance/Tester/Release/Documentation/Knowledge）
- `skills/` — 21 个实际 Skill 模板（backend/frontend/database/security/performance/deployment/documentation/api/llm/prompt/evaluation/debug/refactor/review/architecture）
- `prompts/` — 5 个 Prompt 模板文件（Narrative/Team/Risk/Tokenomics/Orchestrator）
- `knowledge/` — 业务和技术知识文件（business/technical/api/external/decisions）
- `configs/` — 分环境配置文件（dev/staging/prod）+ Feature Flags
- `tests/` — 可运行测试骨架（unit/contracts/golden/api，22 passed）
- `docs/00_index.md` — 00–15 编号体系文档索引
- `.github/workflows/docs.yml` — 文档链接校验 CI

---

## [0.1.0] - 2026-07-08

### Added
- 完整设计文档体系（20+ 份文档）
- 11 份 ADR（ADR-001 ~ ADR-011）
- 编码规范（`CONVENTIONS.md`，17 节）
- API 规范（`docs/API_SPEC.md`）
- 评分数据字典（`docs/DATA_SCORING_DICT.md`）
- 数据库 DDL（`docs/DATABASE_DDL.md`）
- 前端规范（`docs/FRONTEND_SPEC.md`）
- 用户故事（`docs/USER_STORIES.md`）
- 任务分解（`docs/TASK_BREAKDOWN.md`）
- 部署文档（`docs/DEPLOYMENT.md`）
- 可观测性设计（`docs/OBSERVABILITY.md`）
- 安全规范（`docs/SECURITY.md`）
- 数据质量框架（`docs/DATA_QUALITY.md`）
- 运维手册（`docs/OPERATIONS.md`）
- 性能基准（`docs/PERFORMANCE_BENCHMARK.md`）
- Golden 测试用例（`docs/GOLDEN_TEST_CASES.md`）
- 设计令牌（`docs/DESIGN_TOKENS.md`）
- 术语表（`docs/GLOSSARY.md`）
- Agent 系统（`agents/README.md`）
- Skills 系统（`skills/README.md`）
- Prompt 管理（`prompts/README.md`）
- 知识库（`knowledge/README.md`）
- CI/CD 流水线（ci.yml / security.yml / release.yml）
- PR 模板 + Issue 模板
- 测试骨架（`tests/` + `conftest.py`）
- Docker 配置（Dockerfile + nginx）
- AI 开发工作流（`docs/AI_DEV_WORKFLOW.md`）
- 项目启动检查清单（`docs/PROJECT_BOOTSTRAP_CHECKLIST.md`）

---

## [0.0.1] - 2026-07-07

### Added
- 项目初始化
- README.md 基础结构
- 基础目录结构

---

[Unreleased]: https://github.com/web3-airdrop-alpha/web3-airdrop-alpha-agent/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/web3-airdrop-alpha/web3-airdrop-alpha-agent/compare/v0.0.1...v0.1.0
[0.0.1]: https://github.com/web3-airdrop-alpha/web3-airdrop-alpha-agent/releases/tag/v0.0.1
