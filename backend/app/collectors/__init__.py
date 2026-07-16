"""Collectors package.

外部数据源采集器包，用于从 DefiLlama/GitHub/CoinGecko/Twitter 等源
自动发现 Web3 早期项目。

主要模块：
- base: 采集器抽象基类与数据模型
- registry: 采集器注册表
- rate_limiter: 异步令牌桶限流
- scheduler: APScheduler 采集调度器
- persistence: 采集结果持久化
- defillama: DefiLlama 采集器实现
- github: GitHub 采集器实现
- coingecko: CoinGecko 采集器实现
"""

from app.collectors.base import (
    CollectorResult,
    DataCollector,
    RawDiscovery,
    RawSignal,
)
from app.collectors.coingecko import CoinGeckoCollector
from app.collectors.cryptorank import CryptoRankCollector
from app.collectors.github import GitHubCollector
from app.collectors.persistence import CollectionRepository
from app.collectors.registry import CollectorRegistry
from app.collectors.rootdata import RootDataCollector

__all__ = [
    "CoinGeckoCollector",
    "CollectionRepository",
    "CollectorRegistry",
    "CollectorResult",
    "CryptoRankCollector",
    "DataCollector",
    "GitHubCollector",
    "RawDiscovery",
    "RawSignal",
    "RootDataCollector",
]
