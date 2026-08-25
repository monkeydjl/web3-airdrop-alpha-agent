#!/bin/bash

# ══════════════════════════════════════════════════════════════
# Web3 Airdrop Alpha - 健康检查脚本
# ══════════════════════════════════════════════════════════════
#
# 用途: 检查服务健康状态，可用于监控告警
# 使用: ./scripts/health-check.sh
#       API_URL=http://localhost:8002 ./scripts/health-check.sh
#
# 退出码:
#   0 - 健康
#   1 - 不健康
#
# ── 2026-08-24 修复记录 ────────────────────────────────────────
#
# 默认 API_URL 原来是 8000，真实端口是 8002。这个脚本的用途是
# **给监控告警用**，所以默认值错了的后果是：一个完全健康的系统
# 被持续报成不健康，而值班的人会去查服务，不会去查探测地址。
#
# 另外原脚本第 4 步查的是 `data/app.db`，而实测运行时真正连的库是
# `.env` 里 DB_PATH 指定的那个（本地默认 `data/airdrop.db`，
# 容器里是 `/app/data/app.db`）。查错文件的表现是「⚠️ 数据库文件未找到」
# ——一句听起来无害的警告，实际说明这个检查项从来没检查过真的那个库。
#
# ══════════════════════════════════════════════════════════════

set -e

# 配置
# 真实端口是 8002（app/config.py 的 PORT 默认值、compose 的端口映射都是它）。
# 如果部署时改了 API_PORT，用环境变量覆盖：API_URL=http://host:port
API_URL="${API_URL:-http://localhost:8002}"
TIMEOUT="${TIMEOUT:-10}"

echo "🔍 检查服务健康状态..."
echo "API URL: $API_URL"
echo ""

# 检查 API 健康端点
echo "1️⃣  检查 API 健康端点..."
HEALTH_RESPONSE=$(curl -s -f --max-time "$TIMEOUT" "$API_URL/health" || echo "failed")

if [ "$HEALTH_RESPONSE" = "failed" ]; then
    echo "❌ API 健康检查失败（$API_URL/health 无响应）"
    echo "   若服务监听在别的端口，用 API_URL=... 覆盖后重试。"
    exit 1
fi

# 实测响应体是紧凑 JSON：{"ok":true,"status":"healthy",...}（无空格），
# 所以下面这个无空格模式是对的。
if echo "$HEALTH_RESPONSE" | grep -q '"ok":true'; then
    echo "✅ API 健康检查通过"
else
    echo "❌ API 返回异常: $HEALTH_RESPONSE"
    exit 1
fi

# /health 的 db 字段：连不上库时它是 "error"，而 ok 会是 false，
# 所以上面那一关已经覆盖。这里额外把降级原因打出来，省一次人工查询。
if echo "$HEALTH_RESPONSE" | grep -q '"status":"degraded"'; then
    echo "⚠️  服务处于 degraded 状态（详见上面响应里的 db 字段）"
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

# 检查 LLM 预算账本（2026-08-24 新增）
#
# 为什么值得单独查一项：预算拦截靠日累计花费判断，而
# **一个坏掉的账本和一个还没花钱的账本，在数字上都是 0**。
# 所以判据不是"花费是不是 0"，而是"ledger_error 有没有值"。
# 这个接口要鉴权，没 token 时跳过而不是报错。
echo ""
echo "3️⃣  检查 LLM 预算账本..."
if [ -n "$API_KEY" ]; then
    LLM_RESPONSE=$(curl -s -f --max-time "$TIMEOUT" \
        -H "X-API-Key: $API_KEY" "$API_URL/api/v1/llm/status" || echo "failed")
    if [ "$LLM_RESPONSE" = "failed" ]; then
        echo "⚠️  LLM 状态端点无响应（非致命）"
    elif echo "$LLM_RESPONSE" | grep -q '"ledger_error":null'; then
        echo "✅ 预算账本可读"
    elif echo "$LLM_RESPONSE" | grep -q '"ledger_error":"'; then
        echo "❌ 预算账本读取失败 —— LLM 调用会被 fail-closed 拦住"
        echo "   响应: $LLM_RESPONSE"
        exit 1
    else
        echo "ℹ️  响应里没有 ledger_error 字段（可能是旧版本后端）"
    fi
else
    echo "ℹ️  未设置 API_KEY 环境变量，跳过（该接口需鉴权）"
fi

# 检查 Docker 容器（如果在 Docker 环境）
echo ""
echo "4️⃣  检查 Docker 容器状态..."
if command -v docker &> /dev/null; then
    # 容器名按 compose 文件：开发 airdrop-alpha-backend（docker-compose.yml），
    # 生产 airdrop-web（docker-compose.prod.yml）。原脚本只查前者，
    # 于是在生产环境永远打印「未找到容器（可能是本地运行）」。
    CONTAINER_STATUS=""
    for name in airdrop-alpha-backend airdrop-web; do
        FOUND=$(docker ps --filter "name=$name" --format "{{.Status}}" 2>/dev/null || true)
        if [ -n "$FOUND" ]; then
            CONTAINER_STATUS="$FOUND"
            echo "   容器: $name"
            break
        fi
    done

    if [ -z "$CONTAINER_STATUS" ]; then
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
echo "5️⃣  检查数据库..."
# 从 .env 读 DB_PATH，而不是猜文件名。
# 原脚本硬查 data/app.db —— 本地实际默认是 data/airdrop.db，
# 于是这一项从来没检查过真的那个库，只是安静地打一句"未找到"。
DB_PATH_ENV=""
if [ -f .env ]; then
    DB_PATH_ENV="$(grep -E '^DB_PATH=' .env | tail -1 | cut -d= -f2- | tr -d '[:space:]')"
fi
DB_CANDIDATES="$DB_PATH_ENV data/airdrop.db backend/data/airdrop.db data/app.db backend/data/app.db"
DB_FOUND=""
for candidate in $DB_CANDIDATES; do
    [ -z "$candidate" ] && continue
    if [ -f "$candidate" ]; then
        DB_FOUND="$candidate"
        break
    fi
done

if [ -n "$DB_FOUND" ]; then
    DB_SIZE=$(du -h "$DB_FOUND" | cut -f1)
    echo "✅ 数据库文件存在: $DB_FOUND ($DB_SIZE)"
    if [ -n "$DB_PATH_ENV" ] && [ "$DB_FOUND" != "$DB_PATH_ENV" ]; then
        echo "⚠️  注意：找到的是回退候选，不是 .env 里的 DB_PATH=$DB_PATH_ENV"
        echo "   服务真正连的是 DB_PATH 那个 —— 别对着一个过期副本做判断。"
    fi
else
    echo "⚠️  数据库文件未找到（可能首次运行，或库在容器内 / PostgreSQL）"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ 所有健康检查通过！"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

exit 0
