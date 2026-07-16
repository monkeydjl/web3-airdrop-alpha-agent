# ADR-003: MVP 前端用单页 HTML

- **Status**: Accepted（主路径已由 [ADR-013](ADR-013-nextjs-primary-frontend.md) 演进；本文保留为历史决策与 `frontend/` 静态原型说明）
- **Date**: 2026-07-08
- **Deciders**: 架构 / 前端

## 背景

Next.js 正式 Dashboard 开发成本高（构建链、组件化、SSR 配置），MVP 需快速可预览以验证字段映射与交互逻辑。
MVP 聚焦后端 pipeline 与评分正确性，前端只需验证 API 契约。

## 决策

MVP 用**单页 HTML+JS（CDN Chart.js）**零构建预览：
- `frontend/index.html` + 原生 `fetch` + 内联 CSS
- CDN 引入 Chart.js（加 SRI hash，见 §21.3）
- API base 默认同源 `/api/v1`；跨域时后端开 CORS

正式 Next.js 14 Dashboard 在 V2 完成。

## 理由

| 备选 | 否决理由 |
| --- | --- |
| MVP 直上 Next.js | 构建成本高；MVP 阶段后端契约仍在迭代，前端跟着改两遍 |
| 用 Vue/Svelte 单页 | 引入构建工具链，违背"零构建预览"目标 |
| **单页 HTML+JS（本决策）** | 浏览器直接打开即可预览；验证字段映射足够 |

## 后果

- 需保证 API 字段契约稳定（FRONTEND_SPEC §6），V2 迁 Next.js 时仅替换视图层。
- MVP 不引入前端构建工具链；CSS/JS 内联或同目录静态文件。
- 单页 HTML 不做复杂状态管理；筛选/分页直接重拉 API。
- V2 切 Next.js 时，单页 HTML 保留作为"快速演示"备选入口。
- 无障碍（a11y）基础要求仍需满足（FRONTEND_SPEC §10），不因单页降标。
