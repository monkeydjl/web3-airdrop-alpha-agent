#!/usr/bin/env bash
# scripts/deploy/rollback.sh
# 回滚到上一个版本

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

echo_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

echo_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

echo_warn "⚠️  开始回滚..."

# 1. 获取上一个版本
CURRENT_VERSION=$(git describe --tags --abbrev=0)
PREVIOUS_VERSION=$(git describe --tags --abbrev=0 "$CURRENT_VERSION^")

echo_info "当前版本: $CURRENT_VERSION"
echo_info "回滚到: $PREVIOUS_VERSION"

# 2. 确认回滚
read -p "确认回滚到 $PREVIOUS_VERSION? (y/N) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo_warn "回滚取消"
    exit 0
fi

if docker compose version &> /dev/null; then
    COMPOSE="docker compose"
elif command -v docker-compose &> /dev/null; then
    COMPOSE="docker-compose"
else
    echo_error "Docker Compose 未安装"
    exit 1
fi

# 3. 停止当前应用容器
echo_info "停止当前容器..."
$COMPOSE -f docker-compose.prod.yml down

# 4. 切换到上一个版本并拉起数据库
echo_info "切换代码版本..."
git checkout "$PREVIOUS_VERSION"

# 5. 恢复最新备份（兼容 scripts/backup.sh 产出的 PostgreSQL dump 与 SQLite 归档）
echo_info "恢复数据库备份..."
LATEST_BACKUP=$(ls -t backups/airdrop-alpha-backup-*.tar.gz 2>/dev/null | head -1 || true)

if [ -n "$LATEST_BACKUP" ]; then
    echo_info "使用备份: $LATEST_BACKUP"
    TMP_RESTORE=$(mktemp -d)
    tar -xzf "$LATEST_BACKUP" -C "$TMP_RESTORE"
    PG_DUMP_FILE=$(find "$TMP_RESTORE" -name "airdrop_pg.dump" | head -1 || true)
    SQLITE_FILE=$(find "$TMP_RESTORE" -name "app.db" | head -1 || true)
    if [ -n "$PG_DUMP_FILE" ]; then
        $COMPOSE -f docker-compose.prod.yml up -d db
        sleep 5
        docker cp "$PG_DUMP_FILE" airdrop-db:/tmp/restore.dump
        docker exec airdrop-db pg_restore -U airdrop -d airdrop --clean --if-exists --no-owner /tmp/restore.dump
        docker exec airdrop-db rm -f /tmp/restore.dump
        echo_info "✅ PostgreSQL 数据库已恢复"
    elif [ -n "$SQLITE_FILE" ]; then
        mkdir -p data
        cp "$SQLITE_FILE" data/airdrop.db
        echo_info "✅ SQLite 数据库已恢复"
    else
        echo_warn "备份压缩包中未检测到数据库文件，跳过数据库恢复"
    fi
    rm -rf "$TMP_RESTORE"
else
    echo_warn "未找到 backups/airdrop-alpha-backup-*.tar.gz，仅回滚代码与镜像"
fi

# 6. 重新构建并启动容器
echo_info "重新构建并启动容器..."
$COMPOSE -f docker-compose.prod.yml up -d --build

# 7. 健康检查（生产入口 18080）
echo_info "健康检查..."
sleep 5

HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:18080/health || echo "000")

if [ "$HTTP_CODE" = "200" ]; then
    echo_info "✅ 回滚成功: $PREVIOUS_VERSION"
else
    echo_error "❌ 回滚后健康检查失败 (HTTP $HTTP_CODE)"
    exit 1
fi

# 8. 记录回滚
mkdir -p logs
cat >> logs/deployments.log << EOF
---
时间: $(date '+%Y-%m-%d %H:%M:%S')
操作: ROLLBACK
从版本: $CURRENT_VERSION
到版本: $PREVIOUS_VERSION
执行人: $(whoami)
状态: SUCCESS
---
EOF

echo_info "✅ 回滚完成"
