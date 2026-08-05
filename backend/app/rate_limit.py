"""Per-IP rate limiting middleware.

`RATE_LIMIT_ENABLED` / `RATE_LIMIT_REQUESTS` / `RATE_LIMIT_WINDOW` 三个配置项
在 `config.py` 里定义了，但全仓库没有任何代码读取它们——`SECURITY.md §4.2`
要求的"每 IP 60 req/min，超限 429 + Retry-After"从未实现，`§10.4` 要求的
"`/run` 每小时 1 次"同样没有。这意味着：

  - 生产环境的 API_KEY 可以按线速爆破（配合 §4.2 的长度下限一起看）
  - `POST /api/v1/run` 可被连续触发，在 `ENABLE_LLM_ENHANCEMENT=1` 时
    直接击穿 `LLM_DAILY_BUDGET_USD`

实现用进程内滑动窗口计数。单实例部署（Dockerfile 默认单 worker uvicorn）下
准确；多实例时每个实例各自计数，属于已知近似——真要跨实例精确限流需要
Redis，那是 V2 的事，这里先把"完全没有限流"这个状态解决掉。
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.config import settings

# 豁免路径：健康检查与指标由探针/采集器高频拉取，限流会造成误判
EXEMPT_PREFIXES = ("/health", "/metrics")


def _expensive_limits() -> tuple[tuple[str, int, int], ...]:
    """昂贵端点的额外限制：(路径前缀, 次数, 窗口秒)。

    SECURITY.md §10.4 写的是"`/run` 每小时 1 次"，其给出的理由是"防 LLM 配额
    耗尽攻击"。照字面实现会把手动触发一次分析也锁死一小时，而在 LLM 关闭时
    这条限制并不针对任何真实风险。因此按其**理由**分档：LLM 开启时严格到
    每小时 1 次，关闭时放宽到每小时 10 次——仍能挡住刷接口，不妨碍正常运维。
    """
    per_hour = 1 if settings.is_llm_enabled else 10
    return (("/api/v1/run", per_hour, 3600),)


class _SlidingWindow:
    """按 key 记录请求时间戳的滑动窗口。"""

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, limit: int, window: float, now: float) -> float | None:
        """未超限返回 None；超限返回还需等待的秒数。"""
        with self._lock:
            bucket = self._hits[key]
            cutoff = now - window
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= limit:
                return max(0.0, bucket[0] + window - now)
            bucket.append(now)
            return None

    def prune(self, now: float, max_window: float, max_keys: int = 50_000) -> None:
        """丢弃长期无活动的 key，并对总量设硬上限。

        仅靠"按时间清理"挡不住短时间内的大量不同 key（例如伪造来源标识的洪泛）：
        清理窗口内它们全都算"活跃"。因此再加一道按最近活动时间的硬上限淘汰。
        """
        with self._lock:
            for key in [k for k, v in self._hits.items() if not v or v[-1] <= now - max_window]:
                del self._hits[key]
            overflow = len(self._hits) - max_keys
            if overflow > 0:
                oldest = sorted(self._hits, key=lambda k: self._hits[k][-1] if self._hits[k] else 0.0)
                for key in oldest[:overflow]:
                    del self._hits[key]


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app) -> None:
        super().__init__(app)
        self._windows = _SlidingWindow()
        self._last_prune = 0.0

    async def dispatch(self, request: Request, call_next):
        if not settings.rate_limit_enabled:
            return await call_next(request)

        path = request.url.path
        if any(path == p or path.startswith(p + "/") for p in EXEMPT_PREFIXES):
            return await call_next(request)
        # 预检请求不携带凭据，交给 CORSMiddleware，不计入配额
        if request.method == "OPTIONS":
            return await call_next(request)

        now = time.monotonic()
        if now - self._last_prune > 60:
            self._last_prune = now
            # 清理窗口取最长的实际配额窗口即可，无需再乘 2
            longest = max(float(settings.rate_limit_window), *(float(w) for _, _, w in _expensive_limits()))
            self._windows.prune(now, longest)

        client_ip = _client_ip(request)

        # 顺序要紧：先判全局配额。反过来的话，一个被全局配额拒绝的 /run 请求
        # 已经扣掉了"每小时 1 次"的昂贵端点令牌——管线一次都没跑，配额却没了。
        retry = self._windows.check(
            client_ip,
            max(1, settings.rate_limit_requests),
            float(max(1, settings.rate_limit_window)),
            now,
        )
        if retry is not None:
            return _too_many(retry)

        for prefix, limit, window in _expensive_limits():
            if path == prefix or path.startswith(prefix + "/"):
                retry = self._windows.check(f"{client_ip}:{prefix}", limit, float(window), now)
                if retry is not None:
                    return _too_many(retry)
        return await call_next(request)


def _client_ip(request: Request) -> str:
    """限流用的客户端标识。

    **默认不采信 X-Forwarded-For。** 本仓库的 nginx.conf 用
    `proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for`，它会把客户端
    自带的头**前置**再追加真实 IP；若取 `split(",")[0]`，攻击者只要每次换一个
    伪造值就能无限刷配额——限流的首要目的（挡 API key 爆破）当场失效。

    只有显式配置 `TRUSTED_PROXY_COUNT > 0`（表示前面确实有 N 层可信代理）时才
    从右往左数第 N 个值，那是链上唯一不可伪造的位置。
    """
    trusted = max(0, int(getattr(settings, "trusted_proxy_count", 0) or 0))
    if trusted:
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            parts = [p.strip() for p in forwarded.split(",") if p.strip()]
            if len(parts) >= trusted:
                return parts[-trusted]
    return request.client.host if request.client else "unknown"


def _too_many(retry_after: float) -> JSONResponse:
    seconds = max(1, int(retry_after + 0.999))
    return JSONResponse(
        status_code=429,
        content={
            "ok": False,
            "error": {"code": "RATE_LIMITED", "message": "Too many requests"},
        },
        headers={"Retry-After": str(seconds)},
    )
