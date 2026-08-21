# ──────────────────────────────────────────────
# Web3 Airdrop Alpha Agent System — Dockerfile
# 多阶段构建：builder → production
# ──────────────────────────────────────────────

# ── Stage 1: Builder ────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /app

# 安装编译依赖
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        gcc \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件（锁定版本，见 backend/requirements.txt 头部说明）
COPY backend/requirements.txt ./

# 创建虚拟环境并安装依赖
#
# 只装运行时依赖：requirements-dev.txt（pytest/ruff/mypy）不进镜像。
#
# ⚠ 链路追踪依赖（requirements-otel.txt）也**不在**镜像内。app/tracing.py
# 缺包时降级为 no-op tracer（实测：OTEL_ENABLED=true 且缺包时应用正常启动、
# /health 200，仅打一条 tracing.unavailable 警告），因此不会导致启动失败，
# 但**链路追踪不会生效**。要用 compose 的 observability profile
# （otel-collector + jaeger）时，需在此追加：
#   COPY backend/requirements-otel.txt ./
#   /venv/bin/pip install --no-cache-dir -r requirements-otel.txt
RUN python -m venv /venv && \
    /venv/bin/pip install --no-cache-dir --upgrade pip && \
    /venv/bin/pip install --no-cache-dir -r requirements.txt

# ── Stage 2: Production ─────────────────────
FROM python:3.12-slim AS production

# 安全 + 运行时依赖
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl \
        libpq5 \
    && rm -rf /var/lib/apt/lists/* && \
    useradd --create-home --shell /bin/bash --uid 1000 appuser

WORKDIR /app

# 复制虚拟环境
COPY --from=builder /venv /venv
ENV PATH="/venv/bin:$PATH"

# 复制应用代码
COPY backend/ ./backend/

# 创建数据目录并设置权限
RUN mkdir -p /app/data/cache /app/backups && \
    chown -R appuser:appuser /app

USER appuser

WORKDIR /app/backend

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8002/health || exit 1

EXPOSE 8002

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8002"]
