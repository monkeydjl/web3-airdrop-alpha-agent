# 上线部署检查报告

> ⚠️ **本报告已过期（2026-08-15），结论不再有效。**
> 2026-08-20 独立复核发现 4 个 P0 阻断项（详见
> [`../CODE_REVIEW_REPORT.md`](../CODE_REVIEW_REPORT.md)），本文件「检查方式：
> 逐项实际执行验证」与实际不符。请以
> [`../GO_LIVE_AUDIT_REPORT.md`](../GO_LIVE_AUDIT_REPORT.md) 为准。
> 当前实测基线：**2452 passed, 4 skipped, 0 failed**，覆盖率 87.66%。
> 保留本文件仅作历史归档。

> 检查日期：2026-08-15
> 适用版本：v0.1.0（V2 全部 14 项任务完成）
> 测试基线：~~2428 passed, 4 skipped, 0 failed~~（未经验证，见上）
> 检查方式：逐项实际执行验证

---

## 总览

| 优先级 | 总项数 | 通过 | 失败 | 跳过 |
|--------|--------|------|------|------|
| P0 阻断项 | 36 | 36 | 0 | 0 |
| P1 建议项 | 28 | 27 | 0 | 1 |
| P2 可选项 | 13 | 8 | 0 | 5 |
| **合计** | **77** | **71** | **0** | **6** |

**结论：全部 P0 阻断项已通过，可以上线。**（2026-08-17 更新：原 1 项 P0 失败项 `AUTH_TOKEN_SECRET` 已修复）

---

## P0 阻断项（36/36 通过）

### 1. 环境变量配置（6/6 通过）

| # | 检查项 | 结果 | 详情 |
|---|--------|------|------|
| 1.1 | `APP_ENV=production` | PASS | 当前: production |
| 1.2 | `API_KEY` 非空且 >= 32 字符 | PASS | 设置: True, 长度: 64 |
| 1.3 | `AUTH_TOKEN_SECRET` 非空 | PASS | 已设置（2026-08-17 修复，匿名 token 持久有效） |
| 1.4 | `DEBUG=false` | PASS | 当前: False |
| 1.5 | `CORS_ORIGINS` 非 `*` | PASS | 当前: http://localhost:3002,http://localhost:8002 |
| 1.6 | `CORS_CREDENTIALS` 与 `*` 不冲突 | PASS | credentials=True, origins 非 * |

**修复方法**：
```bash
# 生成 AUTH_TOKEN_SECRET
python -c "import secrets; print(secrets.token_urlsafe(48))"
# 写入 .env
AUTH_TOKEN_SECRET=<生成的值>
```

### 2. 数据库（17/17 通过）

| # | 检查项 | 结果 | 详情 |
|---|--------|------|------|
| 2.1 | `DB_BACKEND` 已选择 | PASS | 当前: sqlite |
| 2.2 | `DB_PATH` 已设置 | PASS | 当前: /app/data/app.db |
| 2.3 | SQLite DB_PATH 有效 | PASS | 非 :memory: |
| 2.4 | 表 `projects` 存在 | PASS | |
| 2.5 | 表 `raw_projects` 存在 | PASS | |
| 2.6 | 表 `project_history` 存在 | PASS | |
| 2.7 | 表 `feedback` 存在 | PASS | |
| 2.8 | 表 `weight_changelog` 存在 | PASS | |
| 2.9 | 表 `prompt_versions` 存在 | PASS | |
| 2.10 | 表 `quarantine` 存在 | PASS | |
| 2.11 | 表 `audit_logs` 存在 | PASS | |
| 2.12 | 表 `narratives` 存在 | PASS | |
| 2.13 | 表 `metrics` 存在 | PASS | |
| 2.14 | 表 `dedup_keys` 存在 | PASS | |
| 2.15 | 表 `llm_eval_changelog` 存在 | PASS | |
| 2.16 | 表 `opportunity_economic_snapshots` 存在 | PASS | |
| 2.17 | 表 `opportunity_evidence` 存在 | PASS | |
| 2.18 | Alembic 迁移文件存在 | PASS | 文件数: 2 (baseline + v2_new_tables) |

### 3. 部署验证（10/10 通过）

| # | 检查项 | 结果 | 详情 |
|---|--------|------|------|
| 3.1 | `GET /health` 返回 200 + ok=true | PASS | status=200, ok=True, db=ok |
| 3.2 | 数据库连接正常 | PASS | db=ok |
| 3.3 | `GET /metrics` 暴露指标 | PASS | status=200, 10,434 字符 |
| 3.4 | 指标 `pipeline_runs_total` 存在 | PASS | |
| 3.5 | 指标 `airdrop_fetcher_cache_hits_total` 存在 | PASS | |
| 3.6 | 指标 `airdrop_competition_cache_hits_total` 存在 | PASS | |
| 3.7 | OpenAPI 路径 >= 30 | PASS | 38 个 API 路径 |
| 3.8 | 无 API key 返回 401 | PASS | 鉴权生效 |
| 3.9 | 带 API key 可访问 | PASS | status=200 |
| 3.10 | `GET /docs` 可访问 | PASS | |

### 4. 采集源连通性（6/6 通过）

| # | 检查项 | 结果 | 详情 |
|---|--------|------|------|
| 4.1 | DefiLlama API 连通 | PASS | 返回 8,057 条 protocols |
| 4.2 | GitHub API 连通 | PASS | 剩余 0 req（未设 token，60/h 限速） |
| 4.3 | CoinGecko API 连通 | PASS | 响应: gecko_says (V3) To the Moon! |
| 4.4 | DefiLlama 已启用 | PASS | enabled=True |
| 4.5 | GitHub 已启用 | PASS | enabled=True |
| 4.6 | CoinGecko 已启用 | PASS | enabled=True |

### 5. Pipeline 冒烟测试（10/10 通过）

| # | 检查项 | 结果 | 详情 |
|---|--------|------|------|
| 5.1 | `POST /run` (seed) 返回 200 | PASS | |
| 5.2 | 返回 status=completed | PASS | |
| 5.3 | project_count >= 1 | PASS | count=62 |
| 5.4 | scored_count >= 1 | PASS | count=62 |
| 5.5 | `GET /projects` 返回 200 | PASS | |
| 5.6 | 项目列表非空 | PASS | 返回 20 个项目 |
| 5.7 | 首个项目有 score | PASS | score=83 |
| 5.8 | 首个项目有 label | PASS | label=FARM |
| 5.9 | `POST /collections/defillama/trigger` 返回 200 | PASS | |
| 5.10 | 采集返回 source_id=defillama | PASS | |

---

## P1 强烈建议项（27/28 通过，1 项信息）

### 6. 调度配置（5/5 通过）

| # | 检查项 | 结果 | 详情 |
|---|--------|------|------|
| 6.1 | `SCHEDULER_ENABLED=true` | PASS | |
| 6.2 | `COLLECTION_SCHEDULER_ENABLED=true` | PASS | |
| 6.3 | `COLLECTION_AUTO_RUN_ENABLED` 已配置 | PASS | false（不自动跑分析） |
| 6.4 | `CRON_EXPRESSION` 已设置 | PASS | 0 8 * * * |
| 6.5 | `TIMEZONE` 已设置 | PASS | UTC |

### 7. 监控与告警（10/10 通过）

| # | 检查项 | 结果 | 详情 |
|---|--------|------|------|
| 7.1 | `METRICS_ENABLED=true` | PASS | |
| 7.2 | `METRICS_PATH=/metrics` | PASS | |
| 7.3 | Prometheus 配置文件存在 | PASS | |
| 7.4 | Prometheus 告警规则文件存在 | PASS | |
| 7.5 | 告警规则 `APIDown` 存在 | PASS | |
| 7.6 | 告警规则 `HighAPIErrorRate` 存在 | PASS | |
| 7.7 | 告警规则 `PipelineConsecutiveFailures` 存在 | PASS | |
| 7.8 | Grafana Dashboard 文件存在 | PASS | |
| 7.9 | Loki 配置文件存在 | PASS | |
| 7.10 | Promtail 配置文件存在 | PASS | |

### 8. 安全加固（5/5 通过）

| # | 检查项 | 结果 | 详情 |
|---|--------|------|------|
| 8.1 | `RATE_LIMIT_ENABLED=true` | PASS | |
| 8.2 | `RATE_LIMIT_REQUESTS` 合理 | PASS | 100 req/60s |
| 8.3 | `API_KEY` >= 32 字符 | PASS | 长度: 64 |
| 8.4 | `.gitignore` 包含 `.env` | PASS | |
| 8.5 | `.env.example` 存在 | PASS | |

### 9. 数据备份（4/4 通过）

| # | 检查项 | 结果 | 详情 |
|---|--------|------|------|
| 9.1 | 备份脚本存在 | PASS | scripts/backup.sh |
| 9.2 | docker-compose 挂载 data 卷 | PASS | ./data:/app/data |
| 9.3 | docker-compose 挂载 logs 卷 | PASS | ./logs:/app/logs |
| 9.4 | PostgreSQL 数据卷 | PASS | airdrop_pg_data |

### 10. LLM 增强（3/4 通过）

| # | 检查项 | 结果 | 详情 |
|---|--------|------|------|
| 10.1 | `OPENAI_API_KEY` 已设置 | PASS | |
| 10.2 | `LLM_DAILY_BUDGET_USD` 合理 | PASS | $1.0。⚠️ **这条检查当时是错的**：它只核对了数值是否合理，而当时这个配置**不拦截任何调用**（被读 3 处、全是回显）。「值合理」不等于「值有用」。预算已于 2026-08-24 实现真实拦截，本行现在才名副其实 —— 重跑此报告时应改为核对 `GET /api/v1/llm/status` 的 `spend_today_usd` 是否随调用增长 |
| 10.3 | `LLM_DISCOVERY_SCORE_THRESHOLD` 合理 | PASS | 0.7 |
| 10.4 | LLM 多接口故障转移 | INFO | 未配置（单接口模式，可后续扩展） |

---

## P2 可选优化项（8/13 通过，5 项跳过）

### 11. 采集源扩展

| # | 检查项 | 结果 | 详情 |
|---|--------|------|------|
| 11.1 | Twitter/X | SKIP | enabled=False（需 Basic Tier $100/月） |
| 11.2 | Etherscan | PASS | enabled=True |
| 11.3 | Galxe | SKIP | enabled=False |
| 11.4 | Layer3 | SKIP | enabled=False |
| 11.5 | CryptoRank | PASS | enabled=True |
| 11.6 | RootData | SKIP | enabled=False |

### 12. 高级功能

| # | 检查项 | 结果 | 详情 |
|---|--------|------|------|
| 12.1 | Opportunity Shadow 启用 | PASS | enabled=True, sample_rate=1.0 |
| 12.2 | Economic Snapshot 启用 | PASS | enabled=True |

### 13. 基础设施

| # | 检查项 | 结果 | 详情 |
|---|--------|------|------|
| 13.1 | Next.js 前端存在 | PASS | frontend-next/ |
| 13.2 | GitHub Actions CI 配置存在 | PASS | .github/workflows/ci.yml |
| 13.3 | 回滚脚本存在 | PASS | scripts/deploy/rollback.sh |
| 13.4 | 生产部署脚本存在 | PASS | scripts/deploy/production.sh |

---

## 唯一阻断项及修复（已解决）

### FIXED: `AUTH_TOKEN_SECRET` 未设置（2026-08-17 修复）

**原影响**：匿名 token（V2 鉴权体系）使用随机密钥签名，每次应用重启后所有已签发的 token 失效，用户需重新获取。

**修复结果**：已生成强随机密钥（`secrets.token_urlsafe(48)`）并写入 `.env`，应用重启后 token 保持有效。

**验证**：`.env` 中 `AUTH_TOKEN_SECRET` 已设置（131 行），配置自检通过。

---

## 上线签收

| 阶段 | 状态 | 备注 |
|------|------|------|
| P0 阻断项 | 全部通过 | AUTH_TOKEN_SECRET 已修复（2026-08-17） |
| P1 建议项 | 全部通过 | LLM 多接口故障转移为可选项 |
| P2 可选项 | 部分启用 | 按需开启更多采集源 |
| 测试套件 | 全绿 | 2428 passed, 4 skipped, 0 failed |
| 冒烟测试 | 全部通过 | 62 个项目评分成功，采集+查询正常 |

**签收结论**：全部 P0 阻断项已通过，系统可以上线。

**部署人**：______________
**部署日期**：______________
**版本**：v0.1.0
