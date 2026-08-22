# 2026-08-22

## 本次做了什么

两件事：① 把编码修复的箭头推断规则按实测收紧（已提交 `a1a49e0`）；
② **落地归档子系统 —— 起因只是前端一句"暂无运行历史接口"的占位**。

---

## 一、箭头规则收紧（已提交 a1a49e0）

上一轮我说箭头规则"已量化但待收紧"，本轮真收紧了。

原规则「前缀 `e286` 一律填 `→`」在 140 个文档上的留一法准确率只有 **92.34%**
（平均每 13 处写错 1 个字）。我先试着限缩语法位置：

| 判据 | 样本 | 准确率 |
|---|---|---|
| 无条件填 `→` | 992 | 92.34% |
| 仅非缩进行 | 816 | 93.14% |
| 左右邻居都非空白 | 197 | 94.92% |
| **本文档证据（含 git 底本）** | 583 | **99.83%** |
| **＋独行箭头弃权** | 582 | **100%**（410 处弃权） |

**关键教训：限缩语法位置只能涨到 93~95%，换判据的维度才有质变。**
前三行都在问"这个位置像不像箭头"，第四行改问"这篇文档到底用哪些箭头"——
`e286` 前缀下 `→` 占 92.34%，但 62 个含箭头的文档里有 56 个（90.3%）**只用** `→`。
所以"本文档其余存活的 `e286` 字符是否全是 `→`"这个判据几乎无损。

**代价是待定数从 470 涨到 487（进度 58% → 56.4%）。这是刻意的**：
宁可多留 17 个显眼的占位符，也不写 1 个看似通顺的错字 —— 读者分不出哪个是
机器编的。

---

## 二、归档子系统：一句占位掩盖了三个真缺陷

`/archive` 页原本写着「暂无运行历史接口」。我去查"为什么没有接口"，
结果发现**归档功能从来没有真正运行过**。

### 缺陷 1：归档零调度

`app/archive.py` 的 `RawDataArchiver` 逻辑是真实且能跑的，但全仓只有手动脚本
`scripts/archive_raw_data.py` 会调用它 —— `scheduler.py` / CI / compose /
Dockerfile 里对 `archive` **零引用**。而 `docs/DATABASE_DDL.md` §6.1 明明写着
「每日 cron 执行」。

实测印证：`raw_projects_archive` **0 行**、`project_signals_archive` **0 行**。

修复：接入 `UnifiedScheduler`，`ARCHIVE_CRON` 默认 `0 3 * * *`
（采集 job 集中在 08:00–10:30，03:00 跑完不与写入争锁 —— 时间点是所有者选的）。

### 缺陷 2：73% 的行永远不会被归档

归档条件是 `processed = 1 AND 超期`。而 `processed` 只在采集记录被**提升为正式
项目**时才置 1，提升的前提是 `discovery_score >= 0.3`（分析阈值）。

低分记录永远不会被提升 → **永远不满足归档条件**。实测：

| 分组 | 行数 | 占比 | 分数 |
|---|---|---|---|
| `processed = 1` | 184 | 27% | 全部 ≥ 0.3 |
| `processed = 0` | 509 | **73%** | 全部 < 0.3 |

而且这 509 行里**没有任何一行**存在同 `dedup_key` 的高分兄弟记录，所以佐证逻辑
（`_corroborating_rows()`）也不会把它们救回来。它们是纯粹的死数据，只会累积。

按最近一次采集的 460 条低分记录估算（`raw_data` 平均 474 B、最大 1185 B）：

| 时间 | 行数 | 体积 |
|---|---|---|
| 1 个月 | ≈ 13,800 | ≈ 6.2 MB |
| 1 年 | ≈ 167,900 | ≈ 75.9 MB |
| 3 年 | ≈ 503,700 | ≈ 227.7 MB |

修复：新增 `UNPROCESSED_RAW_RETENTION_DAYS`（默认 90 天）单独一档。
**归档而非删除**（所有者选择）—— 它们是复盘"当时为什么没立项"、以及日后调整
阈值做回溯验证的唯一依据。

### 缺陷 3：归档表自身的保留期零实现

`DATABASE_DDL.md` 写了归档表 180/365 天保留期，但全仓搜不到任何按 `archived_at`
删除的语句 —— **归档表只进不出**，等于把无界增长从主表搬到了归档表。

修复：实现 `RAW_ARCHIVE_RETENTION_DAYS`（180）/
`SIGNALS_ARCHIVE_RETENTION_DAYS`（365）的真实清理。

---

## 实现过程中查出的两个"静默出错"

### 时间戳格式不一致会提前一天删数据

归档表的 `archived_at` 没有应用层赋值，走 SQLite `DEFAULT CURRENT_TIMESTAMP`，
写出来是 `'2026-08-22 02:08:51'` —— **空格**分隔、无微秒、无时区。
而 `discovered_at` / `captured_at` / `started_at` 由应用层 `datetime.isoformat()`
写入，实测真实库里是 `'2026-08-15T14:51:16.959145+00:00'` —— **T** 分隔。

SQLite 的 TIMESTAMP 实际是 TEXT，`<` 是**字符串比较**。空格是 `0x20`、`T` 是
`0x54`，所以拿 ISO 格式的 cutoff 去比 `archived_at`，**当天写入的行会被判成
"早于今天零点"**。

实测（保留期设 0 天、行刚写入）：

```
cutoff 用 T 分隔   -> 命中 1 行   ← 刚归档的数据当场被删
cutoff 用空格分隔  -> 命中 0 行   ← 正确
```

修复：拆成 `_cutoff()`（ISO，给应用层写的列）与 `_cutoff_db_default()`（空格，
给 `archived_at`），并加回归测试锁住「同一次运行里刚归档的行不得被删」。

### `days or default` 把显式传入的 0 吃掉了 —— 这让上面那条测试假通过

**这是本轮最该记住的一件事。** 我写完时间戳修复后，想反向验证 bug 真实存在
（把 `_cutoff_db_default` 换回 `isoformat` 看测试是否变红），结果**没能复现**。

差一点我就据此认为"这个 bug 不存在、是我想多了"。

真实原因：构造函数写的是 `raw_archive_retention_days or settings.xxx`，
于是我显式传入的 `0`（合法取值，意为"立刻清理"）被 `or` 当成"没传"而**静默
换成了 180 天**。保留期是 180 天，当然什么都不会被删 —— 测试装置本身失效了。

改成 `is None` 判断后，bug 立刻复现：

```
修复后          : 归档 1, 清理 0, 归档表剩 1
换回 isoformat  : 归档 1, 清理 1, 归档表剩 0   ← 刚归档的数据当场被删
```

**教训：验证失败时，先怀疑验证装置。** 一次"反例跑不出来"不能证明缺陷不存在。

---

## 新增的东西

- `archive_runs` 表 —— 每次归档运行一行（开始时间、触发方式 scheduler/manual/api、
  耗时、六个分项行数、成功或失败）。**失败也记**，否则"归档连续三天没跑成功"
  在界面上看不出来 —— 只显示成功的历史会给人虚假的安心
- `GET /api/v1/archive/runs` —— **管理员专属**（响应含各表真实行数与运维配置，
  与 `/settings` 同一口径）、**严格只读**（查看历史不触发清理，有测试锁住）
- Alembic 迁移 `0003` —— 可单独回滚到 `0002` 而不影响其它表（有测试验证回滚后
  再升回来仍成功）
- `/archive` 页改为真实数据：六档策略各自的当前行数与"待清理"预估、
  归档调度状态与 cron、最近 20 次运行明细

## 顺带修正的文档不实之处

`DATABASE_DDL.md` §6.1 的示意 SQL 是
`WHERE discovered_at < datetime('now','-30 days')`，**没有 `processed` 条件**，
看起来"什么都归档"，而实现一直带 `processed = 1`。已改为与实现一致，
并新增 §6.2（为什么未处理记录要单独一档，含实测数与增长估算）、
§6.3（时间戳格式陷阱）。

## 关键决定

| 决定 | 理由 |
|---|---|
| 低分记录**归档而非删除** | 所有者选择。它们是复盘"当时为什么没立项"和调阈值做回溯的唯一依据 |
| cron 定 **03:00** | 所有者选择。采集 job 在 08:00–10:30，03:00 不争锁 |
| `/api/v1/archive` **管理员专属** | 含各表真实行数与保留期/cron，属运维信息 |
| 归档历史端点**严格只读** | 不做"点一下就删数据"的按钮；手动触发只留脚本入口 |
| 归档失败**不让调度器崩** | 失败已作为一行 `status=failed` 记入历史，下一个 cron 照跑 |
| 写历史失败**不掩盖归档结果** | 记账失败不该丢掉真实成果 |

## 实际跑过的验证

```
pytest -q（全量，后台）   → 2648 passed, 4 skipped, 88.15% cov, 36m31s, exit 0
归档相关定向             → 69 passed（archive 28 + archive_runs 19 + scheduler 17 + alembic 5）
ruff check app tests alembic → All checks passed!
ruff format --check      → 231 files already formatted
mypy app                 → no issues found in 117 source files
check_encoding.py        → 488 文件通过 + 5 个已登记损坏，exit 0
check_terminology.py --all → exit 0
前端 tsc --noEmit         → exit 0
前端 eslint app/archive/page.tsx → exit 0
next build               → 编译成功（4.8s），收尾 spawn EPERM = 沙箱限制，非代码问题
```

> 全量测试数从上一轮 2601 涨到 **2648**（+47：归档相关新测试）。

## 遗留问题 / 下一步

1. ~~**合并 PR #5**~~ → **已合并并验证**（`05741b3`）：
   `Upload Trivy results` **success**、整个 job success，
   且 `code-scanning/analyses` 里**第一次出现 `ref=refs/heads/master` 的记录**
   （此前所有记录都只有 `refs/pull/*` —— 这正是「上传只在 PR 事件下成功」的
   直接证据）。**master 上 `CI` / `Security Scan` / `Docs Link Check`
   三个 workflow 全部 success，是 08-09 以来第一次全绿**
2. **编码损坏**：一型 487 处待人工判定（`DATA_SOURCE_STRATEGY.md` 占 367 处且
   无干净底本）、二型 `API_SPEC.md` 70 处只检测不修复、三型 2 处只登记
3. **Python 版本口径不一致**：镜像/CI/mypy 用 3.12，本地 venv 3.11.9。
   待所有者决定
4. ~~**Docker 未验证**~~ → **本轮已由 CI 验证**：`Docker Build Check` pass
   （含 `/health` 冒烟）、`Docker Image Trivy Scan` pass。本地仍无法构建
   （docker daemon `npipe` 权限被拒），但 CI 覆盖了这一层
5. `SEED_FALLBACK_ENABLED` 生产建议设 `false`
6. `/ops` 仍有无后端接口的区块（诚实占位，非假数据）
7. **归档的真实运行尚未观察到** —— 库里数据只到 08-15，当前没有任何行到期，
   所以定时归档跑起来也是 0 行。要等数据自然过期，或所有者同意临时调小保留期
   做一次实跑
8. **镜像内不再有 pip** —— 为清掉 Trivy 的 2 个高危而删除（详见下文）。
   后果：不能在容器里 `pip install` 排障。要临时装包就进 builder 阶段，
   或另起一个 `python:3.12-slim` 容器

---

## 三、推送与 CI：三处长期红灯查清并修掉

所有者的指示是「没问题就推 master，影响大就开 PR」，判断权交给我。

### 为什么选了开 PR

dry-run 通过（fast-forward、非强推、密钥扫描干净），但查分支保护时发现
`master` 要求的 5 个必过检查里**有 3 个在仓库里没有任何 job 会产出**。
所有者是 owner 且 `enforce_admins: false`，技术上推得进去 —— 但那等于绕过
一道「看着有 5 道、实际只有 2 道生效」的门禁。283 个文件、6.8 万行删除的
改动不该这样落地，且这个配置错误本身需要修。
→ PR #4：`release/v2-consolidation`，master 未动。

### CI 查出并修掉的三项（都先于本次改动存在）

| 检查 | 修前 | 修后 |
|---|---|---|
| `Docker Image Trivy Scan` | 36 HIGH（08-09 起每次红） | **0** |
| `Frontend Lint & Build`（npm audit） | 9 HIGH（08-13 起红） | **0** |
| `Docs Link Check` | 6 条死链 | **0** |
| 分支保护必过检查（第四项，见下） | 5 个里 3 个是假名字 | **5 个全对应真实 job** |

**Trivy 那项的关键教训：一个只报「失败」不报「为什么」的门禁，等于没有门禁。**
它红了 13 天，因为 workflow 只让 Trivy 输出 SARIF 到文件 —— 失败时日志只剩
`exit code 1`，SARIF 上传成功却 code scanning 告警数为 0，run 里也没有构件。
先加一步 table 格式输出（非阻断，判定仍归 SARIF），漏洞才第一次露面。

- 34 个来自基础镜像 util-linux 家族（9 包 × 4 CVE），
  `python:3.12-slim` 的 tag 不随安全更新重新指向新层 → 构建时 `apt-get upgrade`，
  36 → 2
- **剩下 2 个差点被我修错**：`setuptools 70.3.0` / `msgpack 1.1.2`。
  第一反应是「升级 setuptools」，但那是错的 —— 镜像里 setuptools 已经是
  84.0.0（Trivy 自己列出 `setuptools-84.0.0.dist-info` 且 0 漏洞），
  它报的 70.3.0 另有来源。加 JSON 诊断步骤打出 `PkgPath = None`、
  target 名叫 `Python` 而非文件路径，才定位到**真正来源是
  `pip/_vendor/vendor.txt`** —— 与它钉的版本逐字一致。pip 把依赖以源码内嵌、
  不产生 dist-info，Trivy 把这份清单当包列表读（它每次扫描都警告两遍
  「Third-party SBOM may lead to inaccurate vulnerability detection」）。
  本机 pip 已是最新 26.2.1，vendor.txt 仍钉旧版 → **任何 pip 升级都不可能修掉**。
  改为删除 pip/setuptools，且 **builder 与 production 两阶段都要删** ——
  只删一处没用，production 会 `COPY --from=builder /venv /venv` 把同一份 pip 搬过去。

删除前先证明运行时不需要它们：用 `sys.meta_path` 拦截器让
pip / setuptools / pkg_resources / `_distutils_hack` 全部无法导入，
应用仍完整启动（28 条路由）、`/health` 200 healthy，
pandas / numpy / psycopg / alembic / apscheduler 均正常。
numpy 里唯一的 `from setuptools import ...` 在 `numpy/distutils`（构建期代码），
应用完整导入后它从未被加载。

**npm audit 那项**：9 个高危全源自 `nanoid < 3.3.18`，经 postcss 传染。
修法是 cherry-pick dependabot PR #3 的原始 commit（`16e4763`），
**不是自己写版本号** —— 本机 npm registry 不可达（`EPERM`），
编不出可信的 `integrity` 哈希。顺带解掉了 PR #3 卡 5 天的问题。

### PR #4 最终状态

**12 项检查全部 pass**（含 `Full Backend Test Suite` 7m42s、`Coverage Gate` 88.21%、
`Docker Build Check` 含 `/health` 冒烟、`Docker Image Trivy Scan`）。
`mergeStateStatus` 从 `BLOCKED` 变为 `CLEAN`，**已合并**，
合并 commit `d1b710b`（merge commit 方式，保留全部 46 个 commit 的历史）。
dependabot PR #3 已关闭并说明真实原因。

### 五、合并之后才露出来的第二个故障（并更正我自己的说法）

**已修复并验证** —— PR #5 合并后 master（`05741b3`）实测：
`Upload Trivy results` **success**、整个 job success、
`code-scanning/analyses` 里**第一次出现 `ref=refs/heads/master`**
（`results_count=0`，Trivy 0.74.0）。
master 三个 workflow（`CI` / `Security Scan` / `Docs Link Check`）**全部 success**。

合并触发 push 事件，`Docker Image Trivy Scan` 在 master 上**仍然红着** ——
但原因完全不同：

```
Run Trivy scan          success   ← Trivy 本身 0 漏洞，白天那些修复是有效的
Upload Trivy results    failure   ← Resource not accessible by integration
```

实测原因：仓库默认 workflow 令牌权限是 `read`，而 `upload-sarif` 需要
`security-events: write`。`pull_request` 事件下这一步能成功
（PR #4 的记录确实在 `code-scanning/analyses` 里，`ref` 为 `refs/pull/4/merge`），
`push` 事件下被拒。修法：只在 `container-scan` 这一个 job 上声明所需权限，
**不动仓库默认值** —— 默认 `read` 是对的。

**这更正了我白天的说法。** 我说过「这个 job 红 13 天是因为 36 个高危」
「SARIF 上传成功但 code scanning 告警数为 0」，两句都只对一半：
**一个 job 里叠了两个独立故障**，漏洞那个把权限那个挡住了 ——
Trivy 先 exit 1，上传成不成功轮不到显现。逐步骤走完 08-09 以来每一次 master 运行：

| 日期 | commit | 事件 | Run Trivy scan | Upload |
|---|---|---|---|---|
| 08-22 | d1b710b | push | **success** | failure |
| 08-17 | 3d6d7ef | schedule | failure | failure |
| 08-13 | d77d827 | push | failure | failure |
| 08-13 | 237b23c | push | failure | failure |
| 08-10 | fd0cb60 | schedule | failure | failure |
| 08-09 | fd0cb60 | push | failure | failure |

**上传从第一天起就在所有非 PR 运行里失败。** 我白天观察到的「告警数为 0」
正是这件事的可见症状 —— 我当时把它当成 SARIF 机制的怪癖，
其实它就是权限不足的直接后果。

**教训：一个 job 的红灯不等于一个故障。** 修好前面那个，后面那个才会露出来。
所以「修好了」这个判断必须在**修完之后再看一次实际结果**，
而不是在推之前根据推理下结论。

顺带修两个让上一个修复无法验证的问题：

- push 路径过滤不含 `security.yml` 自己 → 改这个 workflow 不会触发它
  （权限修复本来验证不了，只能等周一定时任务）
- 加 `workflow_dispatch` 手动触发 —— 这个 job 之所以 13 天没人诊断，
  部分原因就是复现一次运行得先凑出符合路径过滤的提交

这两个 commit **走了 PR #5**，没有直推 master —— 分支保护刚修成真的，
不该由我第一个绕过去。已把它们从本地 master 撤下、确认与远程逐字一致后再开分支。

### 四、分支保护的检查名错配（所有者选了「改保护规则名」后修）

这一项性质和上面三项不同 —— 不是某个检查红了，而是**门禁本身是假的**。

原状：`master` 要求 5 个必过检查，其中 3 个名字在仓库里没有任何 job 会产出，
于是永远 pending，任何 PR 恒为 `BLOCKED`（dependabot PR #3 卡整 5 天正是此因）。
表面上比别人严（要 5 道门），实际只有 2 道生效。

所有者选了「改保护规则名对齐实际 job 名」。执行时发现三项里有一项**改名解决不了**：

| 必过检查名 | 处理 |
|---|---|
| `Lint (ruff)` | → `Lint & Format Check`（纯改名） |
| `Test (pytest)` | → `Full Backend Test Suite`（纯改名） |
| `Coverage Gate` | **需要新建一个真实 job** |

**为什么 `Coverage Gate` 特殊**：覆盖率门槛一直在跑，但它只以
`--cov-fail-under=80` 参数的形式藏在测试步骤内部 —— **闸门是真的、名字是假的**，
而分支保护匹配的正是名字。一个真实生效的检查，因为没有名字，
在门禁体系里等于不存在。

新增 `coverage-gate` job（`name: Coverage Gate`）：不重跑测试（那要 7 分半），
只下载测试阶段已上传的 `coverage.xml` 并独立断言行覆盖率。
这**不是**与 `--cov-fail-under` 重复劳动 —— 写在命令行里的阈值被谁调低或删掉
都不会有任何提示，而这是一道名字可见、能独立失败的闸门。
**选「让名字真实存在」而不是「从必过列表删掉它」：后者是放宽门禁，前者不是。**

**闸门先被验证过能失败**（不会失败的覆盖率闸门比没有闸门更糟）。
人造边界样本逐个实测，六个全部符合预期：

```
恰好 80.00%          → 放行（边界不得误拒）
79.99%               → 拦
79.00%               → 拦
缺 line-rate 属性     → 拦（不得静默当成通过）
0%                   → 拦
100%                 → 放行
```

浮点比较用 `pct + 1e-9 < THRESHOLD`，避免二进制表示误差把真正的 80.0%
判成不及格。CI 实跑：**88.21%（10493/11896 行）通过**。

**改分支保护时逐项比对了改前改后**（服务器回读，不是复述我发的请求）：
只有 `contexts` 里 5 个名字变化；`strict` / `enforce_admins` / 强推 / 删除 /
评审 / 推送限制 / 线性历史 / 会话解决 / `block_creations` / `lock_branch`
全部保持原值。必过检查数量 **5 → 5 未减少**，且改后 5 个名字
**每一个都对应真实 job**。改前配置已存为回滚点。

## 这轮踩过的坑（给下一个会话）

- `glob` / `grep` 工具在 `.pytest_cache` / `.pytest_tmp` 上报 `os error 5`
  → 改用 `Get-ChildItem` / `Select-String`
- `ruff format scripts` 会把无关的 `scripts/seed.py` 重排（57 行）
  → 每次跑完 `git checkout -- scripts/seed.py`。根 `scripts/` 的既有 ruff 问题
  是刻意不动的（CI 只在 `backend` 目录跑 ruff）
- Python 源码里中文双引号 `"..."` 在字符串内会撞上外层引号 → 用 `「」`
- `npx next build` 收尾 `spawn EPERM`（沙箱不能开管道）→ 用
  `node ./node_modules/typescript/bin/tsc --noEmit` 单独验类型
- `git diff --stat` 的 `LF will be replaced by CRLF` 警告无害
- **`git push` 在本环境的正确姿势**（踩了好几轮）：
  默认 schannel 报 `SEC_E_NO_CREDENTIALS`；换 `-c http.sslBackend=openssl` 后
  凭据助手是 shell 脚本包装（`!'...gh.exe' auth git-credential`），
  沙箱不能开命名管道 → `sh.exe: couldn't create signal pipe, Win32 error 5`。
  可行解：**Basic 认证头**（Bearer 不行，GitHub 的 git-http 认 Basic）
  ```
  $b64 = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes("x-access-token:" + (gh auth token)))
  git -c http.sslBackend=openssl -c credential.helper= -c "http.extraHeader=Authorization: Basic $b64" push origin <branch>
  ```
- **`gh run view --log-failed` 会失败**（`Access is denied`，缓存目录在
  `%LOCALAPPDATA%` 沙箱外）→ 改用
  `gh api repos/<o>/<r>/actions/jobs/<id>/logs > 工作区内文件`
- **GitHub Actions 日志是 UTF-16LE 带 BOM**，不是 UTF-8。
  用 UTF-8 解码会得到空字符串，让人误以为日志里没有内容 ——
  我因此一度以为 Trivy 没输出表格。按前两字节嗅探：
  `raw[:2] in (b'\xff\xfe', b'\xfe\xff')` → `utf-16`
- **别急着「修」一个自相矛盾的报告**：Trivy 报 setuptools 70.3.0，
  而镜像里明明是 84.0.0。第一反应「再升一次 setuptools」是个看起来合理、
  但**不可能生效**的修法。先加诊断把 `PkgPath` / `PURL` 打出来，
  才找到真来源 `pip/_vendor/vendor.txt`。
  **报告自相矛盾时，先怀疑取数口径，别急着改代码。**

---

# 同日续：前端「自说自话」专项清查（PR #7 / #8 及后续）

上半场修的是**功能缺失**（归档没跑、门禁名字是假的）。下半场换了一个视角：
**前端页面上显示的每一个数字、每一个中文名、每一个分类入口，凭什么是那个值？**
一路问下来抓到 9 处，全部属于同一类病：**前端私藏了一份后端真值的副本，
或者读了一个后端根本不返回的键**。

## 已合并

| PR | 内容 | 合并时间 |
|---|---|---|
| #7 | `/ops` 导入导出接通真接口、删掉编造的导入历史、设置页改只读、上真 cron、CI node 22→24 | 14:47Z |
| #8 | 详情页/设置页不再私藏权重与阈值、洞察页补漏的扣分信号、通知中心删 3 个空分类、来源中文名补齐 | 16:07Z |

## 九处发现，按"谎言的形态"分类
### 形态一：写死一份副本，碰巧对上（4 处）

1. **详情页 8 个维度权重 + 「FARM≥65 / WATCH≥50」**
   权重当时确实与后端一致。但阈值**历史上已经被改过一次**（v1.1 把 FARM 从
   70 调到 65）—— 这就是「碰巧对上」不能当合格的铁证。
   没有只把字面量改对：后端新增 `LABEL_FARM_THRESHOLD` /
   `LABEL_WATCH_THRESHOLD`（从 `scorer.LABEL_THRESHOLDS` 查表，不是新写一份），
   前端按 `WEIGHT_*` 键去取，取不到渲染 `×—`。

2. **发现页来源下拉的 10 个 `source_id`**
   实测与后端 `GET /collections/sources` 完全一致 —— 同样是碰巧。
   改为运行时拉取；拉不到就只留「全部来源」，统计卡显示「采集源 —」而不是
   「0 个采集源」。

3. **设置页权重合计的「1.00 ✓」**
   8 行每行都带硬编码兜底值，于是这个"校验"**永远为真**。
   删掉兜底：8 个不全就显示 `—`，不等于 1.0 就显示 `✗`。

4. **数据来源中文名表**
   漏 `rootdata` 和 `import`（导入按钮上个 PR 才接通，这条路径立刻走到）、
   多一个后端从不产出的 `manual`。实测 288 个项目里真有 1 个 `import`，
   界面上原本显示的正是英文。

### 形态二：读了一个不存在的键（4 处，全在详情页）

| 页面上那格 | 读的键 | 真相 |
|---|---|---|
| 团队 → Flags | `team.flags` | 字段叫 `team_flags` → **永远显示「无」** |
| 团队 → 风险 | `team.risk_level` | 后端算了但只打日志 → 永远空白 |
| 风险 → 交互成本 | `risk.farming_cost` | 同上 |
| 代币经济 → 解锁压力 | `tokenomics.unlock_pressure` | 该键只在 `risk` 块 → 永远「—」 |

实测：落库 281 条里，前三个键各出现 **0 次**。

**这类比空白更危险**：「Flags：无」看起来像"这个项目没有风险标记"，
而不是"我读错了键名"。一个匿名团队的项目，页面上会显示得像个干净项目。

修法：后端本来就算了的（`risk_level` / `farming_cost`）补成真字段落库；
前端读错位置的改对，重复那格直接删。

`risk_level` 做成 `computed_field` 而非普通字段 —— 分档必须由 `team_score`
唯一决定，不允许外部塞一个与分数矛盾的档位。顺带消掉第四份重复：
`insights.py` 原先又抄了一遍分档三元表达式。

### 形态三：一个永远为空的入口 = 承诺一个不存在的功能（1 处）

通知中心侧栏列了 7 个分类，后端只产出 3 个（`new_project` / `score` /
`collector`）。`deadline` / `funding` / `ai` 是永久 0。概览还有一格
「截止时间临近 / 有数据时显示」—— 全仓没有任何代码路径能让它非零。
删到 3 个真类型，那格换成「评分变化」。

### 形态四：一个词在界面上代表两种东西（1 处）

系统里有两个都叫 stage 的字段，含义完全不同：

| 字段 | 取值 | 说的是 | 实测分布 |
|---|---|---|---|
| `projects.stage`（采集器写） | ideation / testnet / mainnet | 代码上到哪张网了 | 主网 184 / 测试网 97 / 构想期 5 / 空 2 |
| `NarrativeResult.stage` | early / growth / peak / mature | 赛道热度处在周期哪一段 | 成长期 208 / 成熟期 64 / 高峰期 9 |

前端只有一个 `stageZh`，**同时收录两套词汇共 8 个键**。

**一张表接受两套取值，等于把口径错配变成了看不出来的错配。**
传错词汇不会显示英文原文（那样反倒能被发现），而是显示另一套口径下
一个看着很合理的中文。实际已经在发生：详情页叙事面板写的是
`narrative.stage ?? project.stage` —— 兜底看起来贴心，实际是拿另一套口径的
答案填这一格。7 个没有叙事结果的项目，生命周期那格显示的是「主网」。

拆成 `stageZh`（只认部署三值）与 `lifecycleStageZh`（只认生命周期四值），
详情页只读 `narrative.stage`，缺了显示「—」。

顺带删掉 `timingZh` 里的 `growth: '上升期'`：穷举 `stage_to_timing()` 的
全部 4 个合法输入，输出只可能是 early/peak/late，**这一行不可达**。

### 补网（非缺陷）：旁路机会引擎面板的三张枚举表

工作流状态 7 个、资格 3 个、存活 3 个，实测**当前都对**。纳入回归是补网。
记一句：**「多一项」比「少一项」更坏** —— 少一项界面冒英文，用户看得出不对；
多一项是给了个后端会 422 拒绝的下拉选项，用户选了、保存、失败，
而界面只会说「保存失败」。

### 形态五：文档声称存在的端点（16 条）+ 虚构的字段与参数（10 处）

这一形态是本轮最大的一处，也是**唯一一处"错的东西不在代码里、但会让代码写错"**。
`docs/API_SPEC.md` 是前后端唯一书面依据，实测大面积失真。

**16 条不存在的端点**（逐条真实请求量状态码），成因分四类：

| 类型 | 例子 | 实测 |
|---|---|---|
| 单复数写错 | `/api/v1/project/{id}` | 404 |
| 动词与参数顺序颠倒 | `/collections/trigger/{source_id}` | 404 |
| 层级挂错 | 顶层 `/participation-tasks` | 404 |
| 纯设计稿从未实现 | `/re-score/{id}`、`/audit`、`/discoveries/stats`、`/discoveries/{id}` | 404 |
| 动词写错 | `PUT .../funding`（真实 PATCH）、`POST /watchlist`（真实带路径参数） | 405 |
| 前缀多余 | `/api/version`（真实 `/version`） | 404 |

其中 **8 条还明确标着「已实现」**。

`/collections/logs` 这条最阴：回 **405 而不是 404**，因为它恰好匹配上
`PATCH /collections/{source_id}` 的路径模式。**405 是个假信号** ——
看起来像「端点在、只是动词错了」，会把人往错的方向带。

**10 处虚构字段/参数**，三处会静默出错（比报错更难查）：

1. `GET /projects` 文档说 `label`/`sector`/`stage`「支持逗号多选」——
   实测 `label=FARM,WATCH` 返回 **0 条**：被当成一个字面值精确匹配，
   既不报错也不匹配。另外 `search`/`limit`/`order` 三个参数根本不存在
   （首页的关键词搜索其实是**前端在已取回的分页数据上过滤**）。
2. `GET /discoveries` 文档列 7 个参数，**只有 3 个真存在**。FastAPI 会
   **静默忽略未声明的 query 参数** —— 实测 `?source=defillama&label=FARM`
   依然返回全部 693 条。调用方以为筛选生效，手里是全量数据。
3. `POST /events` 文档说 `event_type` 限定 5 个枚举值 —— 实测**完全不校验**。
   **一个不校验的枚举，读文档的人却以为它在校验**：埋点名打错没人拦，
   只在后续统计里多出一个孤立事件名。

还有三处口径错误值得单记：

- `/auth/anonymous` 是**全仓唯一不走 `{ok, data}` 包络**的端点（贴合 OAuth2
  惯例，直接返回顶层 token 对象）。字段是 `access_token` 不是 `token`，
  有效期 `expires_in` = 259200 秒 = **3 天**，不是文档写的 30 天。
  前端 `apiFetch` 会自动解包 `data`，所以这个端点必须单独处理。
- `§22 数据模型`把**数据库列名**当成 API 字段名列了出来
  （`narrative_json` / `team_json` / …）—— **这正是详情页四个字段读空的根源**。
  现已把「API 响应字段」与「数据库列名」分成两组分别写。
- `/collections/{source_id}/trigger` 是**同步跑完采集并写库**才返回 200，
  不是文档说的「202 排队 + 返回 task_id」。我探这个端点时它真的去打了
  etherscan 并写入 2 行 raw + 4 行 signals + 1 行 log —— 已全部删除还原
  （raw 693 / projects 288 / signals 2261 / logs 20）。**探写接口前先想清楚
  它会不会落库**，这是本会话第二次栽在同一件事上。

另修掉该文档**从 §18 起断裂的编号**：后半段从「## 21. interactions」起重新
从 21 编号，与前半段 §21–§26 整段撞号 —— 同一份文档里「§23」既指版本管理
又指隔离队列。**交叉引用有一半概率翻错，而且两处都真实存在，所以看不出自己
翻错了**。已平移为 §27–§37，编号 1–37 连续无重复无缺号。

### 形态六：分级算对了，但界面把所有档位画成同一种颜色（1 处）

洞察页「高风险团队」列表实测返回 **270 条：high 71 / medium 199** ——
**74% 是「中」**。后端分档完全正确（`score_to_risk_level`），
但前端徽章写死红底红字，还直接显示英文 `high` / `medium`。

**同一种视觉强度代表两种严重程度，等于把分级取消掉了。**
用户只有两种反应，都比不分色更糟：把 199 个中风险当高危处理（决策被噪音淹没），
或者满屏红色一起无视（连真正的 71 个也漏掉）。

这一形态与前五种的区别：**数据、后端、字段名全对，错的只是"呈现的分辨率"**。
它不会被任何字段一致性测试抓到 —— 键存在、值正确、类型匹配。
新加的断言换了个角度：档位从**路由源码的过滤条件**解析（`if risk_level in (...)`），
要求前端每个档位有独立分支、且不同档位不许共用配色。
路由哪天放宽档位，测试会红。

同一处还有一个编造兜底：`flags` 缺失时填 `['匿名团队', '无公开仓库']`，
其中 **`无公开仓库` 后端根本没有这个 flag**。而且 JS 里空数组是真值，
所以这个兜底只在后端不发这个键时触发 —— 真到那天，界面会替后端凭空断言
「这个团队匿名、没有公开仓库」。改成兜底空数组、没标记就不渲染标记行。

### 形态七：一个从来没人用的组件，被我自己当成了现状（1 处）

`components/AppShell.tsx` —— 137 行，自带一套 `NAV_ITEMS`（**只有 3 项**）、
健康指示灯、主题切换、移动端底栏。**全仓没有任何文件 import 它。**
真正在跑的是 `components/Nav.tsx`（10 项导航）。

**这一处的证人是我自己**：审导航时先翻到 `AppShell.tsx`，
一度以为侧栏只有工作台/洞察/运维三个入口。任何人或 AI 审这个仓库都会踩同一脚。

更麻烦的是它带着一份**独立演化的旧逻辑**：自己探 `/health`、
主题存 `aa-theme-v2`（真正生效的是 `ThemeProvider.tsx`）。
照它改代码不会有任何报错 —— 改完刷新毫无变化，最难查的那种。

`tsc` 与 `eslint` 都不报这种文件（自身语法、类型都对），
所以只能靠显式断言。新增 `test_frontend_structure.py`：
组件必须被 import、侧栏 href 必须有对应页面、每个页面必须有入口能走到
（**没有入口的页面等于没做**）。

### 编码「二型」清零，以及为什么豁免清单本身是个坑

`docs/API_SPEC.md` 的 70 处二型损坏（整个中文字符变半角 `?`，文件仍是合法
UTF-8）全部修完，`KNOWN_BROKEN_MOJIBAKE` 清空，二型成为零豁免硬门禁。

修法**不是猜原字** —— 那等于用机器编的文字冒充原文，读者分辨不出。
损坏点都落在描述接口行为的中文散文里，所以是**按实测重写整段**，
每句话对着 `GET /openapi.json` 和真实请求校对。上面那 26 处失真就是这么查出来的。

**这就是豁免清单的危险之处**：只要文件挂在清单上，就没人会去逐行读它，
于是**错的内容跟错的字节一起躺着**。那 16 条假端点在仓库里躺了很久没人碰，
因为「反正这文件已登记待修」。新增 `test_mojibake_registry_is_empty` 正面钉住
清单必须为空 —— 往里加文件是倒退，得在测试里显式讨论，不能悄悄加一行。

一型（3 文件 1116 处非法 UTF-8）与三型（2 处 emoji）仍在登记待修。

## 历史数据：可重放才补，不可重放宁可显示「—」

这是本轮做的最需要拿捏的一个判断，两个字段**刻意处理得不一样**：

- `risk_level` **补算**：它由 `team_score` 唯一决定，而 `team_score` 是落库的，
  所以现算等于**重放同一个映射**，不是猜。实测 4 个历史项目都拿到了正确档位。
- `farming_cost` **不补**：它的输入 `has_points_program` 不在 `projects` 表里，
  无法忠实重放。历史行就是没有这个键，前端显示「—」。

**宁可显示「不知道」，也不端出一个看起来很像真值的默认值**——
这条和上半场编码修复「宁可留 17 个显眼占位符」是同一个原则。

## 新增的五套跨语言一致性回归（共 59 项）

做法：**Python 测试用正则解析前端 `.tsx` 源码（以及 Markdown 文档）**，
与后端枚举/上限/模型字段/真实路由表比对。零新增依赖
（`npm audit --audit-level=high` 必须保持 0）。

| 文件 | 项数 | 钉住什么 |
|---|---|---|
| `test_frontend_flag_parity.py` | 10 | 信号中文名与正负号分类 vs `FLAG_ADJUSTMENTS`；风险徽章分色 vs 路由过滤档位；flags 不许编造兜底 |
| `test_frontend_enum_parity.py` | 22 | 组合/复盘/通知/来源/机会引擎枚举、批量上限、来源清单不得硬编码、两套 stage 词汇分离 |
| `test_frontend_field_parity.py` | 8 | 前端读的每个键都必须存在于后端 Pydantic 模型 |
| `test_api_spec_parity.py` | 13 | API 文档端点章节 + §3 总览表 vs `GET /openapi.json` 真实路由表；章节编号唯一 |
| `test_frontend_structure.py` | 6 | 组件必须被 import；导航 href 必须有页面；页面必须有入口 |

`test_api_spec_parity.py` 的关键设计：

- **真值必须取自 OpenAPI schema，不能取 `app.routes`** —— `create_app()`
  单独调用只暴露 8 条路由，v1 的 router 是在 lifespan 里挂的。
  正确姿势是 `with TestClient(create_app()) as c: c.get("/openapi.json")` → 43 条。
- **必须单独校验 §3 总览表**：16 条幽灵端点里**13 条只出现在那张表里**，
  章节标题一条都没写。总览表是读者第一眼看的地方 ——
  只校验章节标题等于**把门修在后院**。
- **反向校验「漏列」**：真实存在的路由不许缺席总览表。漏写比写错更隐蔽 ——
  读者不会去找一个他不知道存在的端点，于是现成功能被重复实现一遍。
- **「未实现」标记双向校验**：标着未实现的必须真的不存在，
  **可用的端点也不许被标成未实现** —— 后者会让人绕开现成功能去重复实现。
- `_normalise()` 把 `{...}` 折叠成 `{}`（所以 `{id}` ≡ `{project_id}`），
  但**保留单复数与段序**，否则 `/project/{id}` 与 `/projects/{id}`、
  `/{id}/trigger` 与 `/trigger/{id}` 这两类真实存在过的错就查不出来了。

### 撞到一道「假门」：永远不会被触发的规则

解析总览表时要跳过 §3.1（那一整节列的就是**不存在**的路径，收进来断言必红）。
写了跳过逻辑、13 条断言全绿 —— 但变异验证时把 `### 3.1` 改成 `### 3.2`，
**预期变红，结果全绿**。

原因：§3.1 当时把方法和路径挤在同一个反引号单元格里（`` `GET /api/v1/audit` ``），
根本匹配不上「方法列 + 路径列」的表格正则，所以那段跳过逻辑**从未执行过**。
改成与 §3 同布局后，规则才真正生效，改标题的变异也立刻红了 3 条。

**一条永不执行的规则等于没有规则，而它看起来和生效的规则一模一样。**
这与本仓反复栽的「描述规则的文本 vs 遵守规则的代码」是同一类问题 ——
只有变异验证能把这种「看着有、其实没有」的门抓出来。

### 解析器必须"找不到就吵"

一个静默返回空集合的解析器，会让它下游**所有**断言假通过 —— 比没有测试更糟，
因为它给人一种被保护的错觉。每个 helper 在无匹配时显式 assert，
且各套件都有专门的解析器自检测试。

### 每一条都做过变异验证

不会失败的测试不是测试。逐条植入错误、确认只有对应断言变红、再字节级还原
（`git diff --stat` 无输出）：

```
FARM 阈值改 70            → 阈值断言红
删 wash-trading VC 标签   → 覆盖断言红
把 anonymous team 判为正向 → 符号断言红
删组合页 breakeven 标签   → 覆盖断言红
BATCH_LIMIT 50 → 100     → 上限断言红
把 deadline 加回通知类型  → 幽灵类型断言红
删 import 中文名          → 来源覆盖断言红
把 manual 加回来          → 幽灵来源断言红
拿掉 @computed_field      → dump 断言 + 字段断言红（2 项）
删 farming_cost 字段      → 3 项红
删回放兼容 validator      → 回放断言红
删历史行补算              → 补算断言红
补算不检查分数是数字      → 造假断言红
给历史行硬塞 farming_cost → 不补算断言红
把硬编码来源清单加回来    → 清单断言红
把 apiFetch 路径改坏      → 调用断言红
stageZh 里塞回 growth     → 词汇混用断言红
stageZh 删 testnet        → 部署阶段覆盖断言红
lifecycleStageZh 删 mature → 生命周期覆盖断言红
timingZh 塞回不可达 growth → 死条目断言红
详情页改回跨口径兜底      → 跨口径断言红
STATE_ZH 删 BLOCKED       → 状态覆盖断言红
STATE_ZH 加不存在的 PAUSED → 幽灵状态断言红
删 ineligible 选项        → 选项覆盖断言红
给存活判定加 pending      → 后端会 422 的选项断言红
§6 路径改回单数 project   → 路径存在性断言红
§21 触发路径动词在前      → 路径存在性断言红
§31b 动词改回 PUT         → 动词断言红
§30b 关注改回顶层 POST    → 动词断言红
撤掉 §11 的「未实现」标记 → 路径存在性断言红
给已实现的 §8 贴「未实现」→ 反向谎言断言红
§15 改回 /api/version     → 路径存在性断言红
§27 编号改回 21（制造重号）→ 编号唯一断言红
总览表 projects 写成单数    → 路径存在 + 漏列 + 解析自检断言红（3 项）
总览表 funding 动词写成 PUT → 总览动词断言红
总览表漏写 action-queue     → 漏列断言红
改掉 §3.1 小标题            → 幽灵路径混入，3 项红（这一条最初全绿 → 查出假门）
API_SPEC 加回二型豁免清单 → 清单为空断言红（+ 清单一致性断言红）
往 API_SPEC 注入 1 处二型损坏 → check_encoding 退出码 1
删掉徽章 medium 分支        → 档位覆盖 + 观感区分断言红（2 项）
medium 复用 high 的红色     → 观感区分断言红
flags 兜底改回编造标记      → 编造兜底断言红
路由放宽到也返回 low        → 档位覆盖断言红（前端缺分支）
路由过滤不存在的 critical   → 档位覆盖断言红（反向自检）
新增一个孤儿组件            → 孤儿断言红
导航 href 少一个字母        → 目标存在 + 可达 + 解析自检断言红（3 项）
新增一个侧栏没入口的页面    → 可达断言红
```

一共 48 次变异，每次只红对应断言，全部字节级还原
（`git diff --numstat` 复核内容差异，不看行尾）。

### 又一次「注释让断言假通过」——这次是反向

新写的断言「`无公开仓库` 不许出现在 `insights/page.tsx` 里」**第一次就红了**，
但红的原因不是代码里还留着那个编造标记 ——
是**我在代码上方的注释里解释了「不要写这个标记」**。

这就是同一个坑的反面：正向时（术语检查、`/collections/sources` 那次）
注释让本该报警的断言假通过；反向时注释让本该通过的断言误报。
根因一样：**字符串匹配分不清「描述规则的文本」和「遵守规则的代码」**。

对策：凡是"某个字面量不许出现"这类断言，先用 `_strip_comments()` 剥掉
`//` 与 `/* */` 再匹配，并给剥注释函数本身加自检
（既要剥掉两种注释，也要确认代码本体没被误剥 —— 否则断言会永远通过）。

## 这轮新踩的坑

- **`mypy app --config-file ..\pyproject.toml` 会报 371 个假错**。
  CI 是 `working-directory: backend` + `--config-file pyproject.toml`。
  用错路径会得到一份完全误导的报告 —— 正确调用是
  `Success: no issues found in 117 source files`。
- **写测试时先踩了自己一脚**：`TestNoHardcodedSourceList` 最初只断言源码里
  出现过 `/collections/sources` 字符串 —— 而文件顶部的**说明注释里也写着这个
  路径**，把真正的调用改坏测试照样绿。改成匹配 `apiFetch<...>('...')` 的实际
  调用才抓得住。**描述规则的文本和遵守规则的代码长得一模一样**，这个坑本仓
  已经出现过多次（术语检查、编码检查都栽过），必须用运行时构造违规样本来验。
- **`extra="forbid"` 与 `computed_field` 天然冲突**：dump 里带着 computed 字段，
  再喂回构造器就被当成非法额外字段 —— 任何从 `team_json` 回放的导入/重算路径
  都会硬失败。每加一个 computed_field 都要补 `mode="before"` 的丢弃 validator，
  并用测试验证这条回路（`TokenomicsResult.risk` 早先就是这么处理的，属于同因同治）。
- **`Literal[...] | None` 的 `get_args` 返回 `(Literal[...], NoneType)`**，
  不是字符串元组。不解包会得到空集合 → 断言假通过。解包后必须再断言非空。
- **Python 文件里的中文 docstring 用 ASCII 双引号会撞外层 `"""`** →
  报 `Perhaps you forgot a comma?`。全部改用 `「」`。
- **写新测试文件后 `ruff format --check` 必挂**（`1 file would be reformatted`）
  → 提交前先 `ruff format app tests` 再 check。
- **删 UI 代码后 eslint 报未使用的 lucide 图标** → 顺手删 import。
- **`node --test <file>` 报 `spawn EPERM`**（每个文件一个子进程）→
  用 `test.mjs` 在同进程内 `await import()`，且**显式列出文件**
  （自动扫描会藏起"写了但没跑"的失败）。
- **JSDoc 注释里写 cron 字面量**，其中的 `*/` 会提前终止注释 →
  `tsc` 报一串 TS1109/TS1005。注释里用文字描述 cron。
- 自罚两条（都已清理）：
  - **打印 `dir(settings)` 把整个 `Settings(...)` repr 连 8 个密钥一起 dump 出来**。
    以后绝不枚举 `settings` 属性、绝不打印该对象，只用 `bool(settings.x)`。
  - **探接口时往生产库写了 3 行**（`POST /import/projects`），其中 2 行是我造的，
    已删除（290 → 288）。探写接口前先想清楚它会不会落库。
- **别拿本地 `data/airdrop.db` 当真值**。差点在这儿报错数：那个文件里
  `projects` 只有 94 行、`stage` 分布也不一样；真正在用的库要问
  `settings.db_path`（本机解析成 `D:\app\data\app.db`，288 行）。
  **量数据前先确认自己连的是哪一个库** —— 两个库都存在、都能打开、都不报错。
- **变异脚本还原后 `git status` 仍显示 `M`**：脚本用 `newline=""` 写回，
  换行变成 LF，而仓库工作区是 CRLF。内容一致但字节不同。
  判据用 `git diff --numstat`（空输出 = 规范化后无差异），
  确认后 `git checkout -- <file>` 恢复行尾。**"字节一致"要按仓库的行尾口径判，
  不是按脚本读到的字符串判。**
- **`write` 工具不能凭空创建刚被删掉的路径**（报 `file no longer exists`）。
  写一次性脚本的稳妥流程：`New-Item -ItemType File` → `read` → `write` → 跑 → 删。
- **变异脚本第一行就该断言基线干净**（如 `assert "SOURCE_OPTIONS" not in src`）。
  上一次变异没还原干净时，后面每一轮"变异 → 红"都会红得毫无意义 ——
  我确实撞上过一次全红，一度以为测试写错了。
- **绝不对带未提交改动的文件跑 `git checkout -- <file>`**。这轮真的把
  `docs/API_SPEC.md` 一次进行中的重写整段抹了：变异脚本还原后
  `git diff --numstat` 显示 `366 193`，我按上一条经验判成"行尾差异"就
  `git checkout --` 了，结果那 366 行**正是我自己写的正文**，§3/§6/§7/§10/§11/
  §15/§17–§21 全部回退成损坏原文，只能重做一遍。
  **修正上一条的判据**：`--numstat` 非零**不一定**是行尾 —— 行尾差异的表现是
  `--numstat` **为空**而 `git status` 仍显示 `M`。反过来推是错的。
- **探写接口第二次栽同一个坑**：`POST /collections/{source_id}/trigger`
  文档写「202 排队」，我以为只是入队，实际它**同步打了 etherscan 并落库**
  （2 行 raw + 4 行 signals + 1 行 log）。已全部删净还原到
  raw 693 / projects 288 / signals 2261 / logs 20。
  **文档说的状态码不能当行为依据** —— 这次恰恰是在修那份文档的谎言时被它骗的。
- **`app.routes` 拿不到 v1 路由**（只有 8 条基础设施路由）：router 是在
  lifespan 里挂的。要真值必须
  `with TestClient(create_app()) as c: c.get("/openapi.json")` → 43 条 `/api/v1`。
- **`ruff` 的 SIM300（Yoda condition）会拦 `x == set()`** → 改写成 `not x`。
  测试文件写完先 `ruff format` 再 `ruff check`，两道都要跑。
- **`ruff format` 改过文件后 `edit` 工具会拒绝**（`file changed since it was read`）
  → 重新 `read` 该区域再 `edit`。

