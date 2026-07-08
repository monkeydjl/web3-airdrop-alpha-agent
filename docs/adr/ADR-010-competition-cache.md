# ADR-010: 竞争度（Competition）子分缓存与增量计数策略

- **Status**: Accepted
- **Date**: 2026-07-08
- **Deciders**: 架构师 / Tech Lead

## 背景

competition 子分（权重 15%）基于同 `sector` 项目数计算，当前每次评分执行 `SELECT COUNT(*) FROM projects WHERE sector=?`。问题：

1. **性能退化**：50k 项目时每条 COUNT 扫描 ~2,500 行，耗时 20–50ms；V2 并发 10 项目各 COUNT 一次 → 200–500ms 在 counting 上。
2. **re-score 累积压力**：re-score 单项目时仍需重新 COUNT 全库，高频 re-score 场景退化明显。
3. **重复计算**：同一轮 run 内多个同 sector 项目重复 COUNT 同数据，无缓存复用。

随着项目数从 MVP 的 ≤1k 增长到 V2 的 ≤50k、V3 的 500k+，必须引入缓存机制避免每次评分全表扫描。

## 决策

采用 **三阶段演进** 的 competition 缓存策略：

### MVP：直接 COUNT

项目数 ≤ 1k，直接 `SELECT COUNT(*) FROM projects WHERE sector=?` 耗时 <10ms，无需缓存。

### V2（单进程）：进程内 LRU 缓存

- Python `OrderedDict` 实现的 LRU 缓存，TTL 300s（5min）。
- **写时失效**（invalidate-on-write）：Write 阶段写入项目后使对应 sector 缓存项失效。
- **读时重建**（read-through）：缓存 miss 时回退 `COUNT(*)` 并更新缓存。
- 规模适用：≤ 50k 项目，单进程部署。

### V2（PG 后）：DB `sector_counts` 物化表 + Trigger 增量更新

- 新增 `sector_counts` 表（`sector TEXT PRIMARY KEY, count INTEGER`）。
- PostgreSQL trigger 在 INSERT/UPDATE/DELETE projects 时自动增减计数。
- 每日全量重建 `sector_counts` + 一致性比对告警（差异 >1% 触发）。
- 规模适用：≤ 50k 项目，多进程部署。

### V3：Redis Sorted Set / 原子计数器

- 使用 Redis `INCR` / `ZINCRBY` 原子操作。
- 规模适用：500k+ 项目，分布式部署。

## 理由

| 备选方案 | 被否理由 |
| --- | --- |
| **每次都 COUNT 全表** | 50k 项目时 200–500ms/run→可接受但不够好，500k 时不可接受 |
| **Redis 缓存（V2）** | 单进程场景引入 Redis 增加运维复杂度，进程内 LRU 足够 |
| **读时缓存（read-through）** | 比写时失效复杂（需处理缓存击穿），写频率低（每日 1 次 run），invalidate 更简单 |
| **MQ 异步更新计数** | 过度设计，competition 子分不要求实时精确 |

选择三阶段演进的核心理由：
- 每个阶段的技术复杂度与系统规模匹配，无超前设计。
- 写时失效 + 读时重建的组合在竞争度不高的写入场景下效果最优。
- 增量计数的精度风险通过每日全量重建 + 一致性比对告警兜底。

## 后果

### 正面
- 50k 项目时 competition 子分计算从 200–500ms 降至 ≈0ms（缓存命中）或 <10ms（COUNT PG 索引）。
- 缓存与 DB 不一致窗口 ≤ TTL（300s），且缓存值偏差不超过 ±1（并发写入时）。
- 增量更新无额外 I/O（trigger 随事务提交）。

### 负面/限制
- 进程内 LRU 在多进程部署时各进程独立缓存，不一致窗口 ≤ TTL。
- `sector_counts` 表需要每日全量重建 + 一致性监控，增加少量运维工作。
- Trigger 实现依赖 PostgreSQL，SQLite 不支持 trigger 自动更新 `sector_counts`（V2 切 PG 前只能用进程内 LRU）。

### 需配套的工作
1. V2 实现进程内 LRU `SectorCountCache` 类（`app/cache.py`）。
2. V2 切 PG 后实现 `sector_counts` 表 + trigger。
3. 注册 5 个竞争度监控指标（cache hits/misses/stale_entries/db_duration/sector_count）。
4. 每日 cron 执行 `sector_counts` 全量重建 + 一致性比对。
5. 数据一致性告警规则：`|sector_counts.count - actual_count| / actual_count > 0.01`。
