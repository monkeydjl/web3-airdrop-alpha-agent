#!/bin/bash

# ══════════════════════════════════════════════════════════════
# Web3 Airdrop Alpha - 部署脚本
# ══════════════════════════════════════════════════════════════
#
# 用途: 一键部署系统（开发或生产环境）
# 使用: ./scripts/deploy.sh [dev|prod]
#
# ══════════════════════════════════════════════════════════════

set -e

# 配置
ENVIRONMENT="${1:-dev}"
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "🚀 开始部署 Web3 Airdrop Alpha Agent System"
echo "环境: $ENVIRONMENT"
echo "目录: $PROJECT_ROOT"
echo ""

cd "$PROJECT_ROOT"

# 检查 Docker
if ! command -v docker &> /dev/null; then
    echo "❌ 错误: Docker 未安装"
    echo "请访问 https://docs.docker.com/get-docker/ 安装 Docker"
    exit 1
fi

if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
    echo "❌ 错误: Docker Compose 未安装"
    exit 1
fi

# 检查 .env 文件
if [ ! -f .env ]; then
    echo "⚠️  未找到 .env 文件，从模板创建..."
    cp .env.example .env

    if [ "$ENVIRONMENT" = "prod" ]; then
        # 生产环境：修改默认配置
        sed -i.bak 's/APP_ENV=production/APP_ENV=production/' .env
        sed -i.bak 's/LOG_LEVEL=info/LOG_LEVEL=info/' .env
        sed -i.bak 's/SEED_ON_STARTUP=false/SEED_ON_STARTUP=false/' .env
        rm .env.bak
    else
        # 开发环境：修改默认配置
        sed -i.bak 's/APP_ENV=production/APP_ENV=development/' .env
        sed -i.bak 's/LOG_LEVEL=info/LOG_LEVEL=debug/' .env
        rm .env.bak
    fi

    echo "✅ .env 文件已创建"
    echo ""
fi

# 创建必要目录
echo "📁 创建数据目录..."
mkdir -p data logs backups
echo "✅ 目录创建完成"
echo ""

# 停止现有容器
echo "🛑 停止现有容器..."
docker-compose down 2>/dev/null || true
echo "✅ 现有容器已停止"
echo ""

# 构建镜像
echo "🔨 构建 Docker 镜像..."
if [ "$ENVIRONMENT" = "prod" ]; then
    docker-compose build --no-cache
else
    docker-compose build
fi
echo "✅ 镜像构建完成"
echo ""

# 启动服务
echo "▶️  启动服务..."
if [ "$ENVIRONMENT" = "prod" ]; then
    # 生产环境：启动 Nginx
    docker-compose --profile production up -d
else
    # 开发环境：仅启动后端
    docker-compose up -d
fi
echo "✅ 服务启动完成"
echo ""

# 等待服务就绪
echo "⏳ 等待服务就绪..."
sleep 5

MAX_RETRIES=30
RETRY_COUNT=0

while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    if curl -s -f http://localhost:8000/health > /dev/null 2>&1; then
        echo "✅ 服务已就绪"
        break
    fi

    RETRY_COUNT=$((RETRY_COUNT + 1))
    echo "   等待中... ($RETRY_COUNT/$MAX_RETRIES)"
    sleep 2
done

if [ $RETRY_COUNT -eq $MAX_RETRIES ]; then
    echo "❌ 服务启动超时"
    echo ""
    echo "查看日志:"
    docker-compose logs --tail=50 backend
    exit 1
fi

echo ""

# 显示部署信息
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ 部署成功！"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "🔗 服务地址:"
echo "   API: http://localhost:8000"
echo "   文档: http://localhost:8000/docs"
echo "   健康检查: http://localhost:8000/health"

if [ "$ENVIRONMENT" = "prod" ]; then
    echo "   Nginx: http://localhost:80"
fi

echo ""
echo "📋 常用命令:"
echo "   查看日志: docker-compose logs -f backend"
echo "   查看状态: docker-compose ps"
echo "   停止服务: docker-compose down"
echo "   健康检查: ./scripts/health-check.sh"
echo "   备份数据: ./scripts/backup.sh"
echo ""
echo "📖 完整文档: DEPLOYMENT.md"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

exit 0
