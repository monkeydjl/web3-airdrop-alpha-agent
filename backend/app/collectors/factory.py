"""Default collector registry factory.

集中构建全部采集器并缓存为进程级单例。

为什么必须共享实例：`TokenBucketRateLimiter` 的令牌桶是 **实例状态**。
此前 API 路由每次请求都新建一套采集器，等于每次请求都拿到一个满桶的限流器，
反复调用手动触发端点即可完全绕过出站限流（并让上游把本机 IP 拉黑）。
调度器与 API 路由共用同一注册表后，限流才真正生效。
"""

from __future__ import annotations

import threading

from app.collectors.coingecko import CoinGeckoCollector
from app.collectors.cryptorank import CryptoRankCollector
from app.collectors.defillama import DefiLlamaCollector
from app.collectors.discord import DiscordCollector
from app.collectors.etherscan import EtherscanCollector
from app.collectors.galxe import GalxeCollector
from app.collectors.github import GitHubCollector
from app.collectors.layer3 import Layer3Collector
from app.collectors.medium import MediumCollector
from app.collectors.mirror import MirrorCollector
from app.collectors.reddit import RedditCollector
from app.collectors.registry import CollectorRegistry
from app.collectors.rootdata import RootDataCollector
from app.collectors.twitter import TwitterKeywordCollector, TwitterKolCollector

_registry: CollectorRegistry | None = None
_lock = threading.Lock()


def build_default_registry() -> CollectorRegistry:
    """构建一个包含全部采集器的新注册表（不缓存）。"""
    registry = CollectorRegistry()
    for collector in (
        DefiLlamaCollector(),
        GitHubCollector(),
        CoinGeckoCollector(),
        CryptoRankCollector(),
        RootDataCollector(),
        TwitterKolCollector(),
        TwitterKeywordCollector(),
        EtherscanCollector(),
        GalxeCollector(),
        Layer3Collector(),
        DiscordCollector(),
        RedditCollector(),
        MediumCollector(),
        MirrorCollector(),
    ):
        registry.register(collector)
    return registry


def get_default_registry() -> CollectorRegistry:
    """返回进程级共享注册表（首次调用时构建）。

    同步路由现在跑在线程池里，可能并发首次调用，故加锁做双重检查。
    """
    global _registry
    if _registry is None:
        with _lock:
            if _registry is None:
                _registry = build_default_registry()
    return _registry


def reset_default_registry() -> None:
    """丢弃缓存实例（测试用：让配置改动重新生效）。"""
    global _registry
    with _lock:
        _registry = None
