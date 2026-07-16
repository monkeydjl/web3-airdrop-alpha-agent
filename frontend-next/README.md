# Airdrop Alpha — Next.js Dashboard

Next.js **16** App Router + React **19** + Tailwind CSS 的专业运营前端。

## 页面

| 路由 | 说明 |
|------|------|
| `/` | Dashboard：统计、图表、筛选、卡片/列表、一键采集评分 |
| `/project/[id]` | 详情：Score 环、理由 chips、四 Agent 面板、反馈校准 |
| `/insights` | Insights：标签/赛道、FARM 榜、叙事热度、风险团队 |
| `/ops` | 运维：采集源触发、隔离区释放、仅评分 |

## 启动

```bash
cd frontend-next
npm install
npm run dev
```

- 前端：http://localhost:3002
- API rewrite → `http://127.0.0.1:8002`（`next.config.js`）

```bash
cd backend
uvicorn app.main:app --host 127.0.0.1 --port 8002
```

## 主题

右上角切换浅色 / 暗色（`localStorage: aa-theme`）。

## 构建

```bash
npm run build
npm start
```
