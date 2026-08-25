# 部署与运维指南

> **2026-08-24 全文重写。** 上一版几乎每条可执行命令都是错的 —— 见文末 §12「上一版错在哪」。
>
> 运维值班流程（告警处置、备份恢复、故障排查）在 [OPERATIONS.md](OPERATIONS.md)，
> 本文只讲**怎么把它跑起来**。两者重复的部分以 OPERATIONS.md 为准。

---

## 0. 先记住三个数字

| 项 | 值 | 写错的后果 |
|---|---|---|
| 后端端口 | **8002** | 打 8000 会得到「连接被拒绝」，而服务其实好着 |
| 前端端口 | **3002** | `frontend-next/package.json` 的 `dev`/`start` 都写死了 |
| Python | 声明下限 **3.11**，运行时 **3.12** | 检查器按 3.11，运行时可更新，见 §11 |

---

## 1. 本地运行（开发 / 演示）

### 1.1 最省事的方式：Start.bat（Windows）

仓库根目录双击 `Start.bat`。它会检查 Python、按需建 venv、装依赖，
然后开两个窗口分别起后端（8002）和前端（3002）。`Stop.bat` 停。

### 1.2 手动起后端

**要求**：Python 3.11 或 3.12（`pyproject.toml` 写的是 `requires-python = ">=3.11"`）。

```bash
cd backend
python -m venv venv                                 # 目录名就叫 venv，不是 .venv
venv\Scripts\activate                               # Linux/macOS: source venv/bin/activate
pip install -r requirements.txt                     # 运行时依赖（版本已锁定）
pip install -r requirements-dev.txt                 # 要跑测试才需要

python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8002
```

> **没有 `run.py`。** 上一版让你跑 `python run.py`，那个文件不存在。
> 入口是 `app.main:app`，交给 uvicorn 起。

依赖分三个文件：`requirements.txt`（运行时，进镜像）、
`requirements-dev.txt`（pytest/ruff/mypy，**不进镜像**）、
`requirements-otel.txt`（链路追踪，可选，缺了应用照常启动只是追踪不生效）。

首次启动会自动建表（`init_db()` 幂等，实测建 **28 张表**）。
库文件位置由 `DB_PATH` 决定，默认 `data/airdrop.db`，
**相对进程工作目录解析** —— 从 `backend/` 起服务就是 `backend/data/airdrop.db`。
这一条是本项目最容易踩的坑，详见 OPERATIONS.md §1.2。

### 1.3 手动起前端

```bash
cd frontend-next
npm install
npm run dev          # http://localhost:3002
```

前端通过 `frontend-next/proxy.ts` 转发到后端，
并从服务端环境变量 `BACKEND_API_KEY` 或 `API_KEY` 注入 `X-API-Key`。
**没有 `frontend/index.html`** —— 上一版提到的那个静态 Dashboard 不存在，
前端是 Next.js 应用。

### 1.4 灌一批演示数据

```bash
curl -X POST http://localhost:8002/api/v1/run \
  -H 'Content-Type: application/json' -d '{"source":"seed"}'
```

`/api/v1/run` 有频率限制：LLM 开启时 **1 次/小时**，关闭时 **10 次/小时**，
超了返回 429。这是三道成本闸门里管「次数」的那一道（另两道见 §7）。

---

## 2. Docker 部署

### 2.1 Dockerfile 在 `docker/` 下，不在根目录

```bash
# 在仓库根目录执行（build context 是根目录，Dockerfile 在子目录）
docker build -f docker/Dockerfile -t airdrop-alpha:latest .
```

多阶段构建，基础镜像 `python:3.12-slim`，最终 `WORKDIR /app/backend`，
`EXPOSE 8002`，以非 root 用户 `appuser` 运行。

### 2.2 单容器运行

```bash
docker run -d --name airdrop-alpha \
  -p 8002:8002 \
  -v "$(pwd)/data:/app/data" \
  --env-file .env \
  airdrop-alpha:latest
```

> 挂载点是 **`/app/data`**，不是 `/app/backend/data`（上一版写错了，
> 挂错位置的后果是容器重建后数据消失，而挂载本身不会报错）。
>
> `--env-file .env` 是必需的：镜像里没有 `.env`（被 `.dockerignore` 排除）。

### 2.3 docker compose（推荐）

```bash
docker compose up -d --build
```

`docker-compose.yml` 定义三个服务：

| 服务名 | 容器名 | 说明 |
|---|---|---|
| `backend` | `airdrop-alpha-backend` | FastAPI，宿主端口 `${API_PORT:-8002}` → 容器 8002 |
| `postgres` | `airdrop-alpha-postgres` | **默认不启动**（profile `postgres`） |
| `nginx` | `airdrop-alpha-nginx` | **默认不启动**（profile `production`），`${NGINX_PORT:-80}` |

> `API_PORT` 与 `NGINX_PORT` **不在 `.env.example` 里**，只在 compose 的
> `${VAR:-默认值}` 里出现。也就是说不设就是 8002 / 80；
> 要改宿主端口得自己往 `.env` 里加这两行。

> 服务名是 **`backend`**，不是 `web`。上一版写 `web`，
> 于是 `docker compose logs web` 会报「no such service」。
> （生产 compose `docker-compose.prod.yml` 里那个服务才叫 `web`，容器名 `airdrop-web` —— 两套文件不要混。）

切 PostgreSQL：

```bash
docker compose --profile postgres up -d
# 并设 DB_BACKEND=postgres（或直接给完整的 DATABASE_URL）
```

启用 nginx：

```bash
docker compose --profile production up -d
```

⚠️ **nginx 把 `/metrics` 公开代理出去且无任何鉴权**（实测返回 200）。
公网部署前必须自己加访问限制 —— 这一条仍是待决项，见 OPERATIONS.md。

### 2.4 一键脚本

```bash
./scripts/deploy.sh dev     # 开发：模板默认值可直接跑
./scripts/deploy.sh prod    # 生产：先过 4 项启动前预检，不通过就停下
```

`prod` 模式会在启动容器**之前**核对 `APP_ENV` / `API_KEY`（≥32 字符）/
`AUTH_TOKEN_SECRET` / `CORS_ORIGINS`，任一不合格立刻 `exit 1` 并说明要填什么。
这四项都会让 `app/config.py` 拒绝启动，提前查比等 60 秒超时快。

**脚本不会替你生成密钥。** 密钥和域名的正确值只有部署者知道；
自动塞一个进去会让一个配错的生产环境**看起来部署成功了**。

> 这三个脚本（`deploy.sh` / `health-check.sh` / `backup.sh`）在 2026-08-24 前
> 各带一个不报错的缺陷，详见 OPERATIONS.md §3.4。
> **首次在真 Linux 环境跑 `deploy.sh prod` 仍需人工盯一遍** ——
> 门禁只能证明它不再犯已知的那几个错，证不了它在真容器里跑得通。

---

## 3. 环境变量

**唯一权威清单是 [`.env.example`](../.env.example)**（380 行，逐项带注释，
并有测试 `test_env_example_parity.py` 保证它与 `app/config.py` 的默认值一致）。
本节只列启动必看的几项，不再复制全表 —— 复制出来的表会过期，
而**一个过期的配置表比没有表更坏**：它会让人填一个不存在的键，
然后以为自己配好了。

| 变量 | 生产必填 | 默认 | 说明 |
|---|---|---|---|
| `APP_ENV` | ✅ | `development` | 填 `production` 会打开一组自检，不合格**拒绝启动** |
| `PORT` | | `8002` | 服务监听端口 |
| `API_KEY` | ✅ | 空 | **留空 = 整个鉴权中间件短路，所有接口都不校验**。生产要求 ≥32 字符 |
| `AUTH_TOKEN_SECRET` | ✅ | 空 | 匿名 token 签名密钥。生产为空则拒绝启动 |
| `CORS_ORIGINS` | ✅ | `http://localhost:3002,...` | 含 localhost / 127.0.0.1 时生产拒绝启动 |
| `DB_PATH` | | `data/airdrop.db` | 相对路径按**进程工作目录**解析 |
| `DB_BACKEND` | | `sqlite` | 或 `postgres` |
| `OPENAI_API_KEY` | | 空 | 设置后才可能启用 LLM 增强（ADR-001） |
| `LLM_DAILY_BUDGET_USD` | | `1.0` | **真的会拦调用**（2026-08-24 起）。`0` = 不限 |
| `LLM_FALLBACK_PRICE_PER_1M_USD` | | `10.0` | 价格表里没有的模型按这个价算，宁可高估 |
| `LOG_MAX_BYTES` / `LOG_BACKUP_COUNT` | | `10485760` / `5` | 日志轮转，磁盘占用上界约 60 MiB |

生成密钥：

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

**不要读 `.env`。** 只需确认某个键是否已设置时用：

```bash
cd backend
python -c "from app.config import settings; print('github', bool(settings.github_token))"
```

只打印 True/False，不输出值。

### 3.1 几个曾被写错的键名

上一版列了四个**不存在**的变量名。真实名字是：

| 上一版写的（不存在） | 真实键名 |
|---|---|
| `CRON_HOUR` / `CRON_MINUTE` | `CRON_EXPRESSION`（cron 表达式，默认 `0 8 * * *`） |
| `DEFILLAMA_BASE` | `DEFILLAMA_BASE_URL` |
| `TWITTER_BEARER` | `TWITTER_BEARER_TOKEN` |

> **一个填了不生效的配置键，比缺一个更坏。** 前者会让人以为自己配好了。
> 这个道理今天在 `LLM_DAILY_BUDGET_USD` 上又验证了一次（它被读了 3 处，
> 全是回显，什么也不拦）。

---

## 4. 数据持久化与备份

- SQLite 单文件，容器里必须挂卷（`-v ./data:/app/data`），否则容器重建丢数据。
- PostgreSQL 用命名卷 `airdrop_pg_data`。

**备份用脚本，不要用 `cp`**：

```bash
./scripts/backup.sh              # 自动识别 PG 容器 / SQLite 容器 / 本地文件
./scripts/backup.sh /mnt/backup  # 指定目录
```

脚本按 PostgreSQL → 容器内 SQLite → 本地文件三级回退，
本地文件那级从 `.env` 的 `DB_PATH` 读路径，用 `sqlite3 .backup` 取一致快照，
**找不到库就 `exit 1`**。

> 为什么不用 `cp`：`cp` 一个正在被写入的 SQLite 文件可能拿到撕裂快照，
> 而它**照样能被打开**，只是内容不一致。
> 为什么找不到库要失败而不是跳过：原来的脚本会跳过并一路走到「✅ 备份成功！」，
> 打包出一个只含 `backup-info.txt` 的压缩包。
> **备份的失败方式里最坏的一种，就是它看起来成功了。**

恢复：停服务 → 覆盖库文件 → 启动。恢复前请先确认你手上那份备份**真的有内容**
（解开压缩包看有没有 `app.db`，行数对不对）。

保留策略：`backup.sh` 自动删 7 天前的 `.tar.gz`。

---

## 5. 健康检查

```bash
curl http://localhost:8002/health
```

实测响应体（**扁平结构，没有 `data` 包装**）：

```json
{"ok":true,"status":"healthy","version":"0.1.0","db":"ok","db_backend":"sqlite",...}
```

`db` 的值是 `"ok"` / `"error"`，不是 `"connected"`。
`db` 出错时 `ok` 会变 `false`、`status` 变 `degraded`，HTTP 状态码也会变。

`GET /version` 走的是标准信封：`{"ok":true,"data":{...}}`。
`/health`、`/version`、`/metrics` 三个都不需要鉴权。

值班用脚本：

```bash
API_URL=http://localhost:8002 ./scripts/health-check.sh
API_KEY=<管理员密钥> ./scripts/health-check.sh   # 带 key 才会检查 LLM 预算账本
```

预算账本那一项的判据是 `ledger_error` 字段而不是花费数字 ——
**一个坏掉的账本和一个还没花钱的账本，在数字上都是 0。**

容器侧：compose `healthcheck` 每 30s 用 `urllib.request` 探测 `/health`，
超时 10s、重试 3 次、`start_period` 10s；Dockerfile 里的 HEALTHCHECK 用 `curl`。
重启策略统一 `restart: unless-stopped`。

---

## 6. 日志

- `structlog`，生产输出 JSON 到 stdout（`LOG_FORMAT=json`），本地可设 `console`。
- 设了 `LOG_FILE` 就同时写文件，并按 `LOG_MAX_BYTES` / `LOG_BACKUP_COUNT` 轮转
  （磁盘占用上界约 60 MiB）。**2026-08-24 前完全没有轮转**：
  实测 6 天长到 3.97 MB，约 240 MB/年且无上限。写满盘的后果不是"日志丢了"，
  是**数据库写入一起失败**（DB 和日志同一块盘）。
- **生产** compose（`docker-compose.prod.yml`）里 11 个服务共用一个
  `x-logging` 锚点，`max-size: 10m` / `max-file: 3`。
  开发 compose（`docker-compose.yml`）**没有**配 logging 驱动 ——
  本地日志由 docker 默认驱动无界累积，长期开着的话自己留意。
- `docker compose logs -f backend`（服务名是 `backend`）。
- 生产 compose 另有 Loki + Promtail 集中收集。

事件名清单见 [OBSERVABILITY.md](OBSERVABILITY.md) §2.2。

---

## 7. 监控与告警

`/metrics` 暴露 Prometheus 指标，**实测 39 个**，全部以 `airdrop_` 开头，例如
`airdrop_pipeline_runs_total`、`airdrop_collection_runs_total`、
`airdrop_llm_cost_usd_total`、`airdrop_llm_budget_blocked_total`。

> 上一版列的 `run_total` / `run_errors` / `analyze_latency_seconds` /
> `db_write_errors` **四个都不存在**。
> **幻影指标名比错的指标名更坏**：照它建的面板和告警会永远是空的、永不触发，
> 而空面板看起来和"系统很健康"一样。
> 完整目录与 35 个历史幻影名的登记清单在 OBSERVABILITY.md §3.2。

告警规则 `configs/observability/prometheus/alert_rules.yml`，**实测 10 条**，
处置口径见 OPERATIONS.md §8.1。Grafana 面板与 Alertmanager 在生产 compose 里。

### 三道成本闸门（管的是不同的轴，别搞混）

| 闸门 | 管什么 | 超了怎样 |
|---|---|---|
| `/api/v1/run` 频率限制 | **调用次数**（LLM 开=1/小时，关=10/小时） | HTTP 429 |
| `LLM_DISCOVERY_SCORE_THRESHOLD=0.7` | **哪些项目值得走 LLM** | 低分项目走规则引擎 |
| `LLM_DAILY_BUDGET_USD` | **花了多少钱** | 降级到规则引擎 + `llm.budget.exceeded` 告警 |

预算是**软上限**：拦截发生在调用前，成本在调用后才知道，
所以最后一次被放行的调用必然越线。超出上界 = 一次调用的成本（由 `LLM_MAX_TOKENS` 决定）。
预算 1.0 而账单 1.003 是正常的，不是 bug。

---

## 8. CI

`.github/workflows/ci.yml`，Python **3.12**，`ubuntu-latest`。真实作业（不是示例）：

| 作业 | 内容 |
|---|---|
| `Lint & Format Check` | `ruff check` + `ruff format --check` |
| `Full Backend Test Suite` | 完整 pytest，带 `-W error::DeprecationWarning` 等三个 `-W error` |
| `Coverage Gate` | 行覆盖率 **≥80%** |
| `Type Check (mypy)` | `mypy app` |
| `Frontend Lint & Build` | typecheck + 单测 + build + `npm audit` |
| `Docker Build Check` | 构建镜像并跑健康检查冒烟 |

另有安全类工作流（`security.yml` / `docs.yml` / `release.yml`）：`Detect Secrets`、
`pip-audit (CVE Scan)`、`Dependency Review`、`Docker Image Trivy Scan`、
`Check Markdown Links`。

**master 分支保护**（服务端读取）要求 5 个上下文全绿才能合并：
`Lint & Format Check`、`Full Backend Test Suite`、`Coverage Gate`、
`Type Check (mypy)`、`Frontend Lint & Build`。`strict: true`（必须先与 master 同步）。

本地跑同一套：

```bash
cd backend
venv\Scripts\python.exe -m pytest -q                 # 完整套件约 38 分钟
venv\Scripts\python.exe -m ruff check .
venv\Scripts\python.exe -m ruff format --check app tests
venv\Scripts\python.exe -m mypy app --config-file pyproject.toml

cd ..\frontend-next
node ./node_modules/typescript/bin/tsc --noEmit
npx eslint .
node test.mjs

cd ..
backend\venv\Scripts\python.exe scripts\check_encoding.py --strict
backend\venv\Scripts\python.exe scripts\check_terminology.py --all
```

> `ruff format --check .` 在 0.16.1 上会 panic，必须显式给目录（`app tests`）。
> `mypy` 必须以 `backend` 为工作目录跑。

---

## 9. 升级与数据库迁移

Alembic **已启用**，`backend/alembic/versions/` 下实测 **4 个版本**：

| 版本 | 内容 |
|---|---|
| `0001` | baseline schema |
| `0002` | v2 新表 |
| `0003` | `archive_runs` |
| `0004` | `llm_spend_daily`（LLM 花费账本） |

```bash
cd backend
venv\Scripts\python.exe -m alembic upgrade head
venv\Scripts\python.exe -m alembic downgrade -1     # 回滚一步
```

`init_db()` 也能幂等建全部 28 张表（本地开发路径），
两条路径建出的表结构由 `test_alembic_migration.py` 逐表比对，不允许漂移。

字段扩展采用**追加列 + JSON 兼容**，避免破坏性迁移。
破坏性迁移的回滚请先备份（§4）。

---

## 10. 安全注意事项

- 密钥只通过环境变量注入，禁止写入镜像或提交仓库（`.dockerignore` 排除 `.env`）。
- **`API_KEY` 留空等于关掉整个鉴权层**，不是"少一层保护"。生产必填且 ≥32 字符。
- 生产环境 `APP_ENV=production` 会强制关闭两个种子开关
  （`SEED_ON_STARTUP` / `SEED_FALLBACK_ENABLED`），配置里写 `true` 也不生效。
  理由：种子数据开着的危害不是"多几条假数据"，而是**它让故障看起来像正常** ——
  采集全挂时库里仍有项目、Dashboard 仍有数字，没人会去查一个看起来有数据的系统。
- 写接口分两类：管理员专用（7 个前缀 + 按 (方法, 路径) 的规则表）与匿名可用。
  详见 [SECURITY.md](SECURITY.md)。
- 容器以非 root 用户 `appuser` 运行。
- 仅聚合公开数据。

**仍未处理的两条**（需所有者决定）：生产是否关闭 `/docs`、`/redoc`、
`/openapi.json`；nginx 是否限制 `/metrics` 访问。

---

## 11. Python 版本口径

**声明支持的下限是 3.11，运行时用 3.12。这不是不一致，是刻意的**：

| 位置 | 值 | 角色 |
|---|---|---|
| `pyproject.toml` `requires-python`（两份） | `>=3.11` | **声明支持的下限** |
| ruff `target-version` | `py311` | 按下限检查语法 |
| mypy `python_version`（两份） | `3.11` | 按下限检查标准库 API |
| CI `PYTHON_VERSION` | `3.12` | 实际跑测试的解释器 |
| `docker/Dockerfile` | `python:3.12-slim` | 实际部署的解释器 |
| 本地 `backend/venv` | 3.11.9 | 开发机 |

规则一句话：**检查器按下限（3.11），运行时可以更新（3.12）。**

### 为什么检查器不能跟着运行时一起调高

2026-08-24 之前 `backend/pyproject.toml` 的 mypy 写的是 `3.12`。
用 `itertools.batched`（3.12 新增的标准库 API）做探针实测四道门：

| 门 | 结果 |
|---|---|
| `mypy --python-version 3.11` | `error: Module has no attribute "batched"` ✅ 拦住 |
| `mypy --python-version 3.12` | `Success: no issues found` ❌ 放过 |
| `ruff --target-version py311` | `All checks passed` ❌ 放过 |
| 真 3.11.9 解释器 | `AttributeError: module 'itertools' has no attribute 'batched'` |

ruff 的 `target-version` 拦得住 3.12 专属**语法**
（实测能拦 PEP 695 的 `type X = int` 与 `def f[T]()`），
但**拦不住标准库 API 的版本差** —— 那只有类型检查器管。

所以 mypy 配 3.12 的后果是：`requires-python = ">=3.11"` 这句承诺
**一道门都没有**。一段用了 3.12 新 API 的代码会通过全部 CI，
然后在任何 3.11 环境上抛 AttributeError —— 运行时才抛，
而报错信息完全不提 Python 版本。

已改成 3.11 并加了门禁 `backend/tests/test_toolchain_version_parity.py`（8 条）：
两份 pyproject 的 `requires-python` 与 `version` 必须一致、
mypy 与 ruff 必须等于声明下限、CI 与镜像**不得低于**下限
（可以更高 —— 这个方向是刻意不对称的）、Dockerfile 各阶段必须同一版本
（`site-packages` 路径写死在 `python3.X` 目录里，不一致会在容器启动时才炸）。

要只支持 3.12，改的是 `requires-python`，不是放宽检查器。

**本地必须用 `backend\venv\Scripts\python.exe` 显式调用** ——
系统 Python 是 3.14.6，直接敲 `python` 会用错解释器。

---

## 12. 上一版错在哪（留痕，不直接删）

上一版的问题不是"有几处过时"，而是**几乎每条可执行命令都跑不通**，
而且没有一条会给出指向真正原因的错误信息：

| 上一版写的 | 实际 | 照它做会怎样 |
|---|---|---|
| `python run.py` | 没有 `run.py` | `can't open file 'run.py'` |
| `docker build -t airdrop-alpha:latest .` | Dockerfile 在 `docker/` 下 | `failed to read dockerfile` |
| `-p 8000:8002 -e PORT=8000` | 端口 8002 | 容器内外端口自相矛盾 |
| `-v ./data:/app/backend/data` | 挂载点是 `/app/data` | **挂载成功但挂错位置，数据仍会丢** |
| compose 服务名 `web` | 是 `backend` | `no such service: web` |
| `frontend/index.html` | 不存在，前端是 `frontend-next` | 打不开 |
| `PORT` 默认 `8000` | `8002` | 见上 |
| `DB_PATH` 默认 `backend/data/airdrop.db` | `data/airdrop.db`（相对 cwd） | 找错库 |
| `CRON_HOUR` / `CRON_MINUTE` | `CRON_EXPRESSION` | **填了不报错，也不生效** |
| `DEFILLAMA_BASE` | `DEFILLAMA_BASE_URL` | 同上 |
| `TWITTER_BEARER` | `TWITTER_BEARER_TOKEN` | 同上 |
| `/health` 返回 `{ok, data:{status, db:"connected"}}` | 扁平结构，`db` 是 `"ok"` | 照它写的监控解析不出字段 |
| 指标 `run_total` / `run_errors` / `analyze_latency_seconds` / `db_write_errors` | 四个都不存在 | **面板永远空、告警永不触发** |
| CI 只有一个 `test` 作业 | 6 个作业 + 5 个安全工作流 | 低估了门禁 |
| 「MVP 无迁移需求，V2 引入 Alembic」 | Alembic 已启用，4 个版本 | 跳过 `alembic upgrade` |

其中**最坏的三条**：

1. **挂载路径错**（`-v ./data:/app/backend/data`）—— 挂载不会报错，
   容器跑得好好的，直到容器重建那天数据没了。
2. **四个不存在的环境变量名** —— 填了不报错也不生效。
   **一个填了不生效的配置键，比缺一个更坏**：缺的会被发现，填错的会让人以为配好了。
3. **四个幻影指标名** —— 照它建的面板是空的、告警永不触发。
   **空面板和"系统很健康"长得一模一样。**

三条的共同点：**都不产生任何错误信号。**
这也是为什么这份文档被重写而不是打补丁 —— 一条假行会让读者怀疑其余每一行，
**清单的可信度是有限资源。**

---

## 13. 常见问题

| 现象 | 排查 |
|---|---|
| 端口被占用 | 改 `PORT` / `API_PORT`；`netstat -ano \| findstr :8002`（Win）/ `lsof -i:8002` |
| 容器起来就退出 | 先看 `docker compose logs backend`。生产环境最常见是 `API_KEY` / `AUTH_TOKEN_SECRET` / `CORS_ORIGINS` 不合格被 `config.py` 拒绝启动 —— 用 `./scripts/deploy.sh prod` 会在启动前就告诉你 |
| 「服务启动超时」 | 先确认探测的是 **8002**。历史上这条报错的真因多半是探测地址错了，服务其实好着 |
| DB 锁（SQLite busy） | 并发写冲突。`SQLITE_BUSY_TIMEOUT_SECONDS` 默认 10s；长期方案换 Postgres |
| 库里数据和预期不符 | 极可能连的不是你以为的那个文件。`DB_PATH` 相对路径按进程工作目录解析，详见 OPERATIONS.md §1.2 |
| AI 简报总是走规则引擎 | 看响应里的 `degraded_reason`：`llm_disabled`（没配密钥）/ `budget_exceeded`（预算用完）/ `ledger_unavailable`（账本故障）/ `llm_error`（接口全挂）。**四种的处置动作完全不同** |
| `/api/v1/run` 返回 429 | 频率限制。LLM 开启时 1 次/小时 |
| 依赖安装慢 | `pip install -i https://pypi.tuna.tsinghua.edu.cn/simple` |
| 前端空白 | 确认后端在 8002 且 `CORS_ORIGINS` 含前端地址；浏览器控制台看 CORS 报错 |
| `/metrics` 返回 404 | `METRICS_ENABLED` 被关了 |

---

_文档版本：v2.0（2026-08-24 全文重写）· 配套：[OPERATIONS.md](OPERATIONS.md)（值班）、[SECURITY.md](SECURITY.md)、[OBSERVABILITY.md](OBSERVABILITY.md)_
