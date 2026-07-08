# Skill：SQL 查询优化

## 目标
定位并优化慢 SQL 查询，提升 SQLite/Postgres 读写性能，遵循 CONVENTIONS.md §13 与 docs/PERFORMANCE_BENCHMARK.md。

## 适用场景
- 列表/聚合接口响应变慢
- 评分写入成为瓶颈
- 全表扫描 / 缺索引

## 输入要求
- 文件：`backend/app/db.py`
- 文件：`docs/DATABASE_DDL.md`（现有索引）
- 文件：`docs/PERFORMANCE_BENCHMARK.md`
- 文件：`docs/OBSERVABILITY.md`（慢查询日志）

## 执行步骤

### Step 1: 定位慢查询
- 操作：从 `logs/` 的 structlog（前缀 `db.query`）或 `OBSERVABILITY.md` 指标找出高频/高耗 SQL
- 验证：关注 `airdrop_db_*` 指标与 `db.query` 事件 duration_ms

### Step 2: 分析执行计划
- 操作：SQLite 用 `EXPLAIN QUERY PLAN <sql>`；Postgres 用 `EXPLAIN (ANALYZE, BUFFERS)`
- 验证：确认是否走索引（避免 SCAN TABLE）

### Step 3: 加索引/改写 SQL
- 操作：缺索引则按 `idx_<表>_<列>` 命名新增（改 `DATABASE_DDL.md`）；改写避免 `SELECT *`、用 `?` 参数化
- 验证：索引列匹配 WHERE/ORDER BY/JOIN 字段

### Step 4: 验证与基准
- 操作：在 `tests/perf/` 跑回归，对比 `PERFORMANCE_BENCHMARK.md` 基线
- 验证：P95 延迟下降且结果一致

## 输出
- 文件：`docs/DATABASE_DDL.md`（索引更新）
- 文件：`backend/app/db.py`（SQL 改写）
- 文件：`tests/perf/test_query_<name>.py`

## 检查清单
- [ ] 使用 `EXPLAIN QUERY PLAN` 确认走索引
- [ ] 索引命名 `idx_<表>_<列>`
- [ ] SQL 仍使用 `?` 占位符
- [ ] 性能回归测试通过
- [ ] PERFORMANCE_BENCHMARK.md 已更新基线

## 参考
- `docs/PERFORMANCE_BENCHMARK.md`
- `docs/OBSERVABILITY.md`
- `CONVENTIONS.md §13 数据库访问模式`
