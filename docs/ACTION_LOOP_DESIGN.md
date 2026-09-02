# 执行闭环设计 —— 决策推送 · 参与流水 · 收益台账 · 领取监控

> 引用：[ADR-012](adr/ADR-012-system-direction-auto-scan.md)（自动扫描方向）、
> [ADR-008](adr/ADR-008-user-system.md)（匿名 token / 用户体系）、
> [ADR-005](adr/ADR-005-apscheduler-inprocess.md)（进程内调度）、
> [WEIGHT_CALIBRATION.md](WEIGHT_CALIBRATION.md)、[SECURITY.md](SECURITY.md) §10、
> [OBSERVABILITY.md](OBSERVABILITY.md)、[OPERATIONS.md](OPERATIONS.md)
> 阶段：V3（**设计稿，未实现** —— 除各节「现状」小节外，本文描述的能力当前都不存在）
> 更新：2026-08-30
> 术语：遵循 [GLOSSARY.md](GLOSSARY.md)；本稿新增的 5 个术语已收编进 GLOSSARY §1（标注「设计稿」）。
> 任务拆解格式沿用 [V2_TASKS.md](V2_TASKS.md)（现状 / 产出物 / 验收），见 §5。

---

## 0. 为什么是这四件事

2026-08-30 全项目审核 + 功能盘点结论：系统的「发现 → 评分决策引擎打分 → 三档分类」链路已经完整
（14 个采集器、`score-v1.4`、FARM/WATCH/IGNORE），但产出之后断在两处：

1. **决策只存在于站内**。`notifications.py` 聚合了三类站内通知（new_project / score 变化 /
   collector 失败），已读状态存 `notification_reads` —— 但没有任何出站通道，用户必须主动开面板。
2. **执行与回收无记录**。`GET /projects/{id}/participation-tasks` 只是无状态的「建议生成器」，
   前端勾选存 localStorage（换设备即丢）；反馈只有 `useful / useless / wrong_label / correct_outcome`
   四档主观信号，权重校准（有效样本 ≥200 / FARM ≥30 门槛）学不到「最终有没有领到钱」。

四个子系统补的正是这后半段闭环：

| 子系统 | 补的缺口 | 一句话 |
|---|---|---|
| F1 决策推送 | 决策送不出去 | 把 FARM/WATCH 变化与每日摘要推到 Telegram / Discord |
| F2 参与流水 | 做了什么没记录 | 服务端任务状态机，替代 localStorage |
| F3 收益台账与历史回测 | 模型学不到真值 | 投入/产出结构化，回测引导校准样本 |
| F4 领取监控 | 到账不知道 | 监控自己的钱包地址，疑似空投到账即提醒 |

**依赖与实施顺序：F1 → F2 → F3 → F4**（F1 独立；F2 独立；F3 弱依赖 F2 的投入记录；F4 依赖 F1 的推送通道）。

```
采集器(14) → 评分决策引擎(score-v1.4) → 三档分类
                                          │
              ┌───────────────────────────┤
              ▼                           ▼
        F1 决策推送                  F2 参与流水
   (Telegram/Discord 出站)      (任务状态机,替 localStorage)
              │                           │
              │      ┌────────────────────┘
              ▼      ▼
        F4 领取监控            F3 收益台账 + 历史回测
   (自己的钱包到账→推送)  ──→  (投入/产出 → 校准真值 → 权重)
```

---

## 1. 术语（已收编 GLOSSARY §1）

| 术语 | 英文 | 定义 |
|---|---|---|
| 决策推送 | Outbound Notifier | 把系统内的评分决策变化与每日摘要经出站通道（Telegram / Discord Webhook）推送给用户的子系统 |
| 参与流水 | Participation Tracker | 记录用户对每个项目「做到哪一步」的服务端任务状态机，替代前端的 localStorage 勾选 |
| 收益台账 | ROI Ledger | 按项目记录参与投入（gas / 基础设施 / 时间）与产出（空投到账 / 未领取）的结构化账本 |
| 历史回测 | Backtest | 把已知历史空投项目在「发币前 T0」时刻的公开数据灌入评分决策引擎，检验当年是否会给出 FARM |
| 领取监控 | Claim Watch | 对用户登记的自有钱包地址做链上事件匹配，疑似空投到账时经 F1 推送提醒 |

---

## 2. F1 决策推送（Outbound Notifier）

### 2.1 现状

- ✅ `routers/v1/notifications.py`：三类站内通知（new_project / score / collector），已读存
  `notification_reads`（按 `user_id` 隔离）。
- ✅ 统一调度器（ADR-005）：cron + `misfire_grace_time=3600` + `max_instances=1`，加一个 job 即可。
- ✅ 出站 HTTP 统一走 `utils/fetcher.py::fetch()`，域名白名单 fail-closed（SECURITY §10.3）。
- ❌ 无任何出站通知通道；`api.telegram.org` 不在白名单（`discord.com` 已在 —— 采集器 bot API 用）。

### 2.2 目标 / 非目标

**目标**：四类事件经可配置通道出站；发送有日志、有去重、有指标；凭证入脱敏。
**非目标**：不做每用户偏好路由（单 owner 假设，所有推送发同一目的地）；不做移动端推送（APNs/FCM）；
不做 HTML 富文本（纯文本 + 链接）。

### 2.3 事件模型

| event_type | 触发时机 | 去重键（event_key） | 说明 |
|---|---|---|---|
| `daily_digest` | cron（`NOTIFY_DIGEST_CRON`，默认 `0 9 * * *` UTC） | `digest:{YYYY-MM-DD}` | 今日新增 FARM/WATCH 数、最高分项目、watchlist 变化汇总 |
| `score_crossing` | 每轮 `run` 落库后评估 | `cross:{project_id}:{up|down}:{YYYY-MM-DD}` | 上穿 65 → FARM 提醒；下穿 50 → 降级提醒；同项目同方向每天最多一条 |
| `new_farm` | 同上 | `new_farm:{project_id}` | 与站内通知 new_project 同源，首次入库且 label=FARM |
| `watchlist_signal` | 采集落库后评估 | `signal:{project_id}:{signal_type}:{date}` | watchlist 项目出现新融资 / 测试网上线等强信号 |

评估器实现为纯函数（输入：本轮落库结果 + 上一轮快照 + watchlist 集合，输出：待发事件列表），
单独可测；调度器 job 与 `run` 的收尾钩子都只调它。

### 2.4 通道与出站安全

- `app/notify/` 新模块：`Sender` 协议（`async send(title: str, body: str) -> None`），
  实现 `TelegramSender`（Bot API `sendMessage`）、`DiscordWebhookSender`（webhook URL POST）。
- **必须经 `fetcher.fetch(method="POST")` 发出** —— 域名白名单对这条新出口自动生效。
  SECURITY §10.2 表新增 `api.telegram.org`（Discord Webhook 复用已在表的 `discord.com`）。
- 凭证脱敏：`redact.py::_SECRET_ATTRS` 增加 `telegram_bot_token`、`discord_notify_webhook_url`
  （后者 URL 路径本身含 secret，整串脱敏）。
- **内容边界**：推送正文只含 `name / score / label / url`，**不含** `raw_data` 全文与采集原文 ——
  外发面最小化，避免把未脱敏的采集内容送出站。

### 2.5 数据模型

```sql
CREATE TABLE IF NOT EXISTS notify_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,   -- PG: SERIAL
    event_type  TEXT NOT NULL,
    event_key   TEXT NOT NULL,
    channel     TEXT NOT NULL,                       -- telegram / discord_webhook
    title       TEXT NOT NULL,
    body        TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending',     -- pending/sent/failed
    attempts    INTEGER NOT NULL DEFAULT 0,
    last_error  TEXT,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP, -- PG: TIMESTAMPTZ
    sent_at     TIMESTAMP,                           -- PG: TIMESTAMPTZ
    UNIQUE (event_key, channel)
);
CREATE INDEX IF NOT EXISTS idx_notify_log_status ON notify_log(status, created_at);
```

发送器带重试（≤3 次，指数退避），3 次后置 `failed` 不再自动重发 —— 与采集器的熔断心态一致：
通知是尽力而为，不是事务承诺。

### 2.6 配置（全部需同步 `.env.example`，值 = 代码默认）

| 键 | 默认 | 说明 |
|---|---|---|
| `NOTIFY_ENABLED` | `false` | 总开关；false 时评估器照跑（写 notify_log）但不发送 |
| `NOTIFY_CHANNEL` | `telegram` | `telegram` / `discord_webhook` |
| `TELEGRAM_BOT_TOKEN` | 空 | Bot Father 签发 |
| `TELEGRAM_CHAT_ID` | 空 | 目标 chat |
| `DISCORD_NOTIFY_WEBHOOK_URL` | 空 | 频道 Webhook URL |
| `NOTIFY_DIGEST_CRON` | `0 9 * * *` | 每日摘要（UTC） |
| `NOTIFY_MAX_PER_RUN` | `20` | 单轮推送条数上限，防事件风暴 |

### 2.7 API（envelope 对齐 `{ok, data}`）

| 方法 | 路径 | 鉴权 | 说明 |
|---|---|---|---|
| POST | `/api/v1/notify/test` | **管理员** | 发一条测试消息 |
| GET | `/api/v1/notify/status` | 管理员 | 通道配置布尔回显（不回显凭证） |
| GET | `/api/v1/notify/log` | 管理员 | 发送历史（分页） |

### 2.8 指标与日志

- 指标：`airdrop_notify_sent_total{channel}`、`airdrop_notify_failure_total{channel}`、
  `airdrop_notify_event_evaluated_total{event_type}` —— 真实埋点在 Sender 与评估器里，
  同步 OPERATIONS §12.1 幽灵清单核对（不许出现「注册了但不调用」）。
- 日志事件（**字面量在调用点**，OBSERVABILITY parity 门禁静态扫描）：
  `notify.digest_started` / `notify.sent` / `notify.send_failed` / `notify.event_suppressed`。
  同步登记进 OBSERVABILITY.md。

### 2.9 测试计划

- 评估器：纯函数单元测试（上穿/下穿、同日去重、上限截断、watchlist 信号）。
- 发送器：respx mock Telegram / Discord 响应（200 / 429 / 500），重试与 failed 落库。
- 门禁 parity：`.env.example` / OPERATIONS（job 表 + 门控）/ SECURITY §10.2 / OBSERVABILITY 四份同步，
  CI 全红不了才算完。

### 2.10 工作量

**1.5–2 天**（评估器 + 两通道 + 测试 + 五处文档同步）。

---

## 3. F2 参与流水（Participation Tracker）

### 3.1 现状

- ✅ `GET /projects/{id}/participation-tasks`：按 `signals_view` 生成**建议清单**（无状态、无持久化）。
- ❌ 前端 `ParticipationTasks.tsx` 勾选存 localStorage（`aa-task-done:<id>`），换设备即丢，
  且与后端状态无法区分。
- ❌ 无任何参与状态表。

### 3.2 目标 / 非目标

**目标**：服务端任务状态机；生成的建议清单可一键导入为可跟踪任务；按 `user_id` 隔离
（与 watchlist / feedback 同模式，匿名 token 可写）。
**非目标**：不做多人协作/共享；不做任务自动执行（见 §8 红线）。

### 3.3 数据模型

```sql
CREATE TABLE IF NOT EXISTS participation_plans (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,   -- PG: SERIAL
    user_id     TEXT NOT NULL,
    project_id  TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'active',      -- active/paused/completed/abandoned
    note        TEXT,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP, -- PG: TIMESTAMPTZ
    updated_at  TIMESTAMP,                           -- PG: TIMESTAMPTZ
    UNIQUE (user_id, project_id)
);

CREATE TABLE IF NOT EXISTS participation_tasks (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,  -- PG: SERIAL
    plan_id      INTEGER NOT NULL REFERENCES participation_plans(id) ON DELETE CASCADE,
    title        TEXT NOT NULL,
    kind         TEXT NOT NULL DEFAULT 'other',      -- testnet/quest/bridge/swap/social/kyc/other
    status       TEXT NOT NULL DEFAULT 'todo',       -- todo/doing/done/skipped
    url          TEXT,
    due_at       TIMESTAMP,                          -- PG: TIMESTAMPTZ
    note         TEXT,
    completed_at TIMESTAMP,                          -- PG: TIMESTAMPTZ
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_participation_tasks_plan ON participation_tasks(plan_id, status);
```

> `due_at` 到期提醒复用 F1：评估器新增 `task_due` 事件（due 前 24h），event_key =
> `task_due:{task_id}:{date}`。

### 3.4 API

| 方法 | 路径 | 鉴权 | 说明 |
|---|---|---|---|
| POST | `/api/v1/projects/{id}/participation` | 匿名 token | 建 plan；`seed_from_generated=true` 时把建议清单导入为任务 |
| GET | `/api/v1/participation` | 匿名 token | 我的全部 plan（含任务），按 status 过滤 |
| PATCH | `/api/v1/participation/tasks/{task_id}` | 匿名 token | 改 status / note / due_at（校验 plan 归属当前 user_id） |
| DELETE | `/api/v1/participation/{plan_id}` | 匿名 token | 删 plan（级联删任务） |

**鉴权分类**：三个写端点匿名可写 —— 与 feedback 同一设计意图（参与记录本来就要让普通使用者写）。
API_SPEC §2.1 的 write-auth-split 计数会变，**合并前重算该块**（块有再生成的注释标记，按标记走）。

### 3.5 前端

- `ParticipationTasks.tsx`：勾选改走 PATCH；首次检测到本地 `aa-task-done:*` 记录时提示一次性迁移，
  迁移完删除本地键。
- 项目详情页加「参与状态」入口（active/paused/… 状态切换）。

### 3.6 测试计划

- API 集成：建/改/删 + `seed_from_generated`；**跨 user_id 读不到别人的 plan**（正反断言都要，
  这是 watchlist 隔离测试的同款写法）。
- 状态机：非法迁移（completed → doing）拒绝。
- 门禁：API_SPEC 章节新增 + write-auth-split 重算。

### 3.7 工作量

**2 天**。

---

## 4. F3 收益台账与历史回测（ROI Ledger + Backtest）

### 4.1 现状

- ✅ `feedback.signal ∈ {useful, useless, wrong_label, correct_outcome}`（`outcome` 为自由文本）。
- ✅ 权重校准闭环（`weight_changelog`、`app/calibration.py`），门槛 **有效样本 ≥200 / FARM ≥30**
  有测试钉死（`test_calibration.py::test_gate_constants_not_lowered`，**不许调低**，owner 拍板）。
- ✅ 前端 portfolio 页（只读）。
- ❌ 投入与产出没有结构化记录；校准学不到「实际回报」。

### 4.2 数据模型

```sql
CREATE TABLE IF NOT EXISTS roi_entries (          -- 投入
    id          INTEGER PRIMARY KEY AUTOINCREMENT, -- PG: SERIAL
    user_id     TEXT NOT NULL,
    project_id  TEXT NOT NULL,
    kind        TEXT NOT NULL,                     -- gas/infra/time/other
    amount_usd  REAL,
    hours       REAL,
    note        TEXT,
    recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP  -- PG: TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS roi_outcomes (         -- 产出
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     TEXT NOT NULL,
    project_id  TEXT NOT NULL,
    event       TEXT NOT NULL,   -- token_launched/airdrop_received/airdrop_missed/campaign_ended
    amount_usd  REAL,            -- 领到时的估值,人工录入
    tokens      REAL,
    tx_hash     TEXT,
    source      TEXT NOT NULL DEFAULT 'manual',    -- manual/backtest
    recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**诚实边界**：`amount_usd` 以人工录入为准，MVP 不做链上自动取价（代币价格源是另一个工程，
不塞进本期）。`tx_hash` 只作凭证存档，不自动验证。

### 4.3 校准对接（本节是 F3 的核心价值）

- 派生真值：`airdrop_received` → 正样本；`airdrop_missed` → 负样本。
- 校准样本来源新增 `source` 列：`live | backtest`。**两类样本分开统计、分开计算门槛**，
  不混算 —— 回测样本是历史分布，live 是当前分布。
- 门槛 200/30 **不变**（测试钉着）；回测的价值是让「有效样本」不用苦等几个月自然积累。

### 4.4 历史回测

- 数据：`backend/data/backtest/airdrops_2024_2025.json`，目标 ~50 个已知项目。每条：
  `name / sector / funding(T0 前) / signals(T0 时刻可得的公开信号) / outcome(实际是否空投 + 量级)`。
  T0 = 发币公告日。**只收 T0 前公开可得的信息** —— 用 T0 后的信息构造样本是自欺。
- 执行器：`backend/scripts/run_backtest.py` —— 每个项目构造 `RawProject`，走**规则引擎**路径
  （LLM 关闭，ADR-001 口径）评分，输出：FARM 命中率、分数分布、按八维的失分归因。
- 报告形态对齐 `opportunity/calibration/report.py` 的既有输出风格，结果可导出为
  `source=backtest` 的校准样本。

### 4.5 API 与前端

| 方法 | 路径 | 鉴权 |
|---|---|---|
| POST / GET | `/api/v1/projects/{id}/roi` | 匿名 token（user_id 隔离） |
| GET | `/api/v1/roi/summary` | 匿名 token（总投入/总产出/ROI） |

前端：portfolio 页加 ROI 列与录入表单。

### 4.6 测试计划

- 录入/隔离/聚合集成测试；`source=live|backtest` 分桶统计的单元测试。
- 回测执行器对种子数据的确定性输出（金标准式断言，进 `tests/golden/`）。
- 校准门槛常量测试确认未被改动。

### 4.7 工作量

**3–4 天** + 回测数据集整理 1 天（一次性数据工程，可并行）。

---

## 5. F4 领取监控（Claim Watch）

### 5.1 现状

- ✅ `POST /webhook/alchemy`：HMAC-SHA256 签名校验（fail-closed，签名密钥为独立的
  `ALCHEMY_WEBHOOK_SIGNING_KEY`），事件作为 RawDiscovery 入库。
- ❌ 事件里分不清「别人的合约」和「我的钱包」；没有自有钱包概念。

### 5.2 目标 / 非目标

**目标**：登记自有地址（admin-only）；webhook 命中自有地址时生成站内通知 + F1 推送
「疑似空投到账」。
**非目标**：不做金额确权（只提示，人工确认）；不自动维护 Alchemy 控制台的地址清单
（MVP 在 Alchemy Notify 控制台手工挂地址，Notify API 自动同步留作后续）。

### 5.3 数据模型与判定

```sql
CREATE TABLE IF NOT EXISTS watched_wallets (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,      -- PG: SERIAL
    address  TEXT NOT NULL UNIQUE,                   -- 小写归一
    label    TEXT NOT NULL,
    chain    TEXT NOT NULL DEFAULT 'ethereum',
    active   INTEGER NOT NULL DEFAULT 1
);
```

- webhook 处理器在**签名校验通过后**增加匹配：`event` 的 from/to ∈ active watched 地址。
- 命中且 `category=erc20`、`asset ≠ ETH` → `airdrop_candidate` 事件 → 站内通知 + F1 推送。
  启发式只做提示，不承诺语义。

### 5.4 安全

- `/api/v1/watched-wallets` **整前缀管理员锁**（钱包地址是资金隐私，匿名角色不可见不可写）。
- 通知内容只含 `label + 地址前 10 位`，不回显完整地址。

### 5.5 工作量

**1.5 天**。

---

## 6. 里程碑与任务拆解（现状 / 产出物 / 验收）

> 图例：现状 ✅ 已有 / 🟡 部分 / ❌ 缺失。每项完成后在 V2_TASKS 同款格式上勾销。

### M1 = F1 + F2

#### T1.1 notify 模块骨架 + 评估器
- **现状**：❌。**产出物**：`app/notify/`（Sender 协议、评估器纯函数）、`notify_log` 表
  （db.py 双方言 DDL + alembic `0005_notify_log.py` + DATABASE_DDL.md）。
- **验收**：评估器单元测试全绿；建表迁移 upgrade/downgrade 通过。

#### T1.2 Telegram / Discord 发送器 + fetcher 接入
- **现状**：🟡（fetcher 可用，白名单缺 `api.telegram.org`）。
- **产出物**：两个 Sender、重试与 failed 落库、SECURITY §10.2 增行、redact 增两键。
- **验收**：respx 测试覆盖 200/429/500；表外域名被 `DomainNotAllowedError` 拒绝。

#### T1.3 调度 job + API + 配置 + 指标
- **现状**：❌。**产出物**：digest cron job、`/notify/*` 三端点、7 个 env 键（`.env.example`
  parity）、3 个指标 + 4 个日志事件（OBSERVABILITY 登记）。
- **验收**：`NOTIFY_ENABLED=true` 本地实测收到测试消息；幽灵清单核对通过。

#### T2.1 participation 表 + API
- **现状**：❌（建议生成器已有）。**产出物**：两张表（DDL ×2 + alembic）+ 4 端点 +
  API_SPEC 章节与 write-auth-split 重算。
- **验收**：跨 user_id 隔离正反测试；非法状态迁移拒绝。

#### T2.2 前端接线 + localStorage 迁移
- **现状**：🟡（组件在，走本地存储）。**产出物**：`ParticipationTasks.tsx` 改服务端 +
  一次性迁移提示。
- **验收**：换浏览器勾选状态保持；`npm run typecheck/build` 绿。

### M2 = F3

#### T3.1 roi 两表 + API + portfolio 接线
- **现状**：✅ 已完成（`09c7c6c` 后端 / `ade9544` 前端）。**产出物**：`roi_entries` /
  `roi_outcomes`（db.py 双方言 DDL + alembic `0007_roi.py` + DATABASE_DDL §2.9d）、
  **6 端点**（设计写 5，实施时拆出 summary 与 by-project 两个读端点）、
  `RoiLedger.tsx` 挂 `/portfolio`。
- **验收**：✅ `tests/api/test_roi.py` 21 passed（含跨 token 隔离正反断言、请求体自报
  user_id 被忽略、summary 与手工核算逐项比对）；write-auth-split 双向门禁 44 passed
  （写端点 26→30、匿名 16→20 与 API_SPEC §2.1 对齐）。
- **实施记录**：`amount_usd` / `hours` 至少给一个（否则 422 `MISSING_AMOUNT`）；
  零成本时 `roi_ratio` 返回 `null` 而非 `0`（会被读成"没赚没赔"）或 `inf`（污染下游聚合）。

#### T3.2 校准 source 分桶 + 回测执行器 + 数据集
- **现状**：✅ 代码完成（`b641c91`），**数据集 15/50 条**。**产出物**：`CalibrationSample.source`
  + `count_by_source()` + `GateResult.total_by_source`、`scripts/run_backtest.py`、
  `backend/data/backtest/airdrops_2024_2025.json`。
- **验收**：✅ `tests/test_backtest.py` 21 passed —— golden 断言（知名空投不得判 IGNORE、
  召回率 ≥0.7）、门槛 200/30 未动、分桶统计正确，并含关键断言
  **「灌 500 条 backtest 样本门禁仍不通过」**。
- **偏差（须补全）**：数据集 **19 条**（15 正 / 4 负 + 原有 1 负 = 5 负），仍未达设计
  要求 ≥50，标 `pending_expansion=true` / `target_size=50`，报告会自动打警告。
  负样本已补到 5 条、覆盖三类（迟迟不发币 / 明确不做代币激励 / 已发币无追加分配），
  `fpr` 分母够了、选择偏差警告已熄灭。

#### ✅ 回测发现的引擎缺陷（已由 ADR-015 修复，2026-09-01）

> **状态**：已修复。修复方案与实测结果见本节末「修复结果」。以下保留原始
> 缺陷记录，因为它解释了为什么修复必须动模型结构而不是权重取值。

**已发币项目仍被判 FARM。** Chainlink 68 分、Worldcoin 69 分，越过 FARM 阈值 65。

`airdrop_signal` 这一维**已经正确压到 20 分**（`no_token_yet=false` 信号生效了），
但加权求和模型下压不住其余七维：`execution` 100、`competition` 100、
`transparency` 100、`team_reputation` 85~95 把总分抬了起来。

根因是模型结构，不是权重取值：对本系统而言「**已发币 = 没有空投机会**」
应当是**否决条件**（veto），而不是可被其他维度补偿的一项打分。一个各方面都
优秀的成熟项目，在"还能不能 farm"这个问题上应当直接出局。

修复要改评分结构（引入 veto 或对 `airdrop_signal` 设下限门），会牵动
`WEIGHT_CALIBRATION` 协议，因此**不在 M2 范围内做**。

> **2026-09-01 补充**：已立项为 **[ADR-015](adr/ADR-015-eligibility-gate-before-scoring.md)
> 机会资格前置门**（Accepted，已实现）。
>
> ADR 阶段又跑了一次带子分的完整探查，结论比这里记的更严重：
> **19 个样本全部判 FARM，fpr = 100%**（不只是已发币那两例）。按 ADR-006 §4
> 的目标函数 `recall − 2×fpr` 代入 = `1.00 − 2×1.00 = −1.00` —— 现模型在
> 自己的校准目标函数下是负分。
>
> 另在探查中查清 `narrative_timing` 全样本恒 60 的根因：**回测数据集的
> sector 写法（`zk-rollup`/`l2`）与 `SECTOR_PROFILE` 键名（`ZK`/`L2`）
> 完全不匹配，19 个样本全部落到 `DEFAULT_PROFILE`**。这是数据集保真度问题
> 而非引擎缺陷，但顺带暴露一个生产隐患：该查表大小写敏感且未命中时**静默**
> 走默认档，真实采集数据写法不同就会让 0.20 权重白扔。详见 ADR-015
> §「本 ADR 不解决什么」第 3 条。

曾用 `@pytest.mark.xfail(strict=True)` 在
`tests/test_backtest.py::test_known_engine_gap_already_launched_still_farm`
钉住：修好后该条会变 XPASS 并报错，逼人回来删标记 —— 缺陷修复不能静默发生。
**该机制按设计生效了**：ADR-015 落地后这条立刻 XPASS 报错，于是删除 xfail
并改写为正向断言 `test_already_launched_projects_are_vetoed_from_farm`
（断言两个已发币样本 label ≠ FARM 且 `veto == "already_launched"`）。
配套的 `test_already_launched_projects_get_low_airdrop_signal` 断言子分侧
（≤30）持续有效，保证信号本身不退化。

#### 修复结果（2026-09-01 实测）

资格门插在 `_score_to_label()` 之后、`_apply_confidence_degradation()` 之前，
**只改 label 不改 score**。同批修正了数据集 sector 写法。

| 指标 | 修复前 | 修复后 |
| --- | --- | --- |
| recall(FARM) | 1.000 | 0.929 |
| fpr(FARM) | 1.000 | 0.400 |
| 目标函数 `recall − 2×fpr` | **−1.00** | **+0.129** |
| label 分布 | `{FARM: 19}` | `{FARM: 15, WATCH: 2, IGNORE: 2}` |
| veto 分布 | — | `{already_launched: 2, no_participation_path: 2}` |

Chainlink / Worldcoin 的 `score` **仍是 68 / 69**（否决不改分），label 降为
IGNORE 并带 `veto=already_launched`；日志 `scorer.veto_applied` 记
`original_label` / `final_label`，靠它能区分「分数低」与「被规则否决」。

sector 归一化后 `narrative_timing` 不再恒 60（Manta 93.5 / Linea 90.2 /
Taiko 90.2 / Chainlink 84.0），0.15 权重恢复作用。

**仍未闭合**：`veto_false_negatives = 1` —— Jupiter 实际发过大额空投，却被
`no_participation_path` 误否决（它的参与路径是历史交易行为，三个信号字段都
表达不了）。降级只到 WATCH 所以机会仍可见，recall 的全部损失来自这一条。
处置方式待 owner 拍板，见 ADR-015 §「实施结果」。
`competition` 大面积 100 的**分组口径部分已修**（2026-09-02）：原来按 sector
原始写法分组，同一赛道的多种写法（`Dexes` / `DEX` / `dex` / `Derivatives`）
被拆成多组、每组计数偏小，`n <= 3` 满分档命中率虚高，方向是系统性偏乐观。
改为按 `canonical_sector_key()` 规范键分组（计数侧与查表侧同口径），实测
12 个 DEX 项目从「7 组 / 75~100 分」收敛为「1 组 / 55 分」。
`COMPETITION_MAP` 分段是否过宽属权重校准范畴，仍未处理。
Farcaster 需要的 `explicit_no_airdrop` 字段也仍未处理 —— 两者都在
ADR-015 §「本 ADR 不解决什么」里划为独立立项。

### M3 = F4

#### T4.1 watched_wallets + webhook 匹配 + 通知
- **现状**：🟡（webhook 在，无匹配）。**产出物**：表 + 匹配逻辑 + admin 前缀锁 + F1 事件接入。
- **验收**：命中地址触发通知、未命中不触发；匿名访问 watched-wallets 得 403。

---

## 7. 横切约束（每项新能力都要过的门）

1. **新表**：db.py SQLite/PG 双份 DDL + alembic 迁移 + [DATABASE_DDL.md](DATABASE_DDL.md)。
   现状 DDL 三处维护是已知债 —— 新表**必须三处同落**，不许只改一处。
2. **新配置**：config.py + `.env.example` 同键同默认（env parity 门禁逐键比对）。
3. **新端点**：API_SPEC 新章节（路径/方法与真实路由表 parity）+ write-auth-split 计数重算 +
   `{ok, data}` envelope + mypy strict。
4. **新出站域名**：SECURITY §10.2 表登记，且调用必须经 `fetcher.fetch`（白名单才真的生效）。
5. **新指标**：真实埋点在代码路径上（有测试读样本值），对照 OPERATIONS §12.1 幽灵清单。
6. **新日志事件**：字面量写在 `logger.xxx("...")` 调用点（OBSERVABILITY parity 静态扫描），
   并登记进 OBSERVABILITY.md。
7. **术语**：`python scripts/check_terminology.py --all` 通过。
8. **交付定义**：每个子系统合入 = 全量后端套件绿（覆盖率 ≥80%）+ 上述 parity 全同步。

---

## 8. 非目标与红线

- **永不自动执行链上交互**（代签交易 / 自动领奖）—— 系统只提醒，资金操作永远人工。这是安全红线，
  不因任何「自动化程度」目标放宽。
- 多链扩展（Solana 等）：方向对，等 M1–M3 落地后评估。
- 对外开放 API / 第三方接入：不做。
- Dune 采集：不接。建议顺手**删掉** `DUNE_API_KEY` 死配置（docs/DATA_SOURCE_STRATEGY.md §8.2
  已注明它配了也不生效），而不是为了「配了能用」反向加需求。
- 移动端推送（APNs/FCM）：不做，Telegram/Discord 已覆盖随时在线场景。

## 9. 前置依赖（与 2026-08-30 审核遗留的关系）

- **前端代理注入管理员密钥的问题未解决前，不要把前端暴露到公网再启用推送** ——
  推送会把「面板越权」升级成「主动外呼越权」。F1 上线只要求本机/内网使用。
- 公网部署前必须处理：反代后限流退化为全局配额（`TRUSTED_PROXY_COUNT`）与 P2 清单中的
  compose 默认密码。详见 2026-08-30 审核报告。
