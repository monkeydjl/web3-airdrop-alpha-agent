# 上线部署检查清单

> 生成日期：2026-08-15
> 适用版本：v0.1.0（V2 全部 14 项任务完成）
> 测试基线：2428 passed, 4 skipped, 0 failed

---

## 使用方法

1. 按顺序逐项检查，每一项确认后打勾
2. P0 为阻断项（必须通过才能上线）
3. P1 为强烈建议项（影响生产稳定性）
4. P2 为可选优化项

---

## P0 阻断项 — 必须全部通过

### 1. 环境变量配置

- [ ] `APP_ENV=production`（当前默认 development，生产自检会校验）
- [ ] `API_KEY` 已设置，长度 >= 32 字符随机字符串
  ```bash
  # 生成方法
  python -c "import secrets; print(secrets.token_urlsafe(32))"
  ```
- [ ] `AUTH_TOKEN_SECRET` 已设置固定值（不设则匿名 token 每次重启失效）
  ```bash
  python -c "import secrets; print(secrets.token_urlsafe(48))"
  ```
- [ ] `DEBUG=false`
- [ ] `CORS_ORIGINS` 已设置为实际前端域名（非 `*`）
- [ ] `CORS_CREDENTIALS=true` 时 `CORS_ORIGINS` 不含 `*`

### 2. 数据库

- [ ] 选择数据库后端：
  - SQLite（小型/演示）：`DB_BACKEND=sqlite`，`DB_PATH=/app/data/airdrop.db`，挂载持久卷
  - PostgreSQL（生产推荐）：`DB_BACKEND=postgres`，设置 `POSTGRES_*` 分项或 `DATABASE_URL`
- [ ] PostgreSQL 密码已修改（非 `change-me-in-production`）
- [ ] 数据卷已挂载（`-v ./data:/app/data`），容器重建不丢数据
- [ ] 首次启动执行 `alembic upgrade head` 建表（或依赖 `init_db()` 自动建表）

### 3. 部署验证

- [ ] Docker 镜像构建成功
  ```bash
  docker build -t airdrop-alpha:latest -f backend/Dockerfile .
  ```
- [ ] 容器启动无报错
  ```bash
  # SQLite 模式
  docker compose up -d --build

  # PostgreSQL 模式
  docker compose --profile postgres up -d --build
  ```
- [ ] 健康检查通过
  ```bash
  curl http://localhost:8002/health
  # 预期: {"ok": true, "status": "healthy", "db": "ok", ...}
  ```
- [ ] API 鉴权生效
  ```bash
  # 无 key 应返回 401
  curl http://localhost:8002/api/v1/projects
  # 带 key 正常访问
  curl -H "X-API-Key: <your-key>" http://localhost:8002/api/v1/projects
  ```

### 4. 采集源连通性

- [ ] DefiLlama（P0，免费）：`DEFILLAMA_ENABLED=true`，访问 `https://api.llama.fi/protocols` 正常
- [ ] GitHub（P0，免费）：`GITHUB_ENABLED=true`，建议设置 `GITHUB_TOKEN` 提升 API 限速至 5000 req/h
- [ ] CoinGecko（P0，免费）：`COINGECKO_ENABLED=true`，建议设置 `COINGECKO_API_KEY`
- [ ] 至少 P0 采集源（DefiLlama + GitHub + CoinGecko）有一个连通

### 5. 评分 Pipeline 冒烟测试

- [ ] 手动触发一次评分运行
  ```bash
  curl -X POST http://localhost:8002/api/v1/run \
    -H "Content-Type: application/json" \
    -H "X-API-Key: <your-key>" \
    -d '{"source":"seed"}'
  ```
- [ ] 返回 `status: completed`，`project_count >= 1`
- [ ] 查询项目列表返回数据
  ```bash
  curl -H "X-API-Key: <your-key>" "http://localhost:8002/api/v1/projects?sort_by=score&order=desc&limit=10"
  ```

---

## P1 强烈建议项

### 6. 调度配置

- [ ] `SCHEDULER_ENABLED=true`（分析调度）
- [ ] `COLLECTION_SCHEDULER_ENABLED=true`（采集调度）
- [ ] `COLLECTION_AUTO_RUN_ENABLED=false`（采集后不自动跑分析，避免突发负载；按需开启）
- [ ] `CRON_EXPRESSION=0 8 * * *`（每日 08:00 UTC 自动分析，按实际时区调整）
- [ ] `TIMEZONE` 与团队时区一致

### 7. 监控与告警

- [ ] `/metrics` 端点可访问
  ```bash
  curl http://localhost:8002/metrics | head -20
  ```
- [ ] Prometheus 已配置抓取目标（`configs/observability/prometheus/prometheus.yml`）
- [ ] Grafana Dashboard 已导入（`configs/observability/grafana/dashboard-system-overview.json`）
- [ ] 告警规则已加载（`configs/observability/prometheus/alert_rules.yml`），至少覆盖：
  - `APIDown`（服务不可用，1m，critical）
  - `HighAPIErrorRate`（错误率 > 0.1/s，5m，critical）
  - `PipelineConsecutiveFailures`（15 分钟内 >= 2 次失败，critical）
- [ ] 日志收集已配置（Loki/Promtail 或等效方案，见 `docker/loki/`）

### 8. 安全加固

- [ ] `RATE_LIMIT_ENABLED=true`
- [ ] `RATE_LIMIT_REQUESTS=100`（每窗口 60s 最大请求数，按实际负载调整）
- [ ] SQLite 文件权限限制（`chmod 600 data/airdrop.db`）
- [ ] 容器不以 root 运行（Dockerfile 中已创建非特权用户）
- [ ] `.env` 文件不提交版本库（`.gitignore` 已包含）
- [ ] 密钥仅通过环境变量注入，不写入镜像

### 9. 数据备份

- [ ] SQLite 模式：定时备份脚本已配置
  ```bash
  # crontab 示例：每日 02:00 备份
  0 2 * * * cp /app/data/airdrop.db /backups/airdrop-$(date +\%F).db
  ```
- [ ] PostgreSQL 模式：`pg_dump` 定时备份已配置
- [ ] 备份文件保留策略已定义（如保留 30 天）
- [ ] 至少做过一次备份恢复演练

### 10. LLM 增强（可选）

- [ ] `OPENAI_API_KEY` 已设置（不设则仅走规则引擎，功能完整但无 LLM 增强）
- [ ] `LLM_DAILY_BUDGET_USD=1.0`（每日费用上限，按预算调整）
- [ ] `LLM_DISCOVERY_SCORE_THRESHOLD=0.7`（仅高分项目启用 LLM，节省费用）
- [ ] 或配置多接口故障转移（`LLM_BASEURL_1`/`LLM_API_KEY_1`/`LLM_MODELS_1_*`）

---

## P2 可选优化项

### 11. 采集源扩展

- [ ] Twitter/X：`TWITTER_ENABLED=true`，设置 `TWITTER_BEARER_TOKEN`（需 Basic Tier $100/月）
- [ ] Etherscan：`ETHERSCAN_ENABLED=true`，设置 `ETHERSCAN_API_KEY`（免费）
- [ ] Galxe：`GALXE_ENABLED=true`，设置 `GALXE_API_KEY`
- [ ] Layer3：`LAYER3_ENABLED=true`，设置 `LAYER3_API_KEY`
- [ ] CryptoRank：`CRYPTORANK_ENABLED=true`，设置 `CRYPTORANK_API_KEY`
- [ ] RootData：`ROOTDATA_ENABLED=true`，设置 `ROOTDATA_API_KEY`

### 12. 高级功能

- [ ] 权重校准：积累 >= 200 条反馈后运行 `python scripts/calibrate_weights.py --search`
- [ ] Opportunity Shadow：`OPPORTUNITY_SHADOW_ENABLED=true`，`SAMPLE_RATE=1.0`（已默认开启）
- [ ] Economic Snapshot：`OPPORTUNITY_ECONOMIC_SNAPSHOT_ENABLED=true`（已默认开启）
- [ ] 前端 Next.js 部署（`frontend-next/` 目录，`docker compose --profile production up -d`）

### 13. 容器编排优化

- [ ] 资源限制已设置（docker-compose 中添加 `deploy.resources.limits`）
- [ ] 日志轮转已配置（docker-compose 中添加 `logging.max-size` + `max-file`）
- [ ] Nginx 反向代理已启用（`--profile production`，配置见 `nginx.conf`）
- [ ] HTTPS/TLS 已配置（Nginx 层或前置负载均衡）

### 14. CI/CD

- [ ] GitHub Actions CI 已配置（`.github/workflows/ci.yml`）
- [ ] 测试在 CI 中全绿
- [ ] 镜像推送至 registry（`docker compose --profile production` + `DOCKER_REGISTRY`）

---

## 快速启动命令

### SQLite 模式（最简）

```bash
# 1. 复制并编辑环境变量
cp .env.example .env
# 编辑 .env，至少设置：APP_ENV, API_KEY, AUTH_TOKEN_SECRET

# 2. 构建并启动
docker compose up -d --build

# 3. 验证
curl http://localhost:8002/health
```

### PostgreSQL 模式（生产推荐）

```bash
# 1. 复制并编辑环境变量
cp .env.example .env
# 编辑 .env，至少设置：
#   APP_ENV=production
#   API_KEY=<32+ chars random>
#   AUTH_TOKEN_SECRET=<48+ chars random>
#   DB_BACKEND=postgres
#   POSTGRES_PASSWORD=<strong-password>

# 2. 构建并启动（含 PostgreSQL）
docker compose --profile postgres up -d --build

# 3. 执行数据库迁移
docker exec airdrop-alpha-backend alembic upgrade head

# 4. 验证
curl http://localhost:8002/health
curl http://localhost:8002/metrics
```

### 冒烟测试

```bash
# 设置 API_KEY 变量
export API_KEY="<your-api-key>"

# 健康检查
curl http://localhost:8002/health | python -m json.tool

# 触发采集
curl -X POST -H "X-API-Key: $API_KEY" http://localhost:8002/api/v1/collections/defillama/trigger

# 触发评分
curl -X POST -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  http://localhost:8002/api/v1/run -d '{"source":"seed"}'

# 查询结果
curl -H "X-API-Key: $API_KEY" "http://localhost:8002/api/v1/projects?sort_by=score&order=desc&limit=5" | python -m json.tool

# 检查指标
curl http://localhost:8002/metrics | grep -E "pipeline_runs|airdrop_fetcher"
```

---

## 回滚方案

```bash
# 1. 停止服务
docker compose down

# 2. 恢复数据库备份
cp backups/airdrop-2026-08-14.db data/airdrop.db
# PostgreSQL: psql -d airdrop_test -f backups/airdrop-2026-08-14.sql

# 3. 回滚到上一版本镜像
docker tag airdrop-alpha:prev airdrop-alpha:latest

# 4. 重新启动
docker compose up -d

# 5. Alembic 回滚（如需）
docker exec airdrop-alpha-backend alembic downgrade -1
```

---

## 常见问题排查

| 现象 | 排查方向 |
|------|----------|
| 容器启动即退出 | 检查 `.env` 中 `API_KEY` 是否设置且 >= 32 字符 |
| `/health` 返回 db 错误 | 检查数据库连接、卷挂载、`alembic upgrade head` |
| `/run` 返回空结果 | 检查采集源连通性；`SEED_FALLBACK_ENABLED=true` 可降级兜底 |
| 采集源全部超时 | 检查 `FETCHER_CIRCUIT_BREAKER_THRESHOLD`；网络/防火墙 |
| 内存持续增长 | 调低 `MAX_CONCURRENT_PROJECTS`；检查缓存 `COMPETITION_CACHE_MAX_SIZE` |
| Prometheus 抓取失败 | 确认 `METRICS_ENABLED=true`、`METRICS_PATH=/metrics` |
| SQLite busy 锁 | 并发写冲突，切换 PostgreSQL 或降低并发 |

---

## 签收

- [ ] P0 阻断项全部通过
- [ ] P1 强烈建议项全部通过
- [ ] 冒烟测试通过
- [ ] 备份恢复演练通过

**部署人**：______________
**部署日期**：______________
**版本**：v0.1.0
