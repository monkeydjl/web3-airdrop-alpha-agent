# W4/W5 进度 — MVP 收尾、真实采集联调、Next.js 迁移准备

**日期**: 2026-07-09
**状态**: 已完成

---

## 1. MVP 收尾（W4）

### 1.1 GitHub Actions CI 流水线
- **文件**: `.github/workflows/ci.yml`
- **改动**:
  - Python 版本从 3.11 升级到 3.13
  - 为各 job 设置 `working-directory: backend`
  - 修复 ruff 路径：`ruff check app tests ../scripts`
  - 修复 pytest 路径和 coverage 报告路径
  - 保留 Docker build smoke test

### 1.2 种子数据脚本
- **文件**: `backend/scripts/seed.py`
- **功能**:
  - 幂等插入 3 个示例项目（Nova L2 / DeFi Vault / Pixel Pets）
  - 同时写入 `raw_projects` 和 `projects`
  - 支持 `DATABASE_PATH` 环境变量覆盖
  - 通过 `make seed` 调用
- **验证**: 用独立测试 DB 运行成功，3 raw + 3 projects 已插入

### 1.3 文档与端口一致性
- **修复**:
  - `frontend/README.md`: `python -m http.server 3000` → `3002`
  - `README.md`: 补充 `make seed` 说明
  - `Makefile`: `dev` 端口 `8000` → `8002`
- **保留未改**:
  - `DEPLOYMENT.md` / `docker-compose.yml` 中 Docker 默认端口 `8000`（部署端口与本地开发端口 8002 独立）

### 1.4 Start.bat 一键启动修复
- **问题**:
  - `backend/requirements.txt` 中 `uvicorn==0.35.6` 不存在、`pydantic==2.10.8` 被 yanked，导致 `pip install -r requirements.txt` 失败。
  - 缺少 `apscheduler`、`prometheus-client` 等运行时依赖。
  - 启动旧版 `frontend/index.html` 的 Python HTTP 服务，而非 Next.js。
  - `if not exist "venv\"` 和 `if not exist "node_modules\"` 在批处理中因 `\"` 转义导致语法错误（`... was unexpected at this time`）。
- **修复**:
  - 重写 `backend/requirements.txt`：改为最低版本约束，并补充 `apscheduler`、`prometheus-client` 等缺失依赖。
  - 修改 `Start.bat`：
    - 前端改为进入 `frontend-next` 运行 `npm run dev`（端口 3002）。
    - 检查 `node_modules` 不存在时自动 `npm install`。
    - 修正 `venv` / `node_modules` 目录判断语法。
    - fallback 安装命令同步包含 `apscheduler`、`prometheus-client`。
- **验证**: 双击 `Start.bat` 后 6 步全部 `[OK]`，后端 8002、前端 3002 均正常监听，API rewrite 返回 201 个项目。

### 2.1 DefiLlama 采集优化
- **文件**: `backend/app/collectors/defillama.py`
- **改动**:
  - 放宽未发币判断：以 `gecko_id` 缺失为主，而不是 `gecko_id && symbol` 同时缺失
  - 增加 `MAX_ITEMS = 100`，单次只保留 discovery_score 最高的 100 个项目

### 2.2 采集持久化性能优化
- **文件**: `backend/app/collectors/persistence.py`
- **改动**:
  - `persist_collection_result` 改为单一连接、单一事务批量写入
  - 避免每条记录都开关 SQLite 连接（原来 1038 个项目耗时 512 秒，现在 100 个项目 < 1 秒）

### 2.3 API key 配置说明
- **文件**: `.env.example`
- **补充**:
  - GitHub token 获取地址与免费额度说明
  - CoinGecko API key 获取地址
  - Twitter/X、Etherscan、Alchemy、Galxe、Layer3、Dune 获取地址

### 2.4 联调验证
- 启动后端：`APP_ENV=testing uvicorn app.main:app --host 127.0.0.1 --port 8002`
- 触发 DefiLlama 采集：`POST /api/v1/collections/defillama/trigger`
  - 结果：`items_collected: 100`, `status: success`, 耗时约 1.5 秒
- 调用 `/run` 自动评分：
  - `project_count: 100`, `scored_count: 100`, `top_score: 63`
- 项目列表 API：
  - `total: 201`（含历史手动输入、seed 数据、DefiLlama 真实采集）
- Dashboard 可正常加载真实数据。

---

## 3. Next.js Dashboard 迁移（代码结构已就绪，待安装依赖）

### 3.1 创建的项目结构
- `frontend-next/package.json` — Next.js 14 + React 18 + Tailwind + Chart.js
- `frontend-next/tsconfig.json`
- `frontend-next/next.config.js` — API rewrite 到 `http://127.0.0.1:8002`
- `frontend-next/tailwind.config.js` — 品牌色 primary/farm/watch/ignore
- `frontend-next/postcss.config.js`
- `frontend-next/app/layout.tsx` — 根布局 + 导航
- `frontend-next/app/page.tsx` — Dashboard 首页（统计、筛选、项目网格）
- `frontend-next/app/project/[id]/page.tsx` — 项目详情页
- `frontend-next/app/insights/page.tsx` — Insights 洞察页
- `frontend-next/components/Nav.tsx` — 顶部导航
- `frontend-next/lib/api.ts` — API 封装
- `frontend-next/README.md` — 启动说明

### 3.2 调试结果

- 用户授权后，使用本地 npm cache 成功安装依赖：
  ```bash
  npm install --cache frontend-next/.npm-cache
  ```
- 修复 `frontend-next/lib/api.ts`：默认 `API_BASE` 改为 `/api/v1`，通过 Next.js rewrite 访问后端，避免 CORS 问题。
- 启动 Next.js dev server：
  ```bash
  cd frontend-next
  npm run dev
  ```
  默认端口 `3002`，API rewrite 到 `http://127.0.0.1:8002`。
- 验证结果：
  - `http://localhost:3002/` → 200
  - `http://localhost:3002/insights` → 200
  - `http://localhost:3002/project/project-002` → 200
  - `http://localhost:3002/api/v1/projects?page_size=1` → 200，返回真实数据

### 3.3 注意事项
- 旧版 `frontend/index.html` 静态服务已停止，Next.js 已占用 `3002`。
- Next.js 版本 `14.2.5` 有安全漏洞警告，生产部署前建议升级到 patched 版本（参考 https://nextjs.org/blog/security-update-2025-12-11）。
- `npm audit` 提示 2 个漏洞（1 moderate, 1 critical），正式使用前应 `npm audit fix --force` 或升级依赖。

### 3.4 按钮没反应问题修复
- **问题**：用户反馈 Next.js Dashboard "点按钮都没反应"。
- **根因**：
  - `frontend-next/app/page.tsx` 请求 `/projects?page_size=200`，`frontend-next/app/insights/page.tsx` 请求 `/projects?page_size=500`。
  - 后端 `backend/app/routers/v1/projects.py` 限制 `page_size <= 100`，导致请求返回 422，页面加载失败，所有按钮自然无法交互。
  - `frontend-next/lib/api.ts` 只处理 `{ok, error}` 格式，对 FastAPI 的 `detail` 校验错误显示为 `Request failed: 422`，用户看不到真正原因。
- **修复**：
  - 后端放宽 `page_size` 上限到 500，同步修改测试 `test_projects.py`。
  - 前端 `apiFetch` 增加对 `json.detail` 数组和字符串的错误消息提取。
  - 为 Dashboard 首页增加「▶ 运行自动采集评分」按钮，先触发所有已启用采集源，再调用 `/run` 自动评分，完成后刷新列表。
  - 为 Project Detail 页增加「↻ 重新评分」按钮，调用 `/run` 对当前项目重新评分。
- **验证**：
  - `/api/v1/projects?page_size=500` 通过 Next.js rewrite 返回 201 个项目。
  - 按钮点击后触发 API 调用并显示 toast 提示。

---

- 全量后端测试：`531 passed, 1 skipped`
- 覆盖率：84%
- 无新增失败测试

---

## 下一步建议

1. **Next.js 体验打磨**：根据浏览器实际效果调整 UI/交互细节（空态、loading、错误提示、暗色主题）。
2. **采集器增强**：配置 GitHub token / CoinGecko API key 后，启用更多真实数据源。
3. **反馈校准**：基于已收集的反馈数据，开始训练/调整评分权重。
