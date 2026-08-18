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
else
    BACKUP_TYPE="sqlite-local"
    if [ -f "data/airdrop.db" ]; then
        cp "data/airdrop.db" "$BACKUP_DIR/$BACKUP_NAME/app.db"
        echo "✅ 本地 SQLite 备份完成 (data/airdrop.db)"
    elif [ -f "backend/data/airdrop.db" ]; then
        cp "backend/data/airdrop.db" "$BACKUP_DIR/$BACKUP_NAME/app.db"
        echo "✅ 本地 SQLite 备份完成 (backend/data/airdrop.db)"
    else
        echo "⚠️  未找到数据库文件，跳过数据库备份"
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