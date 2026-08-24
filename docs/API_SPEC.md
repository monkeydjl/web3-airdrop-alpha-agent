# API 详细规范（FastAPI）

> 配套文档：ENGINEERING_ROADMAP.md §8。本文档给出每个端点的请求/响应样例、错误码、鉴权设计与数据模型，供前后端与测试对齐。
---

## Opportunity v2 evidence safety and remediation

- `source_url` rejects URL userinfo and query keys containing `token`, `key`, `secret`, `signature`, or `auth`.
- `raw_snapshot_ref` is an opaque identifier using letters, digits, `.`, `_`, `:`, or `-`; URLs, paths, queries, and fragments are rejected.
- `supersedes_evidence_id` appends remediation evidence and must target existing evidence for the same project and factor. Existing evidence is never updated.
- A blocker clears only through current, verified, A-grade observed/derived evidence whose value is `false`; weak, expired, malformed, or circular remediation remains conservative.
- `outcome_observed_at` requires a timezone-aware ISO 8601 datetime. Creating or patching eligibility, survival, or reward outcomes without one records server UTC.

---

## 1. 基础信息

| 项目 | 值 |
| --- | --- |
| Base URL | http://127.0.0.1:8002 (project fixed port; frontend 3002) |
| API 前缀 | `/api/v1` |
| 内容类型 | `application/json; charset=utf-8` |
| 时间格式 | UTC 时间戳（`YYYY-MM-DD HH:MM:SS`） |
| 文档 | Swagger `/docs`、OpenAPI `/openapi.json` |

### 1.1 统一响应包络

所有端点返回统一结构：

```json
{ "ok": true,  "data": <任意>, "error": null }
```

失败时：

```json
{ "ok": false, "data": null,  "error": { "code": 404, "message": "project not found" } }
```

---

## 2. 鉴权

> **本节已按实测重写（2026-08-22）**。原文写的「MVP 无鉴权 / V2 才上 Bearer
> Token」已经不是现状 —— 鉴权中间件**当前就在生效**，无凭据直接 401。
> 按旧文档假设「本地随便调」会一路撞 401 却找不到原因。

三种身份（实测行为）：

| 身份 | 怎么带 | 权限 |
| --- | --- | --- |
| 无凭据 | — | **401**（除下方公开路径） |
| 匿名 token | `POST /api/v1/auth/anonymous` 换取，放 `Authorization: Bearer <token>` | 普通业务端点 200；管理员前缀 **403** |
| 管理员 API Key | `X-API-Key: <key>` 或 `Authorization: Bearer <api_key>` | 全部 200 |

**公开路径**（无需任何凭据）：`/health`、`/metrics`、`/docs`、`/redoc`、
`/openapi.json`、`/version`、`/api/v1/webhook*`、`/api/v1/auth/anonymous`。

**管理员专属前缀**（匿名 token 会拿到 403）：`/api/v1/run`、
`/api/v1/quarantine`、`/api/v1/export`、`/api/v1/import`、
`/api/v1/settings`、`/api/v1/archive`。

> `/api/v1/feedback` 与 `/api/v1/interactions` **不在**管理员名单里 ——
> 反馈与参与记录本来就要让普通使用者写入，这是有意的。
>
> `/settings` 与 `/archive` 之所以收紧到管理员：它们回显 CORS 白名单、
> DB 后端、全部阈值与 cron、LLM provider 清单，对匿名角色开放等于免费送侦察。
> 真值见 `backend/app/auth.py` 的 `PUBLIC_PREFIXES` / `ADMIN_ONLY_PREFIXES`。

### 2.1 写操作的鉴权分布（实测，2026-08-24 已收紧）

全仓共 **21 个**写端点（POST/PUT/PATCH/DELETE），当前分布：

<!-- write-auth-split:begin -->
| 归属 | 数量 |
| --- | --- |
| 管理员专用 | 7 |
| 无鉴权（公开） | 2 |
| 匿名 token 可调 | 12 |
<!-- write-auth-split:end -->

管理员专用的 7 个：`/run`、`/import/projects`、`/quarantine`、
`/quarantine/release`，加上 2026-08-24 新收紧的三个 ——
`POST /collections/{source_id}/trigger`、`PATCH /collections/{source_id}`、
`PATCH /projects/{project_id}/funding`。

公开的 2 个：`POST /auth/anonymous`（匿名入口本身）、
`POST /webhook/alchemy`（第三方回调，靠签名而非 token 保护）。

#### 收紧的是哪三个，为什么

这三个此前**匿名 token 实测返回 200**，而且不是"能看"而是"能做"：

| 端点 | 匿名可调的后果 |
| --- | --- |
| `POST /collections/{source_id}/trigger` | **真的去打外部 API 并写库**（同步跑完整采集，消耗第三方配额） |
| `PATCH /collections/{source_id}` | 开关采集源、改 cron —— 属于运维动作 |
| `PATCH /projects/{project_id}/funding` | 直接改项目融资数据，会影响评分输入 |

它们不是被谁故意放开的，而是 `ADMIN_ONLY_PREFIXES` 只支持**整前缀**匹配，
这三个都表达不了：

- `/collections/sources` 是只读的采集源就绪状态，首页和 `/discoveries` 页在用，
  整前缀锁会让匿名角色的页面直接空掉；
- `funding` 的通配段在路径**中间**（`/projects/{id}/funding`），前缀匹配写不出来，
  而且同一路径的 `GET` 应当保持开放。

因此新增了一层**按方法**的规则（`backend/app/auth.py` 的
`ADMIN_ONLY_METHOD_RULES`）：这两处的 `GET`/`HEAD` 照旧开放，
`POST`/`PATCH`/`PUT`/`DELETE` 一律要管理员。
`/collections/` 用的是**方法白名单取反**而不是逐条列出 trigger 和 PATCH ——
新加一个写端点时默认就是受保护的。
**一个需要人记得来登记的白名单，迟早会漏一条。**

#### 剩下 12 个匿名可写，为什么可以

`feedback` / `feedback/batch` / `events` / `interactions`（含 PATCH/DELETE）/
`watchlist`（含 DELETE）/ `notifications/read` 记录的是**使用者自己**的行为与偏好，
按 `user_id` 隔离，对匿名开放符合设计意图 —— 反馈闭环本来就要匿名可用。

`opportunity/evidence` 只追加证据条目，不花钱、不改评分事实。

`ai-brief` 和 `opportunity/evaluate` 会走 LLM（**有额度成本**），
但刻意没有按角色锁：成本改由 `LLM_DAILY_BUDGET_USD` 的预算门统一拦截。
理由是锁角色挡不住真实风险 —— 管理员自己刷同样会花钱。

> 这 12 条**逐条登记**在 `backend/tests/test_admin_only_rules.py` 的
> `ANON_WRITABLE` 里，每条都必须写一句为什么，且门禁**双向**核对：
> 登记条目必须在 OpenAPI 里真实存在（防陈旧条目），
> OpenAPI 里每个写操作必须有归属（防新增漏网）。
> **只查一个方向永远发现不了缺行。**

---

## 3. 端点总览

> **本表已按实测校对（2026-08-22）**：逐行拿 `GET /openapi.json` 的真实路由
> 比对，并对可疑项发真实请求确认状态码。此前本表混入了 13 条**不存在的路径**
> —— 一份声称某接口存在的规范，比没有规范更坏：读者会按它写调用，
> 拿到 404 却以为自己写错了。未实现的行现已移入 §3.1 并明确标注。
> `test_api_spec_parity.py` 会在 CI 阶段拦住新的漂移。

| 方法 | 路径 | API 版本 | 阶段 | 说明 |
| --- | --- | --- | --- | --- |
| POST | `/api/v1/run` | v1 | MVP（已实现） | 触发一次评分 pipeline（手动输入项目 → analyze → score → 写库） |
| GET | `/api/v1/projects` | v1 | MVP（已实现） | 项目列表（支持筛选/排序/分页） |
| GET | `/api/v1/projects/{id}` | v1 | MVP（已实现） | 单项目完整详情（**复数** `projects`，详见 §6） |
| GET | `/api/v1/export/projects` | v1 | MVP（已实现） | 导出项目列表（Excel/CSV） |
| GET | `/api/v1/export/project/{id}` | v1 | MVP（已实现） | 导出单项目完整详情（Excel） |
| GET | `/api/v1/export/template` | v1 | MVP（已实现） | 下载导入模板（Excel） |
| POST | `/api/v1/import/projects` | v1 | MVP（已实现） | 批量导入项目并评分（Excel/CSV，最多 100 个） |
| GET | `/api/v1/insights` | v1 | MVP（已实现） | 聚合洞察（label/sector 计数、最热叙事、高风险团队） |
| GET | `/api/v1/dashboard/overview` | v1 | V2（已实现） | Dashboard 今日概览聚合（采集运行/新增项目/发现队列/影子评估） |
| GET | `/api/v1/notifications` | v1 | V2（已实现） | 通知中心聚合（今日新机会 + 评分变化 + 采集器告警） |
| POST | `/api/v1/notifications/read` | v1 | V2（已实现） | 标记通知已读（ids 或 all=true，按用户持久化） |
| GET | `/api/v1/discoveries` | v1 | V2（已实现） | 查询自动发现的项目列表（支持 source/score 筛选） |
| GET | `/api/v1/collections/sources` | v1 | V2（已实现） | 查询数据源状态与最近同步信息 |
| PATCH | `/api/v1/collections/{source_id}` | v1 | V2（已实现） | 启用/停用单个采集源 |
| POST | `/api/v1/collections/{source_id}/trigger` | v1 | V2（已实现） | 手动触发指定源的采集（运维测试用） |
| POST | `/api/v1/feedback` | v1 | V2（已实现） | 提交用户反馈（useful/useless/wrong_label + outcome） |
| POST | `/api/v1/feedback/batch` | v1 | V2（已实现） | 批量提交反馈（单次上限 50 条） |
| GET | `/api/v1/feedback/{project_id}` | v1 | V2（已实现） | 查询某项目的反馈汇总（**按项目**，无不带参数的列表端点） |
| GET | `/api/v1/feedback/pending-review` | v1 | V2（已实现） | 待复盘队列 |
| GET | `/api/v1/calibration/status` | v1 | V2（已实现） | 校准状态（样本量 / 是否达到 200 门槛） |
| GET | `/api/v1/action-queue` | v1 | V2（已实现） | 今日行动队列 |
| GET / POST | `/api/v1/interactions` | v1 | V2（已实现） | 参与记录列表 / 新建 |
| GET | `/api/v1/interactions/summary` | v1 | V2（已实现） | 参与记录聚合（成本/收益/命中率） |
| PATCH / DELETE | `/api/v1/interactions/{interaction_id}` | v1 | V2（已实现） | 更新 / 删除单条参与记录 |
| GET | `/api/v1/projects/{project_id}/interactions` | v1 | V2（已实现） | 某项目的参与记录 |
| GET | `/api/v1/projects/{project_id}/participation-tasks` | v1 | V2（已实现） | 参与任务清单（**挂在项目下**，无顶层端点） |
| GET / PATCH | `/api/v1/projects/{project_id}/funding` | v1 | V2（已实现） | 融资信息 / 人工修正 |
| GET / POST | `/api/v1/projects/{project_id}/ai-brief` | v1 | V2（已实现） | 读取 / 生成 AI 简报（POST 即重新生成，无 `/regenerate`） |
| GET | `/api/v1/projects/{project_id}/opportunity` | v1 | V2（已实现） | 旁路机会引擎最新快照 |
| POST | `/api/v1/projects/{project_id}/opportunity/evaluate` | v1 | V2（已实现） | 显式执行机会评估 |
| GET / POST | `/api/v1/projects/{project_id}/opportunity/evidence` | v1 | V2（已实现） | 证据历史 / 追加证据 |
| GET | `/api/v1/projects/{project_id}/opportunity/workflow` | v1 | V2（已实现） | 工作流状态与建议动作 |
| GET / POST | `/api/v1/quarantine` | v1 | V2（已实现） | 隔离队列 / 加入隔离 |
| POST | `/api/v1/quarantine/release` | v1 | V2（已实现） | 解除隔离（**POST release**，无 `DELETE /{id}`） |
| GET | `/api/v1/watchlist` | v1 | V2（已实现） | 关注列表 |
| POST / DELETE | `/api/v1/watchlist/{project_id}` | v1 | V2（已实现） | 加入 / 移出关注（项目 id 在**路径**上） |
| GET | `/api/v1/settings/config` | v1 | V2（已实现） | 运行时配置只读快照 |
| GET | `/api/v1/llm/status` | v1 | V2（已实现） | LLM 开关与提供方状态 |
| GET | `/api/v1/archive/runs` | v1 | V2（已实现） | 归档运行历史（只读，详见 §37） |
| POST | `/api/v1/webhook/alchemy` | v1 | V2（已实现） | Alchemy 事件推送入口 |
| GET | `/api/v1/webhook/alchemy/status` | v1 | V2（已实现） | Webhook 状态（路径含 `alchemy`） |
| POST | `/api/v1/events` | v1 | V2（已实现） | 提交隐式行为埋点（click/expand/feedback 等） |
| POST | `/api/v1/auth/anonymous` | v1 | V2（已实现） | 获取匿名用户 token（Dashboard 首次访问） |
| GET | `/version` | — | MVP（已实现） | 版本与环境元信息（**无 `/api` 前缀**） |
| GET | `/health` | — | MVP（已实现） | 健康检查（基础设施 API） |
| GET | `/metrics` | — | MVP（已实现） | Prometheus 指标 |

### 3.1 曾被本文档列为「已实现」但实际不存在的端点

以下路径**当前没有任何路由**（实测状态码见括号）。本节保留它们只为提示
「文档曾经这么写过」，不要再按旧文档去调用：

| 方法 | 旧文档写的路径 | 实测 | 真相 |
| --- | --- | --- | --- |
| GET | `/api/v1/project/{id}` | 404 | 路径是**复数** `/api/v1/projects/{id}` |
| POST | `/api/v1/re-score/{id}` | 404 | 从未实现；重算走 `POST /api/v1/run` |
| GET | `/api/v1/audit` | 404 | 从未实现 |
| GET | `/api/v1/collections/logs` | 405 | 从未实现（405 因路径撞上 `PATCH /collections/{source_id}`） |
| POST | `/api/v1/collections/trigger/{source_id}` | 404 | 参数与动词顺序相反：`POST /collections/{source_id}/trigger` |
| GET | `/api/v1/discoveries/{id}` | 404 | 从未实现，只有列表端点 |
| GET | `/api/v1/discoveries/stats` | 404 | 从未实现；概览走 `/dashboard/overview` |
| GET | `/api/v1/feedback` | 405 | 列表端点不存在；按项目查是 `GET /feedback/{project_id}` |
| GET | `/api/v1/participation-tasks` | 404 | 挂在项目下：`/projects/{project_id}/participation-tasks` |
| GET | `/api/v1/webhook/status` | 404 | 真实路径含 provider：`/webhook/alchemy/status` |
| POST | `/api/v1/projects/{id}/ai-brief/regenerate` | 404 | `POST /ai-brief` 本身就是重新生成 |
| GET / PATCH | `/api/v1/quarantine/{id}` | 404 | 解除隔离是 `POST /quarantine/release` |
| POST | `/api/v1/watchlist` | 405 | 项目 id 在路径上：`POST /watchlist/{project_id}` |
| PUT | `/api/v1/projects/{id}/funding` | 405 | 真实动词是 **PATCH** |
| GET | `/api/version` | 404 | 真实路径是 `/version` |
| GET | `/api/v1/archive` | 404 | 真实路径是 `/archive/runs` |

> 本表**刻意与 §3 采用同一套列布局**（方法列独立、路径单独放反引号里）。
> 这样「解析总览表时必须跳过 §3.1」才是一条真会生效的规则 ——
> `test_overview_parser_finds_rows_and_skips_phantom_table` 通过改小标题就能
> 验证它确实在起作用。
>
> 此前 §3.1 把方法和路径挤在同一个反引号单元格里，于是那段跳过逻辑
> **永远不会被触发**：一条永不执行的规则等于没有规则，而测试照样全绿。
> 这是靠变异验证（把 `### 3.1` 改成 `### 3.2`，预期变红却全绿）才暴露的。

> 所有业务端点当前均在 `/api/v1`（首个稳定版）。V2 发布后，该表将增加 `/api/v2/*` 行并标注 v1 为 Deprecated。详见 [ENGINEERING_ROADMAP.md §26](ENGINEERING_ROADMAP.md)。

---

## 4. POST /api/v1/run

触发一次完整评分分析。接收项目列表（不自动采集外部源），同步运行并行评分
Pipeline（Narrative / Team / Risk / Tokenomics 四个 Agent + Scorer 加权），
返回评分结果与三档分类。单次最多 **100** 个项目。

**请求体**
```json
{
  "projects": [
    {
      "name": "LayerX",
      "url": "https://layerx.xyz",
      "sector": "L2",
      "stage": "testnet",
      "has_testnet": true,
      "has_points_program": true,
      "no_token_yet": true,
      "recent_funding": true
    }
  ],
  "enable_llm": false,
  "llm_model": "gpt-4o-mini"
}
```

字段说明（实测自 OpenAPI schema）：

- `projects`（**可选**，最多 100 项）：待评分项目列表。
  **省略或传 `null` 时不报错** —— 服务端会转为「从 `raw_projects` 队列取待分析
  项目」的自动模式，这也是首页「一键跑一遍」按钮发 `{}` 空 body 的原因。
  想显式指定项目就必须传这个字段。
  - `name`（该项**必填**）：项目名称
  - `url` / `sector` / `stage`（可选）：官网、赛道、部署阶段
  - `has_testnet` / `has_points_program` / `no_token_yet` / `recent_funding`
    （可选 bool）：空投信号
- `enable_llm`（可选 bool，默认 `false`）：是否启用 LLM 增强
  （默认走规则引擎路径）
- `llm_model`（可选 string，默认 `gpt-4o-mini`）：LLM 模型名称
  （仅在 `enable_llm=true` 时生效）

**鉴权**：`/api/v1/run` 属于管理员前缀，匿名 token 会拿到 **403**。

**响应 200**
```json
{
  "ok": true,
  "data": {
    "run_id": "api-run-20240708-120000",
    "status": "completed",
    "project_count": 1,
    "scored_count": 1,
    "error_count": 0,
    "top_score": 85,
    "top_projects": [
      {
        "id": "layerx-001",
        "name": "LayerX",
        "sector": "L2",
        "stage": "testnet",
        "score": 85,
        "label": "FARM",
        "confidence": 1.0,
        "reason": ["strong airdrop signal", "early narrative", "credible team"]
      }
    ]
  }
}
```

> 注：`top_projects` 按分数排序返回前 10 个；`scored_count` 为成功评分数量；
> `error_count` 为 agent 执行失败的项目数。
>
> **评分阈值（实测自 `app/agents/scorer.py` 的 `LABEL_THRESHOLDS`）**：
> FARM ≥65 / WATCH ≥50 / IGNORE <50，权重版本 **v1.2**。
> 原文标注的「v1.1」已过期 —— 阈值数字没变，但版本号变了；
> `test_frontend_enum_parity.py` 会把前端展示的阈值与这张表钉在一起。

**错误**

- `422`：输入校验失败（项目数超过 100、`name` 缺失等，FastAPI 自动校验）
- `403`：用匿名 token 调用（本端点是管理员前缀）
- `500`：Pipeline 执行失败（body 的 `error.message` 带定位信息）
**cURL**
```bash
curl -X POST http://localhost:8002/api/v1/run \
  -H 'Content-Type: application/json' \
  -d '{"projects":[{"name":"LayerX","url":"https://layerx.xyz","sector":"L2","stage":"testnet","has_testnet":true,"has_points_program":true,"no_token_yet":true,"recent_funding":true}],"enable_llm":false}'
```

---

## 5. GET /api/v1/projects

> **本节已按实测重写（2026-08-22）**。原文的六个 query 参数里，
> **`search` / `limit` / `order` 三个根本不存在**，`label` / `sector` / `stage`
> 也**不支持逗号多选**（实测 `label=FARM,WATCH` 返回 `total: 0` —— 它被当成
> 一个字面值去精确匹配，既不报错也不匹配，是最难发现的那种错）。
> 响应也不是扁平数组，而是带分页元信息的对象。

**Query 参数**（实测，全部来自 OpenAPI schema）

| 参数 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `page` | int ≥1 | `1` | 页码 |
| `page_size` | int 1–500 | **`20`** | 每页条数（超出范围 **422**） |
| `label` | string | - | **精确**匹配 `FARM`/`WATCH`/`IGNORE`，不支持多选 |
| `sector` | string | - | **精确**匹配赛道 |
| `stage` | string | - | **精确**匹配部署阶段 `ideation`/`testnet`/`mainnet` |
| `min_score` | int 0–100 | - | 分数下限 |
| `sort_by` | string | `score` | 排序字段 |
| `sort_order` | enum | `desc` | `asc`/`desc`（非法值 **422**） |
| `auto_discovered` | bool | - | 只看自动发现 / 只看手工录入 |

**没有 `search` 参数**：首页的关键词搜索是**前端在已取回的列表上过滤**的，
不是服务端搜索。这意味着搜索范围受当前分页限制 —— 这是现状，不是 bug，
但不要以为它在全库范围内搜索。

**响应 200**（实测形状，列表项为精简字段，不含四个分析块）
```json
{
  "ok": true,
  "data": {
    "projects": [
      {
        "id": "cf62d275-db05-5d8b-ad83-ec8de18cd3ce",
        "name": "Scroll zkEVM",
        "sector": "ZK",
        "stage": "mainnet",
        "score": 83,
        "label": "FARM",
        "confidence": 0.814,
        "discovery_source": "seed",
        "discovered_at": null,
        "auto_discovered": false
      }
    ],
    "total": 288,
    "page": 1,
    "page_size": 20,
    "filters": { "label": null, "sector": null, "stage": null, "min_score": null },
    "sort": { "by": "score", "order": "desc" }
  }
}
```

**错误行为（实测，与原文不同）**

- 非法 `sort_order` → **422**（原文写 400）
- 非法 `label`（如 `NOPE`）→ **200 + 空列表**，不报错。
  过滤值打错**不会**得到提示，只会「查不到东西」—— 排查时先怀疑枚举值拼写。
- `page_size` 越界 → **422**
---

## 6. GET /api/v1/projects/{id}

> **本节已按实测重写（2026-08-22）**。早期版本把路径写作
> `/api/v1/project/{id}`（**单数**，实测 404），并按数据库列名把四个分析块
> 写成顶层的 `narrative_json` / `team_json` / `risk_json` / `tokenomics_json`，
> 还凭空多了一个 `lineage` 对象。真实响应把项目包在 `data.project` 里，
> 四个块的键名去掉了 `_json` 后缀，字段名也与旧文档不同。
>
> **这份错文档是四个前端 bug 的源头**：详情页照着它读 `team.flags`、
> `team.risk_level`、`risk.farming_cost`、`tokenomics.unlock_pressure`，
> 四个键在真实响应里都不存在，于是那四格永远显示「无」或「—」。

**路径参数**：`id`（项目主键，uuid 字符串）

**响应 200**（实测形状，取自真实库中一条记录）
```json
{
  "ok": true,
  "data": {
    "project": {
      "id": "cf62d275-db05-5d8b-ad83-ec8de18cd3ce",
      "name": "Scroll zkEVM",
      "url": "https://scroll.io",
      "sector": "ZK",
      "stage": "mainnet",
      "score": 83,
      "label": "FARM",
      "confidence": 0.814,
      "reason": ["strong airdrop signal", "early narrative, high heat"],
      "sub_scores": { "narrative": 0.9, "team": 0.95 },
      "weight_version": "v1.2",
      "narrative":  { "sector": "ZK", "stage": "growth", "heat_score": 0.902, "timing": "early" },
      "team":       { "team_score": 0.95, "team_flags": ["tier-1 vc backed", "doxxed team"], "team_type": "doxxed", "risk_level": "low" },
      "risk":       { "token_risk": 0.267, "risk_flags": [], "unlock_pressure": "low", "sybil_difficulty": "high" },
      "tokenomics": { "vc_share": 0.35, "team_share": 0.2, "unlock_penalty": 0.35, "risk": 0.305 },
      "funding": { "funding_tier": "tier1" },
      "funding_note": null,
      "signals": [],
      "source": "defillama",
      "created_at": "2026-08-15 14:51:17",
      "updated_at": "2026-08-18 15:40:31"
    }
  }
}
```

### 6.1 容易读错的四个字段归属

| 界面上那格 | 正确的键 | 曾经读错成 | 读错的后果 |
| --- | --- | --- | --- |
| 团队 → Flags | `team.team_flags` | `team.flags` | 永远显示「无」，像是「这个项目没有风险标记」 |
| 团队 → 风险档位 | `team.risk_level` | 同名但后端原先没落库 | 永远空白 |
| 风险 → 交互成本 | `risk.farming_cost` | 同名但后端原先没落库 | 永远显示「—」 |
| 解锁压力 | `risk.unlock_pressure` | `tokenomics.unlock_pressure` | 该键只在 `risk` 块，代币经济那格永远「—」 |

**为什么读错键比报错更危险**：TypeScript 里读一个不存在的键不会抛错，
配上 `?? ''` 就静默变成「无」/「—」。「Flags：无」看起来像
**「这个项目干净」**，而不是「我读错了键名」—— 一个匿名团队的高风险项目，
会在页面上显示得像个没有任何问题的项目。

`test_frontend_field_parity.py` 现在把前端读的每个键与后端 Pydantic 模型的
`model_dump()` 对起来，读不存在的键会直接让 CI 变红。

### 6.2 历史行的补算策略：可重放才补

`risk_level` 与 `farming_cost` 是同一批修复加上的字段，但对**历史数据**
刻意处理得不一样：

- `risk_level` **补算**：它由 `team_score` 唯一决定，而 `team_score` 已落库，
  所以现算等于**重放同一个映射**，不是猜。
- `farming_cost` **不补**：它的输入 `has_points_program` 不在 `projects` 表里，
  无法忠实重放。历史行就是没有这个键，前端显示「—」。

**宁可显示「不知道」，也不端出一个看起来很像真值的默认值** ——
读者无法分辨「机器编的」和「原本就是这个值」。
参见 `tests/api/test_projects.py::TestLegacyRowBackfill`。

**错误**：`404` 项目不存在
```json
{ "ok": false, "data": null, "error": { "code": 404, "message": "project not found" } }
```

---

## 7. POST /api/v1/re-score/{id} — **未实现**

> **实测 404（2026-08-22）**。本节此前把它写成 MVP 端点，但全仓没有任何
> 对应路由。要重算某个项目，用 `POST /api/v1/run` 并在请求体里带上该项目
> —— pipeline 会重跑 analyze + score 并覆盖写库。
>
> 保留本节只为说明「旧文档承诺过这个路径」。不要照此实现调用方。
---

## 8. GET /api/v1/insights

**响应 200**
```json
{
  "ok": true,
  "data": {
    "total_projects": 23,
    "label_counts": { "FARM": 5, "WATCH": 12, "IGNORE": 6 },
    "sector_counts": { "L2": 8, "Restaking": 6, "DeFi": 9 },
    "hottest_narratives": [
      {
        "sector": "Restaking",
        "project_count": 6,
        "avg_heat_score": 0.82,
        "trend": "up"
      }
    ],
    "risky_teams": [
      {
        "id": "layerx-001",
        "name": "LayerX",
        "sector": "L2",
        "risk_level": "medium",
        "team_score": 0.35,
        "flags": ["previous failed project"]
      }
    ]
  }
}
```

> 全部从 `projects` 表聚合得出。
>
> `risk_level` 由 `team_json.team_score` 推导，真值是
> `app/agents/team.py::score_to_risk_level`：**<0.4 → high，0.4–0.7 → medium，
> >0.7 → low**。这个映射曾在三处各写一份（本端点、详情页、AI 简报），
> 现已统一收敛到那个函数 —— **同一个推导出现在 N 个地方，其中 N−1 个是待爆的 bug**。
>
> `trend` 由 `avg_heat_score` 推导。
>
> 实测当前 `risky_teams` 返回 **270 条**（288 个项目里绝大多数团队分不高），
> 每条含 `flags` / `id` / `name` / `risk_level` / `sector` / `team_score`。
---

## 8a. GET /api/v1/dashboard/overview

聚合「今日流水线」真实数据：采集运行统计、今日新增项目、发现队列待处理数、影子引擎评估数。供 Dashboard「今日流水线」卡片展示。

**响应 200**
```json
{
  "ok": true,
  "data": {
    "today": {
      "collection_runs": { "total": 5, "success": 4, "failed": 1 },
      "new_projects": 8,
      "new_farm_projects": 2
    },
    "discovery": {
      "pending_count": 12,
      "today_new": 6,
      "total": 180
    },
    "shadow": {
      "saved_today": 3,
      "label_counts": { "FARM": 1, "WATCH": 2, "IGNORE": 0 }
    }
  }
}
```

> `today.collection_runs` 统计今日 `collection_logs`；`discovery` 统计 `raw_projects`（待处理 = `processed=0`）；`shadow` 统计今日 `opportunity_assessments`。「今日」按 UTC 零点窗口计算。

---

## 8b. GET /api/v1/notifications

聚合通知中心真实数据：今日新建 FARM/WATCH、评分变化、采集失败告警，并合并当前用户已读状态。

**响应 200**
```json
{
  "ok": true,
  "data": {
    "unread_count": 3,
    "items": [
      {
        "id": "new-xxxx",
        "type": "new_project",
        "title": "今日新进 FARM：Nova Protocol",
        "tag": "FARM",
        "text": "主评分 82 · L2 · 建议参与",
        "project_id": "xxxx",
        "created_at": "2026-07-26 08:00:00",
        "read": false,
        "link": { "label": "查看项目", "href": "/project/xxxx" }
      },
      {
        "id": "score-xxxx-12",
        "type": "score",
        "title": "Nova Protocol 评分上升 8",
        "tag": "评分变化",
        "text": "评分 74 → 82 · 当前标签 FARM",
        "project_id": "xxxx",
        "created_at": "2026-07-26 07:45:00",
        "read": false,
        "link": { "label": "查看项目", "href": "/project/xxxx" }
      },
      {
        "id": "col-defillama-...",
        "type": "collector",
        "title": "defillama 采集器失败",
        "tag": "采集器告警",
        "text": "状态 failed：401 unauthorized",
        "created_at": "2026-07-26 07:30:00",
        "read": true,
        "link": { "label": "运维台", "href": "/ops" }
      }
    ]
  }
}
```

> - `new_project`：今日 `projects`（label ∈ FARM/WATCH）
> - `score`：`project_history` 同项目最新两条 score/label 有差异，且最新条在今日窗口
> - `collector`：今日 `collection_logs` 中 status ∈ failed/error
> - `read`：来自 `notification_reads`（按当前鉴权 user_id）

---

## 8c. POST /api/v1/notifications/read

标记通知已读并持久化。

**请求**
```json
{ "ids": ["new-xxxx", "score-yyyy-12"] }
```
或
```json
{ "all": true }
```

**响应 200**
```json
{
  "ok": true,
  "data": { "marked": 2, "ids": ["new-xxxx", "score-yyyy-12"] }
}
```

> `all=true` 时会对当前可聚合出的全部通知 id 写入已读；与 `ids` 可同时使用（并集）。按 `user_id` 隔离。

---

## 9. POST /api/v1/feedback

提交用户对项目的反馈（显式反馈回流）。

**请求体**（字段与上限均实测自 OpenAPI schema）
```json
{
  "project_id": "cf62d275-db05-5d8b-ad83-ec8de18cd3ce",
  "user_id": "default",
  "signal": "useful",
  "note": "该项目确实有空投，已参与",
  "outcome": "airdropped"
}
```

| 字段 | 必填 | 取值 / 上限 |
| --- | --- | --- |
| `project_id` | ✅ | string，≤64 字符 |
| `signal` | ✅ | `useful` / `useless` / `wrong_label` / `correct_outcome` |
| `user_id` | — | string，≤64 字符 |
| `note` | — | string，**≤2000** 字符（原文写 500，已更正） |
| `outcome` | — | `airdropped` / `not_airdropped` / `pumped` / `dumped` |

**响应 200**
```json
{
  "ok": true,
  "data": { "id": 1, "project_id": "uuid", "signal": "useful", "outcome": "airdropped", "created_at": "2026-07-08 08:00:12" }
}
```

**错误**：`422` 非法 signal/outcome 枚举或超长 note（FastAPI 校验，
**不是 400** —— 原文写错）；`404` 项目不存在。

> 反馈是权重校准的唯一输入。校准门槛为 **200 条样本**
> （`app/services/feedback.py` 的 `min_samples`），未达门槛时
> `/calibration/status` 会明确回「样本不足」而不是给一个不可信的调整建议。
> 实测当前 `feedback` 表 **0 条** —— 复盘页显示的进度条是真实的 0/200，
> 不是加载失败。
---

## 10. GET /api/v1/feedback/{project_id}

> **本节已按实测重写（2026-08-22）**。原文写的是 `GET /api/v1/feedback`
> 带一堆 query 过滤参数（`signal` / `outcome` / `limit`）—— 那个端点**不存在**
> （实测 405），过滤参数也全是虚构的。真实接口是**按项目查汇总**，
> 唯一参数是路径里的 `project_id`。

查询某个项目的反馈汇总（供详情页与复盘页展示）。

**路径参数**：`project_id`

**响应 200**（实测形状）
```json
{
  "ok": true,
  "data": {
    "project_id": "cf62d275-db05-5d8b-ad83-ec8de18cd3ce",
    "count": 0,
    "signals": {},
    "items": []
  }
}
```

- `count`：该项目的反馈总条数
- `signals`：按 signal 取值聚合的计数（如 `{"useful": 3, "wrong_label": 1}`）
- `items`：明细列表

### 10.1 GET /api/v1/feedback/pending-review

待复盘队列。参数：`limit`（默认 **20**）、`user_id`（可选）。
返回 `data.items[]`，每项含 `project_id` / `name` / `sector` / `stage` /
`score` / `label` / `confidence` / `url` / `updated_at` / `has_interaction` 等。

### 10.2 POST /api/v1/feedback/batch

批量提交反馈，单次上限 **50** 条（前端 `BATCH_LIMIT` 由
`test_frontend_enum_parity.py` 钉住与后端一致）。

---

## 11. GET /api/v1/audit — **未实现**

> **实测 404（2026-08-22）**。全仓没有 audit 路由，本节描述的查询参数与响应
> 结构都是设计稿，不是现状。审计能力当前只体现为结构化日志
> （`LOG_FORMAT=json`），没有查询接口。
>
> 保留本节只为记录设计意图；实现前不要按它写调用方。原文中的 `re-score`
> 过滤值同样指向一个不存在的动作。

---

## 12. GET /health

**响应 200**
```json
{ "ok": true, "data": { "status": "healthy", "db": "connected", "projects": 23, "config_version": "1.0.0" } }
```

---

## 13. POST /api/v1/events

提交隐式行为埋点。前端在 Dashboard 交互时调用，用于后续反馈校准与个性化排序。

**请求体**（实测：`detail` 是**字符串**，不是 JSON 对象）
```json
{
  "project_id": "cf62d275-db05-5d8b-ad83-ec8de18cd3ce",
  "user_id": "default",
  "event_type": "expand",
  "detail": "{\"duration_ms\":1200,\"section\":\"reason\"}"
}
```

| 字段 | 必填 | 取值 / 上限 |
| --- | --- | --- |
| `event_type` | ✅ | string，≤32 字符（**无枚举约束**，任意字符串都收） |
| `project_id` | — | string，≤64；全局事件（如 `page_view`）可省略 |
| `user_id` | — | string，≤64 |
| `detail` | — | **string**，≤4000 字符；要放结构化内容需自行 JSON 序列化 |

> 原文把 `detail` 写成 JSON 对象、并声称 `event_type` 限定
> `click|expand|feedback|filter_change|page_view` —— 两者都不对：
> 传对象会 422，传任意 `event_type` 反而会被接受。
> **一个不校验的枚举，读文档的人却以为它在校验** —— 埋点名打错不会有人拦，
> 只会在后续统计里多出一个孤立的事件名。

**响应 200**
```json
{ "ok": true, "data": { "id": 1, "event_type": "expand", "created_at": "2026-07-08 08:00:12" } }
```

**错误**：`422` 超长字段或 `detail` 传了非字符串。

---

## 14. POST /api/v1/auth/anonymous

签发匿名 token。前端首次访问时调用，本端点自身**无需鉴权**（在公开路径里）。

**请求体**：`{}`（实测无必填字段；原文提到的 `client_id` 不在 schema 里）

**响应 200**（实测形状 —— 注意**没有** `data` 包络）
```json
{
  "access_token": "eyJ1c2VyX2lkIjoiYW5vbi0wN2Zk...",
  "token_type": "Bearer",
  "expires_in": 259200,
  "user_id": "anon-07fd20436aa9"
}
```

> **这是全仓唯一不走 `{ok, data}` 包络的端点** —— 它直接返回顶层 token 对象，
> 因为要贴合 OAuth2 惯例。前端的 `apiFetch` 会自动解包 `data`，所以这个端点
> 必须单独处理，不能套用统一封装。
>
> 字段名是 `access_token`（不是原文的 `token`），有效期是
> `expires_in` **秒数**（实测 259200 = **3 天**，不是原文说的「30 天」），
> 不是 `expires_at` 时间戳。`user_id` 形如 `anon-<hex>`（连字符，不是下划线）。
---

## 15. GET /version

> **本节已按实测重写（2026-08-22）**。原文写的路径是 `/api/version`
> —— 实测 **404**；真实路径是 `/version`（无 `/api` 前缀，与 `/health`
> `/metrics` 同属基础设施端点）。响应体也完全不同：原文列的
> `current_version` / `latest_version` / `deprecated_versions` /
> `sunset_versions` / `stable_versions` / `docs_url` **六个字段无一存在**。

版本与运行环境元信息。

**响应 200**（实测形状）
```json
{
  "ok": true,
  "data": {
    "version": "0.1.0",
    "app_env": "development",
    "llm_enabled": false
  }
}
```

> 版本弃用/下架清单当前**没有**接口承载 —— 原文那套字段是 API 版本治理的
> 设计稿。真要做版本迁移提示，需要先实现它，不能假设现在读得到。

---

## 16. GET /api/v1/discoveries

> **本节已按实测重写（2026-08-22）**。原文列的 7 个查询参数里
> **只有 3 个真实存在**（`min_score` / `page` / `page_size`），另外
> `source` / `auto_discovered` / `label` / `since` 全是虚构。
> 更糟的是：**传这些不存在的参数不会报错** —— FastAPI 静默忽略未声明的
> query 参数，实测 `?source=defillama&label=FARM&since=2026-01-01` 依然返回
> 全部 693 条。调用方会以为筛选生效了，拿到的却是未过滤的全量数据。

查询自动发现的原始项目队列（`raw_projects`）。

**鉴权**：普通身份即可（匿名 token 也能读）。

**查询参数**（实测自 OpenAPI schema）

| 参数 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `page` | int ≥1 | `1` | 页码 |
| `page_size` | int 1–**200** | `20` | 每页条数（原文写 max 100，已更正） |
| `processed` | bool | - | `false` 只看未处理，`true` 只看已处理 |
| `min_score` | number ≥0 | `0.0` | `discovery_score` 下限 |

**响应 200**（实测形状）

```json
{
  "ok": true,
  "data": {
    "items": [
      {
        "raw_id": "796723d44e71486c8e75d55b710fa389",
        "source_id": "defillama",
        "dedup_key": "veda::Onchain Capital Allocator",
        "project_id": "5d84e1c8-6663-511d-9dbf-a24bdfbcb38e",
        "name": "Veda",
        "sector": "Onchain Capital Allocator",
        "stage": "mainnet",
        "discovery_score": 1.0,
        "processed": true,
        "discovered_at": "2026-08-15T14:51:16.956923+00:00",
        "score": 66,
        "label": "FARM",
        "confidence": 0.721
      }
    ],
    "total": 693,
    "page": 1,
    "page_size": 20
  },
  "error": null
}
```

字段名与原文的差异（都已按实测更正）：来源字段是 `source_id` 而非
`discovery_source`，另有 `raw_id` / `dedup_key` / `processed` 三个原文没提的
字段，而原文写的 `signal_count` / `auto_discovered` **不存在**。

---

## 17. GET /api/v1/discoveries/{id} — **未实现**

> **实测 404（2026-08-22）**。只有列表端点 `GET /api/v1/discoveries`，
> 没有单条详情端点。下面的响应示例是设计稿，不代表现状。
>
> 需要单条原始发现数据时，当前只能从列表结果里取，或直查 `raw_projects` 表。

<details>
<summary>原设计稿（未实现，仅存档）</summary>

```json
{
  "ok": true,
  "data": {
    "project": { "id": "uuid", "name": "LayerX" },
    "discovery": {
      "raw_id": "uuid",
      "source_id": "defillama",
      "dedup_key": "layerx::l2",
      "raw_data": { "tvl": 5000000, "has_token": false },
      "discovered_at": "2026-07-09 08:15:00",
      "discovery_score": 0.78
    },
    "signals": [
      {
        "signal_type": "tvl",
        "signal_source": "defillama",
        "signal_data": { "tvl": 5000000 },
        "signal_strength": 0.5,
        "captured_at": "2026-07-09 08:15:00"
      }
    ]
  },
  "error": null
}
```

</details>

---

## 18. GET /api/v1/discoveries/stats — **未实现**

> **实测 404（2026-08-22）**。Dashboard 概览走的是
> `GET /api/v1/dashboard/overview`，不是本节描述的这个端点。
> 下面的数字（`total_discovered: 156`、`by_source` 里的 `twitter` / `chain`）
> 全是虚构示例 —— 实测 `raw_projects` 共 693 条，来源只有
> coingecko / cryptorank / defillama / github / etherscan 五个。

<details>
<summary>原设计稿（未实现，仅存档）</summary>

```json
{
  "ok": true,
  "data": {
    "total_discovered": 156,
    "by_source": { "defillama": 89, "github": 32 },
    "by_label": { "FARM": 12, "WATCH": 45, "IGNORE": 99 },
    "daily_trend": [{ "date": "2026-07-03", "count": 22 }],
    "avg_discovery_score": 0.42
  },
  "error": null
}
```

</details>

---

## 19. GET /api/v1/collections/sources

> **本节已按实测重写（2026-08-22）**。原文把 `data` 写成一个**扁平数组**，
> 且每项字段（`enabled` / `sync_status` / `last_sync` / `api_calls_today`）
> 直接躺在顶层。真实形状是 `data.sources[]`，且状态字段全部**嵌在
> `status` 子对象里** —— 按旧文档写的调用方会读到一堆 `undefined`。
> 前端 `discoveries/page.tsx` 正是消费这个端点（由
> `test_frontend_enum_parity.py::TestNoHardcodedSourceList` 钉住）。

查询所有数据源的当前状态与最近同步信息。实测返回 **10 个源**：
`coingecko` / `cryptorank` / `defillama` / `etherscan` / `galxe` /
`github` / `layer3` / `rootdata` / `twitter_keyword` / `twitter_kol`。

**响应 200**（实测形状）

```json
{
  "ok": true,
  "data": {
    "sources": [
      {
        "source_id": "defillama",
        "source_name": "DefiLlama",
        "source_type": "api",
        "config_ready": true,
        "operator_enabled": true,
        "is_enabled": true,
        "status": {
          "enabled": true,
          "sync_status": "success",
          "last_sync": "2026-08-15 14:51:17",
          "api_calls_today": 0
        }
      }
    ]
  },
  "error": null
}
```

三个 enabled 语义**刻意分开**，不要合并理解：

| 字段 | 含义 |
| --- | --- |
| `config_ready` | 该源所需的配置（如 API key）是否齐备 |
| `operator_enabled` | 运维是否手动开启（`PATCH /collections/{source_id}` 改这个） |
| `is_enabled` | 两者都成立才为 `true`，即**实际会不会跑** |

---

## 20. GET /api/v1/collections/logs — **未实现**

> **实测 405（2026-08-22）**。没有这个端点；405 是因为 `/collections/logs`
> 恰好匹配上 `PATCH /api/v1/collections/{source_id}` 的路径模式，
> FastAPI 于是回「方法不允许」而不是 404 —— 这个假信号本身就容易骗人：
> 405 看起来像「端点在、只是动词错了」。
>
> 采集日志当前只在 `collection_logs` 表里（实测 20 条），无查询接口。

---

## 21. POST /api/v1/collections/{source_id}/trigger

> **路径已按实测更正（2026-08-22）**。原文写的是
> `/collections/trigger/{source_id}`（动词在前）—— 实测 404。
> 真实路径把参数放在前面：`/collections/{source_id}/trigger`。

**鉴权（实测）**：无凭据 **401**；**匿名 token 就能触发（200）** ——
本端点**不在**管理员前缀清单里。原文标的「需管理员权限」不成立。

> 这值得单独指出：一个会真的去打外部 API、真的往库里写数据的端点，
> 目前**匿名身份就能调**。这是现状记录，不是推荐配置 —— 上生产前
> 应当考虑把 `/api/v1/collections` 加入 `ADMIN_ONLY_PREFIXES`。

**响应 200**（实测 —— **不是 202**，也**没有** `task_id`）

原文把它写成「`202 Accepted` + 返回采集任务 id + 去 `/collections/logs` 查日志」，
三点全错：OpenAPI 只声明 `200` 与 `422`；采集是**同步跑完**才返回的，
所以没有任务 id 可给；而 `/collections/logs` 这个查日志端点本身不存在（见 §20）。

```json
{
  "ok": true,
  "data": {
    "source_id": "etherscan",
    "status": "success",
    "items_collected": 2,
    "items_new": 2,
    "items_duplicate": 0,
    "started_at": "2026-08-22T18:14:33.043194+00:00",
    "finished_at": "2026-08-22T18:14:37.209419+00:00",
    "auto_run": null,
    "auto_run_skipped": null
  },
  "error": null
}
```

> **这个端点会真的去打外部 API 并写库** —— 它同步执行完整采集，
> 把新条目写进 `raw_projects`。不要当成「排个队而已」拿去随手试。
> `auto_run` 为 `null` 表示没有连带触发分析（受
> `COLLECTION_AUTO_RUN_ENABLED` 控制，实测为 `false`）。

---

## 22. 数据模型（概要，详见 DATA_SCORING_DICT.md）

> **本节已按实测更正（2026-08-22）**。`ProjectRecord` 原来那串字段名是照
> **数据库列名**抄的，与 **API 响应**不是一回事 —— 详情页 bug 的根源就在这。
> 现在两者分开列。

**API 响应字段**（`GET /projects/{id}` → `data.project`，见 §6）：
`id, name, url, sector, stage, score, label, confidence, reason[], sub_scores,
weight_version, narrative, team, risk, tokenomics, funding, funding_note,
signals, source, created_at, updated_at`

**数据库列名**（`projects` 表，供直查 SQL 用）：
`narrative_json, team_json, risk_json, tokenomics_json` —— 带 `_json` 后缀的是
**列名**，API 响应里会去掉后缀。原文列的 `recommendation` / `lineage` /
`discovery_source` / `auto_discovered` / `signal_count` 不在详情响应里
（其中 `discovery_source` / `auto_discovered` 只出现在**列表**响应，见 §5）。

- `DiscoveryRecord`（`raw_projects` 表实测列）：
  `raw_id, source_id, dedup_key, raw_data, discovered_at, processed,
  processed_at, project_id, discovery_score, quarantined, quarantine_reason`
  —— 注意**没有 `name` 列**，项目名藏在 `raw_data` JSON 里。
- `SignalRecord`：`signal_id, project_id, signal_type, signal_source,
  signal_data, signal_strength, captured_at`
- `NarrativeResult` / `TeamResult` / `RiskResult` / `TokenomicsResult` /
  `ScoreResult`：见各 Agent 的输出字典（真值为
  `backend/app/models.py` 的 Pydantic 模型，
  `test_frontend_field_parity.py` 会把前端读的键与它们对起来）。

### 22.1 Opportunity v2.0 Shadow API

`opportunity-v2.0` 当前只以 Shadow 模式追加证据和不可变评估快照。`opportunity_shadow_enabled` 默认 `false`，仅控制评分 pipeline 是否自动旁路执行；以下显式 API 在开关关闭时仍可调用。Shadow 结果不会更新 `projects.score`、`projects.label` 或 `projects.recommendation`，现有 `score-v1.4` 标签仍是权威输出。

| 方法 | 路径 | 成功状态码 | 说明 |
| --- | --- | ---: | --- |
| `POST` | `/api/v1/projects/{project_id}/opportunity/evidence` | `201` | 追加一条带来源和验证状态的证据 |
| `GET` | `/api/v1/projects/{project_id}/opportunity/evidence` | `200` | 按时间倒序返回完整证据历史，包括 invalidated 记录 |
| `POST` | `/api/v1/projects/{project_id}/opportunity/evaluate` | `200` | 显式执行评估并追加不可变快照 |
| `GET` | `/api/v1/projects/{project_id}/opportunity` | `200` | 返回默认画像的最新快照及 `stale`、`review_due` |

追加证据示例：

```json
{
  "factor_key": "participation_open",
  "value": true,
  "value_type": "bool",
  "observation_type": "observed",
  "source_url": "https://project.example/rules",
  "source_type": "official_docs",
  "source_grade": "A",
  "observed_at": "2026-07-15T11:00:00Z",
  "verification_status": "verified",
  "independence_group": "official-rules"
}
```

评估响应同时包含内部 `status` 和公开 `public_label`。映射为：`ACTIONABLE → FARM`、`MONITOR/INSUFFICIENT_EVIDENCE → WATCH`、`NOT_FIT → IGNORE`；`BLOCKED` 表示必须先提供可信修复证据，不能因时间经过自动解除。稀疏 legacy 输入不会补中性默认值，而是返回 `INSUFFICIENT_EVIDENCE/WATCH`。完整响应还包含模型/画像版本、概率与经济区间、风险、置信度、原因码、证据 ID、复查和过期时间。

错误：四个端点在项目不存在时返回 `404 PROJECT_NOT_FOUND`；`POST evidence` 的未知因子、值类型不匹配、非法范围或额外字段返回统一 `422 VALIDATION_ERROR`。显式 evaluate 的意外服务/数据库错误按全局 `500` 处理。
---

## 23. 版本管理

> **本节已按实测更正（2026-08-22）**。原文说「版本元端点 `GET /api/version`
> 返回当前/最低/已弃用/已下架版本列表」—— 那个路径实测 404，真实端点是
> `GET /version`，返回的是 `version` / `app_env` / `llm_enabled` 三个字段，
> **没有任何版本清单**。下面把「已实现」和「设计意图」分开写。

**已实现**

- 当前 API 版本为 **v1**（稳定版），所有业务端点都在 `/api/v1` 下。
- `GET /version` 返回 `version` / `app_env` / `llm_enabled`。

**尚未实现（设计意图，实现前不要依赖）**

- 版本清单（当前 / 最低 / 已弃用 / 已下架）没有接口承载。
- 同一大版本内向后兼容（字段仅增不减、响应仅扩不缩）是约定而非机制，
  没有自动校验。
- 弃用期响应头（`Deprecation: true` / `Sunset` / `Link`）尚未实现。
- 版本策略与弃用流程详见 [ENGINEERING_ROADMAP.md §26](ENGINEERING_ROADMAP.md)。

---

## 24. 错误码表

| 状态码 | 含义 | 触发场景 |
| --- | --- | --- |
| 400 | Bad Request | 参数非法（枚举 / 类型错误） |
| 401 | Unauthorized | 缺失 / 错误的凭据 |
| 403 | Forbidden | 凭据有效但权限不足（匿名 token 访问管理员前缀） |
| 404 | Not Found | `id` 不存在，或路径本身不存在 |
| 405 | Method Not Allowed | 路径存在但动词不对 —— **也可能是路径压根不存在、只是恰好匹配上了另一个路由的模式**（例：`/collections/logs` 撞上 `PATCH /collections/{source_id}`） |
| 422 | Validation Error | Pydantic 校验失败（FastAPI 自动） |
| 500 | Internal Error | agent 执行异常 / DB 不可用 |

---

## 25. 速率限制

- 当前**不限制**（`APP_ENV=development`）。
- 设计意图：每 IP 60 req/min（超限返回 `429`），Dashboard 轮询与 cron 不受影响
  —— **尚未实现**，不要假设已有保护。

---

## 26. 示例：端到端最小流程

> 每条命令都按实测路由校对过（2026-08-22）。原版第 4 步用的是单数
> `/api/v1/project/{id}`、第 5 步调的 `/re-score/{id}` 根本不存在
> —— 照抄会直接拿到 404。

```bash
# 1) 启动服务（见 DEPLOYMENT.md）
python run.py &

# 2) 跑一次评分
curl -X POST http://localhost:8002/api/v1/run -H 'Content-Type: application/json' -d '{"projects":[{"name":"LayerX","sector":"L2","stage":"testnet","has_testnet":true,"has_points_program":true,"no_token_yet":true,"recent_funding":true}],"enable_llm":false}'

# 3) 看 Top 项目
curl 'http://localhost:8002/api/v1/projects?label=FARM&limit=10'

# 4) 看详情（复数 projects）
curl http://localhost:8002/api/v1/projects/a1b2c3d4-e5f6-5a7b-8c9d-0e1f2a3b4c5d

# 5) 重算：没有 re-score 端点，重新提交同一个项目走 /run 即可覆盖写库
curl -X POST http://localhost:8002/api/v1/run -H 'Content-Type: application/json' -d '{"projects":[{"name":"LayerX","sector":"L2","stage":"testnet"}],"enable_llm":false}'
```

---

## 27. interactions（参与记录）

### 27a. POST /api/v1/interactions

创建项目参与记录（用于校准与复盘）。

**请求体**:
```json
{
  "project_id": "uuid-here",
  "status": "active",
  "started_at": "2026-07-26",
  "cost_usd": 120.0,
  "profit_usd": null,
  "hours_spent": 6.5,
  "outcome": "pending",
  "activities": "Galxe 任务 + 测试网交互",
  "note": "多钱包参与"
}
```

**响应 201**:
```json
{
  "ok": true,
  "data": { "id": 1, "project_id": "uuid-here", "status": "active", "net_usd": -120.0 }
}
```

### 27b. GET /api/v1/interactions

列出参与记录（可按 project_id / status 筛选）。

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `project_id` | string | — | 按项目筛选 |
| `status` | string | — | planned/active/done/abandoned |
| `limit` | int | 50 | 1-200 |

**响应 200**:
```json
{
  "ok": true,
  "data": { "items": [...], "total": 34, "count": 5 }
}
```

### 27c. GET /api/v1/interactions/summary

聚合统计（校准矩阵 + 收益分析）。

**响应 200**:
```json
{
  "ok": true,
  "data": {
    "total": 34,
    "by_status": { "planned": 6, "active": 3, "done": 21, "abandoned": 4 },
    "by_outcome": { "airdropped": 10, "not_airdropped": 5, "pending": 19 },
    "label_outcome_matrix": [
      { "label_at_start": "FARM", "outcome": "airdropped", "c": 8 }
    ],
    "total_cost_usd": 3250.0,
    "total_profit_usd": 15730.0,
    "net_usd": 12480.0,
    "total_hours": 186.0
  }
}
```

### 27d. GET /api/v1/projects/{project_id}/interactions

列出指定项目的全部参与记录（等价于 `GET /interactions?project_id=...`）。

### 27e. PATCH /api/v1/interactions/{interaction_id}

更新参与记录（状态流转 / 结果 / 成本收益）。

**请求体**（部分字段）:
```json
{
  "status": "done",
  "outcome": "airdropped",
  "profit_usd": 890.0
}
```

### 27f. DELETE /api/v1/interactions/{interaction_id}

删除参与记录。返回 `{ "ok": true, "data": { "deleted": true, "id": 1 } }`。

---

## 28. participation-tasks

### 28a. GET /api/v1/projects/{project_id}/participation-tasks

> **路径与响应已按实测更正（2026-08-22）**。原文写的是顶层
> `GET /api/v1/participation-tasks` 带 `project_id` **查询参数** —— 实测 404。
> 真实端点挂在项目下，项目 id 是**路径**的一部分。响应也不是扁平数组，
> 而是带 `summary` 聚合的对象。

查询某项目的参与任务清单（Galxe / Layer3 等平台任务）。

**路径参数**：`project_id`

**响应 200**（实测形状，节选）
```json
{
  "ok": true,
  "data": {
    "project_id": "cf62d275-db05-5d8b-ad83-ec8de18cd3ce",
    "project_name": "Scroll zkEVM",
    "label": "FARM",
    "stage": "mainnet",
    "summary": {
      "total": 10,
      "required_count": 2,
      "by_category": { "信息核实": 3, "记录与复盘": 2, "主网产品": 1 }
    }
  }
}
```

---

## 29. quarantine（隔离队列）

### 29a. GET /api/v1/quarantine

列出隔离队列（采集失败 / 数据异常的原始记录）。实测当前 **3 条**。

响应形状为 `data.count` + `data.items[]`，每项含
`raw_id` / `source_id` / `dedup_key` / `raw_data` 等。

### 29b. POST /api/v1/quarantine

把一条原始记录加入隔离。

### 29c. POST /api/v1/quarantine/release

> **本节已按实测更正（2026-08-22）**。原文写的是
> `GET /api/v1/quarantine/{id}`（查看详情）与 `PATCH /api/v1/quarantine/{id}`
> （更新状态）—— **两者实测均为 404**，从未实现。真实的解除隔离动作是
> 一个不带路径参数的 `POST /quarantine/release`。

解除隔离。

---

## 30. watchlist（用户关注列表）

### 30a. GET /api/v1/watchlist

列出当前用户的关注项目。

**响应 200**:
```json
{
  "ok": true,
  "data": [
    { "id": 1, "project_id": "uuid", "note": "高优先级", "created_at": "2026-07-26T08:00:00Z" }
  ]
}
```

### 30b. POST /api/v1/watchlist/{project_id}

> **路径与请求体已按实测更正（2026-08-22）**。原文写的是
> `POST /api/v1/watchlist`，项目 id 放在**请求体**里 —— 实测 **405**
> （该路径只有 GET）。真实端点把项目 id 放在**路径**上，请求体只接受
> `note` 与 `user_id` 两个可选字段，**没有** `project_id` 字段。

添加项目到关注列表。

**路径参数**：`project_id`

**请求体**（全部可选）
```json
{ "note": "值得关注", "user_id": "default" }
```

### 30c. DELETE /api/v1/watchlist/{project_id}

从关注列表移除项目。

> 关注列表响应形状为 `data.items[] / total / page / page_size / user_id`
> （分页对象，非扁平数组）。实测当前 0 条。

---

## 31. funding（融资信息）

### 31a. GET /api/v1/projects/{project_id}/funding

> **响应已按实测更正（2026-08-22）**。原文写成一个「融资轮次数组」
> （`round` / `amount_usd` / `date` / `investors`）—— 那些字段**都不存在**。
> 真实响应是**单个聚合对象**，字段名全部带 `funding_` 前缀。

查询项目融资信息。

**响应 200**（实测形状）
```json
{
  "ok": true,
  "data": {
    "project_id": "cf62d275-db05-5d8b-ad83-ec8de18cd3ce",
    "funding": {
      "funding_total_usd": 80000000.0,
      "funding_rounds": 2,
      "funding_last_date": "2025-10-01",
      "funding_investors": ["Polychain", "Sequoia", "Bain Capital"],
      "funding_lead_investors": ["Polychain"],
      "funding_tier": "tier1"
    }
  }
}
```

`funding_tier` 取值：`tier1` / `tier2` / `tier3` / `none` / `unknown`
（真值在 `app/services/funding.py`，前端 `tierZh` 已覆盖全集）。

### 31b. PATCH /api/v1/projects/{project_id}/funding

> **动词与请求体已按实测更正（2026-08-22）**。原文写的是 **PUT** ——
> 实测 405（该路径只支持 GET / PATCH）；请求体原文写的
> `funding` / `funding_note` 两个字段也**都不存在**。

人工修正融资信息（编辑后触发重评）。

**请求体**（全部可选，实测字段名）
```json
{
  "funding_total_usd": 5000000,
  "funding_rounds": 1,
  "funding_last_date": "2026-06-01",
  "funding_investors": ["a16z"],
  "funding_lead_investors": ["a16z"],
  "recent_funding": true,
  "note": "2026-06 Seed"
}
```

---

## 32. ai_brief（AI 简报）

### 32a. GET /api/v1/projects/{project_id}/ai-brief

获取项目的 AI 简报（规则生成 / 可选 LLM 增强）。

**响应 200**:
```json
{
  "ok": true,
  "data": {
    "brief": "Nova Protocol 是一个 L2 扩容方案...",
    "llm_available": false,
    "generated_at": "2026-07-26T08:00:00Z"
  }
}
```

### 32b. POST /api/v1/projects/{project_id}/ai-brief

> **路径已按实测更正（2026-08-22）**。原文写的是
> `POST /projects/{id}/ai-brief/regenerate` —— 实测 404。
> 真实做法是对**同一个路径**发 POST：`GET` 读缓存，`POST` 即重新生成。

重新生成 AI 简报。

---

## 33. llm（LLM 状态）

### 33a. GET /api/v1/llm/status

查询 LLM 多接口故障转移配置状态。

**响应 200**:
```json
{
  "ok": true,
  "data": {
    "enabled": false,
    "provider_count": 1,
    "total_model_count": 2,
    "failover_strategy": "sequential",
    "providers": [
      {
        "name": "provider-1",
        "base_url": "https://api.openai.com/v1",
        "api_key_masked": "sk-***",
        "has_api_key": true,
        "models": ["gpt-4o-mini", "gpt-4o"],
        "model_count": 2
      }
    ],
    "temperature": 0.3,
    "max_tokens": 512,
    "daily_budget_usd": 1.0,
    "discovery_score_threshold": 0.7
  }
}
```

---

## 34. webhook（Alchemy 事件推送）

### 34a. POST /api/v1/webhook/alchemy

Alchemy webhook 回调端点（接收链上事件推送）。

**请求头**: `X-Alchemy-Signature`（HMAC 签名验证）

### 34b. GET /api/v1/webhook/alchemy/status

> **路径已按实测更正（2026-08-22）**。原文写的是 `/webhook/status`
> —— 实测 404。真实路径带 provider 段：`/webhook/alchemy/status`。

查询 webhook 配置状态。

**响应 200**（实测形状）
```json
{
  "ok": true,
  "data": {
    "source_id": "alchemy_webhook",
    "source_type": "webhook",
    "configured": false,
    "webhook_url": null
  }
}
```

---

## 35. auth（鉴权）

### 35a. POST /api/v1/auth/anonymous

签发匿名 token（用于受限 API 访问）。

**响应 200**:
```json
{
  "ok": true,
  "data": {
    "access_token": "eyJ...",
    "token_type": "Bearer",
    "expires_in": 86400,
    "user_id": "anon-abc123def456"
  }
}
```

---

## 36. settings（运行时配置）

### 36a. GET /api/v1/settings/config

返回当前运行时配置的只读快照（密钥只返回是否已设置，不返回明文）。

**响应 200**:
```json
{
  "ok": true,
  "data": {
    "access": { "api_key_set": false, "cors_origins": "http://localhost:3002" },
    "weights": { "WEIGHT_AIRDROP_SIGNAL": 0.18 },
    "flags": { "ENABLE_LLM_ENHANCEMENT": false },
    "sources": { "defillama": { "enabled": true, "has_api_key": false } },
    "automation": { "SCHEDULER_ENABLED": true },
    "platform": { "METRICS_ENABLED": true, "LOG_LEVEL": "info" },
    "thresholds": {
      "CONFIDENCE_THRESHOLD": 0.5,
      "LABEL_FARM_THRESHOLD": 65.0,
      "LABEL_WATCH_THRESHOLD": 50.0
    },
    "llm": { "enabled": false, "providers": [] }
  }
}
```

> 密钥类字段（API_KEY、*_TOKEN 等）只返回布尔值 `has_api_key` / `api_key_set`，不返回明文。

> `thresholds.LABEL_FARM_THRESHOLD` / `LABEL_WATCH_THRESHOLD` 是标签分档下限，
> 真值来自 `app.agents.scorer.LABEL_THRESHOLDS`（不是环境变量），本端点做查表暴露。
> 前端不得自行写死这两个数：它们已经调过一次（v1.1 把 FARM 从 70 降到 65），
> 写死的副本不会跟着变，只会静默变成错的。`tests/api/test_settings.py`
> 里有断言把本端点与 scorer 常量钉在一起。

---

## 37. archive（归档运行历史）

**管理员专属**（`/api/v1/archive` 在 `ADMIN_ONLY_PREFIXES` 内）：响应含各表真实
行数、保留期配置与调度 cron，属运维信息，与 `/settings` 同一口径。

### 37a. GET /api/v1/archive/runs

只读。返回最近若干次归档运行、六档保留策略的当前待清理规模、以及归档调度配置。
**不会触发归档** —— 手动触发用 `python scripts/archive_raw_data.py`。

**查询参数**：`limit`（默认 20，范围 1–200）

**响应 200**:
```json
{
  "ok": true,
  "data": {
    "runs": [
      {
        "id": 12,
        "started_at": "2026-08-22T03:00:00+00:00",
        "finished_at": "2026-08-22T03:00:04+00:00",
        "duration_ms": 4120,
        "trigger": "scheduler",
        "dry_run": 0,
        "status": "success",
        "raw_archived": 18,
        "unprocessed_archived": 460,
        "signals_archived": 0,
        "logs_deleted": 3,
        "raw_archive_pruned": 0,
        "signals_archive_pruned": 0,
        "error_message": null
      }
    ],
    "summary": {
      "total_runs": 12,
      "failed_runs": 0,
      "last_run_at": "2026-08-22T03:00:00+00:00",
      "pending_total": 0
    },
    "policies": [
      {
        "key": "raw_unprocessed",
        "table": "raw_projects",
        "label": "未过分析阈值的采集记录",
        "retention_days": 90,
        "action": "archive",
        "total": 509,
        "pending": 0
      }
    ],
    "schedule": { "enabled": true, "cron": "0 3 * * *", "timezone": "UTC" }
  }
}
```

`trigger` 取值 `scheduler` / `manual` / `api`；`status` 取值 `success` / `failed`。
失败的运行同样会出现在 `runs` 里并带 `error_message` —— 只显示成功会让"归档
连续几天没跑成"看不出来。

`policies` 固定六档：`raw_processed`、`raw_unprocessed`、`signals`、`logs`、
`raw_archive`、`signals_archive`；`action` 为 `archive`（搬入归档表）或
`delete`（直接删除）。`pending` 是"下一次运行会动多少行"的实时预估，与归档器
使用同一组条件。详见 [DATABASE_DDL.md §6](DATABASE_DDL.md)。
