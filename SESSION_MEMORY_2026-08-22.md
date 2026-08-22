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

1. **master 分支保护有 3 个必过检查名对不上，任何 PR 恒为 BLOCKED**
   —— 要求 `Lint (ruff)` / `Test (pytest)` / `Coverage Gate`，
   而仓库里实际 job 名是 `Lint & Format Check` / `Full Backend Test Suite`，
   覆盖率门禁在 pytest 步骤内部、不是独立 job。这 3 项永远 pending。
   **下个会话先请所有者定夺**：改保护规则名 vs 改 job 名。未擅自改动，
   因为改分支保护属于放宽门禁
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

11 项检查**全部 pass**（含 `Full Backend Test Suite` 7m34s、
`Docker Build Check` 含 `/health` 冒烟、`Docker Image Trivy Scan`）。
`mergeStateStatus` 仍是 `BLOCKED`，唯一原因就是上面那 3 个不存在的检查名。

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

