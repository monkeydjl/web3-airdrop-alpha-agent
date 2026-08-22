# Changelog

> 所有显著变更均记录在此文件。
> 格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)，
> 版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

---

## [Unreleased]

### Fixed — CI 三处长期红灯（2026-08-22）

推送 37 个积压 commit 时开了 PR #4，借 CI 把三项长期失败的检查查清并修掉。
它们**都先于本次改动存在**，只是此前没人看得出失败原因。

- **Docker 镜像扫描：36 个高危 → 0**（`Docker Image Trivy Scan` 自 08-09 起每次都红）

  这个 job 从未给出可读的失败原因：workflow 只让 Trivy 输出 SARIF 到文件，
  失败时日志里只剩一句 `exit code 1`；SARIF 上传成功但 code scanning 告警数为 0，
  run 里也没有可下载的构件 —— 从任何角度都看不到漏洞明细。先加了一步 table 格式
  输出（`exit-code: 0`，只负责让人看见，判定仍归 SARIF 那步），漏洞才第一次露面：

  - **34 个来自基础镜像的 util-linux 家族**：9 个包 × 4 个 CVE
    （`bsdutils` / `libblkid1` / `liblastlog2-2` / `libmount1` / `libsmartcols1` /
    `libuuid1` / `login` / `mount` / `util-linux`），
    CVE-2026-53612/53613/53614（mount 的 TOCTOU 与 nosuid/noexec 绕过）、
    CVE-2026-53615（libblkid 整数溢出）。Debian 已发布修复 `2.41.5-0+deb13u1`，
    但 `python:3.12-slim` 这个 tag 不会随安全更新重新指向新层，所以构建时
    必须显式 `apt-get upgrade`。加上之后 36 → 2。

  - **剩下 2 个的真正来源是 pip 的内嵌依赖清单，升级 pip 修不掉**。
    `setuptools 70.3.0`（CVE-2025-47273）与 `msgpack 1.1.2`
    （GHSA-6v7p-g79w-8964）这两个版本号，与 pip 自带的
    `pip/_vendor/vendor.txt` 里钉着的版本**逐字一致**。pip 把依赖以源码形式
    内嵌在 `pip/_vendor/` 下、不产生 dist-info，Trivy 把 vendor.txt 当成包清单来读 ——
    这也解释了它每次扫描都警告两遍
    「Third-party SBOM may lead to inaccurate vulnerability detection」，
    以及诊断输出里 `PkgPath = None`、target 名叫 `Python` 而非文件路径。
    本机 pip 已是最新的 26.2.1，vendor.txt 里**依然**钉着这两个旧版，
    所以任何 pip 升级都不可能清掉它们。
    改为**从镜像里删除 pip 与 setuptools**，builder 与 production 两个阶段都删 ——
    只删一处没用，因为 production 会 `COPY --from=builder /venv /venv`
    把同一份 pip 搬过去（Trivy 报告里确实列着
    `venv/lib/python3.12/site-packages/pip-26.2.1.dist-info/METADATA`）。
    删除安全性已实测：用 `sys.meta_path` 拦截器让 pip / setuptools /
    pkg_resources / `_distutils_hack` 全部无法导入，应用仍完整启动（28 条路由）、
    `/health` 返回 200 healthy，pandas / numpy / psycopg / alembic / apscheduler
    均正常；numpy 里唯一的 `from setuptools import ...` 位于 `numpy/distutils`
    （构建期代码），应用完整导入后它从未被加载。
    **代价**：镜像内不能再 `pip install` 排障，已在 Dockerfile 注明；
    可选的 OTel 依赖若要装，必须加在删除步骤之前。

- **前端依赖 9 个高危 → 0**（`npm audit` 自 08-13 起让 `Frontend Lint & Build` 红着）

  9 个全部源自 `nanoid < 3.3.18`（GHSA-2v37-7h3g-55p8，CWE-835 无限循环），
  经 `postcss` 传染到 `next` / `tailwindcss` 与各 postcss 插件。
  修法是 **cherry-pick dependabot PR #3 的原始 commit**（`16e4763`），
  而不是自己写版本号 —— 本机 npm registry 不可达（`EPERM`），
  编不出可信的 `integrity` 哈希，只能用它从 registry 取到的那份。
  只改 `frontend-next/package-lock.json` 3 行。实测 `npm audit --audit-level=high`
  从 9 high / exit 1 变为 **found 0 vulnerabilities / exit 0**，
  `tsc --noEmit` 与 `eslint` 仍 exit 0。同时解掉了 dependabot PR #3 卡了 5 天的问题。

- **文档死链 6 条 → 0**（`Docs Link Check`）

  `docs/00_index.md` 与 `ENGINEERING_ROADMAP.md` 仍链向 `0966179`
  （移除遗留 HTML 原型）里删掉的 6 个文件，而索引表还给每一个都标着 ✅：
  `PROJECT_BOOTSTRAP_OVERVIEW.md`、`IMPLEMENTATION_STATUS.md`、
  `PROJECT_BOOTSTRAP_CHECKLIST_V2.md`、`PROJECT_BOOTSTRAP_AUDIT_REPORT_V2.md`、
  `COLLECTION_ANALYSIS_HANDOFF.md`、`DESIGN_REVIEW_CHANGELOG.md`。
  实现状态改指向 `docs/PHASES.md`，并在索引里留了一条说明记录删了什么、为什么，
  而不是悄悄改表。本地复现 CI 判据（仅相对链接、folder-path 与 workflow 一致）
  扫 117 个 md 确认清零。ADR / superpowers 计划 / DELIVERY_CHECKLIST 里的**散文提及**
  保持原样 —— 那是历史记录而非导航，CI 也不检查它们。

### Changed — Trivy 失败时先打印明细（2026-08-22）

`security.yml` 的 `container-scan` 增加一步 table 格式扫描（非阻断），
排在原 SARIF 步骤之前。判定逻辑完全没变，SARIF 那步仍以 HIGH/CRITICAL 阻断。
动机是这个 job 红了 13 天却无人能说出原因 —— 一个只报「失败」不报「为什么」的
门禁，实际效果等于没有门禁。

### Fixed — master 分支保护有 3 个检查名对不上（2026-08-22 已修）

**原判断（保留原文）**：`master` 的 `required_status_checks` 要求 5 项，
其中 **3 项在仓库里没有任何 job 会产出**：
要求 `Lint (ruff)` 而实际 job 名为 `Lint & Format Check`；要求 `Test (pytest)`
而实际为 `Full Backend Test Suite`；要求 `Coverage Gate` 而覆盖率门禁在 pytest
步骤内部、不是独立 job。这 3 项会永远 pending，因此任何 PR 的 `mergeStateStatus`
恒为 `BLOCKED`（dependabot PR #3 卡 5 天正是此因）。
门禁看着有 5 道、实际只有 2 道生效。修法二选一：改保护规则的名字对齐实际 job 名，
或改 job 名对齐保护规则。**未擅自改动** —— 修改分支保护属于放宽门禁，需所有者决定。

**所有者选了第一种（改保护规则名对齐实际 job 名）。已按此执行：**

- **`Coverage Gate` 不是改名能解决的 —— 它需要一个真实存在的 job**。
  覆盖率门槛此前只以 `--cov-fail-under=80` 参数的形式藏在测试步骤内部：
  闸门是真的，名字是假的，而分支保护匹配的正是名字。
  新增 `coverage-gate` job（`name: Coverage Gate`）：不重跑测试（那要 7 分半），
  只下载测试阶段已上传的 `coverage.xml` 并独立断言行覆盖率。
  这**不是**与 `--cov-fail-under` 重复劳动 —— 写在命令行里的阈值被谁调低或删掉
  都不会有任何提示，而这是一道名字可见、能独立失败的闸门。
  选「让名字真实存在」而不是「从必过列表删掉它」：后者是放宽门禁，前者不是。

- 另两项是纯改名：`Lint (ruff)` → `Lint & Format Check`、
  `Test (pytest)` → `Full Backend Test Suite`。

- **闸门本身先被验证过能失败**，因为一个不会失败的覆盖率闸门比没有闸门更糟。
  用人造边界样本逐个实测：恰好 80.00% 放行（边界不得误拒）、79.99% 拦、
  79.00% 拦、缺 `line-rate` 属性拦（不得静默当成通过）、0% 拦、100% 放行 ——
  六个全部符合预期。浮点比较用 `pct + 1e-9 < THRESHOLD`，
  避免二进制表示误差把真正的 80.0% 判成不及格。
  CI 实跑结果：**88.21%（10493/11896 行）通过**。

- **改分支保护时逐项比对了改前改后**（服务器回读，不是复述请求）：
  仅 `contexts` 5 个名字变化，`strict` / `enforce_admins` / `allow_force_pushes` /
  `allow_deletions` / `required_reviews` / `restrictions` /
  `required_linear_history` / `required_conversation_resolution` /
  `block_creations` / `lock_branch` 全部保持原值。
  必过检查数量 **5 → 5，未减少**，且改后 5 个名字**每一个都对应真实 job**。
  改前的原始配置已存为回滚点。

结果：PR #4 的 `mergeStateStatus` 从 `BLOCKED` 变为 **`CLEAN`**。
门禁从「看着 5 道实际 2 道」变成「5 道全部真实生效」。

### Fixed — 归档从未真正运行过（2026-08-22）

从「归档页上那句『暂无运行历史接口』」查起，结果发现它掩盖的不是缺个接口，
而是**归档功能从来没有生效过**，以及两处会导致数据无限增长或被提前删除的缺陷。

- **归档从未被调度**：`app/archive.py` 的 `RawDataArchiver` 逻辑是真实的，但
  全仓只有手动脚本 `scripts/archive_raw_data.py` 会调用它 —— `scheduler.py`、
  CI、compose、Dockerfile 里对 `archive` 零引用，而 `DATABASE_DDL.md` §6.1 却
  写着「每日 cron 执行」。现在归档由 `UnifiedScheduler` 按 `ARCHIVE_CRON`
  （默认 `0 3 * * *`，在采集 job 08:00–10:30 之前跑完）执行
  - 归档失败**不会**让调度器崩掉，失败作为一行 `status=failed` 记入历史
  - 采集与分析都关掉、只开归档时调度器仍会启动（此前 `start()` 的「全都关了」
    判断只看两个开关，加第三档时必须一并修正，否则归档会静默失效）

- **低分采集记录永远不会被归档，会无限累积**：`processed` 只在采集记录被提升为
  正式项目时置 1，而提升要求 `discovery_score >= 0.3`。低分记录永远不会被提升，
  所以**永远不满足 `processed = 1 AND 超期` 这个归档条件**。实测本地库 693 行
  `raw_projects` 中有 509 行（**73%**）是 `processed = 0`，且它们的分数全部
  < 0.3；`processed = 1` 的 184 行全部 ≥ 0.3。这 509 行里也没有任何一行存在
  同 `dedup_key` 的高分兄弟记录，佐证逻辑不会把它们救回来
  - 按最近一次采集的 460 条低分记录估算（`raw_data` 平均 474 B）：1 个月约
    13,800 行 / 6.2 MB，1 年约 167,900 行 / 75.9 MB，3 年约 503,700 行 / 227.7 MB
  - 新增 `UNPROCESSED_RAW_RETENTION_DAYS`（默认 90 天）单独一档。**归档而非删除**
    —— 它们是复盘「当时为什么没立项」、以及日后调阈值做回溯验证的唯一依据

- **归档表自身的保留期零实现**：`DATABASE_DDL.md` 写了归档表 180/365 天保留期，
  但全仓搜不到任何按 `archived_at` 删除的语句 —— 归档表只进不出，等于把无界增长
  从主表搬到了归档表。现在按 `RAW_ARCHIVE_RETENTION_DAYS`（180）/
  `SIGNALS_ARCHIVE_RETENTION_DAYS`（365）真实清理

- **时间戳格式不一致会提前一天删数据**：归档表的 `archived_at` 走 SQLite
  `DEFAULT CURRENT_TIMESTAMP`，写出来是 `'2026-08-22 02:08:51'`（**空格**分隔）；
  而其它时间列由应用层 `datetime.isoformat()` 写入，形如
  `'2026-08-15T14:51:16.959145+00:00'`（**T** 分隔）。SQLite 的 TIMESTAMP 实际是
  TEXT，`<` 是字符串比较，空格 `0x20` < `T` 0x54，所以拿 ISO cutoff 去比
  `archived_at`，**当天写入的行会被判成「早于今天零点」**。实测（保留期设 0 天、
  行刚写入）：ISO cutoff 命中 1 行（刚归档的数据当场被删），空格 cutoff 命中 0 行。
  现在两种 cutoff 分开（`_cutoff` / `_cutoff_db_default`），并有回归测试锁住
  「同一次运行里刚归档的行不得被删」

- **保留期传 0 天曾被静默改成默认值**：构造函数原写 `days or settings.xxx`，
  于是显式传入的 `0`（合法取值，意为「立刻清理」）被当成「没传」。这个 bug 一度
  让上面那条时间戳测试**假通过**，改用 `is None` 判断后才复现出真实缺陷

### Added — 归档运行历史（2026-08-22）

- **新增 `archive_runs` 表 + `GET /api/v1/archive/runs`**：每次归档运行记一行
  （开始时间、触发方式 scheduler/manual/api、耗时、六个分项行数、成功或失败），
  失败也记 —— 只显示成功会让「归档连续几天没跑成」在界面上看不出来
  - **管理员专属**（`/api/v1/archive` 加入 `ADMIN_ONLY_PREFIXES`）：响应含各表真实
    行数与运维配置，与 `/settings` 同一口径
  - 端点**只读**，查看历史不会触发一次清理（有测试锁住）
  - 写历史失败不会掩盖归档结果（记账失败不该丢掉真实成果）
- **`/archive` 页改为真实数据**：六档保留策略各自的当前行数与「待清理」预估、
  归档调度状态与 cron、最近 20 次运行明细。此前只有保留期数字 + 一句占位说明
- **新增 Alembic 迁移 `0003`**：`archive_runs` 表 + 三个 `archived_at` 索引，
  可单独回滚到 `0002` 而不影响其它表（有测试验证回滚后再升回来仍成功）

### Docs — 修正与实现不符的归档文档（2026-08-22）

- **`DATABASE_DDL.md` §6.1 的示意 SQL 缺了 `processed` 条件**：原文写
  `WHERE discovered_at < datetime('now','-30 days')`，看起来「什么都归档」，
  而实现一直带 `processed = 1`。已改为与实现一致，并新增 §6.2（为什么未处理记录
  需要单独一档，含实测数据与增长估算）、§6.3（时间戳格式陷阱）
- `API_SPEC.md` 新增 §31 archive；`.env.example` 补齐 5 个新配置项并说明
  为什么需要它们

### Added — 打通「行动 → 复盘 → 校准」闭环（2026-08-21）

评分决策引擎此前已能算出 162 个重点参与项目，但 `watchlist` / `interactions` /
`feedback` 三张表全为 0 条 —— 结论一条都没被跟进。本次补齐从「看到」到「行动」
再到「反哺校准」的链路。

- **新增今日行动清单**（`GET /api/v1/action-queue` + 工作台卡片）：把 FARM/WATCH
  项目的参与清单跨项目聚合，按「任务优先级 × 项目分数 × 是否必做 × 是否已收藏」
  排序，默认排除已有交互记录的项目。此前参与清单只存在于单个项目详情页，
  上百个项目必须逐个点进去才看得到任务，没有任何视图回答「今天该做什么」
  - 采用**轮转取样**：5 个名额覆盖 5 个不同项目，而非被最高分项目占满
    （实测纯按分数排时 5 个名额只覆盖 3 个项目）
  - 只提供推进资格的任务类别（official/testnet/mainnet/research/risk/dev）；
    track/social 类每个项目都有，会把清单刷满
  - 结果确定性排序，同分不随字典顺序抖动
  - 标记「已做」**复用 `interactions` 表**，不引入第二套状态，记录在参与复盘页可见
- **新增结果复盘页**（`/review`）+ `POST /api/v1/feedback/batch` +
  `GET /api/v1/feedback/pending-review`：把「标十几个项目的结果」压缩到一次请求。
  权重校准门禁需要 200 条样本，而逐条进入项目详情页提交的成本让这个数字实际
  不可能达到（实测 feedback 表为 0 条，校准能力永久空转）
  - 每行三个按钮（空投了 / 没空投 / 归零），选完一次性批量提交
  - 整批在**单事务**内写入，不会出现「标了 10 个成功 3 个」的中间状态
  - 有交互记录的项目排最前（你真投入过，结果对校准最有价值）
  - 页面显示校准进度条（当前样本 / 门禁 200）。**门禁阈值未被改动**，
    降低的是录入成本而不是安全标准

### Security — 批量反馈端点加固（2026-08-21）

- **`POST /feedback/batch` 增加项目存在性校验**：该端点与既有 `POST /feedback`
  一样只需匿名 token（`/api/v1/feedback` 不在 `ADMIN_ONLY_PREFIXES` 里）。缺少
  存在性校验时，任意 `project_id` 都会入库 —— 实测**一次请求**注入 200 条伪造
  ID（`ghost-0..199`）即可让 `calibration_ready` 变为 `True`，等于用凭空数据
  决定真实的评分权重。现在未知 `project_id` 整批拒绝（404），一条伪造 ID 会让
  同批次的真实条目也不写入
- **批量条数上限由 200 收紧到 50**：与校准门禁同为 200 时，单次调用即可填满门禁。
  压到 50 使填满至少需要 4 次请求，叠加限流后提高投毒成本；真实使用一屏也标不到
  50 个。前端改为自动分批发送，用户勾再多也不会吃 422
- 补回归测试：伪造 ID 被拒、混合批次整体回滚、404 不被兜底 `except` 改写成 500

### Fixed — 术语闸门此前是坏的（2026-08-21）
**发现的问题**：`scripts/check_terminology.py` 是防止「评分决策引擎」术语回退的
唯一机械闸门（CLAUDE.md §1），但实跑 `--all` **直接失败** —— 3 个文件 5 处命中。
更关键的是它**自己一行测试都没有**，所以这个坏状态没人知道。

5 处命中里有 3 处是**不该改的**：`CLAUDE.md` 那行正在定义禁用词清单本身，
`SESSION_MEMORY_2026-07-26.md` 那行引用的是历史 git commit message（改它就是
篡改记录）。这说明问题不在文档，在闸门缺少表达"这里必须写出禁用词"的手段。

**修复**：
- 新增**行级豁免**机制（行尾加 `terminology-ok`）。刻意做成逐行显式、可
  `grep -rn terminology-ok` 审计，**不做整文件豁免** —— 否则真正的术语回退
  会藏在被豁免的文件里。当前全仓真豁免只有 **2 处**，都有明确理由
- 修掉 1 处真实的术语回退：`docs/DEPLOYMENT_REPORT_FINAL.md:115`
- `iter_tracked_files()` 改用 `shutil.which("git")` 解析全路径（ruff S607），
  并补 `check=False`
- 新增 **27 个测试**（`backend/tests/test_check_terminology.py`），其中三条是
  防滥用的关键断言：豁免只作用于本行、豁免标记数量受限、
  **本测试文件自己必须过闸门**（禁用术语样本全部拼接生成而非字面量 ——
  写字面量会让测试文件自己被拦下，实测踩过）
- 把 `--all` 的结果固化成测试，等于让 CI 也守住这道闸门
  （此前只有 pre-commit 守，`git commit --no-verify` 就绕过了）

**现在**：`check_terminology.py --all` 退出码 0。

### Fixed — 发现并部分修复文档编码损坏（2026-08-21）

**发现的问题**：文档存在**三种**编码损坏，成因同源（写回文件时没用 UTF-8，
或用 `errors='replace'` 解码后又写回），但可修复性差别很大。

**一型（非法 UTF-8，1116 处）**：每个 3 字节中文字符的第 3 字节被替换成 `?`。
`docs/DATA_SOURCE_STRATEGY.md` 498 处、`docs/OPERATIONS.md` 404 处、
`docs/OBSERVABILITY.md` 214 处。

**二型（整字变 `?`，70 处）**：`docs/API_SPEC.md`。整个中文字符被替换成一个
半角 `?`，结果**仍是合法 UTF-8** —— 一型的检查完全看不见它。
它在 git 历史里潜伏了 **6 个提交**。

**三型（字面 U+FFFD，2 处）**：`docs/SYSTEM_DIRECTION_CHANGE.md` 两个小节标题
的 emoji 被吃掉了。同样是合法 UTF-8，前两型的检查都看不见。
**这一型损失可忽略**（装饰性图标，不影响语义），但它证明了一件事 ——
"查完了"这个判断必须有依据。

这类损坏**静默**：文件照样能打开、git 照常提交，只是内容里多了一堆 `?`。
`DATA_SOURCE_STRATEGY.md` 的**所有历史版本都已损坏**，无法从 git 恢复。

**一型已定 629 处（56.4%）**，全部是可证明的恢复，不含猜测：
- 432 处由 `6823d18` 的干净历史底本序列对齐**精确恢复**
- 27 处由"该前缀在全仓语料里只对应唯一字符"推断
- 170 处由上下文规则推断，并通过**交叉验证**：规则与底本对齐独立推断同一批
  位置，105 处可核对、**冲突 0**

**箭头规则已按实测收紧，进度因此从 646 退到 629 —— 这是刻意的。**
原规则"前缀 e286 一律填 `→`"在 5 个文档上是 72/72 = 100%，扩到 140 个文档后
只有 **92.34%**（916/992），平均每 13 处写错 1 个字。
e286 前缀的真实分布：`→` 916、`←` 26、`↓` 22、`↔` 15、`↑` 13。

关键观察：**全仓统计不可靠，但同一份文档内部用法高度一致** ——
62 个含箭头的文档里 56 个（90.3%）只用 `→`。所以判据从"全仓统计"换成
"**本文档证据**（含其 git 底本）全为 `→`" + "整行只有箭头则弃权（那是架构图
纵向连接符）"。留一法实测（逐个隐藏一个箭头，只用同文档其余箭头判断）：
**582/582 = 100%**，代价是弃权 410 处。

顺带一个有价值的负面结果：两种"看起来更聪明"的收紧 —— 限缩到非缩进行
（93.14%）、限缩到左右均非空白（94.92%）—— 几乎没用。
**换判据的维度**（从"位置像不像"改成"这份文档怎么用箭头"）才有质变。

实际影响：`DATA_SOURCE_STRATEGY.md` 无底本且存活箭头 0 个，17 处箭头全部退回
人工，待定数 470 → **487**。宁可多留 17 个显眼的占位符，也不写 1 个看似通顺
的错字。

**刻意未修的一型 487 处**：这些位置的前缀对应多个候选字符，无法证明是哪一个。
实测 `efbc` 前缀的 4 个全角标点各占 26/25/20/19% —— 按频率猜的错误率接近 3/4。
把猜测写进文档比留占位符更糟：读者无法分辨哪句是原文、哪句是机器编的。
已导出为受约束选择题清单（每条给候选集 + 前后 40 字上下文）。

**二型 70 处只检测不修复**，理由是实测发现它**连"1 字符换 1 字符"都不成立**：
逐行对齐底本后，24 处可核对位置里恰好 1 个字符的是 **0 处**，多于 1 个的是
**24 处**（例如一个 `?` 吃掉了 `求/` 两个字符）。既没有候选集约束、也没有
长度约束，任何自动修复都无法用逐字节校验证明没越界。

**三型 2 处只登记不修复**：没有干净底本（最早版本就已损坏），从上下文只能
猜是哪个 emoji。补一个合适的图标属于**内容编辑**而非数据恢复，不该由修复
脚本代劳。

**新增三个工具 + 56 个测试**：
- `scripts/check_encoding.py` — 检测**三型**损坏，**已挂 pre-commit 钩子**防复发
- `scripts/repair_utf8_docs.py` — 一型四轮修复 + 选择题导出/合并
- `scripts/verify_utf8_repair.py` — 机械校验：未损坏正文必须逐字节一致，
  每处修复必须落在候选集内。这条约束结构上排除了"顺手改写句子"的修复方式。
  实测四种输入（正确修复 / 改一个字 / 插改写标记 / 删 300 字）：
  只有第一种通过，其余全部拦下
- `backend/tests/test_utf8_repair_tools.py`（32 个）— 含上述交叉验证，
  以及箭头收紧后的 8 条（默认弃权、混用多向的文档不填、独行箭头不填、
  底本也算证据）
- `backend/tests/test_encoding_mojibake.py`（24 个）— 二型 + 三型检测，
  重点防误报；含"全仓不得出现未登记损坏"这两条把钩子效果固化下来的断言，
  以及一条断言三型判据与二型互不重叠

**三型是怎么被发现的**：写完二型检测后我主动追问"还有没有第三种形态"，
换判据（字面 U+FFFD、中文后连续 `??`、全仓非 md 文本）重扫才找到。
教训写进了 `docs/ENCODING_REPAIR.md` —— **检测判据的盲区就是损坏的藏身处**。
同一份文档 §6 也如实写了"没有再找第四种形态，但没找到不等于不存在"。

**过程中更正了自己的一个结论**：上下文规则最初只在 5 个文档上量，四条都是
100%，看起来很稳。扩到全仓 140 个既有文档复测后发现箭头规则只有 **92.2%**、
括号 99.6%、句号 99.4% —— **小样本给了虚假的安全感**。
箭头那条本轮已换判据收紧到留一法 100%（见上）；括号与句号留着（错误率 0.5%
量级、被交叉验证兜住），但已在 `docs/ENCODING_REPAIR.md` §6 明确登记它们
**不算"已证明"**，若要机械处理剩下的 487 处必须先用同样方式重测。

详见 `docs/ENCODING_REPAIR.md`。

### Security — 锁定依赖版本，构建可复现（2026-08-21）

- **`backend/requirements.txt` 全部改为精确 `==`**（此前 25 行全是浮动 `>=`）。
  浮动约束意味着每次 `docker build` 拉到的可能是不同版本，本地测过的组合与线上
  跑的不是一回事，出问题无法复现。锁定值逐包与**本地跑通 2500 个测试的环境**
  核对一致（Python 3.11.9）
- **拆出 `requirements-dev.txt`**：pytest / pytest-asyncio / pytest-cov / respx /
  Faker / ruff / mypy 各锁精确版本，且**不进生产镜像**
- **CI 三处散装安装改为装锁定文件**：`pip install ruff`、`pip install pytest
  pytest-cov`、`pip install mypy` 全部替换。散装等于不锁版本 —— ruff/mypy 小版本
  间检查结果会变，这正是"本地绿 CI 红"的常见来源
- **`pip-audit` 现在能给出确定结论**：审计对象从浮动约束变为精确版本，
  同时覆盖 dev 依赖
- Dockerfile 的 `COPY backend/requirements*.txt` 收窄为只复制运行时依赖，
  并注明启用链路追踪时需要额外装什么

**发现的既有问题（顺带查清）**：那 7 个 `opentelemetry-*` 包被声明为必需依赖，
但**本地从未安装**，也**没有任何针对性测试**（`pytest -k "otel or tracing"` →
2504 deselected，0 个用例）。实测 `OTEL_ENABLED=true` 且缺包时应用正常启动、
`/health` 200，仅打一条 `tracing.unavailable` 警告——说明它们对主流程并非必需。
已移入可选的 `requirements-otel.txt`。

**后续补救**：既然它成了可选依赖，"缺包时能降级"就从隐含假设变成了**契约**，
必须有测试守。新增 `backend/tests/test_tracing_degraded.py`（18 个），
覆盖 no-op span 的调用契约、以及最关键的一条 ——
**运维在生产打开了 `OTEL_ENABLED` 但镜像没装 OTel 包**时，
必须记 warning 继续跑、不能让应用启动失败。
`app/tracing.py` 覆盖率从 **44% 升到 58%**（实测；剩下 42% 需真装 OTel 才能走到）。
同时把两处 `# pragma: no cover - deps always installed` 注释改掉 ——
那句话是错的（依赖并非总是安装），现在指向 `requirements-otel.txt`。

**刻意未锁的一项**：`requirements-otel.txt` 保留 `>=` 区间。本次作业时本机
**无法访问 PyPI**（实测连接被关闭），无法确认这些包的可用版本；凭记忆写死一个
版本号会让人以为"已锁定已验证"，实际是未经证实的猜测，比不锁更危险。首次真正
启用追踪时应实测通过后回填。

**验证方式**：新建干净 venv → 仅装 `requirements.txt` → 实测 41 个包安装成功、
应用启动、`/health` 200、`/metrics` 200；追加 `requirements-dev.txt` 后跑
22 个测试通过；临时环境已清理，本机 venv 未受污染。

### Changed — 统一用户归属过滤口径（2026-08-21）

- **新增 `app/services/user_scope.py`，收敛「查某用户的记录」这一判断**。
  根因是两张表写入 `user_id` 的方式**不一致**（实测确认，非推测）：
  `POST /interactions` 直接落 `body.user_id`，不传即 **NULL**；
  `POST /watchlist/{id}` 走 `body.user_id or "default"`，不传落 **'default'**。
  因此没有单一正确写法——只按 `user_id = 'default'` 查会漏掉 interactions 里
  那批 NULL（表现为用户刚标记「已做」的项目仍反复出现在今日行动里），
  而无条件加 `OR user_id IS NULL` 又会在多用户启用后把归属未标注的数据算进
  每个用户名下。现在：查默认用户时纳入 NULL，查具名用户时严格匹配、不读 NULL
- **`GET /feedback/pending-review` 补上用户过滤**：此前完全没有用户条件，
  与 `/action-queue` 口径不一致。多用户启用后会把别人标过的项目从你的待标
  清单里剔掉、也会把别人的交互记录当成你的
- 新增 `tests/test_user_scope.py`（8 个）锁死语义，含多用户隔离与表名白名单

### Performance — 核实 action-queue 无需缓存（2026-08-21）

上一轮我把「`action-queue` 无缓存」列为风险，**实测后确认该判断有误**：
候选池固定 60，耗时与库内项目总数**无关**。288 项目库下端到端中位数 **26ms**
（`/dashboard/overview` 为 46ms），纯聚合计算约 0.04ms/项目、线性增长。
因此刻意**不加缓存**——缓存会引入失效时机问题（标记「已做」后必须立即从清单
消失），收益却只有几毫秒。已补两个测试锁死：考察项目数 ≤ 候选池上限、
标记后下次请求立即排除该项目。

### Fixed — 独立评审发现的问题（2026-08-21）

- **修复 `--brand` CSS 变量从未定义，导致交互色静默失效**：`globals.css` 里有 10 处
  `rgb(var(--brand))`（其中 5 处为既有代码），但该变量在 `:root` / `.dark` 中
  **从未定义** —— Tailwind 的 `brand` token 只作用于工具类（`bg-brand`），不产生
  CSS 自定义属性。解析为 `rgb(undefined)` 后颜色被静默丢弃：结果按钮的选中态、
  校准进度条填充、行 hover 边框全都不显示。现按 `--accent` 同值补上定义，
  顺带修好 5 处既有失效样式
- **修复结果复盘页跨批次部分失败会重复提交**：勾选超过 50 条时分批发送，若第 2 批
  失败，第 1 批已成功却仍留在待提交集合里，用户重试会把成功过的项目重复写一遍。
  现在失败时把已成功的批次从选择集中移除，并刷新列表反映真实已写入的部分。
  界面文案也改为如实说明「批次内原子、跨批次不保证」，不再笼统宣称「不会部分成功」
- **`ActionQueue` 不再静默吞掉标记失败**：错误此前只经可选的 `onDone` 回调上报，
  调用方不传时点击失败毫无反馈。现增加组件内 `role="alert"` 错误提示兜底
- 结果按钮补 `aria-pressed` 与描述性 `aria-label`（此前选中态只靠 `data-active`
  传达，读屏软件无法感知）

### Fixed — 参与清单信号读取（2026-08-21）

- **修复参与清单的信号全部读不到、任务退化为通用套话**：扩展信号（`has_testnet` /
  `has_task_portal` / `explicit_airdrop_mention` 等）存储在 `projects.meta.signals`
  里，而 `projects` 表**没有**这些列；`generate_participation_tasks()` 直接读顶层
  键，于是 281 个项目的信号判断**恒为 False**，全部落到「无信号」兜底分支。
  实测最高分项目（83 分）也只拿到 5 条与项目无关的通用任务。
  现新增 `signals_view()` 把 `meta.signals` 展平后再传入，实测同样 6 个项目
  产出 11 种不同任务组合、单项目任务数从恒定 5 条变为 5~15 条
  - 顶层值优先于 meta（已迁移到真实列的字段不被旧快照覆盖）
  - meta 里显式的 `False` / `0` 视为有效观测，不当作缺失
  - 原有单测传的是**扁平** dict，因此这个 bug 长期潜伏且测试全绿；
    已补按真实存储形态断言的回归用例
- **修复 `/feedback/pending-review` 被动态路由吞掉**：FastAPI 按声明顺序匹配，
  `/feedback/{project_id}` 在前会把 `pending-review` 当成一个 project_id，返回
  `{"project_id":"pending-review","count":0,"items":[]}` —— HTTP 200 但内容全空。
  已调整声明顺序并补回归测试

### Security — 上线复核 P0 修复（2026-08-20）

- **修复 `/api/v1/settings/config` 明文泄露 LLM API Key**（严重）：该端点直接返回 `settings.llm_providers`，其中含 `api_key` 原文。配合公开的 `POST /api/v1/auth/anonymous`（任何人可领匿名 token），构成**零凭证窃取 OpenAI/DeepSeek 密钥**的完整链路（已实测复现）。现改为只返回 `has_api_key` 布尔值，与 `/llm/status` 的脱敏口径一致
- **`/api/v1/settings` 收入管理员权限**（`ADMIN_ONLY_PREFIXES`）：运行时配置快照含 CORS 白名单、DB 后端、全部阈值与 cron，属运维信息，不应对匿名角色开放。修复后匿名 token 访问返回 403，管理员 200
- **移除 `NEXT_PUBLIC_API_KEY` 客户端兜底**（`frontend-next/lib/api.ts`）：`NEXT_PUBLIC_*` 会被内联进浏览器 bundle，任何访客都能在 DevTools 读到管理员密钥。鉴权统一由服务端 `proxy.ts` 注入，密钥不出服务端
- **生产环境 CORS 增加 localhost 校验**：`CORS_ORIGINS` 含 `localhost`/`127.0.0.1` 时拒绝启动，避免生产忘配导致真实前端域名被全部挡掉（表现为"上线后所有接口跨域失败"）

### Fixed — 上线复核 P0/P1 修复（2026-08-20）

- **修复容器按官方文档启动必然 CrashLoop**（阻断）：`docker-compose.yml` 的 `environment:` 白名单未透传 `AUTH_TOKEN_SECRET`，而镜像内无 `.env`（被 `.dockerignore` 排除）、也没有 `env_file:`；`APP_ENV` 默认为 `production` 时生产自检强制要求该值 → `docker compose up -d --build` 100% 起不来。现补 `env_file: [.env]`，与 `docker-compose.prod.yml` 对齐。已用真实容器验证：修复前拒绝启动，修复后 `Up (healthy)` 且 `/health` 返回 healthy
- **修复两层缓存 TTL 边界判定**（`app/utils/fetcher.py`）：内存与磁盘层都用 `time.time() - ts > ttl`，`ttl=0`（语义为"不缓存"）时因 `0 > 0` 为 False 而返回本该过期的数据。Windows 时钟分辨率约 15.6ms，实测 20 次里 14 次命中脏数据。改为 `>=`
- **移除 `/collections` 整页虚构数据**：原页面零 API 调用，展示 9 个不存在的项目（Nova Protocol / Poly Oracle 等）配虚构评分与「官方确认 Q3 空投」类假情报，对空投决策系统属误导性金融信息。现接入既有但从未被前端使用的 `GET/DELETE /api/v1/watchlist`，取消收藏为真实写入
- **移除 `/archive` 整页虚构数据**：原页面展示虚构归档记录、「命中率 99.2%」、「已归档 38.6 GB」，且所有开关为 `onChange={() => {}}`。现只展示 `/settings/config` 里真实的保留期配置，并明确标注「暂无运行历史接口」
- **移除 `/settings` 假保存按钮**：`handleSave` 只弹「配置已保存」toast 而不写任何东西，旁边却写着「修改将在保存后写入 .env 并热加载」，自相矛盾。整页改为明确的只读快照（标题标注「只读」，输入框改文本展示，开关 `disabled`），删除保存按钮
- **移除 `/ops` 假调度块与假配额**：`SCHEDULER_JOBS` 写死 4 个后端根本不存在的 job 及其「成功 · 182 条」等执行结果，开关空操作、「立即执行」无 onClick；`SOURCE_QUOTAS` 写死各源配额用量。现改为展示 `/settings/config` 的真实调度配置，配额改用后端真实的 `api_calls_today`
- **移除项目详情页恒为「排名第 1」**：`const rank = 1` 写死，任何项目都显示第 1 名
- **采集源缺凭证时启动告警**：`GITHUB_ENABLED=true` 但 `GITHUB_TOKEN` 为空时，GitHub 源静默不跑（`is_enabled()` 返回 False），而 execution 维度占 13% 权重会永久缺失。现在启动日志显式 warning
- **`dashboard.py` 影子块异常不再静默 `pass`**：改记 debug 日志，避免真实 SQL/schema 故障被吞掉、面板恒显 0 而无从排查

### Changed — 工程门禁与配置一致性（2026-08-20）

- **CI 三道门修复至全绿**：`ruff check` 由 99 errors → 0（62 项自动修复，其余逐条判断）；`ruff format` 由 31 文件待重排 → 全部合规；`mypy app` 由 7 errors → 0
- **`sqlite3.Row` 的 SIM118 加豁免**：`"col" in row.keys()` 是列存在性检查的唯一正确写法（`in row` 检查的是**值**），照 ruff 建议改会让所有可选列静默变 None——已在 `pyproject.toml` 注明原因
- **统一两份 `pyproject.toml` 的口径**：`backend/pyproject.toml` 的 version 1.0.0→0.1.0、requires-python >=3.10→>=3.11、mypy python_version 3.13→3.12（对齐 CI 与 Dockerfile 的 3.12），并补上此前缺失的 `--cov-fail-under=80`（pytest 从 `backend/` 运行时用的正是这份配置，等于本地跑测试完全不校验覆盖率）
- **`.env.example` 补关键提示**：`AUTH_TOKEN_SECRET` 标注生产必填（为空则容器 CrashLoop）+ 生成命令；`CORS_ORIGINS` 标注生产必须改真实域名

### Added — Portfolio/Settings 真实化 + middleware 迁移（2026-07-26）

- **Portfolio 页接入真实 API**：去掉全部 mock 数据，改为读取 `GET /interactions/summary` + `GET /interactions`；KPI、校准矩阵、分布、记录表全部真实数据
- **Settings 页接入真实配置**：新增 `GET /api/v1/settings/config` 只读端点，返回运行时配置快照（密钥只返回布尔值）；前端 Settings 页从硬编码默认值改为回填真实运行时值
- **Next.js middleware → proxy 迁移**：`middleware.ts` 重命名为 `proxy.ts`（Next.js 16 约定），消除 deprecation warning

### Added — 通知中心增强：评分变化 + 已读持久化（2026-07-26）

- **评分变化通知**：从 `project_history` 对比同项目最新两条快照，生成 `score` 类型通知（升/降/标签变化）
- **已读状态持久化**：新增表 `notification_reads` + `POST /api/v1/notifications/read`（支持 ids / all）；刷新后已读状态保留
- **前端通知中心**：点击单条 / 「全部已读」会调用后端持久化；并修正 `apiFetch` 解包 `data` 后的字段读取

### Added — 通知中心真实化（2026-07-26）

- **新增 `GET /api/v1/notifications` 聚合端点**：返回今日新 FARM/WATCH 机会 + 采集器失败告警
- **通知中心页接入真实数据**：去掉写死 mock，改为读取上述端点；空库时显示空状态而不是假项目

### Added — Dashboard 今日流水线真实化（2026-07-26）

- **新增 `GET /api/v1/dashboard/overview` 聚合端点**：一次返回今日采集运行数、今日新增项目数、发现队列待处理数、影子引擎今日评估数
- **Dashboard「今日流水线」卡片接入真实数据**：原先写死的 `sampled 3 / saved 3 / 待处理 12` 等假数据，改为读取真实采集运行、发现队列与影子评估计数

### Added — 上线审核 P1 项（GO_LIVE_AUDIT_REPORT，2026-07-26）

- **所有 API 响应携带 `X-Disclaimer` 响应头**（`Not investment advice...`，SECURITY.md §7.5 合规要求）
- **新增 HTTP 请求计数指标** `airdrop_http_requests_total`（按方法 + 状态码分档）
- **告警规则补充**：`HighAPIErrorRate`（5xx > 0.1/s，critical）+ `PipelineConsecutiveFailures`（15 分钟 ≥ 2 次失败，critical）；`airdrop_pipeline_runs_total` 新增 `status` 标签（started/completed/failed）
- **生产自检新增 AUTH_TOKEN_SECRET 校验**：生产环境该值为空会拒绝启动（否则匿名 token 每次重启后失效）

### Fixed — 上线审核阻断项修复（GO_LIVE_AUDIT_REPORT，2026-07-26）

- **删除冲突的 `backend/Dockerfile`**：它与正确的 `docker/Dockerfile` 并存且被 `docker-compose.yml` 默认引用，但其 Python 3.14 + 不完整的 COPY 会让 `docker compose up --build` 构建失败；统一引用 `docker/Dockerfile`
- **统一 Python 版本到 3.12**：此前 CI 用 3.13、Dockerfile 用 3.11、本地为 3.14，三处不一致可能引入「CI 通过但生产失败」的幽灵问题；现 CI（ci.yml / security.yml）和 docker/Dockerfile 统一为 3.12

### Fixed — 系统审查（采集链路 / 流水线 / 安全 / 前端，2026-07-26）

详见 `SYSTEM_AUDIT_REPORT.md`。真实库（702 项目 / 1040 原始记录）实测：7 项可验证信号里 6 项命中率为 0%。

**采集链路**
- **DefiLlama 补齐字段映射**：`description`（文本判断的唯一来源，缺失导致 `has_docs`/`has_roadmap`/`explicit_airdrop_mention` 全语料恒为 False）、`tvl_usd`、`has_twitter`/`has_github`
- **跨源合并首次可发生**：galxe/layer3/etherscan/twitter/coingecko 不再臆造赛道（写死 `Quest`/`On-chain`/`Unknown`/`DeFi` 会让 dedup_key 与真实赛道永不相撞，真实库 `source_count>=2` 恒为 0%）；新增"赛道未知分组并入同名已知分组"（仅唯一匹配时）
- **信号补充源不再被阈值挡在门外**：coingecko(0.1)/etherscan/cryptorank(≤0.28) 低于分析阈值 0.3，此前从不进入合并；现在同 dedup_key 已有记录过线时，低分佐证一并载入，且 `limit` 改为约束项目数而非原始行数
- **Twitter 正文参与解析**：推文载荷在 `raw_data["text"]`，此前不在取值范围内，两个 twitter 源贡献恒为零
- **修正阶段与代币推断**：TVL 分档判 testnet 造成 31.8% 项目误标；`_is_unlisted` 改为"真实 ticker > gecko_id"，并把 DefiLlama 的 `"-"` 哨兵值（真实库 658/1040 条）排除在 ticker 之外
- **GitHub 赛道整词匹配**：`"ai" in desc` 会命中 blockchain/chain/mainnet；改存 `pushed_at` 而非会被 star 顶新的 `updated_at`
- **CoinGecko 不再拿币种图标当官网**
- **合并容忍 naive/aware 时间戳混用**：`min()` 抛 TypeError 会中断整批采集

**流水线与调度**
- **持久化失败不再报成功**：状态改到落库之后再定；出队判据从"内存评分成功"改为"确实写进 projects"，此前整批丢失且队列已清空、DB 与 metrics 均无痕迹
- **每次运行落持久记录**（`LogRepository.log_run` 此前定义了却从无调用方）
- **cron 传 timezone**：预构造的 `CronTrigger` 不继承 `scheduler.timezone`，`TIMEZONE` 配置被静默忽略；`misfire_grace_time` 由默认 1 秒改为 1 小时 + `coalesce`

**安全（对照 `docs/SECURITY.md`）**
- **500 响应不再回显异常原文**（psycopg 异常带 DSN 含库密码，httpx 异常带 `?apikey=`）
- **安装 structlog 脱敏 processor**（§3.3 要求但全仓库无 `structlog.configure()`）：按字段名脱敏、递归容器，且排在 traceback 渲染**之后**
- **`APP_ENV` 归一化**：`Production`/`PRODUCTION`/`prod`/`"production "` 此前全部绕过生产安全校验
- **API_KEY 长度下限 32**（§4.2；原实现只校验非空）
- **接入限流**（§4.2/§10.4，三个配置项此前无人读取）：按 IP 滑动窗口 + 429/Retry-After，昂贵端点分档；默认不采信可伪造的 `X-Forwarded-For`，新增 `TRUSTED_PROXY_COUNT`
- **输入长度与取值域上限**：feedback 的 note 实测 20MB 直接落库；funding 的 NaN 会写进 meta 再报 500
- **移除根目录 nginx.conf 的 CORS 通配**：`Access-Control-Allow-Origin: *` + 自动放行预检 + `always`（连 401 都带），且与后端同名头重复导致白名单失效
- `/health` 降级时返回 503（探针按状态码判活）

**前端**
- **采集按钮失效**：后端返回嵌套 `status.enabled`，前端读顶层 `enabled` → 启用列表恒为空；同一错位让 Ops 页全部显示"已禁用"
- **Insights 页 `热度 NaN`**：读错字段名（`heat_score` vs `avg_heat_score`）
- **失败请求不再渲染成空数据成功**；Nav 的接口状态改为三态（检测中/在线/异常），并改探 `/health`
- **项目详情页加代次守卫**：重评后的刷新可能被慢的旧响应覆盖，把分数写回重评之前

### Fixed — 评分决策引擎回归规范（ADR-014，2026-07-26）
- **跨源合并不再丢信号**（`utils/normalize.py`）：原按来源优先级整条择一，落选来源的 23 个信号字段被清空、`source_count` 恒为 1，导致「多发现一个来源分数反而下降」。改为按字段类合并（存在性布尔 OR / 数值 max·min / 列表并集 / 标量取最高可信已知值），并给 `manual`/`api` 显式取值以否决权（唯二能主张否定的来源）；合并结果与输入顺序、与 `PYTHONHASHSEED` 均无关。见 `DATA_SCORING_DICT.md §5.8`
- **Risk Agent 改用 `tokenomics.risk`**（`agents/risk.py`）：原误取 `unlock_penalty`，与 `DATA_SCORING_DICT.md §5.7.2` 不符，方向与模型意图相反（高解锁压力少扣 31.5 分、VC 集中反加 12 分）
- **`airdrop_signal` 子分统一到 `agents/airdrop_signal.py`**：原在 scorer 与 risk 各有一份实现，2304 种信号组合中 666 种结果不一致
- **confidence 去掉 0.55/0.45 人为下限**（`agents/scorer.py`）：四个 Agent 全部成功的正常路径下 confidence 恒 ≥0.55，`confidence < 0.5 强制降档` 只在 Agent 崩溃时生效，而它本意是防「可验证信号不足」
- **`weight_version` 改为从配置读取**；新增 `projects.sub_scores` 列承载子分快照（不复用 `raw_signals`——那一列存的是采集**输入**信号），UPSERT 以 `COALESCE` 写入，评分失败时不覆盖上一次的好快照
- **`TokenomicsResult` 可往返**：`computed_field` + `extra="forbid"` 曾使 `model_dump()` 无法回放，任何从 `tokenomics_json` 重建的路径都会硬失败
- **`tier-1 vc backed` 误判修正**（`agents/team.py`）：`funding_quality <= 0` 时不再打 tier-1 标记
- **融资文本匹配收紧**（`agents/collector.py`）："hourly funding rate"、"raised the block gas limit" 等不再误判为融资事件
- **信号缺失判定修正**（`services/project_signals.py`）：布尔 `False` 与数值 `0` 是有效观测，不再当作缺失，消除单向棘轮

### Fixed — 旁路机会引擎（ADR-014，`opportunity-v2.0`）
- **联合概率区间算法**（`opportunity/probability.py`）：端点由逐分位连乘（`low×low×low`，与 `base` 的独立性假设自相矛盾）改为相对不确定度平方和合成，并以逐分位连乘为地板/天花板，保证新区间恒为旧区间的子集（0.1 网格穷举 2334 万组验证）。原算法使「官方分发 + 积分制资格」档的 `joint.low` 恒为 0.1650，永远跨不过 FARM 门槛 0.20。`base=0` 时端点不再一并归零，避免经 `DUST_REWARD` 误判 IGNORE
- **`TOO_EXPENSIVE` 恢复可达**（`opportunity/decision.py`）：已确知超预算的判定前移到「证据不足」短路之前（仍后于三个 BLOCK 判定），并要求来源等级 ≥ B 且为 observed/derived，避免一条 U 档道听途说把项目钉成 30 天 IGNORE。此前 270 项语料中旧引擎产出 `NOT_FIT` 的数量为 0，用户被告知「去补证据」而真实原因是「太贵了」
- **理由码不再塌缩**（`opportunity/decision.py`）：补齐 `service.evaluate_row` 使用的 8 个 `_usd`/`_hours` 后缀命名，此前一律映射为通用码 `WAIT_MORE_EVIDENCE`
- **证据新鲜度延长衰减尾部**（`opportunity/service.py`）：原 >90 天一律 0.2 且永不再降；现 ≤180 天 0.2、≤365 天 0.1、此后 0.05（只收紧，任何年龄都 ≤ 原值）

### Added
- `backend/app/agents/airdrop_signal.py` — `airdrop_signal` 子分唯一实现
- `backend/scripts/dual_run_compare.py` — 新旧引擎双跑对比（`dump`/`diff` 主引擎，`dump-opp`/`diff-opp` 旁路引擎）
- `backend/tests/test_review_regressions.py` — 74 条回归测试（每条对应一处已确认并修复的缺陷）
- `backend/app/rate_limit.py` — 按 IP 限流中间件
- `backend/scripts/backfill_meta_signals.py` — 从 raw_projects / project_signals 回填历史行的 meta.signals
- `SYSTEM_AUDIT_REPORT.md`
- `docs/adr/ADR-014-engine-spec-conformance.md`
- 工程基础设施完整搭建（P0/P1 全部完成）
- `pyproject.toml` — 项目元数据 + ruff/mypy/pytest 配置
- `.env.example` — 全量环境变量模板
- `.gitignore` — 完整的忽略规则
- `.editorconfig` — 跨编辑器格式统一
- `Makefile` — 开发常用命令
- `backend/app/` — FastAPI 应用骨架（config/db/main/models）
- `agents/` — 15 个详细 Agent 定义文件（Planner/Architect/Backend/Researcher/Frontend/Database/DevOps/Prompt/Reviewer/Security/Performance/Tester/Release/Documentation/Knowledge）
- `skills/` — 21 个实际 Skill 模板（backend/frontend/database/security/performance/deployment/documentation/api/llm/prompt/evaluation/debug/refactor/review/architecture）
- `prompts/` — 5 个 Prompt 模板文件（Narrative/Team/Risk/Tokenomics/Orchestrator）
- `knowledge/` — 业务和技术知识文件（business/technical/api/external/decisions）
- `configs/` — 分环境配置文件（dev/staging/prod）+ Feature Flags
- `tests/` — 可运行测试骨架（unit/contracts/golden/api，22 passed）
- `docs/00_index.md` — 00–15 编号体系文档索引
- `.github/workflows/docs.yml` — 文档链接校验 CI

---

## [0.1.0] - 2026-07-08

### Added
- 完整设计文档体系（20+ 份文档）
- 11 份 ADR（ADR-001 ~ ADR-011）
- 编码规范（`CONVENTIONS.md`，17 节）
- API 规范（`docs/API_SPEC.md`）
- 评分数据字典（`docs/DATA_SCORING_DICT.md`）
- 数据库 DDL（`docs/DATABASE_DDL.md`）
- 前端规范（`docs/FRONTEND_SPEC.md`）
- 用户故事（`docs/USER_STORIES.md`）
- 任务分解（`docs/TASK_BREAKDOWN.md`）
- 部署文档（`docs/DEPLOYMENT.md`）
- 可观测性设计（`docs/OBSERVABILITY.md`）
- 安全规范（`docs/SECURITY.md`）
- 数据质量框架（`docs/DATA_QUALITY.md`）
- 运维手册（`docs/OPERATIONS.md`）
- 性能基准（`docs/PERFORMANCE_BENCHMARK.md`）
- Golden 测试用例（`docs/GOLDEN_TEST_CASES.md`）
- 设计令牌（`docs/DESIGN_TOKENS.md`）
- 术语表（`docs/GLOSSARY.md`）
- Agent 系统（`agents/README.md`）
- Skills 系统（`skills/README.md`）
- Prompt 管理（`prompts/README.md`）
- 知识库（`knowledge/README.md`）
- CI/CD 流水线（ci.yml / security.yml / release.yml）
- PR 模板 + Issue 模板
- 测试骨架（`tests/` + `conftest.py`）
- Docker 配置（Dockerfile + nginx）
- AI 开发工作流（`docs/AI_DEV_WORKFLOW.md`）
- 项目启动检查清单（`docs/PROJECT_BOOTSTRAP_CHECKLIST.md`）

---

## [0.0.1] - 2026-07-07

### Added
- 项目初始化
- README.md 基础结构
- 基础目录结构

---

[Unreleased]: https://github.com/web3-airdrop-alpha/web3-airdrop-alpha-agent/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/web3-airdrop-alpha/web3-airdrop-alpha-agent/compare/v0.0.1...v0.1.0
[0.0.1]: https://github.com/web3-airdrop-alpha/web3-airdrop-alpha-agent/releases/tag/v0.0.1
