#!/bin/bash

# ══════════════════════════════════════════════════════════════
# Web3 Airdrop Alpha - 备份脚本
# ══════════════════════════════════════════════════════════════
#
# 用途: 备份 SQLite 数据库和日志文件
# 使用: ./scripts/backup.sh [backup-dir]
#
# ══════════════════════════════════════════════════════════════

set -e

# 配置
BACKUP_DIR="${1:-./backups}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_NAME="airdrop-alpha-backup-$TIMESTAMP"
CONTAINER_NAME="airdrop-alpha-backend"

echo "🗂️  开始备份..."
echo "备份目录: $BACKUP_DIR/$BACKUP_NAME"
echo ""

# 创建备份目录
mkdir -p "$BACKUP_DIR/$BACKUP_NAME"

# 检查是否在 Docker 环境
if docker ps --filter "name=$CONTAINER_NAME" --format "{{.Names}}" 2>/dev/null | grep -q "$CONTAINER_NAME"; then
    echo "📦 检测到 Docker 容器，从容器备份..."

    # 备份数据库
    echo "1️⃣  备份数据库..."
    docker exec "$CONTAINER_NAME" sqlite3 /app/data/app.db ".backup /app/data/backup.db"
    docker cp "$CONTAINER_NAME:/app/data/backup.db" "$BACKUP_DIR/$BACKUP_NAME/app.db"
    docker exec "$CONTAINER_NAME" rm /app/data/backup.db
    echo "✅ 数据库备份完成"

    # 备份日志
    echo ""
    echo "2️⃣  备份日志..."
    if docker exec "$CONTAINER_NAME" test -d /app/logs 2>/dev/null; then
        docker cp "$CONTAINER_NAME:/app/logs" "$BACKUP_DIR/$BACKUP_NAME/"
        echo "✅ 日志备份完成"
    else
        echo "ℹ️  无日志文件需要备份"
    fi

else
    echo "💻 本地环境，从本地文件备份..."

    # 备份数据库
    echo "1️⃣  备份数据库..."
    if [ -f "data/app.db" ]; then
        cp "data/app.db" "$BACKUP_DIR/$BACKUP_NAME/app.db"
        echo "✅ 数据库备份完成"
    elif [ -f "backend/data/app.db" ]; then
        cp "backend/data/app.db" "$BACKUP_DIR/$BACKUP_NAME/app.db"
        echo "✅ 数据库备份完成"
    else
        echo "⚠️  未找到数据库文件"
    fi

    # 备份日志
    echo ""
    echo "2️⃣  备份日志..."
    if [ -d "logs" ]; then
        cp -r logs "$BACKUP_DIR/$BACKUP_NAME/"
        echo "✅ 日志备份完成"
    elif [ -d "backend/logs" ]; then
        cp -r backend/logs "$BACKUP_DIR/$BACKUP_NAME/"
        echo "✅ 日志备份完成"
    else
        echo "ℹ️  无日志文件需要备份"
    fi
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
cd - > /dev/null

BACKUP_SIZE=$(du -h "$BACKUP_DIR/$BACKUP_NAME.tar.gz" | cut -f1)
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
