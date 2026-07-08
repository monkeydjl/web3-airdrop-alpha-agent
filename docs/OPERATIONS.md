# 运维 Runbook

> 配套文档：ENGINEERING_ROADMAP.md §15、SECURITY.md §9、OBSERVABILITY.md §5。本文档是值班/运维人员的操作手册，覆盖日常运维、故障处理、部署发布、备份恢复。
>
> 适用阶段：MVP 单机部署 → V2 容器化 → V3 多实例。每节标注适用阶段。

---

## 1. 角色与值班

### 1.1 角色定义
| 角色 | 职责 | 阶段 |
| --- | --- | --- |
| Primary on-call | 响应 critical 告警，<30min 介入 | V2+ |
| Secondary on-call | Primary 未响应 15min 后升级 | V2+ |
| Data steward | 处理 quarantine、词表维护 | V2+ |
| Release manager | 发布窗口决策、回滚授权 | V2+ |

### 1.2 值班轮换（V2+）
- 每周轮换，周一 00:00 UTC 交接
- 值班期间保持即时通讯可达（Slack/电话）
- 值班前检查：告警通道是否通、`/health` 是否绿、最近 run 是否成功

### 1.3 MVP 阶段
- 无正式值班；作者/小团队自行响应
- 告警走邮件，工作时间处理

---

## 2. 日常运维检查项

### 2.1 每日（自动化 + 人工抽查）
| 检查项 | 方式 | 期望 | 异常处理 |
| --- | --- | --- | --- |
| 每日 run 成功 | 查 `airdrop_run_total{status="success"}` | 当日 ≥1 次 | §4.1 |
| 健康检查 | `curl /health` | `ok:true` | §4.2 |
| 库内项目增长 | `airdrop_projects_in_db` | 每日 +20–50 | §4.5 |
| quarantine 积压 | `airdrop_quarantine_pending` | <50 | §4.6 |
| LLM 成本（V2） | `airdrop_llm_cost_usd_total` | < 日预算 | §4.7 |
| 外部源熔断 | `airdrop_fetcher_circuit_open` | 全 0 | §4.3 |
| 数据完整性 | `airdrop_data_completeness_ratio` | P0=1.0 | §4.6 |

### 2.2 每周
- 检查磁盘空间（SQLite + backups + cache 目录）
- 检查 logs 表增长，超 50MB 考虑清理（保留 90 天）
- 审阅告警趋势（是否有反复触发的规则）
- 词表审计：剔除无项目命中的死赛道词条

### 2.3 每月
- 依赖安全扫描 `pip-audit` 全量
- 数据质量月报复盘（V2+）
- 密钥轮换检查（V2+，超 90 天未换提醒）
- 备份恢复演练（§6.3）

---

## 3. 部署与发布

### 3.1 MVP 本地部署
```bash
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python run.py
# 首次启动自动建库；导入种子数据
curl -X POST http://localhost:8000/api/v1/run -H 'Content-Type: application/json' -d '{"source":"seed"}'
```

### 3.2 Docker 部署
```bash
# 构建
docker build -t airdrop-alpha:latest .

# 单容器
docker run -d --name airdrop-alpha \
  -p 8000:8000 \
  -v $(pwd)/data:/app/backend/data \
  -e PORT=8000 \
  --restart unless-stopped \
  airdrop-alpha:latest

# 或 compose 一键
docker compose up -d --build
```

### 3.3 发布流程（V2+）
```
1. PR 合并到 main（CI 全绿）
2. 打 tag v*.*.*
3. CI 自动构建镜像 → ghcr.io/<org>/airdrop-alpha:<tag>
4. Release manager 确认发布窗口
5. 演示环境部署 + 冒烟（curl /health + POST /run?source=seed）
6. 冒烟通过 → 更新 latest tag → 生产部署
7. 观察 30min（告警 + 错误率）
```

### 3.4 回滚
- **应用回滚**（优先）：重新部署上一版本镜像 `<tag-prev>`
- **数据库回滚**（慎用）：仅当 schema 迁移破坏性时
  ```bash
  alembic downgrade -1
  ```
- **配置回滚**：恢复 `.env` 上一版本，重启容器
- 回滚决策：P0/P1 事件 + Release manager 授权

### 3.5 蓝绿/金丝雀（V3）
- V3 引入：新版本先发 10% 流量，观察 1h 无异常再全量
- 数据库迁移仍需"先兼容双写 → 切读 → 删旧列"三步（ENGINEERING_ROADMAP.md §15.3）

---

## 4. 故障处理手册

> 每个故障：症状 → 排查 → 止损 → 根因 → 恢复 → 事后。

### 4.1 每日 run 失败
**症状**：`airdrop_run_total{status="error"}` 增加；告警 `pipeline 连续失败`
**排查**：
1. `docker logs airdrop-alpha --since 30m | grep "run.error"`
2. 确认失败 stage：collect / analyze / score / db.write
3. 查 `logs` 表 `WHERE agent_name='orchestrator' ORDER BY timestamp DESC LIMIT 5`

**止损**：
- 若 collect 失败 → 切 `source=seed` 跑一次保证有输出
- 若 db.write 失败 → 见 §4.2

**根因**：外部源全挂 / DB 锁 / 配置错误 / 代码 bug
**恢复**：修后 `curl -X POST /api/v1/run`
**事后**：补测试用例 + ADR（若是设计缺陷）

### 4.2 DB 写失败 / `database is locked`
**症状**：`airdrop_db_write_errors_total` 增加；SQLite `database is locked`
**排查**：
1. 是否有多个 writer 进程？`lsof airdrop.db`
2. 是否有长事务未提交？查 logs `db.query.duration` P95
3. 磁盘是否满？`df -h`

**止损**：
- 杀掉冲突 writer，单 writer 重启
- 磁盘满 → 清理 `data/cache/` 与旧 backups

**根因**：并发写 / 长事务 / 磁盘满 / V2 未切 PG
**恢复**：重启服务；若 DB 损坏 → 从备份恢复（§6.2）
**升级**：频繁发生 → 加速 V2 PG 迁移

### 4.3 外部源熔断
**症状**：`airdrop_fetcher_circuit_open{source=X} == 1` 持续 >5min
**排查**：
1. `curl -I <source-endpoint>` 确认源是否在线
2. 查 `airdrop_fetcher_errors_total{source=X,code}` 看错误码分布
3. 是否 API key 失效？（401/403）

**止损**：
- 该源走降级路径（ENGINEERING_ROADMAP.md §10.2），不影响主流程
- 若 key 失效 → 轮换 key 后重启

**根因**：源宕机 / 限流 / key 失效 / 网络分区
**恢复**：熔断窗口（60s）后自动半开探测；持续失败需人工介入
**事后**：若频发 → 调 TTL / reliability / 加备用源

### 4.4 LLM 成本超预算
**症状**：`airdrop_llm_cost_usd_total > daily_budget_usd` 告警
**排查**：
1. `airdrop_llm_calls_total` 是否异常增长
2. 是否有人手动触发大量 `/run`？
3. 是否 prompt 变长（token 用量 `airdrop_llm_tokens_total` 增长）？

**止损**：
- 自动停用已生效（超预算当日不再调 LLM）
- 手动 `export LLM_ENABLED=false` 重启，强制走规则引擎

**根因**：预算过低 / 调用量异常 / prompt 失控
**恢复**：调 `LLMConfig.daily_budget_usd` 或修 prompt
**事后**：评估是否调采样率（ENGINEERING_ROADMAP.md §19.4）

### 4.5 库内项目不增长
**症状**：`airdrop_projects_in_db` 当日无增长
**排查**：
1. `airdrop_run_total` 是否有触发？无 → 调度器问题
2. 有 run 但 `airdrop_projects_inserted_total=0` →
   - Collector 拉空（外部源空/缓存 miss）
   - 全部 dedup 命中已有项目（正常，看 `updated_total`）
   - 全部进 quarantine（看 `quarantine_pending`）

**止损**：手动 `POST /run?source=seed` 保证有演示数据
**根因**：调度器挂 / 外部源空 / 校验过严
**恢复**：按根因对应处理

### 4.6 数据质量退化
**症状**：`airdrop_data_completeness_ratio{tier="P0"} < 1.0` 或 P1 < 0.8
**排查**：
1. 哪个字段完整性下降？`completeness_ratio{field=X}`
2. 查该字段最近的 quarantine 记录
3. 是否某 source 全挂导致字段空？

**止损**：受影响项目按 ENGINEERING_ROADMAP.md §7.6 降级（自动），保证输出不崩
**根因**：fetcher 解析挂 / 字段 schema 变更 / source 限流
**恢复**：修 fetcher；quarantine 处理后回填
**事后**：补 schema 校验测试

### 4.7 健康检查失败
**症状**：`/health` 返回非 200 或超时
**排查**：
1. 容器是否运行？`docker ps`
2. 端口是否占用？`lsof -i:8000`
3. DB 是否可连？`sqlite3 data/airdrop.db ".tables"`

**止损**：`docker restart airdrop-alpha`
**根因**：进程挂 / 端口冲突 / DB 损坏
**恢复**：重启；DB 损坏从备份恢复

### 4.8 评分异常（用户报告）
**症状**：用户反馈某项目评分明显不合理
**排查**：
1. `GET /project/{id}` 看四 agent 明细 + reason
2. `SELECT * FROM logs WHERE project_id=? ORDER BY timestamp` 看 agent 输入输出
3. 判断是数据问题 / 权重问题 / 规则 bug

**止损**：必要时手动 `POST /re-score/{id}` 用最新数据重算
**根因**：数据脏 / 权重需校准 / 规则逻辑错
**恢复**：修后 re-score
**事后**：补 golden 回归用例（ENGINEERING_ROADMAP.md §14.6）

---

## 5. 自动化 Runbook（Auto-Runbook）

> V2+ 引入自动化诊断与自愈脚本，减少人工介入。

### 5.1 自动诊断脚本

```bash
#!/bin/bash
# scripts/diagnose.sh - 自动诊断常见问题

echo "=== Airdrop Alpha 自动诊断 ==="

# 1. 健康检查
echo "[1/5] 健康检查..."
HEALTH=$(curl -s http://localhost:8000/health)
if echo "$HEALTH" | grep -q '"status":"healthy"'; then
  echo "  ✓ 服务健康"
else
  echo "  ✗ 服务异常: $HEALTH"
  echo "  → 建议: docker restart airdrop-alpha"
fi

# 2. 最近 run 状态
echo "[2/5] 最近 run 状态..."
RUNS=$(curl -s "http://localhost:8000/api/v1/audit?action=run&limit=5")
echo "$RUNS" | grep -q '"status":"success"' && echo "  ✓ 最近 run 成功" || echo "  ✗ 最近 run 失败"

# 3. 数据库连接
echo "[3/5] 数据库连接..."
DB_STATUS=$(curl -s http://localhost:8000/health | grep -o '"db":"[^"]*"')
echo "  状态: $DB_STATUS"

# 4. 外部源健康
echo "[4/5] 外部源健康..."
METRICS=$(curl -s http://localhost:8000/metrics)
CIRCUIT_OPEN=$(echo "$METRICS" | grep "airdrop_fetcher_circuit_open" | grep -v "^#" | awk '{print $2}')
if [ "$CIRCUIT_OPEN" = "0" ] || [ -z "$CIRCUIT_OPEN" ]; then
  echo "  ✓ 无熔断"
else
  echo "  ⚠ 存在熔断源: $CIRCUIT_OPEN"
fi

# 5. 磁盘空间
echo "[5/5] 磁盘空间..."
DISK_USAGE=$(df -h / | awk 'NR==2 {print $5}')
echo "  使用率: $DISK_USAGE"

echo "=== 诊断完成 ==="
```

### 5.2 自动自愈脚本

```bash
#!/bin/bash
# scripts/heal.sh - 自动自愈常见问题

echo "=== Airdrop Alpha 自动自愈 ==="

# 1. 服务挂了 → 重启
if ! curl -sf http://localhost:8000/health > /dev/null; then
  echo "[自愈] 服务不可达，重启中..."
  docker restart airdrop-alpha
  sleep 10
fi

# 2. DB 锁 → 杀掉冲突进程
if docker logs airdrop-alpha --since 5m 2>&1 | grep -q "database is locked"; then
  echo "[自愈] 检测到 DB 锁，重启服务..."
  docker restart airdrop-alpha
fi

# 3. 磁盘 >80% → 清理旧 backups
DISK_PCT=$(df / | awk 'NR==2 {print $5}' | sed 's/%//')
if [ "$DISK_PCT" -gt 80 ]; then
  echo "[自愈] 磁盘使用率 ${DISK_PCT}%，清理 7 天前 backups..."
  find ./backups -name "*.db" -mtime +7 -delete
  find ./backups -name "*.sql.gz" -mtime +7 -delete
fi

# 4. 连续 run 失败 → 切 seed 模式重跑
RECENT_FAILURES=$(curl -s "http://localhost:8000/api/v1/audit?action=run&limit=3" | grep -c '"status":"error"')
if [ "$RECENT_FAILURES" -ge 2 ]; then
  echo "[自愈] 检测到连续失败，切 seed 模式重跑..."
  curl -s -X POST http://localhost:8000/api/v1/run -H 'Content-Type: application/json' -d '{"source":"seed"}'
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
1. 改 `config.py` 或 `.env.example`
2. PR + 说明（为何改、影响什么）
3. CI 测试通过
4. 部署后 `/health` 确认 `config_version` 更新
5. 观察相关指标 1h

### 5.2 常见配置变更
| 变更 | 影响 | 是否需 ADR |
| --- | --- | --- |
| 调权重 | 评分漂移 | 是（ENGINEERING_ROADMAP.md §7.9 灰度流程） |
| 调阈值（FARM/WATCH） | label 分布变化 | 是 |
| 调 TTL | 数据新鲜度/外部源负载 | 否 |
| 调 LLM 预算 | 成本/质量权衡 | 否 |
| 调 cron 时间 | run 触发点 | 否 |
| 改 sector 词表 | 归一化结果 | 否，但需数据 review |
| 新增数据源 | 完整性提升 | 是 |

### 5.3 热更新（V3 前瞻）
- MVP/V2：配置变更需重启容器
- V3：权重/阈值支持热加载（admin API + 鉴权），但仍记 changelog

---

## 6. 备份与恢复

### 6.1 备份策略
| 数据 | 频率 | 保留 | 方式 |
| --- | --- | --- | --- |
| SQLite（MVP） | 每日 02:00 | 14 天 | `cp airdrop.db backups/airdrop-$(date +%F).db` |
| PG（V2） | 每日 02:00 + WAL | 30 天 | `pg_dump` + WAL 归档 |
| 配置（.env） | 变更时 | 永久 | git（除密钥）+ secret store |
| 代码 | 实时 | 永久 | git |

### 6.2 恢复流程（SQLite）
```bash
# 1. 停服务
docker stop airdrop-alpha
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
- 演练失败 → 备份策略需修正

### 6.4 RPO/RTO
| 阶段 | RPO | RTO |
| --- | --- | --- |
| MVP | 24h | 1h |
| V2 | 1h（WAL） | 30min |
| V3 | 15min | 15min |

---

## 7. 监控面板使用

### 7.1 日常关注面板（OBSERVABILITY §6）
- 概览行：run 成功率、P95 耗时、库内项目数
- LLM 行：成本曲线、剩余预算
- Fetcher 行：4 源成功率、熔断状态

### 7.2 告警确认
- 收到告警 → 在 Alertmanager 确认收到
- 处理中 → 标注 `silence` 避免重复通知
- 解决后 → 关闭告警 + 补 postmortem（P0/P1）

### 7.3 面板维护
- 指标新增后同步加面板
- 季度审计面板：清理无用图表、调整阈值

---

## 8. 安全事件响应

> 详见 SECURITY.md §9。本节仅给值班视角的快速决策树。

```
收到安全告警
├── 密钥泄漏（P0）
│   ├── 立即轮换该密钥
│   ├── 审计 logs 定位泄漏范围
│   └── 通知 Release manager + 开 incident
├── DB 被篡改（P0）
│   ├── 停服
│   ├── 从备份恢复
│   └── 审计谁在何时改了什么
├── 服务不可用（P1）
│   ├── §4 故障处理
│   └── 1h 未恢复 → 升级 P0
└── 评分系统性错误（P1）
    ├── 停 cron 调度（防继续产出错误评分）
    ├── 修后回滚或热修
    └── re-score 受影响项目
```

---

## 9. 容量管理

### 9.1 容量指标（OBSERVABILITY §3.2）
- 磁盘：SQLite 文件大小、logs 表行数、cache 目录大小
- 内存：容器 RSS（V2 接 cAdvisor）
- 并发：`airdrop_http_requests_total` rate

### 9.2 扩容触发（对齐 ENGINEERING_ROADMAP.md §23）
| 触发条件 | 动作 |
| --- | --- |
| SQLite > 1GB | 切 PostgreSQL（ADR-004） |
| logs 表 > 100MB | 清理 90 天前数据 |
| 单次 run > 60s | 切后台 task（V2）/ 加并发（V3） |
| 内存 > 80% | 加资源 / 查内存泄漏 |
| 磁盘 > 80% | 清 cache / 扩盘 |

### 9.3 容量预估
- 每月评估一次：当前增长趋势 vs 容量上限
- 预计 3 个月内触顶 → 提前扩容

---

## 10. 文档维护

- 本 runbook 每季度 review 一次，剔除过时流程
- 每次重大故障后补充对应章节（"下次遇到直接照做"）
- 命令示例需在测试环境验证可用

---

## 11. 紧急联系人（V2+ 填写）

| 角色 | 姓名 | 联系方式 | 时区 |
| --- | --- | --- | --- |
| Primary on-call | _待填_ | _待填_ | _待填_ |
| Secondary on-call | _待填_ | _待填_ | _待填_ |
| Release manager | _待填_ | _待填_ | _待填_ |
| Data steward | _待填_ | _待填_ | _待填_ |
| 安全负责人 | _待填_ | _待填_ | _待填_ |
