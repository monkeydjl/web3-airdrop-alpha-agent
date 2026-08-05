"""Optional API key authentication middleware.

When settings.api_key is empty, all requests are allowed (MVP).
When set, require header X-API-Key or Authorization: Bearer <key>.
"""

from __future__ import annotations

import hmac

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.config import settings

# Paths that stay open even with API key enabled
PUBLIC_PREFIXES = (
    "/health",
    "/metrics",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/version",
)


class APIKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        expected = (settings.api_key or "").strip()
        if not expected:
            return await call_next(request)

        # CORS 预检请求不携带自定义头，必须放行交给 CORSMiddleware 处理
        if request.method == "OPTIONS":
            return await call_next(request)

        path = request.url.path
        if any(path == p or path.startswith(p + "/") for p in PUBLIC_PREFIXES):
            return await call_next(request)

        provided = request.headers.get("X-API-Key") or ""
        if not provided:
            auth = request.headers.get("Authorization") or ""
            if auth.lower().startswith("bearer "):
                provided = auth[7:].strip()

        # 常量时间比较，避免逐字节短路的时序侧信道
        if not hmac.compare_digest(provided.encode(), expected.encode()):
            return JSONResponse(
                status_code=401,
                content={
                    "ok": False,
                    "error": {
                        "code": "UNAUTHORIZED",
                        "message": "Missing or invalid API key",
                    },
                },
            )
        return await call_next(request)
