"""Collector Registry.

管理所有 DataCollector 实例的注册与发现。

参考：
- DATA_SOURCE_STRATEGY.md §采集器注册
- ENGINEERING_ROADMAP.md §6.2
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from app.collectors.base import DataCollector

logger = structlog.get_logger(__name__)


class CollectorRegistry:
    """采集器注册表。

    示例：
        registry = CollectorRegistry()
        registry.register(DefiLlamaCollector())
        for collector in registry.list_enabled():
            result = await collector.collect()
    """

    def __init__(self) -> None:
        self._collectors: dict[str, DataCollector] = {}

    def register(self, collector: DataCollector) -> None:
        """注册采集器。"""
        self._collectors[collector.source_id] = collector
        logger.info(
            "collector.registry.registered",
            source_id=collector.source_id,
            source_name=collector.source_name,
        )

    def get(self, source_id: str) -> DataCollector | None:
        """按 source_id 获取采集器。"""
        return self._collectors.get(source_id)

    def list_all(self) -> list[DataCollector]:
        """返回所有已注册采集器。"""
        return list(self._collectors.values())

    def list_enabled(self) -> list[DataCollector]:
        """返回当前配置下启用的采集器。"""
        return [c for c in self._collectors.values() if c.is_enabled()]

    def unregister(self, source_id: str) -> DataCollector | None:
        """注销采集器。"""
        collector = self._collectors.pop(source_id, None)
        if collector:
            logger.info("collector.registry.unregistered", source_id=source_id)
        return collector

    def __contains__(self, source_id: str) -> bool:
        return source_id in self._collectors

    def __len__(self) -> int:
        return len(self._collectors)
