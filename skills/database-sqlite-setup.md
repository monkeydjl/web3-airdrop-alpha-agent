# Skill：SQLite 连接与建表配置

## 目标
为项目配置 SQLite 连接与幂等建表，遵循 CONVENTIONS.md §13.1 与 docs/DATABASE_DDL.md。

## 适用场景
- 初始化新环境数据库
- 新增表/索引
- 调整 `db.py` 连接参数

## 输入要求
- 文件：`backend/app/db.py`（数据层）
- 文件：`docs/DATABASE_DDL.md`（完整 DDL）
- 文件：`CONVENTIONS.md §13.1 SQLite（MVP）`

## 执行步骤

### Step 1: 配置连接
- 操作：在 `backend/app/db.py` 的 `get_connection()` 设置 `journal_mode=WAL`、`foreign_keys=ON`、`row_factory=sqlite3.Row`
- 验证：使用 `config.db_path`（pydantic-settings）而非硬编码路径

### Step 2: 幂等建表
- 操作：`init_db(conn)` 执行 `DATABASE_DDL`（`conn.executescript`），用 `IF NOT EXISTS`
- 验证：重复调用不报错（幂等）

### Step 3: 参数化写入
- 操作：所有写入用 `?` 占位符，批量用 `executemany` + 显式事务
- 验证：无 f-string 拼接 SQL（防注入，CONVENTIONS §13.1）

### Step 4: 更新 DDL 文档
- 操作：新表/索引同步写入 `docs/DATABASE_DDL.md`
- 验证：表名/索引名遵循 `snake_case` 复数 / `idx_<表>_<列>`（§3.3）

## 输出
- 文件：`backend/app/db.py`（更新）
- 文件：`docs/DATABASE_DDL.md`（更新）
- 文件：`tests/unit/test_db.py`（连接/建表测试）

## 检查清单
- [ ] 连接启用 WAL + foreign_keys
- [ ] `init_db` 幂等（IF NOT EXISTS）
- [ ] 全部 SQL 使用 `?` 占位符
- [ ] DATABASE_DDL.md 已同步
- [ ] 建表测试通过（:memory: SQLite）

## 参考
- `CONVENTIONS.md §13 数据库访问模式`
- `docs/DATABASE_DDL.md`
- `backend/app/db.py`
