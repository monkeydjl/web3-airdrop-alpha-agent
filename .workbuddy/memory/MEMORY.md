# 项目记忆：Web3 Airdrop Alpha Agent System

> 更新：2026-08-31 · 当前分支 `feat/action-loop-m2`（栈式分支未 push）·
> M1 基线套件 **3129 passed / 0 failed / 88.93%**；M2 新增 42 测试全绿
> 逐日会话记忆在项目根 `SESSION_MEMORY_YYYY-MM-DD.md`（本项目惯例，本文件只存长期事实）

## 一、项目定位与红线

- 自动扫描全网的 Web3 早期项目发现与评分平台（ADR-012 / `SYSTEM_DIRECTION_CHANGE.md`）。
- 链路：系统主动采集 → 去重归一化 → 多 Agent 分析 → **FARM / WATCH / IGNORE**；用户是评分消费者 + 反馈提供者。
- 手动输入 / CSV / seed 仅作采集盲区补充。
- **永不做**：交易执行、自动链上交互（只提醒不代签）、自动 farming、资金/KYC 托管。输出仅供决策参考。
- 设计稿四子系统见 `docs/ACTION_LOOP_DESIGN.md`（标「设计稿」，未全部实现）。

## 二、开发环境

| 项 | 值 |
|---|---|
| 前端 | **3002**（`frontend-next`；旧 `frontend/` 非主入口） |
| 后端 API | **8002**（本地 / Docker / CI 统一） |
| 测试 PostgreSQL | **5433**（容器内 5432，`docker-compose.postgres.yml`） |

- 端口刻意避开 3000/8000/5432（用户多项目并行）。
- 双后端：设 `DATABASE_URL` → PG，未设 → SQLite(WAL)。`/health` 返回 `db` / `db_backend`。
- 启动：`Start.bat`。DB 备份目录 `backend/data/*.bak-*`。
- 后端工具链用 `backend\venv\Scripts\python.exe`（系统 PATH 的 python 无 pytest；ruff 本地 0.16.1 / CI 0.16.2）。

## 三、协作约定（owner 已拍板，不要来回问）

1. **先文档后代码**；有明确实现指令才写 production 代码。
2. **禁止读/改 `.env`**（OpenCode leak protection，`opencode.json` + `AGENTS.md`）。只能判断"键是否设置"，不能取值；需要 owner 自己改 `.env`。
3. 真相源：`docs/` 设计文档 + 代码。冲突时 **`IMPLEMENTATION_STATUS` + 代码 > 旧 Roadmap 阶段表述 > 本记忆文件**。
4. 权重校准门槛 **有效样本 ≥200 / FARM ≥30**，不调低（测试钉死）。
5. 域名白名单走「诚实口径」（文档不宣称未实现的 fail-closed）。
6. **Git 只本地 commit，绝不主动 push**，除非 owner 明确要求。

## 四、技术栈与当前状态（2026-08-31）

- 后端：Python 3.11+ / FastAPI / SQLite+PG / pydantic-settings / 自研 Orchestrator / APScheduler
- 评分：规则引擎默认（LLM 默认关，ADR-001）；Agent：Collector + Narrative/Team/Risk/Tokenomics + Scorer
- 采集器 14 个（`backend/app/collectors/`）：DefiLlama、GitHub、CoinGecko、Etherscan、CryptoRank、RootData、Medium、Mirror、Reddit、Discord 等
- 前端：Next.js **16.3.0** + React 19，`npm audit` 0 vulnerabilities
- 迁移：Alembic（0004 baseline → 0005 notify_log → 0006 participation）
- 门禁：全量 **3129 passed / 9 skipped / 88.93%**（本机约 45–47 min，必须后台跑 + 日志写文件）、mypy strict 131 文件 0 错、ruff 264 文件全过

## 五、关键文档

- 索引：`docs/00_index.md`、`QUICK_REFERENCE.md`
- **实现现状（优先读）**：`docs/IMPLEMENTATION_STATUS.md`
- 产品/架构：`docs/01_product.md`、`docs/02_architecture.md`、`docs/ENGINEERING_ROADMAP.md`
- 方向/数据源：`docs/SYSTEM_DIRECTION_CHANGE.md`、`docs/DATA_SOURCE_STRATEGY.md`
- 执行闭环（V3 设计稿）：`docs/ACTION_LOOP_DESIGN.md`
- 规范：`API_SPEC.md`、`DATABASE_DDL.md`、`SECURITY.md`、`OBSERVABILITY.md`、`OPERATIONS.md`、`DATA_QUALITY.md`、`GLOSSARY.md`
- 校准：`docs/WEIGHT_CALIBRATION.md`（ADR-006）；任务清单：`docs/V2_TASKS.md`
- 编码：`CONVENTIONS.md`；ADR：`docs/adr/`（至 ADR-014）

## 六、核心链路

### 采集 → 分析 → 评分
- 共享噪声 denylist `collectors/noise.py`；命中即 quarantine，分析入口跳过并 mark processed。
- 二阶内容源（CryptoRank/Medium/Mirror/Reddit/Discord）`discovery_score` 压在 **0.28**，只贡献 `project_signals`，**永不触发 LLM 分析**。
- 死数据清理：`python backend/scripts/purge_noise_projects.py`（支持 `--dry-run`）。
- `pipeline_run.execute_analysis_pipeline` 是 /run、分析 cron、采集 auto-run 的共用入口。

### 融资信号（v1.4）
```
采集/手动/CSV → funding.extract_funding_from_raw / compute_funding_quality
  → RawProject.funding_* → repository.save → projects.meta.signals (JSON)
  → scorer / team / tokenomics 读 funding_quality / funding_tier
```
- API：`GET|PATCH /api/v1/projects/{id}/funding?rescore=true`；前端 `FundingPanel`。
- 详情「重新评分」= **PATCH funding 空 body + rescore**（保留 meta.signals，勿精简成 POST /run）。
- RootData 免费档融资数据不全，**不指望它单独喂饱融资维度**；主路径是手动编辑。

### F1 决策推送（M1 已交付）
- `app/notify/`（evaluator 纯评估 / senders 双通道 Telegram+Discord / service 编排）；`notify_log` 表（alembic 0005）。
- 调度 job `notify_digest`（默认 09:00 UTC）；`/api/v1/notify/*` 三端点，整前缀管理员锁。
- `NOTIFY_ENABLED` 默认 false —— **关开关 ≠ 停审计**，评估照常留痕只是不发送。
- **未落库不得有任何后台写**：`save_to_db=False`（试算）时钩子不跑（`if save_to_db:`）。

### F2 参与流水（M1 已交付）
- `participation_plans/tasks`（alembic 0006）；plan 与 task 各四态，状态机闭表，非法迁移 422。
- **user_id 只来自 token，请求体自报一律忽略**（与 P1-1 同款身份伪造教训）。
- 前端 `ParticipationTasks` 接服务端（乐观更新 + 失败回滚），本机 `aa-task-done:*` 勾选一次性迁移后清除。

### F3 收益台账与回测（M2 已交付，数据集待补全）
- `roi_entries`（投入：amount_usd / hours）+ `roi_outcomes`（产出事件）；alembic **0007**。
- 6 端点 `/api/v1/roi/*`；前端 `RoiLedger.tsx` 挂 `/portfolio`（**空态分支也挂**，否则没记录时入口消失）。
- **诚实边界**：`amount_usd` 人工录入不做链上取价、`tx_hash` 只存档不验证、汇总不给时间定价；
  零成本时 `roi_ratio` 返回 **`null`**（不是 `0`——会被读成"没赚没赔"，也不是 `inf`——污染下游聚合）。
- **校准 source 分桶（§4.3，核心约束）**：`CalibrationSample.source` = `live` | `backtest`，
  `check_gate()` **只数 live 桶**但两桶计数都通过 `total_by_source` 暴露。
  否则灌 200 条历史数据就能解锁权重切换。默认 `live`（默认成 backtest 会让历史反馈整批出局）。
- 回测：`PYTHONPATH=. python scripts/run_backtest.py [--json] [--export-samples]`。
  走规则引擎（`enable_llm=False`）+ 确定性 id `backtest-<n>-<slug>` + `save_to_db=False`。
  **结果载体是 `response.states`（`PipelineState` 列表），不是 `results`**；名字取 `state.project.name`。
- 数据集 `backend/data/backtest/airdrops_2024_2025.json`：**19/50 条**（14 正 / 5 负），
  标 `pending_expansion=true`。负样本覆盖三类（迟迟不发币 / 明确不做代币激励 /
  已发币无追加分配），补样本时注意 Monad 这类**时间敏感负样本**会翻转。
- **🔴 回测暴露的引擎缺陷（未修）**：已发币项目仍判 FARM（Chainlink 68 / Worldcoin 69
  越过阈值 65）。airdrop signal 已压到 20，但加权求和压不住其余七维
  （execution/competition/transparency 各 100）。**「已发币 = 无空投机会」应是否决
  条件而非可补偿打分** —— 修它要改评分结构 + 动权重校准协议，已用
  `xfail(strict=True)` 钉在 `test_known_engine_gap_already_launched_still_farm`。
  运维含义：**不能只靠评分兜底，`collectors/noise.py` denylist 仍是第一道防线**。

### Opportunity v2.0 Shadow
- 默认开启（`OPPORTUNITY_SHADOW_ENABLED=true`、sample_rate=1.0）；确定性 SHA-256 分桶，扩量是单调超集。
- Shadow 非权威，不覆盖 `score-v1.4`；任何 Shadow 失败不得影响主 Pipeline。
- 指标低基数，禁止 project ID / URL / 错误文本作 label。
- **遗留**：`opportunity_economic_snapshots` 仍 0 行，7 个 `economic_*` 模块已合但未触发写入。

## 七、全仓硬约定（改代码前必读，这些都是被测试钉死的）

1. **日志事件名必须是调用点字面量**：OBSERVABILITY parity 用正则扫 `logger.xxx("...")`，经变量传入 helper 扫不出来。
2. **`fetcher.fetch()` 会 `.json()` 且缓存一切**：204 空体会炸。POST 场景用 `fetcher.post()`（不缓存、不解析、4xx 除 429 立即失败）。
3. **pipeline 响应是逐键精确断言的主契约**（`test_pipeline_run`），钩子往 result 加键就红。可见性走 notify_log + API，不走响应。
4. **schema 不用 SQL 级外键**（无 `references`），级联删除在路由里显式先删子表。
5. **写端点必须显式登记归属**：新匿名可写端点进 `test_admin_only_rules.py` 的 `ANON_WRITABLE`（逐条带理由），并同步 `API_SPEC §2.1` write-auth-split 计数与逐项清单（当前 admin 8 / public 2 / anon 20 / 共 30）。
6. **`.env.example` parity 两个反向坑**：① 带 env-external 标记的键不许同时是 Settings 字段；② 注释里出现「env-external」字样就会被当标记，措辞要避开。
7. **alembic 多语句迁移必须拆分执行**（sqlite3 驱动一次一条）→ 用 `_exec_script` 按分号拆；可回滚性测试改为在 `_REVISION_TABLES` 登记一行。
8. **新增调度 job 要同步三处**：`_JOB_OWNER` + `_expected_jobs` + switches，否则 `/scheduler/jobs` missing_jobs 天天红灯；job id 由测试从 `scheduler.py` 源码抽取核对。
9. **`/api/v1/` 文档标题不能带查询串**（`?status=` 会被路由对账当路径），参数说明放正文。
10. **`.gitignore` 目录规则带尾斜杠会杀死所有 `!` 例外**：`backend/data/` 让 git 整个目录不再进入，里面写多少白名单都无效。要给子目录开例外必须写成 `backend/data/*` 逐项排除。**不要用 `git add -f`** —— 强推进去的文件仍是 ignored 状态，后续改动不出现在 `git status` 里。
11. **structlog 三个坑**：① `event` 是 `logger.info(event, ...)` 的位置参数名，当关键字传会 `TypeError` 且只在运行时炸（静态扫不出）；② 默认写 **stdout**，脚本要输出可管道 JSON 时必须把 `logger_factory` 指到 stderr，且**只换 factory 不换 processors 链**（脱敏 processor 必须原样保留，SECURITY §3.3）；③ **`structlog.configure()` 改的是进程级全局配置，在测试里调用必须还原**，用 `@contextmanager` + `finally: structlog.configure(**saved)`。不还原会把全局 logger 钉在 pytest 的临时 stderr 捕获对象上，用例结束该对象关闭 → 后续文件集体炸 `ValueError: I/O operation on closed file`。**单跑各文件全绿、只在特定顺序下暴露**。
12. **`OBSERVABILITY.md §2.2` 的事件/命名空间总数要同步**：新增日志事件后，`test_documented_event_counts_match_reality` 会比对实测值（当前 317 事件 / 65 命名空间）。文档里附了与门禁同源的重算命令，别凭印象改。另注意：**文档的事件登记门禁是单向的**（只查「文档提到的必须存在」，不查「代码里的都登记了」），所以漏登记新事件不会红灯，得手工核对。
13. **排查跨文件测试污染的方法**：`pytest --collect-only -q` 拿到完整序号表，按进度行号 ×72 反推失败区间落在哪个文件，再用「疑似污染源 + 受害文件」两文件组合复现。**位置吻合不等于根因** —— 本次先误判为文档 parity 连带失败，用改动前文档实测只有 2 个失败（不是 14），推断才被否掉。
14. **ruff 没启 E402**：写 `# noqa: E402` 会被 RUF100 判为多余 noqa 而报错。
15. **新增 alembic 迁移要同步 `OPERATIONS.md §3.5`**：那里有「Alembic 迁移目前有 **N 个版本**」+ 逐个文件名清单，`test_operations_doc_parity::TestMigrationCountIsCurrent` 两条断言会核对数量与文件名。清单是回滚操作的依据，写错会让人 downgrade 到错误版本。
16. **新增采集源要同步五处文档**：`DATA_SOURCE_STRATEGY.md`（§2/§3/§5.2/§6.1/§8.4/§11/§12.9）、`OPERATIONS.md`（§4.3 门控 + §7.1 cron）、`SECURITY.md`（§10.2 域名白名单）、`.env.example`、测试真相函数。`test_operations_doc_parity` 的 `needs_key` 正则要覆盖 `bot_token|client_id|client_secret`。

## 八、当前分支与下一步

栈式分支（**合并必须按序，后面的 PR 才干净**）：
```
fix/p1-audit-hardening → docs/action-loop-design → feat/action-loop-m1 → feat/action-loop-m2
  (5 commits, P1 修复)     (1 commit, V3 设计稿)      (8 commits, M1)       (9 commits, M2)
```
四个均**未 push**。M2 的九个提交：`09c7c6c` T3.1 后端 / `ade9544` T3.1-3 前端 /
`b641c91` T3.2 回测+分桶 / `205b80c` 设计文档回填 / `565af55` 导出幂等 + json 污染 /
`7d2a28e` OPERATIONS 迁移清单 + F3 运维小节 / `98588e3` 日志重定向改上下文管理器（修 14 个跨文件污染）/
`660096b` 补 4 条负样本 + 引擎缺陷记录 / `ccfe9cb` OBSERVABILITY 登记 + 统计数字门禁。

1. **PR 栈式合并**，push 后依次开 PR。
2. **补全回测数据集到 50 条**（当前 19 条，重点补负样本）。
3. **修 🔴 引擎缺陷**（已发币仍判 FARM）：改评分结构 + 动权重校准协议，需单独立项。
4. **M3 = F4 领取监控**（§5）：`watched_wallets` + Alchemy webhook 地址匹配。

### 本仓 git ref 不落盘（必知）
`git commit` / `git branch` 退出码 0、reflog 也写了，但 `.git/refs/heads/` 下的
ref 会被环境反复删掉，导致分支还指向旧 commit 甚至"消失"。
**每次 commit 后跑 `sh .git/sync-head-ref.sh`**（幂等，自动从 reflog 取新 sha）。
底层是 `.git/pack-ref-helper.sh` 写 `packed-refs` —— 该文件**必须按 ref 名字典序排序**，
追加到末尾会让 git 二分查找静默忽略新行。

### owner 手工项（agent 不能代做）
- `.env` 里 `ALCHEMY_API_KEY` 改名 `ALCHEMY_WEBHOOK_SIGNING_KEY`（值不变）——旧键名让人误填 Data API key，导致合法回调永远 401。
- 启用推送：`NOTIFY_ENABLED=true` + `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID`（注意 alertmanager 也读它）或 `DISCORD_NOTIFY_WEBHOOK_URL`。
- Discord / Reddit 采集 Key：`DISCORD_BOT_TOKEN`+`DISCORD_CHANNEL_ID`、`REDDIT_CLIENT_ID`+`REDDIT_CLIENT_SECRET`+`REDDIT_USERNAME`（填进 `.env` 即启用，代码零改动）。
- `alembic upgrade head`。

## 九、遗留债务

### 公网部署前必须处理（08-31 审核遗留，owner 默认先交付 M1）
1. **P1-5 前端代理注入管理员密钥** —— 最急：推送上线后会把「面板越权」升级成「主动外呼越权」。
2. **P1-4 同步 IO 阻塞事件循环**。
3. 反代限流 `TRUSTED_PROXY_COUNT`；compose 默认密码。
4. 「诚实口径」的另一半：14 个采集器接运行时 `assert_url_allowed`。

### 小债
- README 的 WATCH 阈值写 40–64，真值 **≥50**（`scorer.py:50`）。
- `_score()` 四份复制（值一致、各有测试钉住，owner 拍板延后）。
- 反馈样本 0/200，需日常使用积累。
- Shadow 转正：等产出有意义 action 分布后做 `dual_run_compare`。
