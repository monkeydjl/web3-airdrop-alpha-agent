# 代码审查与修复报告 · Web3 Airdrop Alpha Agent System

审查日期：2026-07-26 ｜ 范围：`backend/`（FastAPI + SQLite/PostgreSQL 多智能体评分系统）与 `frontend-next/`（Next.js 16 / React 19）

## 概览

本次对全仓 169 个 Python 模块与全部前端组件做了系统性审查，聚焦正确性、并发/事务、安全、SQLite↔PostgreSQL 行为一致性、异步事件循环与前端数据竞争。共确认并修复 **30 处后端缺陷 + 5 处前端缺陷**，另做 1 处性能优化、4 项增强，并新增 19 个回归测试锁定修复。

修复后基线：后端 **1823 项测试全部通过**（原 1804 + 新增 19），`ruff`（含 bandit 安全规则集）零告警；前端改动文件全部通过 TypeScript 解析校验，`lib` 层严格模式类型检查通过。所有改动已写回本地项目磁盘。

> 说明：审查在云端沙箱进行。由于沙箱无法访问 PyPI，运行测试时用你本机 venv 中的依赖搭建了等价环境，并为 `respx` 编写了轻量兼容层——这些仅用于云端验证，不改动你的项目。

## 严重缺陷（数据丢失 / 功能整体失效 / 安全）

**数据层 · SQLite 保存清空列（数据丢失）** — `repository.py` 的 `save()` 用 `INSERT OR REPLACE`，其本质是 DELETE+INSERT，会把未列出的列（`recommendation` / `weight_version` / `raw_signals` / `raw_signals_hash`）清空、`created_at` 重置。即 seed/导入的数据在首次重新评分后即被破坏，而 PostgreSQL 分支用 `ON CONFLICT DO UPDATE` 却会保留——同一调用两端行为不一致。已改为 SQLite `UPSERT`（3.24+），与 Postgres 语义对齐。

**数据层 · 列表接口在 Postgres 上必 500** — `repository.py` 等多处用 `fetchone()[0]` 取 COUNT，而 Postgres 走 `dict_row`，`row[0]` 抛 `KeyError`。`GET /projects`、`/discoveries`、归档统计全部受影响。统一改用兼容两端的 `scalar()`。

**API · 开启鉴权后跨域整体失效** — 中间件注册顺序使 `APIKeyMiddleware` 在 `CORSMiddleware` 外层，浏览器预检 `OPTIONS`（不带自定义头）被 401 拦截，且所有错误响应不带 CORS 头。已调整为 CORS 最外层，并在鉴权中间件放行 `OPTIONS`。

**评分 · 稀疏项目被整条吞成 None** — Scorer 的“保证 ≥2 条 reason”兜底条件写错且只从 `optional` 取，可能返回 1 条 reason，触发 `ScoreResult` 校验失败，被外层 `except` 吞成 `score=None`。这类记录还因此永不落 `processed`，每次定时任务重复重跑同一批失败项，形成队列堵塞。已改为无条件补齐至 2 条（含按标签的确定性兜底）。

**采集 · 每个定时采集任务静默空转** — `scheduler.py` 引用了不存在的 `result.duplicate_count`（实为 `items_duplicate`），在持久化回调前即抛 `AttributeError`，导致所有定时源采集结果从不落库、从不触发分析。异常兜底分支又用了错误的构造参数会二次抛 `TypeError` 掩盖原始错误。均已修复。

**安全 · Etherscan/CryptoRank 的 API Key 落日志与数据库** — 两个采集器把 key 放在 URL query 里，httpx 异常信息含完整 URL，`str(e)` 被写入 structlog 日志和 `collection_logs.error_message` 永久留存。新增 `app/utils/redact.py` 统一脱敏，并在持久化写入与两个采集器的日志/健康检查处接入。

**Opportunity · 校准报告在正常数据形态下崩溃** — 聚簇自助重采样（cohort bootstrap）在“单项目多 cohort”这一生产常态下，重采样长度会超过固定的 `coverage_denominator`，触发 `ValueError` 使整份校准报告中断。已将 bootstrap 统计的 denominator 改为按重采样自身长度计算。

## 主要缺陷（并发 / 事务 / 逻辑）

事务与并发：`archive.py` 用 `with conn:` 在 `DbConnection` 上会调用 `close()` 而非提交，归档整批被丢弃却仍报告成功——改为显式提交/回滚；`quarantine.py` 的 fallback 缺少 `rollback`，Postgres 首条失败后进入 aborted 事务掩盖真实异常——补齐回滚；`repository.save()` / `update_meta_signals` 对 `meta` 列做无锁读改写会丢信号——接入 `begin_serialized_write()` + Postgres `FOR UPDATE`。

Postgres 兼容：`feedback.py` 两个写端点用 SQLite 专属的 `cursor.lastrowid`，在 Postgres 上插入成功却返回 500 导致客户端重试产生重复行——新增 `insert_returning_id()` 走 `RETURNING`；`db.py` 的 `datetime('now')→NOW()` 改写未处理时区，非 UTC 服务器会偏移——改为 `NOW() AT TIME ZONE 'UTC'`。

Agent 数据依赖：`orchestrator_simple.py` 把 4 个 agent 放同一 `gather`，而 Risk 读取 Tokenomics 的结果、二者却在竞态中 Risk 先执行，导致 Risk 恒用默认值、每个项目都带上错误的“risk estimate uncertain”标记。已拆为两阶段：Narrative/Team/Tokenomics 并行 → Risk。

其他：`pipeline_run.py` 的 `top_projects` 取输入前 10 而非按分数前 10（与 API 文档不符）——改为按分数排序；`rate_limiter.py` 中 Twitter 采集器用 `twitter_kol`/`twitter_keyword` 作 source_id 却未登记，回落到宽 5 倍的默认限流——补登记；每日配额计数从不重置形成进程级永久锁定——加入按 UTC 自然日滚动重置；`funding.py` 的 `_parse_date` 对无偏移字符串返回 naive datetime，与 aware `now` 相减崩溃——统一补 UTC；`defillama`/`galxe` 对 `null` 字段 `.lower()`/`.get()` 崩溃——加兜底；`collections.py` 分页参数无约束可致全表导出/Postgres 负 OFFSET 报错，且注册表漏了 RootData——补 `Query` 约束与注册；Opportunity 显式概率证据绕过来源等级下限，U 档（权重 0）证据可覆盖 A 档规则结论——补 `minimum_grade="B"`。

## 前端缺陷

`ThemeProvider` 的 `!ready` 早返回会在挂载后切换根元素类型，使整棵子树卸载重挂——每次访问重复触发所有 `useEffect`（含付费的 `/ai-brief` POST）并丢失用户输入。已改为始终渲染同一 Provider，并在 `layout.tsx` head 注入首帧前主题脚本消除白屏闪烁。

存储型 XSS：`ParticipationTasks` 与项目详情页把采集来源（可控性弱）的 URL 直接放进 `href`，`javascript:` 伪协议可执行。新增 `safeExternalUrl()` 仅放行 http/https。`InteractionPanel` 对 `net_usd` 直接 `.toFixed()`，后端若以字符串序列化 Decimal 会抛错白屏——改为 `Number(...)` 包裹。`next.config.js` 的开发用 loopback 代理会打进生产构建导致线上 502——加 `NODE_ENV`/`API_PROXY_TARGET` 守卫。

## 优化与增强

优化：`db.py` 的 `executescript` 在 Postgres 上每条 DDL 泄漏一个游标（`init_db` 约 90 条），改为复用单游标并在结束关闭。

增强：新增启动期安全自检——生产环境下 `CORS_ORIGINS='*'` 与凭据同用、或 `API_KEY` 为空时直接拒绝启动；新增 `safeExternalUrl` 外链白名单；主题预渲染脚本消除 FOUC；文档与代码对齐（FARM 阈值 65）。新增 `tests/test_review_regressions.py` 共 19 个回归测试，覆盖 Scorer 最少 reason、UPSERT 保列、密钥脱敏、限流键与每日重置、funding 时区、生产配置校验等关键修复点。

## 已核验的“非缺陷”

审查中对若干疑似项做了核验后判定为误报，未做改动：`InteractionPanel` 提交的交互体与 `lib/types.ts` 声明不符——但后端 `InteractionCreate` 模型实际是宽松的（`wallet_count` 默认 1、assessment 可选），面板可正常工作，仅 TS 类型偏严；`app/project/[id]` 目录未发现会破坏路由的错误命名子目录。

## 验证

- 后端：`pytest` 1823 passed（新增 19 回归用例）；`ruff`（E/F/I/N/W/UP/B/SIM/ARG/RUF/S 全集）零告警。
- 两处最高风险改动（UPSERT、Agent 重排序）经独立对抗式复核确认正确，且被既有测试与新回归用例双重锁定。
- 前端 7 个改动文件通过 TypeScript 解析校验；`lib/format.ts` + `lib/types.ts` 严格模式类型检查通过。
- 全部 38 个改动文件已写回本地 `E:\Github\Web3 Airdrop Alpha Agent System`（0 拒绝）。

## 建议的后续项（本次未做，供参考）

将 `interactions`/`feedback`/`insights`/`export_import` 等以 `async def` 承载阻塞式同步 DB 的路由改为 `def`（交由线程池），可根治单请求拖垮事件循环的问题（`opportunity.py` 已是此正确写法，可作范式）；为 `raw_projects(source_id, dedup_key)` 加唯一索引并把 check-then-insert 收敛为 `ON CONFLICT`，消除并发重复行；引入实际生效的入站限流（`rate_limit_*` 配置目前未接线）。
