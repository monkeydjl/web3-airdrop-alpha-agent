#!/usr/bin/env bash
# scripts/deploy/production.sh
# 生产环境部署脚本

set -e

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

echo_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

echo_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 1. 参数检查
VERSION=$1

if [ -z "$VERSION" ]; then
    echo_error "请提供版本号"
    echo "用法: $0 <version>"
    exit 1
fi

echo_info "开始部署版本: $VERSION"

# 2. 环境检查
echo_info "检查部署环境..."

if [ ! -f ".env.production" ]; then
    echo_error "缺少 .env.production 文件"
    exit 1
fi

if ! command -v docker &> /dev/null; then
    echo_error "Docker 未安装"
    exit 1
fi

if ! command -v docker-compose &> /dev/null; then
    echo_error "Docker Compose 未安装"
    exit 1
fi

# 3. 备份当前数据库
echo_info "备份数据库..."
if [ -f "./scripts/workflows/db-backup.sh" ]; then
    ./scripts/workflows/db-backup.sh
else
    echo_warn "备份脚本不存在，跳过（建议手动备份）"
fi

# 4. 拉取最新代码
echo_info "拉取代码..."
git fetch origin
git checkout "v$VERSION"

# 5. 构建 Docker 镜像
echo_info "构建 Docker 镜像..."
docker build -t airdrop-backend:$VERSION -f docker/Dockerfile .

# 6. 停止旧容器
echo_info "停止旧容器..."
docker-compose -f docker-compose.prod.yml down

# 7. 数据库迁移（如有）
echo_info "运行数据库迁移..."
# TODO: 实际迁移逻辑
# docker run --rm -v $(pwd)/data:/data airdrop-backend:$VERSION python scripts/migrate.py

# 8. 启动新容器
echo_info "启动新容器..."
docker-compose -f docker-compose.prod.yml up -d

# 9. 健康检查
echo_info "健康检查..."
MAX_RETRIES=30
RETRY_COUNT=0

while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8002/health || echo "000")

    if [ "$HTTP_CODE" = "200" ]; then
        echo_info "✅ 健康检查通过"
        break
    fi

    echo_warn "等待服务启动... ($RETRY_COUNT/$MAX_RETRIES)"
    RETRY_COUNT=$((RETRY_COUNT + 1))
    sleep 2
done

if [ $RETRY_COUNT -ge $MAX_RETRIES ]; then
    echo_error "健康检查失败，开始回滚..."
    ./scripts/deploy/rollback.sh
    exit 1
fi

# 10. 烟雾测试
echo_info "运行烟雾测试..."
curl -f "http://localhost:8002/api/v1/projects?limit=1" -H "X-API-Key: ${API_KEY}" || {
    echo_error "烟雾测试失败，开始回滚..."
    ./scripts/deploy/rollback.sh
    exit 1
}

# 11. 清理旧镜像
echo_info "清理旧镜像..."
docker image prune -f

# 12. 记录部署
echo_info "记录部署信息..."
cat >> logs/deployments.log << EOF
---
时间: $(date '+%Y-%m-%d %H:%M:%S')
版本: $VERSION
部署人: $(whoami)
Git Commit: $(git rev-parse HEAD)
状态: SUCCESS
---
EOF

echo_info "✅ 部署完成: v$VERSION"
echo_info "服务地址: http://localhost:80 (nginx)"
echo_info "后端 API: http://localhost:8002"
