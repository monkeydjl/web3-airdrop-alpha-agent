# ──────────────────────────────────────────────
# Frontend Dockerfile — Next.js 16 + React 19
# ──────────────────────────────────────────────
# 多阶段构建：deps → builder → runner
# ──────────────────────────────────────────────

# Stage 1: 安装依赖（含 devDependencies，构建需要 typescript/tailwind）
FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci

# Stage 2: 构建
FROM node:22-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .

# `next.config.js` 的 rewrites 在 **build 时**读取 API_PROXY_TARGET 并写入产物，
# 不是运行时才解析。生产 nginx 现在将 /api 交给 Next（这样 proxy.ts 才能注入
# 分档凭据），所以这里必须是后端容器内网地址；若漏掉，production build 得到
# 空 rewrite，页面请求 /api 会被 Next 当作自身路由处理而 404。
#
# 本 Dockerfile 只给 docker-compose.prod.yml 用，那里后端服务名固定为 web:8002。
# 运行时 compose 也重复传同一个值给 proxy.ts 的匿名 token 换取路径，但两者不能
# 互相替代：一个决定 build 产物的 rewrite，另一个决定运行时 server-side fetch。
ARG API_PROXY_TARGET=http://web:8002
ENV API_PROXY_TARGET=$API_PROXY_TARGET
ENV NEXT_TELEMETRY_DISABLED=1
ENV NODE_ENV=production

# 确保 public 目录存在（Next.js 可能不生成）
RUN mkdir -p public

RUN npx next build --webpack

# Stage 3: 生产运行
FROM node:22-alpine AS runner
WORKDIR /app

# npm 随 node:22-alpine 基础镜像分发，其 vendored 依赖（brace-expansion 等 6 个包）
# 带 10 个 HIGH CVE（2026-11-22 CI 扫描）；基础镜像里的 alpine 系统包（musl/zlib）
# 也会随本地缓存的基础镜像层过时而带上已修复的 CVE。运行时只执行 node server.js，
# npm 不会被调用，但漏洞件留在镜像层里会被扫描器持续点名且是阻塞门禁 ——
# apk upgrade 把系统包升到当前 alpine 仓库的修复版，npm install -g npm@latest
# 直接换掉 vendored 依赖。扫描结果随上游漂移：若新版再引入漏洞件，按扫描报告再升。
RUN apk upgrade --no-cache && npm install -g npm@latest && npm cache clean --force

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
    CMD node -e "fetch('http://localhost:3002/').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"

CMD ["node", "server.js"]
