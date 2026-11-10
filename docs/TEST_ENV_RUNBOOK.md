# 测试环境启动清单（内部 / 单实例）

> 面向「先在内网测试环境跑通」这一目标，不是对外上线清单。
> 对外发布的前置条件见 [`GO_LIVE_CHECKLIST.md`](GO_LIVE_CHECKLIST.md)。
>
> 本文所有结论来自 2026-11-10 的实机核查（启动、构建、迁移重放、代理转发均为实跑），
> 未验证项在 §7 单独标注。文中**不含任何真实密钥**，取值一律写成占位符。

---

## 0. 总览

| 步骤 | 动作 | 大致耗时 |
|---|---|---|
| 1 | 在 `.env` 里写好 §1 的必填项 | 5 分钟 |
| 2 | 准备测试库（§2），可选跑一次 `alembic upgrade head` | 1 分钟 |
| 3 | 起后端 `:8002`，确认 `/health` | 首次约 5 秒 |
| 4 | 构建并起前端 `:3002` | 构建 1-2 分钟 |
| 5 | 逐条过 §5 验收检查点 | 10 分钟 |

**关键结构**：后端单实例 + SQLite；前端通过 Next.js 自身的 `rewrites` 把 `/api` 转发到后端，
测试环境**不需要**额外的 nginx 反向代理。

---

## 1. 前置：必须设置的配置项

配置读的是仓库根目录 `.env`（其次 `backend/.env`），由 `pydantic-settings` 加载。
模板见仓库根 `.env.example`（200 个键，与 `Settings` 字段一一对齐，有 parity 测试覆盖）。

### 1.1 必须显式设置

| 键名 | 取值要求 | 为什么 |
|---|---|---|
| `API_KEY` | 随机串，**≥ 32 字符**；不要用字典词 | 留空等于**无鉴权模式**：所有接口对能访问到该端口的人完全开放。空值不会报错，只会静默降级 |
| `AUTH_TOKEN_SECRET` | 随机串，**≥ 32 字符**（建议 48+） | 为空时进程启动时随机生成，**重启后所有匿名 token 立即失效**，前端会周期性 401 |
| `SEED_FALLBACK_ENABLED` | `false` | 默认 `true`。采集全挂时会用 8 个硬编码种子项目（`source='seed'`）冒充采集结果入库，Dashboard 汇总数字被污染，会让你误判「采集链路正常」 |
| `APP_ENV` | `development`（内部测试，推荐）或 `production` | 决定是否启用生产强校验，见 §1.2 |
| `CORS_ORIGINS` | 逗号分隔的完整 origin，含协议与端口 | 默认只放行 `http://localhost:3002,http://localhost:8002`；用测试机 IP/域名访问前端时必须补上，否则浏览器侧跨域失败 |

生成占位（**只在本地终端执行，不要把输出贴进任何文档或聊天**）：

```powershell
# PowerShell
-join ((1..48) | ForEach-Object { [char](Get-Random -InputObject (48..57 + 65..90 + 97..122)) })
```

### 1.2 `APP_ENV` 怎么选（这里有个真实的取舍）

`production` 会触发启动强校验，**任一不满足就拒绝启动**：

- `API_KEY` 非空且 ≥ 32 字符
- `AUTH_TOKEN_SECRET` 非空
- `CORS_ORIGINS` **不得包含** `localhost` / `127.0.0.1`
- `HOST=0.0.0.0` 时必须配 `API_KEY`
- `DB_BACKEND=postgres` 时 `POSTGRES_PASSWORD` ≥ 16 位且不在弱密码清单内
- 强制 `SEED_ON_STARTUP=false`、`SEED_FALLBACK_ENABLED=false`

| 选择 | 适合 | 代价 |
|---|---|---|
| `APP_ENV=development`（推荐先跑通） | 内网机器、用 `localhost:3002` 访问 | 不校验 CORS 与密钥强度，配置写错不会报错，只会静默降级 |
| `APP_ENV=production` | 想在测试环境顺带验证生产校验链路 | `CORS_ORIGINS` 不能用 localhost，必须填测试机的真实 IP 或域名；配置不全直接起不来 |

> 建议：第一次跑通用 `development` 快速验证功能；功能通过后再切 `production` 跑一遍，
> 确认「生产校验也能过」，这一步等价于一次免部署的上线预演。

### 1.3 按需项（不配只会少功能，不会启动失败）

| 键名 | 不配的后果 |
|---|---|
| `GITHUB_TOKEN` | 采集器**仍然运行**，但走匿名配额（≤ 10 req/min），结果会被截断 |
| `ETHERSCAN_API_KEY` | `ETHERSCAN_ENABLED` 即使为 true，`is_enabled()` 也返回 false，整源跳过 |
| `CRYPTORANK_API_KEY` | 同上，状态记为 `skipped`（干净跳过，不伪造数据） |
| `COINGECKO_API_KEY` | 不影响运行，仅免费额度更低 |
| `DISCORD_BOT_TOKEN` + `DISCORD_CHANNEL_ID` | 两者需同时存在，缺一个则整源跳过 |
| `NOTIFY_ENABLED=true` 及 Telegram / Discord webhook | 默认为 `false`，不注册推送任务；sender 未配置时返回空而不抛错 |
| `ENABLE_LLM_ENHANCEMENT=true` + provider 三元组 | 默认 `false`，评分走纯规则路径（功能完整，只是没有 LLM 增强） |

DefiLlama / Medium / CoinGecko 三个源**不需要任何 key**，只受 `*_ENABLED` 开关控制，
所以「零外部 key」也能把主链路跑起来。

---

## 2. 数据库

### 2.1 路径约定

```ini
DB_BACKEND=sqlite
DB_PATH=data/airdrop.db
```

- `DB_PATH` 是**相对路径**，相对于**后端进程的工作目录**（`backend/`）解析，
  即实际落到 `backend/data/airdrop.db`。启动时目录不存在会自动创建。
- 测试环境建议换一个独立文件名，避免污染开发库：

  ```ini
  DB_PATH=data/airdrop-test.db
  ```

- SQLite 以 WAL 模式运行，目录里会同时出现 `-wal` / `-shm` 两个伴生文件，属正常现象。

### 2.2 是否需要 `alembic upgrade head`？

**不是必需的，但建议跑一次。**

- 运行时建表靠 `init_db()`：`CREATE TABLE IF NOT EXISTS` + `ALTER TABLE ADD COLUMN`，幂等，
  全新库与存量库都能直接启动（实测：全新库 41 张表，存量库 44 张表，均正常）。
- 代价是**库里没有 `alembic_version` 表**，Alembic 目前只是「影子历史」，`alembic current` 查不到版本。
- 迁移脚本 `0001_baseline_schema.py` 的 `upgrade()` 直接复用 `init_db` 逻辑，因此**在已有库上重放是幂等的**
  （实测：复制真实库副本后执行 `upgrade head` 成功，`current` 显示 `0015`，原库未被触碰）。

执行方式（工作目录 `backend/`）：

```powershell
venv\Scripts\python.exe -m alembic upgrade head
venv\Scripts\python.exe -m alembic current   # 期望输出 0015
```

当前 head 为 **`0015`**，与 `backend/alembic/versions/` 下的 15 个迁移文件一致。

### 2.3 备份建议

- 手动备份：**先停后端**，再复制 `backend/data/airdrop.db`（连同 `-wal` / `-shm`），
  命名带时间戳，例如 `airdrop.db.bak-20261110-1000`。
- 后端在跑时用文件复制可能拿到不一致快照；在线备份请用 `sqlite3 airdrop.db ".backup out.db"`。
- 执行任何批量脚本（回填、重算、导入）之前先备份，这是本仓库既有约定。

---

## 3. 后端

### 3.1 安装依赖

```powershell
# 工作目录：backend/
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt          # 运行时依赖
pip install -r requirements-dev.txt      # 只有要跑测试时
```

> 仓库根目录的 `Start.bat` 也能做这件事（检查 Python、按需建 venv、装依赖），
> 但脚本化启动前建议先手工跑通一次，出问题更容易定位。

### 3.2 启动

```powershell
# 工作目录：backend/
venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8002
```

- 入口是 `app.main:app`；端口默认 `8002`（避开常见的 8000）。
- 实测启动耗时：全新库 **4.7s**，45 MB 存量库 **4.6s**，无阻塞点。
- 启动日志里如果出现 `collector_disabled_missing_credential`，是「该源缺 key 所以不跑」的正常提示，
  不是错误。

### 3.3 健康检查

```powershell
curl.exe http://127.0.0.1:8002/health
```

实测返回（关键字段）：

```json
{
  "ok": true,
  "status": "healthy",
  "version": "0.1.0",
  "db": "ok",
  "db_backend": "sqlite",
  "quarantined_raw": 0,
  "auth_required": true,
  "feedback_enabled": true,
  "opportunity_model_version": "opportunity-v2.0"
}
```

判定要点：

- `ok=true` 且 `status="healthy"`：进程与数据库都正常。
- `db="ok"`：连接正常。为 `"error"` 说明 `DB_PATH` 不可写或目录不存在。
- **`auth_required` 必须为 `true`**。若为 `false`，说明 `API_KEY` 没生效（留空或读错了文件），
  此时后端是无鉴权模式——这是测试环境最容易漏掉的一项。
- `quarantined_raw` 只是被隔离的脏数据条数，非 0 不一定是故障，但值得看一眼。

其他系统端点：`/metrics`（Prometheus 文本）、`/version`。

---

## 4. 前端

### 4.1 安装依赖

```powershell
# 工作目录：frontend-next/
npm ci        # 有 package-lock.json，用 ci 保证可复现
```

### 4.2 构建——**`API_PROXY_TARGET` 必须在这里设置**

这是整套流程里最容易踩的坑：`next.config.js` 的 `rewrites()` 在 **build 时**求值，
结果被固化进 `.next/routes-manifest.json`。**运行时再设不算数。**

```powershell
# PowerShell，同一条命令里设好再构建
$env:API_PROXY_TARGET = "http://127.0.0.1:8002"
$env:BACKEND_API_KEY   = "<与后端 API_KEY 完全相同的值>"
npm run build
```

- 不设 `API_PROXY_TARGET` 做 production build → rewrites 数组为空 → 经前端的 `/api/*` **全部 404**。
  （实测：同一条命令下，不设变量时 `/health` 经前端返回 404；设了变量重新 build 后返回 200。）
- `BACKEND_API_KEY` 是**前端侧的键名**，后端读的是 `API_KEY`，两个名字不同但**必须同值**。
  留空则代理不注入任何凭据，等于关闭匿名 token 换取。
- **不要**设置 `NEXT_PUBLIC_API_KEY`：`NEXT_PUBLIC_` 前缀会被内联进客户端 bundle，
  任何访客都能在 DevTools 里读到管理员密钥。

### 4.3 启动

```powershell
$env:API_PROXY_TARGET = "http://127.0.0.1:8002"   # 运行期也要，用于换取匿名 token
$env:BACKEND_API_KEY   = "<同上>"
npm run start
```

- 端口 **3002**（脚本里写死，`npm run dev` 同端口）。
- 实测：`Ready in 451ms`，首页 HTTP 200。
- 所以：**构建环境变量和运行环境变量要一起给**，两个都不能省。

### 4.4 是否需要反向代理

**测试环境不需要。** 前端自身的 rewrite 已经覆盖：

- `/api/:path*` → `${API_PROXY_TARGET}/api/:path*`
- `/health` → `${API_PROXY_TARGET}/health`

用户只访问 `http://<测试机>:3002` 即可，同源，浏览器不产生跨域。
对外发布时才需要在前面加 nginx 做 TLS 终止，届时 `CORS_ORIGINS` 也要跟着改。

---

## 5. 验收检查点

逐条勾选，全部通过才算测试环境可用。

### 5.1 鉴权生效

- [ ] `curl.exe http://127.0.0.1:8002/health` → `auth_required: true`
- [ ] 无凭据访问业务接口被拒：

  ```powershell
  curl.exe -i http://127.0.0.1:8002/api/v1/projects
  # 期望 401
  ```

- [ ] 管理员 key 可访问（把 `<KEY>` 换成实际值）：

  ```powershell
  curl.exe -i -H "X-API-Key: <KEY>" http://127.0.0.1:8002/api/v1/projects
  # 期望 200
  ```

- [ ] 匿名 token 链路可用（前端的公开请求依赖它）：

  ```powershell
  curl.exe -X POST http://127.0.0.1:8002/api/v1/auth/anonymous
  # 期望返回 access_token 与 expires_in
  ```

- [ ] 管理员专属端点对匿名 token 返回 403（而不是 200）：

  ```powershell
  curl.exe -i -H "Authorization: Bearer <anon_token>" -X POST http://127.0.0.1:8002/api/v1/run
  ```

### 5.2 没有种子数据污染

- [ ] 库内 `source='seed'` 的记录数为 0：

  ```powershell
  # 工作目录：backend/
  venv\Scripts\python.exe -c "import sqlite3;c=sqlite3.connect('data/airdrop-test.db');print(c.execute(\"select count(*) from projects where source='seed'\").fetchone())"
  # 期望 (0,)
  ```

- [ ] 若不为 0：确认 `.env` 里 `SEED_FALLBACK_ENABLED=false` 已生效，并清理这批记录后重新采集。

### 5.3 调度任务已注册

- [ ] 管理员 key 查询任务表：

  ```powershell
  curl.exe -H "X-API-Key: <KEY>" http://127.0.0.1:8002/api/v1/scheduler/jobs
  ```

  判定：`missing_jobs` 为空数组；`collect_*` 只出现「已配置且启用」的源
  （缺 key 的源本就不该注册，缺失属正常）。

- [ ] 不要用 `APP_ENV=testing` 启动——该值会**禁用调度器并跳过路由注册**，看起来像「不采集」，见 §6。

### 5.4 前端页面能取到真实数据

- [ ] 经前端访问健康检查：

  ```powershell
  curl.exe -i http://127.0.0.1:3002/health
  # 期望 200，且 body 与直连后端一致
  ```

- [ ] 索引页（项目列表）能渲染出数据，不是空态、不是报错横幅。
- [ ] 随便点进一个项目详情页，评分/信号/时间线与列表页数据一致（详情页依赖同一份后端数据，
      与列表不一致通常意味着代理用了旧构建）。
- [ ] 浏览器 DevTools → Network 中 `/api/v1/*` 全部 200，无 401/404；响应头里不应出现管理员密钥。

### 5.5 限流与 429 排查

- [ ] 快速连打同一接口触发限流：

  ```powershell
  1..150 | ForEach-Object { curl.exe -s -o NUL -w "%{http_code}`n" http://127.0.0.1:8002/health }
  ```

  期望后面若干条返回 `429`（默认 100 请求 / 60 秒窗口）。

- [ ] 429 响应带 `Retry-After` 头，数值为剩余等待秒数。
- [ ] 若**没有**触发 429：检查 `RATE_LIMIT_ENABLED` 是否被关掉；若部署在反向代理之后，
      还需确认 `TRUSTED_PROXY_COUNT` 与实际代理层数一致（默认 0 表示不信任
      `X-Forwarded-For`，这是有意的防伪造设计）。
- [ ] 若**误报** 429（正常使用就撞限）：主要原因是前端首屏并发较多，
      临时调高 `RATE_LIMIT_REQUESTS` 或放宽 `RATE_LIMIT_WINDOW` 即可。

### 5.6 采集链路冒烟

- [ ] 先看哪些源可用：

  ```powershell
  curl.exe -H "X-API-Key: <KEY>" http://127.0.0.1:8002/api/v1/collections/sources
  ```

  关注每个源的 `is_enabled` / `config_ready`：缺 key 的源 `is_enabled=false`，属正常降级。

- [ ] 触发单个源采集（比一次性全跑更容易定位问题）：

  ```powershell
  curl.exe -X POST -H "X-API-Key: <KEY>" http://127.0.0.1:8002/api/v1/collections/defillama/trigger
  # 期望 status=success、items_collected>0（DefiLlama 无需 key；实测约 85 秒采到 100 条）
  ```

- [ ] 触发评分分析。注意 `/run` **必须带 JSON body**，空请求体会返回 422：

  ```powershell
  curl.exe -X POST -H "X-API-Key: <KEY>" -H "Content-Type: application/json" -d "{}" `
    http://127.0.0.1:8002/api/v1/run
  # 空 body 时自动读取 raw_projects 中未处理的项目；期望 persisted_count>0
  ```

- [ ] 采集完成后 `projects` 表有新增记录，且 `source` 不是 `seed`。
- [ ] 无 `GITHUB_TOKEN` 时 `github_curated` 可能返回 `status=partial`、`items_collected=0`
      （匿名配额 ≤10 req/min），属已知降级而非故障。
- [ ] 启动日志中无 `collector_disabled_missing_credential` 之外的异常告警。

---

## 6. 常见坑

| 坑 | 现象 | 处理 |
|---|---|---|
| **`APP_ENV=testing`** | 启动后没有任何采集/分析任务，`/scheduler/jobs` 返回空或「调度器未初始化」 | `testing` 只用于 pytest。测试环境用 `development`（或 `production`） |
| **`API_PROXY_TARGET` 只在运行时设** | 页面能打开，但所有 `/api/*` 404 | rewrites 在 build 期固化，必须重新 build |
| **多个后端实例共享 SQLite** | 同一批项目被重复采集、评分反复重算、日志出现并发写冲突 | `ha_enabled=false`（默认）时每个实例都自认 leader 并启动调度器。测试环境**只跑一个后端**；要多副本必须切 Postgres 并开启 HA 租约 |
| **`SEED_ON_STARTUP` 设了没用** | 改了这个键，行为毫无变化 | 它是**死配置**：`Settings` 里有字段，但全仓无代码消费。真实开关是 `SEED_FALLBACK_ENABLED` |
| **改后端地址只重启前端** | 前端仍指向旧地址 | 同 `API_PROXY_TARGET` 那条，改了要重新 build |
| **`CORS_ORIGINS` 用 IP 访问没配** | 浏览器 Console 报跨域 | 补上 `http://<测试机IP>:3002`；用前端同源访问时不会触发，但在 `APP_ENV=production` 下 localhost 会被启动校验直接拒绝 |
| **`API_KEY` 留空** | 一切正常，但接口谁都能写 | 看 `/health` 的 `auth_required` 字段，必须为 `true` |
| **前端构建未设 `BACKEND_API_KEY`** | 页面大量 401，且换 token 的请求也失败 | 前端键名与后端不同但必须同值 |

---

## 7. 已知未验证项（如实标注）

2026-11-10 实测覆盖范围：SQLite 全新库启动、鉴权三层（无凭据 / 管理员 key / 匿名 token）、
调度任务注册、采集与评分全链路、前端构建与经 3002 的代理转发、详情页取数。
**未覆盖**：Postgres、Docker、推送投递、LLM 增强，见下表。

| 项 | 状态 | 影响 |
|---|---|---|
| **Postgres 路径** | 只做了代码核查，**无活库实跑**（本机无 PG 实例） | 测试环境按 SQLite 规划即可；切 PG 前需单独验证连接串组装、`DbConnection` 的占位符改写与 HA 租约 |
| **Docker / compose 构建** | 未实跑，仅做了本地前端 build 与 uvicorn 启动 | 容器路径的实际依赖安装、健康检查探针未验证 |
| **推送通道（Telegram / Discord / 邮件）** | 仅代码核查「未配置时返回空而不抛错」 | 未做真实投递验证 |
| **LLM 增强链路** | 默认关闭，未实测 | 不影响主流程；启用前需单独验证 provider 配置与熔断行为 |
| **依赖版本可复现性** | `requirements.txt` 为浮动 `>=` 约束 | 不同日期构建可能得到不同版本，对外发布前应锁定 |

---

## 8. 停止与回滚

```powershell
# 停后端 / 前端：各自终端 Ctrl+C
# 回滚数据库：停后端后用备份覆盖
Copy-Item data\airdrop-test.db.bak-<时间戳> data\airdrop-test.db -Force
# 回滚迁移一步（仅在跑过 alembic 时需要）
venv\Scripts\python.exe -m alembic downgrade -1
```

---

_依据：本地实跑（uvicorn 启动、`/health`、`alembic heads/current`、`npm run build`、`next start`、
经前端代理的 `/api` 与 `/health`）+ 配置与代码逐行核对。所有密钥相关结论仅基于「是否设置」，未读取任何密钥值。_
