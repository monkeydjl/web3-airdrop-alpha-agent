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

## 后记（2026-09-29 下午）：diff 对象自己也得有「单一归属」——v3 快照在 xdist 下的两个实测缺陷

复盘④说「快照 + 人工核查进基线是共享介质上能诚实做出的最强承诺」。
当天下午的实证补充了一条必要前提：**diff 对象自己必须单一介质、单一
归属，否则「diff 替代断言」只是把 v1 的误报从「用例红」降级成「基线
静默漂移」——后者更危险。** v3 快照机制在 xdist 8 worker 全量
（`3854 passed / 9 skipped, 88.32%, 4:03`，`/tmp/full_run_f1.txt`）上
实测出两个缺陷：

**缺陷 A：8 个 worker 共享写同一份基线（last-writer-wins）。**
`_default_db_cleanliness_snapshot` 的快照路径是
`db_file.parent / "test.db.cleanliness.json"` —— **文件名硬编码**，与
`db_file` 的名字无关。worker 各有独立库（`test_gw0.db`…`test_gw7.db`，
DB_PATH 推导见 conftest 头部），但 teardown 时 8 个进程全写
`data/test.db.cleanliness.json` 这一个文件。全量跑完后的 JSON 与
`test_gw3.db` 的足迹**逐表逐值一致**（`projects=7, project_history=5,
gas_alert_rules=4, harvest_records=5, team_studio_*=1+1`，44 张表）——
最后结束的 worker 把自己那份「子集足迹」盖成了「全量基线」。串行全量
与 xdist 全量的合规足迹本来就不同（串行：`projects=9,
project_history=30`；xdist：`logs=10, notify_log=5, collection_logs=4`
等分散在多个 worker 库），模式混用时基线被两种介质轮流覆盖，diff 的
参照系每轮都在漂。

**缺陷 B：xdist 下 diff 警告通道整体失聪。** 探针实验：预埋
`{"__sentinel__": 999}` 进基线 JSON 后——

- 串行单文件 `-s`：警告正常出现（`清空: {'__sentinel__': 999}`）；
- 同一文件 `-n 2 -s`：**零警告**，哨兵被静默覆盖。

机制：worker 进程的 teardown print 默认被 pytest-xdist 捕获（`-s`
不改变 worker 内的捕获行为），而 xdist 的实时日志由 controller 转发
worker 事件产生——teardown print 不在其中。也就是说：**哪怕某轮出现
真正的异常足迹，xdist 全量（本体系的主要验收形态）也不会把 diff 提示
送到任何人眼前**；「确认无害后覆盖更新」这个动作照常执行，异常就这样
无声地进入基线。v3 验证时「两轮 diff 零差异」的结论，其实是
「diff 提示通道 + last-writer-wins 叠加后什么也看不见」，而非干净重放
的证据本身。

**对照组证据链**：

- 跑前基线 = 串行足迹（`projects=9, project_history=30`，39 表）；
- 跑后基线 = gw3 足迹（44 表），两者完全不同，中间无任何警告；
- 8 个 worker 库的独立足迹各不相同且都合法（规则一/二自播种），
  例如 gw0 `projects=77/project_history=242`，gw6 仅 `projects=6`
  ——任何一个子集都不等于全量足迹，这是「worker 子集不相交」复盘②
  在快照介质上的再次显形；
- gw3 多出的 5 张表（`gas_alert_rules` / `harvest_records` /
  `team_studio_operators` + `team_studio_tasks` / `faucet_claims`）
  查明为 `ensure_*_table` 按需建表服务的合规自播种，非隔离泄漏。

**教训（复盘④的补充条款）：** diff 机制要成立，先问三个问题——
写基线的是谁（单一归属）、基线描述的是哪份介质（模式标注）、
提示往哪走（在主要验收形态下可达）。三个问题里任何一个不成立，
漂移追踪就退化成「漂移掩埋」。

**修复（2026-09-29 下午，最小方案已实施并验证）**：不引入多文件
分流，改为两条最小规则——

1. **仅非 worker 进程写快照**：fixture 开头对
   `PYTEST_XDIST_WORKER` 显式 `return`。controller 进程不跑用例、
   fixture 不激活，天然不写；worker 是独立介质且提示不可达，写基线
   的一切副作用（缺陷 A）就此归零。语义：**基线由串行验收轮
   （全量/酸测）维护，xdist 全量验收不碰基线**。
2. **快照内容带 `_mode` 标注**：读到异模式基线时，diff 提示里显式
   注记模式差异——单侧归属明确后，参照系漂移从「静默」变为「可见」。

哨兵探针验证（修改后）：① 串行单文件：警告正常 + 新格式写入；
② `-n 2` 预埋哨兵基线：跑后逐字节不变（缺陷 A 消除）；
③ 预埋 `_mode: "xdist"` 异模式基线跑串行：警告中出现「基线模式」
注记。终验：xdist 8 worker 全量 `3854 passed / 9 skipped`，跑前跑后
基线 hash 一致（`718bfe8a…`），`_mode` 保持 `serial`。
新格式（多 `_mode` 键）对旧基线的兼容是天然的：旧格式文件在下一轮
串行运行时被新格式覆盖，无需迁移脚本。

**串行双轮重放验证（同日，修复后的确定性验收）**：串行全量
`-s -q` 背靠背两轮，各 `3854 passed / 9 skipped`（18:16 / 18:11）。

- R1 出现 **1 条 diff 警告，且是真信号**：跑前基线是修复前遗留的
  部分运行足迹（`projects=9 / project_history=30`，酸测模式产物，
  见下方已知边界），串行全量的真实足迹是
  `projects=118 / project_history=307 / logs=31 / notify_log=18 /
  opportunity_assessments=17` + 5 张 ensure-table 服务表
  （`gas_alert_rules=4`、`harvest_records=5`、`team_studio_*=1+1`）。
  机制正确地把参照系漂移暴露出来并更新进基线——「diff + 人工核查
  进基线」的预期行为，而非回归。
- R2 **零 diff 警告**，跑后基线与 R1 跑后**逐字节一致**
  （hash `795d8e8e…`，39 张 schema 表 + 5 张服务表 + `_mode` 键，
  逐表零差异）——串行重放确定性成立，漂移追踪在修复后首次拿到
  「第二轮零差异」的诚实基线。
- **基线分流（同日下午补充，消除交替运行时的预期内大 diff）**：
  串行全量与串行酸测都是单进程、足迹却截然不同（全量
  `projects=118` vs 酸测最后文件的残留 `projects=9`），共用一份基线
  时每次交替都会出一条千行级「增长/清空」警告——预期差异不是污染
  信号，不该以大 diff 形式出现。故 `_mode` 细分为两桶：
  **`serial-full`**（直跑 pytest，默认）与 **`serial-acid`**（酸测脚本
  给子进程注入 `CLEANLINESS_MODE=acid`）。同模式比对走完整逐表 diff；
  异模式基线只出**单行模式注记**（数字不可比，逐表列举只会是噪声），
  基线随本轮覆盖更新。两个桶各自重放确定：serial-full 已由双轮全量
  验证（R2 零警告、hash `795d8e8e…` 一致）；serial-acid 由探针验证
  （同两个灰区文件连跑两轮，第二轮零警告、基线逐字节一致）。

  **分流实施后的终态验收顺带演示了酸测的价值**：全量酸测首轮
  （39 文件）立刻抓住分流重构引入的回归——同模式 diff 分支漏了
  `parts = []` 初始化，同模式足迹变化时 teardown 抛
  UnboundLocalError，5 个文件报「N passed, 1 error」。此前所有探针
  都没踩中它（探针走的是异模式分支或零差异路径），直到真实足迹
  变化才引。
  修复后重跑：**39/39 绿 ×2，跑后基线逐字节一致**
  （`_mode=serial-acid` 全零足迹，hash `221580a9…`）；同模式 diff
  路径另以哨兵探针直接验证（`清空: {'__sentinel__': 42}` 正常输出）。
  终态验收全景：xdist 8 worker 全量 ×2（3854 passed，基线 hash
  `cb502177…` 两轮逐字节不变）+ 全量酸测 ×2（39/39 绿，acid 桶
  重放确定）。

**探针固化为回归钉子（同日，`tests/test_cleanliness_snapshot.py`）**：
四条快照路径（串行警告通道 / xdist 零写入 / 异模式单行注记 /
同模式完整 diff）各一个用例，外加 `CLEANLINESS_MODE=acid` 注入契约。
固化过程本身又实测出**三个继承污染盲区**——子进程会继承外层全部
环境变量，而被测路径必须用 in-pytest 子进程重放「会话结束」时序：

1. `CLEANLINESS_MODE`：acid 外层（酸测单跑本文件）会把 serial-full
   路径用例静默变成 acid 会话，断言全部错位（实测 3 failed）；
2. `PYTEST_XDIST_WORKER`：不剥掉，串行子进程被 conftest 误判成
   worker，teardown 直接跳过快照——失效且无报错；
3. `DB_PATH`：内层 `pytest_configure` 会删库重建，不钉住删的就是
   外层正在用的库。解法：每用例私有 `tmp_path` 探针库，快照随
   `db_file.parent` 规则落私有目录，与真实基线彻底解耦——外层
   xdist 多 worker 并发跑本文件也不再共享任何介质（缺陷 A 的微型
   重演，在固化过程中被复现并消灭）。

用例在三种外层语境（直跑 / acid / xdist）下全部验证；嵌套 xdist
用例在外层 xdist 下显式 skip（内层 worker 会被 conftest 强制重定向
DB_PATH 到仓库 data/ 删库，外层全量下不安全）。教训与复盘②同源：
**探针自身的语境必须钉死，否则验证工具自己就成了新的共享介质。**

**xdist 提示可达性审计（同日，AST 全树扫描）**：确认缺陷 B 没有同类
残留——tests 全树 114 个 fixture 中 42 个带 yield，全部 function
scope 且 yield 后零 print；无 sessionfinish/unconfigure/terminal_summary
钩子、无模块级 print、无插件注册、无其他 conftest。全仓唯一的会话级
teardown print 就是洁净度快照（已修复）。设计指引：**今后需要 xdist
下可见的会话级提示，用 `warnings.warn`（进 warnings summary，
controller 会汇总 worker 记录）或 `pytest_terminal_summary` 钩子，
不要用 print**——print 在 worker 内必被捕获，这是机制不是例外。

**子进程环境变量继承审计（同日）**：tests 全树 7 个 subprocess 调用点
（5 文件）逐个核查——唯一 spawn pytest 的只有洁净度钉子文件自身
（已钉三个变量）；`test_alembic_migration._run` 已显式钉 DB_PATH 到
tmp 库（spawn 的是 alembic/init_db，非 pytest 会话，模式变量无消费方）；
test_ci_parity / gitignore / shell_scripts 的子进程（ruff、守卫脚本、
git、bash -n）均不读 DB_PATH/CLEANLINESS_MODE/PYTEST_XDIST_WORKER。
无残留盲区。

**scripts 侧继承面审计（同日，延续同一方法）**：全仓 5 个 spawn 点
（backend/scripts 2 文件 + 根 scripts 2 文件；check_ci_parity 唯一
spawn 点是其 ruff/守卫腿）。判定同构：ruff / git / bash -n / 守卫
AST 脚本不消费三个高危变量；消费 DB_PATH 的 bench/dual_run 脚本
spawn 的是应用内线程非子进程。**唯一真实盲区在酸测脚本自身**：
`_run_one` 只注入了 CLEANLINESS_MODE，未钉 DB_PATH 也未剥
PYTEST_XDIST_WORKER——若操作员 shell 导出 DB_PATH，酸测会话写的
库与本脚本 `_delete_default_db` 固定删的 `data/test.db` 分家，酸测
数据写进操作员指定的工作库。已修复：env 显式 pin DB_PATH 到
conftest 同款默认值（删/写永远同库）+ 剥 PYTEST_XDIST_WORKER
（堵死嵌套调用时 worker 身份覆盖 pin 的理论路径）；
`DB_PATH=…` 污染 shell 下单文件酸测 + 全量 39/39 复跑验证通过。
教训与 tests 侧同源：**写介质的脚本必须 pin 介质路径，读环境的
继承不能隐式信任操作员 shell。**

**`_run_one` 环境钉住的回归钉子（2026-09-30）**：钉子文件新增
`TestRunOneEnvPinning`，把上一段的修复钉死——进程内调真 `_run_one`
（monkeypatch `_default_db_files` → 探针目录三件套，删除目标与
DB_PATH pin 一起落到 `backend/data/_probe/`，脚本代码原样执行，外层
介质零触碰），污染 shell（DB_PATH / PYTEST_XDIST_WORKER /
CLEANLINESS_MODE 全部在场）下断言子进程三件事：DB_PATH == 删除目标
（顺带钉住 pin 来源 = `_default_db_files()[0]` 单一真相源——脚本侧
已从硬编码重构过来，任何一处再分叉探针必红）、CLEANLINESS_MODE 强制
acid、无 worker 身份。三外层语境（直跑 / 酸测 --only / xdist
8 worker）全绿；静态守卫兼容（探针在 data/ 下，tests/ 树外，守卫
枚举不可见）。

**探针选址教训（同日，xdist 下实测爆出）**：探针最初放在系统 TEMP
（仓库 tmp_path fixture 的常规落点），xdist 外层 8 worker 下三个用例
齐红——内层子进程 collection 阶段 `lstat` 了**别的用例的** tmp 目录
并撞上 FileNotFound。根因：pytest 9 在 win32 的收集路径匹配会对
不匹配的兄弟收集节点逐个 `samefile_nofollow`（lstat）兑底，探针在
`$TEMP` 根下时内层会话收集链涵盖 `$TEMP`，而外层 worker 正在并发
rmtree 彼此的 per-test 目录 → TOCTOU。单 worker 重跑永远绿（无并发
删除），又一次「并发语境才爆」。落点改为仓库内运行时忽略区
（`backend/data/_probe/`，收集链祖先的兄弟节点全程稳定）后消除。
教训：**嵌套 spawn 的探针文件选址要考虑内层会话的收集链祖先——任何
会被外层并发改动/删除的目录（系统 TEMP、仓库 tmp 落点）都不能放。**

**「pin 来源与删除目标分叉」全 scripts 审计（2026-09-30，同款问题
排查）**：`_run_one` 的分叉修复后，对根 scripts/ + backend/scripts/
共 45 个脚本做同款排查（unlink/rmtree/Remove-Item/硬编码 db 文件名/
data 目录构造五路扫描 + 逐个人工过）。判定标准：**删介质与写/指
介质在脚本内成对出现且来源不同源**才算分叉。结论——零残留：

- 有删行为的 3 处全部自洽：`_delete_default_db`（pin 已同源，见上）；
  auto_backup.ps1 的 Remove-Item 全部作用于自建备份工作目录（自建
  自删）；backup.sh 的 `rm -f` 只删容器内临时导出文件。
- 写库脚本（seed/purge/rescore/calibrate/e2e/quarantine/backfill 等）
  介质统一走 `settings.db_path`（尊重 DB_PATH env），单介质、无硬编
  码删除目标与之配对；bench 三兄弟（bench_db/bench_event_loop/
  dual_run_compare）pin 到自建 tmp 自洽；backfill_listed_subproducts
  是单介质写 + docstring 显式 CWD 陷阱警告；migrate_sqlite_to_pg
  两端介质都是显式 CLI 参数。
- 读介质脚本无分叉风险：backup.sh/health-check.sh 的库源 = `.env`
  DB_PATH（2026-08-24 已修过同款「查错文件」问题，有回退候选警告）；
  backtest 数据集是只读输入；守卫脚本的 test.db/DB_PATH 字样全是
  AST 模式签名非真实路径。verify_init_db_concurrency 是 PG-only
  无文件介质。grep 假阳性（unlinked 业务词、shutil.which）逐一排除。

## 附：数据来源

- v1 全量日志：xdist 8 worker，1 failed + 8 errors（2026-09-29，
  `/tmp/full_run_detail.txt`，已清理；关键样本摘录于本文）
- v2 全量日志：xdist 8 worker，2693 errors / 3853 passed；
  表分布统计脚本按 `ERROR at teardown of <nodeid>` + 洁净度消息
  解析（本文表格即其输出）
- v3 双轮全量：3854 passed ×2，第二轮 diff 零差异
- 后记实证（2026-09-29 下午）：xdist 8 worker 全量
  `3854 passed / 9 skipped, 88.32%, 4:03`（`/tmp/full_run_f1.txt`）+ 两轮
  哨兵探针（串行单文件 `-s` vs `-n 2 -s`，警告出现/失聪各一）；
  逐库取证脚本遍历 `data/test.db` + 8 个 `test_gw*.db` 的表集合与非零计数
- 后记修复验证：xdist 8 worker 全量 + 串行双轮重放
  （`/tmp/serial_replay_r1.txt`、`/tmp/serial_replay_r2.txt`，
  R1 警告 1 条真信号、R2 零警告，两轮跑后基线 hash 一致
  `795d8e8e…`）；基线分流探针：异模式单行注记 + serial-acid
  双轮重放零警告
- 分流终态验收（同日）：xdist 8 worker 全量 ×2
  （`/tmp/accept_xdist_r1/r2.txt`，基线 hash `cb502177…` 两轮不变）+
  全量酸测 ×2（`/tmp/accept_acid_r1/r2.txt`，39/39 绿，acid 桶基线
  `221580a9…` 逐字节一致；首轮曾抓出分流重构的 parts 未初始化
  回归，修复后重跑）
- `_run_one` 钉子验收（2026-09-30）：三外层语境全绿 + xdist 竞争
  定位与修复重验（`/tmp/xdist_pin_debug*.txt`）；基线 JSON
  serial-acid hash `66cb1eb6…` 验收后不变
- 相关提交：`6ce2038`（conftest 快照 + 串行统一重建）、
  `9d18692`（整体回归）、CONVENTIONS §13.4
