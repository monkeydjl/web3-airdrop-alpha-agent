# 2026-08-20

## 本次做了什么

用户要求「以上线为标准审查项目，另外看看有没有需要真假的功能」。分两阶段：**独立复核审查** → **修复全部 P0/P1**。

### 阶段一：审查（推翻了既有报告的结论）

仓库里的 `GO_LIVE_AUDIT_REPORT.md` 写着「✅ 可上线，2428 项测试全绿（本次实测确认）」。实跑后发现**该结论不成立**：

| 项目 | 旧报告声称 | 实测 |
|---|---|---|
| 测试 | 2428 passed, 0 failed（"实测确认"） | 1 failed |
| ruff check | CI 全流程通过 | 99 errors |
| ruff format | — | 31 文件待重排 + 全仓执行时 ruff panic |
| mypy | — | 7 errors |
| 容器启动 | 「可直接按 CHECKLIST 部署」 | 按文档命令必然 CrashLoop |

发现 4 个 P0 + 8 个 P1。**关键教训：不要采信文档里的「已实测确认」，自己跑一遍。**

### 阶段二：修复 + 验证（全部完成）

**P0-1 零凭证窃取 LLM API Key（最严重）**
`routers/v1/settings.py:211` 直接返回含 `api_key` 原文的 `settings.llm_providers`。配合公开的 `/auth/anonymous`，实测走通完整链路：任何人领匿名 token → 读 `/settings/config` → 拿到明文 `sk-...`。
修复：新增 `_safe_providers()` 只输出 `has_api_key` 布尔；并把 `/api/v1/settings` 加入 `ADMIN_ONLY_PREFIXES`（纵深防御）。同仓库 `/llm/status` 早就做了脱敏——说明规范存在，这个端点漏了。

**P0-2 容器按官方文档启动必崩**
`docker-compose.yml` 未透传 `AUTH_TOKEN_SECRET`，镜像内无 `.env`（被 `.dockerignore` 排除），也没 `env_file:`；`APP_ENV` 默认 production 而生产自检强制要求该值。修复：补 `env_file: [.env]`。用真实 docker 验证：旧配置拒绝启动，新配置 `Up (healthy)`。
> 讽刺点：该文件第 46 行有段注释专门讲「上次漏了 API_KEY 害得运维起不来」——同一个坑在 AUTH_TOKEN_SECRET 上原样重现。

**P0-3 两个整页假数据（用户问的"真假功能"核心）**
- `/collections`：零 API 调用，9 个**不存在**的项目（Nova Protocol 等）配虚构评分 + 「官方确认 Q3 代币空投资格」类假情报。空投决策系统里这属于误导性金融信息。修复：接入**早就存在但前端从未用过**的 `GET/DELETE /api/v1/watchlist`。
- `/archive`：虚构归档记录 + 「命中率 99.2%」「38.6 GB」，全部开关 `onChange={() => {}}`。修复：只展示真实保留期配置，明确标注「暂无运行历史接口」。

**P0-4 缓存真 bug + CI 三门**
`fetcher.py` 用 `age > ttl`，`ttl=0`（"不缓存"）时 `0 > 0` 为 False 返回脏数据；Windows 时钟分辨率 15.6ms，实测 20 次里 14 次命中。
**修复过程中补的回归测试又抓到第二层 bug**：改成 `>=` 后仍失败——磁盘 mtime 可能比 `time.time()` **超前**，age 为负。最终改为 `ttl <= 0` 直接短路 + 新增 `invalidate()`。

**P1（全部完成）**：`/settings` 假保存按钮（只弹 toast，旁边文案却说「写入 .env 并热加载」，自相矛盾）→ 整页改只读；`/ops` 假调度块（4 个后端不存在的 job）+ 假配额 → 改真实配置 + 真实 `api_calls_today`；详情页恒显「排名第 1」→ 移除；生产 CORS 含 localhost 拒绝启动；移除 `NEXT_PUBLIC_API_KEY`（会内联进浏览器 bundle 泄露管理员密钥）；统一两份 pyproject 口径并补上缺失的 `--cov-fail-under=80`；GitHub 缺 token 时启动告警。

## 最终验证（全部实跑）

```
pytest -q                    → 2452 passed, 4 skipped, 0 failed（32分40秒，exit 0）
覆盖率                        → 87.66%（门槛 80%）
ruff check                   → All checks passed（原 99 errors）
ruff format --check          → 237 files already formatted（原 31）
mypy app                     → no issues in 112 files（原 7 errors）
前端 tsc / eslint / build     → 全部通过（eslint 0 problems）
docker 真实容器               → Up (healthy)，/health ok
密钥泄露链路                  → 无凭证 401 / 匿名 403 / 管理员 200 且无明文
```

## 决定

- **`/archive` 选"诚实占位"而非补后端**：`app/archive.py` 有真实归档逻辑但没挂路由，补 API 属新功能，超出"修上线阻断"范围。改为展示真实保留期 + 明确说明缺接口。
- **`/collections` 选"接真 API"而非下线**：因为 watchlist 后端完整可用，接上比删掉价值高。
- **`/settings` 选"改只读"而非补写入接口**：配置热写入涉及 .env 落盘 + 重载，风险大且非上线必需；关键是消除「点了说已保存但没保存」的欺骗。
- **SIM118 不照 linter 改**：`sqlite3.Row` 的 `in` 检查的是**值**不是键（实测 `'name' in row` 为 False），照改会让所有可选列静默变 None。加豁免并注明原因。
- **ruff 删掉的 `update_db_gauges` 导入不加回去**：核对确认 gauge 更新真实发生在 `pipeline_run.py`，是测试在 patch 残留符号，遂删除那两行无效 patch。

## 遗留/风险

- **未 git commit**：本次全部改动仍在工作区，用户未要求提交。
- **未推送**：加上之前的 7 个本地 commit，都还没推远程。
- **生产环境仍需人工设定**：`SEED_FALLBACK_ENABLED=false`（已在 .env.example 注明建议）、真实 `CORS_ORIGINS`、`AUTH_TOKEN_SECRET`。
- **Docker 依赖未锁版本**：`requirements.txt` 全浮动 `>=`，不同时间构建可能拿到不同版本（P1-7 只统一了 pyproject 口径，未加 lock）。
- **`/archive` 与 `/ops` 仍缺后端接口**：归档运行历史、调度任务手动触发。当前是诚实占位，不是假数据。
- **旧报告已标注过期**：`docs/GO_LIVE_REPORT.md` 与 `docs/DEPLOYMENT_REPORT_FINAL.md` 顶部加了失效声明，保留作历史归档。

## 相关

- 审查详情：`CODE_REVIEW_REPORT.md`（含实跑证据 + 修复验证记录表）
- 上线结论：`GO_LIVE_AUDIT_REPORT.md`（已重写，替换 07-26 版本）
- 变更记录：`CHANGELOG.md`（Security / Fixed / Changed 三节）
