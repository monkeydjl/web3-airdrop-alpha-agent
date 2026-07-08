# ADR-004: 数据层 MVP 用 SQLite(WAL)，V2 切 PostgreSQL

- **Status**: Accepted
- **Date**: 2026-07-08
- **Deciders**: 架构 / 后端

## 背景

数据层选型需平衡运维成本与扩展性：
- SQLite：零运维、单文件、本地开发友好；但并发写弱（写锁全局）、无原生行锁。
- PostgreSQL：生产级、并发强、支持复杂查询与 JSON 操作；但 MVP 阶段需额外容器/服务。

MVP 单机单写者场景，SQLite 足够；但需为 V2 数据量增长预留切换路径。

## 决策

- **MVP**：SQLite，开启 **WAL 模式**（Write-Ahead Logging）提升并发读。
- **V2**：切换 PostgreSQL（触发条件见下方）。
- 通过 `db.py` 抽象层隔离，切换仅改 `DB_PATH`/`DATABASE_URL` 连接串，应用层无感。

## V2 切换触发条件（任一满足）

- 库内项目 > 10k
- SQLite 单文件 > 1GB
- 出现 `database is locked` 频发（并发写冲突）
- 需多实例部署（多 writer）

## 理由

| 备选 | 否决理由 |
| --- | --- |
| MVP 直上 PostgreSQL | MVP 单机演示需额外容器，违背"零运维启动" |
| 用 MongoDB | 非关系型，我们的数据是结构化+JSON 列，关系型更合适 |
| **SQLite(WAL) → PG（本决策）** | MVP 零运维；V2 切换仅改连接串 |

## 后果

- **禁用 PG 专有语法**：如 `ON CONFLICT ... DO UPDATE` 部分子句需兼容 SQLite 的 `INSERT OR REPLACE`；JSON 操作用 SQLAlchemy 抽象或应用层处理。
- 并发写靠应用层串行化（`threading.Lock` MVP / 行锁 V2 PG，见 §6.2.3）。
- V2 切换时需 Alembic 迁移，且 SQLite→PG 数据迁移脚本一次性执行。
- WAL 模式产生 `-wal`/`-shm` 文件，备份时需一起拷贝或用 `VACUUM` 后再备份。
- 字段扩展采用"追加列 + JSON 兼容"，避免破坏性迁移，保证 SQLite/PG 双兼容。
