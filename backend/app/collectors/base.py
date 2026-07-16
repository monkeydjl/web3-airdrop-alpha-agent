"""Collector Base Classes.

定义所有外部数据源的采集器抽象接口与统一输出模型。
v2.0 方向：从手动输入项目反转为系统自动扫描全网项目。

参考：
- ENGINEERING_ROADMAP.md §6.2 Collector Agent
- DATA_SOURCE_STRATEGY.md §采集器接口
- ADR-012-system-direction-auto-scan.md
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

import structlog

from app.utils.normalize import create_dedup_key, generate_deterministic_id

logger = structlog.get_logger(__name__)


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
    """

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

    async def health_check(self) -> dict[str, Any]:
        """可选：源健康检查。默认返回未知。"""
        return {"source_id": self.source_id, "status": "unknown"}


class CollectorRegistry(Protocol):
    """注册表协议，用于依赖注入。"""

    def register(self, collector: DataCollector) -> None: ...
    def get(self, source_id: str) -> DataCollector | None: ...
    def list_enabled(self) -> list[DataCollector]: ...
