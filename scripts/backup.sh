#!/bin/bash

# ══════════════════════════════════════════════════════════════
# Web3 Airdrop Alpha - 备份脚本
# ══════════════════════════════════════════════════════════════
#
# 用途: 备份 PostgreSQL（生产）或 SQLite（开发）数据库和日志文件
# 使用: ./scripts/backup.sh [backup-dir]
#
# 说明:
#   - 生产环境已切换 PostgreSQL（airdrop-db, postgres:15），
#     使用 pg_dump 逻辑备份（SQL 格式，可精确恢复）
#   - 旧环境 SQLite 备份逻辑保留兼容
#   - 容器名: airdrop-web / airdrop-db（docker-compose.prod.yml）
#
# ══════════════════════════════════════════════════════════════

set -e

# 配置
BACKUP_DIR="${1:-./backups}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_NAME="airdrop-alpha-backup-$TIMESTAMP"
WEB_CONTAINER="airdrop-web"
DB_CONTAINER="airdrop-db"
PG_DB="airdrop"
PG_USER="airdrop"

echo "🗂️  开始备份..."
echo "备份目录: $BACKUP_DIR/$BACKUP_NAME"
echo ""

# 创建备份目录
mkdir -p "$BACKUP_DIR/$BACKUP_NAME"

echo "1️⃣  备份数据库..."
BACKUP_TYPE=""

# 优先 PG：检测生产 PG 容器
if docker ps --filter "name=$DB_CONTAINER" --format "{{.Names}}" 2>/dev/null | grep -q "$DB_CONTAINER"; then
    BACKUP_TYPE="postgres"
    echo "   (PostgreSQL: $DB_CONTAINER, db=$PG_DB)"
    docker exec "$DB_CONTAINER" pg_dump -U "$PG_USER" -d "$PG_DB" \
        --no-owner --no-privileges -F c -f /tmp/airdrop_backup.dump
    docker cp "$DB_CONTAINER:/tmp/airdrop_backup.dump" "$BACKUP_DIR/$BACKUP_NAME/airdrop_pg.dump"
    docker exec "$DB_CONTAINER" pg_dump -U "$PG_USER" -d "$PG_DB" \
        --no-owner --no-privileges -f /tmp/airdrop_backup.sql
    docker cp "$DB_CONTAINER:/tmp/airdrop_backup.sql" "$BACKUP_DIR/$BACKUP_NAME/airdrop_pg.sql"
    docker exec "$DB_CONTAINER" rm -f /tmp/airdrop_backup.dump /tmp/airdrop_backup.sql
    echo "✅ PostgreSQL 数据库备份完成（custom + SQL 双格式）"

# 回退 SQLite：检测旧版后端容器
elif docker ps --filter "name=$WEB_CONTAINER" --format "{{.Names}}" 2>/dev/null | grep -q "$WEB_CONTAINER"; then
    BACKUP_TYPE="sqlite"
    echo "   (SQLite 容器备份)"
    docker exec "$WEB_CONTAINER" python -c "import sqlite3; c=sqlite3.connect('/app/data/app.db'); c.backup(sqlite3.connect('/tmp/backup.db')); c.close()" 2>/dev/null \
        || docker exec "$WEB_CONTAINER" sqlite3 /app/data/app.db ".backup /tmp/backup.db"
    docker cp "$WEB_CONTAINER:/tmp/backup.db" "$BACKUP_DIR/$BACKUP_NAME/app.db"
    docker exec "$WEB_CONTAINER" rm -f /tmp/backup.db
    echo "✅ SQLite 数据库备份完成"

# 最后回退：本地文件
#
# 2026-08-24 修复：原来这里硬写 `cp data/airdrop.db`。
# 实测运行时真正连的库由 `.env` 的 DB_PATH 决定，而 `data/airdrop.db`
# 在这台机器上是一个 94 个项目的**过期副本**（真库 288 项目 / 9.3 MB）。
# 于是在容器都不在的情况下，这个分支会**安静地备份那个过期副本
# 并报告"备份完成"** —— 一次成功的备份报告，配一份没用的备份文件。
# 备份的失败方式里最坏的一种，就是它看起来成功了。
else
    BACKUP_TYPE="sqlite-local"
    DB_PATH_ENV=""
    if [ -f .env ]; then
        DB_PATH_ENV="$(grep -E '^DB_PATH=' .env | tail -1 | cut -d= -f2- | tr -d '[:space:]')"
    fi

    DB_SRC=""
    if [ -n "$DB_PATH_ENV" ] && [ -f "$DB_PATH_ENV" ]; then
        DB_SRC="$DB_PATH_ENV"
    elif [ -n "$DB_PATH_ENV" ] && [ -f "backend/$DB_PATH_ENV" ]; then
        # DB_PATH 是相对路径时，服务的工作目录是 backend/
        DB_SRC="backend/$DB_PATH_ENV"
    fi

    if [ -n "$DB_SRC" ]; then
        # 用 sqlite3 .backup 而不是 cp：cp 一个正在被写入的 SQLite 文件
        # 可能拿到一个撕裂的快照（尤其有 -wal 时），而它照样能被打开，
        # 只是内容不一致 —— 又一种"看起来成功"的失败。
        if command -v sqlite3 &> /dev/null; then
            sqlite3 "$DB_SRC" ".backup '$BACKUP_DIR/$BACKUP_NAME/app.db'"
        elif command -v python3 &> /dev/null; then
            python3 -c "import sqlite3,sys; s=sqlite3.connect(sys.argv[1]); d=sqlite3.connect(sys.argv[2]); s.backup(d); d.close(); s.close()" \
                "$DB_SRC" "$BACKUP_DIR/$BACKUP_NAME/app.db"
        else
            cp "$DB_SRC" "$BACKUP_DIR/$BACKUP_NAME/app.db"
            echo "   ⚠️  无 sqlite3/python3，退化为 cp（运行中的库可能拿到不一致快照）"
        fi
        echo "✅ 本地 SQLite 备份完成（源: $DB_SRC，来自 .env 的 DB_PATH）"
    else
        # 这里必须失败，不能"跳过并报成功"。
        echo "❌ 未找到数据库文件，备份失败"
        echo "   .env 里 DB_PATH=${DB_PATH_ENV:-<未设置>}"
        echo "   不猜其它文件名：猜中一个过期副本比找不到更坏 ——"
        echo "   前者会给你一份看起来成功的、没用的备份。"
        exit 1
    fi
fi

# 备份日志（仅容器内存在时）
echo ""
echo "2️⃣  备份日志..."
if docker ps --filter "name=$WEB_CONTAINER" --format "{{.Names}}" 2>/dev/null | grep -q "$WEB_CONTAINER" \
    && docker exec "$WEB_CONTAINER" test -d /app/backend/logs 2>/dev/null; then
    docker cp "$WEB_CONTAINER:/app/backend/logs" "$BACKUP_DIR/$BACKUP_NAME/"
    echo "✅ 日志备份完成"
elif [ -d "logs" ] && [ -z "$(find logs -maxdepth 1 -type f | head -1)" ]; then
    cp -r logs "$BACKUP_DIR/$BACKUP_NAME/"
    echo "✅ 日志备份完成"
else
    echo "ℹ️  无日志文件需要备份"
fi

# 创建备份信息文件
echo ""
echo "3️⃣  创建备份信息..."
cat > "$BACKUP_DIR/$BACKUP_NAME/backup-info.txt" << EOF
Backup Information
==================

Date: $(date)
Timestamp: $TIMESTAMP
System: $(uname -s)
Environment: ${APP_ENV:-unknown}
Database backend: $BACKUP_TYPE

Files:
$(ls -lh "$BACKUP_DIR/$BACKUP_NAME")
EOF

echo "✅ 备份信息创建完成"

# 压缩备份
echo ""
echo "4️⃣  压缩备份..."
cd "$BACKUP_DIR"
tar -czf "$BACKUP_NAME.tar.gz" "$BACKUP_NAME"
rm -rf "$BACKUP_NAME"
BACKUP_SIZE=$(du -h "$BACKUP_DIR/$BACKUP_NAME.tar.gz" | cut -f1)
cd - > /dev/null
echo "✅ 备份压缩完成: $BACKUP_SIZE"

# 清理旧备份（保留最近 7 天）
echo ""
echo "5️⃣  清理旧备份..."
find "$BACKUP_DIR" -name "airdrop-alpha-backup-*.tar.gz" -mtime +7 -delete
REMAINING_BACKUPS=$(find "$BACKUP_DIR" -name "airdrop-alpha-backup-*.tar.gz" | wc -l)
echo "✅ 清理完成，保留 $REMAINING_BACKUPS 个备份"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ 备份成功！"
echo "备份文件: $BACKUP_DIR/$BACKUP_NAME.tar.gz"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

exit 0