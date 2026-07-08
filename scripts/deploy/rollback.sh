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

# 3. 停止当前容器
echo_info "停止当前容器..."
docker-compose -f docker-compose.prod.yml down

# 4. 恢复数据库备份
echo_info "恢复数据库备份..."
LATEST_BACKUP=$(ls -t backups/*/airdrop_*.db.gz | head -1)

if [ -z "$LATEST_BACKUP" ]; then
    echo_error "未找到数据库备份"
    exit 1
fi

echo_info "使用备份: $LATEST_BACKUP"
gunzip -c "$LATEST_BACKUP" > data/airdrop.db

# 5. 切换到上一个版本
echo_info "切换代码版本..."
git checkout "$PREVIOUS_VERSION"

# 6. 重新构建镜像
echo_info "重新构建镜像..."
docker build -t airdrop-backend:$PREVIOUS_VERSION -f docker/Dockerfile .

# 7. 启动容器
echo_info "启动容器..."
docker-compose -f docker-compose.prod.yml up -d

# 8. 健康检查
echo_info "健康检查..."
sleep 5

HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/health || echo "000")

if [ "$HTTP_CODE" = "200" ]; then
    echo_info "✅ 回滚成功: $PREVIOUS_VERSION"
else
    echo_error "❌ 回滚后健康检查失败"
    exit 1
fi

# 9. 记录回滚
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
