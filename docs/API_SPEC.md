# API 详细规范（FastAPI?
> 配套文档：ENGINEERING_ROADMAP.md §8。本文档给出每个端点的请?响应样例、错误码、鉴权设计与数据模型，供前后端与测试对齐?
---

## Opportunity v2 evidence safety and remediation

- `source_url` rejects URL userinfo and query keys containing `token`, `key`, `secret`, `signature`, or `auth`.
- `raw_snapshot_ref` is an opaque identifier using letters, digits, `.`, `_`, `:`, or `-`; URLs, paths, queries, and fragments are rejected.
- `supersedes_evidence_id` appends remediation evidence and must target existing evidence for the same project and factor. Existing evidence is never updated.
- A blocker clears only through current, verified, A-grade observed/derived evidence whose value is `false`; weak, expired, malformed, or circular remediation remains conservative.
- `outcome_observed_at` requires a timezone-aware ISO 8601 datetime. Creating or patching eligibility, survival, or reward outcomes without one records server UTC.

---

## 1. 基础信息

| ?| ?|
| --- | --- |
| Base URL | http://127.0.0.1:8002 (project fixed port; frontend 3002) |
| API 前缀 | `/api/v1` |
| 内容类型 | `application/json; charset=utf-8` |
| 时间格式 | UTC 时间戳（`YYYY-MM-DD HH:MM:SS`?|
| 文档 | Swagger `/docs`、OpenAPI `/openapi.json` |

### 1.1 统一响应包络
所有端点返回统一结构?```json
{ "ok": true,  "data": <任意>, "error": null }
```
失败?```json
{ "ok": false, "data": null,  "error": { "code": 404, "message": "project not found" } }
```

---

## 2. 鉴权

- **MVP**：无鉴权（仅限本?内网使用）?- **V2**：Bearer Token。请求头 `Authorization: Bearer <API_KEY>`；`API_KEY` 来自环境变量。缺失或错误返回 `401`?- `/health` ?Swagger 文档无需鉴权?
---

## 3. 端点总览

| 方法 | 路径 | API 版本 | 阶段 | 说明 |
| --- | --- | --- | --- | --- |
| POST | `/api/v1/run` | v1 | MVP（已实现?| 触发一次评?pipeline（手动输入项??analyze ?score ?写库?|
| GET | `/api/v1/projects` | v1 | MVP（已实现?| 项目列表（支持筛?排序/分页?|
| GET | `/api/v1/project/{id}` | v1 | MVP（已实现?| 单项目完整详?|
| GET | `/api/v1/export/projects` | v1 | MVP（已实现?| 导出项目列表（Excel/CSV?|
| GET | `/api/v1/export/project/{id}` | v1 | MVP（已实现?| 导出单项目完整详情（Excel?|
| GET | `/api/v1/export/template` | v1 | MVP（已实现?| 下载导入模板（Excel?|
| POST | `/api/v1/import/projects` | v1 | MVP（已实现?| 批量导入项目并评分（Excel/CSV，最?100 个） |
| POST | `/api/v1/re-score/{id}` | v1 | MVP | 用最新规?数据对该项目重算评分 |
| GET | `/api/v1/insights` | v1 | MVP（已实现?| 聚合洞察（label/sector 计数、最热叙事、高风险团队?|
| GET | `/api/v1/dashboard/overview` | v1 | V2（已实现?| Dashboard 今日概览聚合（采集运行/新增项目/发现队列/影子评估） |
| GET | `/api/v1/notifications` | v1 | V2（已实现） | 通知中心聚合（今日新机会 + 评分变化 + 采集器告警） |
| POST | `/api/v1/notifications/read` | v1 | V2（已实现） | 标记通知已读（ids 或 all=true，按用户持久化） |
| GET | `/api/v1/discoveries` | v1 | V2（v2.0，ADR-012?| 查询自动发现的项目列表（支持 source/score 筛选） |
| GET | `/api/v1/discoveries/{id}` | v1 | V2（v2.0，ADR-012?| 单个发现项目详情（含 raw_projects + signals?|
| GET | `/api/v1/discoveries/stats` | v1 | V2（v2.0，ADR-012?| 发现统计（按??评分分布聚合?|
| GET | `/api/v1/collections/sources` | v1 | V2（v2.0，ADR-012?| 查询数据源状态与最近同步信?|
| GET | `/api/v1/collections/logs` | v1 | V2（v2.0，ADR-012?| 查询采集日志（支?source_id/状?时间筛选） |
| POST | `/api/v1/collections/trigger/{source_id}` | v1 | V2（v2.0，ADR-012?| 手动触发指定源的采集（运?测试用） |
| POST | `/api/v1/feedback` | v1 | V2 | 提交用户反馈（useful/useless/wrong_label + outcome?|
| GET | `/api/v1/feedback` | v1 | V2 | 查询用户反馈（支?project_id 过滤?|
| POST | `/api/v1/events` | v1 | V2 | 提交隐式行为埋点（click/expand/feedback 等，V2 起） |
| GET | `/api/v1/audit` | v1 | V2 | 查询审计日志（action/user 过滤，V2 鉴权?|
| POST | `/api/v1/auth/anonymous` | v1 | V2 | 获取匿名用户 token（Dashboard 首次访问?|
| GET | `/api/version` | ?| MVP | 版本元信息（当前/最?Deprecated/Sunset?|
| GET | `/health` | ?| MVP | 健康检查（无版本，基础设施 API?|

> 所有业务端点当前均?`/api/v1`（首个稳定版）。V2 发布后，该表将增?`/api/v2/*` 行并标注 v1 ?Deprecated。详?[ENGINEERING_ROADMAP.md §26](ENGINEERING_ROADMAP.md)?
---

## 4. POST /api/v1/run

触发一次完整评分分析。MVP 为手动输入方向：接收项目列表（不自动采集外部源），同步运行并行评?Pipeline（Narrative/Team/Risk/Tokenomics 4 ?Agent + Scorer 加权），返回评分结果与三档分类。每次最?100 个项目?
**请求?*
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

字段说明?- `projects`（必填，1?00 项）：待评分项目列表。每项字段：
  - `name`（必填，1?00 字符）：项目名称
  - `url` / `sector` / `stage`（可选）：官网、赛道、阶?  - `has_testnet` / `has_points_program` / `no_token_yet` / `recent_funding`（可?bool，默?`false`）：空投信号
- `enable_llm`（可?bool，默?`false`）：是否启用 LLM（默认使用启发式规则?- `llm_model`（可?string，默?`gpt-4o-mini`）：LLM 模型名称（仅?`enable_llm=true` 时生效）

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

> 注：`top_projects` 按分数排序返回前 10 个；`scored_count` 为成功评分数量；`error_count` ?agent 执行失败的项目数。评分阈值：**FARM ≥65 / WATCH ≥50 / IGNORE <50 (v1.1)**?
**错误**
- `400`：输入校验失败（如项目数超出 1?00、`name` 为空或超?200 字符）?- `500`：Pipeline 执行失败（body ?`error.message` 与定位信息）?
**cURL**
```bash
curl -X POST http://localhost:8002/api/v1/run \
  -H 'Content-Type: application/json' \
  -d '{"projects":[{"name":"LayerX","url":"https://layerx.xyz","sector":"L2","stage":"testnet","has_testnet":true,"has_points_program":true,"no_token_yet":true,"recent_funding":true}],"enable_llm":false}'
```

---

## 5. GET /api/v1/projects

**Query 参数**

| 参数 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `label` | string | - | 过滤 `FARM`/`WATCH`/`IGNORE`；支持多选（逗号分隔?|
| `sector` | string | - | 过滤赛道，如 `L2`/`Restaking`；支持多选（逗号分隔?|
| `stage` | string | - | 过滤项目阶段 `testnet`/`mainnet`/`ideation`；支持多选（逗号分隔?|
| `search` | string | - | 项目名称模糊匹配（大小写不敏感） |
| `limit` | int | 100 | 返回条数，上?500 |
| `order` | string | `DESC` | `DESC`/`ASC`（按 score?|

**响应 200**（精简字段，不含大体积 JSON 列）
```json
{
  "ok": true,
  "data": [
    {
      "id": "a1b2c3d4-e5f6-5a7b-8c9d-0e1f2a3b4c5d", "name": "LayerX", "sector": "L2",
      "stage": "testnet", "score": 67, "label": "WATCH",
      "recommendation": "WATCH",
      "confidence": 1.0,
      "reason": ["strong airdrop signal", "early narrative, high heat", "high token unlock pressure"],
      "created_at": "2026-07-08 08:00:12"
    }
  ]
}
```

**错误**：`400` 非法 `order`/`label` 值?
---

## 6. GET /api/v1/project/{id}

**路径参数**：`id`（项目主键，uuid 字符串）

**响应 200**（完整记录）
```json
{
  "ok": true,
  "data": {
    "id": "a1b2c3d4-e5f6-5a7b-8c9d-0e1f2a3b4c5d", "name": "LayerX", "url": "https://layerx.xyz",
    "sector": "L2", "stage": "testnet", "score": 67, "label": "WATCH",
    "recommendation": "WATCH",
    "confidence": 1.0,
    "reason": ["strong airdrop signal", "early narrative, high heat", "high token unlock pressure"],
    "narrative_json":  { "sector": "L2", "stage": "growth", "heat_score": 0.82, "timing": "early" },
    "team_json":       { "score": 0.72, "risk_level": "medium", "flags": ["previous failed project"] },
    "risk_json":       { "sybil_difficulty": "high", "farming_cost": "medium", "token_risk": 0.68 },
    "tokenomics_json": { "vc_share": 0.25, "team_share": 0.2, "unlock_pressure": "high", "risk": 0.75 },
    "lineage": {
      "sources": [
        { "source": "seed", "reliability": 1.0, "fetched_at": "2026-07-08T08:00:00Z" }
      ],
      "agent_executions": [
        { "agent": "Narrative", "status": "success", "timestamp": "2026-07-08T08:00:01Z" },
        { "agent": "Team", "status": "success", "timestamp": "2026-07-08T08:00:02Z" }
      ],
      "weight_version": "v1"
    },
    "source": "seed", "created_at": "2026-07-08 08:00:12"
  }
}
```

**错误**：`404` 项目不存在?```json
{ "ok": false, "data": null, "error": { "code": 404, "message": "project not found" } }
```

---

## 7. POST /api/v1/re-score/{id}

用最新规?数据对该项目重算评分（不重新采集，仅重跑 analyze+score）?
**路径参数**：`id`

**响应 200**：更新后的完?`ProjectRecord`（结构同 §6）?
**错误**：`404` 项目不存在；`500` 重算失败?
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

> ?`projects` 表聚合得出；`risk_level` 根据 `team_json.team_score` 推导?0.4 high，≤0.7 medium?0.7 low）。`trend` ?`avg_heat_score` 推导?
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

提交用户对项目的反馈（显式反馈回流，V2 起支持）?
**请求?*
```json
{
  "project_id": "a1b2c3d4-e5f6-5a7b-8c9d-0e1f2a3b4c5d",
  "signal": "useful",
  "note": "该项目确实有空投，已参与",     // 可选，最?500 字符
  "outcome": "airdropped"                  // airdropped|not_airdropped|pumped|dumped
}
```

**响应 200**
```json
{
  "ok": true,
  "data": { "id": 1, "project_id": "uuid", "signal": "useful", "outcome": "airdropped", "created_at": "2026-07-08 08:00:12" }
}
```

**错误**：`400` 非法 signal/outcome 枚举；`404` 项目不存在?
---

## 10. GET /api/v1/feedback

查询用户反馈（供 Dashboard 展示或数据校准使用）?
**Query 参数**

| 参数 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `project_id` | string | - | 过滤特定项目 |
| `signal` | string | - | 过滤 `useful`/`useless`/`wrong_label`/`correct_outcome` |
| `outcome` | string | - | 过滤 `airdropped`/`not_airdropped`/`pumped`/`dumped` |
| `limit` | int | 50 | 返回条数，上?200 |

**响应 200**
```json
{
  "ok": true,
  "data": [
    { "id": 1, "project_id": "uuid", "signal": "useful", "outcome": "airdropped", "note": "已参?, "created_at": "2026-07-08 08:00:12" }
  ]
}
```

---

## 11. GET /api/v1/audit

查询审计日志（记录关键操作：run 触发、配置变更、权重切换）?
> MVP 无鉴权（本地使用）；V2 需 API_KEY 鉴权?
**Query 参数**

| 参数 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `action` | string | - | 过滤 `run`/`re-score`/`config_change`/`weight_change` |
| `user` | string | - | 过滤触发者（system/手动/API key 名） |
| `limit` | int | 50 | 返回条数，上?200 |

**响应 200**
```json
{
  "ok": true,
  "data": [
    { "id": 1, "action": "run", "user": "system", "detail": "source=seed,limit=50", "ip": "127.0.0.1", "created_at": "2026-07-08 08:00:12" }
  ]
}
```

---

## 12. GET /health

**响应 200**
```json
{ "ok": true, "data": { "status": "healthy", "db": "connected", "projects": 23, "config_version": "1.0.0" } }
```

---

## 13. POST /api/v1/events

提交隐式行为埋点（V2 起）。前端在 Dashboard 交互时调用，用于后续反馈校准与个性化排序?
**请求?*
```json
{
  "project_id": "a1b2c3d4-e5f6-5a7b-8c9d-0e1f2a3b4c5d",  // 可选，全局事件?page_view 可省?  "event_type": "expand",                                // click|expand|feedback|filter_change|page_view
  "detail": { "duration_ms": 1200, "section": "reason" }   // 事件详情 JSON，按 event_type 自定?}
```

**响应 200**
```json
{ "ok": true, "data": { "id": 1, "event_type": "expand", "created_at": "2026-07-08 08:00:12" } }
```

**错误**：`400` 非法 `event_type`?
---

## 14. POST /api/v1/auth/anonymous

获取匿名用户 token（V2 起）。Dashboard 首次访问时调用，无需鉴权?
**请求?*
```json
{}
```
?```json
{ "client_id": "optional-stable-id" }  // 可选，用于同一设备/浏览器稳定关?```

**响应 200**
```json
{
  "ok": true,
  "data": {
    "token": "eyJ...",
    "user_id": "anon_xxxxxxxx",
    "expires_at": "2026-08-07T08:00:00Z"
  }
}
```

> Token 有效?30 天，过期?Dashboard 自动静默刷新?
---

## 15. GET /api/version

版本元信息，供客户端/前端判断是否需要迁移?
**响应 200**
```json
{
  "ok": true,
  "data": {
    "current_version": "v1",
    "latest_version": "v1",
    "deprecated_versions": [],
    "sunset_versions": [],
    "stable_versions": ["v1"],
    "docs_url": "/docs"
  }
}
```

---

## 16. GET /api/v1/discoveries

> v2.0 新增（ADR-012）。查询自动发现的项目列表，支持按数据源、评分、时间筛选?
**鉴权**: V2 Bearer Token（MVP 无鉴权）

**查询参数**:

| 参数 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `source` | string | ?| 按发现来源筛选：`defillama`/`github`/`twitter`/`chain`/`manual` |
| `min_score` | number | ?| discovery_score 下限?-1?|
| `auto_discovered` | bool | ?| `true` 仅自动发现，`false` 仅手?|
| `label` | string | ?| FARM/WATCH/IGNORE |
| `since` | string | ?| 起始时间（UTC，`YYYY-MM-DD`?|
| `page` | int | 1 | 页码 |
| `page_size` | int | 20 | 每页条数（max 100?|

**响应示例**:

```json
{
  "ok": true,
  "data": {
    "items": [
      {
        "project_id": "uuid-v5",
        "name": "LayerX",
        "sector": "L2",
        "stage": "testnet",
        "score": 82,
        "label": "FARM",
        "discovery_source": "defillama",
        "discovered_at": "2026-07-09 08:15:00",
        "auto_discovered": true,
        "discovery_score": 0.78,
        "signal_count": 4
      }
    ],
    "total": 156,
    "page": 1,
    "page_size": 20
  },
  "error": null
}
```

---

## 17. GET /api/v1/discoveries/{id}

> v2.0 新增（ADR-012）。单个发现项目详情，?raw_projects 原始数据与关?signals?
**响应示例**:

```json
{
  "ok": true,
  "data": {
    "project": { "id": "uuid", "name": "LayerX", "..." : "..." },
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
      },
      {
        "signal_type": "github_activity",
        "signal_source": "github",
        "signal_data": { "commits_last_30d": 45 },
        "signal_strength": 0.9,
        "captured_at": "2026-07-09 08:30:00"
      }
    ]
  },
  "error": null
}
```

---

## 18. GET /api/v1/discoveries/stats

> v2.0 新增（ADR-012）。发现统计聚合，用于 Dashboard 概览?
**查询参数**: `since`（起始日期，默认?7 天）

**响应示例**:

```json
{
  "ok": true,
  "data": {
    "total_discovered": 156,
    "by_source": {
      "defillama": 89,
      "github": 32,
      "twitter": 21,
      "chain": 14
    },
    "by_label": {
      "FARM": 12,
      "WATCH": 45,
      "IGNORE": 99
    },
    "daily_trend": [
      { "date": "2026-07-03", "count": 22 },
      { "date": "2026-07-04", "count": 31 }
    ],
    "avg_discovery_score": 0.42
  },
  "error": null
}
```

---

## 19. GET /api/v1/collections/sources

> v2.0 新增（ADR-012）。查询所有数据源的当前状态与最近同步信息?
**响应示例**:

```json
{
  "ok": true,
  "data": [
    {
      "source_id": "defillama",
      "source_name": "DefiLlama",
      "enabled": true,
      "sync_status": "idle",
      "last_sync": "2026-07-09 08:00:12",
      "api_calls_today": 142,
      "api_limit": null
    },
    {
      "source_id": "twitter",
      "source_name": "Twitter/X",
      "enabled": false,
      "sync_status": "idle",
      "last_sync": null,
      "api_calls_today": 0,
      "api_limit": null
    }
  ],
  "error": null
}
```

---

## 20. GET /api/v1/collections/logs

> v2.0 新增（ADR-012）。查询采集日志，用于运维监控与故障排查?
**查询参数**: `source_id` / `status` / `since` / `page` / `page_size`

---

## 21. POST /api/v1/collections/trigger/{source_id}

> v2.0 新增（ADR-012）。手动触发指定数据源的采集，用于运维测试?
**鉴权**: V2 Bearer Token（需管理员权限）

**响应**: `202 Accepted`，返回采集任?id?
```json
{
  "ok": true,
  "data": {
    "task_id": "uuid",
    "source_id": "defillama",
    "status": "queued",
    "message": "Collection triggered, check logs at /api/v1/collections/logs?source_id=defillama"
  },
  "error": null
}
```

---

## 22. 数据模型（概要，详见 DATA_SCORING_DICT.md?
- `ProjectRecord`：`id,name,url,sector,stage,score,label,recommendation,confidence,reason[],narrative_json,team_json,risk_json,tokenomics_json,lineage,source,discovery_source,discovered_at,auto_discovered,signal_count,created_at`
- `DiscoveryRecord`（v2.0）：`raw_id,source_id,dedup_key,raw_data,discovered_at,processed,discovery_score`
- `SignalRecord`（v2.0）：`signal_id,project_id,signal_type,signal_source,signal_data,signal_strength,captured_at`
- `NarrativeResult` / `TeamResult` / `RiskResult` / `TokenomicsResult` / `ScoreResult`：见?Agent 输出字典?

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

- 当前 API 版本?*v1**（稳定版）?- 版本元端点：`GET /api/version` 返回当前版本信息（当?最?已弃?已下架版本列表）?- 版本策略与弃用流程详?[ENGINEERING_ROADMAP.md §26](ENGINEERING_ROADMAP.md)?- 同一大版本内保证向后兼容（字段仅增不减，响应仅扩不缩）。V2 发布?v1 进入 Deprecated 状态，至少 90 天弃用窗口?- 弃用期间旧版响应头含 `Deprecation: true`、`Sunset` 日期?`Link` 迁移指引?
---

## 18. 错误码表

| 状态码 | 含义 | 触发场景 |
| --- | --- | --- |
| 400 | Bad Request | 参数非法（枚?类型错误?|
| 401 | Unauthorized | V2 缺失/错误 API Key |
| 404 | Not Found | `id` 不存?|
| 422 | Validation Error | Pydantic 校验失败（FastAPI 自动?|
| 500 | Internal Error | agent 执行异常 / DB 不可?|

---

## 19. 速率限制

- MVP：不限制?- V2：每 IP 60 req/min（超限返?`429`），Dashboard 轮询?cron 不受影响?
---


## 20. 示例：端到端最小流?
```bash
# 1) 启动服务（见 DEPLOYMENT.md?python run.py &
# 2) 跑分?curl -X POST http://localhost:8002/api/v1/run -H 'Content-Type: application/json' -d '{"projects":[{"name":"LayerX","sector":"L2","stage":"testnet","has_testnet":true,"has_points_program":true,"no_token_yet":true,"recent_funding":true}],"enable_llm":false}'
# 3) ?Top 项目
curl 'http://localhost:8002/api/v1/projects?label=FARM&limit=10'
# 4) 看详?curl http://localhost:8002/api/v1/project/a1b2c3d4-e5f6-5a7b-8c9d-0e1f2a3b4c5d
# 5) 重算
curl -X POST http://localhost:8002/api/v1/re-score/a1b2c3d4-e5f6-5a7b-8c9d-0e1f2a3b4c5d
```

---

## 21. interactions（参与记录）

### 21a. POST /api/v1/interactions

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

### 21b. GET /api/v1/interactions

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

### 21c. GET /api/v1/interactions/summary

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

### 21d. GET /api/v1/projects/{project_id}/interactions

列出指定项目的全部参与记录（等价于 `GET /interactions?project_id=...`）。

### 21e. PATCH /api/v1/interactions/{interaction_id}

更新参与记录（状态流转 / 结果 / 成本收益）。

**请求体**（部分字段）:
```json
{
  "status": "done",
  "outcome": "airdropped",
  "profit_usd": 890.0
}
```

### 21f. DELETE /api/v1/interactions/{interaction_id}

删除参与记录。返回 `{ "ok": true, "data": { "deleted": true, "id": 1 } }`。

---

## 22. participation-tasks

### 22a. GET /api/v1/participation-tasks

查询项目的参与任务清单（Galxe / Layer3 等平台任务）。

| 参数 | 类型 | 说明 |
|---|---|---|
| `project_id` | string | 按项目筛选 |

**响应 200**:
```json
{
  "ok": true,
  "data": [
    { "id": 1, "project_id": "uuid", "platform": "galxe", "url": "https://...", "title": "Daily check-in" }
  ]
}
```

---

## 23. quarantine（隔离队列）

### 23a. GET /api/v1/quarantine

列出隔离队列（采集失败 / 数据异常的原始记录）。

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `status` | string | pending | pending / resolved |
| `limit` | int | 50 | 1-200 |

### 23b. GET /api/v1/quarantine/{id}

查看隔离记录详情。

### 23c. PATCH /api/v1/quarantine/{id}

更新隔离记录状态（标记为已解决 / 降级）。

**请求体**:
```json
{ "status": "resolved", "resolved_at": "2026-07-26T08:00:00Z" }
```

---

## 24. watchlist（用户关注列表）

### 24a. GET /api/v1/watchlist

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

### 24b. POST /api/v1/watchlist

添加项目到关注列表。

**请求体**:
```json
{ "project_id": "uuid-here", "note": "值得关注" }
```

### 24c. DELETE /api/v1/watchlist/{project_id}

从关注列表移除项目。

---

## 25. funding（融资信息）

### 25a. GET /api/v1/projects/{project_id}/funding

查询项目融资记录。

**响应 200**:
```json
{
  "ok": true,
  "data": [
    { "id": 1, "round": "Seed", "amount_usd": 5000000, "date": "2026-06-01", "investors": "a16z" }
  ]
}
```

### 25b. PUT /api/v1/projects/{project_id}/funding

更新项目融资信息（编辑后触发重评）。

**请求体**:
```json
{ "funding": "5M Seed (a16z)", "funding_note": "2026-06" }
```

---

## 26. ai_brief（AI 简报）

### 26a. GET /api/v1/projects/{project_id}/ai-brief

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

### 26b. POST /api/v1/projects/{project_id}/ai-brief/regenerate

重新生成 AI 简报。

---

## 27. llm（LLM 状态）

### 27a. GET /api/v1/llm/status

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

## 28. webhook（Alchemy 事件推送）

### 28a. POST /api/v1/webhook/alchemy

Alchemy webhook 回调端点（接收链上事件推送）。

**请求头**: `X-Alchemy-Signature`（HMAC 签名验证）

### 28b. GET /api/v1/webhook/status

查询 webhook 配置状态。

**响应 200**:
```json
{
  "ok": true,
  "data": { "configured": false, "webhook_url": null }
}
```

---

## 29. auth（鉴权）

### 29a. POST /api/v1/auth/anonymous

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

## 30. settings（运行时配置）

### 30a. GET /api/v1/settings/config

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

## 31. archive（归档运行历史）

**管理员专属**（`/api/v1/archive` 在 `ADMIN_ONLY_PREFIXES` 内）：响应含各表真实
行数、保留期配置与调度 cron，属运维信息，与 `/settings` 同一口径。

### 31a. GET /api/v1/archive/runs

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
