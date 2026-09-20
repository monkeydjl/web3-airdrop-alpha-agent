# 2026-08-31

> 本 session 一条线走完：全项目独立审核 → P1 修复 → V3 设计文档 → 按 M1 里程碑
> 实施完 F1 决策推送 + F2 参与流水。三个栈式分支全部本地就绪未 push。
> 全量套件最终 **3129 passed / 0 failed / 88.93%**（基线 3083）。

---

## 一、这个 session 在干什么（给接手的人）

| 阶段 | 分支 | 产出 |
|---|---|---|
| ① 全项目审核 | 无（只读） | 4 维并行探查（安全/后端质量/前端/测试与基建），出审核报告；结论：无 P0，5 个 P1 |
| ② 修复 P1-1~3 | `fix/p1-audit-hardening`（5 提交） | 匿名 token 身份 / 队列中毒 / webhook 签名密钥改名 / release 门禁 |
| ③ V3 设计文档 | `docs/action-loop-design`（1 提交） | `ACTION_LOOP_DESIGN.md` 四子系统 + GLOSSARY 5 个新术语（标「设计稿」） |
| ④ M1 实施 | `feat/action-loop-m1`（8 提交） | F1 决策推送 + F2 参与流水，全量绿 |

分支是**栈式**的：`fix/p1-audit-hardening` ← `docs/action-loop-design` ←
`feat/action-loop-m1`。合并必须按此顺序，后两个的 PR 才能干净地 rebase。

### ② 修了什么（审核 P1）

1. **匿名 token 不再接受调用方自报 `user_id`**（`routers/v1/auth.py`）—— 公开端点 +
   客户端身份 = 任何人能给别人的 user_id 签 token，读写按 user_id 隔离的
   watchlist/feedback/interactions。现在一律服务端生成 `anon-<uuid>`，
   请求字段从 schema 删除。原测试 `test_issue_with_custom_user_id` 把漏洞钉成
   预期行为，已反转为钉住修复方向。
2. **分析队列中毒防护**（`agents/collector.py`）—— 一条坏 `raw_data` /
   `discovered_at` 曾让整批 collect 抛异常且该行永远留在队列头，流水线永久卡死。
   现在坏行 quarantine + 跳过；三处复制粘贴的隔离块抽成 `_quarantine_row()`。
3. **`ALCHEMY_API_KEY` 改名 `ALCHEMY_WEBHOOK_SIGNING_KEY`** —— 它的唯一消费方
   就是 webhook 签名校验，拿 Data API key 填旧键时合法回调永远 401。
   **owner 需改 `.env` 键名（值不变）**，本 session 未读 `.env` 无法代改。
4. **release.yml 加 Release Test Gate**（ruff+mypy+全量 pytest）+ 构建 no-cache ——
   tag push 不触发 CI，发布镜像的 commit 可能从未过测试；gha 缓存会把带 CVE 的
   旧基础层带进发布镜像（security.yml 已因此改 no-cache，release 漏同步）。

### ④ M1 交付（按 ACTION_LOOP_DESIGN §2/§3）

**F1 决策推送**：`app/notify/`（evaluator 纯评估 / senders 双通道 / service 编排）；
`notify_log` 表（alembic 0005）；调度 job `notify_digest`（默认 09:00 UTC）；
pipeline 落库钩子实时评估；`/api/v1/notify/*` 三端点（整前缀管理员锁）；3 个指标。
`NOTIFY_ENABLED` 默认 false —— **关开关≠停审计**（评估照常留痕，只是不发送）。

**F2 参与流水**：`participation_plans/tasks`（alembic 0006），plan 四态 / task 四态
状态机闭表（非法迁移 422）；**user_id 只来自 token，请求体自报被忽略**（P1-1 同款
教训）；建议清单一键 seed（按生成 id 去重）；前端 `ParticipationTasks` 接服务端
（乐观更新 + 失败回滚），本机 `aa-task-done:*` 勾选开始参与时一次性迁移后清除。

---

## 二、owner 的关键决策（沿用 + 新增）

1. （08-30 已拍板，仍有效）域名白名单「诚实口径」；校准门槛 200/30 不调低。
2. （本 session）审核 P1-4（事件循环阻塞）与 P1-5（前端代理注入管理员密钥）
   **未修**，owner 默认了"先交付 M1"——**公网部署前必须回头处理**，尤其 P1-5：
   推送上线后它会把「面板越权」升级成「主动外呼越权」。
3. 设计文档四子系统的红线：**永不自动执行链上交互**（只提醒不代签）；Dune 不接
   （建议删死配置）。

---

## 三、技术要点 + 给接手 AI 的坑（这次全量套件抓出来的都是真金）

1. **日志事件名必须是调用点字面量**。OBSERVABILITY parity 门禁用正则扫
   `logger.xxx("<事件名>")` —— 经变量传进 helper 的名字扫不出来，第一版实现
   `collector.noise_quarantined` 直接红。修法：helper 只做动作返回结果，
   日志留在调用点写字面量。
2. **`fetcher.fetch()` 会 `response.json()` 且缓存一切响应**。Discord webhook
   成功返回 204 空体，直接炸。新增 `fetcher.post()`：同套白名单/熔断/信号量，
   不缓存（POST 无缓存语义）、不解析响应体；4xx 除 429 立即失败不重试。
3. **pipeline 响应是逐键精确断言的主契约**（test_pipeline_run）。钩子往 result
   加任何键都会红。推送的可见性走 notify_log + /api/v1/notify/*，不走响应。
4. **「未落库不得有任何后台写」是被钉住的不变量**。save_to_db=False（试算）时
   连 notify 评估都不该跑 —— 而且本来就没产生新事实。钩子现在 `if save_to_db:`。
5. **全仓约定：schema 不用 SQL 级外键**（opportunity 测试扫 `_postgres_ddl()` 断言
   无 `references`）。participation_tasks 一开始带了 REFERENCES，已移除；级联
   删除由路由显式先删 task 再删 plan。
6. **写端点必须显式登记归属**：新匿名可写端点要进 `test_admin_only_rules.py` 的
   `ANON_WRITABLE`（逐条带理由），同时改 API_SPEC §2.1 的 write-auth-split 计数
   （实测驱动：admin 8 / public 2 / anon 16 / 共 26）。只改数字不够，逐项清单
   也有门禁。
7. **`.env.example` parity 的两个反向坑**：① 带 env-external 标记的键**不许**
   同时是 Settings 字段（TELEGRAM_BOT_TOKEN 双用途化后摘了标记）；② 标记解析
   按"键上方注释块含标记字样"判定 —— **注释里解释性地写"env-external"四个字
   都会被当成标记**，措辞要避开。
8. **alembic 迁移多语句必须拆分执行**（sqlite3 驱动一次一条）；0004 模板是单条
   DDL 没踩到，0005 起含 CREATE INDEX 就要 `_exec_script` 按分号拆。可回滚性
   测试改为 `_REVISION_TABLES` 登记 + `_tables_removed_after(revision)` 推算，
   **新迁移只需登记一行**。
9. **`/scheduler/jobs` 的 expected 清单与开关表要同步新 job**（`_JOB_OWNER` +
   `_expected_jobs` + switches 三处），否则 missing_jobs 天天亮红灯；job id
   由 `TestJobIdsMatchTheScheduler` 从 scheduler.py 源码抽取核对。
10. **`/api/v1/` 文档标题里不能带查询串**（`?status=...` 会被路由对账当路径），
    参数说明放正文。
11. **README 漂移一处待修**：WATCH 档写 40-64，真值是 ≥50（`scorer.py:50` 与
    GLOSSARY 一致）。

---

## 四、验证记录（实际跑过的命令与结果）

| 检查 | 结果 |
|---|---|
| 全量后端套件（最终，M1 完成后） | **3129 passed, 9 skipped, 0 failed, 88.93% cov**（47min） |
| 全量后端套件（P1 修复后） | 3087 passed, 88.87% |
| mypy strict（131 文件） | Success: no issues found |
| ruff check / format --check（264 文件） | All checks passed / already formatted |
| 前端 typecheck / lint / test / build | 全绿 |
| 门禁抽测（env parity / api spec / admin rules / observability / security / domain / scheduler jobs / alembic） | 全绿（分批跑，每批 ≤349 tests） |

三轮全量的教训：第一轮 9 failed（上面 11 条坑里的 2/3/4/6 + ops 文档），
修复后第二轮 2 failed（坑 5 + 10），第三轮 0。**全量套件在本机要 45-47 分钟，
后台跑、日志写文件（别 `| tail`，会截掉 FAILED 清单）**。

---

## 五、下一步 & 遗留

1. **PR 栈式合并**：fix/p1-audit-hardening → docs/action-loop-design →
   feat/action-loop-m1，三个都未 push。
2. **M2 = F3 收益台账与历史回测**（ACTION_LOOP_DESIGN §4）：roi_entries/
   roi_outcomes 两表、校准样本 `source=live|backtest` 分桶、回测数据集
   （~50 个 T0 前公开信息）+ `scripts/run_backtest.py`。
3. **M3 = F4 领取监控**（§5）：watched_wallets + Alchemy webhook 地址匹配。
4. **owner 手工项**：① `.env` 里 `ALCHEMY_API_KEY` 改名
   `ALCHEMY_WEBHOOK_SIGNING_KEY`（值不变）；② 启用推送需配
   `NOTIFY_ENABLED=true` + `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID`（注意双用途：
   alertmanager 也读它）或 `DISCORD_NOTIFY_WEBHOOK_URL`；③ `alembic upgrade head`。
5. **公网部署前必须处理**（审核遗留）：P1-5 前端代理注入管理员密钥、
   P1-4 同步 IO 在事件循环、反代限流 `TRUSTED_PROXY_COUNT`、compose 默认密码。
6. 小债：README 的 WATCH 阈值（40 → 50）；`_score()` 四份复制（owner 拍板延后）。
