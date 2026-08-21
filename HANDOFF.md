# HANDOFF — 2026-08-20

## 项目当前状态

多智能体 Web3 空投评分系统（后端 FastAPI + 前端 Next.js 16）。**2026-08-20 完成一次以上线为标准的独立复核，发现并修复 4 个 P0 阻断项 + 8 个 P1**，全部验证通过：

```
pytest -q          → 2452 passed, 4 skipped, 0 failed（exit 0，32分40秒）
覆盖率              → 87.66%
ruff check/format  → 全绿
mypy app           → 全绿
前端 tsc/eslint/build → 全绿
docker 真实容器     → Up (healthy)
```

**改动全部在工作区，未 commit、未推送。** 加上此前 7 个本地 commit 也未推远程。

## 本次会话做了什么

1. **推翻了旧的上线结论**：`GO_LIVE_AUDIT_REPORT.md` 声称「可上线，2428 测试全绿（本次实测确认）」，实跑发现 1 failed + CI 三门全红（ruff 99 errors / format 31 文件 / mypy 7 errors）+ 容器按文档启动必崩。
2. **修完 4 个 P0**：
   - **零凭证窃取 LLM API Key**：`/settings/config` 明文回显 `api_key`，配合公开的 `/auth/anonymous` 构成完整泄露链路（已实测复现）。改为脱敏 + 端点收进管理员权限。
   - **容器必然 CrashLoop**：`docker-compose.yml` 漏传 `AUTH_TOKEN_SECRET`（镜像无 `.env`、无 `env_file`），补 `env_file: [.env]`。
   - **两个整页假数据**：`/collections` 展示 9 个不存在的项目配虚构空投情报 → 接真实 watchlist API；`/archive` 虚构归档统计 → 改真实保留期配置 + 诚实标注缺接口。
   - **缓存 TTL bug + CI 三门**：`ttl=0` 会返回脏数据（含"mtime 超前导致 age 为负"的第二层问题），三门修至全绿。
3. **修完 8 个 P1**：假保存按钮、假调度块、恒显「排名第 1」、生产 CORS localhost 校验、移除 `NEXT_PUBLIC_API_KEY`（浏览器泄露密钥）、统一 pyproject、GitHub 缺 token 告警、dashboard 静默 pass。
4. **补回归测试**：key 脱敏（canary 全文搜索）、管理员鉴权、`ttl=0`（50 轮）、生产 CORS。
5. **更新文档**：重写 `GO_LIVE_AUDIT_REPORT.md`、`CODE_REVIEW_REPORT.md`、`CHANGELOG.md`；修正 README/CHECKLIST 基线数字；给两份过期报告加失效声明。

## 进行中的工作（未完成）

**无进行中任务** —— P0/P1 全部修完并验证。

## 下一步（给下一个会话的行动清单）

- [ ] **决定是否 commit**：本次改动较大（后端 ~15 文件 + 前端 ~8 文件 + 文档 6 份），建议按 `fix(security)` / `fix(deploy)` / `fix(frontend)` / `chore(lint)` / `docs` 分批提交
- [ ] **考虑 git push**：确认远程仓库地址，推送本地累计的 commit
- [ ] **上线前人工设定**：`.env` 里 `APP_ENV=production`、`API_KEY`（≥32）、`AUTH_TOKEN_SECRET`（≥48）、`CORS_ORIGINS`（**真实域名，含 localhost 会拒绝启动**）、`SEED_FALLBACK_ENABLED=false`
- [ ] **可选补后端接口**：归档运行历史（`app/archive.py` 有逻辑无路由）、调度任务手动触发、项目排名。补上后 `/archive`、`/ops`、详情页可以从"诚实占位"升级为完整功能
- [ ] **可选**：给 Docker 依赖加 lock（`requirements.txt` 目前全浮动 `>=`，不同时间构建版本可能不同）

## 如何运行与验证

### 启动

```bash
# 后端
cd backend && pip install -e ".[dev]"
python -m uvicorn app.main:app --host 0.0.0.0 --port 8002

# 前端（另开终端）
cd frontend-next && npm install && npm run dev   # http://localhost:3002

# Windows 一键
Start.bat

# Docker（现已可用）
docker compose up -d --build
```

### 验证（本次实际跑过的命令）

```bash
cd backend
pytest -q                                            # 2452 passed, 4 skipped, 0 failed
python -m ruff check app tests scripts alembic       # All checks passed
python -m ruff format --check app tests scripts alembic
python -m mypy app --config-file pyproject.toml      # 112 files, no issues

cd ../frontend-next
npm run typecheck && npm run lint && npm run build
```

> ⚠️ **注意两个环境陷阱**：
> 1. `ruff format --check .`（全仓，带点）在 ruff 0.16.1 会 **panic 崩溃**（`Expected a ruff source file`）。必须按子目录跑：`ruff format --check app tests scripts alembic`。
> 2. 全量 pytest 约 **33 分钟**，不要以为卡住了。用 `venv\Scripts\python.exe` 跑（venv 是 3.11，系统 python 是 3.14）。

## 已知问题 / 风险

1. **改动未提交** —— 全部在工作区
2. **`/archive` 与 `/ops` 部分区块仍无后端接口** —— 当前是诚实占位（明确写"暂无接口"），不是假数据，但功能不完整
3. **Docker 依赖未锁版本** —— 生产不完全可复现
4. **`SEED_FALLBACK_ENABLED` 默认 true** —— 生产建议关掉，否则采集全挂时会用 8 个内置种子项目填充（标记 `source='seed'`、前端显示「种子数据」，用户可分辨，但会计入 Dashboard 汇总）
5. **`data/pytest_tmp/` 等目录偶发文件锁** —— 会让 `glob`/`grep` 全仓搜索报权限错误，改用子目录搜索即可

## 关键决定（及理由）

- **`/archive` 选诚实占位而非补后端**：补 API 属新功能，超出"修上线阻断"范围
- **`/collections` 选接真 API 而非下线**：watchlist 后端完整可用，接上比删掉价值高
- **`/settings` 选改只读而非补写入**：关键是消除「点了说已保存但实际没保存」的欺骗，而非新增热写配置能力
- **SIM118 不照 linter 改**：`sqlite3.Row` 的 `in` 检查的是**值**不是键，照改会让可选列静默变 None（已加豁免并注明）
- **不把 ruff 删掉的 `update_db_gauges` 导入加回去**：核对确认 gauge 更新真实发生在 `pipeline_run.py`，是测试在 patch 残留符号

---

_交接日期：2026-08-20 · 会话记忆见 `SESSION_MEMORY_2026-08-20.md` · 审查详情见 `CODE_REVIEW_REPORT.md` · 上线结论见 `GO_LIVE_AUDIT_REPORT.md`_
