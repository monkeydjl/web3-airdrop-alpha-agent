"""Collector Base Classes.

定义所有外部数据源的采集器抽象接口与统一输出模型。
v2.0 方向：从手动输入项目反转为系统自动扫描全网项目。

参考：
- ENGINEERING_ROADMAP.md §6.2 Collector Agent
- DATA_SOURCE_STRATEGY.md §采集器接口
- ADR-012-system-direction-auto-scan.md
"""

from __future__ import annotations

import asyncio
import contextlib
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

import httpx
import structlog

from app.collectors.rate_limiter import TokenBucketRateLimiter
from app.utils.domain_allowlist import assert_url_allowed
from app.utils.normalize import create_dedup_key, generate_deterministic_id
from app.utils.redact import redact

logger = structlog.get_logger(__name__)


async def _enforce_collector_domain_allowlist_hook(request: httpx.Request) -> None:
    """在真正发出网络请求前校验域名是否在白名单中，否则抛出 DomainNotAllowedError。"""
    assert_url_allowed(str(request.url))


@contextlib.asynccontextmanager
async def safe_collector_client(
    *,
    timeout: float | httpx.Timeout | None = 10.0,
    follow_redirects: bool = False,
    **kwargs: Any,
) -> AsyncIterator[httpx.AsyncClient]:
    """供采集器或辅助函数调用的受出站白名单防护的 HTTP 客户端上下文管理器。"""
    hooks = kwargs.pop("event_hooks", None) or {}
    req_hooks = list(hooks.get("request", []))
    if _enforce_collector_domain_allowlist_hook not in req_hooks:
        req_hooks.append(_enforce_collector_domain_allowlist_hook)
    hooks["request"] = req_hooks

    effective_timeout = 10.0 if timeout is None else timeout
    async with httpx.AsyncClient(
        timeout=effective_timeout,
        follow_redirects=follow_redirects,
        event_hooks=hooks,
        **kwargs,
    ) as client:
        yield client


@dataclass
class RawSignal:
    """从外部源采集到的原始信号。"""

    signal_type: str  # tvl / github_activity / twitter_mention / chain_activity / quest
    signal_source: str  # defillama / github / twitter / chain / galxe
    signal_data: dict[str, Any]
    signal_strength: float = 0.0  # 0-1
    captured_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class RawDiscovery:
    """采集器输出的一条原始项目发现记录。"""

    source_id: str  # 如 "defillama"
    raw_id: str  # 源侧唯一 id（或采集器生成的 UUID）
    name: str
    url: str | None
    sector: str | None
    stage: str | None  # testnet / mainnet / ideation
    raw_data: dict[str, Any]  # 原始完整数据
    raw_signals: list[RawSignal] = field(default_factory=list)
    discovery_score: float = 0.0  # 0-1，初筛质量分
    discovered_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def dedup_key(self) -> str:
        """生成去重键。"""
        return create_dedup_key(self.name, self.sector).to_string()

    @property
    def project_id(self) -> str:
        """基于 dedup_key 生成确定性 UUID。"""
        return generate_deterministic_id(create_dedup_key(self.name, self.sector))


class CollectorResult:
    """一次采集任务的结果。"""

    def __init__(
        self,
        source_id: str,
        status: str = "success",
        items: list[RawDiscovery] | None = None,
        error_message: str | None = None,
    ) -> None:
        self.source_id = source_id
        self.status = status  # success / partial / error / rate_limited
        self.items = items or []
        self.error_message = error_message
        self.items_new = 0
        self.items_duplicate = 0
        self.started_at: datetime | None = None
        self.finished_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "status": self.status,
            "items_collected": len(self.items),
            "items_new": self.items_new,
            "items_duplicate": self.items_duplicate,
            "error_message": self.error_message,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }


class DataCollector(ABC):
    """外部数据源采集器抽象基类。

    所有外部采集源（DefiLlama/GitHub/CoinGecko/Twitter）都必须继承此类。

    统一的 HTTP 重试策略由 :meth:`request_with_retry` 提供：各源用自己的
    ``*_RETRY`` 配置设置 ``self.retry``（重试次数，总尝试数 = 1 + retry），
    只重试网络错误 / 429 / 5xx，其余 4xx 立即返回由调用方处理。
    """

    # 统一退避：1s、2s、4s…；429/5xx 带 Retry-After 时取两者较大值，单次等待封顶。
    RETRY_BASE_DELAY: float = 1.0
    RETRY_MAX_DELAY: float = 60.0
    # 子类用各自的 *_RETRY 覆盖；未单独配置的源沿用 3 次。
    retry: int = 3
    timeout: float = 10.0
    rate_limiter: TokenBucketRateLimiter

    def __init__(self, source_id: str, source_name: str) -> None:
        self.source_id = source_id
        self.source_name = source_name
        self.logger = logger.bind(source_id=source_id)

    @property
    @abstractmethod
    def source_type(self) -> str:
        """源类型：api / stream / webhook / manual。"""
        ...

    @abstractmethod
    async def collect(self) -> CollectorResult:
        """执行采集，返回原始发现记录列表。

        子类负责：
        1. 调用外部 API
        2. 解析响应
        3. 生成 RawDiscovery（含 discovery_score）
        4. 处理异常并返回适当 status
        """
        ...

    def is_enabled(self) -> bool:
        """该源是否在当前配置下启用。子类可覆盖。"""
        return True

    async def request_with_retry(
        self,
        method: str,
        url: str,
        *,
        client: httpx.AsyncClient | None = None,
        timeout: float | httpx.Timeout | None = None,
        follow_redirects: bool = False,
        **kwargs: Any,
    ) -> httpx.Response:
        """发送一次 HTTP 请求，按 ``self.retry`` 对可恢复失败退避重试。

        只重试网络错误（含超时）、429 和 5xx；其余 4xx 立即返回，交给调用方
        ``raise_for_status()`` 或按状态码分支处理。可重试状态在重试耗尽后
        返回最后一次响应（调用方照常 raise），网络错误耗尽后抛出最后一次异常。

        每次尝试都会重新通过本地令牌桶；``client`` 为空时每次尝试新建受
        白名单保护的客户端，传入 ``client`` 则复用调用方的连接（由调用方关闭）。
        """
        max_attempts = 1 + max(0, int(self.retry or 0))
        last_transport_error: httpx.TransportError | None = None
        response: httpx.Response | None = None

        for attempt in range(1, max_attempts + 1):
            retry_after: float | None = None
            try:
                if client is None:
                    async with (
                        self.rate_limiter,
                        self.http_client(timeout=timeout, follow_redirects=follow_redirects) as owned,
                    ):
                        response = await owned.request(method, url, **kwargs)
                else:
                    async with self.rate_limiter:
                        response = await client.request(method, url, **kwargs)
            except httpx.TransportError as exc:
                last_transport_error = exc
                response = None
            else:
                last_transport_error = None
                if not self._is_retryable_status(response.status_code):
                    return response
                retry_after = self._retry_after_seconds(response)

            if attempt >= max_attempts:
                break

            delay = self._retry_delay(attempt, retry_after)
            self.logger.warning(
                "collector.retry",
                method=method,
                attempt=attempt,
                max_attempts=max_attempts,
                delay_seconds=round(delay, 2),
                status_code=response.status_code if response is not None else None,
                error_type=type(last_transport_error).__name__ if last_transport_error is not None else None,
                error=redact(str(last_transport_error))[:200] if last_transport_error is not None else None,
            )
            await asyncio.sleep(delay)

        if last_transport_error is not None:
            raise last_transport_error

        assert response is not None
        return response

    @staticmethod
    def _is_retryable_status(status_code: int) -> bool:
        """429 与 5xx 可重试；403 常是权限或硬限流，重试只会放大配额压力。"""
        return status_code == 429 or 500 <= status_code < 600

    @staticmethod
    def _retry_after_seconds(response: httpx.Response) -> float | None:
        """解析 Retry-After 的秒数形式；HTTP-date 形式不解析，退回指数退避。"""
        raw = response.headers.get("Retry-After")
        if not raw:
            return None
        try:
            return max(0.0, float(raw.strip()))
        except ValueError:
            return None

    def _retry_delay(self, attempt: int, retry_after: float | None) -> float:
        """指数退避 + Retry-After 取大，并限制单次等待上限。"""
        # 用 2.0 而非 2：mypy 把 int ** int 视作 Any（负指数时结果可能是 float）。
        backoff: float = self.RETRY_BASE_DELAY * (2.0 ** (attempt - 1))
        if retry_after is not None:
            backoff = max(backoff, retry_after)
        return min(self.RETRY_MAX_DELAY, backoff)

    @contextlib.asynccontextmanager
    async def http_client(
        self,
        *,
        timeout: float | httpx.Timeout | None = None,
        follow_redirects: bool = False,
        **kwargs: Any,
    ) -> AsyncIterator[httpx.AsyncClient]:
        """统一出站 HTTP 客户端，强制校验域名白名单并隔离外部访问。"""
        effective_timeout = timeout if timeout is not None else getattr(self, "timeout", 10.0)
        async with safe_collector_client(
            timeout=effective_timeout,
            follow_redirects=follow_redirects,
            **kwargs,
        ) as client:
            yield client

    async def health_check(self) -> dict[str, Any]:
        """可选：源健康检查。默认返回未知。"""
        return {"source_id": self.source_id, "status": "unknown"}


class CollectorRegistry(Protocol):
    """注册表协议，用于依赖注入。"""

    def register(self, collector: DataCollector) -> None: ...
    def get(self, source_id: str) -> DataCollector | None: ...
    def list_enabled(self) -> list[DataCollector]: ...
