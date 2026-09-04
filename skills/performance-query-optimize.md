# Skill：SQL 查询优化

## 目标
定位并优化慢 SQL 查询，提升 SQLite/Postgres 读写性能，遵循 CONVENTIONS.md §13 与 docs/PERFORMANCE_BENCHMARK.md。

> **现状提醒**：仓库里**没有 `tests/perf/` 目录，也没有任何性能测试**；
> `backend/app/db.py` 里**也没有 `db.query` 这类慢查询日志事件**。
> 想做性能回归得先建，别照旧文档去跑不存在的东西。

## 适用场景
- 列表/聚合接口响应变慢
- 评分写入成为瓶颈
- 全表扫描 / 缺索引

## 输入要求
- 文件：`backend/app/db.py`（DDL 与连接层）、`backend/app/repositories/`（查询实现）
- 文件：`docs/DATABASE_DDL.md`（现有索引清单）
- 文件：`docs/PERFORMANCE_BENCHMARK.md`（基线）
- 文件：`docs/OBSERVABILITY.md`（指标与日志规范）

## 执行步骤

### Step 1: 定位慢查询
- 操作：目前没有内建慢查询日志，可选两条路：
  1. 在待查代码路径临时加 structlog 计时，测完删掉
  2. 看 Prometheus 侧已有的 DB 指标（`airdrop_db_projects_total`、
     `airdrop_db_raw_projects_total`、`airdrop_competition_cache_db_duration_seconds` 等）
- 验证：先确认瓶颈真在 SQL 上，而不是在 fetcher/LLM 等 IO 上

### Step 2: 分析执行计划
- 操作：SQLite 用 `EXPLAIN QUERY PLAN <sql>`；Postgres 用 `EXPLAIN (ANALYZE, BUFFERS)`
- 验证：确认是否走索引（避免 `SCAN TABLE`）
- 说明：本仓双方言并存，SQLite 上的结论不能直接搬到 Postgres

### Step 3: 加索引/改写 SQL
- 操作：缺索引则按 `idx_<表>_<列>` 命名新增
- 验证：**索引也是 schema 变更，必须三处同落**：
  1. `backend/app/db.py` 的 `_sqlite_ddl()` **与** `_postgres_ddl()`
  2. 新的 `backend/alembic/versions/00NN_<desc>.py`
  3. `docs/DATABASE_DDL.md`
  详见 `skills/database-alembic-migration.md`。改写 SQL 时避免 `SELECT *`，
  参数化用 `?`（SQLite）/ `%s`（PG），不要字符串拼接

### Step 4: 验证与基准
- 操作：
  - 正确性：跑受影响模块的测试
    （`cd backend && ./venv/Scripts/python.exe -m pytest tests/test_repository.py tests/api -q --no-cov -p no:cacheprovider`）
  - 迁移可回滚性：`pytest tests/test_alembic_migration.py`（实跑 upgrade/downgrade）
  - 性能：手工计时对比，把数字写回 `docs/PERFORMANCE_BENCHMARK.md`
- 验证：延迟下降且**查询结果集与优化前完全一致**（结果变了就不是优化，是改行为）

## 输出
- 文件：`backend/app/db.py`（双方言 DDL / SQL 改写）
- 文件：`backend/app/repositories/*.py`（查询改写）
- 文件：`backend/alembic/versions/00NN_<desc>.py`（新索引）
- 文件：`docs/DATABASE_DDL.md`、`docs/PERFORMANCE_BENCHMARK.md`（更新）

## 检查清单
- [ ] 用 `EXPLAIN QUERY PLAN` / `EXPLAIN ANALYZE` 确认走索引
- [ ] 索引命名 `idx_<表>_<列>`
- [ ] 新索引三处同落（双方言 DDL + alembic + DATABASE_DDL.md）
- [ ] SQL 仍参数化，未拼接字符串
- [ ] 未引入 SQL 级外键（全仓约定 schema 无 `REFERENCES`）
- [ ] 结果集与优化前一致，相关测试通过
- [ ] PERFORMANCE_BENCHMARK.md 已更新基线
- [ ] 临时加的计时日志已删除

## 参考
- `docs/PERFORMANCE_BENCHMARK.md`
- `docs/OBSERVABILITY.md`
- `docs/DATABASE_DDL.md`
- `CONVENTIONS.md §13 数据库访问模式`
- `skills/database-alembic-migration.md`
