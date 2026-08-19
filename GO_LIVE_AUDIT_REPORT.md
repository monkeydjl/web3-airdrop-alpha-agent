# 上线审核报告

> 审核日期：2026-07-26
> 审核依据：`docs/GO_LIVE_CHECKLIST.md` P0/P1 项 + `docs/SECURITY.md`
> 测试基线：2428 passed, 4 skipped, 0 failed, 0 errors（本次实测确认）

---

## 总评

**结论：✅ 可上线 — 2 个 P0 阻断项已修复（2026-07-26）**

代码质量、测试覆盖、安全自检、监控告警都已到位。P0 部署配置问题（Dockerfile 路径冲突 + Python 版本不匹配）已修复。剩余 P1 项不影响上线，建议上线后一周内补齐。

---

## P0 阻断项 — 已全部修复 ✅

### ✅ P0-1：Dockerfile 路径冲突（已修复）

**已修复**：删除了 `backend/Dockerfile`，`docker-compose.yml` 第 10 行改为 `dockerfile: docker/Dockerfile`，与 `docker-compose.prod.yml` 和 CI 对齐。`docs/GO_LIVE_CHECKLIST.md` 中的构建命令也同步更新。

### ✅ P0-2：Python 版本不匹配（已修复）

**已修复**：CI（ci.yml + security.yml）和 `docker/Dockerfile` 统一到 Python 3.12。

---

## P1 强烈建议项

### 🟡 P1-1：`X-Disclaimer` 响应头缺失

**问题**：`SECURITY.md §7.5` 要求 API 响应头含 `X-Disclaimer: Not investment advice.`，但 `backend/app/main.py` 和所有中间件中均未实现。前端有免责声明（`layout.tsx` / `AiBriefPanel.tsx`），但 API 层没有。

**影响**：合规层面缺失。商用部署时可能需要。

**修复建议**：在 `main.py` 的 `create_app` 中加一个轻量中间件给所有响应加 `X-Disclaimer` 头。

### 🟡 P1-2：告警规则偏弱

**问题**：`alert_rules.yml` 只有 4 条规则，缺少 GO_LIVE_CHECKLIST 要求的：
- `HighAPIErrorRate`（错误率 > 0.1/s，5m，critical）— 缺失
- `PipelineConsecutiveFailures`（≥ 2 次失败，critical）— 缺失，只有 `PipelineFailureRate`（任何触发即告警，过于敏感）

**修复建议**：补充这两条规则。需要确认 metrics.py 暴露了 `http_requests_total{status=~"5.."}` 类指标。

### 🟡 P1-3：`AUTH_TOKEN_SECRET` 默认随机（重启失效）

**问题**：`config.py` 中 `auth_token_secret` 默认为空，空时进程级随机生成。生产环境若不设置 `AUTH_TOKEN_SECRET`，每次容器重启所有已签发的匿名 token 失效。

**影响**：已在 GO_LIVE_CHECKLIST 中列出但容易遗漏。config.py 的生产自检**不校验此项**。

**修复建议**：在 `config.py` 的 `_validate_production` 中增加：生产环境 `auth_token_secret` 为空时报错。

### 🟡 P1-4：SQLite WAL 模式未显式开启

**问题**：`GO_LIVE_CHECKLIST` 推荐 SQLite 模式，`db.py` 中 `init_db` 有 WAL 相关逻辑但依赖配置。并发写场景（多项目评分）可能出现 `database is locked`。

**影响**：SQLite 模式下高并发可能不稳定。

**修复建议**：确认 `init_db` 显式执行 `PRAGMA journal_mode=WAL`。生产推荐切换 PostgreSQL。

---

## 已通过项（✅ 确认可上线）

### ✅ 测试全套通过
- **2428 passed, 4 skipped, 0 failed**（本次实测，19 分 40 秒）
- 覆盖单元 / 集成 / 契约 / Golden / API 五类
- 覆盖率 ≥ 80%（pyproject.toml 强制）

### ✅ 生产安全自检
- `APP_ENV=production` + 空 API_KEY → 启动拒绝 ✅
- `API_KEY` 长度 < 32 → 启动拒绝 ✅
- `CORS_ORIGINS=*` + `CORS_CREDENTIALS=true` → 启动拒绝 ✅
- `APP_ENV` 大小写/空格变体归一化 → 全部捕获 ✅

### ✅ 鉴权与限流
- `APIKeyMiddleware`：Bearer + X-API-Key 双方式 ✅
- 匿名 token HMAC-SHA256 签名，72h TTL ✅
- `RateLimitMiddleware`：IP 滑动窗口 + 429/Retry-After ✅
- 管理员专属端点隔离（/run, /re-score, /export, /import）✅

### ✅ 日志脱敏
- `structlog` redact processor 安装在模块加载时 ✅
- 按 `*_key|*_token|*_bearer|authorization|password` 字段名脱敏 ✅
- 500 响应不回显异常原文（防 DSN/apikey 泄漏）✅

### ✅ Docker 安全
- 非 root 用户 `appuser`（uid 1000）✅
- 多阶段构建，builder 不进最终镜像 ✅
- HEALTHCHECK 配置 ✅
- 基础镜像 `python:3.11-slim`（非 latest）✅

### ✅ 可观测性
- Prometheus 73 条指标 ✅
- Grafana Dashboard 配置 ✅
- Loki 日志收集配置 ✅
- `/metrics` 端点 ✅
- `/health` 降级返回 503 ✅

### ✅ CI/CD
- lint（ruff）→ test（pytest）→ docker build → smoke test 全流程 ✅
- security.yml：pip-audit + detect-secrets + Trivy 扫描 ✅
- frontend CI：typecheck + build + npm audit ✅

### ✅ 数据备份
- `scripts/auto_backup.ps1` + `scripts/backup.sh` ✅
- 卷挂载持久化 ✅

### ✅ 回滚方案
- GO_LIVE_CHECKLIST 含完整回滚命令 ✅
- Alembic 迁移支持 downgrade ✅

---

## 上线前行动清单

### 必须做（阻断上线）
1. **修复 Dockerfile 路径** — 删除 `backend/Dockerfile`，改 `docker-compose.yml` 第 10 行为 `dockerfile: docker/Dockerfile`
2. **统一 Python 版本** — CI + Dockerfile 统一到 3.12（或确认 3.11 全依赖兼容后保持 3.11）

### 强烈建议（上线后一周内）
3. **补充 `X-Disclaimer` 响应头** — main.py 加中间件
4. **补充告警规则** — HighAPIErrorRate + PipelineConsecutiveFailures
5. **生产自检增加 AUTH_TOKEN_SECRET 校验** — config.py `_validate_production`
6. **确认 SQLite WAL 显式开启** — db.py init_db

### 上线步骤
1. 修复 P0-1 和 P0-2
2. 在 `.env` 设置生产配置（API_KEY ≥32 字符 / AUTH_TOKEN_SECRET ≥48 字符 / DB_BACKEND=postgres）
3. `docker compose --profile postgres up -d --build`
4. 按 GO_LIVE_CHECKLIST 执行冒烟测试
5. 确认 `/health` 返回 healthy + `/metrics` 有数据 + Grafana Dashboard 正常

---

_审核人：AI Agent · 审核日期：2026-07-26 · 依据：GO_LIVE_CHECKLIST.md + SECURITY.md_
