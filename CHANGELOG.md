# Changelog

> 所有显著变更均记录在此文件。
> 格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)，
> 版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

---

## [Unreleased]

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
