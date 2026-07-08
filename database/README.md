# Database — 数据库迁移指南

> 本目录管理数据库 schema、迁移脚本与迁移策略。
>
> 参考：`docs/ENGINEERING_ROADMAP.md §5`（数据模型）、`docs/DATABASE_DDL.md`（完整 DDL）

---

## 目录结构

```
database/
├── README.md               # 本文档
├── migrations/              # Alembic 迁移脚本（V2）
│   ├── env.py
│   ├── alembic.ini
│   └── versions/            # 迁移版本
│       └── 0001_initial.py
├── ddl/                     # DDL 脚本
│   ├── 001_projects_logs.sql    # MVP 建表
│   ├── 002_v2_tables.sql        # V2 新表（feedback/events/quarantine/...）
│   └── 003_indexes.sql          # 索引优化
└── seed/                    # 种子数据
    └── seed_projects.sql
```

---

## MVP 阶段（SQLite）

MVP 使用 SQLite WAL 模式，应用启动时 `init_db()` 幂等建表。

```sql
-- ddl/001_projects_logs.sql
CREATE TABLE IF NOT EXISTS projects (
    id   TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    ...
);
```

**特点**：
- 零运维，无需迁移工具
- 应用启动自动建表
- 变更 schema 通过新增列 + JSON 兼容避免破坏

---

## V2 阶段（PostgreSQL + Alembic）

### 初始化

```bash
# 1. 初始化 Alembic
cd backend
alembic init alembic
# 2. 配置 alembic.ini 中的 sqlalchemy.url
# 3. 创建初始迁移
alembic revision --autogenerate -m "initial schema"
# 4. 应用迁移
alembic upgrade head
```

### 日常迁移流程

```bash
# 创建新迁移
alembic revision --autogenerate -m "add feedback table"

# 查看状态
alembic current
alembic history

# 应用/回滚
alembic upgrade head      # 应用到最新
alembic downgrade -1      # 回滚一步
alembic downgrade base    # 回滚到起点
```

### 迁移原则

1. **可回滚**：每份迁移必须含 `upgrade()` + `downgrade()`
2. **向后兼容**：迁移后旧版应用可继续运行（先兼容双写 → 切读 → 删旧列）
3. **CI 验证**：`alembic upgrade head` → `alembic downgrade base` → `upgrade head` 循环验证

---

## V2 → V3 迁移（数据量增长）

| 场景 | 策略 |
| --- | --- |
| 表结构变更 | Alembic 递增版本 |
| 数据迁移 | 离线迁移脚本（`scripts/migrate_data.py`） |
| SQLite → PG | 迁移脚本 + 数据校验 |
| 大表拆分 | 分片 + 应用层路由 |

---

## 数据一致性

### 每日检查

```sql
-- 检查 sector_counts 与 projects 表一致
SELECT p.sector, p.cnt AS actual, COALESCE(sc.count, 0) AS cached,
       p.cnt - COALESCE(sc.count, 0) AS diff
FROM (SELECT sector, COUNT(*) AS cnt FROM projects GROUP BY sector) p
LEFT JOIN sector_counts sc ON p.sector = sc.sector
HAVING ABS(diff) > 1;
```

### 完整性检查

```sql
-- 检查缺失评分的项目
SELECT id, name, sector FROM projects WHERE score IS NULL;

-- 检查孤立 logs
SELECT COUNT(*) AS orphaned_logs
FROM logs l
LEFT JOIN projects p ON l.project_id = p.id
WHERE p.id IS NULL;
```

---

_文档版本：v1.0 · 2026-07-08_
