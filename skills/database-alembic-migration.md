# Skill：Alembic 迁移创建（V2）

## 目标
为 V2 从 SQLite 迁移到 Postgres（ADR-004）创建 Alembic 迁移脚本，保证可前向/后向回滚。

## 适用场景
- 新增表或列
- 修改列类型/约束
- 建立索引或外键

## 输入要求
- 目录：`backend/alembic/versions/`（真实路径，**不是** `database/migrations/`）
- 文件：`docs/DATABASE_DDL.md`（目标 schema）
- 文件：`docs/OPERATIONS.md §3.5`（迁移版本清单，回滚操作的依据）
- 参考模板：`backend/alembic/versions/0009_watched_wallets.py`（最新，含 `_exec_script` 正确写法）
- 信息：变更内容、是否需数据回填

## 执行步骤

### Step 0: 新表必须「三处同落」
本仓 schema 有**三个真相源**，缺一处就会有测试红灯或运行时表不存在：
1. `backend/app/db.py` 的 `_sqlite_ddl()` **与** `_postgres_ddl()`（两个方言各写一份）
2. `backend/alembic/versions/000N_<desc>.py`
3. `docs/DATABASE_DDL.md`

类型对照：SQLite `INTEGER PRIMARY KEY AUTOINCREMENT` / `REAL` / `TIMESTAMP`
↔ PG `SERIAL PRIMARY KEY` / `DOUBLE PRECISION` / `TIMESTAMPTZ`。

### Step 1: 复制最近一个迁移做模板
- 操作：抄 `backend/alembic/versions/0009_watched_wallets.py`（不用 `alembic revision`
  自动生成 —— 本仓是手写 SQL 常量风格）
- 设 `revision` / `down_revision`（当前最新是 `"0009"`，新的应为 `"0010"`）；
  DDL 写成 `_SQLITE_SQL` / `_PG_SQL` 两个模块级常量

### Step 2: 多语句 DDL 必须按分号拆分执行
sqlite3 驱动**一次只接受一条语句**，含 `CREATE INDEX` 的脚本直接 `execute` 会静默
只跑第一条。用 `_exec_script(bind, sql)` 按 `;` 拆分逐条执行（模板见 0005–0007）。

```python
def upgrade() -> None:
    """创建 xxx 表。

    `text` 不在这里 import —— DDL 全部经 `_exec_script` 执行，它自己拿 `text`。
    """
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"
    _exec_script(bind, (_PG_SQL if is_pg else _SQLITE_SQL).strip())
```

**⚠️ 两个 lint 坑（0005/0006 真实踩过，CI 红）**：
- `from typing import Any`（`_exec_script` 的签名要用）**必须放文件头 import 区**。
  贴在 SQL 常量字符串之后会触发 **E402 + I001**，而且 `backend/scripts/*.py` 才有
  E402 豁免，`alembic/versions/` 没有。
- 改用 `_exec_script` 后，`upgrade()` 里原来的 `from sqlalchemy import text`
  就是**死 import** → **F401**。`downgrade()` 若还直接 `bind.execute(text(...))`
  则要保留它自己那份。
- 列表推导式别手写成多行，`ruff format` 会要求压成一行（line-length 120 放得下）。

### Step 3: 编写 downgrade
- 操作：对称回滚（`DROP TABLE IF EXISTS`），保证可降级
- 在 docstring 里**写清回滚丢什么数据**：日志类可丢，用户操作数据（参与流水、
  收益台账）**不可再生成**，必须提醒回滚前导出
- 在 `backend/tests/test_alembic_migration.py` 的 `_REVISION_TABLES` 登记一行，
  可回滚性测试才会覆盖新版本

### Step 4: 不要用 SQL 级外键
**全仓约定：schema 无 `REFERENCES`**（`backend/tests/test_repository.py` 有断言扫
`_postgres_ddl`）。级联删除在路由层显式先删子表 —— 完整性由应用层保证。

### Step 5: 同步 OPERATIONS.md §3.5
那里有「Alembic 迁移目前有 **N 个版本**」+ 逐个文件名清单，
`backend/tests/test_operations_doc_parity.py::TestMigrationCountIsCurrent`
两条断言会核对数量与文件名。
**这份清单是运维 downgrade 的依据，写错会让人回滚到错误版本。**

## 输出
- 文件：`backend/alembic/versions/000N_<desc>.py`
- 文件：`backend/app/db.py`（双方言 DDL）
- 文件：`docs/DATABASE_DDL.md`（更新）
- 文件：`docs/OPERATIONS.md §3.5`（版本计数 + 清单 + 回滚风险）

## 检查清单
- [ ] 三处同落：`db.py` 双方言 + alembic + `DATABASE_DDL.md`
- [ ] 多语句走 `_exec_script` 按分号拆分
- [ ] `from typing import Any` 在文件头；`upgrade()` 里无死 `text` import
- [ ] 无 `REFERENCES`（外键）
- [ ] `_REVISION_TABLES` 已登记
- [ ] `OPERATIONS.md §3.5` 版本数与文件名已同步
- [ ] downgrade docstring 说明数据丢失范围
- [ ] `cd backend && ruff check . && ruff format --check .` 全过（**全目录，不是只跑改动文件**）
- [ ] `cd backend && ./venv/Scripts/python.exe -m pytest tests/test_alembic_migration.py -p no:cacheprovider -q`
      通过（实跑 upgrade/downgrade，约 85s）

## 参考
- `backend/alembic/versions/0009_watched_wallets.py`（最新模板）
- `docs/DATABASE_DDL.md`、`docs/OPERATIONS.md §3.5`
- `CONVENTIONS.md §3.3 数据库命名`
- `skills/deployment-ci-pipeline.md`（本地按 CI 口径复核 lint 的正确命令）
