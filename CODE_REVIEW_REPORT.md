# 上线审查报告（独立复核）

> 审查日期：2026-08-20
> 审查范围：全仓（后端 112 个模块 / 前端 10 个页面 / Docker / CI / 配置 / 文档）
> 审查方式：实跑验证 + 逐项代码核对，不采信既有文档结论
> **初审结论：❌ 暂不可上线** — 4 个 P0 阻断项（1 个密钥泄露、1 个容器必崩、2 个整页假数据）
> **当前状态：✅ P0/P1 全部已修复并验证**（见文末「修复验证记录」）

---

## 修复验证记录（2026-08-20 同日完成）

所有 P0 与 P1 项均已修复，最终验证结果：

| 验证项 | 命令 | 结果 |
|---|---|---|
| 后端全量测试 | `pytest -q` | ✅ **2452 passed, 4 skipped, 0 failed**（32分40秒，exit 0） |
| 覆盖率 | 同上 | ✅ **87.66%**（门槛 80%） |
| lint | `ruff check app tests scripts alembic` | ✅ All checks passed（原 99 errors） |
| 格式 | `ruff format --check ...` | ✅ 237 files already formatted（原 31 待重排） |
| 类型 | `mypy app --config-file pyproject.toml` | ✅ no issues in 112 files（原 7 errors） |
| 前端类型 | `tsc --noEmit` | ✅ 通过 |
| 前端 lint | `eslint .` | ✅ 0 problems（原 6 warnings） |
| 前端构建 | `next build` | ✅ Compiled successfully |
| 容器启动 | `docker run`（真实镜像） | ✅ Up (healthy)，`/health` ok；旧配置如实拒绝启动 |
| 密钥泄露链路 | 生产配置实测三步 | ✅ 无凭证 401 / 匿名 403 / 管理员 200 且响应无明文 |
| watchlist 契约 | 真实增删读回 | ✅ 字段与前端 `WatchlistItem` 完全一致 |

**修复过程中新发现并修掉的两个问题**（初审时未识别）：

1. **缓存 TTL 的第二层 bug**：把 `>` 改成 `>=` 后，我补的 25 轮回归用例仍然失败——因为磁盘文件 mtime 可能比 `time.time()` 略微**超前**，`age` 为负数，`age >= ttl` 同样挡不住。最终改为 `ttl <= 0` 直接短路失效并新增 `invalidate()`。**这是"补测试"而不是"补断言"才抓到的**。
2. **ruff 自动修复引入的测试失败**：`ruff --fix` 正确地删掉了 `scheduler.py` 里确实没用到的 `update_db_gauges` 导入，但两个测试在 patch 这个残留符号。核对后确认 gauge 更新真实发生在 `pipeline_run.py`，遂删除这两行无效 patch（而非把死导入加回去）。

---

---

## 0. 与既有报告的差异（重要）

仓库里的 `GO_LIVE_AUDIT_REPORT.md` 结论是「✅ 可上线，2428 项测试全绿（本次实测确认）」。本次复核**不成立**：

| 项目 | 既有报告声称 | 本次实测 |
|---|---|---|
| 测试结果 | 2428 passed, **0 failed**（实测确认） | **1 failed**, 2438 passed, 4 skipped（34分42秒） |
| ruff lint | CI 全流程通过 ✅ | **99 errors**（app 58 / tests 40 / alembic 1） |
| ruff format | — | **31 个文件需重排**，且 `--check .` 直接 panic 崩溃 |
| mypy | — | **7 errors** |
| 容器启动 | 「按 GO_LIVE_CHECKLIST 执行部署」 | 按文档命令启动**必然崩溃**（见 P0-2） |

既有报告的「本次实测确认」字样与实际不符。**建议不要再以该报告作为上线依据。**

---

## P0 阻断项（必须修完才能上线）

### P0-1 🔴 `/api/v1/settings/config` 明文泄露 LLM API Key

**位置**：`backend/app/routers/v1/settings.py:211`

```python
"providers": settings.llm_providers,   # ← 每个 provider 都含明文 api_key
```

`settings.llm_providers`（`config.py:303-351`）返回的字典里带 `"api_key"` 原文。同仓库的 `/api/v1/llm/status`（`llm.py:45`）对同一数据做了 `_mask_key()` 脱敏——**说明脱敏是既定规范，settings 端点漏了**。

**已实测确认的完整利用链**（生产配置 `APP_ENV=production` + 40 位 API_KEY + 48 位 AUTH_TOKEN_SECRET）：

1. 无凭证访问 → `401`（鉴权正常）
2. `POST /api/v1/auth/anonymous` → `200`，任何人可领匿名 token（该路径在 `auth.py:51` 的 `PUBLIC_PREFIXES` 白名单里，设计如此）
3. 携带匿名 token 访问 `GET /api/v1/settings/config` → **`200`，响应体内含明文 `sk-...`**

即：**任意互联网用户零凭证即可窃取你的 OpenAI/DeepSeek API Key**，直接产生真金白银损失。`settings/config` 不在 `ADMIN_ONLY_PREFIXES`（`auth.py:55-61`）内，匿名角色可读。

**修法（二者都做）**：
1. `settings.py` 改为只输出脱敏字段（复用 `llm.py` 的 `_mask_key`），或只返回 `provider_count` / `has_api_key`；
2. 把 `/api/v1/settings` 加入 `ADMIN_ONLY_PREFIXES`——运行时配置快照属于运维信息，本不该对匿名开放。

> 附带同类风险：该端点还输出 `cors_origins`、`app_env`、`db_backend`、全部阈值与 cron，属于给攻击者的免费侦察情报，一并收进管理员权限为宜。

---

### P0-2 🔴 按官方文档启动容器 100% 崩溃（CrashLoop）

**位置**：`docker-compose.yml:20-51` 与 `backend/app/config.py:472-476` 冲突

`config.py` 的生产自检要求 `AUTH_TOKEN_SECRET` 非空，否则拒绝启动。但 `docker-compose.yml` 的 `environment:` 白名单里**没有透传 `AUTH_TOKEN_SECRET`**（只透传了 `API_KEY`），而镜像里也没有 `.env`（`.dockerignore:7` 排除了它），`docker-compose.yml` 又**没有 `env_file:` 段**。

**已实测确认**：完全按 `docker-compose.yml` 提供的环境变量构造 Settings（`_env_file=None` 模拟容器内无 dotenv），结果：

```
STARTUP: REFUSED -> ValidationError
不安全的生产配置: 生产环境必须设置 AUTH_TOKEN_SECRET
```

`APP_ENV` 在 compose 里默认就是 `production`（第 22 行），所以这是**默认路径**，不是边缘情况。运维照 `GO_LIVE_CHECKLIST.md` 第 192 行敲 `docker compose up -d --build`，容器起不来，且 `restart: unless-stopped` 会让它无限重启。

讽刺的是第 46-48 行有一大段注释专门讲「此前漏了 API_KEY 这一行，运维即使在 .env 里正确设置也传不进容器」——**同一个坑在 AUTH_TOKEN_SECRET 上原样重现了**。

**修法**：给 `docker-compose.yml` 的 backend 服务补 `env_file: [.env]`（与 `docker-compose.prod.yml:65-66` 对齐），或至少补透传这些行：
```yaml
      - AUTH_TOKEN_SECRET=${AUTH_TOKEN_SECRET}
      - CORS_ORIGINS=${CORS_ORIGINS}
      - CORS_CREDENTIALS=${CORS_CREDENTIALS:-true}
      - DEBUG=${DEBUG:-false}
```

---

### P0-3 🔴 `/collections` 与 `/archive` 两个整页是纯编造的假数据

这是你问的「有没有需要真假的功能」里**最严重的两处**。

**`frontend-next/app/collections/page.tsx`** — 全页零 API 调用（grep `fetch|apiFetch|useAsyncData` 无任何命中）：
- 第 24-34 行 `COLLECTIONS`：9 个**虚构项目**，含虚构评分与虚构空投情报，例如
  `Nova Protocol / 0.88 / 截止 2025-08-30 / 备注「官方确认 Q3 代币空投资格与节点绑定；评分决策引擎 v2.0 给出 0.88」`
  ——`Nova Protocol`、`Poly Oracle`、`Kite Network`、`Aether Fi` 等**全部不存在**。
- 第 45-58 行：分组统计（18/12/21/9）与「全部 60」也是写死的。
- 第 67-70 行 `toggleStar`：星标只改本地 state，刷新即丢。

**风险**：这是一个空投投资决策系统。用户在「收藏关注」页看到「官方确认 Q3 空投」这种**具体到能照着做的假情报**，可能真的去交互、真的投钱。这已经超出「UI 未完成」范畴，属于**误导性金融信息**。
（讽刺的是后端 `watchlist.py` 有一套完整可用的收藏 API：`POST/DELETE/GET /api/v1/watchlist`——前端根本没接。）

**`frontend-next/app/archive/page.tsx`** — 同样零 API 调用：
- 第 7-38 行 `POLICIES`：虚构保留策略与「命中率 99.2% / 100%」
- 第 40-46 行 `RECORDS`：虚构归档记录（`#4821 / 2,314 条 / 6.2 GB / 4分12秒`）
- 第 62-83 行：虚构统计（「本月已归档 4,821 / 归档体积 38.6 GB / 较上月 +12%」）
- 全部 Switch 是 `onChange={() => {}}`，「立即归档」「导出清单」「下载」按钮均无 onClick

**风险**：用户会据此判断「归档在正常跑、命中率 99.2%」，而后端 `archive.py` 虽有真实归档逻辑，却**没有任何 HTTP 路由暴露**（`main.py:483-501` 的 include_router 列表里没有 archive）。真实归档状态无从得知。

**修法（选一）**：
- 上线前**下线这两个路由**（从 `Nav.tsx` 移除入口 + 删页面或改成「功能开发中」占位）——最快、最安全；
- 或 collections 接 `watchlist` API、archive 补后端路由后再接。

---

### P0-4 🔴 测试基线不实 + CI 三道门全红

**测试**：实跑 `pytest`（34分42秒）结果 **1 failed, 2438 passed, 4 skipped, 88% coverage**。

失败用例：`tests/test_fetcher_v2.py::TestTwoTierCache::test_disk_cache_expiration`

**根因已定位**（不是环境问题，是真 bug）：`backend/app/utils/fetcher.py:147` 与 `:157`

```python
if time.time() - timestamp > ttl:      # ttl=0 时，同一时刻写入+读取 → 0 > 0 为 False → 返回过期数据
```

Windows 上 `time.time()` 分辨率约 15.6ms（实测连续两次调用差值为 0.0），我循环 20 次复现：**14/20 次返回了应当过期的缓存**。应改为 `>=`。这意味着 `ttl=0`（「不缓存」语义）实际会命中缓存——生产上表现为「明明关了缓存却拿到旧数据」。

**CI 门禁实测**（`.github/workflows/ci.yml` 的 lint / type-check 阶段 `continue-on-error: false`）：

| 门 | 结果 |
|---|---|
| `ruff check .` | **99 errors**（F401 未用导入 41、I001 导入未排序 11、SIM118 10、S110 静默吞异常 3、S105/S106 疑似硬编码密钥 3…） |
| `ruff format --check .` | **31 文件需重排**；且对全仓执行时 ruff 0.16.1 **panic 崩溃**（`Expected a ruff source file`），需按子目录分别跑 |
| `mypy app` | **7 errors**（`auth.py:75`、`settings.py:80`、`repository.py:442`、`calibration.py:114` 等） |

**即：现在推上去 CI 必然红，lint 阶段就断，根本走不到 test。** 前端 `tsc --noEmit` ✅ 通过（唯一全绿的门）。

---

## P1 应修项

### P1-1 🟠 `/settings` 的「保存更改」是假按钮

`frontend-next/app/settings/page.tsx:367-369`
```python
const handleSave = () => {
  setToast({ message: '配置已保存（演示模式 — 实际写入需编辑 .env 并重启服务）', type: 'info' });
};
```
不调用任何 API。页面上有**两个**保存按钮（第 391、821 行）都绑这个函数。

更糟的是第 814 行紧挨着写「修改将在保存后写入 .env 并热加载」——**与 toast 里的「演示模式」自相矛盾**，用户很容易只看到「配置已保存」就以为生效了。用户改完 LLM 接口 / 8 项评分权重 / 调度开关，全部丢弃。

**修法**：文案统一改为只读（如「当前配置只读，修改请编辑 .env 并重启」）并移除保存按钮；或后端补配置写入接口。**不要留一个说「已保存」却什么都不做的按钮。**

### P1-2 🟠 `/ops` 的「定时跑批」整块是假的

`frontend-next/app/ops/page.tsx:48-53` `SCHEDULER_JOBS` 写死 4 个任务及其执行结果（「每日机会评分 · 成功 · 182 条」「AI 简报生成 · 超时 · 已重试」）。这些 job key（`job_daily_opportunity` / `job_discovery_sweep` / `job_ai_brief_daily` / `job_chain_archive`）在后端 `scheduler.py` / `analysis_scheduler.py` 里**均不存在**。
- 第 647 行开关 `onChange={() => {}}` 空操作
- 第 652 行「立即执行」无 onClick
- 第 34-46 行 `SOURCE_QUOTAS` 写死各源 API 配额用量（`github: 318/1000`），非真实用量

注意 ops 页**其余部分是真的**（采集源列表、启停、触发、隔离区释放都接了真实 API），只有这一块和配额是假的——反而更容易骗过人。

### P1-3 🟠 每个项目详情页都显示「排名第 1」

`frontend-next/app/project/[id]/page.tsx:321`
```python
const rank = 1; // TODO: 后端暂无排名接口，前端默认第 1
```
第 407 行渲染成「排名第 1」。打开任何项目都是第 1 名。**建议直接隐藏该字段**，比显示错的好。

### P1-4 🟠 生产环境 CORS 默认放行 localhost

`backend/app/config.py:258-259`
```python
cors_origins: str = "http://localhost:3002,http://localhost:8002"
cors_credentials: bool = True
```
生产自检（`config.py:455`）只拦 `"*"` + credentials 的组合，**不检查生产环境是否仍是 localhost 默认值**。配合 P0-2（compose 不透传 `CORS_ORIGINS`），实际生产跑起来的 CORS 白名单就是 localhost：真实前端域名被挡，形成「上线后前端全部接口跨域失败」。前端 `settings/page.tsx:438` 也把 localhost 作为兜底显示值，进一步掩盖问题。

**修法**：`_validate_production` 增加一条——生产环境 `cors_origins` 含 `localhost`/`127.0.0.1` 时拒绝启动或告警。

### P1-5 🟠 `seed` 兜底数据可能被当成真实采集结果

`backend/app/config.py:286` `seed_fallback_enabled: bool = True`（默认开），`pipeline_run.py:257-263`：当采集队列为空时，自动加载 `seed.py` 里 8 个**硬编码项目**（EigenLayer Pro / Scroll zkEVM / Berachain…，含写死的融资额与投资方）并正常评分入库。

**做得好的地方**：这些记录 `source='seed'`、`fetched_at=NULL`，前端 `lib/format.ts:91` 会显示成「种子数据」——**用户理论上能分辨**，比前面几条干净得多。

**仍需注意**：只有一个小标签作为区分，Dashboard 的汇总数字（项目总数、平均分）会把 seed 项目算进去。生产环境建议显式 `SEED_FALLBACK_ENABLED=false`，让「采集全挂」如实表现为 0 条，而不是用假项目填充。

### P1-6 🟠 `NEXT_PUBLIC_API_KEY` 会把管理员密钥泄露到浏览器

`frontend-next/lib/api.ts:24,34` 支持从 `NEXT_PUBLIC_API_KEY` 读密钥附加到请求头。Next.js 的 `NEXT_PUBLIC_*` 变量会被**编译进客户端 JS bundle**，任何访客都能在 DevTools 里看到。

正确做法项目里已经有了——`proxy.ts:18` 用服务端 `BACKEND_API_KEY` 注入，密钥不出服务端。**建议删掉 `api.ts` 里这条客户端兜底路径**，或在 `.env.example` 中明确标注「仅本地调试，生产禁用」。

### P1-7 🟠 两个 `pyproject.toml` 依赖声明互相冲突

| | 根 `pyproject.toml` | `backend/pyproject.toml` |
|---|---|---|
| version | 0.1.0 | 1.0.0 |
| requires-python | >=3.11 | >=3.10 |
| fastapi | >=0.110.0（浮动） | ==0.115.12（钉死） |
| mypy python_version | 3.11 | 3.13 |
| 覆盖率门槛 | `--cov-fail-under=80` | **无** |

CI 的 mypy 用 `--config-file pyproject.toml`（在 `backend/` 下执行，取的是 backend 那份），而 ruff 取根那份。`backend/requirements.txt` 又是第三套浮动版本（`fastapi>=0.110.0`）。**Docker 镜像装的是 requirements.txt（全浮动，无 lock）**——今天构建和下周构建可能拿到不同版本，生产不可复现。

**修法**：明确单一事实来源（建议只留根 `pyproject.toml`），Docker 改用钉死版本或加 lock 文件。

### P1-8 🟠 GitHub 采集源在无 token 时静默禁用，与文档矛盾

`backend/app/collectors/github.py:130-132` `is_enabled()` 要求 `settings.github_token` 非空，而 `GO_LIVE_CHECKLIST.md:75` 写「GitHub（P0，免费）：`GITHUB_ENABLED=true`，**建议**设置 `GITHUB_TOKEN`」——按文档理解 token 是可选的，实际不设就整源不跑，且没有任何启动告警。评分里 `weight_execution=0.13`（GitHub 活跃度）会因此永久缺失。

---

## ✅ 真实且质量不错的部分（避免误伤）

审查中确认这些**不是**假功能，实现扎实：

- **9 个采集器全部发真实 HTTP 请求**（`httpx.AsyncClient` + 真实 endpoint + 真实字段解析）。全仓 `random` 只出现 3 次，均为统计用途（`calibration.py:318` gamma 采样、bootstrap），**没有一处伪造业务数据**。付费源无 key 时是干净跳过（`is_enabled()` 返回 False），不伪造。
- **采集器刻意不写死赛道**：`galxe.py:188`、`etherscan.py:267`、`twitter.py:211`、`layer3.py:156` 都留了注释说明「写死 sector 会隔断跨源合并」，宁可留空——这是很克制的正确取舍。
- **限流真实有效**（`rate_limit.py`）：进程内滑动窗口 + 429/Retry-After，`/run` 按 LLM 开关分档，且**默认不采信 X-Forwarded-For**（`:128-135` 解释了采信首值会让攻击者伪造 header 绕过限流）——比多数项目考虑得细。
- **鉴权分层正确**：双令牌（管理员 key + HMAC 匿名 token）、`hmac.compare_digest` 防时序攻击、匿名访问 `/run` 实测返回 403。
- **中间件顺序有意为之**：限流在鉴权外层（`main.py:272-276` 注明「否则爆破 key 的请求走不到限流」），CORS 最外层。
- **其余 8 个前端页面接的是真实 API**：`/`、`/project/[id]`、`/discoveries`、`/insights`、`/portfolio`、`/notifications`、`/settings`（只读部分）、`/ops`（采集源部分）。
- 88% 测试覆盖率、2438 个用例、Prometheus 指标 + Grafana + Loki + OTel 配置齐备、非 root 容器 + 多阶段构建。

---

## 上线前行动清单（按顺序）

**必做（P0）**
1. `settings.py:211` 脱敏 LLM key + 把 `/api/v1/settings` 收进 `ADMIN_ONLY_PREFIXES`
2. `docker-compose.yml` 补 `env_file: [.env]`（至少透传 `AUTH_TOKEN_SECRET` / `CORS_ORIGINS`）
3. 下线（或接真实 API）`/collections` 与 `/archive` 两个页面
4. 修 `fetcher.py:147,157` 的 `>` → `>=`；跑 `ruff check --fix` + `ruff format` + 修 7 个 mypy 错误，直到三门全绿

**强烈建议（P1）**
5. `/settings` 保存按钮改为只读文案或接真实写入；`/ops` 定时跑批块下线或接后端
6. `project/[id]` 隐藏「排名第 1」
7. 生产自检增加 CORS localhost 检查；生产 `.env` 显式设 `SEED_FALLBACK_ENABLED=false`
8. 删除 `api.ts` 的 `NEXT_PUBLIC_API_KEY` 客户端兜底
9. 统一 pyproject 依赖来源，Docker 钉死版本
10. GitHub 无 token 时启动打告警日志

**修完后重跑**：`pytest -q` → `ruff check .` → `ruff format --check`（分目录）→ `mypy app` → `npm run typecheck && npm run build` → 容器启动冒烟 → 重写 `GO_LIVE_AUDIT_REPORT.md` 结论。

---

_审查人：AI Agent（独立复核）· 日期：2026-08-20 · 所有结论均基于实跑或逐行代码核对，未采信既有文档_
