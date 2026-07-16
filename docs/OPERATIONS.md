# 运维 Runbook

> 配套文档：ENGINEERING_ROADMAP.md §15、SECURITY.md §9、OBSERVABILITY.md §5。本文档是值班/运维人员的操作手册，覆盖日常运维、故障处理、部署发布、备份恢复�?>
> 适用阶段：MVP 单机部署 �?V2 容器�?�?V3 多实例。每节标注适用阶段�?
---

## 1. 角色与值班

### 1.1 角色定义
| 角色 | 职责 | 阶段 |
| --- | --- | --- |
| Primary on-call | 响应 critical 告警�?30min 介入 | V2+ |
| Secondary on-call | Primary 未响�?15min 后升�?| V2+ |
| Data steward | 处理 quarantine、词表维�?| V2+ |
| Release manager | 发布窗口决策、回滚授�?| V2+ |

### 1.2 值班轮换（V2+�?- 每周轮换，周一 00:00 UTC 交接
- 值班期间保持即时通讯可达（Slack/电话�?- 值班前检查：告警通道是否通、`/health` 是否绿、最�?run 是否成功

### 1.3 MVP 阶段
- 无正式值班；作�?小团队自行响�?- 告警走邮件，工作时间处理

---

## 2. 日常运维检查项

### 2.1 每日（自动化 + 人工抽查�?| 检查项 | 方式 | 期望 | 异常处理 |
| --- | --- | --- | --- |
| 每日 run 成功 | �?`airdrop_run_total{status="success"}` | 当日 �? �?| §4.1 |
| 健康检�?| `curl /health` | `ok:true` | §4.7 |
| 库内项目增长 | `airdrop_projects_in_db` | 每日 +20�?0 | §4.5 |
| quarantine 积压 | `airdrop_quarantine_pending` | <50 | §4.6 |
| LLM 成本（V2�?| `airdrop_llm_cost_usd_total` | < 日预�?| §4.4 |
| 外部源熔�?| `airdrop_fetcher_circuit_open` | �?0 | §4.3 |
| 数据完整�?| `airdrop_data_completeness_ratio` | P0=1.0 | §4.6 |
| **采集调度器运�?*（v2.0�?| `airdrop_collection_total{status="success"}` | 当日每源 �? �?| §4.3 / §4.5 |
| **采集成功�?*（v2.0�?| `airdrop_collection_success_ratio` | �?5% | §4.3 |
| **发现项目�?*（v2.0�?| `raw_projects` 当日新增 | 20-50/�?| §4.5 |
| **采集质量-误报�?*（v2.0�?| `evaluation/collection/` 周报 | <10% | §4.3.5 |
| **采集质量-源覆盖率**（v2.0�?| `evaluation/collection/` 周报 | �?0% | §4.3.5 |

### 2.2 每周
- 检查磁盘空间（SQLite + backups + cache 目录�?- 检�?logs 表增长，�?50MB 考虑清理（保�?90 天）
- 审阅告警趋势（是否有反复触发的规则）
- 词表审计：剔除无项目命中的死赛道词条

### 2.3 每月
- 依赖安全扫描 `pip-audit` 全量
- 数据质量月报复盘（V2+�?- 密钥轮换检查（V2+，超 90 天未换提醒）
- 备份恢复演练（�?.3�?
---

## 3. 部署与发�?
### 3.1 MVP 本地部署
```bash
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python run.py
# 首次启动自动建库；导入种子数�?curl -X POST http://localhost:8002/api/v1/run -H 'Content-Type: application/json' -d '{"source":"seed"}'
```

### 3.2 Docker 部署
```bash
# 构建
docker build -t airdrop-alpha:latest .

# 单容�?docker run -d --name airdrop-alpha \
  -p 8000:8000 \
  -v $(pwd)/data:/app/backend/data \
  -e PORT=8000 \
  --restart unless-stopped \
  airdrop-alpha:latest

# �?compose 一�?docker compose up -d --build
```

### 3.3 发布流程（V2+�?```
1. PR 合并�?main（CI 全绿�?2. �?tag v*.*.*
3. CI 自动构建镜像 �?ghcr.io/<org>/airdrop-alpha:<tag>
4. Release manager 确认发布窗口
5. 演示环境部署 + 冒烟（curl /health + POST /run?source=seed�?6. 冒烟通过 �?更新 latest tag �?生产部署
7. 观察 30min（告�?+ 错误率）
```

### 3.4 回滚
- **应用回滚**（优先）：重新部署上一版本镜像 `<tag-prev>`
- **数据库回�?*（慎用）：仅�?schema 迁移破坏性时
  ```bash
  alembic downgrade -1
  ```
- **配置回滚**：恢�?`.env` 上一版本，重启容�?- 回滚决策：P0/P1 事件 + Release manager 授权

### 3.5 蓝绿/金丝雀（V3�?- V3 引入：新版本先发 10% 流量，观�?1h 无异常再全量
- 数据库迁移仍需"先兼容双�?�?切读 �?删旧�?三步（ENGINEERING_ROADMAP.md §15.3�?
### 3.6 Opportunity Shadow rollout

Opportunity v2.0 Shadow is a non-authoritative side evaluation. It does not replace the `score-v1.4` project score or label. Roll it out in this order:

1. Start with `OPPORTUNITY_SHADOW_ENABLED=false` and `OPPORTUNITY_SHADOW_SAMPLE_RATE=0.0`.
2. Verify `/health`, including `opportunity_model_version`, `opportunity_shadow_enabled`, and `opportunity_shadow_sample_rate`.
3. After baseline health verification, set enabled to `true`, set the rate to `0.05`, and restart the service.
4. Observe one normal scheduling window. Check the health fields; Shadow `eligible`, `sampled`, `attempted`, `saved`, `failed`, and `skipped` counters; assessment statuses and public labels; and duration.
5. Increase the sample rate gradually after the signals remain normal. Project-ID buckets are deterministic, so higher thresholds select monotonic supersets: a project selected at a lower rate remains selected at a higher rate.
6. Roll back by setting `OPPORTUNITY_SHADOW_ENABLED=false` and restarting. No schema rollback or legacy-score rollback is required because Shadow assessments are append-only and non-authoritative.

#### Sequential PostgreSQL verification

Run the following commands from `backend`. They share test database state and must run in this exact order; do not parallelize them:

```powershell
$env:DATABASE_URL='postgresql://airdrop:airdrop_test@127.0.0.1:5433/airdrop_test'
python scripts/verify_postgres.py
python scripts/verify_opportunity_shadow.py
python scripts/verify_init_db_concurrency.py --database-url 'postgresql://airdrop:airdrop_test@127.0.0.1:5433/airdrop_test' --workers 4 --rounds 2
```
---

## 4. 故障处理手册

> 每个故障：症�?�?排查 �?止损 �?根因 �?恢复 �?事后�?
### 4.1 每日 run 失败
**症状**：`airdrop_run_total{status="error"}` 增加；告�?`pipeline 连续失败`
**排查**�?1. `docker logs airdrop-alpha --since 30m | grep "run.error"`
2. 确认失败 stage：collect / analyze / score / db.write
3. �?`logs` �?`WHERE agent_name='orchestrator' ORDER BY timestamp DESC LIMIT 5`

**止损**�?- �?collect 失败 �?�?`source=seed` 跑一次保证有输出
- �?db.write 失败 �?�?§4.2

**根因**：外部源全挂 / DB �?/ 配置错误 / 代码 bug
**恢复**：修�?`curl -X POST /api/v1/run`
**事后**：补测试用例 + ADR（若是设计缺陷）

### 4.2 DB 写失�?/ `database is locked`
**症状**：`airdrop_db_write_errors_total` 增加；SQLite `database is locked`
**排查**�?1. 是否有多�?writer 进程？`lsof airdrop.db`
2. 是否有长事务未提交？�?logs `db.query.duration` P95
3. 磁盘是否满？`df -h`

**止损**�?- 杀掉冲�?writer，单 writer 重启
- 磁盘�?�?清理 `data/cache/` 与旧 backups

**根因**：并发写 / 长事�?/ 磁盘�?/ V2 未切 PG
**恢复**：重启服务；�?DB 损坏 �?从备份恢复（§6.2�?**升级**：频繁发�?�?加�?V2 PG 迁移

### 4.3 采集故障（v2.0 扩充，ADR-012�?
> 自动扫描模式下，外部 API 故障是核心运维场景。本节对�?`DATA_SOURCE_STRATEGY.md §采集故障降级矩阵` �?L1-L4 四级故障�?
#### 4.3.1 L1：限流（API 接近或达到速率限制�?
**症状**�?- `airdrop_collection_status{source=X,status="rate_limited"}` 持续 >10min
- 日志出现 `429 Too Many Requests`
- `airdrop_collection_api_calls{source=X}` 接近 `api_limit`

**排查**�?1. �?`collection_logs WHERE source_id=X AND status='rate_limited' ORDER BY started_at DESC LIMIT 5`
2. 确认是否多任务并发争抢配额：`airdrop_collection_running{source=X}` 是否 >1
3. 确认令牌桶是否被耗尽：`airdrop_rate_limiter_tokens{source=X}`

**止损**�?- 令牌桶自动排队等待（无需人工干预�?- 若持续限�?�?调低该源的采集频率（�?Twitter �?15min �?30min�?- 紧急情况：`POST /api/v1/collections/trigger/{source_id}` 手动触发一次，绕过 cron

**根因**：采集频率过�?/ 令牌桶配置过�?/ 上游源临时收紧限�?**恢复**：令牌桶自动恢复；下一�?cron 自动重试
**事后**：若频发 �?调高 `rate_limiter.capacity` 或降低采�?cron 频率

---

#### 4.3.2 L2：故障（API 短时不可用）

**症状**�?- `airdrop_collection_status{source=X,status="error"}` 持续 >5min
- 日志出现 `5xx` 响应连续 �? 次或连接超时
- `airdrop_fetcher_circuit_open{source=X} == 1`（熔断器打开�?
**排查**�?1. `curl -I <source-endpoint>` 确认源是否在�?2. �?`airdrop_fetcher_errors_total{source=X,code}` 看错误码分布
3. 是否 API key 失效？（401/403�?4. 是否网络分区？`ping <source-domain>`

**止损**�?- 该源自动跳过本轮，下一�?cron 重试（指数退避）
- 该源故障不影响其他源采集；已发现项目照常进入分析管道
- 若是关键源（DefiLlama/GitHub）故�?�?监控发现项目数下降，但不中断服务

**根因**：源宕机 / 网络分区 / API key 失效 / 代码 bug
**恢复**：熔断窗口（60s）后自动半开探测；持续失败需人工介入
**事后**：若频发 �?�?TTL / 加备用源 / 检�?key 轮换

---

#### 4.3.3 L3：停服（API 长时不可用，>1 小时�?
**症状**�?- L2 故障持续 >1 小时未恢�?- `airdrop_collection_success_ratio{source=X}` 7 日均�?<50%
- 告警：`采集�?{source} 停服`

**排查**�?1. 确认是否上游官方公告（如 Twitter API 政策变更、GitHub 大规模故障）
2. 检�?API key 是否被吊销：手�?`curl -H "Authorization: Bearer $KEY" <endpoint>`
3. 确认是否 IP 被封：从服务�?IP 测试 + 本地测试对比

**止损**（按 `DATA_SOURCE_STRATEGY.md §采集故障降级矩阵`）：
| 故障�?| 降级动作 |
|---|---|
| DefiLlama | 降级：仅�?CoinGecko + GitHub 发现 |
| GitHub | 降级：仅�?DefiLlama TVL 评估活跃�?|
| CoinGecko | 标记 `has_token=unknown`，放行进分析；告�?|
| Twitter | 降级：仅保留其他源；告警 |
| 链上（Etherscan�?| 降级：仅�?DefiLlama TVL 交叉验证 |
| Alchemy webhook | 告警，人工介入；切换�?Etherscan 轮询 |
| Galxe/Layer3 | 降级：无任务平台信号 |

**全局降级规则**�?- �? 个核心源同时 L3 �?系统进入"降级采集模式"：仅保留 DefiLlama + GitHub，停止其他源；告�?- 所有采集源�?L3/L4 �?系统进入"维护模式"：停止采集调度器，仅响应手动输入与已有项目重跑；告警

**根因**：上游长期故�?/ API 政策变更 / IP 封禁 / key 吊销
**恢复**�?- 上游恢复后，对该源做一次全量回扫（`POST /api/v1/collections/trigger/{source_id}`�?- 数据补偿：检查故障期间是否有漏采项目，对比其他源的发现量
**事后**：评估是否接入备用源；若政策变更 �?新增 ADR 评估替代方案

---

#### 4.3.4 L4：付费超限（付费源额度耗尽�?
**症状**�?- Twitter / 链上 付费源返�?`402 Payment Required` �?`429` + `quota_exceeded`
- 月度配额监控：`airdrop_collection_api_calls{source=X}` 月累计接近购买额�?- 告警：`付费�?{source} 配额耗尽`

**排查**�?1. �?`collection_logs WHERE source_id=X AND started_at >= '本月1�?` 统计月调用数
2. 确认是否有异常高频调用（�?cron 配置错误导致每分钟触发）
3. 确认额度是否被其他环境（dev/staging）消�?
**止损**�?- **Twitter 配额耗尽**：`TWITTER_ENABLED=false` 重启，停�?Twitter 采集；仅保留其他�?- **链上配额耗尽**：切换至 Etherscan 免费额度�? calls/min�?- **临时提额**：联系上游加购配额（需审批�?
**根因**：月度配额用�?/ 异常高频调用 / dev 环境误用生产 key
**恢复**：下�?1 日自动恢复；或加购配额后重启
**事后**�?- 评估是否调整采集频率以降低消�?- 检�?dev/staging 是否使用独立 key
- 评估 `LLM_DISCOVERY_SCORE_THRESHOLD` 是否过低导致过多项目进入分析（间接增加链上调用）

---

#### 4.3.5 采集质量退�?
**症状**（对�?`DATA_SOURCE_STRATEGY.md §采集质量评估指标`）：
- 误报�?>20%（IGNORE �?+ discovery_score 虚高项目占比�?- 漏报�?>25%（手动补充项目中应被自动发现但未发现的比例）
- 源覆盖率 <20%（进入分析的项目中被 �? 个源命中的比例）
- 采集稳定�?<90%（`collection_logs.status='success'` 占比�?
**排查**�?1. �?`evaluation/collection/` 最近月�?2. 确认是否某源长期故障导致覆盖率下�?3. 确认 `discovery_score` 计算是否异常（某源信号强度权重过高）

**止损**�?- 误报率高 �?调高 `DISCOVERY_SCORE_ANALYSIS_THRESHOLD`（如 0.3 �?0.4�?- 漏报率高 �?临时增加数据源或扩大关键词覆�?- 源覆盖率�?�?接入更多交叉验证�?
**根因**：阈值过�?/ 源覆盖不�?/ 信号权重配置不当 / 源长期故�?**恢复**：调整阈值或配置后，下一轮采集自动应用新规则
**事后**：更�?`DATA_SOURCE_STRATEGY.md §新项目识别规则` 的阈值表

### 4.4 LLM 成本超预�?**症状**：`airdrop_llm_cost_usd_total > daily_budget_usd` 告警
**排查**�?1. `airdrop_llm_calls_total` 是否异常增长
2. 是否有人手动触发大量 `/run`�?3. 是否 prompt 变长（token 用量 `airdrop_llm_tokens_total` 增长）？

**止损**�?- 自动停用已生效（超预算当日不再调 LLM�?- 手动 `export LLM_ENABLED=false` 重启，强制走规则引擎

**根因**：预算过�?/ 调用量异�?/ prompt 失控
**恢复**：调 `LLMConfig.daily_budget_usd` 或修 prompt
**事后**：评估是否调采样率（ENGINEERING_ROADMAP.md §19.4�?
### 4.5 库内项目不增�?**症状**：`airdrop_projects_in_db` 当日无增�?**排查**�?1. `airdrop_run_total` 是否有触发？�?�?分析调度器问�?2. 采集调度器是否运行？�?`airdrop_collection_total{status="success"}` 当日是否有计数（v2.0，ADR-012�?3. 有采集但 `airdrop_projects_inserted_total=0` �?   - Collector 拉空（外部源全挂，见 §4.3�?   - 全部 dedup 命中已有项目（正常，�?`updated_total`�?   - 全部�?quarantine（看 `quarantine_pending`�?   - `discovery_score < 0.3` 全部被过滤（�?`raw_projects WHERE discovery_score < 0.3`�?
**止损**�?- 手动 `POST /run`（手动输入路径）保证有演示数�?- 若采集调度器�?�?`POST /api/v1/collections/trigger/{source_id}` 手动触发一次采�?
**根因**：采集调度器�?/ 外部源全�?/ dedup_key 全命�?/ discovery_score 阈值过�?/ 校验过严
**恢复**：按根因对应处理

### 4.6 数据质量退�?**症状**：`airdrop_data_completeness_ratio{tier="P0"} < 1.0` �?P1 < 0.8
**排查**�?1. 哪个字段完整性下降？`completeness_ratio{field=X}`
2. 查该字段最近的 quarantine 记录
3. 是否�?source 全挂导致字段空？

**止损**：受影响项目�?ENGINEERING_ROADMAP.md §7.6 降级（自动），保证输出不�?**根因**：fetcher 解析�?/ 字段 schema 变更 / source 限流
**恢复**：修 fetcher；quarantine 处理后回�?**事后**：补 schema 校验测试

### 4.7 健康检查失�?**症状**：`/health` 返回�?200 或超�?**排查**�?1. 容器是否运行？`docker ps`
2. 端口是否占用？`lsof -i:8000`
3. DB 是否可连？`sqlite3 data/airdrop.db ".tables"`

**止损**：`docker restart airdrop-alpha`
**根因**：进程挂 / 端口冲突 / DB 损坏
**恢复**：重启；DB 损坏从备份恢�?
### 4.8 评分异常（用户报告）
**症状**：用户反馈某项目评分明显不合�?**排查**�?1. `GET /project/{id}` 看四 agent 明细 + reason
2. `SELECT * FROM logs WHERE project_id=? ORDER BY timestamp` �?agent 输入输出
3. 判断是数据问�?/ 权重问题 / 规则 bug

**止损**：必要时手动 `POST /re-score/{id}` 用最新数据重�?**根因**：数据脏 / 权重需校准 / 规则逻辑�?**恢复**：修�?re-score
**事后**：补 golden 回归用例（ENGINEERING_ROADMAP.md §14.6�?
---

## 5. 自动�?Runbook（Auto-Runbook�?
> V2+ 引入自动化诊断与自愈脚本，减少人工介入�?
### 5.1 自动诊断脚本

```bash
#!/bin/bash
# scripts/diagnose.sh - 自动诊断常见问题

echo "=== Airdrop Alpha 自动诊断 ==="

# 1. 健康检�?echo "[1/5] 健康检�?.."
HEALTH=$(curl -s http://localhost:8002/health)
if echo "$HEALTH" | grep -q '"status":"healthy"'; then
  echo "  �?服务健康"
else
  echo "  �?服务异常: $HEALTH"
  echo "  �?建议: docker restart airdrop-alpha"
fi

# 2. 最�?run 状�?echo "[2/5] 最�?run 状�?.."
RUNS=$(curl -s "http://localhost:8002/api/v1/audit?action=run&limit=5")
echo "$RUNS" | grep -q '"status":"success"' && echo "  �?最�?run 成功" || echo "  �?最�?run 失败"

# 3. 数据库连�?echo "[3/5] 数据库连�?.."
DB_STATUS=$(curl -s http://localhost:8002/health | grep -o '"db":"[^"]*"')
echo "  状�? $DB_STATUS"

# 4. 外部源健�?echo "[4/5] 外部源健�?.."
METRICS=$(curl -s http://localhost:8002/metrics)
CIRCUIT_OPEN=$(echo "$METRICS" | grep "airdrop_fetcher_circuit_open" | grep -v "^#" | awk '{print $2}')
if [ "$CIRCUIT_OPEN" = "0" ] || [ -z "$CIRCUIT_OPEN" ]; then
  echo "  �?无熔�?
else
  echo "  �?存在熔断�? $CIRCUIT_OPEN"
fi

# 5. 磁盘空间
echo "[5/5] 磁盘空间..."
DISK_USAGE=$(df -h / | awk 'NR==2 {print $5}')
echo "  使用�? $DISK_USAGE"

echo "=== 诊断完成 ==="
```

### 5.2 自动自愈脚本

```bash
#!/bin/bash
# scripts/heal.sh - 自动自愈常见问题

echo "=== Airdrop Alpha 自动自愈 ==="

# 1. 服务挂了 �?重启
if ! curl -sf http://localhost:8002/health > /dev/null; then
  echo "[自愈] 服务不可达，重启�?.."
  docker restart airdrop-alpha
  sleep 10
fi

# 2. DB �?�?杀掉冲突进�?if docker logs airdrop-alpha --since 5m 2>&1 | grep -q "database is locked"; then
  echo "[自愈] 检测到 DB 锁，重启服务..."
  docker restart airdrop-alpha
fi

# 3. 磁盘 >80% �?清理�?backups
DISK_PCT=$(df / | awk 'NR==2 {print $5}' | sed 's/%//')
if [ "$DISK_PCT" -gt 80 ]; then
  echo "[自愈] 磁盘使用�?${DISK_PCT}%，清�?7 天前 backups..."
  find ./backups -name "*.db" -mtime +7 -delete
  find ./backups -name "*.sql.gz" -mtime +7 -delete
fi

# 4. 连续 run 失败 �?�?seed 模式重跑
RECENT_FAILURES=$(curl -s "http://localhost:8002/api/v1/audit?action=run&limit=3" | grep -c '"status":"error"')
if [ "$RECENT_FAILURES" -ge 2 ]; then
  echo "[自愈] 检测到连续失败，切 seed 模式重跑..."
  curl -s -X POST http://localhost:8002/api/v1/run -H 'Content-Type: application/json' -d '{"source":"seed"}'
fi

echo "=== 自愈完成 ==="
```

### 5.3 定时巡检 cron

```bash
# crontab -e（每小时执行一次）
0 * * * * /app/scripts/diagnose.sh >> /var/log/airdrop/diagnose.log 2>&1
*/30 * * * * /app/scripts/heal.sh >> /var/log/airdrop/heal.log 2>&1
```

---

## 5. 配置变更

### 5.1 变更流程
1. �?`config.py` �?`.env.example`
2. PR + 说明（为何改、影响什么）
3. CI 测试通过
4. 部署�?`/health` 确认 `config_version` 更新
5. 观察相关指标 1h

### 5.2 常见配置变更
| 变更 | 影响 | 是否需 ADR |
| --- | --- | --- |
| 调权�?| 评分漂移 | 是（ENGINEERING_ROADMAP.md §7.9 灰度流程�?|
| 调阈值（FARM/WATCH�?| label 分布变化 | �?|
| �?TTL | 数据新鲜�?外部源负�?| �?|
| �?LLM 预算 | 成本/质量权衡 | �?|
| �?cron 时间 | run 触发�?| �?|
| �?sector 词表 | 归一化结�?| 否，但需数据 review |
| 新增数据�?| 完整性提�?| �?|

### 5.3 热更新（V3 前瞻�?- MVP/V2：配置变更需重启容器
- V3：权�?阈值支持热加载（admin API + 鉴权），但仍�?changelog

---

## 6. 备份与恢�?
### 6.1 备份策略
| 数据 | 频率 | 保留 | 方式 |
| --- | --- | --- | --- |
| SQLite（MVP�?| 每日 02:00 | 14 �?| `cp airdrop.db backups/airdrop-$(date +%F).db` |
| PG（V2�?| 每日 02:00 + WAL | 30 �?| `pg_dump` + WAL 归档 |
| 配置�?env�?| 变更�?| 永久 | git（除密钥�? secret store |
| 代码 | 实时 | 永久 | git |

### 6.2 恢复流程（SQLite�?```bash
# 1. 停服�?docker stop airdrop-alpha
# 2. 备份当前损坏文件
mv data/airdrop.db data/airdrop.db.broken
# 3. 恢复
cp backups/airdrop-2026-07-07.db data/airdrop.db
# 4. 重启
docker start airdrop-alpha
# 5. 验证
curl /health
curl -X POST /api/v1/run?source=seed
```

### 6.3 恢复演练
- 每月一次：从备份恢复到测试环境，验证可启动 + 数据完整
- 演练失败 �?备份策略需修正

### 6.4 RPO/RTO
| 阶段 | RPO | RTO |
| --- | --- | --- |
| MVP | 24h | 1h |
| V2 | 1h（WAL�?| 30min |
| V3 | 15min | 15min |

---

## 7. 监控面板使用

### 7.1 日常关注面板（OBSERVABILITY §6�?- 概览行：run 成功率、P95 耗时、库内项目数
- LLM 行：成本曲线、剩余预�?- Fetcher 行：4 源成功率、熔断状�?
### 7.2 告警确认
- 收到告警 �?�?Alertmanager 确认收到
- 处理�?�?标注 `silence` 避免重复通知
- 解决�?�?关闭告警 + �?postmortem（P0/P1�?
### 7.3 面板维护
- 指标新增后同步加面板
- 季度审计面板：清理无用图表、调整阈�?
---

## 8. 安全事件响应

> 详见 SECURITY.md §9。本节仅给值班视角的快速决策树�?
```
收到安全告警
├── 密钥泄漏（P0�?�?  ├── 立即轮换该密�?�?  ├── 审计 logs 定位泄漏范围
�?  └── 通知 Release manager + 开 incident
├── DB 被篡改（P0�?�?  ├── 停服
�?  ├── 从备份恢�?�?  └── 审计谁在何时改了什�?├── 服务不可用（P1�?�?  ├── §4 故障处理
�?  └── 1h 未恢�?�?升级 P0
└── 评分系统性错误（P1�?    ├── �?cron 调度（防继续产出错误评分�?    ├── 修后回滚或热�?    └── re-score 受影响项�?```

---

## 9. 容量管理

### 9.1 容量指标（OBSERVABILITY §3.2�?- 磁盘：SQLite 文件大小、logs 表行数、cache 目录大小
- 内存：容�?RSS（V2 �?cAdvisor�?- 并发：`airdrop_http_requests_total` rate

### 9.2 扩容触发（对�?ENGINEERING_ROADMAP.md §23�?| 触发条件 | 动作 |
| --- | --- |
| SQLite > 1GB | �?PostgreSQL（ADR-004�?|
| logs �?> 100MB | 清理 90 天前数据 |
| 单次 run > 60s | 切后�?task（V2�? 加并发（V3�?|
| 内存 > 80% | 加资�?/ 查内存泄�?|
| 磁盘 > 80% | �?cache / 扩盘 |

### 9.3 容量预估
- 每月评估一次：当前增长趋势 vs 容量上限
- 预计 3 个月内触�?�?提前扩容

---

## 10. 文档维护

- �?runbook 每季�?review 一次，剔除过时流程
- 每次重大故障后补充对应章节（"下次遇到直接照做"�?- 命令示例需在测试环境验证可�?
---

## 11. 紧急联系人（V2+ 填写�?
| 角色 | 姓名 | 联系方式 | 时区 |
| --- | --- | --- | --- |
| Primary on-call | _待填_ | _待填_ | _待填_ |
| Secondary on-call | _待填_ | _待填_ | _待填_ |
| Release manager | _待填_ | _待填_ | _待填_ |
| Data steward | _待填_ | _待填_ | _待填_ |
| 安全负责�?| _待填_ | _待填_ | _待填_ |
