# HANDOFF — 2026-08-22

## 项目当前状态

多智能体 Web3 空投评分系统（后端 FastAPI + 前端 Next.js 16）。
**08-20 修完上线阻断项；08-21 打通「行动 → 复盘 → 校准」闭环、锁定依赖版本、
发现并部分修复文档编码损坏；08-22 收紧编码修复的箭头规则、落地归档子系统
（并查出归档从未真正运行过）、把 41 个积压 commit 推上远程分支并开 PR #4，
顺带查清并修掉三处长期红着的 CI 检查。**

```
pytest -q（全量，本地）   → 2648 passed, 4 skipped, 88.15% cov, 36m31s, exit 0
ruff check               → All checks passed!
ruff format --check      → 251 files already formatted
mypy app                 → no issues found in 117 source files
前端 tsc / eslint         → 全通过（tsc exit 0、eslint exit 0）
check_encoding.py        → exit 0（489 文件，5 个已登记损坏）
check_terminology.py --all → exit 0
```

**PR #4 与 #5 均已于 2026-08-22 合入 master，远程全绿。**
远程是 `github.com/monkeydjl/web3-airdrop-alpha-agent.git`，当前 master = `05741b3`。

| PR | 合并 commit | 内容 |
|---|---|---|
| #4 | `d1b710b` | 46 个 commit、283 个文件：归档子系统、编码修复、门禁修复、上线修复 |
| #5 | `05741b3` | Trivy job 的 `security-events: write` 权限 + 触发器修复 |

合并 #4 前 12 项检查全绿（`Full Backend Test Suite` 2648 passed、
`Coverage Gate` 88.21%、`Docker Build Check` 含 `/health` 冒烟、
`Docker Image Trivy Scan` 0 HIGH、`npm audit` 0 vulnerabilities、
`Check Markdown Links` 0 死链）。
dependabot PR #3 已关闭（其 nanoid 修复已 cherry-pick 进 #4，保留原作者）。

**master 最终状态（`05741b3` 实测）**：`CI` / `Security Scan` / `Docs Link Check`
三个 workflow **全部 success —— 2026-08-09 以来第一次全绿**。

合并 #4 时又露出一个此前被掩盖的故障：`Docker Image Trivy Scan` 在 master 上
仍然红着，但 Trivy 扫描本身 success（0 漏洞），是 `Upload Trivy results` 报
`Resource not accessible by integration` —— 仓库默认 workflow 令牌权限是 `read`，
而 `upload-sarif` 需要 `security-events: write`。PR #5 只在这一个 job 上补了权限
（**不动仓库默认值**），并把 push 路径过滤加上 `security.yml` 自己 + 加
`workflow_dispatch`（否则改这个 workflow 根本触发不了它、验证不了）。
**已实测生效**：`05741b3` 上 `Upload Trivy results` success，
且 `code-scanning/analyses` 里第一次出现 `ref=refs/heads/master` 的记录
（此前所有记录都只有 `refs/pull/*`，正是「只在 PR 事件下能上传」的直接证据）。

分支保护的检查名错配已修（所有者选了「改保护规则名对齐实际 job 名」）：
- `Lint (ruff)` → `Lint & Format Check`、`Test (pytest)` → `Full Backend Test Suite`（纯改名）
- `Coverage Gate` 不是改名能解决的 —— 它需要一个真实存在的 job。
  新增 `coverage-gate`（不重跑测试，只下载 `coverage.xml` 独立断言行覆盖率）。
  选「让名字真实存在」而非「从必过列表删掉它」：后者是放宽门禁，前者不是
- 改保护时逐项比对了改前改后（服务器回读）：只有 5 个检查名变化，
  其余保护项（`strict` / `enforce_admins` / 强推 / 删除 / 评审 / 推送限制等）
  全部保持原值；必过检查数量 5 → 5 未减少，且改后每个名字都对应真实 job。
  原始配置已存为回滚点

> 门禁现在是真的生效了，所以 PR #5 那两个 commit 也走了 PR、没有直推 ——
> 刚把门修成真的，不该由我第一个绕过去。

## 08-22 做了什么

### 1. 归档子系统落地 —— 起因是一句"诚实占位"

`/archive` 页此前写着「暂无运行历史接口」。去查"为什么没接口"，结果发现
**归档功能从来没有生效过**，以及两个会让数据无限增长、一个会提前删数据的缺陷：

- **零调度**：`RawDataArchiver` 逻辑是真的，但全仓只有手动脚本会调它 ——
  `scheduler.py` / CI / compose / Dockerfile 里对 `archive` 零引用，
  而 `DATABASE_DDL.md` §6.1 却写着「每日 cron 执行」。
  现在接入 `UnifiedScheduler`，`ARCHIVE_CRON` 默认 `0 3 * * *`
  （采集 job 在 08:00–10:30，03:00 不争锁）
- **73% 的行永远不会被归档**：`processed` 只在采集记录被提升为正式项目时置 1，
  而提升要求 `discovery_score >= 0.3`。低分记录永远不会被提升 → 永远不满足
  `processed = 1 AND 超期`。实测 693 行里 509 行（73%）是 `processed = 0` 且
  分数全部 < 0.3；184 行 `processed = 1` 全部 ≥ 0.3。这 509 行也没有同
  `dedup_key` 的高分兄弟，佐证逻辑救不回来。估算 1 年约 16.8 万行 / 76 MB。
  新增 `UNPROCESSED_RAW_RETENTION_DAYS`（90 天）单独一档，**归档而非删除**
  —— 它们是复盘"当时为什么没立项"和调阈值做回溯的唯一依据（所有者选的）
- **归档表保留期零实现**：文档写了 180/365 天，代码里搜不到任何按 `archived_at`
  删除的语句 —— 归档表只进不出，等于把无界增长搬了个地方
- **时间戳格式不一致会提前一天删数据**：`archived_at` 走 SQLite
  `DEFAULT CURRENT_TIMESTAMP`（`'2026-08-22 02:08:51'`，空格分隔），其它时间列
  走应用层 `isoformat()`（`'...T02:08:51.9+00:00'`，T 分隔）。SQLite 的
  TIMESTAMP 是 TEXT，`<` 是字符串比较，空格 0x20 < `T` 0x54 → 当天写入的行被判成
  "早于今天零点"。实测保留期设 0 天时刚归档的行**当场被删**。现在两种 cutoff
  分开（`_cutoff` / `_cutoff_db_default`）
- **`days or default` 把显式的 0 吃掉了**：构造函数原写 `raw_retention_days or
  settings.xxx`，于是显式传入的 `0`（合法，意为立刻清理）被换成默认值。
  这一度让上面那条时间戳测试**假通过** —— 改成 `is None` 才复现出真缺陷。
  *这是本轮第二次"测试通过≠功能正确"*

新增：`archive_runs` 表（每次运行一行，含失败）+ `GET /api/v1/archive/runs`
（管理员专属、只读）+ Alembic 迁移 `0003`（可单独回滚到 `0002`）+ `/archive` 页
真实数据（六档策略行数与待清理预估、调度状态、最近 20 次运行）。

### 2. 顺带修正的文档不实之处

`DATABASE_DDL.md` §6.1 的示意 SQL 是
`WHERE discovered_at < datetime('now','-30 days')`，**没有 `processed` 条件**，
看起来"什么都归档"，而实现一直带 `processed = 1`。已改为与实现一致，
并补 §6.2（为什么未处理记录要单独一档，含实测数与增长估算）、
§6.3（时间戳格式陷阱）。

## 08-21 做了什么

### 1. 「行动 → 复盘 → 校准」闭环（用户点的优先级 1+2）

- **修了一个静默已久的地基 bug**：扩展信号存在 `projects.meta.signals` 里，
  而 `projects` 表没有这些列，`generate_participation_tasks()` 直读顶层键 →
  281 个项目的信号判断**恒为 False**，全部落进兜底分支拿同样 5 条通用任务。
  新增 `signals_view()` 展平后，同样 6 个项目产出 **11 种**组合、任务数 5→5~15。
  *旧测试传扁平 dict，所以 bug 长期潜伏且测试全绿。*
- 新增 `GET /api/v1/action-queue` + 工作台「今日行动」卡片（轮转取样，
  5 个名额覆盖 5 个项目而非 3 个）。完成状态复用 `interactions` 表。
- 新增 `POST /feedback/batch` + `/review` 快速标记页 + 校准进度条。
  **没有动 200 条门禁阈值**，降的是录入成本。

### 2. 自己发现并修掉的 P0（校准投毒）

`POST /feedback/batch` 缺项目存在性校验，一次请求塞 200 条伪造 ID
（`ghost-0..199`）就能让 `calibration_ready` 翻 True —— 等于用凭空数据决定
真实评分权重。已实测复现。修复：未知 ID 整批 404，上限 200→50。

### 3. 统一 `user_id` 过滤口径

抽出 `app/services/user_scope.py`。根因是两张表**写入约定本来就不同**：
`POST /interactions` 不传 user_id 落 **NULL**，`POST /watchlist/{id}` 落
**'default'**。所以"统一成严格 `= 'default'`"会引入真实 bug（标记过的项目
第二天又冒出来）。现在默认用户同时认 NULL 与 default，具名用户严格匹配。

### 4. 锁定依赖版本

`requirements.txt` 此前全浮动 `>=`，每次 docker build 都可能装到与本地测过的
不同版本。拆成三个文件：运行时 13 个全部精确 `==`、`requirements-dev.txt`
7 个（不进生产镜像）、`requirements-otel.txt` 可选。
CI 三处散装 `pip install ruff/pytest/mypy` 也改为装锁定文件。

**顺带查出**：7 个 `opentelemetry-*` 被声明为必需，但本机从未安装、
无针对性测试，实测缺包时应用照常启动（降级 no-op tracer）。
**刻意没锁它们的版本** —— 本机无法访问 PyPI，凭记忆写版本号会伪装成"已验证"。

拆成可选依赖后我意识到：**"缺包时能降级"从隐含假设变成了必须守住的契约**
（因为生产镜像现在默认不装它）。补了 18 个测试
（`backend/tests/test_tracing_degraded.py`），最关键的一条是"运维把
`OTEL_ENABLED` 打开了但镜像没装包" —— 此时必须记 warning 继续跑。
`app/tracing.py` 覆盖率 **44% → 58%**。

### 5. 发现文档编码损坏，三型共 1188 处

**一型（非法 UTF-8）1116 处**：3 个文档的中文字符第 3 字节被替换成 `?`。
已定 **629 处（56.4%）**，全部可证明；**剩 487 处刻意留白**等语义判定。
（进度比上一版的 646 低了 17 处 —— 箭头规则收紧后主动退回人工，见下。）

**二型（整字变 `?`）70 处**：`docs/API_SPEC.md`。整个中文字符被替换成一个半角
`?`，文件**仍是合法 UTF-8** —— 一型的检查完全看不见，潜伏了 **6 个提交**。
这一型是我修完一型后主动去找的：起因是想到"会不会还有一种损坏因为合法而看不见"。

**三型（字面 U+FFFD）2 处**：`docs/SYSTEM_DIRECTION_CHANGE.md`，
丢的是两个小节标题的 emoji。同样是合法 UTF-8，前两型的检查都看不见。
**损失可忽略**（装饰图标，不影响语义）。

三型是写完二型检测后再一次主动追问"还有没有第四、第五种形态"才找到的。
**这件事的方法论价值大于它本身**：换判据（字面 U+FFFD / 中文后连续 `??` /
全仓非 md 文本）重扫，才知道"查完了"到底有没有依据。
我在 `docs/ENCODING_REPAIR.md` §6 也写清了"没有再找第四种，但没找到不等于不存在"。

详见 `docs/ENCODING_REPAIR.md`。

## 进行中的工作（唯一未完成品）

**编码损坏还剩三批。** 这是本次唯一没做完的事，且**故意**没做完。

### 一型：487 处待人工判定

| 文件 | 待判定 | 说明 |
|---|---:|---|
| `docs/DATA_SOURCE_STRATEGY.md` | 367 | **最难**：所有历史版本都已损坏，无干净底本 |
| `docs/OPERATIONS.md` | 101 | 有底本，剩下的是底本范围外的新增内容 |
| `docs/OBSERVABILITY.md` | 19 | 同上 |

怎么继续：

```bash
python scripts/repair_utf8_docs.py --worklist   # 导出 docs/_utf8_worklist.json
# 逐条填 "pick" 字段（只能从 "candidates" 里挑）
python scripts/repair_utf8_docs.py --choices docs/_utf8_worklist.json --apply
python scripts/verify_utf8_repair.py docs/OPERATIONS.md docs/OPERATIONS.md.partial
```

清单每条给候选集 + 前后 40 字上下文。全部填完某个文件后，`--apply` 会直接写回
原文件（不再是 `.partial`），此时记得从 `scripts/check_encoding.py` 的
`KNOWN_BROKEN` 里删掉该条目 —— 有个测试专门断言"已修好的文件不该还在清单里"。

### 二型：70 处，只能人工对照底本重写

**不要试图自动修复这一型。** 实测原因：一个 `?` 不总是只吃掉一个字符 ——
逐行对齐底本后，24 处可核对位置里恰好 1 个字符的是 **0 处**、多于 1 个的是
**24 处**（例如一个 `?` 吃掉了 `求/` 两个字符）。既没有候选集约束（候选是全部
汉字），也没有长度约束，所以**无法用逐字节校验证明修复没越界**。

`docs/API_SPEC.md` 的干净底本在 `6823d18`，但那之后文档被大幅改写
（10065 → 26694 字符），不能整体回滚，只能逐段对照。
登记在 `check_encoding.py` 的 `KNOWN_BROKEN_MOJIBAKE` 里。

### 三型：2 处，手工补个 emoji 就行

`docs/SYSTEM_DIRECTION_CHANGE.md` 第 125 行 `## <FFFD> 成功指标（KPI）`、
第 190 行 `## <FFFD>️ 实施路线图（v2.0）`。该文档其余小节标题都带 emoji
（📋 🔄 🎯 🏗️ 📊 ⚠️ 🔗 ✅），所以这两处原本也是 emoji。

**没有底本**（最早版本就已损坏），选哪个图标是猜的 —— 但因为它纯装饰，
猜错也没有信息损失。所以这属于**内容编辑**，随手补即可，
不要写进修复脚本（脚本的原则是"只填能证明的"）。
补完从 `KNOWN_BROKEN_REPLACEMENT` 里删掉条目。

### 箭头规则已收紧（本轮做的，附一条方法论）

上下文推断规则最初在 5 个文档上量出 100%，扩到全仓 140 个文档后箭头规则只有
**92.2%** —— 平均每 13 处写错 1 个字。本轮把它换判据重做了：

从"全仓统计"改成"**本文档证据**"。理由是实测发现全仓分布不可靠
（`→` 92%、`←`/`↓`/`↔`/`↑` 各占几个百分点），但**同一份文档内部用法高度一致**
—— 62 个含箭头的文档里 56 个只用 `→`。加上"整行只有箭头则弃权"
（那是架构图的纵向连接符，`↓` 更常见）后，留一法实测 **582/582 = 100%**。

**这里有个值得记住的负面结果**：我先试了两种"看起来更聪明"的收紧 ——
只在非缩进行填（93.14%）、只在左右紧邻非空白时填（94.92%）—— 几乎没用。
**限缩语法位置涨不上去，换判据的维度才有质变。**

代价：`DATA_SOURCE_STRATEGY.md` 无底本且存活箭头 0 个，17 处箭头全部退回人工，
待定数 470 → **487**，进度 58% → 56.4%。**进度倒退是有意的**，
宁可多留 17 个显眼占位符，也不写 1 个看似通顺的错字。

括号（99.57%）与句号（99.37%）两条还留着，因为错误率在 0.5% 量级、且被底本
交叉验证兜住（105 处可核对、冲突 0）。但它们**不算"已证明"**，
若要机械化处理剩下的 487 处，必须先按同样方式换判据重测。

**继续这件事时必须守住的一条**：只填能证明的。候选集外的答案会被机械拒绝，
拿不准就留空。写一个看起来通顺的错字，比留一个显眼的占位符坏得多 ——
读者无法分辨哪句是原文、哪句是机器编的，整份文档从此不可信。

我试过把这批判定分片交给 subagent 并行做，**七次都异常退出、没留下结果**
（分片判定 + 独立评审都试过），所以目前仍是零进展。
**这个工作区的 subagent 委派不可靠，建议直接前台跑脚本探测。**

## 下一步（按优先级）

- [x] ~~**合并 PR #5**~~ → 已合并（`05741b3`），**已验证** `Upload Trivy results`
      success、`code-scanning/analyses` 首次出现 `refs/heads/master` 记录
- [x] ~~**合并 PR #4**~~ → 已合并（`d1b710b`），dependabot PR #3 已关闭
- [x] ~~**问所有者：分支保护那 3 个对不上的检查名怎么修**~~ → **已修**，
      所有者选了改保护规则名对齐实际 job 名（详见开头）
- [ ] **决定 Python 版本口径**：`docker/Dockerfile` 与 CI 用 **3.12**、mypy 配置
      也写 3.12，但本地 venv 是 **3.11.9**，`pyproject.toml` 只声明 `>=3.11`。
      **本地测过的解释器和镜像里跑的不是同一个。** 统一到 3.12 需要重建本地
      venv 并重跑全套（约 36 分钟），或把镜像降到 3.11。我没擅自改。
      注：CI 的 `Full Backend Test Suite` 是在 3.12 上跑绿的，所以两边都能过测试
- [ ] **继续编码修复**（见上）：一型 487 处 + 二型 70 处 + 三型 2 处
- [ ] **上线前人工设定**：`.env` 里 `APP_ENV=production`、`API_KEY`（≥32）、
      `AUTH_TOKEN_SECRET`（≥48）、`CORS_ORIGINS`（**真实域名，含 localhost 会
      拒绝启动**）、`SEED_FALLBACK_ENABLED=false`
- [ ] **确认调度器怎么跑**：数据已过期（最新 `updated_at` 08-18，最后采集 08-15），
      因为 APScheduler 只在服务常驻时才跑。上线要么保证长驻，要么加外部定时
- [x] ~~**重跑一次 docker 构建**~~ → **08-22 已由 CI 验证**：
      `Docker Build Check` pass（含起容器 + `/health` 冒烟）、
      `Docker Image Trivy Scan` pass（0 HIGH）。本地仍无法构建（daemon `npipe`
      权限被拒），但 CI 覆盖了这一层。⚠ 注意本轮**从镜像里删除了 pip/setuptools**
      （原因见下文 CI 段），所以容器内不能再 `pip install` 排障
- [ ] **可选补后端接口**：调度任务手动触发、项目排名。
      归档运行历史已于 08-22 补齐（`GET /api/v1/archive/runs`），`/archive` 页已实装；
      `/ops` 仍有"诚实占位"区块

## 08-22 后半段：推送与三处 CI 长期红灯

所有者指示「没问题就推 master，影响大就开 PR」，判断权交给我 → 选了开 PR（理由见开头）。
借 CI 把三项长期失败的检查查清并修掉，**它们都先于本次改动存在**：

| 检查 | 修前 | 修后 |
|---|---|---|
| `Docker Image Trivy Scan` | 36 HIGH（08-09 起每次红） | **0** |
| `Frontend Lint & Build`（npm audit） | 9 HIGH（08-13 起红） | **0** |
| `Docs Link Check` | 6 条死链 | **0** |
| 分支保护必过检查 | 5 个里 3 个是假名字 | **5 个全部对应真实 job** |

**Trivy 那项的教训：一个只报「失败」不报「为什么」的门禁，等于没有门禁。**
它红了 13 天，因为 workflow 只让 Trivy 输出 SARIF 到文件 —— 失败时日志只剩
`exit code 1`，SARIF 上传成功却 code scanning 告警数为 0，run 里也没有构件。
先加一步 table 格式输出（非阻断，判定仍归 SARIF），漏洞才第一次露面。

- 34 个来自基础镜像 util-linux 家族（9 包 × 4 CVE：CVE-2026-53612/53613/53614/53615）。
  `python:3.12-slim` 的 tag 不随 Debian 安全更新重新指向新层 → 构建时
  `apt-get upgrade`，36 → 2
- **剩下 2 个差点被我修错**（详见「我更正过自己」一节新增的第 8 条）：
  真来源是 `pip/_vendor/vendor.txt`，不是任何已安装的包。
  改为删除 pip/setuptools，**builder 与 production 两阶段都要删** ——
  只删一处没用，production 会 `COPY --from=builder /venv /venv` 把同一份 pip 搬过去。
  删除前已实测：用 `sys.meta_path` 拦截器让 pip/setuptools/pkg_resources/
  `_distutils_hack` 全部无法导入，应用仍完整启动（28 条路由）、`/health` 200 healthy

**npm audit 那项**：9 个高危全源自 `nanoid < 3.3.18` 经 postcss 传染。
修法是 **cherry-pick dependabot PR #3 的原始 commit**（`16e4763`），
不是自己写版本号 —— 本机 npm registry 不可达（`EPERM`），编不出可信的
`integrity` 哈希。

### 第四项：分支保护的检查名错配（所有者决定后修）

这一项和上面三项性质不同 —— 不是某个检查红了，而是**门禁本身是假的**：
`master` 要求 5 个必过检查，其中 3 个名字在仓库里没有任何 job 会产出，
于是永远 pending，任何 PR 恒为 `BLOCKED`。看着 5 道门，实际只有 2 道生效。

所有者选了「改保护规则名对齐实际 job 名」。执行时发现三项里有一项**不能靠改名解决**：

- `Lint (ruff)` → `Lint & Format Check`、`Test (pytest)` → `Full Backend Test Suite`
  是纯改名
- **`Coverage Gate` 需要一个真实存在的 job**。覆盖率门槛此前只以
  `--cov-fail-under=80` 参数藏在测试步骤内部 —— 闸门是真的、名字是假的，
  而分支保护匹配的正是名字。新增 `coverage-gate` job：不重跑测试（那要 7 分半），
  只下载测试阶段已上传的 `coverage.xml` 独立断言行覆盖率。
  这不是与 `--cov-fail-under` 重复劳动：命令行里的阈值被谁调低都不会有提示，
  而这是一道名字可见、能独立失败的闸门。
  **选「让名字真实存在」而非「从必过列表删掉它」—— 后者是放宽门禁，前者不是。**

**闸门先被验证过能失败**，因为不会失败的覆盖率闸门比没有闸门更糟。
人造边界样本六个全部符合预期：恰好 80.00% 放行（边界不得误拒）、79.99% 拦、
79.00% 拦、缺 `line-rate` 属性拦（不得静默当成通过）、0% 拦、100% 放行。
浮点比较用 `pct + 1e-9 < THRESHOLD` 以免二进制误差把真正的 80.0% 判成不及格。
CI 实跑：**88.21%（10493/11896 行）通过**。

**改保护时逐项比对了改前改后**（服务器回读，不是复述请求）：只有 `contexts`
里 5 个名字变化；`strict` / `enforce_admins` / 强推 / 删除 / 评审 / 推送限制 /
线性历史 / 会话解决 / `block_creations` / `lock_branch` 全部保持原值。
必过检查数量 5 → 5 未减少，且改后 5 个名字**每一个都对应真实 job**。
原始配置已存为回滚点。

结果：PR #4 `BLOCKED` → **`CLEAN`**，12 项检查全绿。

## 如何运行与验证

### 启动

```bash
# 后端（注意：必须用 venv 的 python，venv 是 3.11.9，系统 python 是 3.14.6）
cd backend && .\venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8002

# 前端（另开终端）
cd frontend-next && npm install && npm run dev   # http://localhost:3002

# Windows 一键
Start.bat

# Docker
docker compose up -d --build
```

本地跑用 `.env` 里 `APP_ENV=development`（已设好，localhost 可用）。

### 验证（08-21 实际跑过的命令）

```bash
cd backend
.\venv\Scripts\python.exe -m pytest -q                          # 2524 passed, 4 skipped
.\venv\Scripts\python.exe -m ruff check app tests scripts alembic
.\venv\Scripts\python.exe -m ruff format --check app tests scripts alembic
.\venv\Scripts\python.exe -m mypy app --config-file pyproject.toml

cd ..
python scripts/check_encoding.py        # 编码闸门（已挂 pre-commit）
python scripts/check_terminology.py --all

cd frontend-next
npm run typecheck && npm run lint && npm run build
```

> ⚠️ **五个环境陷阱**（都实际踩过）
> 1. `ruff format --check .`（带点跑全仓）在 ruff 0.16.1 会 **panic**。
>    必须按目录跑 `app tests scripts alembic`。
> 2. 全量 pytest 约 **34 分钟**，不要以为卡住了。放后台跑。
> 3. **必须用 `venv\Scripts\python.exe`** —— 系统 python 是 3.14.6，装不上依赖。
> 4. 跑任何输出中文的脚本前设 `$env:PYTHONUTF8="1"`，否则 GBK 编码报错。
>    pip 安装也一样（不设会 `UnicodeDecodeError: 'gbk' codec`）。
> 5. `data/pytest_tmp/`、`.pytest_cache` 等目录偶发文件锁 → 会让 `glob`/`grep`
>    全仓搜索报 `os error 5`，改用 `Get-ChildItem`/`Select-String` 或搜子目录。
> 6. 写 git commit message 用 `[System.IO.File]::WriteAllText` + `UTF8Encoding $false`
>    写到 `.git/CMSG.txt` 再 `git commit --file=` —— 直接 `-m` 会让 BOM 混进标题。

## 已知问题 / 风险

1. **30 个 commit 未推远程**，推送方式待确认
2. **编码损坏三批待处理**（见上）：一型 487 处待判定
   （`DATA_SOURCE_STRATEGY.md` 无底本可依）、二型 70 处只能人工重写、
   三型 2 处手工补 emoji 即可
3. **括号与句号两条推断规则仍不是 100%**（99.57% / 99.37%）；
   箭头那条本轮已换判据收紧到留一法 100%
4. **Python 版本口径不一致**（3.12 镜像/CI/mypy vs 3.11.9 本地 venv），
   待所有者决定 —— 本地跑通 2500+ 测试的解释器与生产镜像里的不是同一个
5. **OTel 依赖未锁版本**（本机 PyPI 不可达，凭记忆锁版本会伪装成"已验证"）。
   降级路径已补 18 个测试（覆盖率 44% → 58%）；
   **正向路径（真装 OTel 能上报）仍未验证**
6. **数据已过期**（最新 08-18），调度器只在服务常驻时跑
7. **`SEED_FALLBACK_ENABLED` 默认 true** —— 生产建议关掉。开着时采集全挂会用
   8 个内置种子项目填充（标记 `source='seed'`、前端显示「种子数据」，用户可
   分辨，但会计入 Dashboard 汇总）
8. ~~**`/archive` 与 `/ops` 部分区块无后端接口**~~ → `/archive` **已接真实数据**
   （08-22）。查这句占位时发现它掩盖的是三个真缺陷（归档零调度、73% 低分记录
   无界增长、归档表保留期零实现），详见「08-22 做了什么」。`/ops` 仍有占位区块
9. **跨批次非原子**：`/review` 勾选 > 50 条时分多批，批次内原子、跨批次不保证。
   界面已如实说明
10. **信号覆盖严重不均**：`token_listed` 268 个项目有、`tvl` 165、
    `github_activity` 只有 30、etherscan `chain_activity` 只有 **4**。
    这意味着 `execution` 维度（占 13% 权重）**基本靠猜**，
    置信度 ≥0.8 的只有 9 个项目。上线前值得让所有者知道这一点
11. **新镜像未实测**：上一轮（08-20）验证过容器 `Up (healthy)`，
    但之后改了 `Dockerfile` 的 COPY 行与 requirements 拆分，没重跑构建

## 关键决定（及理由）

- **复用 `interactions` 表**而非新建 `action_items`（所有者选择）：
  标记「已做」= 一条交互记录，参与复盘页看到同一份数据
- **不动校准门禁 200 与评分权重**：那是 ADR-006 / WEIGHT_CALIBRATION 管的，
  改了历史评分不可比。只降录入成本
- **`action-queue` 打分不复用评分决策引擎权重**：项目价值与「今天该做哪一步」
  是两回事，混用会让两边都难解释
- **刻意不给 action-queue 加缓存**：实测中位数 26ms 且耗时与库内项目数无关
  （候选池固定 60）。缓存会引入失效时机问题（标记"已做"需立刻反映），
  收益只有几毫秒。*我一开始把"无缓存"列为风险，实测后推翻了自己*
- **编码修复只填能证明的**：底本对齐 / 语料唯一 / 结构规则三条路径之外一律留白
- **二型损坏只检测不修复**：它连"1 字符换 1 字符"都不成立，自动修复无法被
  逐字节校验证伪 —— 与其做个证明不了对错的修复，不如先把它标出来
- **不凭记忆锁 OTel 版本**：PyPI 不可达 → 无从验证 → 写死会伪装成"已验证"
- **低分采集记录归档而不是删除**（所有者选择）：它们是复盘"当时为什么没立项"、
  以及日后调 `discovery_score` 阈值做回溯验证的唯一依据，删了拿不回来
- **归档 cron 定在 03:00**（所有者选择）：采集 job 集中在 08:00–10:30，
  03:00 跑完不与写入争锁
- **`/api/v1/archive` 收进管理员专属**：响应含各表真实行数与保留期/cron 配置，
  属运维信息，与 `/settings` 同一口径。前端 `/archive` 走服务端注入密钥的代理，
  不影响页面可用性
- **归档历史端点严格只读**：查看历史不触发清理（有测试锁住）。
  手动触发只保留脚本入口，避免"点一下就删数据"的按钮

## 我在这几轮里更正过自己九次

留档是为了让接手的人知道哪些结论是被推翻过的、不要照着旧结论走：

1. 说「action-queue 无缓存是风险」→ 实测 26ms 且与数据量无关，**不该加缓存**
2. 凭记忆把 mypy 锁成 1.18.2 → 实测本机是 **2.3.0**，改正
3. 说编码修复的第一轮对齐"逻辑没问题只是命中率低" → 查出两个真实原因
   （占位符本身对不上底本要看邻居、CRLF vs LF 把 difflib 块打碎），
   修完命中从 0 涨到 432
4. 说上下文推断规则"都量过准确率、只留 100% 的" → 那是 **5 个文档的小样本**。
   扩到 140 个文档后箭头规则只有 92.2%。**小样本给了虚假的安全感**
5. 说 `app/tracing.py`「零测试覆盖」→ 实测靠其它测试导入 `app.main` 已有
   **44%** 间接覆盖。准确说法是"没有针对性测试、关键契约从未被断言"
6. 说箭头规则"已量化但待收紧" → 本轮**已收紧**（换判据到留一法 100%），
   并如实披露待定数从 470 涨到 487 这个**进度回退**
7. 归档的时间戳格式 bug **第一次验证时没能复现**，我差点据此认为它不存在。
   真实原因是构造函数的 `days or default` 把我传的 `0` 吃掉了 —— 那个"反例
   跑不出来"的结论本身是错的。修掉 `or` 之后 bug 立刻复现。
   *教训：验证失败时，先怀疑验证装置*
8. Trivy 剩下 2 个高危，我的第一反应是「升级 setuptools」，
   **那是个看起来合理但不可能生效的修法**：镜像里 setuptools 已经是 84.0.0
   （Trivy 自己列出 `setuptools-84.0.0.dist-info` 且 0 漏洞），它报的 70.3.0
   另有来源。我先按这个错判提交了一版 `pip install --upgrade setuptools`，
   结果 36 → 2 之后**一个也没少**。加 JSON 诊断打出 `PkgPath = None`、
   target 名叫 `Python` 而非文件路径，才定位到真来源是 `pip/_vendor/vendor.txt`
   （pip 把依赖以源码内嵌、不产生 dist-info，Trivy 把这份清单当包列表读）。
   本机 pip 已是最新 26.2.1，vendor.txt 仍钉着这两个旧版 —— 任何 pip 升级都
   不可能修掉。*教训：报告自相矛盾时，先怀疑取数口径，别急着改代码*
9. 我一度以为 Trivy 的 table 输出没能打出表格（日志里搜不到），
   实际是 **GitHub Actions 的 job 日志是 UTF-16LE 带 BOM**，用 UTF-8 解码得到
   空字符串。按前两字节嗅探 `raw[:2] in (b'\xff\xfe', b'\xfe\xff')` 才读得到。
   *教训：读不到内容时，先确认编码，再断言"没有内容"*
10. 我说过「`Docker Image Trivy Scan` 红 13 天是因为 36 个高危」，
    还说「SARIF 上传成功但 code scanning 告警数为 0」——**两句都只对一半**。
    合并 PR #4 触发 push 后这个 job 仍然红，但 `Run Trivy scan` 是 success、
    `Upload Trivy results` 才是 failure（`Resource not accessible by integration`，
    仓库默认令牌权限是 `read` 而 `upload-sarif` 需要 `security-events: write`）。
    **一个 job 里叠着两个独立故障**，漏洞那个把权限那个挡住了 ——
    Trivy 先 exit 1，上传成不成功轮不到显现。逐步骤走完 08-09 以来每次 master
    运行才看清：上传**从第一天起就在所有非 PR 运行里失败**。
    我观察到的「告警数为 0」正是它的直接后果，我却把它当成 SARIF 机制的怪癖。
    *教训：一个 job 的红灯不等于一个故障 —— 修好前面那个，后面那个才会露出来。
    所以「修好了」必须在修完之后再看一次实际结果，不能在推之前靠推理下结论*

CHANGELOG、`docs/PHASES.md`、`docs/ENCODING_REPAIR.md` 里都保留了
"原判断 + 更正"两条，没有抹掉痕迹。

## 本轮补的两道闸门（都是"检查本身坏了"）

顺手发现两处**质量闸门自己有问题**，共同点是：它们本该拦别人，却没人拦它们。

1. **术语闸门实跑失败**：`check_terminology.py --all` 3 个文件 5 处命中，
   而这个脚本**自己没有任何测试**。5 处里 3 处是不该改的（定义禁用词清单本身、
   引用历史 commit message）—— 说明缺的是"这里必须写出禁用词"的表达手段。
   加了行级豁免（逐行显式、可 grep 审计、不做整文件豁免）+ 27 个测试，
   并把 `--all` 结果固化成测试（此前只有 pre-commit 守，`--no-verify` 就绕过）。
2. **编码检查有盲区**：写完二型检测后追问"还有没有别的形态"，
   换判据扫出**三型**（字面 U+FFFD，2 处）。

**共同教训**：检查工具的盲区，就是问题的藏身处。而"我已经查完了"这个判断，
本身需要有依据 —— 换判据重扫、让工具检查自己、把结论固化成测试。
本轮有三条测试就是干这个的：检查脚本必须过自己的检查、
测试文件必须过闸门、全仓不得有未登记损坏。

**08-22 又加一例**：`Docker Image Trivy Scan` 红了 13 天，但它只报「失败」不报
「为什么」—— SARIF 写进文件，日志只剩 `exit code 1`。同一个模式：
闸门存在、但它的输出无法被人读取，于是等于不存在。修法是让它先打印再判定。

**08-22 第三例，最彻底的一种**：`master` 分支保护的 5 个必过检查里，
**3 个名字根本没有对应的 job**。这不是闸门坏了，是闸门**从来不存在** ——
它们永远 pending，把所有 PR 一律判为 `BLOCKED`。
表面上比别人严（要 5 道），实际只有 2 道生效，而且这个错配把
dependabot PR #3 卡了整 5 天没人发现原因。
其中 `Coverage Gate` 尤其典型：**门槛是真的（`--cov-fail-under=80` 一直在跑），
但名字是假的**，而分支保护匹配的是名字 —— 一个真实生效的检查，
因为没有名字，在门禁体系里等于不存在。

**统一起来的教训**：闸门的「存在」有三个独立条件 —— 它得**跑**、
它的结果得**能被读到**、它还得有个**别人引用得上的名字**。
缺任何一条，它对使用者就是不存在的，而且从外面看不出来。

## 本环境的操作陷阱（省下重新踩的时间）

- **`git push` 的可行姿势**：默认 schannel 报 `SEC_E_NO_CREDENTIALS`；
  换 `-c http.sslBackend=openssl` 后凭据助手是 shell 脚本包装
  （`!'...gh.exe' auth git-credential`），沙箱不能开命名管道 →
  `sh.exe: couldn't create signal pipe, Win32 error 5`。
  可行解是 **Basic 认证头**（Bearer 不行，GitHub 的 git-http 认 Basic）：
  ```powershell
  $b64 = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes("x-access-token:" + (gh auth token)))
  git -c http.sslBackend=openssl -c credential.helper= -c "http.extraHeader=Authorization: Basic $b64" push origin <branch>
  ```
- **`gh run view --log-failed` 会失败**（`Access is denied`，缓存目录在
  `%LOCALAPPDATA%` 沙箱外）→ 改用
  `gh api repos/<owner>/<repo>/actions/jobs/<id>/logs > 工作区内文件`
- **GitHub Actions 日志与 `npm audit --json` 都是 UTF-16LE 带 BOM**，
  用 UTF-8 解码会得到空串。按前两字节嗅探再解码
- **subagent 委派在本工作区不可靠**（试过七次全部异常退出、无结果）→ 前台跑脚本

---

_交接日期：2026-08-22 · 会话记忆见 `SESSION_MEMORY_2026-08-22.md` ·
编码专题见 `docs/ENCODING_REPAIR.md` · 阶段进度见 `docs/PHASES.md`_
