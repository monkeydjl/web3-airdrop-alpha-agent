"""Layer3 Quest Collector.

Fetches active tasks/bounties from Layer3 and emits RawDiscovery records for
projects running quest campaigns.

Reference:
- DATA_SOURCE_STRATEGY.md §3. Quest Platforms
- ENGINEERING_ROADMAP.md §6.2
- ADR-012-system-direction-auto-scan.md
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import structlog

from app.collectors.base import CollectorResult, DataCollector, RawDiscovery, RawSignal
from app.collectors.rate_limiter import TokenBucketRateLimiter
from app.config import settings

logger = structlog.get_logger(__name__)


class Layer3Collector(DataCollector):
    """Layer3 任务平台采集器。

    采集策略：
    1. 调用 Layer3 REST API 获取活跃任务列表
    2. 提取项目名、奖励类型、链信息
    3. 输出 RawDiscovery，sector 为 "Quest"
    """

    DEFAULT_BASE_URL = "https://api.layer3.xyz/api"

    def __init__(self) -> None:
        super().__init__(source_id="layer3", source_name="Layer3")
        self.api_key = settings.layer3_api_key
        self.base_url = self.DEFAULT_BASE_URL
        self.timeout = settings.layer3_timeout
        self.retry = settings.layer3_retry
        self.rate_limiter = TokenBucketRateLimiter("layer3")
        self.logger = logger.bind(source_id=self.source_id)

    @property
    def source_type(self) -> str:
        return "api"

    def is_enabled(self) -> bool:
        return bool(settings.layer3_enabled and self.api_key)

    async def collect(self) -> CollectorResult:
        """执行 Layer3 任务采集。"""
        result = CollectorResult(source_id=self.source_id)
        result.started_at = datetime.now(UTC)

        try:
            tasks = await self._fetch_tasks()
            self.logger.info(
                "layer3.fetched",
                task_count=len(tasks),
            )

            for task in tasks:
                discovery = self._build_discovery(task)
                if discovery.discovery_score > 0:
                    result.items.append(discovery)

            result.status = "success" if result.items else "partial"

        except Exception as e:
            self.logger.error("layer3.error", error=str(e))
            result.status = "error"
            result.error_message = str(e)

        finally:
            result.finished_at = datetime.now(UTC)

        return result

    async def health_check(self) -> dict[str, Any]:
        """检查 Layer3 API 连通性。"""
        if not self.is_enabled():
            return {"source_id": self.source_id, "status": "disabled"}
        try:
            await self._fetch_tasks(limit=1)
            return {"source_id": self.source_id, "status": "healthy"}
        except Exception as e:
            return {"source_id": self.source_id, "status": "unhealthy", "error": str(e)}

    async def _fetch_tasks(self, limit: int = 100) -> list[dict[str, Any]]:
        """获取 Layer3 任务列表。"""
        url = f"{self.base_url}/tasks"
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        params: dict[str, str | int | float | bool | None] = {"limit": limit, "status": "active"}

        async with self.rate_limiter, httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(url, params=params, headers=headers)
            response.raise_for_status()
            data = response.json()

        if not isinstance(data, dict):
            raise ValueError(f"Unexpected Layer3 response type: {type(data)}")

        return data.get("data", []) or data.get("tasks", []) or []

    def _build_discovery(self, task: dict[str, Any]) -> RawDiscovery:
        """将 Layer3 task 转换为 RawDiscovery。"""
        task_id = str(task.get("id", ""))
        project_name = task.get("projectName") or task.get("title") or task.get("name", "Unknown")
        reward_type = task.get("rewardType", "")
        chain = task.get("chain", "")
        status = task.get("status", "")

        discovery_score = self._calculate_discovery_score(task)

        raw_data = {
            "task_id": task_id,
            "title": task.get("title"),
            "description": task.get("description"),
            "chain": chain,
            "reward_type": reward_type,
            "status": status,
            "difficulty": task.get("difficulty"),
            "xp": task.get("xp"),
        }

        signals = [
            RawSignal(
                signal_type="quest",
                signal_source=self.source_id,
                signal_data={"reward_type": reward_type, "chain": chain, "status": status},
                signal_strength=1.0 if reward_type in {"TOKEN", "NFT", "AIRDROP"} else 0.5,
            ),
            RawSignal(
                signal_type="community_activity",
                signal_source=self.source_id,
                signal_data={"chain": chain},
                signal_strength=0.6 if chain else 0.3,
            ),
        ]

        return RawDiscovery(
            source_id=self.source_id,
            raw_id=task_id,
            name=project_name,
            url=f"https://layer3.xyz/tasks/{task_id}",
            # 同 galxe：任务门户不掌握赛道信息，写死会隔断跨源合并
            sector=None,
            stage="mainnet",
            raw_data=raw_data,
            raw_signals=signals,
            discovery_score=discovery_score,
            discovered_at=datetime.now(UTC),
        )

    def _calculate_discovery_score(self, task: dict[str, Any]) -> float:
        """基于奖励和链信息计算 discovery_score。"""
        reward_type = task.get("rewardType", "")
        status = task.get("status", "")
        chain = task.get("chain", "")

        score = 0.3
        if reward_type in {"TOKEN", "AIRDROP"}:
            score += 0.4
        elif reward_type == "NFT":
            score += 0.2
        if status == "active":
            score += 0.2
        if chain:
            score += 0.1

        return round(min(1.0, score), 3)
