# 前端 UI 设计规范

> 配套文档：ENGINEERING_ROADMAP.md §9。本文档定义 Dashboard 的风格、页面、组件、配色、图表、字段映射与交互，供 MVP 单页实现与 V2 Next.js 实现直接照做。

---

## 1. 总体风格

- **主题**：浅色专业风为默认；提供暗色切换（跟随系统或手动）。
- **字体**：系统无衬线栈 `-apple-system, "Segoe UI", Roboto, "PingFang SC", "Microsoft YaHei", sans-serif`。
- **布局**：顶部导航栏 + 居中内容区（最大宽度 1200px）；卡片化、留白充足、信息层级清晰。
- **圆角/阴影**：卡片 `border-radius:12px`，轻阴影 `0 1px 3px rgba(0,0,0,.08)`。

---

## 2. 配色规范

| 语义 | 浅色色值 | 用途 |
| --- | --- | --- |
| FARM | `#16a34a` | score ≥ 65 徽章 / 强调（v1.1） |
| WATCH | `#d97706` | 50–69 徽章 |
| IGNORE | `#6b7280` | < 50 徽章 |
| risk high | `#dc2626` | 高风险标记 |
| risk medium | `#d97706` | 中风险 |
| risk low | `#16a34a` | 低风险 |
| 主色 | `#2563eb` | 按钮 / 链接 / 导航高亮 |
| 背景 | `#f8fafc` | 页面底色 |
| 卡片 | `#ffffff` | 卡片底 |
| 文字主 | `#0f172a` | 标题/正文 |
| 文字次 | `#64748b` | 辅助说明 |

**暗色（可选）**：背景 `#0f172a`、卡片 `#1e293b`、文字 `#e2e8f0`，语义色不变。

> **色值权威说明（MVP vs V2）**：本表色值为 **MVP 单页 HTML Dashboard 的实际实现色板**。V2 Next.js Dashboard 改用 [DESIGN_TOKENS.md](DESIGN_TOKENS.md) 定义的品牌色板（主色 `#6366F1`、FARM `#10B981`、WATCH `#F59E0B`、IGNORE `#EF4444` 等）。两者语义一致、具体色值不同，MVP 落地以本表为准，V2 以 DESIGN_TOKENS 为准，互不覆盖。

---

## 3. 页面结构

### 3.1 Dashboard（`/`）
- **统计条**：FARM / WATCH / IGNORE 三个计数卡片（色徽章）。
- **Score 分布**：环形图（label_counts）。
- **赛道分布**：横向条形图（sector_counts）。
- **Top 项目**：卡片网格，按 `score` 降序。
- **筛选栏**：label 下拉、sector 下拉、关键词搜索框。
- **排序**：默认 score 降序。

### 3.2 Project Detail（`/project/:id`）
- 标题：`name` + `sector` 徽章 + `stage` 徽章。
- 大号 Score 圆环（0–100）+ Label 徽章 + recommendation。
- **Confidence 指示**：confidence 值以环形图/百分比展示；confidence < 0.5 时显示警告图标，悬停显示 "X/4 个分析 agent 成功"。
- `reason` 列表（标签 chips）：正向信号绿色前缀（+），负向信号红色前缀（-），缺失数据标记黄色前缀（!）。
- **四个 Agent 明细卡**（可展开/折叠）：
  - **Narrative**：`stage`、`heat_score`（进度条）、`timing`。
  - **Team**：`score`、`risk_level`（色）、`flags`。
  - **Risk**：`sybil_difficulty`、`farming_cost`、`token_risk`。
  - **Tokenomics**：`vc_share`、`team_share`、`unlock_pressure`、`risk`。
- **数据来源面板**（V2）：可折叠面板，显示每个来源名称、reliability、fetched_at；来源按 reliability 排序；未命中的来源显示「未命中」。
- **Agent 执行记录**（V2）：显示 agent 执行时间线，每个 agent 显示状态（成功/失败/回退）、耗时；失败的 agent 显示错误类型；LLM 回退时显示「AI-enhanced」标记。
- 「重新评分」按钮 → `POST /re-score/{id}`（V2 前加 loading 态 + 防重复点击）。

### 3.2a V2 反馈区（Project Detail 底部）
- 「👍 有用」/「👎 无用」按钮：点击后按钮状态变化（已反馈），可选填写备注（最长 500 字符）。
- 「标注结果」入口：选项 airdropped / not_airdropped / pumped / dumped，标注后显示「已标注」状态，支持修改。

### 3.2b V3 扩展区（Project Detail 底部）
- **项目历史时间线**：显示 stage 变化、score 变化、label 变化节点，支持查看历史快照。
- **参与 Checklist**（FARM 项目）：交互类型、预估成本、频率建议，支持标记步骤完成状态。

### 3.3 Insight（`/insights`）
- 最热叙事排行（hottest_narratives）：每个赛道显示 heat_score、项目数、趋势箭头。
- 高风险团队聚类（risky_teams）。
- label / sector 分布。
- 赛道热度趋势图（V2）。

### 3.4 用户/Admin 页面（V2/V3）
- **Auth 页面**（V2）：匿名 token 自动获取（首次访问时静默 `POST /api/v1/auth/anonymous`），无注册页面。
- **用户偏好页**（V3）：赛道偏好加权、风险容忍度、通知设置、语言/主题切换。
- **数据导出页**（V3）：一键导出用户数据 JSON。
- **Admin 面板**（V2）：审计日志列表（action/user/时间），支持 action/user 筛选，日志只读不可删除。
- **Admin 面板**（V3）：用户管理（列表/禁用/改角色）、API Key 管理（创建/撤销）。

---

## 4. 组件规格

| 组件 | 说明 |
| --- | --- |
| `StatCard` | 统计条卡片：标签 + 数值 + 色条 |
| `ProjectCard` | 项目卡：name、sector、score 徽章、前 2 条 reason；点击跳详情 |
| `ScoreBadge` | 按 label 着色的圆角徽章 |
| `ScoreRing` | SVG/Chart.js 圆环，显示 0–100 |
| `DistributionChart` | doughnut（label） / bar（sector） |
| `AgentPanel` | 标题 + 键值列表 + 风险色 |
| `FilterBar` | label 下拉 + sector 下拉 + 搜索 |
| `Toast` | 错误/成功轻提示 |

---

## 5. 图表（Chart.js）

- **label 分布**：doughnut，配色 FARM/WATCH/IGNORE 语义色。
- **赛道分布**：horizontal bar（sector_counts）。
- **heat_score**：线性 progress / bar。
- 全局：统一调色板（见 §2），禁用 3D 与过多动画。

---

## 6. 字段映射表

| UI 元素 | API 字段 |
| --- | --- |
| 项目名 | `name` |
| 赛道 | `sector` |
| 阶段 | `stage` |
| 综合评分 | `score` |
| 建议 | `label` / `recommendation` |
| 置信度 | `confidence` |
| 决策理由 | `reason[]` |
| 叙事热度 | `narrative_json.heat_score` |
| 叙事时点 | `narrative_json.timing` |
| 团队风险 | `team_json.risk_level` |
| 团队标签 | `team_json.flags` |
| Sybil 难度 | `risk_json.sybil_difficulty` |
| 参与成本 | `risk_json.farming_cost` |
| 代币风险 | `risk_json.token_risk` |
| VC 占比 | `tokenomics_json.vc_share` |
| 团队占比 | `tokenomics_json.team_share` |
| 解锁压力 | `tokenomics_json.unlock_pressure` |

> 完整字段含义见 `DATA_SCORING_DICT.md`。

---

## 7. 交互

- 点击 `ProjectCard` → 跳转 Detail。
- 筛选栏变更 → 实时重拉 `GET /projects`（防抖 300ms）。
- 详情页「重新评分」→ loading → 刷新该卡片数据。
- 错误 → 内联提示 / Toast。
- 空态 → 无项目时引导执行 `POST /run`。
- 加载态 → 骨架屏 / spinner。
- **反馈交互**（V2）：点击「有用/无用」→ 按钮状态变化（已反馈）；标注结果 → 下拉选择。
- **Auth 交互**（V2/V3）：匿名 token 静默获取（首次访问）→ 存 localStorage，有效期 30 天；401 时重新获取。
- **Admin 交互**（V2）：审计日志可滚动列表。

---

## 8. 响应式

| 视口 | 布局 |
| --- | --- |
| 桌面 ≥1024px | 项目网格 3 列 |
| 平板 640–1023px | 2 列 |
| 移动 <640px | 1 列，导航折叠为汉堡菜单 |

---

## 9. 技术实现

- **MVP**：单页 `frontend/index.html` + 原生 `fetch` + Chart.js（CDN）+ 内联 CSS，**零构建**直接打开预览。API base 默认同源 `/api/v1`；跨域时需后端开启 CORS。
- **V2**：Next.js 14 App Router + Tailwind CSS + TanStack Query；路由 `/`、`/project/[id]`、`/insights`、`/admin/audit`；组件化、SSR、类型安全（复用 Pydantic 模型生成 TS 类型）。
- **V2 鉴权**：前端首次访问静默 `POST /api/v1/auth/anonymous` 获取匿名 token → 存 localStorage → 后续请求 `Authorization: Bearer <token>`。Admin 页面由管理员手动配置 API_KEY。
- **i18n 集成**（V2）：`i18next` + `react-i18next`，翻译文件 `frontend/locales/{en,zh}.json`，语言选择器在顶部导航栏右侧。

---

## 10. 无障碍

- 颜色不单独承载信息（配合文字/图标）。
- 语义化标签、图片 `alt`、`aria-label`。
- 键盘可达（Tab 聚焦、Enter 激活）。
- 对比度满足 WCAG AA。

---

## 11. 国际化（i18n）

> V2 起支持中/英双语切换，MVP 可预留结构。

### 11.1 语言检测优先级
1. URL 参数 `?lang=zh` 或 `?lang=en`
2. localStorage 用户偏好
3. 浏览器 `navigator.language`
4. 默认英语（en）

### 11.2 翻译键命名规范
```
<scope>.<element>.<type>
```
示例：
- `dashboard.title` → "Web3 Airdrop Alpha Dashboard"
- `project.score` → "Score"
- `project.label.FARM` → "FARM"
- `filter.sector` → "Sector"
- `error.notFound` → "Project not found"

### 11.3 实现方案
- **MVP**：单语言（英语），所有字符串硬编码
- **V2**：引入 `i18next` + `react-i18next`（Next.js）或自定义轻量字典（单页 HTML）
- 翻译文件位置：`frontend/locales/en.json`、`frontend/locales/zh.json`
- 语言切换器：顶部导航栏右侧下拉

### 11.4 注意事项
- 日期/时间格式：UTC 存储，按用户时区显示
- 数字格式：score 0-100 整数，heat_score 0-1 浮点
- 避免字符串拼接：用模板变量 `"Score: {score}"` 而非 `"Score: " + score`
- 中文文案需专业翻译（避免机翻），关键术语保留英文（FARM/WATCH/IGNORE）
