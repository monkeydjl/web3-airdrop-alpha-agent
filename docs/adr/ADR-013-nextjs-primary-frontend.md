# ADR-013: 主前端演进为 Next.js（App Router）

- **Status**: Accepted
- **Date**: 2026-07-13
- **Deciders**: 前端 / 架构 / 产品
- **技术栈**: Next.js 16 App Router、React 19、Tailwind、Chart.js（自 14 升级）
- **影响面**: 前端入口、部署、CORS/API 代理、ADR-003
- **Supersedes（演进）**: [ADR-003](ADR-003-single-page-html-mvp.md) 中「单页 HTML 作为唯一 MVP 前端」的主路径表述；ADR-003 仍保留为历史决策与静态原型说明

---

## 背景

ADR-003 决定 MVP 使用单页 HTML+JS 以零构建预览 Dashboard。W3 按该决策交付 `frontend/index.html`。W4 已落地 `frontend-next/`（Next.js 14），并由 `Start.bat` / 本地开发默认启动 Next（端口 **3002**），通过 rewrite 访问后端 **8002**。

若继续以 ADR-003 为「当前前端架构」唯一表述，会导致：

- 新人按 HTML 路径开发，与主入口不一致；
- 部署与 CORS 策略文档混乱；
- Chart.js / 路由 / 后续用户系统（ADR-008）与 App Router 集成路径不清晰。

---

## 决策

1. **主前端**为 `frontend-next/`（Next.js 16 App Router + React 19 + Tailwind；2026-07 自 14 升级）。
2. **本地默认端口**：前端 3002；API 经 Next rewrite 到 `http://127.0.0.1:8002`（`next.config.js`）。
3. **旧 `frontend/` 单页**：保留作原型/对照/低依赖预览，**非**产品主路径；不再作为新功能默认落点。
4. **图表**：继续 ADR-011（Chart.js），在 React 组件中封装，不强制更换库。
5. **V2+** 用户系统、鉴权回调、多页路由均在 Next 上扩展；不在 HTML 单页并行实现完整功能。

---

## 理由

| 备选 | 否决理由 |
|------|----------|
| 长期只维护单页 HTML | 路由/状态/鉴权/组件化成本高，与 V2 规格冲突 |
| 立即删除 `frontend/` | 仍有测试与历史对照价值；删除非必须 |
| 另起 Vue/纯 SPA | 无收益；已投入 Next |
| **Next 为主 + HTML 保留（本决策）** | 对齐已实现路径，保留轻量回退 |

---

## 后果

- 文档与 MEMORY 以 Next 为启动说明；`IMPLEMENTATION_STATUS.md` 登记前端状态。
- 生产构建：`frontend-next` 的 `next build` / Node 运行或静态导出策略在 DEPLOYMENT 中逐步对齐（若尚未写清，以本 ADR 为意图）。
- 安全：关注 Next 依赖 CVE，升级 patched 版本后再标生产就绪。
- ADR-003 标记为被本 ADR 在「主路径」上演进，原文保留。

---

## 关联

- ADR-003 单页 HTML MVP
- ADR-011 Chart.js
- ADR-008 用户系统（前端落点）
- `docs/FRONTEND_SPEC.md`、`frontend-next/README.md`、`W4_PROGRESS.md`
