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
# （otel-collector + jaeger）时，需在此追加（必须加在下面删 pip 之前）：
#   COPY backend/requirements-otel.txt ./
#   /venv/bin/pip install --no-cache-dir -r requirements-otel.txt
RUN python -m venv /venv && \
    /venv/bin/pip install --no-cache-dir --upgrade pip && \
    /venv/bin/pip install --no-cache-dir -r requirements.txt

# 装完依赖后从 venv 里删掉 pip 与 setuptools。
#
# 为什么必须在这里也删一次：production 阶段 `COPY --from=builder /venv /venv`
# 会把整个 venv 搬过去，而 venv 里的 pip 与基础镜像的 pip 是同一份代码 ——
# 都带着 `pip/_vendor/vendor.txt`（内钉 msgpack==1.1.2 / setuptools==70.3.0）。
# Trivy 扫到的就是这份清单（它在报告里列出了
# `venv/lib/python3.12/site-packages/pip-26.2.1.dist-info/METADATA`）。
# 只删 production 阶段那份、留下 venv 这份，2 个 HIGH 一个也不会少。
#
# 依赖此时已全部装好，运行期不再需要 pip。
RUN rm -rf /venv/lib/python3.12/site-packages/pip \
           /venv/lib/python3.12/site-packages/pip-*.dist-info \
           /venv/lib/python3.12/site-packages/setuptools \
           /venv/lib/python3.12/site-packages/setuptools-*.dist-info \
           /venv/lib/python3.12/site-packages/pkg_resources \
           /venv/lib/python3.12/site-packages/_distutils_hack \
           /venv/lib/python3.12/site-packages/distutils-precedence.pth \
           /venv/bin/pip /venv/bin/pip3 /venv/bin/pip3.12

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

# 基础镜像自带的 pip 是剩下 2 个 HIGH 的来源，且**升级 pip 修不掉**：
#   setuptools 70.3.0 → CVE-2025-47273（PackageIndex 路径穿越）
#   msgpack 1.1.2     → GHSA-6v7p-g79w-8964（Unpacker 复用后越界读）
#
# 为什么升级无效（已实测）：这两个版本号来自 pip 自带的
# `pip/_vendor/vendor.txt`，pip 把依赖以源码形式内嵌在 `pip/_vendor/` 下，
# 不产生 dist-info。本机 pip 已是最新的 26.2.1，它的 vendor.txt 里**仍然**
# 钉着 `msgpack==1.1.2` / `setuptools==70.3.0` —— 与 Trivy 报的版本逐字一致。
# 上一版 Dockerfile 加的 `pip install --upgrade setuptools` 把独立安装的
# setuptools 升到了 84.0.0（Trivy 也确认那份 0 漏洞），可 vendor.txt 不受影响，
# 所以 2 个 HIGH 一个没少。这也解释了 Trivy 那句
# "Third-party SBOM may lead to inaccurate vulnerability detection"：
# 它读的是 vendor.txt 这份清单，而不是真实安装的包。
#
# 因此改为**从运行镜像里删掉 pip 与 setuptools**。运行时确实不需要它们：
# 应用跑的是 /venv 里的 uvicorn，依赖已在 builder 阶段装好。已实测验证 ——
# 用 meta_path 拦截器让 pip / setuptools / pkg_resources / _distutils_hack
# 全部不可导入，应用仍完整启动（28 条路由）、/health 返回 200 healthy，
# pandas / numpy / psycopg / alembic / apscheduler 均正常。
# numpy 里唯一的 `from setuptools import ...` 位于 numpy/distutils（构建期
# 代码），实测应用完整导入后 numpy.distutils 从未被加载。
#
# 代价：镜像内无法再 pip install 排障。要临时装包就进 builder 阶段，
# 或 `docker run --rm -it python:3.12-slim` 另起一个容器。
RUN pip uninstall -y pip setuptools 2>/dev/null || true; \
    rm -rf /usr/local/lib/python3.12/site-packages/pip \
           /usr/local/lib/python3.12/site-packages/pip-*.dist-info \
           /usr/local/lib/python3.12/site-packages/setuptools \
           /usr/local/lib/python3.12/site-packages/setuptools-*.dist-info \
           /usr/local/lib/python3.12/site-packages/pkg_resources \
           /usr/local/lib/python3.12/site-packages/_distutils_hack \
           /usr/local/lib/python3.12/site-packages/distutils-precedence.pth \
           /usr/local/lib/python3.12/ensurepip \
           /usr/local/bin/pip /usr/local/bin/pip3 /usr/local/bin/pip3.12

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
