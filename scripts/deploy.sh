#!/bin/bash

# ══════════════════════════════════════════════════════════════
# Web3 Airdrop Alpha - 部署脚本
# ══════════════════════════════════════════════════════════════
#
# 用途: 一键部署系统（开发或生产环境）
# 使用: ./scripts/deploy.sh [dev|prod]
#
# ── 2026-08-24 修复记录 ────────────────────────────────────────
#
# 这个脚本此前**在生产路径上必然失败**，而且失败信息指向错误的方向：
#
# 1. 健康检查打的是 8000 端口，真实端口是 8002。照原样跑会在健康检查
#    环节卡满 30 次重试（约 65 秒）后报「服务启动超时」——
#    而服务其实已经起来了，只是没人在 8000 上听。
#    **一个把"探测地址错了"报成"服务起不来"的脚本，会让人去查容器日志、
#    查依赖、查数据库，而问题在脚本自己这一行。**
#
# 2. 原来那 5 行 sed 全是空操作，形如：
#        sed -i.bak 's/APP_ENV=production/APP_ENV=production/' .env
#    把 X 替换成 X。其中开发分支那条 `s/APP_ENV=production/APP_ENV=development/`
#    也匹配不上 —— `.env.example` 里写的本来就是 `APP_ENV=development`。
#    同理 `s/LOG_LEVEL=info/…/` 匹配不上大写的 `LOG_LEVEL=INFO`。
#    **五行 sed，零个生效，而且每行都 exit 0**，所以看不出任何异常。
#
# 3. 生产路径最严重的一条：从 `.env.example` 复制出来的 `.env` 里
#    `API_KEY=` 和 `AUTH_TOKEN_SECRET=` 都是空的，而 `app/config.py`
#    的生产自检要求 API_KEY 非空且 ≥ 32 字符、AUTH_TOKEN_SECRET 非空，
#    否则**拒绝启动**。于是脚本会打印「✅ .env 文件已创建」，
#    然后容器 CrashLoop，60 秒后报「服务启动超时」。
#    密钥的正确值只有部署者知道，脚本不能也不该自动生成一个假的 ——
#    所以改成**立刻停下并说清要填什么**，而不是让它跑到超时。
#
# 一句话：这个脚本原来的三个问题都不是"功能缺失"，而是**把真实原因
# 掩盖成另一个原因**。这类错误最贵的地方不是它失败，而是它指错方向。
#
# ══════════════════════════════════════════════════════════════

set -e

# 配置
ENVIRONMENT="${1:-dev}"
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# 端口从 .env 读（PORT），读不到用真实默认值 8002。
# 硬编码一个端口就是上面第 1 条问题的来源，所以这里不写死。
DEFAULT_PORT=8002

echo "🚀 开始部署 Web3 Airdrop Alpha Agent System"
echo "环境: $ENVIRONMENT"
echo "目录: $PROJECT_ROOT"
echo ""

cd "$PROJECT_ROOT"

if [ "$ENVIRONMENT" != "dev" ] && [ "$ENVIRONMENT" != "prod" ]; then
    echo "❌ 错误: 未知环境 '$ENVIRONMENT'"
    echo "用法: ./scripts/deploy.sh [dev|prod]"
    exit 1
fi

# 检查 Docker
if ! command -v docker &> /dev/null; then
    echo "❌ 错误: Docker 未安装"
    echo "请访问 https://docs.docker.com/get-docker/ 安装 Docker"
    exit 1
fi

# 统一 compose 调用方式：v2 是 `docker compose`，v1 是 `docker-compose`。
# 原脚本检测了两种，但后面全部只调 `docker-compose` —— 在只装了 v2 的
# 机器上检测能过、执行会 command not found。
if docker compose version &> /dev/null; then
    COMPOSE="docker compose"
elif command -v docker-compose &> /dev/null; then
    COMPOSE="docker-compose"
else
    echo "❌ 错误: Docker Compose 未安装"
    exit 1
fi
echo "ℹ️  使用: $COMPOSE"
echo ""

# 检查 .env 文件
if [ ! -f .env ]; then
    echo "⚠️  未找到 .env 文件，从模板创建..."
    cp .env.example .env
    echo "✅ 已从 .env.example 创建 .env"

    if [ "$ENVIRONMENT" = "prod" ]; then
        echo ""
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        echo "⛔ 停止：生产部署不能用模板里的默认值直接启动"
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        echo ""
        echo "刚创建的 .env 里以下几项必须先填好，否则容器会拒绝启动"
        echo "（app/config.py 的生产自检，不是警告，是直接退出）:"
        echo ""
        echo "  APP_ENV=production        # 模板里是 development"
        echo "  API_KEY=<≥32 字符随机串>   # 模板里为空 = 无鉴权"
        echo "  AUTH_TOKEN_SECRET=<随机串> # 模板里为空 = 拒绝启动"
        echo "  CORS_ORIGINS=<真实前端域名> # 模板里是 localhost，生产会拒绝启动"
        echo ""
        echo "生成密钥:"
        echo "  python -c \"import secrets; print(secrets.token_urlsafe(48))\""
        echo ""
        echo "填好后重新执行: ./scripts/deploy.sh prod"
        echo ""
        echo "为什么不自动生成：密钥和域名的正确值只有部署者知道。"
        echo "自动塞一个值进去，会让一个配错的生产环境看起来部署成功了。"
        exit 1
    fi

    # 开发环境：模板默认值（APP_ENV=development / LOG_LEVEL=INFO）本身就能跑，
    # 不需要任何改写。原脚本在这里做的 sed 全是空操作。
    echo "ℹ️  开发环境直接使用模板默认值（APP_ENV=development）"
    echo ""
fi

# 读取真实端口（.env 里的 PORT），供健康检查使用
PORT="$(grep -E '^PORT=' .env 2>/dev/null | tail -1 | cut -d= -f2 | tr -d '[:space:]')"
PORT="${PORT:-$DEFAULT_PORT}"
API_PORT="$(grep -E '^API_PORT=' .env 2>/dev/null | tail -1 | cut -d= -f2 | tr -d '[:space:]')"
# compose 的端口映射是 "${API_PORT:-8002}:8002"，宿主侧端口是 API_PORT
HOST_PORT="${API_PORT:-$PORT}"
echo "ℹ️  容器内端口 $PORT，宿主访问端口 $HOST_PORT"
echo ""

# 生产环境：即使 .env 已存在，也核对那几个会导致拒绝启动的项
if [ "$ENVIRONMENT" = "prod" ]; then
    echo "🔎 生产配置预检（这些项配错会让容器直接退出，提前查比等超时快）..."
    PRECHECK_FAILED=0

    ENV_APP_ENV="$(grep -E '^APP_ENV=' .env | tail -1 | cut -d= -f2 | tr -d '[:space:]')"
    if [ "$ENV_APP_ENV" != "production" ]; then
        echo "   ❌ APP_ENV=$ENV_APP_ENV（生产应为 production）"
        PRECHECK_FAILED=1
    fi

    # 只看长度，不打印值。密钥不进日志。
    ENV_API_KEY_LEN="$(grep -E '^API_KEY=' .env | tail -1 | cut -d= -f2- | tr -d '[:space:]' | wc -c)"
    ENV_API_KEY_LEN=$((ENV_API_KEY_LEN - 1))
    if [ "$ENV_API_KEY_LEN" -lt 32 ]; then
        echo "   ❌ API_KEY 长度 $ENV_API_KEY_LEN（生产要求 ≥ 32）"
        PRECHECK_FAILED=1
    fi

    ENV_SECRET_LEN="$(grep -E '^AUTH_TOKEN_SECRET=' .env | tail -1 | cut -d= -f2- | tr -d '[:space:]' | wc -c)"
    ENV_SECRET_LEN=$((ENV_SECRET_LEN - 1))
    if [ "$ENV_SECRET_LEN" -lt 1 ]; then
        echo "   ❌ AUTH_TOKEN_SECRET 为空（生产会拒绝启动）"
        PRECHECK_FAILED=1
    fi

    ENV_CORS="$(grep -E '^CORS_ORIGINS=' .env | tail -1 | cut -d= -f2-)"
    case "$ENV_CORS" in
        *localhost*|*127.0.0.1*)
            echo "   ❌ CORS_ORIGINS 仍含 localhost/127.0.0.1（生产会拒绝启动）"
            PRECHECK_FAILED=1
            ;;
    esac

    if [ "$PRECHECK_FAILED" -eq 1 ]; then
        echo ""
        echo "⛔ 预检未通过，已在启动前停下。"
        echo "   这些项都会让 app/config.py 拒绝启动 —— 直接跑下去的表现是"
        echo "   容器 CrashLoop、脚本 60 秒后报「服务启动超时」，"
        echo "   而真实原因是配置，不是启动慢。"
        exit 1
    fi
    echo "   ✅ 生产配置预检通过"
    echo ""
fi

# 创建必要目录
echo "📁 创建数据目录..."
mkdir -p data logs backups
echo "✅ 目录创建完成"
echo ""

# 停止现有容器
echo "🛑 停止现有容器..."
$COMPOSE down 2>/dev/null || true
echo "✅ 现有容器已停止"
echo ""

# 构建镜像
echo "🔨 构建 Docker 镜像..."
if [ "$ENVIRONMENT" = "prod" ]; then
    $COMPOSE build --no-cache
else
    $COMPOSE build
fi
echo "✅ 镜像构建完成"
echo ""

# 启动服务
echo "▶️  启动服务..."
if [ "$ENVIRONMENT" = "prod" ]; then
    # 生产环境：启动 Nginx（nginx 服务在 production profile 下）
    $COMPOSE --profile production up -d
else
    # 开发环境：仅启动后端
    $COMPOSE up -d
fi
echo "✅ 服务启动完成"
echo ""

# 等待服务就绪
echo "⏳ 等待服务就绪（端口 $HOST_PORT）..."
sleep 5

MAX_RETRIES=30
RETRY_COUNT=0
READY=0

while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    if curl -s -f "http://localhost:$HOST_PORT/health" > /dev/null 2>&1; then
        echo "✅ 服务已就绪"
        READY=1
        break
    fi

    # 容器已经退出时不必再等满 30 次 —— 那不是"启动慢"，是"起不来"。
    # 这两种情况的处置动作完全不同，报成同一个信息会让人查错方向。
    if ! $COMPOSE ps --status running 2>/dev/null | grep -q backend; then
        echo ""
        echo "❌ 后端容器已退出（不是启动慢，是启动失败）"
        echo ""
        echo "最后 50 行日志:"
        $COMPOSE logs --tail=50 backend || true
        exit 1
    fi

    RETRY_COUNT=$((RETRY_COUNT + 1))
    echo "   等待中... ($RETRY_COUNT/$MAX_RETRIES)"
    sleep 2
done

if [ $READY -eq 0 ]; then
    echo "❌ 服务在 $((MAX_RETRIES * 2 + 5)) 秒内未就绪"
    echo "   探测地址: http://localhost:$HOST_PORT/health"
    echo ""
    echo "查看日志:"
    $COMPOSE logs --tail=50 backend
    exit 1
fi

echo ""

# 显示部署信息
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ 部署成功！"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "🔗 服务地址:"
echo "   API: http://localhost:$HOST_PORT"
echo "   文档: http://localhost:$HOST_PORT/docs"
echo "   健康检查: http://localhost:$HOST_PORT/health"

if [ "$ENVIRONMENT" = "prod" ]; then
    echo "   Nginx: http://localhost:${NGINX_PORT:-80}"
fi

echo ""
echo "📋 常用命令:"
echo "   查看日志: $COMPOSE logs -f backend"
echo "   查看状态: $COMPOSE ps"
echo "   停止服务: $COMPOSE down"
echo "   健康检查: API_URL=http://localhost:$HOST_PORT ./scripts/health-check.sh"
echo "   备份数据: ./scripts/backup.sh"
echo ""
echo "📖 完整文档: docs/DEPLOYMENT.md"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

exit 0
