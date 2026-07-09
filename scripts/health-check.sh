#!/bin/bash

# ══════════════════════════════════════════════════════════════
# Web3 Airdrop Alpha - 健康检查脚本
# ══════════════════════════════════════════════════════════════
#
# 用途: 检查服务健康状态，可用于监控告警
# 使用: ./scripts/health-check.sh
#
# 退出码:
#   0 - 健康
#   1 - 不健康
#
# ══════════════════════════════════════════════════════════════

set -e

# 配置
API_URL="${API_URL:-http://localhost:8000}"
TIMEOUT="${TIMEOUT:-10}"

echo "🔍 检查服务健康状态..."
echo "API URL: $API_URL"
echo ""

# 检查 API 健康端点
echo "1️⃣  检查 API 健康端点..."
HEALTH_RESPONSE=$(curl -s -f --max-time "$TIMEOUT" "$API_URL/health" || echo "failed")

if [ "$HEALTH_RESPONSE" = "failed" ]; then
    echo "❌ API 健康检查失败"
    exit 1
fi

if echo "$HEALTH_RESPONSE" | grep -q '"ok":true'; then
    echo "✅ API 健康检查通过"
else
    echo "❌ API 返回异常: $HEALTH_RESPONSE"
    exit 1
fi

# 检查版本信息
echo ""
echo "2️⃣  检查版本信息..."
VERSION_RESPONSE=$(curl -s -f --max-time "$TIMEOUT" "$API_URL/version" || echo "failed")

if [ "$VERSION_RESPONSE" = "failed" ]; then
    echo "⚠️  版本端点无响应（非致命）"
else
    echo "✅ 版本信息获取成功"
    echo "$VERSION_RESPONSE" | python3 -m json.tool 2>/dev/null || echo "$VERSION_RESPONSE"
fi

# 检查 Docker 容器（如果在 Docker 环境）
echo ""
echo "3️⃣  检查 Docker 容器状态..."
if command -v docker &> /dev/null; then
    CONTAINER_STATUS=$(docker ps --filter "name=airdrop-alpha-backend" --format "{{.Status}}" 2>/dev/null || echo "not found")

    if [ "$CONTAINER_STATUS" = "not found" ]; then
        echo "ℹ️  未找到 Docker 容器（可能是本地运行）"
    elif echo "$CONTAINER_STATUS" | grep -q "Up"; then
        echo "✅ Docker 容器运行中: $CONTAINER_STATUS"
    else
        echo "❌ Docker 容器状态异常: $CONTAINER_STATUS"
        exit 1
    fi
else
    echo "ℹ️  Docker 未安装或不可用"
fi

# 检查数据库文件（如果是本地 SQLite）
echo ""
echo "4️⃣  检查数据库..."
if [ -f "data/app.db" ]; then
    DB_SIZE=$(du -h data/app.db | cut -f1)
    echo "✅ 数据库文件存在: $DB_SIZE"
elif [ -f "backend/data/app.db" ]; then
    DB_SIZE=$(du -h backend/data/app.db | cut -f1)
    echo "✅ 数据库文件存在: $DB_SIZE"
else
    echo "⚠️  数据库文件未找到（可能首次运行）"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ 所有健康检查通过！"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

exit 0
