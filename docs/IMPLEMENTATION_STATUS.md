# 实现现状表（Implementation Status）

> 引用：`W1_STATUS.md` / `W2_PROGRESS.md` / `W3_PROGRESS.md` / `W4_PROGRESS.md`、ADR-012、`.workbuddy/memory/MEMORY.md`
> 阶段：**W1–W4 已完成**（非规划阶段）
> 更新：2026-07-14
> 原则：以代码与进度文件为准；与旧设计表述冲突时，以本表 + 代码为准。
> Agent 会话记忆：`.workbuddy/memory/MEMORY.md` + `.workbuddy/memory/2026-07-14.md`

---

## 1. 运行约定（本地 vs 部署）

| 环境 | 前端 | 后端 API | 说明 |
|------|------|----------|------|
| **本地开发** | **3002**（`frontend-next`） | **8002** | 固定端口，避开常见 3000/8000 |
| **Docker** | 视 compose | **8002**（容器内外一致） | `API_PORT` 默认 8002 |
| 旧静态页 | `frontend/` 可仍用 3002 | — | **非主入口** |

关键文件：`Start.bat`、`Makefile`、`frontend-next/next.config.js`（rewrite → `127.0.0.1:8002`）、`backend/app/config.py`（CORS）。

---

## 2. 总览

| 域 | 状态 | 说明 |
|----|------|------|
| Bootstrap / 文档体系 | ✅ | P0–P2 51/51 |
| W1 基础设施 | ✅ | config / models / db / main |
| W2 Agent 核心 | ✅ | 分析 Agent + Orchestrator + Golden |
| W3 Dashboard | ✅ | 先 HTML，后迁 Next；Insights + feedback UI |
| W4 MVP 收尾 | ✅ | CI、seed、DefiLlama 联调、Start.bat、Next 主前端 |
| 采集多源全量 | 🟡 | 代码多源已有；联调以 DefiLlama 为主，其余依赖 key/开关 |
| 权重反馈校准 | 🟡 | 表与 API/UI 有；离线校准未成主线 |
| 生产硬化 | ⬜ | 鉴权、观测栈日常化、依赖安全升级 |

图例：✅ 已实现可用 · 🟡 部分实现 · ⬜ 未实现 / 仅设计

---

## 3. 后端模块

| 模块 | 路径 / 能力 | 状态 | 备注 |
|------|-------------|------|------|
| 配置 | `backend/app/config.py` | ✅ | 权重 Σ=1.0；`discovery_score_analysis_threshold=0.3`；`llm_discovery_score_threshold=0.7`；双调度 cron |
| DB | `backend/app/db.py` | ✅ | projects / logs / raw_projects / data_sources / project_signals / collection_logs / feedback / archive 等 |
| 统一响应 | `models.py` + routers | ✅ | `{ok, data, error}` |
| POST `/api/v1/run` | `routers/v1/run.py` | ✅ | 有 body → 手动 seed；无 body → 从 `raw_projects` 取未处理项评分 |
| GET projects / project | `routers/v1/projects.py` | ✅ | `page_size` 上限 **500**（W4 修复） |
| export / import | `routers/v1/export_import.py` | ✅ | |
| insights | `routers/v1/insights.py` | ✅ | |
| feedback | `routers/v1/feedback.py` | ✅ | 功能开关 `enable_feedback_system` |
| funding | `routers/v1/funding.py` + `services/funding.py` + `project_signals.py` | ✅ | GET/PATCH 手动融资 → `meta.signals`；可选 rescore |
| interactions | `routers/v1/interactions.py` | ✅ | 用户交互成本/收益记录 |
| participation-tasks | `routers/v1/participation.py` | ✅ | 规则生成可参与任务清单 |
| ai-brief | `routers/v1/ai_brief.py` | ✅ | 规则/可选 LLM 项目解读 |
| collections | `routers/v1/collections.py` | ✅ | sources / logs / trigger |
| Orchestrator | `agents/orchestrator*.py` | ✅ | 自研；多项目并发配置见 ADR-007 |
| 分析 Agent | narrative/team/risk/tokenomics/scorer | ✅ | 规则引擎默认 |
| CollectorAgent | `agents/collector.py` | ✅ | seed / registry / repository 多路径 |
| 采集器 | `collectors/*` | 🟡 | DefiLlama/GitHub/CoinGecko/Etherscan/CryptoRank 已联调；共享 `noise.py` denylist；分析入口跳过旧噪声 |
| 采集持久化 | `collectors/persistence.py` | ✅ | 批量写；unprocessed 查询；mark processed |
| 采集调度 | `collectors/scheduler.py` | ✅ | 与分析调度双开（非 testing）；cron 按源配置 |
| 分析调度 / handoff | `analysis_scheduler.py` + `pipeline_run.py` | ✅ | 成功项 mark processed；`COLLECTION_AUTO_RUN_ENABLED` 默认关 |
| 归档 | `archive.py` | ✅ | raw_projects 保留期默认 30 天 |
| 鉴权 / 多租户 | ADR-008 | ⬜ | MVP 无鉴权 |
| SQLite / PostgreSQL 双后端 | ADR-004 | ✅ | 默认 SQLite；设置 `DATABASE_URL` 后使用 PostgreSQL；`verify_postgres.py` 已验收；health 含 `db_backend`（不表示已完成生产部署） |
| Opportunity v2.0 Shadow | `opportunity/*` + `routers/v1/opportunity.py` | ✅ | `opportunity-v2.0` / `low-cost-curated-multiwallet-v1`；默认关闭、非权威；按项目 ID 确定性灰度并追加保存不可变快照 |
| 竞争度缓存 | ADR-010 | 🟡 | 规则在；缓存策略按阶段演进 |

---

## 4. 前端

| 项 | 状态 | 备注 |
|----|------|------|
| 主 Dashboard | ✅ Next.js 16 `frontend-next/` | React 19；Dashboard / project detail / insights / ops |
| API 客户端 | ✅ `lib/api.ts` | 默认 `/api/v1` + rewrite，避免 CORS |
| 项目详情 | ✅ | Agent 面板、反馈、AI 解读、任务、交互、**FundingPanel** |
| 旧 `frontend/index.html` | 🟡 保留 | 非主路径；ADR-003 由 ADR-013 演进 |
| 暗色 / 空态 / loading | 🟡 | 已有暗色；空态/loading 可持续打磨 |
| Chart.js | ✅ | ADR-011 |

---

## 5. 数据与评分

| 项 | 状态 | 权威文档 / 代码 |
|----|------|-----------------|
| 八维权重 + FARM≥65 | ✅ | ADR-006、`config` 权重；`DATA_SCORING_DICT` |
| FARM/WATCH/IGNORE | ✅ | 枚举英文；UI 中文 |
| 融资质量 v1.4 | ✅ | `funding_quality`/`funding_tier`；手动编辑主路径；RootData 可选 |
| meta.signals 持久化 | ✅ | `project_signals.py`；`rescore_all` 恢复 |
| Golden 回归 | ✅ | 测试目录 + `GOLDEN_TEST_CASES.md` |
| discovery_score 分级 | ✅ 配置+部分链路 | 见 `COLLECTION_ANALYSIS_HANDOFF.md` |
| 去重 / 归一化 | ✅ | `utils/normalize.py` |
| weight_changelog / 双跑校准 | 🟡 | 脚本+门禁有；样本≥200 后搜索 |
| Opportunity Shadow 决策 | ✅ | 旁路结果为非权威追加快照；`score-v1.4` 的 `projects.score/label` 仍是主决策，不得将 Shadow `public_label` 当成替代标签 |
| V3 Memory 系统 | ⬜ | Roadmap §24 |

---

## 6. 运维与质量

| 项 | 状态 |
|----|------|
| pytest（已验证基线） | ✅ 1,523 passed / 1 skipped，覆盖率 84.44% |
| CI `.github/workflows/ci.yml` | ✅ Python 3.13；push 支持 master/main/feat/**/fix/**/docs/**，PR 支持 master/main |
| seed `make seed` | ✅ |
| Opportunity Shadow 汇总 | ✅ `eligible`/`sampled`/`attempted`/`saved`/`failed`/`skipped` 六字段 |
| Opportunity Shadow 指标 | ✅ 五个指标族；仅有限 `result`、状态、标签和版本维度 |
| Health 灰度配置 | ✅ 暴露模型版本、Shadow 开关与采样率 |
| Docker 健康轮询 | ✅ compose healthcheck 使用有限 timeout、retries 与 start period |
| Prometheus 指标暴露 | 🟡 Shadow 指标已实现；其他目录仍有部分 counter/gauge |
| 完整 Grafana/Loki 日常使用 | ⬜ 配置存在，非默认必开 |
| Next 依赖安全告警 | 🟡 升级待办 |

---

## 7. 与旧文档的已知漂移（读文档时注意）

| 旧表述位置 | 旧内容 | 当前真相 |
|------------|--------|----------|
| `ENGINEERING_ROADMAP.md` 文首 | 「规划阶段」 | **W1–W4 已实现** |
| 多处 curl / 运维示例 | 曾写 `8000` | 已统一 **8002**（本地 + Docker） |
| `docs/00_index.md` §16 | 方向文档「手动输入定位」 | v2.0 **自动扫描**（ADR-012） |
| ADR-003 | 单页 HTML 为 MVP 前端 | **主前端已为 Next**（ADR-013） |
| `API_SPEC` Base URL | 8000 | 本地默认文档应注明 8002 |
| `01_product` Phase 勾选 | 部分仍 ⏳ | 以本表与 W* 进度为准 |

端口与阶段的**权威短表**以本文 §1–§2 为准；不必在每份历史文档全文改写，新增/修订文档时对齐本表。

---

## 8. 建议阅读顺序（新人 / Agent）

1. `.workbuddy/memory/MEMORY.md`
2. 本文 `IMPLEMENTATION_STATUS.md`
3. `SYSTEM_DIRECTION_CHANGE.md` + `COLLECTION_ANALYSIS_HANDOFF.md`
4. `DATA_SCORING_DICT.md` + `WEIGHT_CALIBRATION.md`
5. `API_SPEC.md` + `W4_PROGRESS.md`

---

## 9. 下一步设计/工程优先级（对齐产品）

1. ~~采集源 key 联调~~ ✅
2. ~~采集→分析交接~~ ✅
3. ~~噪声清洗 + denylist + purge~~ ✅
4. ~~评分 v1.1~~ ✅ FARM≥65
5. ~~反馈采集 UI + 开关默认开~~ ✅；样本≥200 后再做权重搜索（`feedback_snapshot.py`）
6. ~~Quarantine 全链路~~ ✅（列/写/释放 API + 分析跳过 + health 计数）
7. ~~API Key 鉴权~~ ✅（`API_KEY` 非空时 `X-API-Key` / Bearer）
8. ~~Next 安全升级~~ ✅ `next@16.2.10` + React 19；`npm audit` 0
9. ~~权重校准骨架~~ ✅ `calibrate_weights.py` / `weight_changelog` 表；门禁 200 样本
10. ~~手动融资编辑 + 重评~~ ✅ `FundingPanel` + `PATCH .../funding?rescore=true`（2026-07-14）

后续可选：列表「有融资信号」筛选、卡片 tier 徽章、CSV 扩融资列、样本≥200 权重搜索。

---

_文档版本：v1.1 · 2026-07-14_
