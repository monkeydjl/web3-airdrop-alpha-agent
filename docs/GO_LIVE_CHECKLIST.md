# 上线部署检查清单

> 生成日期：2026-08-15（测试基线与上线前置项于 2026-08-20 复核更新）
> 适用版本：v0.1.0（V2 全部 14 项任务完成）
> 测试基线：2452 passed, 4 skipped, 0 failed，覆盖率 87.66%（2026-08-20 实测）
>
> ⚠️ **上线前必读**：2026-08-20 复核发现并修复了 4 个 P0 阻断项（含一条零凭证
> 窃取 LLM API Key 的链路、容器按本文档命令启动必然 CrashLoop）。详见
> [`CODE_REVIEW_REPORT.md`](../CODE_REVIEW_REPORT.md) 与
> [`GO_LIVE_AUDIT_REPORT.md`](../GO_LIVE_AUDIT_REPORT.md)。
> 本文档 §1 的环境变量清单已补充两项**生产强制**要求：
> `AUTH_TOKEN_SECRET` 必须透传进容器；`CORS_ORIGINS` 不得含 localhost。

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
- [ ] `AUTH_TOKEN_SECRET` 已设置固定值 —— **生产为空会直接拒绝启动**
  ```bash
  python -c "import secrets; print(secrets.token_urlsafe(48))"
  ```
- [ ] **确认该值能传进容器**：`docker-compose.yml` 已通过 `env_file: [.env]` 读取。
      若改用自定义 compose，务必确认 `AUTH_TOKEN_SECRET` 在容器内可见——
      镜像不含 `.env`（被 `.dockerignore` 排除），漏传会 CrashLoop 且无限重启
- [ ] `DEBUG=false`
- [ ] `CORS_ORIGINS` 已设置为实际前端域名 —— **含 `localhost` / `127.0.0.1` 会拒绝启动**
      （默认值就是 localhost，忘改会让真实前端全部跨域失败）
- [ ] `CORS_CREDENTIALS=true` 时 `CORS_ORIGINS` 不含 `*`
- [ ] 建议 `SEED_FALLBACK_ENABLED=false`：否则采集全挂时会用 8 个内置种子项目
      填充评分结果（标记为 `source='seed'`，但会计入 Dashboard 汇总）

### 1b. 反向代理与限流（漏配不报错，但限流等于失效）

- [ ] `TRUSTED_PROXY_COUNT` 按**实际代理层数**设置 —— 默认 `0` 在反代拓扑下会让
      **全站共用一个限流桶**

  这一项的失败方式是静默的：默认值 `0` 表示"直连、忽略 `X-Forwarded-For`"，
  于是限流键取 `request.client.host`。而在 `docker-compose.prod.yml` 拓扑下
  那个值是 **nginx 容器 IP**，所有外部客户端算作同一个来源 ——
  `RATE_LIMIT_REQUESTS=100` / 60s 变成整站共享 100 次，要么正常用户互相挤爆、
  要么 API key 爆破根本挡不住。没有任何日志或告警会提示这件事。

  怎么数层数（数的是**本服务前面**有几层受控代理）：

  | 拓扑 | 取值 |
  |---|---|
  | 直连暴露 uvicorn（不建议） | `0` |
  | 本仓 `docker-compose.prod.yml`（nginx → web） | `1` |
  | 外层 TLS 终止反代 → nginx → web（Cloudflare / ALB / 另一台 nginx） | `2` |
  | 每多一层受控代理 | `+1` |

  **只算你自己控制的那几层。** 取值原理：代码取 `X-Forwarded-For` 从右往左第 N 个
  （`app/rate_limit.py::_client_ip`），因为 nginx 的 `$proxy_add_x_forwarded_for`
  会把客户端自带的 XFF **前置**再追加真实对端 —— 左侧各段都是客户端可伪造的，
  只有右起第 N 个是链上不可伪造的位置。数大了会取到伪造段（等于没限流），
  数小了会取到反代自己的 IP（退回全站一个桶）。

- [ ] 验证方法：部署后从**两个不同外网 IP** 各打 `RATE_LIMIT_REQUESTS + 5` 次
      `GET /api/v1/projects`。正确配置下两边都应先 200 后 429 且互不影响；
      若其中一边一开始就 429，说明层数数小了、两边共用了同一个桶。

- [ ] `RATE_LIMIT_ENABLED=true`（默认已是）。这三个键 `RATE_LIMIT_ENABLED` /
      `_REQUESTS` / `_WINDOW` 是**真实生效**的 —— 部分旧文档曾写"HTTP 层限流未实现"，
      那是过时信息（`app/rate_limit.py` 是实现本体）。

### 1c. 前端代理鉴权（配错等于把管理员权限发给所有访客）

- [ ] `BACKEND_API_KEY` 已设置，且与后端 `API_KEY` **同值**
      （前端容器读这个名字，后端读 `API_KEY`，是两个不同的键）
- [ ] `API_PROXY_TARGET` 指向后端内网地址（本仓生产 compose 固定为 `http://web:8002`；
      它同时在**前端构建期**决定 Next rewrite、在运行期供匿名 token 换取直连后端）
- [ ] **不要**设置 `NEXT_PUBLIC_API_KEY` —— `NEXT_PUBLIC_` 前缀会被 Next.js
      编进浏览器包，等于把密钥公开发布

  这一项曾经是真的越权口子：`proxy.ts` 早期版本对**所有** `/api/*` 请求无差别
  注入 `X-API-Key`，于是任何匿名访客经前端发出的请求，在后端看来都是管理员。
  现在改为按前缀分档注入：

  | 请求 | 注入的凭据 | 后端看到的身份 |
  |---|---|---|
  | `ADMIN_PREFIXES` 命中（如 `/api/v1/watched-wallets`、`/api/v1/settings/*`） | `X-API-Key` | 管理员 |
  | `ADMIN_METHOD_RULES` 命中（对特定前缀的写方法） | `X-API-Key` | 管理员 |
  | 其余（`/api/v1/projects` 等只读） | 服务端换取并缓存的匿名 `Bearer` token | 匿名用户 |
  | `/api/v1/auth/*` | 不注入（放行） | —— |

  > **`proxy.ts` 的 `ADMIN_PREFIXES` 必须与后端 `app/auth.py` 的
  > `ADMIN_ONLY_PREFIXES` 逐项一致。** 漏一项就是一个静默越权口子：前端不认为
  > 它是管理端点、于是只注入匿名 token，而后端认为它是 —— 结果是 403，功能坏掉
  > 但不危险；反过来多写一项才危险（把不该提权的路径提权了）。加后端前缀时
  > 请同步这里，`docs/OPERATIONS.md` §5.2 的清单也要一起改。

  匿名档不等于免鉴权：后端中间件在 `API_KEY` 非空时要求**任何**请求都带凭据，
  不带任何头会拿到 401 而不是 200。所以代理需要在服务端调
  `POST /api/v1/auth/anonymous` 换 token 并缓存（带 5 分钟提前续期余量、
  并发去重），而不是"不注入任何头"。

- [ ] 配套后端改动已在位：`GET /api/v1/public-config`（白名单回显 8 维权重 +
      3 个标签阈值）。它**不能**挂在 `/settings/*` 下 —— 那整个前缀在
      `ADMIN_ONLY_PREFIXES` 里。项目详情页用它替代了原先的 `/settings/config`
      （后者的 `thresholds` 块混着 `LLM_DAILY_BUDGET_USD` 等成本项，
      整块转发会顺带公开预算信息）。契约见 `docs/API_SPEC.md` §42
- [ ] 验证（部署后从公网执行，`$SITE` 换成实际域名）：
  ```bash
  # 匿名可读公开配置 → 期望 200，且响应里只有 weights / thresholds 两个键
  curl -s -o /dev/null -w '%{http_code}\n' "$SITE/api/v1/public-config"

  # 匿名读管理端点 → 期望 403（不是 200！返回 200 说明代理仍在无差别注入密钥）
  curl -s -o /dev/null -w '%{http_code}\n' "$SITE/api/v1/settings/config"
  ```

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
  docker build -t airdrop-alpha:latest -f docker/Dockerfile .
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

- [ ] `/metrics` 仅能从**后端内网**访问（公网 nginx 返回 403，这是预期安全行为）
  ```bash
  # 从 Prometheus 容器或 backend Docker 网络执行；不要从公网域名 curl。
  # Prometheus 的真实 target 已是 airdrop-web:8002，见 prometheus.yml。
  curl http://airdrop-web:8002/metrics | head -20
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

- [ ] 至少一个接口已配**全**（不配则仅走规则引擎，功能完整但无 LLM 增强）。
      三样缺一不可：`OPENAI_BASE_URL_N`（必须 `http://` 或 `https://` 开头）
      + `OPENAI_API_KEY_N` + 至少一个 `OPENAI_MODEL_N_M`
- [ ] **核对 `GET /api/v1/llm/status` 的 `provider_count` 等于你配的接口数**。
      少一个说明那个接口是半配置（缺 key / 缺模型 / base_url 粘连），
      去日志查 llm.provider_config_incomplete 的 `index` 与 `missing`
- [ ] **`candidate_count` 等于 Σ 每接口模型数**。它是轮询一圈的步数；
      为 0 说明一个模型都没注册，此时 LLM 实际不可用
- [ ] 若从旧格式迁移：确认日志**没有** llm.legacy_numbered_config_ignored。
      出现它说明 `LLM_BASEURL_N` 等旧变量还留在环境里，而新格式已生效 ——
      旧变量此时完全不起作用，应删掉以免下次有人改错地方
- [ ] `LLM_DAILY_BUDGET_USD=1.0`（每日费用上限，按预算调整。**2026-08-24 起真的会拦**：超出后拒绝调用并降级回规则引擎；填 `0` 表示不限额）
- [ ] `LLM_FALLBACK_PRICE_PER_1M_USD=10.0`（价格表里没有的模型按此单价估算，故意偏高 —— 宁可高估导致提前熔断）。
      **多接口下更要紧**：免费接口的模型名大多不在价格表里，这个值是它们唯一的成本口径
- [ ] **上线后第一天核对一次**：`GET /api/v1/llm/status` 的 `spend_today_usd` 应随调用增长。如果一直是 `0` 而确实调了 LLM，说明记账断了（预算等于不生效）；如果是 `null`，看同响应里的 `ledger_error`
- [ ] `LLM_DISCOVERY_SCORE_THRESHOLD=0.7`（仅高分项目启用 LLM，节省费用）
- [ ] 知悉轮询边界：计数器是**进程内**的，多 worker / 多实例下**不保证全局
      严格均衡**，重启后从第一个组合重新开始。别按「各接口调用数严格均分」
      验收（详见 `docs/OPERATIONS.md §9.5`、ADR-016）

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
- [ ] 前端 Next.js 生产部署（使用独立全栈 compose）：
      `docker compose -f docker-compose.prod.yml up -d --build`。
      **不是** `docker compose --profile production up`：后者属于基础 compose，
      没有 frontend 服务，起出来只有裸 API；完整原因见 DEPLOYMENT.md §2.3。

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
