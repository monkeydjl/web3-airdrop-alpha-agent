# HANDOFF — 2026-08-21

## 项目当前状态

多智能体 Web3 空投评分系统（后端 FastAPI + 前端 Next.js 16）。
**08-20 修完上线阻断项；08-21 打通「行动 → 复盘 → 校准」闭环、锁定依赖版本、
发现并部分修复文档编码损坏。**

```
pytest -q（全量）        → 2524 passed, 4 skipped, 87.86% cov, 35m10s, exit 0
ruff check               → All checks passed!
ruff format --check      → 245 files already formatted
mypy app                 → no issues found in 115 source files
前端 tsc / eslint / build → 全通过
干净 venv 装依赖          → 41 包装成，/health 200，/metrics 200
```

**30 个本地 commit 未推远程**（`git rev-list --count origin/master..HEAD` 实测）。
远程是 `github.com/monkeydjl/web3-airdrop-alpha-agent.git`，分支 `master`。
**推送方式未获所有者确认**（直推 master vs 开分支走 PR），因此一直没推 —— 这是
下一个会话最该先问清楚的一件事。

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
已修 **646 处（58%）**，全部可证明；**剩 470 处刻意留白**等语义判定。

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

### 一型：470 处待人工判定

| 文件 | 待判定 | 说明 |
|---|---:|---|
| `docs/DATA_SOURCE_STRATEGY.md` | 350 | **最难**：所有历史版本都已损坏，无干净底本 |
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

### 一条待改进项：推断规则不够稳

上下文推断规则最初在 5 个文档上量出 100%，扩到全仓 140 个文档后箭头规则只有
**92.2%**、括号 99.6%、句号 99.4%。本次输出因与底本交叉验证（105 处可核对、
冲突 0）而未受影响，但规则本身应按 `docs/ENCODING_REPAIR.md` §4 的实测表收紧，
或干脆退回人工选择题。

**继续这件事时必须守住的一条**：只填能证明的。候选集外的答案会被机械拒绝，
拿不准就留空。写一个看起来通顺的错字，比留一个显眼的占位符坏得多 ——
读者无法分辨哪句是原文、哪句是机器编的，整份文档从此不可信。

我试过把这批判定分片交给 subagent 并行做，**四次都异常退出、没留下结果**
（三次分片判定 + 一次独立评审），所以目前仍是零进展。若要再试，
建议单个前台跑、每片不超过 30 条。

## 下一步（按优先级）

- [ ] **问所有者：怎么推这 30 个 commit**（直推 master 还是开分支走 PR）
- [ ] **决定 Python 版本口径**：`docker/Dockerfile` 与 CI 用 **3.12**、mypy 配置
      也写 3.12，但本地 venv 是 **3.11.9**，`pyproject.toml` 只声明 `>=3.11`。
      **本地测过的解释器和镜像里跑的不是同一个。** 统一到 3.12 需要重建本地
      venv 并重跑全套（约 35 分钟），或把镜像降到 3.11。我没擅自改。
- [ ] **继续编码修复**（见上）：一型 470 处 + 二型 70 处 + 三型 2 处
- [ ] **上线前人工设定**：`.env` 里 `APP_ENV=production`、`API_KEY`（≥32）、
      `AUTH_TOKEN_SECRET`（≥48）、`CORS_ORIGINS`（**真实域名，含 localhost 会
      拒绝启动**）、`SEED_FALLBACK_ENABLED=false`
- [ ] **确认调度器怎么跑**：数据已过期（最新 `updated_at` 08-18，最后采集 08-15），
      因为 APScheduler 只在服务常驻时才跑。上线要么保证长驻，要么加外部定时
- [ ] **重跑一次 docker 构建**：上一轮（08-20）验证过容器 `Up (healthy)`，
      但之后改了 `Dockerfile` 的 COPY 行与 requirements 拆分，**新镜像未实测**
- [ ] **可选补后端接口**：归档运行历史（`app/archive.py` 有逻辑无路由）、
      调度任务手动触发、项目排名。补上后 `/archive`、`/ops` 可从"诚实占位"升级

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
2. **编码损坏三批待处理**（见上）：一型 470 处待判定
   （`DATA_SOURCE_STRATEGY.md` 无底本可依）、二型 70 处只能人工重写、
   三型 2 处手工补 emoji 即可
3. **上下文推断规则大样本下不是 100%**（箭头 92.2%），待收紧
4. **Python 版本口径不一致**（3.12 镜像/CI/mypy vs 3.11.9 本地 venv），
   待所有者决定 —— 本地跑通 2500+ 测试的解释器与生产镜像里的不是同一个
5. **OTel 依赖未锁版本**（本机 PyPI 不可达，凭记忆锁版本会伪装成"已验证"）。
   降级路径已补 18 个测试（覆盖率 44% → 58%）；
   **正向路径（真装 OTel 能上报）仍未验证**
6. **数据已过期**（最新 08-18），调度器只在服务常驻时跑
7. **`SEED_FALLBACK_ENABLED` 默认 true** —— 生产建议关掉。开着时采集全挂会用
   8 个内置种子项目填充（标记 `source='seed'`、前端显示「种子数据」，用户可
   分辨，但会计入 Dashboard 汇总）
8. **`/archive` 与 `/ops` 部分区块无后端接口** —— 诚实占位，非假数据，但不完整
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

## 我在这几轮里更正过自己五次

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

---

_交接日期：2026-08-21 · 会话记忆见 `SESSION_MEMORY_2026-08-21.md` ·
编码专题见 `docs/ENCODING_REPAIR.md` · 阶段进度见 `docs/PHASES.md`_
