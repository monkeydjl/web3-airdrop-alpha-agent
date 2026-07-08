# 部署与运维指南

> 配套文档：ENGINEERING_ROADMAP.md §15。本文档说明本地运行、Docker 部署、环境变量、CI、日志监控、备份与升级。

---

## 1. 本地运行（开发 / 演示）

**要求**：Python 3.11+

```bash
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python run.py
# 服务启动于 http://localhost:8000
```

首次启动会自动建库（`backend/data/airdrop.db`）。导入演示数据并跑分析：

```bash
curl -X POST http://localhost:8000/api/v1/run -H 'Content-Type: application/json' -d '{"source":"seed"}'
```

打开 `http://localhost:8000/`（若挂载了静态前端）或 `frontend/index.html` 预览 Dashboard。

---

## 2. Docker 部署（推荐）

### 2.1 构建镜像
```bash
docker build -t airdrop-alpha:latest .
```

### 2.2 单容器运行
```bash
docker run -d --name airdrop-alpha \
  -p 8000:8000 \
  -v $(pwd)/data:/app/backend/data \
  -e PORT=8000 \
  airdrop-alpha:latest
```

### 2.3 docker-compose（一键起）
```bash
docker compose up -d --build
```
`docker-compose.yml` 定义：
- `web`：FastAPI 服务，暴露 8000，挂载 `./data` 持久化 SQLite，含 `/health` 健康检查。
- （可选）`frontend`：Nginx 托管静态 Dashboard，反向代理 `/api` 到 `web:8000`。

访问 `http://localhost:8000`。

---

## 3. 环境变量清单

| 变量 | 必填 | 默认 | 说明 |
| --- | --- | --- | --- |
| `PORT` | 否 | `8000` | 服务监听端口 |
| `DB_PATH` | 否 | `backend/data/airdrop.db` | SQLite 文件路径（容器内建议用挂载路径） |
| `OPENAI_API_KEY` | 否 | 空 | 设置后启用 LLM 增强（ADR-1） |
| `API_KEY` | 否(V2) | 空 | V2 Bearer 鉴权密钥 |
| `CRON_HOUR` / `CRON_MINUTE` | 否 | `8` / `0` | 每日自动分析触发时间 |
| `DEFILLAMA_BASE` | 否 | 公开端点 | DefiLlama API 基址 |
| `CRYPTORANK_API_KEY` | 否(V2) | 空 | CryptoRank 项目库 key |
| `TWITTER_BEARER` | 否(V2) | 空 | Twitter API v2 Bearer |
| `DUNE_API_KEY` | 否(V2) | 空 | Dune API key |

> 提供 `.env.example` 模板；`.env` 不得提交进版本库（见 `.gitignore`）。

---

## 4. 数据持久化与备份

- MVP 使用 SQLite 单文件，需挂载卷（`-v ./data:/app/backend/data`）以免容器重建丢数据。
- 备份：
  ```bash
  cp backend/data/airdrop.db backups/airdrop-$(date +%F).db
  ```
- 恢复：停服务 → 覆盖 `airdrop.db` → 启动。
- V2 切换 PostgreSQL：修改连接串即可，应用层通过 `db.py` 抽象隔离。

---

## 5. 健康检查与自愈

- 端点：`GET /health` → `{ "ok": true, "data": { "status":"healthy", "db":"connected" } }`。
- compose `healthcheck`：每 30s 探测 `/health`，失败阈值 3 次。
- 重启策略：`restart: unless-stopped`。

---

## 6. 日志

- 使用 `structlog` 输出 JSON 到 stdout（便于容器采集）。
- 关键事件：`run` 触发、分析项目数、写入/更新数、agent 错误（含 `project_id`/`agent_name`）。
- 本地可直接 `docker logs -f airdrop-alpha`。
- V2 接 Loki/Promtail 集中收集。

---

## 7. 监控与告警（V2）

- 暴露 `/metrics`（Prometheus）：指标如 `run_total`、`run_errors`、`analyze_latency_seconds`、`db_write_errors`。
- Grafana 面板：每日分析成功率、Top 项目数、耗时 P95。
- 告警规则：`run_errors > 0`（连续）、`db_write_errors > 0`、`/health` 持续失败。

---

## 8. CI/CD（GitHub Actions 示例）

`.github/workflows/ci.yml`：
```yaml
name: CI
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - run: pip install -r backend/requirements.txt
      - run: pytest -q
```
> 触发 `POST /run` 的"部署后冒烟"可作为 CD 的一步（curl 健康检查 + run）。

---

## 9. 升级与数据库迁移

- **MVP**：`init_db()` 幂等建表，无迁移需求。
- **V2**：引入 Alembic。
  ```bash
  alembic revision --autogenerate -m "add insights table"
  alembic upgrade head
  ```
- 字段扩展采用**追加列 + JSON 兼容**，避免破坏性迁移。

---

## 10. 安全注意事项

- 密钥仅通过环境变量注入，禁止写入镜像或提交仓库。
- MVP 不暴露公网；如需公网，前置反向代理 + `API_KEY` 鉴权。
- SQLite 文件权限限制为服务账户可读写。
- 仅聚合公开数据，不抓取需授权的隐私数据（见 `ENGINEERING_ROADMAP.md` §16 合规约束）。

---

## 11. 常见问题

| 现象 | 排查 |
| --- | --- |
| 端口被占用 | 修改 `PORT` 或释放 8000；`lsof -i:8000` |
| DB 锁（SQLite busy） | 并发写冲突，确保单写者；V2 换 Postgres |
| 依赖安装慢/失败 | 使用国内镜像 `pip install -i https://pypi.tuna.tsinghua.edu.cn/simple` |
| `/run` 无数据 | 检查 `source` 与网络（DefiLlama 需联网）；`seed` 模式离线可用 |
| 前端空白 | 确认 API base URL 正确（`/api/v1`），浏览器控制台无 CORS 报错 |
