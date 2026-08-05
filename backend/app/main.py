"""FastAPI Application Entry Point.

Web3 Airdrop Alpha Agent System 主应用入口。
启动时初始化数据库、注册路由、配置中间件。

使用方式：
    开发：uvicorn app.main:app --reload
    本地/生产：uvicorn app.main:app --host 0.0.0.0 --port 8002

参考：
- ENGINEERING_ROADMAP.md §8 API 设计
- API_SPEC.md 完整 API 契约
"""

from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from app.analysis_scheduler import AnalysisScheduler
from app.collectors.base import CollectorResult
from app.collectors.factory import get_default_registry
from app.collectors.persistence import CollectionRepository
from app.collectors.scheduler import CollectionScheduler
from app.config import settings
from app.db import init_db
from app.inflight import QueueDrainInProgressError
from app.metrics import MetricsExporter
from app.pipeline_run import execute_analysis_pipeline
from app.utils.redact import configure_logging

# 进程启动即安装脱敏 processor（SECURITY.md §3.3）。放在模块层而非 lifespan：
# 采集器与脚本可能在应用启动前就开始打日志。
configure_logging()

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

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        """Initialize and release application-owned resources."""
        logger.info(
            "app.startup",
            version=settings.app_version,
            env=settings.app_env,
            llm_enabled=settings.is_llm_enabled,
            collection_scheduler_enabled=settings.collection_scheduler_enabled,
        )
        if db_override is None:
            init_db()

        if settings.app_env != "testing":
            # 与 API 路由共用同一批采集器实例，令牌桶限流才不会被逐请求重置
            registry = get_default_registry()

            repo = CollectionRepository()

            async def on_collection(source_id: str, result: CollectorResult) -> None:
                repo.persist_collection_result(
                    result,
                    source_type="api",
                    source_name=source_id,
                )
                if settings.collection_auto_run_enabled and result.status in (
                    "success",
                    "partial",
                ):
                    try:
                        await execute_analysis_pipeline(trigger="collection_auto")
                    except QueueDrainInProgressError:
                        # 10 个采集源各有独立 job，两个源同时完成会各自触发一次
                        # 排空。跳过不是故障：本批项目仍是 processed=0，在飞的
                        # 那次运行或下一次 cron 自会取到。
                        logger.info(
                            "app.collection_auto_run_skipped",
                            source_id=source_id,
                            reason="queue_drain_in_progress",
                        )
                    except Exception as exc:
                        logger.error(
                            "app.collection_auto_run_failed",
                            source_id=source_id,
                            error=str(exc),
                        )

            collection_scheduler = CollectionScheduler(
                registry,
                on_collection=on_collection,
            )
            collection_scheduler.start()
            try:
                analysis_scheduler = AnalysisScheduler()
                analysis_scheduler.start()
            except Exception:
                # 第二个调度器启动失败时回收已启动的第一个，避免孤儿调度线程
                collection_scheduler.shutdown(wait=False)
                raise

            application.state.collector_registry = registry
            application.state.collection_scheduler = collection_scheduler
            application.state.analysis_scheduler = analysis_scheduler
        else:
            application.state.collector_registry = None
            application.state.collection_scheduler = None
            application.state.analysis_scheduler = None

        try:
            yield
        finally:
            logger.info("app.shutdown")
            for attr in ("collection_scheduler", "analysis_scheduler"):
                scheduler = getattr(application.state, attr, None)
                if scheduler:
                    try:
                        scheduler.shutdown(wait=True)
                    except Exception as exc:
                        logger.error(
                            "app.shutdown.scheduler_error",
                            component=attr,
                            error=str(exc),
                        )

    app = FastAPI(
        title="Web3 Airdrop Alpha Agent System",
        description=(
            "多智能体驱动的 Web3 早期项目识别与空投参与决策系统\n\n"
            "## 核心功能\n\n"
            "- **智能评分**: 4 个 AI Agent 并行分析项目（叙事时机、团队信誉、代币风险、代币经济学）\n"
            "- **三档建议**: FARM（高度推荐）、WATCH（观察）、IGNORE（忽略）\n"
            "- **批量处理**: 一次最多处理 100 个项目\n"
            "- **实时分析**: 基于启发式规则的快速评分（LLM 增强可选）\n\n"
            "## API 版本\n\n"
            "- **v1**: MVP 版本，支持批量评分和项目查询\n"
            "- **v2** (规划中): 数据持久化、历史记录、高级筛选\n\n"
            "## 使用示例\n\n"
            "```bash\n"
            "# 批量评分\n"
            "curl -X POST http://localhost:8002/api/v1/run \\\n"
            "  -H 'Content-Type: application/json' \\\n"
            '  -d \'{"projects": [{"name": "LayerX", "sector": "L2", "has_testnet": true}]}\'\n\n'
            "# 查询项目\n"
            "curl http://localhost:8002/api/v1/projects?label=FARM&sort_by=score\n"
            "```\n"
        ),
        version=settings.app_version,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        openapi_tags=[
            {
                "name": "system",
                "description": "系统健康检查和版本信息",
            },
            {
                "name": "pipeline",
                "description": "评分 Pipeline - 批量运行项目分析和评分",
            },
            {
                "name": "projects",
                "description": "项目查询 - 查询已评分项目列表和详情（V2 实现）",
            },
        ],
        contact={
            "name": "Web3 Airdrop Alpha System",
            "url": "https://github.com/your-org/web3-airdrop-alpha",
        },
        license_info={
            "name": "MIT",
        },
    )

    # ── 中间件 ──────────────────────────────────
    # 注意：Starlette 后注册的中间件在最外层。
    # CORS 必须最后注册（最外层），否则 API key/401 等响应不会携带 CORS 头，
    # 且浏览器预检(OPTIONS)会先被鉴权拦截导致跨域整体失效。

    # API key auth (no-op when API_KEY empty)
    from app.auth import APIKeyMiddleware

    app.add_middleware(APIKeyMiddleware)

    # 限流必须在鉴权**外层**（即后注册），否则爆破 API key 的请求先被鉴权拒绝、
    # 根本走不到限流，配额也就拦不住爆破（SECURITY.md §4.2 / §10.4）
    from app.rate_limit import RateLimitMiddleware

    app.add_middleware(RateLimitMiddleware)

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

    # 通配 origin 时禁用 credentials：CORS 规范禁止 "*" 与凭据同用，
    # Starlette 在该组合下会回显任意 Origin，形成凭据跨站读取风险。
    cors_origins = settings.cors_origins_list
    cors_credentials = settings.cors_credentials and "*" not in cors_origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=cors_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── 初始化数据库 ────────────────────────────
    if db_override is None:
        init_db()  # 幂等建表; lifespan 启动时再次确认迁移完整

    # ── 全局异常处理 ────────────────────────────
    @app.exception_handler(HTTPException)
    async def http_exception_handler(_request: Request, exc: HTTPException):
        """统一 HTTP 异常格式。"""
        detail = exc.detail
        error = (
            detail
            if isinstance(detail, dict)
            else {
                "code": "HTTP_ERROR",
                "message": str(detail),
            }
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={"ok": False, "error": error},
        )

    @app.exception_handler(RequestValidationError)
    async def request_validation_exception_handler(_request: Request, exc: RequestValidationError):
        """统一请求校验异常格式。"""
        return JSONResponse(
            status_code=422,
            content=jsonable_encoder(
                {
                    "ok": False,
                    "error": {
                        "code": "VALIDATION_ERROR",
                        "message": "Request validation failed",
                        "details": exc.errors(),
                    },
                }
            ),
        )

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
    def health_check(response: Response):
        """健康检查端点。

        降级时返回 503：k8s/负载均衡器的探针按**状态码**判活，恒返回 200 会让
        流量继续打进一个连不上数据库的实例。响应体保持不变，仍带 ok/status。
        """
        from app.db import backend_name, get_connection

        db_status = "unknown"
        try:
            conn = get_connection()
            try:
                conn.execute("SELECT 1")
                db_status = "ok"
            finally:
                conn.close()
        except Exception as e:
            db_status = f"error:{type(e).__name__}"
            logger.warning("health.db_check_failed", error=str(e))

        from app.quarantine import quarantine_count

        q_count = 0
        try:
            q_count = quarantine_count()
        except Exception as exc:
            logger.warning("health.quarantine_count_failed", error=str(exc))

        if db_status != "ok":
            response.status_code = 503
        return {
            "ok": db_status == "ok",
            "status": "healthy" if db_status == "ok" else "degraded",
            "version": settings.app_version,
            "db": db_status,
            "db_backend": backend_name(),
            "quarantined_raw": q_count,
            "auth_required": bool((settings.api_key or "").strip()),
            "feedback_enabled": settings.enable_feedback_system,
            "opportunity_model_version": "opportunity-v2.0",
            "opportunity_shadow_enabled": settings.opportunity_shadow_enabled,
            "opportunity_shadow_sample_rate": settings.opportunity_shadow_sample_rate,
        }

    # ── Prometheus metrics ─────────────────────
    @app.get(settings.metrics_path, tags=["system"])
    def metrics():
        """Prometheus metrics endpoint."""
        if not MetricsExporter.is_enabled():
            from fastapi.responses import JSONResponse

            return JSONResponse(
                status_code=404,
                content={"ok": False, "error": {"code": "METRICS_DISABLED", "message": "Metrics are disabled"}},
            )
        return Response(
            content=MetricsExporter.render(),
            media_type=MetricsExporter.content_type(),
        )

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

    # ── 自定义 OpenAPI ──────────────────────────
    from app.openapi import customize_openapi_schema

    def custom_openapi():
        return customize_openapi_schema(app)

    app.openapi = custom_openapi

    # ── 注册路由 ────────────────────────────────
    from app.routers.v1 import (
        ai_brief,
        collections,
        export_import,
        feedback,
        funding,
        insights,
        interactions,
        opportunity,
        participation,
        projects,
        quarantine,
        run,
    )

    app.include_router(run.router, prefix="/api/v1", tags=["v1"])
    app.include_router(projects.router, prefix="/api/v1", tags=["v1"])
    app.include_router(export_import.router, prefix="/api/v1", tags=["v1"])
    app.include_router(collections.router, prefix="/api/v1", tags=["v1"])
    app.include_router(feedback.router, prefix="/api/v1", tags=["v1"])
    app.include_router(insights.router, prefix="/api/v1", tags=["v1"])
    app.include_router(quarantine.router, prefix="/api/v1", tags=["v1"])
    app.include_router(ai_brief.router, prefix="/api/v1", tags=["v1"])
    app.include_router(interactions.router, prefix="/api/v1", tags=["v1"])
    app.include_router(participation.router, prefix="/api/v1", tags=["v1"])
    app.include_router(funding.router, prefix="/api/v1", tags=["v1"])
    app.include_router(opportunity.router, prefix="/api/v1", tags=["v1"])

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
