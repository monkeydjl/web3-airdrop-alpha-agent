# W3: Frontend Dashboard - 进度追踪

> 开始时间：2026-07-09
> 目标：按 `docs/FRONTEND_SPEC.md` 实现 MVP 单页 HTML Dashboard，并补充 Insights 聚合接口

---

## 📊 总体进度

**完成度**: 9/9 任务 (100%)

| 任务 | 状态 | 交付物 | 测试/验证 |
|-----|------|--------|----------|
| W3-01 页面结构设计 | ✅ | `frontend/index.html` 新架构 | 手动预览 |
| W3-02 Dashboard 首页 | ✅ | 统计条、图表、筛选、项目网格 | 本地预览 |
| W3-03 Project Detail | ✅ | 详情页、Score Ring、Agent 面板 | 本地预览 |
| W3-04 Insights 页 | ✅ | 最热叙事、高风险团队、分布 | 本地预览 |
| W3-04b Insights 聚合端点 | ✅ | `backend/app/routers/v1/insights.py` | 2/2 ✅ |
| W3-05 API/状态/错误提示 | ✅ | `apiFetch`、debounce、toast、loading | 单元测试 |
| W3-06 响应式/主题 | ✅ | 导航、暗色模式、响应式网格 | 手动预览 |
| W3-07 本地验证 | ✅ | 后端 + 前端同时启动预览 | 200 OK / CORS OK |
| W3-08 进度文档 | ✅ | 本文件 | - |
| W3-09 反馈闭环 UI | ✅ | Project Detail 反馈表单 + 统计 | API/前端验证 ✅ |

---

## ✅ 新增后端能力

### `GET /api/v1/insights`

- 聚合返回：
  - `total_projects`
  - `label_counts`（FARM/WATCH/IGNORE）
  - `sector_counts`
  - `hottest_narratives`（按 sector 聚合 `narrative.heat_score`）
  - `risky_teams`（按 `team_score` 推导 risk_level，列出 high/medium 团队）
- 端点注册在 `backend/app/main.py`。
- 测试：`backend/tests/api/test_insights.py`（使用临时 DB 隔离）。

### 其他后端调整

- `backend/tests/api/test_metrics.py`：修复 `_parse_counter` 在多 label 情况下可能拿到错误 series 的问题，现在按 `trigger="manual"` 精确匹配。

---

## ✅ 前端 Dashboard 能力

`frontend/index.html` 已重写为生产级单页 Dashboard，原测试界面保留为 `frontend/test.html`。

### Dashboard（`/`）

- 统计条：FARM / WATCH / IGNORE / Total
- Label 分布：Chart.js doughnut
- 赛道分布：Chart.js 横向 bar
- 筛选栏：label、sector、最低分数、关键词搜索、排序（防抖 300ms）
- Top 项目卡片网格（按 score 降序），点击进入详情
- 空态引导执行自动采集评分

### Project Detail（`#project/:id`）

- 标题 + sector/stage badge + label badge
- SVG Score Ring（0–100）
- Confidence 指示，低置信度显示 ⚠️ 提示
- 决策理由列表（+ / - / ! 前缀）
- 四个 Agent 明细卡：Narrative / Team / Risk / Tokenomics
- 「重新评分」按钮
- **反馈闭环 UI**：
  - 有用 / 没用 / 标签错了 / 结果预测正确 四种信号选择
  - 选择「标签错了」时展开正确 label（FARM/WATCH/IGNORE）下拉
  - 备注输入框
  - 提交后调用 `POST /api/v1/feedback`，成功 toast 并刷新统计
  - 顶部显示该项目历史反馈统计与最近 3 条备注

### Insights（`#insights`）

- 最热叙事排行（avg heat + 趋势箭头）
- 高风险团队聚类
- Label / Sector 迷你分布条

### 其他

- 浅色/暗色主题切换（localStorage 记忆）
- 响应式导航（桌面横向 / 移动汉堡菜单）
- 统一 Toast 错误/成功提示
- Skeleton loading 态

### 字段对齐说明

实现时发现 `FRONTEND_SPEC.md` 中部分字段名与当前 Agent 输出模型不一致。Dashboard 使用实际模型字段：

| Spec 字段 | 实际模型字段 |
|----------|------------|
| `team_json.risk_level` | 由 `team_score` 推导 |
| `team_json.flags` | `team_flags` |
| `risk_json.sybil_difficulty` / `farming_cost` | 当前模型未输出，未显示 |
| `tokenomics_json.unlock_pressure` / `risk` | 实际为 `unlock_penalty` |

---

## ✅ 测试与验证

### 后端测试

```bash
531 passed, 1 skipped, 1501 warnings in 41.90s
```

- 新增 `tests/api/test_insights.py` 2 个用例通过。
- `test_metrics.py` 修复后通过。
- 覆盖率：**85%**。

### 本地预览

- 后端：`APP_ENV=testing uvicorn app.main:app --host 127.0.0.1 --port 8002`
- 前端：`python -m http.server 3002 --bind localhost`
- CORS：`http://localhost:3002` 已允许。
- 通过 `POST /api/v1/run` 预置 3 个示例项目，Dashboard 可正常加载。
- 反馈闭环验证：
  - 后端 `POST /api/v1/feedback` 返回 `feedback_id` ✅
  - 后端 `GET /api/v1/feedback/{project_id}` 返回统计与最近反馈 ✅
  - Project Detail 页反馈表单已渲染，提交后刷新统计 ✅
- 预览地址：`http://localhost:3002`

### 修复：点击「运行自动采集评分」没反应

- 根因：前端传 `{projects: []}` 触发 Pydantic `min_length=1` 校验，后端返回 422，前端 toast 未正确展示错误。
- 修复：
  - 后端 `backend/app/routers/v1/run.py`：移除 `RunRequest.projects` 的 `min_length=1`，允许空列表表示「自动采集评分」。
  - 前端 `frontend/index.html`：`runAutoPipeline()` 现在先调用 `/collections/sources` 获取已启用源，再逐个触发 `/collections/{source_id}/trigger`，最后调用 `/run` 评分；单个源失败不影响后续源。
  - 测试：`backend/tests/api/test_run.py` 的 `test_run_empty_projects_fails` 改为 `test_run_empty_projects_triggers_auto_collection`，验证空列表走自动采集路径。
- 验证：
  - 空 `projects` 调用 `/run` 返回 200 ✅
  - `/collections/sources` 返回已注册源 ✅
  - `/collections/defillama/trigger` 返回 200 ✅


---

## 🎯 下一步建议

1. **真实数据联调**：接入 DefiLlama/GitHub/CoinGecko/Twitter 等采集器的真实 API key，观察 Dashboard 数据质量。
2. **前端构建迁移**：MVP 验证完成后，按 roadmap V2 迁移到 Next.js + Tailwind。
3. **权重校准闭环**：收集 ≥200 条 feedback 后，实现 `backtest.py` 与权重灰度发布机制（Roadmap W11）。
4. **历史时间线**：V3 扩展 project_history 数据展示。

---

_进度报告：v3.0 · 2026-07-09_
