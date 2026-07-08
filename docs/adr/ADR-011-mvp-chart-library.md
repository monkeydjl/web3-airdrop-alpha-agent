# ADR-011: MVP 前端 Dashboard 图表库选型 — Chart.js + 原生 JS

- **Status**: Accepted
- **Date**: 2026-07-08
- **Deciders**: 架构 / 前端
- **技术栈**：Chart.js 4.x, ECharts 5.x
- **影响面**：前端、构建流程、CDN 依赖

---

## 背景

ADR-003 已决策 MVP 使用单页 HTML+JS 零构建预览，但未明确图表库选型。`ENGINEERING_ROADMAP.md §9.3` 提到"CDN 引入轻量图表库（如 Chart.js）"，而 `FRONTEND_SPEC.md §5` 直接指定了 Chart.js。

需要正式决策 MVP 阶段使用哪个图表库，理由如下：

1. **Chart.js 与 ECharts 都有 CDN 版本**，都能零构建使用，但包体积、API 风格、渲染性能差异显著。
2. **Chart.js CDN 在国内访问可能不稳定**（已记录为 Roadmap 风险 #3），需评估是否需要切换备选。
3. **图表需求已明确**：MVP 只需要 doughnut（label 分布）、horizontal bar（赛道分布）、linear progress（heat_score）三种图表，复杂度低。
4. **V2 切 Next.js 时图表库可能切换**，MVP 的选型不应影响 V2 的技术选型自由。

## 决策

**MVP 阶段使用 Chart.js 4.x（CDN）**，具体约束如下：

- **版本**：Chart.js 4.4.x（锁定 patch 版本，通过 SRI hash 保证一致性）
- **引入方式**：CDN（`https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js`），加 SRI hash
- **图表类型**：仅使用 doughnut、bar、linear progress 三类图表，不引入 Chart.js 插件
- **回退方案**：若 Chart.js CDN 加载失败（网络问题），Dashboard 降级为纯文字统计卡片，不阻断使用
- **SRI hash 管理**：随 Chart.js 版本升级更新 `frontend/index.html` 中的 integrity hash，记录在 `DESIGN_REVIEW_CHANGELOG.md`

## 备选方案对比

| 备选方案 | 被否理由 |
| --- | --- |
| **ECharts** | 包体积 ~1MB（min），Chart.js 仅 ~200KB；MVP 仅需 3 种图表，ECharts 的丰富功能完全用不上；ECharts 依赖 `zrender` 渲染层，引入额外故障点 |
| **D3.js** | 声明式 API 学习曲线陡峭，不适合零构建 MVP 场景；无开箱即用的图表类型，需手动搭建 | 
| **ApexCharts** | 商业授权限制；社区较小，长期维护风险高 |
| **无图表库，纯 CSS** | 无法实现 doughnut 和交互式 bar 图，Dashboard 信息密度不足 |
| **Chart.js（本决策 ✅）** | 包体积最小（~200KB）、API 简洁、CDN 友好、MVP 三种图表类型均原生支持、开源（MIT）、社区活跃 |

**选中理由**：Chart.js 在 MVP 约束条件（零构建、CDN 引入、仅 3 种图表类型）下是最优选择。For ECharts 国内 CDN 更稳定这一仅有的优势，我们认为：
- MVP 演示场景网络中断是小概率事件
- 降级方案（纯文字统计卡片）可在 30 分钟内实现
- V2 迁 Next.js 时按需选择任意图表库

## 后果

### 正面
- `frontend/index.html` 零构建可预览，3 种图表均 Chart.js 原生支持
- CDN 升级只需改 URL + SRI hash，无需修改代码
- 文档 `FRONTEND_SPEC.md §5` 已明确指定 Chart.js，决策与现有设计一致

### 负面 / 限制
- Chart.js CDN 在国内部分地区访问延迟可能 >500ms，但不阻断页面加载（SRI `crossorigin` 属性允许降级）
- 如需高级图表示意（3D、地图、热力图），Chart.js 需要额外插件或无法满足——但 MVP 不需要
- V2 如切 ECharts（如因在国内部署），需要重写所有图表组件（Chart.js → ECharts API 不完全兼容）

### 需配套的工作
- [ ] `frontend/index.html` 引入 Chart.js CDN + SRI hash
- [ ] 实现降级方案：CDN 加载失败时显示纯文字统计卡片
- [ ] 在 `DESIGN_REVIEW_CHANGELOG.md` 记录此 ADR

### 迁移成本
- **Chart.js → ECharts（V2）**：约 2–3 人天（重写 3 个图表组件 + 响应式适配）
- **Chart.js → 其他库（V2）**：约 1–2 人天（因为仅 3 种图表，替换成本低）

---

## 关联

- **相关 ADR**：[ADR-003](ADR-003-single-page-html-mvp.md) — MVP 前端用单页 HTML
- **引用文档**：`docs/FRONTEND_SPEC.md §5`（图表规格）、`docs/ENGINEERING_ROADMAP.md §9.3`（技术实现）
- **Roadmap 风险 #3**（`ENGINEERING_ROADMAP.md §16.2`）：Chart.js CDN 国内访问不稳定
- **实现文件**：`frontend/index.html`
