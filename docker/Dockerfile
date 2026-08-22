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
#
# ⚠ 为什么这里要 apt-get upgrade：
#   Trivy 在 2026-08-22 报出 36 个 HIGH，其中 34 个来自基础镜像自带的
#   util-linux 2.41-5 家族（bsdutils / libblkid1 / liblastlog2-2 / libmount1 /
#   libsmartcols1 / libuuid1 / login / mount / util-linux），4 个 CVE 各命中
#   9 个包：CVE-2026-53612/53613/53614（mount 的 TOCTOU 与 nosuid 绕过）、
#   CVE-2026-53615（libblkid 整数溢出）。Debian 已发布 2.41.5-0+deb13u1。
#   这些包不是我们声明的依赖，requirements.txt 里没有它们 ——
#   `python:3.12-slim` 的 tag 不会随安全更新重新指向新镜像层，所以必须在构建
#   时显式升级，否则每次构建都继承同一批已知漏洞。
RUN apt-get update && \
    apt-get upgrade -y --no-install-recommends && \
    apt-get install -y --no-install-recommends \
        curl \
        libpq5 \
    && rm -rf /var/lib/apt/lists/* && \
    useradd --create-home --shell /bin/bash --uid 1000 appuser

# 基础镜像自带的 Python 打包工具链也有 HIGH（剩下 2 个）：
#   setuptools 70.3.0 → CVE-2025-47273（PackageIndex 路径穿越，修复版 78.1.1）
#   msgpack 1.1.2     → GHSA-6v7p-g79w-8964（pip 内嵌的 CacheControl 依赖，
#                       Unpacker 复用后越界读，修复版 1.2.1）
# 同样不是我们的依赖：本地 venv 里已是 setuptools 83.0.0 / msgpack 1.2.1。
# 运行时并不需要 setuptools 或 pip（应用跑的是 /venv 里的 uvicorn），但直接
# 删掉会让镜像难以排障，因此选择升级而非移除。
RUN pip install --no-cache-dir --upgrade pip setuptools

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
