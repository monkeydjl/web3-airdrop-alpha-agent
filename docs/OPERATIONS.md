# 运维 Runbook

> 配套文档：[OBSERVABILITY.md](OBSERVABILITY.md)（指标 / 日志 / 告警的真实清单）、
> [SECURITY.md](SECURITY.md) §9（安全事件响应）、
> [ENGINEERING_ROADMAP.md](ENGINEERING_ROADMAP.md) §15（部署与运维设计）。
>
> **本文档的写作规则**：只写**实测为真**的命令、路径、端口、指标名、接口名。
> 设计意图与未来规划一律进 §11「未实现 / 已规划」，不混进操作步骤。
>
> 上一版本本文档有 404 处编码损坏，重写时发现它同时还在**内容上**说谎：
> 19 个 Prometheus 指标名里 18 个不存在、4 个 API 路径不存在、
> 2 个"已提供的巡检脚本"根本没有这个文件、端口和数据库文件名都是错的。
> 具体清单见 §12「上一版本的失真记录」。

---

## 1. 当前部署形态（决定后面所有命令怎么写）

系统有三种跑法，运维命令**完全不同**。先确认自己在哪一种。

| 形态 | 怎么起 | 后端地址 | 数据库 | 当前状态 |
|---|---|---|---|---|
| **本地裸跑**（开发/单机） | `Start.bat` 或手动 uvicorn | `http://localhost:8002` | SQLite 文件 | ✅ 本机现在就是这个 |
| **单容器 compose** | `docker compose up -d` | `http://localhost:8002` | SQLite（挂载 `./data`） | 配置存在，本机 Docker 未运行 |
| **生产 compose** | `docker compose -f docker-compose.prod.yml up -d` | `http://localhost:18080`（经 nginx） | PostgreSQL 容器 `airdrop-db` | 配置存在，本机未跑起来 |

### 1.1 端口（**实测**，容易记错）

- 后端监听 **8002**，不是 8000。`backend/app/config.py` 默认 `port = 8002`，
  `docker/Dockerfile` 是 `EXPOSE 8002` + `--port 8002`。
- Next.js 前端 **3002**（`frontend-next/package.json` 的 `dev`/`start` 都写死 `--port 3002`）。
- 生产 compose 的宿主机端口刻意避开常用端口：nginx `18080→80`、
  前端 `13002→3002`、Grafana `13000→3000`、OTel exporter `18889→8889`。
  后端在生产 compose 里**不映射宿主机端口**（只在 compose 网络内以 `airdrop-web:8002` 暴露）。

> ✅ 2026-08-24：`scripts/deploy.sh` 与 `scripts/health-check.sh` **已修好**，
> 不再硬编码 8000（端口从 `.env` 的 `PORT`/`API_PORT` 读，默认 8002）。见 §3.4、§12.4。

### 1.2 数据库文件到底在哪（**实测，最容易踩的坑**）

`DB_PATH` 是**相对路径就相对进程工作目录解析**的。本机 `.env` 里配的是
容器内路径 `/app/data/app.db`，在 Windows 上这个"绝对路径"被解析成 `D:\app\data\app.db`
—— 也就是说**线上真正在用的库不在仓库目录里**：

```powershell
# 实测：确认当前进程真正连的是哪个文件
cd backend
& ".\venv\Scripts\python.exe" -c "from app.db import get_connection; c=get_connection(); print([r[2] for r in c.execute('PRAGMA database_list')]); c.close()"
# -> ['D:\\app\\data\\app.db']
```

仓库里的 `data/airdrop.db`（94 个项目）和 `backend/data/airdrop.db` 都是**过期副本**，
真库 `D:\app\data\app.db` 有 288 个项目、9.3 MB、27 张表。

**这直接让备份脚本备错文件** —— 见 §12.5，属于上线前必须处理的问题。

---

## 2. 日常检查项

### 2.1 每日

| 检查项 | 怎么查（实测可用） | 期望 |
|---|---|---|
| 服务活着 | `curl http://localhost:8002/health` | `{"ok":true,"status":"healthy","db":"ok"}` |
| 版本对 | `curl http://localhost:8002/version` | `version` / `app_env` / `llm_enabled` |
| 指标在吐 | `curl http://localhost:8002/metrics` | 有 `airdrop_` 开头的输出 |
| 管道跑过 | `airdrop_pipeline_runs_total{status="success"}` | 当日 ≥ 1 |
| 采集跑过 | `airdrop_collection_runs_total{source_id,status}` | 各启用源当日 ≥ 1 |
| 熔断没开 | `airdrop_fetcher_circuit_breaker_state` | `0`（CLOSED） |
| 库在长 | `airdrop_db_projects_total` / `airdrop_db_raw_projects_total` | 不长期持平 |
| 隔离积压 | `GET /api/v1/quarantine` 的 `count` | 别持续上涨 |
| 备份成功 | `backups/auto_backup.log` 最后一行 | `备份成功!` |

**指标名以 [OBSERVABILITY.md](OBSERVABILITY.md) §3.2 的 33 项清单为唯一权威。**
本文只引用其中确实存在的名字。

### 2.2 每周

- 看磁盘：`D:\app\data\app.db` 大小、`logs/backend.log` 大小、`backups/` 总量。
- **看日志文件大小**——目前**没有任何日志轮转**（§12.6），只能人工看。
- 翻一遍 `collection_logs` 里 `status='error'` 的记录，确认不是同一个源天天挂。
- 看备份数量：`auto_backup.ps1` 保留 7 天，正常应有 6–7 个 zip。

### 2.3 每月

- 依赖漏洞：`pip-audit`（CI 每次 PR 都跑，本地可复跑）。
- 备份恢复演练（§6.3）——**目前从未演练过**。
- 归档任务有没有真跑过：`GET /api/v1/archive/runs` 的 `summary.total_runs`
  —— **实测当前为 0，即归档从上线到现在一次都没被触发过**。
  注意这不是"数据还不够老"（那种情况也会留下一条 `raw_archived=0` 的成功记录，
  已实测），而是调度那一段从未被验证。处置办法见 §7.3。

  **两个端点要一起看**（2026-08-25 新增了后者）：

  | 组合 | 含义 | 处置 |
  |---|---|---|
  | `/scheduler/jobs` 里**有** `archive_cleanup` + `total_runs = 0` | 调度已就位，只是还没到过 03:00 | 等，或手工跑一次 |
  | `/scheduler/jobs` 里**没有** `archive_cleanup` + `total_runs = 0` | 任务根本没注册 | 查 `ARCHIVE_SCHEDULER_ENABLED` 与启动日志 |

  这两种此前**长得一模一样**（都只看得到 `total_runs = 0`），
  而处置动作完全不同。见 §5.4。

---

## 3. 启动、停止、部署

### 3.1 本地裸跑（当前形态）

```powershell
# 一键（会检查 Python、装依赖、建库、起前后端）
.\Start.bat

# 停
.\Stop.bat
```

手动起后端：

```powershell
cd backend
& ".\venv\Scripts\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port 8002
```

> 本机系统 Python 是 3.14.6，**跑不了本项目**；必须用 `backend\venv` 里的 3.11.9。
> 所有 Python 命令都要写成 `& ".\venv\Scripts\python.exe"`。
> 另外先设 `$env:PYTHONUTF8="1"`，否则中文日志会乱码。

手动起前端：

```powershell
cd frontend-next
npm run dev      # 开发，端口 3002
npm run build; npm start   # 生产模式，端口 3002
```

### 3.2 单容器 compose

```powershell
docker compose up -d --build
docker compose ps
docker compose logs -f backend
docker compose down
```

要点（都在 `docker-compose.yml` 里可核对）：

- 容器名 `airdrop-alpha-backend`，端口 `${API_PORT:-8002}:8002`。
- **必须有 `.env`**：镜像里没有 `.env`（被 `.dockerignore` 排除），compose 用
  `env_file: .env` 整体读入。历史上靠 `environment:` 白名单漏过 `API_KEY`、
  `AUTH_TOKEN_SECRET`，容器直接 CrashLoop。
- `APP_ENV` 默认 **production**，而生产自检要求 `API_KEY` 非空且 ≥32 字符，
  否则**拒绝启动**。本地想跑就显式设 `APP_ENV=development`。
- PostgreSQL 不默认启动，要加 profile：
  `docker compose --profile postgres up -d` 且设 `DB_BACKEND=postgres`。
- nginx 也在 profile 里：`docker compose --profile production up -d`。

### 3.3 生产 compose

```powershell
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml ps
```

包含 11 个服务：`nginx` `frontend` `web` `db` `prometheus` `alertmanager`
`grafana` `loki` `promtail` `otel-collector` `jaeger`。容器名前缀是
`airdrop-`（`airdrop-web` / `airdrop-db` / `airdrop-nginx` …），
**注意和单容器 compose 的 `airdrop-alpha-backend` 不是一套名字**，
写运维脚本时别混。

nginx 路由（`docker/nginx/nginx-http.conf`，实测的 location 列表）：

| 路径 | 转发到 | 备注 |
|---|---|---|
| `/` | frontend | |
| 静态资源正则 | frontend | js/css/图片/字体 |
| `/api/` | backend | |
| `/health` | backend `/health` | 限流 burst=5 |
| `/metrics` | backend `/metrics` | 限流 burst=5，**无鉴权** |

TLS 由上游反向代理终结，这里是 HTTP-only。

### 3.4 部署脚本的可用性

**2026-08-24 已修好，可以用了。** 三个脚本各自原本带一个不报错的缺陷，
全部修掉并加了门禁（`backend/tests/test_shell_scripts.py`，20 条）：

| 脚本 | 原来的缺陷 | 原来的表现 | 现在 |
|---|---|---|---|
| `deploy.sh` | 健康检查打 8000；5 行 `s/X/X/` 空操作 sed；生产用空 `API_KEY` 直接启动 | 报「服务启动超时」 | 端口从 `.env` 读；sed 全删；生产四项预检不通过就 `exit 1` |
| `health-check.sh` | 默认 `API_URL` 是 8000；硬查 `data/app.db` | 健康的系统被报成不健康 | 默认 8002；从 `.env` 的 `DB_PATH` 找库；新增预算账本检查 |
| `backup.sh` | 本地回退 `cp data/airdrop.db`（过期副本） | **报告"备份完成"，产出没用的备份** | 从 `DB_PATH` 找库，用 `sqlite3 .backup`；找不到就 `exit 1` |

> 这三个缺陷的共同点：**都不是功能缺失，而是把真实原因掩盖成另一个原因。**
> 最贵的不是它失败，是它指错方向 —— 照原来的 `deploy.sh` 跑，
> 你会去查容器日志、查依赖、查数据库，而问题在脚本自己那一行。

用法：

```bash
./scripts/deploy.sh dev     # 开发：模板默认值可直接跑
./scripts/deploy.sh prod    # 生产：先过 4 项预检（APP_ENV / API_KEY / AUTH_TOKEN_SECRET / CORS_ORIGINS）

API_URL=http://localhost:8002 ./scripts/health-check.sh
API_KEY=<管理员密钥> ./scripts/health-check.sh   # 带 key 才会检查 LLM 预算账本
```

**生产预检为什么是"停下"而不是"自动补"**：`API_KEY` / `AUTH_TOKEN_SECRET` /
`CORS_ORIGINS` 的正确值只有部署者知道。自动塞一个值进去，会让一个配错的
生产环境**看起来部署成功了**。这与 `config.py` 的判据一致 ——
能推断出唯一正确值的（种子开关）强制改，推断不出的（密钥、域名）拒绝启动。

**本地无法真跑**：这台 Windows 机器上 bash 不可用（Git bash
`CreateFileMapping` Win32 error 5，WSL `E_ACCESSDENIED`），Docker 守护进程也连不上。
所以 `bash -n` 语法校验只在 CI（Linux）上执行，本地自动跳过；
其余 20 条门禁（端口、空操作 sed、预检控制流、CRLF/BOM、账本检查）本地就能跑。
**首次在真 Linux 环境跑 `deploy.sh prod` 仍需人工盯一遍** —— 静态门禁能证明
它不再犯已知的那几个错，不能证明它在真容器里跑得通。

### 3.5 回滚

- **应用回滚**：重新部署上一版本镜像 tag（生产 compose 才有意义）。
- **配置回滚**：改回 `.env`，重启容器。配置只在启动时读，改完必须重启。
- **数据库回滚**：Alembic 迁移目前有 **9 个版本**（`backend/alembic/versions/`）：
  `0001_baseline_schema`、`0002_v2_new_tables`、`0003_archive_runs`、
  `0004_llm_spend_daily`、`0005_notify_log`（2026-08-31，决策推送）、
  `0006_participation`（2026-08-31，参与流水）、
  `0007_roi`（2026-08-31，收益台账）、
  `0008_eligibility_veto`（2026-09-01，资格门否决记录）、
  `0009_watched_wallets`（2026-09-02，领取监控自有地址）。
  ```powershell
  cd backend
  & ".\venv\Scripts\python.exe" -m alembic downgrade -1
  ```
  破坏性迁移的回滚请先做备份（§6）。
  回滚到 `0003` 之前会丢掉 LLM 花费账本 —— 预算拦截会转为 fail-closed
  （拒绝所有 LLM 调用并报 `ledger_unavailable`），不是静默放行。
  回滚掉 `0005` / `0006` 会丢掉推送历史与参与流水 —— 参与流水是用户操作
  数据（不可再生成），回滚前务必确认（notify_log 只是运行时日志，可放弃）。
  回滚掉 `0007` 会丢掉收益台账（`roi_entries` / `roi_outcomes`）——
  **这是全库最不可再生成的数据**：投入金额与工时是用户一条条手敲的，
  链上查不回来、也没有第二份来源。回滚前必须先备份（§6）。
  回滚掉 `0008` 只丢 `projects.veto`（资格门否决原因，重跑 `POST /run` 可重算）。
  回滚掉 `0009` 丢掉 `watched_wallets`（自有地址清单）—— 人工录入但**可重建**：
  地址在用户自己的钱包里、label 是自定义备注，比 `0007` 低一档，仍建议先导出。
  注意 Alchemy 控制台侧的地址清单**不受回滚影响**（MVP 手工维护），回滚后
  webhook 仍会收到那些地址的事件，只是本地匹配不到、不再产生领取候选通知
  （事件类型 airdrop_candidate —— 刻意不加反引号：§10.6 的指标门禁按反引号包裹的
  下划线标识符抓指标名，包起来会被当成幽灵指标）。

#### 给既有库加列的两处登记（漏一处就线上炸）

`projects` / `raw_projects` / `interactions` 这几张表的**新增列**必须同时落在两处：

1. `db.py` 的建表 DDL（新库靠它）；
2. `db.py::init_db` 里的 `_add_column_if_not_exists(...)`（**既有库靠它**）。

只改 DDL 不改第 2 处的失效方式很隐蔽：建表语句是 `CREATE TABLE IF NOT EXISTS`，
既有库表已存在就整条跳过，列永远补不上。CI 是全新 checkout、表由 DDL 现建，
**门禁全绿**；但任何已跑过的开发 / 生产库一升级就在写入时报
`table projects has no column named <col>`。

后果不止是一次报错：`repository.save` 失败会让整个 pipeline run 变
`status="failed"`（评分本身是成功的，只是落不了库），
表现为「升级后所有分析任务突然全挂」。

ADR-015 的 `veto` 列就踩了这个坑，由 golden 回归集捕获（12 failed）。
`alembic` 迁移**不能替代**第 2 处 —— 迁移在滚动 baseline 下做了存在性判断，
且不是所有部署路径都跑 `alembic upgrade`。

### 3.6 Opportunity Shadow 灰度

Shadow 是**非权威旁路评估**，不替换 `score` 与 `label`，assessment 只追加不改写。

1. 先 `OPPORTUNITY_SHADOW_ENABLED=false`、`OPPORTUNITY_SHADOW_SAMPLE_RATE=0.0`。
2. 核对 `/health` 的 `opportunity_model_version`、`opportunity_shadow_enabled`、
   `opportunity_shadow_sample_rate` 三个字段（**实测存在**）。
3. 开 `true`、采样率设 `0.05`，重启。
4. 观察一个完整调度窗口，看 Shadow 的 5 个指标：
   `airdrop_opportunity_shadow_projects_total`、
   `airdrop_opportunity_shadow_assessments_total`、
   `airdrop_opportunity_shadow_duration_seconds`、
   `airdrop_opportunity_shadow_enabled`、
   `airdrop_opportunity_shadow_sample_rate`。
5. 逐步提采样率。项目 ID 分桶是确定性的，所以高采样率是低采样率的**单调超集**——
   低采样率被选中的项目在高采样率下仍然被选中。
6. 回滚：设回 `false` 重启即可，**不需要 schema 回滚**。

### 3.7 PostgreSQL 验证（必须按顺序，不能并行）

这几个脚本共享测试库状态：

```powershell
cd backend
$env:DATABASE_URL='postgresql://airdrop:<password>@127.0.0.1:5433/airdrop_test'
& ".\venv\Scripts\python.exe" scripts\verify_postgres.py
& ".\venv\Scripts\python.exe" scripts\verify_opportunity_shadow.py
& ".\venv\Scripts\python.exe" scripts\verify_init_db_concurrency.py --database-url $env:DATABASE_URL --workers 4 --rounds 2
& ".\venv\Scripts\python.exe" scripts\verify_opportunity_calibration.py --as-of 2026-10-15T00:00:00Z
```

> 密码从 `.env` / secret store 取，**不要写进文档或命令历史**。

### 3.8 Opportunity 结果校准

校准是**观察性**的，`no auto-apply`：门禁通过**不会**改动生产权重、标签或决策。

```powershell
cd backend
& ".\venv\Scripts\python.exe" scripts\calibrate_opportunity.py --as-of 2026-10-15T00:00:00Z --output-dir reports\opportunity-calibration
& ".\venv\Scripts\python.exe" scripts\verify_opportunity_calibration.py --as-of 2026-10-15T00:00:00Z
```

门禁语义：`pass` = 报告可进入评审；`insufficient_data` = 未达最小样本/项目门槛；
`data_quality_only` = 只有质量报告、不给推荐结论。

生产校准读取是**只读**的，不会改 assessment、interaction、评分或标签。
项目的 wallet cohort 数量不均时用 `project_equal` 作为推荐基准，
避免单个高频项目主导结果；`cohort_weighted` 留作运营量级参考。
报告只输出聚合值 —— 项目、assessment、cohort、钱包、URL、备注、私有理由都不得出现。

采纳需要评审并**新建 model/profile 版本**，再走 expand-and-contract 发布与回滚计划，
**绝不原地改已有版本**。

### 3.9 历史回测（F3 / ACTION_LOOP_DESIGN §4）

把 T0 前的公开信息灌进评分决策引擎，看它当年会不会抓到后来真发了币的项目。

```powershell
cd backend
$env:PYTHONPATH="."
& ".\venv\Scripts\python.exe" scripts\run_backtest.py                    # 人读报告
& ".\venv\Scripts\python.exe" scripts\run_backtest.py --json             # 机器可读（stdout 只有 JSON）
& ".\venv\Scripts\python.exe" scripts\run_backtest.py --export-samples   # 结论写入 roi_outcomes
```

安全性：走规则引擎（`enable_llm=False`，ADR-001）保证可复现，
`save_to_db=False` **不写 projects 表** —— 已发币项目混进去会让 Dashboard
显示一堆过期机会。`--export-samples` 幂等，重复跑不会重复写。

**读报告时必须注意三件事**：

1. 数据集当前 **19/50 条**（标 `pending_expansion=true`，报告会自动打警告）。
   样本量不足时命中率置信区间很宽，**不足以支撑权重调整**。
2. 负样本已补到 5 条、覆盖三类（迟迟不发币 / 明确不做代币激励 / 已发币无追加
   分配），`fpr` 分母够了。若负样本被删回 1~2 条，报告会重新在 `fpr` 后面标
   「分母仅 N 条，不可读」—— 那时不要读那个百分数。
3. **当前误报率 100%（5 个负样本全被判 FARM），这是引擎的已知缺陷，不是数据
   问题**，见下方。

**🔴 已知缺陷：已发币项目仍被判 FARM**

Chainlink 68 / Worldcoin 69 分越过 FARM 阈值 65。空投信号维度（评分八维中的
airdrop signal，注意它是 subscore 名、不是 Prometheus 指标）已正确压到 20 分
（`no_token_yet=false` 生效），但加权求和模型下压不住其余七维 ——
execution / competition / transparency 各 100、team 85~95 把总分抬起来了。

对本系统而言「已发币 = 无空投机会」应是**否决条件**，而非可被其他维度补偿的
一项打分。修复要改评分结构、会牵动权重校准协议，**未在 M2 内做**，已用
`xfail(strict=True)` 钉在 `tests/test_backtest.py` 里（修好会变 XPASS 报错，
逼人回来删标记）。

**运维影响**：生产库若混入已发币的成熟项目，Dashboard 可能把它们显示成 FARM。
现有缓解手段是 `collectors/noise.py` 的共享 denylist（采集阶段挡掉蓝筹）
\+ `scripts/purge_noise_projects.py` 清理存量。回测这个结论说明
**不能只依赖评分兜底，denylist 仍是必需的第一道防线**。

**回测样本不解锁校准门禁**：导出的样本 `source='backtest'`，
`check_gate()` 只数 `live` 桶（真实反馈 + 人工录入）。两桶计数都在
`GateResult.total_by_source` 里照实暴露，但灌多少历史数据都不会让门禁通过 ——
否则扩充数据集就能绕过「有效样本 ≥200 / FARM ≥30」的协议约束。

### 3.10 收益台账（F3）

`/api/v1/roi/*` 六个端点，前端在 `/portfolio` 页。数据是**人工录入**的，
诚实边界写在 `API_SPEC §40`：`amount_usd` 不做链上取价、`tx_hash` 只存档
不验证、汇总不给时间定价（不引入凭空捏造的时薪）。

零成本时 `roi_ratio` 返回 `null`，前端渲染「—」。不返回 `0`（会被读成
"没赚没赔"）也不返回 `inf`（污染下游聚合）。

---

## 4. 故障处理

每条都是：症状 → 排查 → 止损 → 根因 → 恢复。
**引用的指标名和接口路径都经过实测**。

### 4.1 每日分析管道失败

**症状**：`airdrop_pipeline_runs_total{status="error"}` 增长；
告警 `PipelineConsecutiveFailures` 或 `PipelineFailureRate` 触发。

**排查**
1. 日志按事件名过滤（不是按自由文本）：
   `pipeline.completed` / `orchestrator.pipeline_start` / `api.run.failed`。
   ```powershell
   Select-String -Path logs\backend.log -Pattern '"event":"api.run.failed"' | Select-Object -Last 5
   ```
2. 看 `airdrop_pipeline_duration_seconds` 是不是卡在长尾桶（上界到 60s）。
3. 查 `logs` 表（实测 196 行，有真实写入）：
   ```sql
   SELECT * FROM logs ORDER BY rowid DESC LIMIT 20;
   ```

**止损**：手动重跑一次 `POST /api/v1/run`（**需要管理员凭据**，见 §5.2）。

**根因**：外部源全挂 / DB 写失败 / 配置错误 / 代码缺陷。

**恢复**：修完再跑一次 `POST /api/v1/run`，确认 `airdrop_pipeline_runs_total{status="success"}` +1。

### 4.2 SQLite `database is locked`

**症状**：日志里出现 `database is locked`。

**排查**
1. 是不是有第二个 writer 在跑（另一个 uvicorn / 另一个脚本 / pytest）？
2. 磁盘满没满。
3. 有没有长事务。

**止损**：只留一个 writer，重启服务。

**恢复**：重启；库真损坏了走 §6.2。

**升级**：频繁出现就该切 PostgreSQL（`DB_BACKEND=postgres` + `--profile postgres`）。

### 4.3 采集源故障

采集共注册 **10 个源**。**「注册了」不等于「在采」** —— 每个源要真正执行，
必须三个条件同时成立：

1. `XXX_ENABLED` 开关为真；
2. 需要 Key 的源，Key 已配置；
3. `data_sources.enabled` 为真（运维开关，见 §7.1）。

前两条合起来就是端点 `GET /api/v1/collections/sources` 返回的 `config_ready`。

<!-- collection-ready:begin -->
| 源 | 开关 | 需要 Key |
|---|---|---|
| `defillama` | `DEFILLAMA_ENABLED` | ❌ 免费无 Key |
| `coingecko` | `COINGECKO_ENABLED` | ❌ 免费额度够用 |
| `github` | `GITHUB_ENABLED` | ✅ `GITHUB_TOKEN` |
| `cryptorank` | `CRYPTORANK_ENABLED` | ✅ `CRYPTORANK_API_KEY` |
| `etherscan` | `ETHERSCAN_ENABLED` | ✅ `ETHERSCAN_API_KEY` |
| `rootdata` | `ROOTDATA_ENABLED` | ✅ `ROOTDATA_API_KEY` |
| `twitter_kol` | `TWITTER_ENABLED` | ✅ `TWITTER_BEARER_TOKEN` |
| `twitter_keyword` | `TWITTER_ENABLED` | ✅ `TWITTER_BEARER_TOKEN` |
| `galxe` | `GALXE_ENABLED` | ✅ `GALXE_API_KEY` |
| `layer3` | `LAYER3_ENABLED` | ✅ `LAYER3_API_KEY` |
| `discord` | `DISCORD_ENABLED` | ✅ `DISCORD_BOT_TOKEN` + `DISCORD_CHANNEL_ID` |
| `reddit` | `REDDIT_ENABLED` | ✅ `REDDIT_CLIENT_ID` + `REDDIT_CLIENT_SECRET` + `REDDIT_USERNAME` |
| `medium` | `MEDIUM_ENABLED` | ❌ RSS 免费无需 Key |
| `mirror` | `MIRROR_ENABLED` | ❌ Arweave 公开读无需 Key |
<!-- collection-ready:end -->

> 注意两个 twitter 源**共用同一个开关** `TWITTER_ENABLED`：关掉它会同时停掉
> KOL 轮询和关键词搜索，没法只留一个。

**代码默认值**（不含任何 `.env`）：只有 `defillama` / `coingecko` / `github`
的开关默认开，其余 7 个默认关。所以一台没配 `.env` 的机器上，实际能跑的源
比这张表短得多。

**本机当前实测**（2026-08-23，`GET /api/v1/collections/sources`）：
`config_ready=true` 的有 5 个 —— `defillama` `coingecko` `github`
`cryptorank` `etherscan`；另外 5 个都是 false（开关关且无 Key）。
`data_sources` 表里也只有这 5 个源有记录。

> ⚠️ 排查「为什么没发现新项目」时**先看这个端点的 `config_ready`**。
> 不看的话会去翻一个从未运行过的源的日志，找不到任何错误，
> 然后误判成"采集是好的、是分析出了问题"。

**症状**：`airdrop_collection_runs_total{source_id,status}` 的 error 计数增长；
或 `airdrop_fetcher_circuit_breaker_state` 变成 `1`(HALF_OPEN) / `2`(OPEN)。

> ⚠️ `airdrop_fetcher_circuit_breaker_state` **没有 `source_id` 标签**，
> 它是全局一个值。想区分哪个源挂了要靠 `airdrop_collection_runs_total` 的
> `source_id` 标签或 `collection_logs` 表。

**排查**
1. 查该源最近几次运行：
   ```sql
   SELECT source_id, status, started_at, finished_at, items_collected, error_message
   FROM collection_logs WHERE source_id='X' ORDER BY started_at DESC LIMIT 5;
   ```
2. 熔断参数（实测配置）：连续 **5** 次失败打开，**60 秒**后半开探测。
3. 限流是**令牌桶**（`backend/app/collectors/rate_limiter.py` 的 `TokenBucketRateLimiter`），
   超限会**自动等待**，不报错、不需要人工干预。

**止损**
- 单源挂了**不影响其他源**，也不中断分析管道，只是发现量下降。
- 手动补一次采集：`POST /api/v1/collections/{source_id}/trigger`
  —— 注意路径是 `/{source_id}/trigger`，**不是** `/trigger/{source_id}`。
- 关掉某个源：`PATCH /api/v1/collections/{source_id}`（运维开关落 `data_sources.enabled`，
  调度器每次执行前会读它）。

**恢复**：熔断窗口过后自动半开重试；下一个 cron 周期自动重跑。

> ⚠️ `POST /api/v1/collections/{source_id}/trigger` 是**同步执行真实采集**的：
> 一次调用会真的落 `raw_projects` / `project_signals` / `collection_logs`。
> 排查时别拿它当"探活"用。

### 4.4 LLM 相关

**当前 LLM 是关闭的**（实测 `/version` 的 `llm_enabled=false`、
`/api/v1/llm/status` 的 `enabled=false`），所以下面只在开启后适用。

**症状**：`airdrop_llm_errors_total{model}` 上涨，告警 `HighLLMErrorRate`。

**排查**：看 `airdrop_llm_requests_total{model}` 与 `airdrop_llm_duration_seconds`
（桶上界到 30s）；日志事件前缀 `llm.`。

**止损**：`LLM_ENABLED=false` 重启，回落到**规则引擎**路径（离线可用、无外部依赖）。

> ✅ **`LLM_DAILY_BUDGET_USD` 现在真的会拦（2026-08-24 实现）。**
> 此前它只被两个只读接口读出来展示、不拦任何调用（旧版本这里的警告写的就是这件事，
> 保留在 §12.3 里作为记录）。
>
> 现在的行为：每次成功调用的 token 与估算成本写入 `llm_spend_daily` 表（按 UTC 日），
> 下一次调用**在发出任何网络请求之前**查当日累计，达到或超过预算就拒绝，
> 降级回规则引擎。
>
> **超预算时你会看到什么**：
> - 日志 `llm.budget.exceeded`（含当日花费与预算）、`llm.refused_by_budget`
> - 指标 `airdrop_llm_budget_blocked_total{reason="budget_exceeded"}` 上涨
> - 指标 `airdrop_llm_spend_today_usd` ≥ `airdrop_llm_budget_usd`
> - 项目解读退回 `mode: "rule"`（这是预期的降级，不是故障）
>
> **要临时放开**：调大 `LLM_DAILY_BUDGET_USD` 重启即可；设为 `0` 表示不限额
> （不是"全部拒绝"）。
>
> **两个容易误判成故障的现象**：
> 1. 账单比预算多一点点。拦截在调用前、成本在调用后才知道，所以最后一次被放行的
>    调用会把当日花费推过线，超出量最多是单次调用成本。这是软上限。
> 2. `airdrop_llm_budget_blocked_total{reason="ledger_unavailable"}` 上涨 =
>    **账本读不出来**（DB 锁 / 磁盘满 / 表缺失），此时策略是拒绝调用（fail closed）。
>    先查 `llm.budget.ledger_unavailable` 日志和 SQLite 是否可写，不要先怀疑预算配置。
>
> **Agent 路径的同一件事（2026-08-25 补齐）**：流水线里的 Agent 调 LLM
> 走的是另一条入口（`BaseAgent.llm_enhance`），此前它拿不到拒绝原因，
> 预算拦截和接口全挂在日志里**长得一模一样**（都只有一条 `llm.failed`），
> 只能靠指标间接分辨。现在已分流：
>
> | 场景 | 日志事件 | 级别 |
> |---|---|---|
> | 预算耗尽（预期降级） | `llm.budget_refused`（带 reason） | info |
> | 账本不可读 → fail-closed | `llm.ledger_fail_closed` | **error**（对应上面 critical 告警） |
> | 接口/网络真失败 | `llm.failed` | error |
>
> 判读口诀：先看有没有 `budget_refused` / `ledger_fail_closed` ——
> 有前者是"今天花完了"，有后者是"账本坏了"，都没有才轮到怀疑接口本身。
>
> 另一道独立的成本闸门仍然在：`/api/v1/run` 的请求频率限制 ——
> LLM 开启时每小时 **1** 次，关闭时每小时 **10** 次
> （`backend/app/rate_limit.py` 的 `_expensive_limits`）。它管频率，预算管金额，
> 两者是不同的轴。

### 4.5 库内项目不增长

**症状**：`airdrop_db_projects_total` 长期持平。

**排查**（按这个顺序）
1. 分析调度器有没有跑：`airdrop_pipeline_runs_total` 当日有没有计数。
2. 采集调度器有没有跑：`airdrop_collection_runs_total` 当日有没有计数。
3. 采集到了但没立项 → 看 `raw_projects`：
   ```sql
   -- 未处理的原始记录堆积（实测当前 509 条未处理 / 106 条已处理）
   SELECT processed, COUNT(*) FROM raw_projects GROUP BY processed;
   -- 被判为噪声隔离（实测当前 3 条）
   SELECT COUNT(*) FROM raw_projects WHERE quarantined = 1;
   -- 低于分析阈值被过滤
   SELECT COUNT(*) FROM raw_projects WHERE discovery_score < 0.3;
   ```
   `DISCOVERY_SCORE_ANALYSIS_THRESHOLD` 实测为 **0.3**。
4. 全是重复命中（`dedup_key` 撞了）也会表现为不增长，这属于正常。

**止损**：`POST /api/v1/run` 手动跑一轮分析。

**根因**：调度器停 / 外部源全挂 / 全部去重命中 / `discovery_score` 阈值偏高 / 噪声过滤过严。

### 4.6 隔离（quarantine）积压

**症状**：`GET /api/v1/quarantine` 的 `count` 持续上涨。

**处理**：`GET /api/v1/quarantine` 看 `items`（含隔离原因），
误判的用 `POST /api/v1/quarantine/release` 放行。
两个接口都在 `ADMIN_ONLY_PREFIXES` 里，需要管理员凭据。

### 4.7 健康检查失败

**症状**：`/health` 非 200 或超时；告警 `BackendDown`。

**排查**
1. 进程/容器还在不在（`docker compose ps` 或看进程）。
2. 端口有没有被占（**8002**）。
3. DB 连不连得上——`/health` 的 `db` 字段会直接告诉你（实测取值 `"ok"`）。

`/health` 的真实字段（实测 11 个，**注意它是平铺的，没有 `data` 包一层**）：
`ok` `status` `version` `db` `db_backend` `auth_required` `feedback_enabled`
`quarantined_raw` `opportunity_model_version` `opportunity_shadow_enabled`
`opportunity_shadow_sample_rate`。

> 除 `POST /api/v1/auth/anonymous` 外，`/api/v1/*` 都是 `{ok, data}` 信封；
> 但 **`/health` 是平铺的**，`/version` 是信封。写监控脚本时别搞错。

### 4.8 评分被质疑

**排查**
1. `GET /api/v1/projects/{project_id}` 看各 agent 明细与理由。
2. 查 `logs` 表里该项目的 agent 事件（`agent.started` / `agent.completed`）。
3. 判断是数据问题、权重问题，还是规则缺陷。

**权重与阈值的权威位置**：8 项权重 Σ=1.0（启动断言，ADR-006）；
标签阈值 `LABEL_THRESHOLDS` 在 `backend/app/agents/scorer.py`
= `[(65,"FARM"),(50,"WATCH"),(0,"IGNORE")]`；当前 `weight_version = "v1.2"`。

> **没有 `POST /api/v1/re-score/{project_id}` 这个接口**（实测 OpenAPI 里不存在）。
> 唯一的重算入口是 `PATCH /api/v1/projects/{project_id}/funding?rescore=true`
> ——改完资金字段顺带重算，以及重跑整条管道的 `POST /api/v1/run`。
> 全量重算走脚本：`cd backend; & ".\venv\Scripts\python.exe" scripts\rescore_all.py`。

**信号覆盖率的现实**（实测，解释为什么有些分数看着"猜的"）：
`token_listed` 268 条、`tvl` 165 条、`github_activity` 30 条、`chain_activity` 仅 4 条。
`execution` 维度（权重 13%）在多数项目上**缺少真实信号**；
confidence ≥0.8 的项目只有 9 个。这不是缺陷，是数据源覆盖不足。

---

## 5. 鉴权与访问控制（运维必须知道的边界）

### 5.1 三种身份

| 身份 | 怎么拿 | 能做什么 |
|---|---|---|
| 无凭据 | — | 只能访问公开端点 |
| 匿名 token | `POST /api/v1/auth/anonymous` | 读类接口 |
| 管理员 | `X-API-Key: <API_KEY>` | 全部，含 `ADMIN_ONLY_PREFIXES` |

### 5.2 管理员专属前缀（实测 `backend/app/auth.py` 的 `ADMIN_ONLY_PREFIXES`）

下面这份清单由 §10.6 的门禁与代码逐项比对，**改代码不改这里会让 CI 变红**。
注意它们是**前缀**，不都是真实路由（例如 `/api/v1/re-score` 就没有对应路由，
见 §12.2）。

<!-- admin-prefixes:begin -->
- `/api/v1/run`
- `/api/v1/re-score`
- `/api/v1/quarantine`
- `/api/v1/export`
- `/api/v1/import`
- `/api/v1/settings`
- `/api/v1/archive`
- `/api/v1/scheduler`
- `/api/v1/notify`
- `/api/v1/watched-wallets`
<!-- admin-prefixes:end -->

匿名 token 打这些前缀下的路径拿 **403**。

> `/api/v1/watched-wallets`（F4 领取监控，§3.10）的锁法与其它项**不同源**：
> 别的前缀锁的是"会改状态或花钱"的写操作，它锁的是**读**。一份「这个人有哪些
> 钱包」的清单配合公开链上数据就能还原完整持仓与交易史，所以 `GET` 也一起锁 ——
> 只锁写在这里没意义。

另有一层**按方法**的规则（`ADMIN_ONLY_METHOD_RULES`），用于"同一路径读开放、
写受限"的两处 —— 前缀匹配表达不了它们：

<!-- admin-method-rules:begin -->
| 路径 | 受限方法 | 开放方法 | 为什么 |
| --- | --- | --- | --- |
| `/api/v1/collections/*` | POST / PATCH / PUT / DELETE | GET / HEAD | trigger 会**真的跑采集**并消耗第三方 API 配额；PATCH 能改采集源开关与 cron。但 `/collections/sources` 是只读就绪状态，首页和 `/discoveries` 页在用，整前缀锁会让匿名角色页面直接空掉。 |
| `/api/v1/projects/{project_id}/funding` | POST / PATCH / PUT / DELETE | GET / HEAD | PATCH 改融资数据并触发重算。通配段在路径**中间**，前缀匹配写不出来；同一路径的 GET 是普通只读明细。 |
<!-- admin-method-rules:end -->

`/collections/` 用的是**方法白名单取反**（GET/HEAD 之外全锁），
而不是逐条列出 trigger 和 PATCH —— 新加一个写端点时默认就是受保护的。
**一个需要人记得来登记的白名单，迟早会漏一条**（§12.7 记的就是这么漏的）。

排障提示：这两处拿到 **403** 时先看用的是哪种凭据 —— 是 `X-API-Key`
（管理员）还是匿名 `Bearer`。前端页面走 `proxy.ts` 由服务端注入管理员 key，
所以页面上能点的操作不受影响；直接用 curl 带匿名 token 会 403，那是预期行为。

### 5.3 无鉴权就能访问的端点（实测）

`/health`、`/version`、`/metrics`、`/docs`、`/redoc`、`/openapi.json`、
`POST /api/v1/auth/anonymous`、`/api/v1/webhook/*`。

`/metrics` 无鉴权是**刻意的**（Prometheus 抓取方便），靠网络边界保护；
生产 compose 里后端不映射宿主端口，只有 compose 网络内和 nginx 能到。

> ⚠️ `/docs` `/redoc` `/openapi.json` 在**任何环境都开着**
> （`backend/app/main.py` 里是写死的 `docs_url="/docs"`，不看 `APP_ENV`）。
> 生产环境等于把完整 API 结构公开。见 §12.8。

### 5.4 调度器任务表（2026-08-25 新增）

`GET /api/v1/scheduler/jobs`（管理员专用）。运维台 `/ops` 页也展示同一份数据。

排查任何"某个定时任务好像没在跑"时，**这是第一个该看的地方**。
`UnifiedScheduler.get_jobs()` 一直存在，但此前没有任何路由暴露它 ——
所以"任务根本没注册"这件事在界面上完全不可见，只能靠翻数据库发现。
归档那次（§7.3）就是这么发现的。

#### `scheduler_state` 的四个取值

「任务表是空的」有四种原因，处置动作完全不同：

| 取值 | 含义 | 处置 |
|---|---|---|
| `not_initialized` | 调度器对象不存在（`APP_ENV=testing` 时正常） | 生产环境出现即异常，查启动日志 |
| `disabled` | 三个开关全关，调度器没启动 | 正常配置，确认是否有意 |
| `running` 且 `job_count = 0` | 开关开着、调度器在跑，一个任务都没注册 | **真故障**，查启动日志 |
| `read_error` | 读任务表本身失败 | 诊断接口自己坏了，看 `read_error` 字段 |

`read_error` 时 `job_count` 与 `missing_jobs` 是 **`null`** 而不是 `0` / `[]` ——
与 `/api/v1/llm/status` 的 `spend_today_usd` 同一口径：
**读不出来和"确实没有"是两件事**，都返回 0 会让一个坏掉的诊断接口
看起来像一个空闲的调度器。

#### `missing_jobs` 的判据（这一栏最容易做错）

只统计**开关开着、且采集器已启用，却没出现在任务表里**的任务。

采集任务的"应当注册"要问 `collector_registry`，不能只看
`COLLECTION_SCHEDULER_ENABLED` —— `scheduler.py:121` 的真实条件是
`if collector and collector.is_enabled()`，**没配 API key 的源不会注册，
那是正常的**。第一版只看总开关，本机实测报出 5 个假缺失。

方向错了比漏报更坏：**一栏天天亮红灯的告警等于没有这一栏** ——
人会先学会忽略它，然后在真出事那天照样忽略。

#### 本机实测（2026-08-25，开发配置）

```
state=running  registered=7  expected=7  missing=[]
  collect_etherscan     2026-08-25T18:00:00+00:00  [COLLECTION_SCHEDULER_ENABLED]
  archive_cleanup       2026-08-26T03:00:00+00:00  [ARCHIVE_SCHEDULER_ENABLED]
  analysis_run_queue    2026-08-26T08:00:00+00:00  [SCHEDULER_ENABLED]
  collect_defillama     2026-08-26T08:00:00+00:00  [COLLECTION_SCHEDULER_ENABLED]
  collect_github        2026-08-26T08:30:00+00:00  [COLLECTION_SCHEDULER_ENABLED]
  collect_coingecko     2026-08-26T09:00:00+00:00  [COLLECTION_SCHEDULER_ENABLED]
  collect_cryptorank    2026-08-26T09:15:00+00:00  [COLLECTION_SCHEDULER_ENABLED]
```

7 个而不是 12 个：galxe / layer3 / rootdata / twitter_kol / twitter_keyword
没配凭据，不注册是正常的。

注意分析任务的真实 id 是 **`analysis_run_queue`**，不是 `daily_analysis`
（后者是我凭印象编的名字，实测才发现 —— 门禁
`TestJobIdsMatchTheScheduler` 现在直接从 `scheduler.py` 源码抽 id 核对）。

**这个端点不触发任何任务**。手动跑归档仍用 `scripts/archive_raw_data.py`。

---

## 6. 备份与恢复

### 6.1 现在真正在跑的备份

`scripts/auto_backup.ps1`，每日 02:00 执行，实测**确实在产出**：

```
backups/auto/airdrop_auto_20260817_215745.zip   1920 KB
backups/auto/airdrop_auto_20260818_020002.zip   2025 KB
backups/auto/airdrop_auto_20260820_020002.zip   2572 KB
backups/auto/airdrop_auto_20260821_020001.zip   2711 KB
backups/auto/airdrop_auto_20260822_020001.zip   3073 KB
backups/auto/airdrop_auto_20260823_020001.zip   3431 KB
```

保留 7 天，日志在 `backups/auto_backup.log`。

**它备份的是 PostgreSQL 容器 `airdrop-db`（`pg_dump` custom + SQL 双格式）。**
Docker / `airdrop-db` 不在的时候它直接退出码 1 跳过，日志里能看到：

```
[2026-08-19 02:00:02] 备份开始: airdrop_auto_20260819_020002
[2026-08-19 02:00:02] 错误: airdrop-db 容器未运行，跳过备份
```

⚠️ 那次失败**留下了一个空目录** `backups/auto/airdrop_auto_20260819_020002/`
到现在还在——脚本先 `New-Item` 建目录、之后才检查容器，失败路径不清理。
不致命，但会让"备份目录里有 7 个条目"这种粗略判断产生误导。

### 6.2 恢复（PostgreSQL）

```powershell
# 1. 解压
Expand-Archive backups\auto\airdrop_auto_<ts>.zip -DestinationPath restore-tmp
# 2. 停应用（别让它一边写一边恢复）
docker compose -f docker-compose.prod.yml stop web
# 3. 恢复（custom 格式，可选择性恢复）
docker cp restore-tmp\<name>\airdrop_pg.dump airdrop-db:/tmp/r.dump
docker exec airdrop-db pg_restore -U airdrop -d airdrop --clean --if-exists /tmp/r.dump
# 4. 起应用
docker compose -f docker-compose.prod.yml start web
# 5. 验证
curl http://localhost:18080/health
```

### 6.3 恢复演练

**从未做过。** 上线前至少做一次：恢复到独立测试库，
核对 `projects` / `raw_projects` / `project_signals` 行数与备份当天一致。
不演练的备份等于没有备份。

### 6.4 RPO / RTO（当前实际能力，不是目标值）

| 项 | 现状 | 依据 |
|---|---|---|
| RPO | **24 小时** | 每日 02:00 一次全量，无 WAL 归档 |
| RTO | 未测量 | 没做过恢复演练，无法给数字 |

---

## 7. 调度任务

四个调度器都在 `backend/app/scheduler.py` 的统一调度器里注册，
时区统一 **UTC**，`misfire_grace_time = 3600` 秒，`coalesce=True`，`max_instances=1`。

### 7.1 采集任务（实测 cron）

下表由 §10.6 的门禁逐条与 `settings` 实际值比对。

<!-- collection-cron:begin -->
| 源 | cron (UTC) |
|---|---|
| `defillama` | `0 8 * * *` |
| `github` | `30 8 * * *` |
| `coingecko` | `0 9 * * *` |
| `cryptorank` | `15 9 * * *` |
| `rootdata` | `45 9 * * *` |
| `twitter_kol` | `0 * * * *` |
| `twitter_keyword` | `*/15 * * * *` |
| `etherscan` | `0 */6 * * *` |
| `galxe` | `0 10 * * *` |
| `layer3` | `30 10 * * *` |
| `discord` | `0 */3 * * *` |
| `reddit` | `30 * * * *` |
| `medium` | `0 */6 * * *` |
| `mirror` | `30 */6 * * *` |
<!-- collection-cron:end -->

注册条件是**两道闸**：`COLLECTION_SCHEDULER_ENABLED=true`（实测 `True`）
且 collector 自身 `is_enabled()`。每次执行前还会再读一次
`data_sources.enabled`（运维开关），关了就跳过并记 `unified_scheduler.skip_operator_disabled`。

### 7.2 分析任务

`SCHEDULER_ENABLED = True`，cron 表达式 `0 8 * * *`，
单轮上限 `ANALYSIS_RUN_LIMIT = 100`。

⚠️ `COLLECTION_AUTO_RUN_ENABLED = False`（实测）——
**采集完不会自动接着跑分析**，两条链是解耦的，各按自己的 cron 走。

### 7.3 归档任务

`ARCHIVE_SCHEDULER_ENABLED = True`，cron 表达式 `0 3 * * *`（UTC），
`misfire_grace_time = 3600`。

保留策略（实测 `GET /api/v1/archive/runs`）：

| 策略 key | 表 | 保留天数 | 当前总量 | 待归档 |
|---|---|---|---|---|
| `raw_processed` | `raw_projects` | 30 | 106 | 0 |
| `raw_unprocessed` | `raw_projects` | 90 | 509 | 0 |
| `signals` | `project_signals` | 90 | 2261 | 0 |
| `logs` | `collection_logs` | 90 | 20 | 0 |

归档表保留期：`RAW_ARCHIVE_RETENTION_DAYS=180`、`SIGNALS_ARCHIVE_RETENTION_DAYS=365`。

#### 归档从未执行过 —— 但原因不是上一版说的那个

`archive_runs` 表 **0 行**，`raw_projects_archive` / `project_signals_archive`
都是 0 行，`summary.total_runs = 0`。

上一版把原因写成「数据还没超过保留期，所以每次触发都无事可做」。
**这个解释是错的**，2026-08-24 拿线上库副本真跑一次归档验证了：

> `run_and_record()` 即使一行都没归档，**也会写下一条 `status=success` 的记录**
> （实测：`raw_archived=0`，`archive_runs` 仍然 +1，
> 内容 `{'id': 1, 'trigger': 'manual', 'status': 'success', 'raw_archived': 0, ...}`）。

所以 `archive_runs` 为 0 只能说明一件事：**这个任务一次都没被触发过**。
本机后端是手工起停的开发进程，从没在 UTC 03:00（本地 11:00）那一刻活着，
`misfire_grace_time=3600` 也没兜住。这跟保留期毫无关系。

**两个诊断的处置动作完全不同**：
「无事可做」是"再等等就好"，「从没触发」是"这条路径的调度部分从未被验证"。
把后者写成前者，会让人以为已经跑过很多次、只是每次都空转。

#### 归档逻辑本身是好的（同一次实跑证明）

同一份线上库副本上把保留期全设为 0 天再 dry-run，命中数：

| 分项 | 命中行数 |
|---|---|
| `raw_processed` | **106** |
| `raw_unprocessed` | **509** |
| `signals` | **2261** |
| `logs` | **20** |

也就是说 SQL 条件、`processed=0` 那一档、`dry_run` 只统计不改数据
（实测 dry-run 后所有表行数不变），都是对的。
**待验证的只剩"调度会不会按时把它叫起来"这一段。**

#### 什么时候会第一次真的归档到东西

本机数据最早 `2026-08-09`（`raw_projects.discovered_at` / `project_signals.captured_at`
都是这一天，`collection_logs.started_at` 是 08-09 06:00）。
按 30 天保留期，`raw_processed` 那一档最早在 **2026-09-08** 前后开始命中。

**建议**：在那之前手工跑一次，别把首次真实执行留给生产。

```powershell
cd backend
& ".\venv\Scripts\python.exe" ..\scripts\archive_raw_data.py --dry-run
```

`--dry-run` 只统计不改数据（已实测），确认数字合理后去掉该参数。
跑完用 `GET /api/v1/archive/runs` 核对 `summary.total_runs` 从 0 变成 1 ——
**判据落在"有没有留下记录"上，不是"命令有没有报错"。**

在此之前先用 `GET /api/v1/scheduler/jobs`（§5.4）确认 `archive_cleanup`
真的在任务表里。2026-08-25 本机实测**已在表里**，下次运行
`2026-08-26T03:00:00+00:00` —— 所以"从没跑过"的原因是这个进程从没活到过
03:00（开发机不常驻），不是任务没注册。**这两种原因的处置动作相反，
而在新端点之前它们看起来完全一样。**

### 7.4 决策推送（F1，ACTION_LOOP_DESIGN §2）

`NOTIFY_ENABLED` 默认 **`false`**（2026-08-31 起存在）。开关关着时每日摘要
job **不注册**，但 pipeline 收尾钩子的评估照常跑 —— 事件照常写入
`notify_log`（留痕 + `airdrop_notify_event_evaluated_total` 指标可见），
只是不发送。**关开关 ≠ 停审计**，排查「为什么没收到推送」先看这里。

| 项 | 值 | 说明 |
|---|---|---|
| job id | `notify_digest` | cron 表达式 `NOTIFY_DIGEST_CRON`（默认 `0 9 * * *`，UTC） |
| 事件来源 | `app/notify/evaluator.py` | 跨线 / 新 FARM / 观察列表信号 / 每日摘要 |
| 发送通道 | `NOTIFY_CHANNEL` | `telegram` / `discord_webhook`，凭证缺失时报错不发送 |
| 单轮上限 | `NOTIFY_MAX_PER_RUN=20` | 防事件风暴 |
| 手动验证 | `POST /api/v1/notify/test` | **管理员专用**；发一条测试消息验证凭证与连通 |
| 排查入口 | `GET /api/v1/notify/log` | 发送历史含失败原因；`status=failed` 表示重试 3 次全败 |

出站经 `utils/fetcher.post`，域名白名单生效（`api.telegram.org` / `discord.com`
已登记 SECURITY §10.2）。推送是尽力而为：失败不影响采集与分析主链路。

---

## 8. 监控栈

### 8.1 告警规则（实测 10 条）

`configs/observability/prometheus/alert_rules.yml`：
`PipelineConsecutiveFailures`、`PipelineFailureRate`、`NoProjectsDiscovered`、
`DBGaugeStale`、`HighLLMErrorRate`、`LLMBudgetExhausted`、
`LLMBudgetLedgerUnavailable`、`LLMSpendNotRecorded`、
`HighAPIErrorRate`、`BackendDown`。

这 10 条引用的指标名**全部真实存在**（有测试钉住，见 §10）。

后三条是 2026-08-24 随日预算拦截一起加的，级别差异见
OBSERVABILITY §5.1。收到时的处置口径：

| 告警 | 是故障吗 | 先看哪里 |
| --- | --- | --- |
| `LLMBudgetExhausted` | **不是**，是设计好的降级（退回规则引擎） | 要放开就调大 `LLM_DAILY_BUDGET_USD` 重启；解读质量下降是预期的 |
| `LLMBudgetLedgerUnavailable` | **是**，基础设施问题 | 数据库可写性、磁盘空间、`llm_spend_daily` 表是否存在。不要先怀疑预算配置 |
| `LLMSpendNotRecorded` | **是**，预算正在静默失效 | `llm.budget.record_failed` 日志 + 数据库写入。这些花费永远不会计入预算 |

### 8.2 代码侧的采集告警

`backend/app/collectors/metrics.py` 的 `check_alerts()` 会写 `collection.alert` 日志事件，
阈值（实测硬编码）：`success_rate < 0.95`、`avg_latency_ms > 30000`、
`freshness_minutes > 120`、`coverage_rate < 0.5`、`duplicate_rate > 0.5`。

其中 `coverage_rate` 用 `logger.info`，其余用 `logger.warning`
—— 想按级别过滤告警时注意这个不一致。

**这些阈值不走 Prometheus**，只进日志，没有告警通道。

### 8.3 抓取配置

`scrape_interval: 15s`，目标 `airdrop-web:8002`，`metrics_path: /metrics`。

⚠️ `external_labels` 里 `environment: 'production'` 是**写死的**，
拿这份配置起 staging 会把所有指标打上 production 标签。见 §12.9。

### 8.4 Grafana

`configs/observability/grafana/dashboards/airdrop-system-overview-v2.json`，
Grafana v2 schema，10 个面板 / 12 条 `expr`，引用的指标名全部真实存在。

### 8.5 日志采集

promtail 采 `/var/log/app/*.log`（宿主 `./logs`）和 `/var/log/nginx/*.log`，
job 名 `airdrop-alpha`，送 Loki。

---

## 9. 配置变更

### 9.1 流程

1. 改 `backend/app/config.py` 默认值 **和** `.env.example`（两个必须同步）。
2. 开 PR，说明改了什么、影响什么。
3. CI 全绿（5 个必需检查，见 §10.5）。
4. 部署后核对 `GET /api/v1/settings/config`（管理员）确认新值生效。

**所有配置只在启动时读取，改完必须重启。** 没有热加载。

第 1 步的「必须同步」现在**由门禁强制**，不再靠人记得：
`backend/tests/test_env_example_parity.py` 逐键比对 `.env.example`
与 `Settings` 的声明默认值，改了代码没改模板会当场变红。
细节见 §9.4。

### 9.2 需要额外谨慎的项

| 配置 | 影响 | 备注 |
|---|---|---|
| 8 项评分权重 | 评分漂移 | Σ 必须=1.0，否则启动断言失败（ADR-006） |
| `LABEL_THRESHOLDS` | 标签分布突变 | 在代码里不在配置里 |
| `LOG_LEVEL` | 日志量 | 非法值**回落 INFO**，绝不回落 DEBUG |
| `DISCOVERY_SCORE_ANALYSIS_THRESHOLD` | 进入分析的项目量 | 当前 0.3 |
| `SEED_FALLBACK_ENABLED` | 采集失败时是否用种子数据兜底 | **当前 `True`，生产建议关**（§11） |
| `API_KEY` | 生产自检要求 ≥32 字符 | 不合格直接拒绝启动 |
| `DATABASE_URL` | **会反向改写 `DB_BACKEND`** | 设了 PG 连接串就一定走 PG，哪怕 `DB_BACKEND=sqlite` |
| 6 个 `OPPORTUNITY_ECONOMIC_*` | 启动直接报错 | 级联要求：`evidence_emit`⇒`snapshot`，`resolver`⇒`evidence_emit` |

### 9.3 日志级别

`LOG_LEVEL` 支持 `debug` `info` `warning` `error` `critical`，
别名 `warn→warning`、`fatal→critical`，大小写不敏感。
**非法值一律回落 `info`** —— 配错不能让输出变得更多。

细节见 [OBSERVABILITY.md](OBSERVABILITY.md) §2.3。

### 9.4 `.env.example` 的门禁（以及它此前错在哪）

`.env.example` 是新人和部署脚本唯一的配置起点，但**它不被任何代码读取** ——
所以写错不会报错，只会静默误导人。实测（2026-08-23）它此前有：

- **47 个键的值与代码默认值不一致**（cron 时间、重试次数、超时、
  权重版本号、并发数、缓存 TTL…）。照它填出来的 `.env` 行为和代码默认值不同，
  而两边都"看起来对"。
- **一处自相矛盾**：文件写着 `DB_BACKEND=sqlite`，同时把
  `DATABASE_URL=postgresql://…` 打开了。而 `_resolve_db_backend()` 会
  **反向**把 `db_backend` 改成 `postgres` —— 照模板复制出来的 `.env`
  实际连的是 Postgres，跟它自己声明的那行完全相反。这类错误最难发现：
  两行单独看都合理，只有读过 validator 才知道后者压过前者。
- **2 个键全仓无人读取**：`LLM_API_KEYS` / `LLM_BASE_URLS`。
  多接口故障转移真正读的是**编号变量**（`LLM_BASEURL_1` / `LLM_API_KEY_1`
  / `LLM_MODELS_1_1`），走 `os.environ` 不经 Settings。
  照着填那两个逗号分隔变量，LLM 一个接口都不会注册。
- **2 个路径不存在**：`SEED_DATA_PATH=data/seed_projects.json`、
  `FETCHER_CACHE_DIR=data/fetcher_cache`。
- **`WEIGHT_VERSION=score-v1.4` 混淆了两个版本轴**：`score-v1.4` 是评分
  **模型代号**（前端展示、Opportunity 的 `LEGACY_MODEL_VERSION`），
  而这个键是**权重版本**（代码默认 `v1.2`，随每条评分写入
  `projects.weight_version`）。照模板填会把模型名写进权重列。

门禁 `backend/tests/test_env_example_parity.py`（13 个测试）现在钉住：

| 断言 | 抓什么 |
|---|---|
| 每个键是 `Settings` 字段或标了 `env-external` | 没人读的假配置 |
| `env-external` 不能标在真的 `Settings` 字段上 | 防这个标记变成绕过值比对的后门 |
| `Settings` 字段在模板里的覆盖率 > 75% | 模板整片跟不上代码 |
| 未标记的值必须等于代码声明默认值 | 值漂移（数值按数值比，`0.10` 等于 `0.1`） |
| 标了 `env-differs` 的值必须**真的**不同 | 过期标记留成永久后门 |
| 8 个权重之和 = 1.0 | 照模板填会启动即崩 |
| 按模板加载后 `db_backend` 必须等于模板声明值 | 上面那处自相矛盾 |
| 模板能被 `Settings` 成功加载且不落生产模式 | 级联校验顺序写错 |
| `SEED_DATA_PATH` 必须是仓库里已存在的文件 | 指向不存在的文件 |
| `FETCHER_CACHE_DIR` 必须是相对路径且不含 `..` | 缓存写到仓库外 |
| 4 条 parser self-check | 解析器读不到东西却依然全绿 |

> **注意运行时目录不能断言"存在"**：`cache/` 由 `_FileCache.__init__` 的
> `mkdir(parents=True, exist_ok=True)` 按需创建，跑过应用的机器上才有。
> 第一版把它当成"必须存在"，本地全绿而 CI 直接挂。
> 凡是断言涉及"文件是否存在"，先问 **「在一台没跑过这个项目的新机器上，
> 这条还成立吗？」** —— 一个随环境改变结论的断言不是断言。

**豁免是逐键显式的**：标记写在键的上一行注释里，`grep -n env-differs .env.example`
就能审计全部例外。空行会截断注释块，所以一个标记不会顺着整节蔓延 ——
**刻意不做整文件豁免**，那正是 `API_SPEC.md` / `OPERATIONS.md` 烂掉的机制。

当前的合法例外（各自写了理由）：`LOG_FORMAT`（代码默认 json 便于采集，
模板给 console 便于本地看）、4 个 `POSTGRES_*`（代码默认值是 CI 的测试实例
`127.0.0.1:5433/airdrop_test`，模板不该把人指向测试库）、
3 个 `OTEL_*` 与 2 个 `TELEGRAM_*`（分别由 OTel SDK 和 docker compose 直接读，
不经 Settings）。

---

## 10. 验证与质量门禁

改任何东西之后，这些必须全绿才算完成。

### 10.1 后端

```powershell
cd backend
$env:PYTHONUTF8="1"; $env:PYTHONIOENCODING="utf-8"
& ".\venv\Scripts\python.exe" -m pytest tests -q --cov=app --cov-fail-under=80
& ".\venv\Scripts\python.exe" -m ruff check app tests
& ".\venv\Scripts\python.exe" -m ruff format --check app tests
& ".\venv\Scripts\python.exe" -m mypy app --config-file pyproject.toml
```

> `mypy` 必须**在 `backend` 目录下**跑并用相对的 `pyproject.toml`；
> 从仓库根跑 `--config-file ..\pyproject.toml` 会冒出几百个假错误。

### 10.2 前端

```powershell
cd frontend-next
node ./node_modules/typescript/bin/tsc --noEmit
node ./node_modules/eslint/bin/eslint.js . --ext .ts,.tsx,.js,.jsx
node test.mjs
```

### 10.3 文档门禁

```powershell
& ".\backend\venv\Scripts\python.exe" scripts\check_encoding.py
& ".\backend\venv\Scripts\python.exe" scripts\check_terminology.py --all
```

### 10.4 CI 的警告策略比本地严

CI 跑 pytest 时加了：

```
-W error::DeprecationWarning -W error::ResourceWarning -W error::pytest.PytestUnraisableExceptionWarning
```

**本地默认不加。** 后果是：一个泄漏的文件句柄本地只是警告、CI 直接失败，
而且失败会被归到"恰好触发垃圾回收的那个无关测试"头上，极难排查
（真发生过一次，见 `CHANGELOG.md`）。

写涉及文件句柄 / socket / 子进程的测试时，本地就该照 CI 的参数跑一遍。

### 10.5 分支保护

`master` 要求 5 个检查通过（服务端读回确认）：
`Full Backend Test Suite`、`Lint & Format Check`、`Type Check (mypy)`、
`Frontend Lint & Build`、`Coverage Gate`。要求分支与 master 同步（`strict: true`）。

### 10.6 本文档的双向门禁

`backend/tests/test_operations_doc_parity.py` 会解析本文档并断言：

- 正文里**被当成可用**的每个 `airdrop_` 指标名，都必须真实存在于 registry；
- 正文里**被当成可用**的每个 `/api/v1` 路径，都必须真实存在于 OpenAPI；
- 正文里**被当成可用**的每个 `scripts` 脚本，文件都必须真实存在；
- 反方向：§12.1 / §12.2 的失真清单里那些东西，必须**确实都不存在**
  （否则纠错清单自己就成了新的谎言）；
- §7.1 cron 表逐条对齐 `settings` 实际值；§5.2 前缀清单逐项对齐
  `ADMIN_ONLY_PREFIXES`；§8.1 告警名对齐 `alert_rules.yml`；
  §8.2 阈值对齐 `check_alerts()`；标签阈值对齐 `scorer.py`。

**「被当成可用」是逐行判定的**：一行里如果出现「不存在 / 没有 / ❌ / 从未」
这类否定标记，那一行就被当成「文档在纠错」而豁免 —— 但只豁免那一行。
不做整节或整文件豁免：否则只要某个名字被登进 §12 清单，正文任何地方
把它当命令写出来都会被放过，而那正是这套门禁要防的事
（这个漏洞在变异测试里被真实抓到过一次，见 `CHANGELOG.md`）。

解析器自身也有自检测试：解析不到东西、或过滤条件写反导致几乎不检查时，
都会**大声失败**，避免「解析器返回空 → 所有断言都通过」这种假绿。

---

## 11. 未实现 / 已规划（**别当成能用的功能**）

<!-- unimplemented:begin -->

| 项 | 状态 |
|---|---|
| `scripts/diagnose.sh` 自动诊断 | ❌ 文件不存在（上一版文档整段贴了它的"源码"） |
| `scripts/heal.sh` 自动自愈 | ❌ 文件不存在 |
| 定时巡检 crontab | ❌ 无（依赖上面两个不存在的脚本） |
| 日志采样 | ❌ 未实现 |
| `X-Run-Id` 响应头 | ❌ 只有 `X-Disclaimer` |
| **7 张死表**（不只 `metrics`） | ❌ `metrics`、`audit_logs`、`llm_eval_changelog`、`narratives`、`dedup_keys`、`prompt_versions`、`quarantine` —— 都是「有 schema、有 repository、有单元测试、**0 行数据、除 repository 外 0 个写入方**」。逐表实测见 §12.14 |
| OpenTelemetry 追踪 | ⚠️ 代码就绪，本地未装依赖 → `setup_tracing()` 返回 `False` |
| 归档任务真实执行 | ⚠️ 逻辑已实跑验证（线上库副本上 dry-run 命中 106/509/2261/20），但**调度从未触发过一次**（`archive_runs` 0 行，§7.3） |
| `evaluation/collection/` 采集质量周报 | ❌ 目录不存在（只有 `evaluation/llm/`） |
| `.env.example` 里的 `LLM_API_KEYS` / `LLM_BASE_URLS` | ❌ 已删除，全仓无人读取（真正生效的是编号变量 `LLM_BASEURL_1` 等，§9.4） |
| `DUNE_API_KEY` | ❌ 已删除（2026-09-03）：配置字段、脱敏登记、模板行、DDL 种子行全部移除。此前是"配了也不生效"的装饰性键，会让人误以为需要去申请 Dune Key |
| `.env.example` 里的 `TWITTER_API_KEY` / `TWITTER_API_SECRET` | ⚠️ 采集器不读，真正用的是 `TWITTER_BEARER_TOKEN` |
| `SEED_ON_STARTUP` / `SEED_DATA_PATH` | ⚠️ 两个键**全仓 0 处读取**（启动灌种子靠手动跑 `scripts/seed.py`）。生产环境另有强制关闭，见 §12.13 |
| 蓝绿 / 金丝雀发布 | ❌ 未实现 |
| 值班轮换 / 紧急联系人 | ❌ 未设置（单人项目） |
| 恢复演练 | ❌ 从未执行 |

<!-- unimplemented:end -->

### 11.1 从这张表里**移出去**的五条（2026-08-24）

这些曾经写在上面，但已经不成立了。单独记下来，因为**"把已实现写成未实现"
和"把未实现写成已实现"都会造成真实损失**，只是方向相反：前者让人重做一遍
已有的东西，或者放弃一个可用的控制；后者让人在风险评估里数进一个不存在的控制。

直接删行是最省事也最糟的做法 —— 读者分不清"修好了"和"被悄悄拿掉了"。

| 曾经的记录 | 真实情况 |
|---|---|
| 「日志轮转 ❌ 完全没有」 | ✅ 已实现，`LOG_MAX_BYTES` / `LOG_BACKUP_COUNT` + compose 全服务 `max-size`，见 §12.6 |
| 「`RATE_LIMIT_ENABLED` / `_REQUESTS` / `_WINDOW` ❌ 三个配置项无任何代码读取，限流未实现」 | ✅ **这条一直是错的**：`app/rate_limit.py` 三个键全读（`:105` / `:128` / `:129`），中间件真实生效，`/api/v1/run` 另有分档配额 |
| 「`SEED_FALLBACK_ENABLED=false` 生产收紧 ⚠️ 待所有者决定」 | ✅ 已决定并实现：生产环境强制关闭，见 §12.13 |
| 「LLM 成本预算真实拦截 ❌ 配置项存在但不生效」 | ✅ 已实现：`llm_spend_daily` 表按 UTC 日累计，调用前查、超限拒绝并降级回规则引擎，见 §4.4 与 §12.3 |
| 「LLM token / 成本指标 ❌ 无任何指标统计」 | ✅ 已实现：`airdrop_llm_cost_usd_total`、`airdrop_llm_tokens_total`、`airdrop_llm_budget_blocked_total` 等 6 个新指标；原有 3 个 LLM 指标此前**注册了但从未递增过一次**，现在也接上了 |

其中第二条最值得记：它把一个**已经在挡攻击的控制**写成不存在。
按它做风险评估，会得出"需要新加限流"的结论，
而真实缺口在别处（`/metrics` 无鉴权、`/docs` 生产未关）。

---

## 12. 上一版本的失真记录

留着这一节是因为：**这些错误能存活这么久，靠的是"这个文件已经登记为编码损坏，
所以没人读它"**。登记豁免掩盖的不只是字节问题，还有内容问题。
写下来，也让 §10.6 的门禁有反向断言的靶子。

### 12.1 15 个不存在的指标名

上一版本引用 19 个 `airdrop_*` 指标，**只有 1 个真实存在**（`airdrop_http_requests_total`）。
以下 15 个在 registry 里查不到 —— §10.6 的门禁会反过来断言它们**确实都不存在**，
免得这份清单自己变成新的谎言：

<!-- ghost-metrics:begin -->
- `airdrop_collection_api_calls`
- `airdrop_collection_running`
- `airdrop_collection_status`
- `airdrop_collection_success_ratio`
- `airdrop_collection_total`
- `airdrop_db_write_errors_total`
- `airdrop_fetcher_circuit_open`
- `airdrop_fetcher_errors_total`
- `airdrop_llm_calls_total`
- `airdrop_projects_in_db`
- `airdrop_projects_inserted_total`
- `airdrop_quarantine_pending`
- `airdrop_rate_limiter_tokens`
- `airdrop_run_total`
- `airdrop_test`
<!-- ghost-metrics:end -->

**2026-08-24 从这张清单里移出了两个**：老文档写的 LLM 成本与 token 指标
（那两个名字现在真实存在，见 §11.1 与 OBSERVABILITY §3.2）。
移出而不是留着标注 ✅，是因为**本节整块会被门禁当作"这些都不存在"来核对** ——
在这里写出一个真实指标名会立刻让 CI 变红，这正是它该做的事。

**2026-08-29 再移出一个**：`airdrop_data_completeness_ratio` —— 数据质量
指标（§11.2）现在真实存在，不再是幽灵。

**为什么这比写错更糟**：Prometheus 查一个不存在的指标**不报错，返回空结果**。
于是仪表盘显示"一切平静"、告警规则永远不触发 —— 看起来系统很健康，
其实是这条监控从来没生效过。幽灵指标名比错误的阈值危险得多。

### 12.2 不存在的 API 路径与脚本

§10.6 的门禁同样反向断言这些**确实不存在**。

<!-- ghost-paths:begin -->
| 上一版本写的 | 真相 |
|---|---|
| `GET /api/v1/audit` | 不存在（管理员打也是 404） |
| `POST /api/v1/re-score/{project_id}` | **完全不存在这个接口**，见下 |
| `POST /api/v1/collections/trigger/{source_id}` | 顺序颠倒，真实是 `/{source_id}/trigger` |
| `scripts/diagnose.sh` | 文件不存在 |
| `scripts/heal.sh` | 文件不存在 |
<!-- ghost-paths:end -->

另外上一版本写的 `GET /project/{id}` 也不存在，真实路径是
`/api/v1/projects/{project_id}`（不带 `/api/v1` 前缀的路径不在门禁的解析范围内，
所以只在这里说明）。

`re-score` 这条最有意思：它**在 `ADMIN_ONLY_PREFIXES` 里**，
所以匿名 token 打 `POST /api/v1/re-score/1` 拿到 **403** 而不是 404 ——
鉴权中间件在路由匹配之前就拦下了。**403 让人确信这个接口存在**（"只是我权限不够"），
比 404 更能把人骗住，文档里的错误也就一直没人发现。
用管理员凭据打才会露出真相：404。

### 12.3 "LLM 超预算自动停用"曾经是假的（2026-08-24 已补成真的）

**当时的问题**：更早的版本 §4.4 写「自动停用已生效（超预算当日不再调 LLM）」。
实测 `llm_daily_budget_usd` 只在两个只读接口里被回显，
代码里**没有任何拦截逻辑**，也没有 token / 成本指标。
真实存在的成本闸门只有 `/api/v1/run` 的频率限制（LLM 开 1 次/时，关 10 次/时）。

一条写在 runbook 里、值班照着信的"自动保护"，实际不存在 —— 这比没写更危险。

**现在**：所有者选择"真正实现"而不是删掉配置项。实现见 §4.4 的操作说明。

**这一节保留下来，是因为它记录的失效模式仍然值得警惕**：
这个配置**被读了 3 处**，搜一下像是实现了 —— 比"配置项完全没被读"更能骗过检查。
判据必须落在「有没有人在累计花费」上，而不是「有没有人读这个配置」。
现在 CI 里那两条门禁（`test_operations_doc_parity.py` /
`test_security_doc_parity.py`）已经从"断言它必须仍然不存在"整体转向为
"断言拦截真的接在调用路径上，且在发请求之前"。

**顺带修掉的另一个假绿**：`airdrop_llm_requests_total` /
`airdrop_llm_errors_total` / `airdrop_llm_duration_seconds` 这三个指标
从注册那天起**从未被递增过一次** —— 注册了、暴露在 `/metrics` 里、
文档记录了、还有一条 `HighLLMErrorRate` 告警建立在其上，但没有任何递增点。
一个存在但永不增长的指标，在面板上是平直的 0 线、在告警里是永不触发，
两者看起来都像"系统很健康"。**这比指标名写错更坏**：名字写错时查询查不到数据，
还有机会被发现。

### 12.4 端口写错（8000 vs 8002）（2026-08-24 已修）

上一版本全篇用 8000，`scripts/deploy.sh` 和 `scripts/health-check.sh`
也写 8000。真实端口 **8002**。
照文档执行 `deploy.sh` 会在健康检查环节卡满 30 次重试后失败 ——
而服务其实已经起来了，只是没人在 8000 上听。

**已修**：文档全篇改成 8002；两个脚本改成从 `.env` 的 `PORT` / `API_PORT` 读，
读不到才用默认 8002。门禁 `test_no_executable_port_8000` 禁止
非注释行再出现 `localhost:8000` 这类可直接复制执行的地址。
注释里为解释这段历史而写的 8000 是允许的 —— 把散文一起禁掉会逼着文档删掉真实的警告。

### 12.5 备份可能备错库（2026-08-24 已修）

上一版本说库在 `data/airdrop.db`，恢复示例是 `sqlite3 data/airdrop.db`。
实测运行时真正连的是 **`D:\app\data\app.db`**（288 项目 / 9.3 MB），
而 `data/airdrop.db` 是 94 个项目的过期副本。

`scripts/backup.sh` 的最后一级回退正是 `cp data/airdrop.db ...`
—— 在容器都不在的情况下，它会**安静地备份那个过期副本并报告"备份完成"**。
一个报成功却备错文件的备份，比明确失败的备份危险。

**已修**：本地回退分支改成从 `.env` 读 `DB_PATH`（相对路径同时试 `backend/` 前缀），
用 `sqlite3 .backup` 或 `python3 sqlite3.backup` 取一致快照而不是 `cp`
（`cp` 一个正在被写入的 SQLite 文件可能拿到撕裂快照，而它照样能被打开，
只是内容不一致 —— 又一种"看起来成功"的失败）。
**找不到库时改成 `exit 1`，不再"跳过并报成功"**：原来会一路走到「✅ 备份成功！」，
最后打包出一个只含 `backup-info.txt` 的压缩包。
门禁 `test_backup_fails_when_no_database_found` 守这一条。

不猜其它文件名是刻意的：**猜中一个过期副本比找不到更坏** ——
前者会给你一份看起来成功的、没用的备份。

（当前每日跑的 `auto_backup.ps1` 走的是 PostgreSQL 容器路径，
本来就不受这个问题影响。）

### 12.6 日志轮转（2026-08-24 已实现）

上一版本 §2.2 说「检查 logs 表增长，超 50MB 考虑清理」，
但没提**文件**日志。实测 `logs/backend.log` 6 天长到 3.97 MB
（2026-08-17 → 08-23），代码里没有轮转 handler，
compose 里也没有 docker `logging` 驱动的 `max-size` / `max-file`，
更没有 logrotate —— **三层都没有**，按当前速率一年约 240 MB 且无上限。

真实后果不是"日志丢了"：DB 和日志在同一块盘上，
写满盘会让**数据库写入开始失败**。

**已实现按大小轮转**（`backend/app/utils/redact.py` 的 `_RotatingLogStream`）：

| 配置键 | 默认值 | 含义 |
| --- | --- | --- |
| `LOG_MAX_BYTES` | `10485760`（10 MiB） | 单文件上限，超过换文件；`0` = 不轮转（显式选择） |
| `LOG_BACKUP_COUNT` | `5` | 保留几个历史文件（`backend.log.1` … `.5`） |

磁盘占用上界约 **60 MiB**。只换文件不删旧的不算轮转 —— 那只是把一个大文件
换成无数小文件，磁盘照样满。

两个实现细节值得知道：

- 进程重启后按**已有文件大小**继续计数，不从 0 重新开始。
  从 0 计数的话，一个已经很大的文件会被认为"还没到上限"而永远不轮转 ——
  而长期运行的服务恰好重启过很多次。
- **轮转失败不会让写日志抛异常**（降级为继续写当前文件）。
  轮转发生在 `write()` 里，抛异常会打断正在处理的业务请求 ——
  一个为了保护磁盘而存在的机制，不该成为线上故障的来源。

#### 容器 stdout 是**另一条**无界路径

应用侧补完轮转后很容易以为问题解决了，但后端**同时**往 stdout 和文件写
（`_TeeWriter`），而 docker 默认的 `json-file` 驱动**没有任何大小上限** ——
每一行都无限追加到 `/var/lib/docker/containers/<id>/<id>-json.log`，
只有删容器才释放。流量和应用日志一样大。

`docker-compose.prod.yml` 现在给**全部 11 个服务**都配了
`max-size: 10m` / `max-file: 3`（通过 `x-logging` YAML 锚点复用），
合计上界约 330 MiB。

> 只修一条路径就在清单上打勾，会让同一个症状在完全相同的地方复发一次，
> 而那时清单显示"已修复"。

排障：日志停在某个时间点不再增长，先看同目录有没有 `backend.log.1` ——
那是轮转过了，不是日志断了。

### 12.7 两个鉴权口子（2026-08-24 已修）

`POST /api/v1/collections/{id}/trigger`、`PATCH /api/v1/collections/{id}` 和
`PATCH /api/v1/projects/{project_id}/funding` 都能改变系统状态
（前两个真的会跑采集/改采集配置，后者改数据并触发重算），
而此前都**不在** `ADMIN_ONLY_PREFIXES` 里 —— 实测匿名 token 返回 **200**。

**已收紧**（见 §5.2 的按方法规则表）：这三个现在都要管理员，
它们的 `GET` 保持开放。

值得记住的是**它们为什么会漏**：`ADMIN_ONLY_PREFIXES` 是一张
"记得来登记才会生效"的白名单，而这类白名单的失效方式是沉默的 ——
漏一条，没有任何东西会变红。

所以修的时候没有只补两行，而是把判据反过来：
`backend/tests/test_admin_only_rules.py` 把 OpenAPI 里**所有 21 个写操作**
枚举出来，每一条都必须有归属 —— 要么受管理员保护，要么在 `ANON_WRITABLE`
里带一句为什么。新增写端点时忘记登记会直接让 CI 变红。

登记只允许**逐条 (方法, 路径)**，不允许按前缀或按文件豁免。

### 12.8 `/docs` 在生产也是开的

`backend/app/main.py` 里 `docs_url` / `redoc_url` / `openapi_url` 是写死的，
不看 `APP_ENV`。生产环境会把完整 API 结构（含全部管理员端点）公开。
目前靠网络边界兜底，未修改。

### 12.9 Prometheus 环境标签写死

`configs/observability/prometheus/prometheus.yml` 的
`external_labels.environment: 'production'` 是硬编码。
拿同一份配置起 staging，指标会带上 production 标签，
告警和仪表盘就分不清环境了。未修改。

### 12.10 章节号重复

上一版本有**两个 `## 5`**（「自动化 Runbook」和「配置变更」），
导致后面所有「见 §5.x」的交叉引用都是二义的。
重复编号会让交叉引用静默失效 —— 读者点过去看到的是另一节，
而没有任何东西会报错。

### 12.11 「10 个采集源全部就绪」是假的

上一版本说 10 个源「全部已注册且 `config_ready=true`」。
实测本机只有 **5 个** 为 true（`defillama` `coingecko` `github`
`cryptorank` `etherscan`），另外 5 个开关关着、Key 也没配；
`data_sources` 表里也只有这 5 个源有记录。

**危害形态**：那 5 个未就绪的源在 `GET /api/v1/collections/sources`
里照样列出来。排查「为什么没发现新项目」时，如果不看 `config_ready`，
就会去翻一个**从未运行过**的源的日志 —— 翻不到任何错误，
于是误判成"采集是好的，问题在分析侧"，方向整个跑偏。

§4.3 现在把门控规则（开关名 + 是否需要 Key）做成了机器可读的表，
由门禁与 `is_enabled()` 的实现逐项比对。

### 12.12 `.env.example` 曾有 47 个键的值与代码不符，还自相矛盾

配置模板不被任何代码读取，所以写错**不会报错，只会静默误导人**。
实测发现 47 个键的值与 `app/config.py` 的默认值不一致、2 个键全仓无人读取、
2 个路径不存在、`WEIGHT_VERSION` 混淆了模型代号与权重版本，
还有一处最难发现的自相矛盾：文件写着 `DB_BACKEND=sqlite`，
同时把 `DATABASE_URL=postgresql://…` 打开了，而后者会**反向改写**
`db_backend` —— 照模板复制出来的 `.env` 实际连的是 Postgres。

完整清单与新增门禁见 §9.4。

### 12.13 种子开关只是"建议"，而建议的执行率不可观测

`.env.example` 此前对 `SEED_ON_STARTUP` / `SEED_FALLBACK_ENABLED` 写的是
「**生产环境建议**设为 false」，`OPERATIONS.md` §11 也把它记成"待所有者决定"。

**2026-08-24 已改成代码强制**：生产环境（`APP_ENV=production` / `prod`，
含大小写与前后空格变体）会把这两个开关强制置为 `false`，
配置里显式写 `true` 也不生效，并写回字段本身 ——
`GET /api/v1/settings/config` 回显的就是真实生效值。

**为什么值得强制**：危害不是"多了 8 条假数据"，而是**它让故障看起来像正常**。
外部采集全挂时，库里仍然有项目、Dashboard 仍然有数字、
`airdrop_db_projects_total` 仍然不为零。
**没人会去查一个看起来有数据的系统。** 静默的错误状态比明确的空状态坏得多。

**为什么是强制改而不是拒绝启动**：§4.2 那几条生产自检（空 `API_KEY`、
localhost `CORS_ORIGINS`）拒绝启动，是因为它们**无法自动修正** ——
密钥和真实域名只有部署者知道。种子开关不一样：生产环境的正确值只有一个，
就是关；忘了改不代表配置冲突，为此拒绝启动是把一个能自动修好的问题
变成一次上线失败。

非生产环境（development / staging / testing）行为不变 ——
本地开箱演示与空库兜底正是这两个开关存在的理由。

排障提示：如果在生产环境里发现 `/api/v1/settings/config` 的
`SEED_FALLBACK_ENABLED` 是 `false` 而 `.env` 里写着 `true`，
那不是配置没加载，是这条强制在生效。

---

### 12.14 死表不止 `metrics` 一张，是 7 张

此前 §11 只点了 `metrics`。2026-08-25 在**线上库**（`D:\app\data\app.db`，
28 张表）上逐表实测行数 + 逐文件搜写入方，结果如下。

判据是两条同时成立：**真库里 0 行**，且**除 `repositories/` 之外没有写入方**。
（只看 grep 会漏 —— repository 里的 `INSERT` 会让搜索有命中，
看起来像"有人在写"。）

| 表 | 行数 | 写入方 |
|---|---|---|
| `metrics` | 0 | 仅 repository |
| `audit_logs` | 0 | 仅 repository |
| `llm_eval_changelog` | 0 | 仅 repository |
| `narratives` | 0 | 仅 repository |
| `dedup_keys` | 0 | 仅 repository |
| `prompt_versions` | 0 | 仅 repository |
| `quarantine` | 0 | 仅 repository（**但隔离功能是真的，见下**） |

对照组（**不是**死表，用来证明这个判据不是恒真）：

| 表 | 行数 | 写入方 |
|---|---|---|
| `project_history` | 1575 | `repository.py` |
| `events` | 1 | `routers/v1/feedback.py` |
| `weight_changelog` | 0 | `calibration.py` —— 0 行但**有**生产写入方，属"还没触发过" |
| `feedback` | 0 | `routers/v1/feedback.py` —— 同上 |
| `notification_reads` | 0 | `routers/v1/notifications.py` —— 同上 |

#### `audit_logs` 是这批里最需要注意的一张

审计日志会被**直接算进合规与安全评估**。一张有 schema、有 repository、
有单元测试的空审计表，比一张不存在的表更容易被当成"这个能力有"。
和 SECURITY.md §6.3 那个"固定 digest"是同一类错：
**声称存在的保护，比缺少保护更危险，因为它会被算进防护面。**

（注：SECURITY.md §4.3 把审计日志列在「V3 前瞻」里，那是诚实的表述 ——
它说的是"将来要做"，没有声称现在有。）

#### `quarantine` 是一次差点搞错的诊断

`quarantine` 表 0 行、只有 repository 写它 —— 照上面的判据，是死表。
但 `/api/v1/quarantine` **是能用的**，`/health` 也报 `quarantined_raw: 3`。

两件事同时成立，因为**真实实现根本不用那张表**：
`app/quarantine.py` 全部走 `raw_projects.quarantined` 标志位
（实测 615 行 raw_projects 里有 3 行被标记，正是 `/health` 那个数字）。

所以正确结论是「隔离功能是真的，另有一张**同名的**死表」，
而不是「隔离功能是假的」。**同名但无关**是这类误判里最容易踩的一种 ——
如果只看表名和行数就下结论，会把一个能用的功能报成坏的。

#### 处置

需所有者决定：接上还是删掉（待决清单第 4 条已扩展为这 7 张）。
本轮只做实测与记录，**没有删任何表** —— 删表是不可逆操作，
而且其中几张（`prompt_versions`、`dedup_keys`）看得出是为未来功能预留的。

另注：`SEED_ON_STARTUP` 与 `SEED_DATA_PATH` **全仓 0 处读取**
（启动灌种子靠手动跑 `python scripts/seed.py`）。
它们仍然保留在模板里是因为 `configs/development/.env.development`
与 `scripts/deploy.sh` 都在教人填，要删得连模板、文档、部署脚本一起删。
**一个能填但什么也不做的配置键比缺一个更坏** —— 填的人以为生效了。

---

_本文档所有数字、路径、指标名、接口名均于 2026-08-23 实测取得；
由 `backend/tests/test_operations_doc_parity.py` 双向门禁钉住。_
