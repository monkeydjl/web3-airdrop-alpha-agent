# ──────────────────────────────────────────────
# Frontend Dockerfile — Next.js 16 + React 19
# ──────────────────────────────────────────────
# 多阶段构建：deps → builder → runner
# ──────────────────────────────────────────────

# Stage 1: 安装依赖
FROM node:22-alpine AS deps
WORKDIR /app
COPY frontend-next/package.json frontend-next/package-lock.json* ./
RUN npm ci --omit=dev

# Stage 2: 构建
FROM node:22-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY frontend-next/ .

# 构建时不需要 API_PROXY_TARGET（rewrites 在生产中由 nginx 处理）
ENV NEXT_TELEMETRY_DISABLED=1
ENV NODE_ENV=production

RUN npm run build

# Stage 3: 生产运行
FROM node:22-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1

RUN addgroup --system --gid 1001 nodejs
RUN adduser --system --uid 1001 nextjs

# 复制 standalone 输出（Next.js 16 默认支持）
COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs

EXPOSE 3002

ENV PORT=3002
ENV HOSTNAME="0.0.0.0"

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD wget --no-verbose --tries=1 --spider http://localhost:3002/ || exit 1

CMD ["node", "server.js"]
