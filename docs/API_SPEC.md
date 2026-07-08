# API 详细规范（FastAPI）

> 配套文档：ENGINEERING_ROADMAP.md §8。本文档给出每个端点的请求/响应样例、错误码、鉴权设计与数据模型，供前后端与测试对齐。

---

## 1. 基础信息

| 项 | 值 |
| --- | --- |
| Base URL | `http://<host>:8000`（本地默认） |
| API 前缀 | `/api/v1` |
| 内容类型 | `application/json; charset=utf-8` |
| 时间格式 | UTC 时间戳（`YYYY-MM-DD HH:MM:SS`） |
| 文档 | Swagger `/docs`、OpenAPI `/openapi.json` |

### 1.1 统一响应包络
所有端点返回统一结构：
```json
{ "ok": true,  "data": <任意>, "error": null }
```
失败：
```json
{ "ok": false, "data": null,  "error": { "code": 404, "message": "project not found" } }
```

---

## 2. 鉴权

- **MVP**：无鉴权（仅限本地/内网使用）。
- **V2**：Bearer Token。请求头 `Authorization: Bearer <API_KEY>`；`API_KEY` 来自环境变量。缺失或错误返回 `401`。
- `/health` 与 Swagger 文档无需鉴权。

---

## 3. 端点总览

| 方法 | 路径 | API 版本 | 阶段 | 说明 |
| --- | --- | --- | --- | --- |
| POST | `/api/v1/run` | v1 | MVP | 触发一次完整分析 pipeline（collect→analyze→score→写库） |
| GET | `/api/v1/projects` | v1 | MVP | 项目列表（支持筛选/排序/分页） |
| GET | `/api/v1/project/{id}` | v1 | MVP | 单项目完整详情 |
| POST | `/api/v1/re-score/{id}` | v1 | MVP | 用最新规则/数据对该项目重算评分 |
| GET | `/api/v1/insights` | v1 | MVP（基础聚合）/ V2（增强） | 聚合洞察（MVP 返回 label/sector 计数等基础聚合，V2 接入实时热度与团队聚类） |
| POST | `/api/v1/feedback` | v1 | V2 | 提交用户反馈（useful/useless/wrong_label + outcome） |
| GET | `/api/v1/feedback` | v1 | V2 | 查询用户反馈（支持 project_id 过滤） |
| POST | `/api/v1/events` | v1 | V2 | 提交隐式行为埋点（click/expand/feedback 等，V2 起） |
| GET | `/api/v1/audit` | v1 | V2 | 查询审计日志（action/user 过滤，V2 鉴权） |
| POST | `/api/v1/auth/anonymous` | v1 | V2 | 获取匿名用户 token（Dashboard 首次访问） |
| GET | `/api/version` | — | MVP | 版本元信息（当前/最新/Deprecated/Sunset） |
| GET | `/health` | — | MVP | 健康检查（无版本，基础设施 API） |

> 所有业务端点当前均为 `/api/v1`（首个稳定版）。V2 发布后，该表将增加 `/api/v2/*` 行并标注 v1 为 Deprecated。详见 [ENGINEERING_ROADMAP.md §26](ENGINEERING_ROADMAP.md)。

---

## 4. POST /api/v1/run

触发一次完整分析。MVP 同步执行（项目量小）；V2 改为后台任务并返回 `task_id`。

**请求体**
```json
{
  "source": "all",   // all | seed | defillama | cryptorank
  "limit": 50        // 最大分析项目数（可选，默认 50）
}
```

**响应 200**（含部分失败信息）
```json
{
  "ok": true,
  "data": {
    "analyzed": 23,
    "inserted": 18,
    "updated": 5,
    "failed": 0,
    "errors": [],
    "top_id": "a1b2c3d4",
    "top_score": 83,
    "elapsed_ms": 1240
  }
}
```

> 注：`failed` 表示因超时/异常未写入的项目数；`errors` 数组包含每个失败项目的 `project_id` 与 `reason`（如 `{"project_id":"xxx", "reason":"timeout"}`）。部分失败时 `ok` 仍为 `true`（pipeline 未完全崩溃），`data.failed > 0` 表明有项目丢失。

**错误**
- `400`：`source` 非法枚举。
- `500`：agent 执行失败（body 含 `error.message` 与定位信息）。

**cURL**
```bash
curl -X POST http://localhost:8000/api/v1/run \
  -H 'Content-Type: application/json' \
  -d '{"source":"seed","limit":50}'
```

---

## 5. GET /api/v1/projects

**Query 参数**

| 参数 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `label` | string | - | 过滤 `FARM`/`WATCH`/`IGNORE`；支持多选（逗号分隔） |
| `sector` | string | - | 过滤赛道，如 `L2`/`Restaking`；支持多选（逗号分隔） |
| `stage` | string | - | 过滤项目阶段 `testnet`/`mainnet`/`ideation`；支持多选（逗号分隔） |
| `search` | string | - | 项目名称模糊匹配（大小写不敏感） |
| `limit` | int | 100 | 返回条数，上限 500 |
| `order` | string | `DESC` | `DESC`/`ASC`（按 score） |

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

**错误**：`400` 非法 `order`/`label` 值。

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

**错误**：`404` 项目不存在。
```json
{ "ok": false, "data": null, "error": { "code": 404, "message": "project not found" } }
```

---

## 7. POST /api/v1/re-score/{id}

用最新规则/数据对该项目重算评分（不重新采集，仅重跑 analyze+score）。

**路径参数**：`id`

**响应 200**：更新后的完整 `ProjectRecord`（结构同 §6）。

**错误**：`404` 项目不存在；`500` 重算失败。

---

## 8. GET /api/v1/insights

**响应 200**
```json
{
  "ok": true,
  "data": {
    "label_counts":       { "FARM": 5, "WATCH": 12, "IGNORE": 6 },
    "score_distribution": { "0-49": 6, "50-69": 12, "70-100": 5 },
    "hottest_narratives": [ { "sector": "Restaking", "heat_score": 0.82, "timing": "early" } ],
    "risky_teams":        [ { "name": "LayerX", "risk_level": "medium", "flags": ["previous failed project"] } ],
    "sector_counts":      { "L2": 8, "Restaking": 6, "DeFi": 9 }
  }
}
```

> MVP 由 `projects` 表聚合得出；V2 接入实时热度与团队聚类后增强。

---

## 9. POST /api/v1/feedback

提交用户对项目的反馈（显式反馈回流，V2 起支持）。

**请求体**
```json
{
  "project_id": "a1b2c3d4-e5f6-5a7b-8c9d-0e1f2a3b4c5d",
  "signal": "useful",
  "note": "该项目确实有空投，已参与",     // 可选，最长 500 字符
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

**错误**：`400` 非法 signal/outcome 枚举；`404` 项目不存在。

---

## 10. GET /api/v1/feedback

查询用户反馈（供 Dashboard 展示或数据校准使用）。

**Query 参数**

| 参数 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `project_id` | string | - | 过滤特定项目 |
| `signal` | string | - | 过滤 `useful`/`useless`/`wrong_label`/`correct_outcome` |
| `outcome` | string | - | 过滤 `airdropped`/`not_airdropped`/`pumped`/`dumped` |
| `limit` | int | 50 | 返回条数，上限 200 |

**响应 200**
```json
{
  "ok": true,
  "data": [
    { "id": 1, "project_id": "uuid", "signal": "useful", "outcome": "airdropped", "note": "已参与", "created_at": "2026-07-08 08:00:12" }
  ]
}
```

---

## 11. GET /api/v1/audit

查询审计日志（记录关键操作：run 触发、配置变更、权重切换）。

> MVP 无鉴权（本地使用）；V2 需 API_KEY 鉴权。

**Query 参数**

| 参数 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `action` | string | - | 过滤 `run`/`re-score`/`config_change`/`weight_change` |
| `user` | string | - | 过滤触发者（system/手动/API key 名） |
| `limit` | int | 50 | 返回条数，上限 200 |

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

提交隐式行为埋点（V2 起）。前端在 Dashboard 交互时调用，用于后续反馈校准与个性化排序。

**请求体**
```json
{
  "project_id": "a1b2c3d4-e5f6-5a7b-8c9d-0e1f2a3b4c5d",  // 可选，全局事件如 page_view 可省略
  "event_type": "expand",                                // click|expand|feedback|filter_change|page_view
  "detail": { "duration_ms": 1200, "section": "reason" }   // 事件详情 JSON，按 event_type 自定义
}
```

**响应 200**
```json
{ "ok": true, "data": { "id": 1, "event_type": "expand", "created_at": "2026-07-08 08:00:12" } }
```

**错误**：`400` 非法 `event_type`。

---

## 14. POST /api/v1/auth/anonymous

获取匿名用户 token（V2 起）。Dashboard 首次访问时调用，无需鉴权。

**请求体**
```json
{}
```
或
```json
{ "client_id": "optional-stable-id" }  // 可选，用于同一设备/浏览器稳定关联
```

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

> Token 有效期 30 天，过期后 Dashboard 自动静默刷新。

---

## 15. GET /api/version

版本元信息，供客户端/前端判断是否需要迁移。

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

## 16. 数据模型（概要，详见 DATA_SCORING_DICT.md）

- `ProjectRecord`：`id,name,url,sector,stage,score,label,recommendation,confidence,reason[],narrative_json,team_json,risk_json,tokenomics_json,lineage,source,created_at`
- `NarrativeResult` / `TeamResult` / `RiskResult` / `TokenomicsResult` / `ScoreResult`：见各 Agent 输出字典。

---

## 17. 版本管理

- 当前 API 版本：**v1**（稳定版）。
- 版本元端点：`GET /api/version` 返回当前版本信息（当前/最新/已弃用/已下架版本列表）。
- 版本策略与弃用流程详见 [ENGINEERING_ROADMAP.md §26](ENGINEERING_ROADMAP.md)。
- 同一大版本内保证向后兼容（字段仅增不减，响应仅扩不缩）。V2 发布时 v1 进入 Deprecated 状态，至少 90 天弃用窗口。
- 弃用期间旧版响应头含 `Deprecation: true`、`Sunset` 日期与 `Link` 迁移指引。

---

## 18. 错误码表

| 状态码 | 含义 | 触发场景 |
| --- | --- | --- |
| 400 | Bad Request | 参数非法（枚举/类型错误） |
| 401 | Unauthorized | V2 缺失/错误 API Key |
| 404 | Not Found | `id` 不存在 |
| 422 | Validation Error | Pydantic 校验失败（FastAPI 自动） |
| 500 | Internal Error | agent 执行异常 / DB 不可写 |

---

## 19. 速率限制

- MVP：不限制。
- V2：每 IP 60 req/min（超限返回 `429`），Dashboard 轮询与 cron 不受影响。

---


## 20. 示例：端到端最小流程

```bash
# 1) 启动服务（见 DEPLOYMENT.md）
python run.py &
# 2) 跑分析
curl -X POST http://localhost:8000/api/v1/run -H 'Content-Type: application/json' -d '{"source":"seed"}'
# 3) 取 Top 项目
curl 'http://localhost:8000/api/v1/projects?label=FARM&limit=10'
# 4) 看详情
curl http://localhost:8000/api/v1/project/a1b2c3d4-e5f6-5a7b-8c9d-0e1f2a3b4c5d
# 5) 重算
curl -X POST http://localhost:8000/api/v1/re-score/a1b2c3d4-e5f6-5a7b-8c9d-0e1f2a3b4c5d
```
