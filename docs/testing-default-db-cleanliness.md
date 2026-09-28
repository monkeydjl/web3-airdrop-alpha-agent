# 为什么「默认库零容忍断言」在共享介质上不成立

> 2026-09-29。配套 `CONVENTIONS.md` §13.4 与 `backend/tests/conftest.py` 的
> `_default_db_cleanliness_snapshot`。本文记录一次真实的两次重设计：
> 同一个目标（守住测试对默认库 `DB_PATH` 的隐式污染），三版实现，前两版
> 在全量套件上被实证证伪。数据都在，防止后来者再试一遍。

## 背景

测试体系的既有口径（CONVENTIONS §13.4，2026-09-28/29 建立）：

- **规则一**（静态守卫）：直连 `DB_PATH` 的测试文件必须有自救建库路径；
- **规则二**（静态守卫）：默认库表读必须有同文件自播种或自管库重定向；
- **酸测**（动态）：34 个灰区文件逐文件删库串行单跑全绿。

在这套口径下，「写默认库」本身是**合法行为**——合规模式恰恰是
「往默认库播种 → 读回断言 → 由下一轮会话重建清理」。守卫要拦的是
**隐式依赖**（不播种就读、依赖上一轮残留、依赖其他文件留下的行）。

本文讨论的问题是：能否再加一道**运行时断言**——「测试对默认库零写入，
发现行即红」？直觉上它比静态守卫更强：静态只拦有信号的文件，运行时
断言能把一切绕过隔离口径的写入一网打尽。

## 结论先行

**不能。** 在本仓的测试体系（规则一/二合规模式 + xdist 8 worker 共享
一个默认库文件）下，任何粒度的「零容忍断言」都与既定合规模式冲突：

| 版本 | 断言粒度 | 全量实测 | 证伪原因 |
|---|---|---|---|
| v1 | 会话级：teardown 时默认库必须零业务行 | 1 failed + 8 errors | xdist worker 跑互不相交的测试子集，**会话级归因不成立**：库里的行来自本 worker 没跑过的其他用例的合法播种 |
| v2 | 用例级：每个用例 teardown 时「本用例留下的行」即红 | **2693 errors**（3853 passed） | 合规的自播种模式**本来就会留下行**——单跑全绿、全量被断言抓住，说明冲突是结构性的，不是个别用例的错 |
| v3（最终） | 无断言：会话结束快照各表行数到 `data/test.db.cleanliness.json`，与上一轮 diff（非阻断） | 3854 passed ×2，第二轮 diff 零差异 | ——漂移追踪替代二值断言 |

## v1 实证：会话级归因不成立

v1 设计：`pytest_configure` 统一删库重建（串行 + worker），session-scope
autouse fixture 在 teardown 时检查默认库，任何业务表有行即红。

实测（xdist 8 worker 全量）：1 failed + 8 errors。典型误报：

```
ERROR at teardown of TestNoTokenYetMergeSemantics.test_... [gw6]
会话级默认库洁净度断言失败：DB_PATH 库在会话结束后仍有业务行
（llm_spend_daily=1, logs=3, projects=2）。

ERROR at teardown of TestTableWhitelist.test_unknown_table_is_rejected [gw0]
（project_history=242, projects=79）
```

gw0 的 worker 根本没跑会写 `project_history` 的用例——这些行来自
**其他 worker 的用例**经规则一/二合规的 own-library 路径写的
（`settings.db_path` 未被重定向的那部分用例写的就是共享的
`data/test.db`）。xdist 把 3854 个用例随机分给 8 个 worker，任何
worker 的 teardown 都会看到全体用例的播种总和，逐表计数全部失衡。

**归因不可行**：teardown 时无法回答「这行是谁写的」。SQLite 没有
per-connection 的行归属；加自增标记列等于给 37 张表动 schema，为
一个断言改生产 DDL 是本末倒置。

## v2 实证：用例级断言与合规模式结构性冲突

v1 失败后自然会想：把粒度降到用例——「本用例开始前库是干净的
（或不管），结束后留下的行即红」。function-scope autouse teardown，
报告直接指名污染用例，看似完美。

实测（xdist 8 worker 全量）：**2693 errors / 3853 passed**——70% 的
用例被「抓到」。被指认的表分布（按出现次数，一行含多表时各表累计）：

| 表 | 次数 | 说明 |
|---|---|---|
| `project_history` | 102,449 | pipeline 用例每次运行写数条 |
| `projects` | 37,258 | 同上 |
| `logs` | 9,256 | 管线日志表 |
| `opportunity_assessments` | 6,504 | |
| `notify_log` | 3,264 | |
| `collection_logs` | 1,098 | |
| 其余 6 表 | <400 | |

被指认的用例横跨 2691 个 nodeid（几乎每个文件都有），且这些用例
**单跑全部绿**。三个代表性复核：

- `TestPipelineExecution.test_single_project_pipeline`
  （`tests/agents/test_orchestrator_simple.py`，21 用例单跑全绿）：
  `SimpleOrchestrator.run_pipeline(save_to_db=True)` 走
  `ProjectRepository` → `get_connection()`（默认库）写 `projects` +
  `project_history`——这正是规则二认可的「自播种后读回」路径，
  文件头的 `_ensure_db_schema` fixture 就是为此而加（cf7a392）。
- `tests/test_db_init.py` 的 `test_migration_failure_rolls_back_...`
  patch `get_connection` 注入替身连接，测试的就是 db.py 本体。
- `tests/test_gdpr.py` 走 TestClient 全栈写默认库再断言读回。

这些不是漏网之鱼，而是**体系设计内的公民**。「写默认库即污染」的
定义与 §13.4 自己批准的模式直接矛盾：规则二说「同文件 INSERT 自建
数据再读回（全新空库上也要成立）」是合法修复方式之一——意味着
写默认库后**留下行**是预期行为，清理责任在会话重建而非用例。

**教训：在一个「共享介质 + 自播种合规」的体系里，用例级零容忍断言
的逻辑等价于「禁止合规模式」，而不是「抓住不合规」。**

## v3（最终）：从二值断言降为可审阅的漂移追踪

目标不变（发现默认库的异常足迹），机制改为：

1. `pytest_configure` 统一删库重建（v1 引入，保留）——会话从已知
   空库开始，快照有确定语义；
2. session-scope teardown 把各业务表行数快照到
   `data/test.db.cleanliness.json`（`alembic_version` 白名单）；
3. 与上一轮快照 diff：新增非零表 / 行数暴增 / 清空 → 打印醒目 diff
   （**非阻断**）；确认无害后快照自然覆盖更新。

实测：两轮全量 3854 passed / 0 failed，第二轮 diff **零差异**——
快照是确定性的，任何偏离即信号。当前基线足迹：32/37 表为 0，
非零表（`collection_logs=4`、`data_sources=1`、`logs`、`notify_log`、
`llm_spend_daily` 等）即现有合规播种的真实总量，每一项都对应已审计
的灰区/自播种文件。

为什么 diff 能抓住零容忍断言想抓的东西：隐式污染的特点是**不可预期**
——某个用例绕过隔离口径写了不该写的表，快照会出现上一轮没有的表或
行数异常；合规播种是确定性的，轮与轮之间重放一致。漂移检测在
「确定性重放」的体系里等效于断言，而不需要回答「这行是谁写的」。

## 复盘：怎么避免再踩

1. **先问「合规的行从哪来」再写断言。** 本次 v1/v2 的失败根源是
   把「默认库有行」当成了污染的充分条件，而体系里它不是（规则二
   明文批准自播种留行）。
2. **xdist 下任何「会话级」观察都不要做跨 worker 归因。** worker
   子集不相交 + 共享介质，归因在机制上不可行。
3. **误报规模是最好的方向校正器。** v2 的 2693/3854（70%）一出来
   就该意识到不是「个别用例要修」而是「口径错了」——个别错误是
   个位数，结构性冲突是千位数。
4. **确定性重放体系里，diff 与断言等价且无归因负担。** 快照 +
   人工核查进基线，是共享介质上能诚实做出的最强承诺。

## 附：数据来源

- v1 全量日志：xdist 8 worker，1 failed + 8 errors（2026-09-29，
  `/tmp/full_run_detail.txt`，已清理；关键样本摘录于本文）
- v2 全量日志：xdist 8 worker，2693 errors / 3853 passed；
  表分布统计脚本按 `ERROR at teardown of <nodeid>` + 洁净度消息
  解析（本文表格即其输出）
- v3 双轮全量：3854 passed ×2，第二轮 diff 零差异
- 相关提交：`6ce2038`（conftest 快照 + 串行统一重建）、
  `9d18692`（整体回归）、CONVENTIONS §13.4
