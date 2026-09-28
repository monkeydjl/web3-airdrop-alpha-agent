# HANDOFF — 2026-09-25（17.1.26 收尾 2026-09-26）

> 接续 2026-08-22 版（历史脉络见文末引用）。本版记录 9 月下旬四波工作：
> **① CI 口径差排查与修复**、**② 测试提速 + xdist 并行**、
> **③ 存量文档漂移（parity 守卫）修绿**（✅ 已完成，14 失败清零）、
> **④ 测试数据库守卫体系**（静态守卫双规则 + 空库酸测 + 豁免纪律）。

## 项目当前状态

多智能体 Web3 空投评分系统（后端 FastAPI + 前端 Next.js 16）。
9 月初起 CI 因 lint 红而 56 连败，mypy job（`needs: lint`）再未执行，
期间合入的代码让 mypy 欠账积累、测试契约陆续过期——「CI 全绿」是过期印象。

```
mypy app                 → 0 错误（225 文件，从 66 个 strict 违规清零）
ruff check / format      → 全绿（489 文件对齐）
pytest 全量 -n 8         → 3:20（原串行 ~40 分钟），✅ 3802 passed / 0 failed（14 个存量失败已清零）
test_interactions        → 226 用例并行 37s（原 19 分钟）
mypy app（CI 同口径）    → CI 只查 app/，scripts/ 的 4 个存量错不在 CI 口径内
```

---

## ① CI 口径差：根因与修复（已完成，2026-09-23）

**根因**：CI 自 2026-09-04 起 56 连败——上游改动先红了 lint，mypy job 因
`needs: lint` 从未再执行，期间合入的代码让 mypy 欠账积累到 66 个、
测试契约也陆续过期。

**mypy strict 66 → 0**，16 个文件的违规归为四类同源模式：

| 模式 | 修法 |
|---|---|
| `meta.get("signals") if isinstance(meta.get("signals"), dict)` 双 get 收窄失效（8 处，13 错） | 收敛为 `project_signals.signals_of()` 共享 helper |
| 异构字面量常量缺显式注解（bridge/sell_off/calendar） | 补 `dict[str, dict[str, Any]]` 等注解 |
| Literal 键 dict 被 `str \| None` 查询（anti_pua/viability_gate） | 显示用查找表放宽为 `dict[str, str]` |
| 单发：auth 冗余 cast、faucet 缓存窄化、leader unreachable、sybil 复名、gas `Body(...)` | 逐个修复，B008 按 per-file-ignore 惯例 |

**顺带挖出 2 个真实产品 bug**（被红 lint 遮蔽三周）：
- `bot_notifier` 的 `/faucets` 调用不存在的 `list_faucets()`（真名 `list_faucets_with_status`）
- 匿名属主死锁：MVP 模式匿名 POST 时 body 的 `user_id` 落库为属主，
  同一匿名身份 PATCH 自己刚建的记录被属主校验 404。修复：匿名不采信 body.user_id

**过期测试契约修正**（全部经 stash 基线验证在 HEAD 即失败）：
`main_lifespan`（collector 14→17、`items_new>0` 才触发管线）、
`leader_election`（断言与 734f0a7 实现自相矛盾）、
`interactions`（3 处直调缺 `req` 参数）、
`pipeline_run`（P1-4 把 gauges 移入 to_thread 后两用例未同步）。

**唯一遗留口径差**：本地 venv 是 Python 3.11、CI 是 3.12——修复后两边 mypy 均为 0，无害。
HANDOFF 旧版遗留的「决定 Python 版本口径」待办仍值得单独收口。

---

## ② 测试提速 + pytest-xdist（已完成，2026-09-25）

**结果：全量 19 分钟（单 test_interactions）→ 全套件 3 分 29 秒（-n 8，3796+ 用例）**。

### 慢因剖析与修复（pytest --durations 定位，按 ROI 排序）

| # | 慢因 | 实测 | 修复 |
|---|---|---|---|
| 1 | **tmp 落在仓库目录**——实时杀毒/索引扫描放大 SQLite 每条 DDL 提交（同 30KB DDL：仓库目录 ~4s vs 系统 TEMP ~0.3s） | interactions 19min | conftest tmp 基准改系统 TEMP 优先（保留仓库回退）→ 2min |
| 2 | **xdist worker 共库**（插桩实证）：controller 先加载 conftest 时无 worker 标识，无后缀 `DB_PATH` 被 setdefault 写进环境并被 worker 继承——8 个 worker 全写同一个 86MB 的 `data/test.db`，「文件级隔离」从未生效 | 固定 ID 用例并行随机红 | worker 内**强制覆盖** `DB_PATH` + 会话开始删库重建并 `init_db()`（串行保持原语义） |
| 3 | **Twitter 限流器真实时钟白等**：`twitter_kol/keyword` 0.2rps/burst1，mock 的 HTTP 每请求真等 ~5s | 2 用例各 31s | 测试 fixture `monkeypatch.setitem` 降速令牌桶 → 7s |
| 4 | **admin 用例误跑真实采集**：鉴权放行后 defillama 真出网烧 DNS/超时 | 单用例 42s | 注册表单例的 `collect()` 换空结果桩（鉴权契约原样保留）→ 5s |
| 5 | **calibration verifier 重采样 1000 次 × 双跑管线** | 9 用例 ×26s | monkeypatch 降到 20（仓库既有惯例）；脚本契约改为调用时读模块运行时属性 → 10s |

### xdist 结论

- `pytest-xdist==3.8.0` 已锁进 `requirements-dev.txt`；CI 的 `pytest tests -q` 无需改动
  （CI 不装 xdist 则行为不变）。
- **默认 load 分发 -n 8 是甜点**（本机 24 核，-n 12 反而慢：CPU 竞争）。
- **`--dist loadfile` 是负优化**（5:50 且 21 失败）：它暴露 auth 文件
  「clean fixture 跑在建表之前」的初始化顺序依赖；worker 会话 init_db 已一并消除。
- 保留的实网冒烟测试（gas、sybil 等）是**故意的**诚实口径探测，不要「顺手 mock 掉」。

### 附带收获

- 修掉 `test_unified_scheduler` 两处对 `get_jobs()` 的**列表**相等断言
  （APScheduler 按触发时间排序，顺序不可依赖）——集合比较后 5 连跑稳定。

### 验证口径

- 连续两轮全量 3:29 / 3:42，失败集合逐项一致（14 个均为存量文档漂移）→ 跨轮次确定性达成
- 串行/并行口径一致；`ruff check` / `format --check` 全绿；`mypy app` 0 错误
- 结论已记入 `docs/EXPANSION_AUDIT_REPORT.md` 附 2

---

## ③ 存量漂移修绿（✅ 已完成，2026-09-25/26）

目标：把全量测试剩的 14 个失败清零——全部是 **parity 守卫**类存量漂移
（自 9/4 CI 变红以来扩展批次加了路由/采集器/作业，但守卫锚定的文档没同步）。

### 已修绿（8 项全部）

| # | 测试 | 修复 |
|---|---|---|
| 1 | `test_scheduler_jobs` | `app/routers/v1/scheduler.py` 的 `_JOB_OWNER` 补 `daily_alpha_digest` 映射 |
| 2 | `test_frontend_enum_parity` | `frontend-next/lib/format.ts` sourceZh 补 `github_curated` 中文名（+同步 format.test.ts） |
| 3 | `test_data_source_strategy_parity` | `docs/DATA_SOURCE_STRATEGY.md` §3 采集器登记表对齐 registry（17 源） |
| 4 | `test_api_spec_parity` | `docs/API_SPEC.md` §3 总览表补齐 56 个缺失路由 + 修 13 处 HTTP 方法（faucets/probe GET、bot/command POST、roi/simulate/{id} GET 等）；`gas/{chain}` 动态路径单独成行 |
| 5 | `test_admin_only_rules` | `tests/test_admin_only_rules.py` `ANON_WRITABLE` 补 30 个扩展批次写端点（各附归属理由）；`docs/API_SPEC.md` §2.1 写端点总数 54→84、匿名可调 36→66 |
| 6 | `test_operations_doc_parity` | `docs/OPERATIONS.md` §4.3 门控表补 `github_curated` 行、17 源计数、§7.1 cron 表补行、`github` 需 Key 改 ❌（b8ccc5a 起无 token 走未认证公开搜索）；`tests/test_operations_doc_parity.py` cron 映射补 github_curated + parser 自检断言同步 |
| 7 | `test_observability_doc_parity` | `docs/OBSERVABILITY.md` §2.2 事件名 405→425、命名空间 77→86（2026-09-25 标注） |

### `test_verify_opportunity_economic` 17.1.26 案例（✅ 已完成，2026-09-26）

`tests/scripts/test_verify_opportunity_economic.py` 三连 + 矩阵 `17.1.26` 全部修绿，
修复共三层（前两层在 verifier 脚本，第三层是生产代码）：

1. **`asyncio.to_thread` 无事件循环**：734f0a7（9/20）把 `trigger_collection` 持久化
   移入 `await asyncio.to_thread(...)`，而 verifier 的 `_run_coro_sync` 是无事件循环的
   裸协程驱动器（socket-free 契约），直接 `RuntimeError: no running event loop`。
   修复：`scripts/verify_opportunity_economic.py` 新增 `_sync_direct()` helper
   （to_thread 的同步替身），手动段 `patch.object(coll_mod.asyncio, "to_thread", ...)`。
2. **直调时 FastAPI 默认值是 FieldInfo 标记**：`trigger_collection(source_id=...)`
   直调时 `payload=Body(None)`、`auto_run=Query(None)` 是非 None 且真值的标记对象，
   `auto_run is not None` 分支先命中并触发真实分析管线（orchestrator 的
   gather/semaphore 同样 loop-free 不可驱动，`RuntimeError: await wasn't used with future`）。
   修复：调用处显式传 `payload=None, auto_run=False`（附注释说明机制）。
3. **借用连接被 LeaderElector 关闭（生产代码 bug）**：`app/main.py` L221 给 elector 的
   `conn_factory` 在 db_override 注入时返回**借用的共享连接**，而 `leader_election.py`
   三处 `with self.conn_factory() as conn:` 会经 `DbConnection.__exit__` 把它关掉
   （lifespan 退出后 `_prove_construction_failure_isolation` 的 `close_s == 1`）。
   修复（`app/services/leader_election.py`）：
   - 新增 `_conn_scope(factory, *, owns)`：只在 elector 拥有连接时关闭；
   - 新增 ctor 参数 `owns_connections`（默认 True，生产 `get_connection` 路径语义不变），
     `app/main.py` 传 `owns_connections=db_override is None`；
   - `stop()` 在 standalone（HA 禁用）时跳过 `step_down()` 与 `on_demoted()`：
     standalone 从未持有真实租约，不会真的被「降级」；旧代码会在关停时做一次
     多余的 DB 写并关闭共享连接、把调度器 `shutdown(wait=False)` 提前关掉，
     破坏「lifespan 统一 wait=True 恰关一次」契约（`test_main_lifespan.py` 两用例
     `close_calls==1` / `shutdown_calls==[True]` 即锚定此契约）。

修复期间曾使 `test_main_lifespan.py` 2 用例变红，定位后确认是暴露既有的
standalone 关停契约违背（非新回归），第 3 层修复使其恢复绿。

---

## ④ 测试数据库守卫体系（✅ 已完成，2026-09-28/29）

测试文件直连 `DB_PATH` 却隐式依赖两类侥幸路径——历史残留 `data/test.db`
带着旧 schema、conftest 会话级兕底 `init_db`——全新 checkout 上「单跑一个
文件」必红；残留行依赖则是 xdist 随机红的同源问题。三道防线，全部落地：

| 防线 | 载体 | 触发时机 | 已知边界 |
|---|---|---|---|
| 静态守卫（新违规进不来） | `scripts/check_test_db_bootstrap.py`：规则一 schema 来源（直连 DB_PATH 须有自救建库路径）+ 规则二数据来源（SELECT 表读须自播种/重定向） | 每次 push/PR：ci.yml lint job + release.yml test-gate，与连接卫生守卫同位；违规 exit 1 | 纯静态 AST：经 service 层间接用默认库的文件看不见 |
| 动态空库酸测（盲区复验） | `scripts/verify_test_db_isolation.py`：动态枚举灰区（复用守卫 AST 函数，零硬编码清单）+ 逐文件删库串行单跑 | 人工：改守卫规则 / 登记豁免后必跑；CI 为 workflow_dispatch 手动按钮（独立 workflow，不在 PR 必过链） | `--changed` 定向选择器不完备（同上边界）→ app/ DB 信号提示不阻断；全量才是完备口径 |
| 豁免登记纪律 | 守卫脚本内 `WHITELIST` / `READS_DEFAULT_DB_WHITELIST`（豁免须附理由注释） | 新增豁免前：`--only` 定向空库验证理由成立再登记 | 红 = 登记理由不成立，修测试不是改酸测 |

规范文本在 `CONVENTIONS.md` §13.4。首跑基线：34 灰区 + 5 探针抽样共
39 文件全新空库全绿（2026-09-28）。反向 `--changed`（按 app 源文件反查
测试）已评估不做：真实 DB 变更提交的反向选集 ≈ 全量，省不了时间反而
给人虚假安全感；其剩余风险由 app/ DB 信号提示显式暴露（不阻断）。

命令速查（backend/ 下）：

```
venv/Scripts/python.exe scripts/check_test_db_bootstrap.py     # 静态守卫（CI 同命令）
venv/Scripts/python.exe scripts/verify_test_db_isolation.py    # 全量酸测 ~4-5 分钟
venv/Scripts/python.exe scripts/verify_test_db_isolation.py --changed           # 定向：本次改动三路并集
venv/Scripts/python.exe scripts/verify_test_db_isolation.py --only tests/xxx.py # 单文件（带桶归属标注）
```

- `--changed` 口径：vs `@{upstream}` 已提交未推送 + 工作区/暂存 + 未跟踪
  新文件；无 upstream 须显式 `--base`
- CI 手动 workflow：`.github/workflows/test-db-isolation.yml`，inputs
  only / changed / base / probe-count / probe-seed；checkout `fetch-depth: 0`
  （`--changed` 要 diff upstream 基线）；不在 ci.yml → 分支保护必过检查名单零改动

守卫相关陷阱（重申 + 新增）：

- 清库删**仓库根** `data/test.db{,-wal,-shm}`，不是 `backend/data/`（曾误删致假绿）
- 酸测**不要带 `--timeout`**：仓库未装 pytest-timeout，传了 pytest exit=4
- 守卫体系全部工作尚在本地未推送：推送前 CI 上 `--changed` 的默认基线
  （`origin/master`）会把全部改动当「本次改动」，workflow 按钮也推送后才出现

---

## 验证快照（本轮收尾时点）

- `docs/API_SPEC.md` §3/§2.1、`docs/OPERATIONS.md` §4.3/§7.1、`docs/OBSERVABILITY.md` §2.2、
  `docs/DATA_SOURCE_STRATEGY.md` §3、`frontend-next/lib/format.ts`、
  `tests/test_admin_only_rules.py`、`tests/test_operations_doc_parity.py`：全部对应 parity 测试已绿
- `mypy app` 0 错误（225 文件）；`ruff check`/`format --check` 对本轮改动文件全绿
- **全量 `-n 8`：3802 passed / 9 skipped / 0 failed（3:20），14 个存量失败清零**
- verifier CLI 出口：`passed=26 failed=0 total=26 / RESULT: PASS`；
  `tests/test_leader_election.py` + HA 套件（ha_endpoints / main_lifespan / v3_core_e2e）34 passed
- 本轮新增改动：`app/services/leader_election.py`（_conn_scope → 改用统一
  `app.db.connection_scope` + owns_connections + standalone 关停语义）、
  `app/main.py`（elector 传 `owns_connections=db_override is None`）、
  `scripts/verify_opportunity_economic.py`（_sync_direct + to_thread patch + 显式参数 + 错别字）
- 连接所有权契约已升级为全仓统一约定：权威实现 `app/db.py::connection_scope`
  （own/borrow 三种用法 + owns 显式优先），文档落在 `CONVENTIONS.md` §13.3，
  契约测试 `tests/test_connection_scope.py`（8 用例）。
- 连接卫生守卫已接入 CI：`scripts/check_connection_hygiene.py`
  （纯标准库 AST，检测裸 `with get_connection() as` 与手写
  `conn = get_connection() + finally close` 两种模式；白名单豁免
  `db.py` 实现本体与 `main.py` 所有权持有方），ci.yml lint job 与
  release.yml test-gate（tag push 不触发 ci.yml，发布门是该 commit 的
  唯一静态门，不应比日常 CI 更松）均在 ruff 之后跑
  `python scripts/check_connection_hygiene.py`
  （`CONVENTIONS.md` §13.3 的机器可执行版）
- 短作用域建连已全部迁移：全仓 57 处裸 `with get_connection() as`（19 文件）
  机械替换为 `with connection_scope() as`，多余 `get_connection` import 由 ruff
  自动清理；monkeypatch 消费点测试（`test_gdpr`、`test_action_and_review`、
  `test_interactions`×7、`test_collections`×4、verifier 17.1.26 手动段）
  全部同步改为 patch `connection_scope`。
- 手写 try/finally `get_connection()` 消费者亦已清零：quarantine、gas_alert_engine、
  team_studio_manager、faucet_registry、signal_correlation、airdrop_pnl、interactions（5 处，
  rollback→close 顺序由 scope finally 等价保持）、notifications、dashboard、insights、
  scheduler×2、agents(base/heat_signals)、llm/budget（_open_repo 拆解到消费点）、
  ops_tasks、alpha_digest/airdrop_calendar/roi_simulator（三个**存量泄漏**：原代码
  连接从不关闭，现由 scope 保证 close 恰一次）、smart_money_radar、daily_briefing、
  bot_notifier、project_comparison、collections.trigger。app/ 内残留 `get_connection()`
  仅剩 db.py 内部定义 + main.py 所有权持有方（刻意保留）；`_should_close`/`_as_db_connection`
  注入型惯例不变

## 本环境的操作陷阱（增量，历史陷阱见文末旧版）

- **pytest 全量单命令会超 600s 上限**：分块跑或用 `-n 8`；
  `--durations` 定位长尾时注意 collecting 阶段也计费
- **CI 的 mypy 口径只查 `app`**：`scripts/` 的存量错误不在 CI 内，别为它扩大范围
- **conftest 的 `DB_PATH` 在 worker 内是强制赋值**（覆盖继承值）：
  串行模式显式设置 DB_PATH 的既有语义保留——改动前先读 `tests/conftest.py` 注释
- **xdist 排障**：先确认 `PYTEST_XDIST_WORKER` 生效时序（xdist 在 worker 进程先设
  该 env 再加载 conftest），插桩打在 conftest 顶部 import 区最直接
- **CI 逐 job 验证（2026-09-26，当前代码）**：lint（ruff check/format + 连接卫生守卫）✅、
  test（3810 passed + cov 86.62% ≥ 80，三类 warning-as-error 无触发）✅、
  type-check（mypy 0 错）✅、frontend（typecheck + 单测 68 + build，node 24 同版本）✅、
  coverage-gate / docker-build 逻辑上随 test 通过。
  **唯一剩余口径差：frontend 的 `npm audit --audit-level=high` 已修复（2026-09-26）** ——
  `npm audit fix` 在 `^` 范围内升级：next 16.3.0→16.3.6（critical RCE 修复）、
  sharp 0.35.3→0.35.4、js-yaml 4.3.1→4.3.2；package.json 未变（^ 范围内），
  仅 lockfile 更新。验证：typecheck 0 错、单测 68 pass、build 成功、
  `npm audit --audit-level=high` 归零（found 0 vulnerabilities）。至此 **CI 全部 job 在当前代码上均会转绿**。
- **release.yml / security.yml 兼容性审查（2026-09-26，同样本地复现验证）**：
  - release test-gate（ruff/mypy/无 cov 全量 pytest，同 CI 命令）全绿；release（Docker+SBOM）
    与 deploy-demo（`if: false` 未启用）无代码耦合
  - security.yml 三个可本地复现的检查全绿：pip-audit 对 requirements.txt / -dev.txt /
    -otel.txt 均「No known vulnerabilities found」；detect-secrets
    （同一 baseline + exclude-files 参数）exit 0；package-lock 改动会触发
    security.yml push，npm audit 已归零，Trivy 扫镜像与 dependency-review
    （PR-only）无本地执行面但依赖面未变

---

_交接日期：2026-09-25（17.1.26 收尾 2026-09-26）· 扩展功能审计见 `docs/EXPANSION_AUDIT_REPORT.md`（含附录 1/2）·
旧版交接（08-22）全文仍在本文件顶部引用段之后的历史里，
此处仅保留增量；操作陷阱继承段见旧版「本环境的操作陷阱」。_
