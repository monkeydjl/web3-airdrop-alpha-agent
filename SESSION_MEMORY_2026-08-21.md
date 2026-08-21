# 2026-08-21

## 本次做了什么

上一轮（08-20）修完上线阻断项后，我给出了功能建议。用户选了优先级 1 和 2：**打通「行动 → 复盘 → 校准」闭环**。

### 先更正了我自己上一轮的判断

我上一轮说「要加两个功能」，实测后发现**这个说法不准确**：参与清单、结果反馈、校准状态**后端全都已存在**（`participation_tasks.py` 424 行 + `POST /feedback` + `GET /calibration/status`，实测都能用）。真正缺的是另外三件事，都是实测发现的。

### 缺口一（地基）：参与清单的信号全部读不到

**这是本次最关键的发现。** 扩展信号（`has_testnet` / `has_task_portal` / `explicit_airdrop_mention` 等 27 个）存在 `projects.meta.signals` 里，而 `projects` 表**没有这些列**。`generate_participation_tasks()` 直接读顶层键 → 281 个项目的信号判断**恒为 False** → 全部落进「无信号」兜底分支。

实测：最高分项目（Scroll zkEVM, 83 分）也只拿到 5 条与项目无关的通用任务。

修复：新增 `signals_view()` 展平 `meta.signals` 再传入。实测同样 6 个项目产出 **11 种**不同任务组合，单项目任务数从恒定 5 条变为 **5~15 条**。

> **教训**：原有单测传的是**扁平 dict**，所以这个 bug 长期潜伏且测试全绿。补了按真实存储形态断言的回归用例。以后写服务层测试，夹具必须复刻真实存储结构。

### 缺口二：没有跨项目的「今天该做什么」

参与清单此前只在单个项目详情页存在，162 个 FARM 必须逐个点进去。新增 `GET /api/v1/action-queue` 聚合 + 工作台卡片。

两个设计决定：
- **轮转取样**：纯按分数排时 5 个名额只覆盖 3 个项目（实测），改为每项目先出 1 条再回头补第 2 条，5 个名额覆盖 5 个项目
- **只出推进类任务**（official/testnet/mainnet/research/risk/dev）：track/social 每个项目都有，会把清单刷满

完成状态**复用 `interactions` 表**（用户选的方案），不新建状态表。

### 缺口三：校准门禁 200 条，而录入成本让它不可能达到

实测 `feedback` 表 0 条、`samples_needed=199`，校准能力永久空转。新增 `/review` 页 + `POST /feedback/batch` + `GET /feedback/pending-review`：每行三个按钮，选完批量提交。**没有动门禁阈值**，降的是录入成本。

## 自己发现并修掉的 P0（安全）

`POST /feedback/batch` 与既有 `POST /feedback` 一样只需匿名 token。我做穿透测试时发现：**缺少项目存在性校验，一次请求注入 200 条伪造 ID（`ghost-0..199`）就能让 `calibration_ready` 变 True** —— 等于用凭空数据决定真实评分权重。

修复：未知 `project_id` 整批拒绝（404），批量上限从 200 收紧到 50（填满门禁至少需 4 次请求）。前端改为自动分批。

## 独立评审发现的问题（前端 subagent）

**`--brand` CSS 变量从未定义** —— `globals.css` 有 10 处 `rgb(var(--brand))`（5 处是既有代码），但 `:root`/`.dark` 里没这个变量。Tailwind 的 `brand` token 只作用于工具类，不产生 CSS 自定义属性。解析成 `rgb(undefined)` 后颜色被静默丢弃：**结果按钮选中态、进度条填充、hover 边框全都不显示**。按 `--accent` 同值补上，顺带修好 5 处既有失效样式。

评审还指出两处我确实做错的：
- 界面写「整批在同一事务内提交，不会出现部分成功」，但前端是**循环分批**发送，跨批次不原子。已改为如实表述，并修掉「第 2 批失败后重试会重复提交第 1 批」的真实 bug
- `ActionQueue` 的错误只经可选 `onDone` 回调上报，调用方不传时点击失败毫无反馈。已加组件内兜底提示

## 最终验证（全部实跑）

```
pytest -q                    → 2490 passed, 4 skipped, 0 failed（32分55秒，exit 0）
覆盖率                        → 87.85%（门槛 80%）
ruff check / format          → All checks passed / 241 files unchanged
mypy app                     → no issues in 114 source files
前端 tsc / eslint / build     → 全通过，eslint 0 problems，Compiled successfully
端到端 5 步闭环                → 建议 → 标记 → 从清单消失 → 排进待标记 → 校准推进
```

新增测试：`tests/test_action_queue.py`（14）、`tests/api/test_action_and_review.py`（20）、`test_participation_tasks.py` 补 4 个。

## 决定

- **复用 `interactions` 表**而非新建 `action_items`（用户选择）：标记「已做」= 一条交互记录，参与复盘页能看到同一份数据
- **不动校准门禁 200 和评分权重**：那是 ADR-006 / WEIGHT_CALIBRATION 管的，改了历史评分不可比。只降录入成本
- **复用 `generate_participation_tasks()`** 而非重写任务规则：单一事实来源
- **`action-queue` 打分不复用评分决策引擎的权重**：项目价值与「今天该做哪一步」是两回事，混用会让两边都难解释。用线性可解释打分（优先级权重 + 标签 + 分数×0.15 + 必做 + 收藏 − 已参与）
- **批量上限选 50 而非 200**：与门禁同量级会让单次请求填满门禁

## 遗留/风险

- **未 git commit**：本次改动全在工作区。加上上一轮的 6 个 commit，共 13 个本地 commit 未推远程
- **`action-queue` 无缓存**：每次请求解析 60 个项目的 meta JSON 并逐个生成清单。当前数据量（288 项目）下响应正常，项目数上万时需要加缓存或收窄候选池
- **`user_id` 过滤不一致**：`action-queue` 用 `user_id = ? OR user_id IS NULL`，而 `pending-review` 查 `interactions` 时完全没有用户过滤。单用户 MVP 无影响，启用多用户（`ENABLE_USER_SYSTEM`）前必须统一
- **跨批次非原子**：勾选 > 50 条时分多批，批次内原子、跨批次不保证。界面已如实说明
- 上一轮的遗留仍在：Docker 依赖未锁版本、`/archive` 与 `/ops` 部分区块仍无后端接口

## 相关

- 变更记录：`CHANGELOG.md`（本日 4 节：Added / Security / Fixed×2）
- 上一轮审查：`CODE_REVIEW_REPORT.md`、`GO_LIVE_AUDIT_REPORT.md`
- 交接：`HANDOFF.md`
