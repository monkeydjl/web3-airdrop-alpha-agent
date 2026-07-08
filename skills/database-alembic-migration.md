# Skill：Alembic 迁移创建（V2）

## 目标
为 V2 从 SQLite 迁移到 Postgres（ADR-004）创建 Alembic 迁移脚本，保证可前向/后向回滚。

## 适用场景
- 新增表或列
- 修改列类型/约束
- 建立索引或外键

## 输入要求
- 文件：`docs/adr/ADR-004-sqlite-to-postgres.md`
- 文件：`docs/DATABASE_DDL.md`（目标 schema）
- 信息：变更内容、是否需数据回填

## 执行步骤

### Step 1: 生成迁移骨架
- 操作：在 `database/migrations/` 运行 `alembic revision -m "<desc>"` 生成 `xxxx_<desc>.py`
- 验证：文件含 `upgrade()` 与 `downgrade()` 两个函数

### Step 2: 编写 upgrade
- 操作：使用 `op.create_table` / `op.add_column` / `op.create_index`，命名遵循 `idx_<表>_<列>`
- 验证：列类型与 `DATABASE_DDL.md` 一致；新增列带 `server_default` 避免 NOT NULL 报错

### Step 3: 编写 downgrade
- 操作：对称回滚（`op.drop_column` / `op.drop_table`），保证可降级
- 验证：`downgrade()` 能回到迁移前状态

### Step 4: 同步文档与模型
- 操作：更新 `docs/DATABASE_DDL.md` 与 `backend/app/models.py`（如 ORM 映射变更）
- 验证：DDL、ORM、迁移三者一致

## 输出
- 文件：`database/migrations/versions/xxxx_<desc>.py`
- 文件：`docs/DATABASE_DDL.md`（更新）

## 检查清单
- [ ] 含 `upgrade()` 与 `downgrade()`
- [ ] 命名遵循 `idx_<表>_<列>` / `snake_case` 复数（§3.3）
- [ ] 新增 NOT NULL 列带 `server_default` 或分批处理
- [ ] downgrade 可回滚
- [ ] DATABASE_DDL.md 与 ORM 已同步

## 参考
- `docs/adr/ADR-004-sqlite-to-postgres.md`
- `docs/DATABASE_DDL.md`
- `CONVENTIONS.md §3.3 数据库命名`
