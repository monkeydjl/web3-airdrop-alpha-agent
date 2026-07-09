"""FastAPI Application Entry Point.

Web3 Airdrop Alpha Agent System 主应用入口。
启动时初始化数据库、注册路由、配置中间件。

使用方式：
    开发：uvicorn app.main:app --reload
    生产：uvicorn app.main:app --host 0.0.0.0 --port 8000

参考：
- ENGINEERING_ROADMAP.md §8 API 设计
- API_SPEC.md 完整 API 契约
"""

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.db import init_db

logger = structlog.get_logger(__name__)


def create_app(db_override=None) -> FastAPI:
    """应用工厂函数。

    创建并配置 FastAPI 应用实例。
    支持 db_override 参数用于测试注入。

    Args:
        db_override: 测试时注入的数据库连接

    Returns:
        配置好的 FastAPI 实例
    """
    app = FastAPI(
        title="Web3 Airdrop Alpha Agent System",
        description="多智能体驱动的 Web3 早期项目识别与空投参与决策系统",
        version=settings.app_version,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # ── 中间件 ──────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=settings.cors_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── 请求日志中间件 ──────────────────────────
    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        """记录请求日志（结构化）。"""
        import time
        start = time.time()
        response = await call_next(request)
        duration = (time.time() - start) * 1000

        logger.info(
            "api.request.completed",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=round(duration, 2),
        )
        return response

    # ── 全局异常处理 ────────────────────────────
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        """统一异常处理，返回标准错误格式。"""
        logger.error(
            "api.unhandled_exception",
            path=request.url.path,
            error=str(exc),
            exc_info=True,
        )
        return JSONResponse(
            status_code=500,
            content={
                "ok": False,
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": "Internal server error",
                },
            },
        )

    # ── 健康检查 ────────────────────────────────
    @app.get(settings.health_check_path, tags=["system"])
    async def health_check():
        """健康检查端点。"""
        return {"ok": True, "status": "healthy", "version": settings.app_version}

    # ── 版本信息 ────────────────────────────────
    @app.get("/version", tags=["system"])
    async def version():
        """获取应用版本信息。"""
        return {
            "ok": True,
            "data": {
                "version": settings.app_version,
                "app_env": settings.app_env,
                "llm_enabled": settings.is_llm_enabled,
            },
        }

    # ── 注册路由 ────────────────────────────────
    from app.routers.v1 import run
    app.include_router(run.router, prefix="/api/v1", tags=["v1"])

    # ── 启动事件 ────────────────────────────────
    @app.on_event("startup")
    async def startup_event():
        """应用启动时执行初始化。"""
        logger.info(
            "app.startup",
            version=settings.app_version,
            env=settings.app_env,
            llm_enabled=settings.is_llm_enabled,
        )
        if db_override is None:
            init_db()

    @app.on_event("shutdown")
    async def shutdown_event():
        """应用关闭时执行清理。"""
        logger.info("app.shutdown")

    return app


# ── 应用实例 ────────────────────────────────────
app = create_app()


def main():
    """CLI 入口。"""
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
