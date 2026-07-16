# Docker 多阶段构建 - 优化镜像大小
# Python 3.14 base image
FROM python:3.14-slim as base

# 设置工作目录
WORKDIR /app

# 安装系统依赖（SQLite 支持）
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# ── 构建阶段 ──────────────────────────────────
FROM base as builder

# 安装构建依赖
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件
COPY backend/pyproject.toml backend/README.md ./

# 安装 Python 依赖到临时目录
RUN pip install --user --no-cache-dir -e .

# ── 运行阶段 ──────────────────────────────────
FROM base

# 创建非 root 用户
RUN useradd -m -u 1000 appuser && \
    mkdir -p /app/data /app/logs && \
    chown -R appuser:appuser /app

# 从构建阶段复制依赖
COPY --from=builder /root/.local /home/appuser/.local

# 复制应用代码
COPY backend/app /app/app

# 切换到非 root 用户
USER appuser

# 设置 Python 路径
ENV PATH=/home/appuser/.local/bin:$PATH \
    PYTHONPATH=/app \
    PYTHONUNBUFFERED=1

# 暴露端口（本项目固定 8002，避免与其他本地项目 8000 冲突）
EXPOSE 8002

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8002/health')"

# 启动命令
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8002"]
