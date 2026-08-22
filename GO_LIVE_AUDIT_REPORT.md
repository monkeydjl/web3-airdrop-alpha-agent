# 上线审核报告

> 审核日期：2026-08-20（替换 2026-07-26 版本）
> 审核依据：`docs/GO_LIVE_CHECKLIST.md` P0/P1 项 + `docs/SECURITY.md`
> 审核方式：全部结论基于实跑命令或逐行代码核对
> 详细问题清单见 [`CODE_REVIEW_REPORT.md`](CODE_REVIEW_REPORT.md)

---

## ⚠️ 关于 2026-07-26 版本的更正

上一版本报告结论为「✅ 可上线 — P0 + P1 全部通过」，并声称「2428 passed, 0 failed（本次实测确认）」。**2026-08-20 复核发现该结论不成立**：

| 项目 | 旧报告声称 | 复核实测 |
|---|---|---|
| 测试 | 2428 passed, **0 failed**（实测确认） | **1 failed**, 2438 passed, 4 skipped |
| ruff check | CI 全流程通过 ✅ | **99 errors** |
| ruff format | — | **31 文件待重排**，全仓执行时 ruff panic |
| mypy | — | **7 errors** |
| 容器启动 | 「可直接按 CHECKLIST 部署」 | 按文档命令**必然 CrashLoop** |
| `/settings/config` | 「密钥只返回布尔值」 | **明文回显 LLM api_key** |

教训：报告里写「本次实测确认」之前必须真的跑一遍并粘贴输出。本版所有结论均附实跑证据。

---

## 总评

**结论：⚠️ 修复后待最终验证 — 4 个 P0 已全部修复并验证**

2026-08-20 复核发现 4 个 P0 阻断项，均已修复：密钥泄露链路已封堵（实测匿名 403 / 管理员 200 且响应无明文）、容器已能真实启动（实测 `Up (healthy)`）、缓存 TTL bug 已修（新增 50 轮回归用例）、CI 三门已全绿。

---

## P0 阻断项 — 已全部修复 ✅

### ✅ P0-1：`/settings/config` 明文泄露 LLM API Key（已修复）

**原问题**：`routers/v1/settings.py` 直接返回 `settings.llm_providers`，其中含 `api_key` 原文。配合公开的 `POST /api/v1/auth/anonymous`（设计上任何人可领匿名 token），构成**零凭证窃取 OpenAI/DeepSeek 密钥**的完整链路——已实测复现三步全通。

**修复**：新增 `_safe_providers()` 只输出 `name` / `base_url` / `has_api_key` / `models`；并把 `/api/v1/settings` 加入 `ADMIN_ONLY_PREFIXES`（纵深防御——运行时配置快照含 CORS 白名单与全部阈值，本就属运维信息）。

**验证**（生产配置下实测）：
```
1) 无凭证        -> 401
2) 匿名 token    -> 403，响应体无明文
3) 管理员 key    -> 200，providers = [{name, base_url, has_api_key:true, models}]
```
回归用例：`tests/api/test_settings.py::TestSettingsConfigLlmKeyRedaction`（canary 全文搜索）+ `TestSettingsRequiresAdmin`。

### ✅ P0-2：按官方文档启动容器必然 CrashLoop（已修复）

**原问题**：`docker-compose.yml` 的 `environment:` 白名单未透传 `AUTH_TOKEN_SECRET`，镜像内无 `.env`（`.dockerignore` 排除），也没有 `env_file:`；而 `APP_ENV` 默认 `production`，生产自检强制要求该值 → `docker compose up -d --build` 100% 起不来，且 `restart: unless-stopped` 会无限重启。

**修复**：补 `env_file: [.env]`，与 `docker-compose.prod.yml` 对齐。

**验证**（真实 docker，镜像 `airdrop-alpha:p0verify`）：
```
A) 旧行为（不传 AUTH_TOKEN_SECRET） -> ValidationError: 生产环境必须设置 AUTH_TOKEN_SECRET
B) 新行为（env_file 提供）          -> Up (healthy)
   /health -> {"ok":true,"status":"healthy","db":"ok",...}
   /api/v1/settings/config 无凭证 -> 401
```

### ✅ P0-3：`/collections` 与 `/archive` 整页虚构数据（已修复）

**原问题**：两页零 API 调用。`/collections` 展示 9 个**不存在**的项目（Nova Protocol / Poly Oracle…）配虚构评分与「官方确认 Q3 代币空投资格」类假情报——对空投决策系统属**误导性金融信息**；`/archive` 展示虚构归档记录与「命中率 99.2%」「已归档 38.6 GB」，全部开关为 `onChange={() => {}}`。

**修复**：
- `/collections` 接入既有但从未被前端使用的 `GET/DELETE /api/v1/watchlist`，取消收藏为真实写入，空库显示空状态引导文案
- `/archive` 改为只展示 `/settings/config` 里真实的保留期配置，并明确标注「暂无运行历史接口」（`app/archive.py` 有真实逻辑但未挂路由）

### ✅ P0-4：测试基线不实 + CI 三门全红（已修复）

**测试失败根因**（真 bug，非环境问题）：`app/utils/fetcher.py` 的两层缓存用 `age > ttl` 判过期，`ttl=0`（语义"不缓存"）时 `0 > 0` 为 False 而返回脏数据。修复中还发现第二层问题：磁盘文件 mtime 可能比 `time.time()` 略微**超前**，age 为负数，连 `>= ttl` 也挡不住。最终改为 `ttl <= 0` 直接短路失效 + 新增 `invalidate()`。

**CI 三门修复结果**（实跑）：
```
ruff check  app tests scripts alembic  -> All checks passed!      (原 99 errors)
ruff format --check ...                -> 237 files already formatted  (原 31 待重排)
mypy app --config-file pyproject.toml  -> Success: no issues found in 112 source files  (原 7 errors)
前端 tsc --noEmit                       -> 通过
前端 eslint                             -> 0 problems（原 6 warnings）
前端 next build                         -> Compiled successfully
```

> 注：修 ruff 时发现 SIM118 对 `sqlite3.Row` 是**假阳性**——`"col" in row` 检查的是**值**而非键（实测 `'name' in row` 为 False、`'alpha' in row` 为 True），照建议改会让所有可选列静默变 None。已在 `pyproject.toml` 加豁免并注明原因，而不是盲从 linter。

---

## P1 项 — 已修复 ✅

- ✅ **`/settings` 假保存按钮**：`handleSave` 只弹「配置已保存」toast 却不写任何东西，旁边文案又写「保存后写入 .env 并热加载」，自相矛盾。整页改为明确只读（标题标注「只读」、输入框改文本、开关 `disabled`），删除保存按钮
- ✅ **`/ops` 假调度块 + 假配额**：`SCHEDULER_JOBS` 写死 4 个后端不存在的 job 及其执行结果，开关空操作、「立即执行」无 onClick；`SOURCE_QUOTAS` 写死配额。改为展示真实调度配置 + 后端真实 `api_calls_today`
- ✅ **项目详情页恒显「排名第 1」**：`const rank = 1` 写死，已移除该字段
- ✅ **生产 CORS 校验**：`CORS_ORIGINS` 含 localhost/127.0.0.1 时拒绝启动（默认值就是 localhost，忘配会让真实前端域名全部跨域失败）
- ✅ **`NEXT_PUBLIC_API_KEY` 浏览器泄露**：`NEXT_PUBLIC_*` 会内联进客户端 bundle，任何访客可在 DevTools 读到管理员密钥。已移除该兜底路径，鉴权统一走服务端 `proxy.ts`
- ✅ **两份 pyproject 口径冲突**：version 1.0.0→0.1.0、requires-python >=3.10→>=3.11、mypy 3.13→3.12（对齐 CI/Dockerfile），并补上缺失的 `--cov-fail-under=80`（pytest 从 `backend/` 运行用的正是这份，此前本地跑测试完全不校验覆盖率）
- ✅ **GitHub 无 token 静默禁用**：`is_enabled()` 要求 token，缺则整源不跑，而 execution 维度占 13% 权重会永久缺失。启动时改为显式 warning
- ✅ **`dashboard.py` 静默 `pass`**：改记 debug 日志，避免真实 SQL 故障被吞、面板恒显 0 无从排查

---

## 仍需运维决策的事项（非代码缺陷）

1. **`SEED_FALLBACK_ENABLED` 生产建议设为 `false`**（默认 `true`）：采集全挂时会用 8 个硬编码种子项目填充并正常评分入库。这些记录 `source='seed'`、`fetched_at=NULL`，前端显示「种子数据」，**用户可分辨**；但 Dashboard 汇总数字会把它们算进去。生产宜让「采集全挂」如实表现为 0 条
2. **Docker 依赖未锁版本**：镜像装的是 `backend/requirements.txt`（全浮动 `>=`），今天与下周构建可能拿到不同版本。建议钉死或加 lock 文件
3. **付费采集源按需开启**：Twitter / Galxe / Layer3 / RootData / Dune 默认关闭，无 key 时干净跳过（不伪造数据）

---

## ✅ 复核确认的既有优点

- **9 个采集器全部发真实 HTTP 请求**（`httpx.AsyncClient` + 真实 endpoint + 真实字段解析）。全仓 `random` 仅 3 处且均为统计用途（gamma 采样 / bootstrap），**无一处伪造业务数据**
- **采集器刻意不写死赛道**：`galxe.py:188`、`etherscan.py:267`、`twitter.py:211`、`layer3.py:156` 均注明「写死 sector 会隔断跨源合并」，宁可留空
- **限流真实有效**：进程内滑动窗口 + 429/Retry-After，`/run` 按 LLM 开关分档，且**默认不采信 X-Forwarded-For**（注释说明采信首值会让攻击者伪造 header 绕过限流）
- **鉴权分层正确**：双令牌 + `hmac.compare_digest` 防时序攻击；匿名访问 `/run` 实测 403
- **中间件顺序有意为之**：限流在鉴权外层（否则爆破 key 的请求走不到限流），CORS 最外层
- 88% 测试覆盖率、Prometheus + Grafana + Loki + OTel 齐备、非 root 容器 + 多阶段构建

---

## 上线步骤

1. `.env` 设置：`APP_ENV=production`、`API_KEY`（≥32）、`AUTH_TOKEN_SECRET`（≥48）、`CORS_ORIGINS`（**真实域名，不能含 localhost**）、`DB_BACKEND=postgres`、`POSTGRES_PASSWORD`、建议 `SEED_FALLBACK_ENABLED=false`
2. `docker compose --profile postgres up -d --build`
3. `docker exec airdrop-alpha-backend alembic upgrade head`
4. 冒烟：`/health` 返回 healthy → `/metrics` 有数据 → 无凭证访问 `/api/v1/projects` 返回 401 → 管理员 key 正常
5. 确认启动日志无 `collector_disabled_missing_credential` 警告（或已知悉对应源不跑）

---

_审核人：AI Agent（独立复核）· 日期：2026-08-20 · 依据：GO_LIVE_CHECKLIST.md + SECURITY.md + 实跑验证_
