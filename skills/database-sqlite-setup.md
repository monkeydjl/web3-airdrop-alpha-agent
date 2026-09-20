# Skill：SQLite 连接与建表配置

## 目标
维护数据层的连接与幂等建表，遵循 CONVENTIONS.md §13.1 与 docs/DATABASE_DDL.md。

> **双方言注意**：`backend/app/db.py` 同时支持 SQLite 与 Postgres
> （`is_postgres()` / `backend_name()` 判定，`DbConnection` 做包装）。
> **DDL 有两份**：`_sqlite_ddl()` 与 `_postgres_ddl()`，改一份等于埋雷。

## 适用场景
- 初始化新环境数据库
- 新增表/列/索引
- 调整连接参数

## 输入要求
- 文件：`backend/app/db.py`（数据层，`_sqlite_ddl` 从第 240 行起，`_postgres_ddl` 从第 791 行起）
- 文件：`docs/DATABASE_DDL.md`（完整 DDL 文档）
- 文件：`CONVENTIONS.md §13.1 SQLite（MVP）`

## 执行步骤

### Step 1: 连接配置
- 操作：SQLite 侧在 `_connect_sqlite()` 里设置：
  `PRAGMA journal_mode=WAL`、`PRAGMA busy_timeout=<settings.sqlite_busy_timeout_seconds * 1000>`、
  `PRAGMA foreign_keys=ON`、`row_factory = sqlite3.Row`；
  Postgres 侧在 `_connect_postgres()`（`psycopg` + `dict_row` + `autocommit=False`）
- 验证：
  - 路径来自 `settings.db_path`（pydantic-settings），不硬编码
  - `foreign_keys=ON` 是兜底 pragma —— schema 本身**不写 `REFERENCES`**
    （全仓约定，`backend/tests/test_repository.py` 有断言扫 `_postgres_ddl`），
    级联删除在路由层显式先删子表

### Step 2: 幂等建表
- 操作：`init_db(conn=None)` 按方言选 `_postgres_ddl()` / `_sqlite_ddl()`，
  经 `db.executescript(ddl)` 执行
- 验证：
  - 全部 `CREATE TABLE IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS`，重复调用不报错
  - **给既有表加列**用 `_add_column_if_not_exists(...)`（`init_db` 里的补列段），
    不要靠重建表
  - PG 侧没有 `executescript`，`DbConnection.executescript` 会用
    `_split_sql_statements()` 逐条执行 —— 语句之间的分号必须干净

### Step 3: 参数化写入
- 操作：写入用占位符（SQLite `?`；PG 由 `DbConnection` 适配），批量用 `executemany` + 显式事务
- 验证：无 f-string 拼接 SQL（防注入，§13.1）。例外是 `PRAGMA table_info({table})`
  这类无法参数化的元数据查询，表名必须来自代码内白名单而非外部输入

### Step 4: 四处同落
新增表/列必须同时改：
1. `_sqlite_ddl()` **与** `_postgres_ddl()`（两个方言各一份）
2. `init_db()` 的补列逻辑（如果是给既有表加列）
3. `backend/alembic/versions/00NN_<desc>.py`（见 `skills/database-alembic-migration.md`）
4. `docs/DATABASE_DDL.md`

类型对照：SQLite `INTEGER PRIMARY KEY AUTOINCREMENT` / `REAL` / `TIMESTAMP`
↔ PG `SERIAL PRIMARY KEY` / `DOUBLE PRECISION` / `TIMESTAMPTZ`。
命名遵循 `snake_case` 复数表名 / `idx_<表>_<列>` 索引名（§3.3）。

### Step 5: 测试
- 操作：相关测试在
  `backend/tests/test_db_init.py`（建表与幂等）、
  `backend/tests/test_repository.py`（含无外键断言）、
  `backend/tests/test_v2_tables.py`（V2 新表）
- 验证：
  ```bash
  cd backend && ./venv/Scripts/python.exe -m pytest \
    tests/test_db_init.py tests/test_repository.py tests/test_v2_tables.py \
    --no-cov -p no:cacheprovider -q
  ```
- 说明：**不存在 `tests/unit/test_db.py`**，不要新建那个路径

## 输出
- 文件：`backend/app/db.py`（更新，双方言）
- 文件：`backend/alembic/versions/00NN_<desc>.py`（新表/列）
- 文件：`docs/DATABASE_DDL.md`（更新）
- 文件：`backend/tests/test_db_init.py` 等（测试）

## 检查清单
- [ ] 连接启用 WAL + busy_timeout + foreign_keys，`row_factory` 已设
- [ ] `init_db` 幂等（IF NOT EXISTS），加列走 `_add_column_if_not_exists`
- [ ] 双方言 DDL 都改了，类型对照正确
- [ ] schema 内无 `REFERENCES`
- [ ] 全部 SQL 参数化，无 f-string 拼接
- [ ] alembic 迁移与 `DATABASE_DDL.md` 已同步
- [ ] 三个 db 测试文件全绿

## 参考
- `CONVENTIONS.md §13 数据库访问模式`
- `docs/DATABASE_DDL.md`
- `backend/app/db.py`
- `skills/database-alembic-migration.md`
