"""Galxe Quest Collector.

Fetches active campaigns from Galxe (formerly Project Galaxy) and emits
RawDiscovery records for projects running quest/airdrop campaigns.

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


GALXE_GRAPHQL_URL = "https://graphigo.prd.galaxy.eco/query"


class GalxeCollector(DataCollector):
    """Galxe 任务平台采集器。

    采集策略：
    1. 调用 Galxe GraphQL API 查询活跃 campaign
    2. 提取项目名（来自 space.name）、奖励类型、参与条件
    3. 输出 RawDiscovery，sector 为 "Quest"
    """

    MIN_CAMPAIGNS = 1

    def __init__(self) -> None:
        super().__init__(source_id="galxe", source_name="Galxe")
        self.api_key = settings.galxe_api_key
        self.timeout = settings.galxe_timeout
        self.retry = settings.galxe_retry
        self.rate_limiter = TokenBucketRateLimiter("galxe")
        self.logger = logger.bind(source_id=self.source_id)

    @property
    def source_type(self) -> str:
        return "api"

    def is_enabled(self) -> bool:
        return bool(settings.galxe_enabled and self.api_key)

    async def collect(self) -> CollectorResult:
        """执行 Galxe campaign 采集。"""
        result = CollectorResult(source_id=self.source_id)
        result.started_at = datetime.now(UTC)

        try:
            campaigns = await self._fetch_campaigns()
            self.logger.info(
                "galxe.fetched",
                campaign_count=len(campaigns),
            )

            for campaign in campaigns:
                discovery = self._build_discovery(campaign)
                if discovery.discovery_score > 0:
                    result.items.append(discovery)

            result.status = "success" if result.items else "partial"

        except Exception as e:
            self.logger.error("galxe.error", error=str(e))
            result.status = "error"
            result.error_message = str(e)

        finally:
            result.finished_at = datetime.now(UTC)

        return result

    async def health_check(self) -> dict[str, Any]:
        """检查 Galxe API 连通性。"""
        if not self.is_enabled():
            return {"source_id": self.source_id, "status": "disabled"}
        try:
            await self._fetch_campaigns(limit=1)
            return {"source_id": self.source_id, "status": "healthy"}
        except Exception as e:
            return {"source_id": self.source_id, "status": "unhealthy", "error": str(e)}

    async def _fetch_campaigns(self, limit: int = 100) -> list[dict[str, Any]]:
        """获取 Galxe campaign 列表。"""
        query = {
            "operationName": "CampaignList",
            "query": (
                "query CampaignList {"
                "  campaignList(listInput: {limit: " + str(limit) + ", order: "
                '["createdAt"]}) {'
                "    list {"
                "      id"
                "      name"
                "      description"
                "      status"
                "      rewardType"
                "      thumbnail"
                "      space {"
                "        id"
                "        name"
                "        alias"
                "      }"
                "    }"
                "  }"
                "}"
            ),
            "variables": {},
        }

        headers = {
            "Content-Type": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        async with self.rate_limiter, httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                GALXE_GRAPHQL_URL,
                json=query,
                headers=headers,
            )
            response.raise_for_status()
            data = response.json()

        if "errors" in data:
            raise ValueError(f"Galxe GraphQL error: {data['errors']}")

        campaign_list = data.get("data", {}).get("campaignList", {})
        return campaign_list.get("list", []) or []

    def _build_discovery(self, campaign: dict[str, Any]) -> RawDiscovery:
        """将 Galxe campaign 转换为 RawDiscovery。"""
        space = campaign.get("space") or {}
        project_name = space.get("name") or campaign.get("name", "Unknown")
        raw_id = str(campaign.get("id", ""))
        reward_type = campaign.get("rewardType", "")
        status = campaign.get("status", "")

        discovery_score = self._calculate_discovery_score(campaign)

        raw_data = {
            "campaign_id": raw_id,
            "campaign_name": campaign.get("name"),
            "space_id": space.get("id"),
            "space_alias": space.get("alias"),
            "reward_type": reward_type,
            "status": status,
            "description": campaign.get("description"),
            "thumbnail": campaign.get("thumbnail"),
        }

        signals = [
            RawSignal(
                signal_type="quest",
                signal_source=self.source_id,
                signal_data={"reward_type": reward_type, "status": status},
                signal_strength=1.0 if reward_type in {"TOKEN", "OAT"} else 0.5,
            ),
            RawSignal(
                signal_type="community_activity",
                signal_source=self.source_id,
                signal_data={"space_alias": space.get("alias")},
                signal_strength=0.6,
            ),
        ]

        return RawDiscovery(
            source_id=self.source_id,
            raw_id=raw_id,
            name=project_name,
            url=f"https://galxe.com/{space.get('alias') or 'space'}/campaign/{raw_id}",
            sector="Quest",
            stage="mainnet",
            raw_data=raw_data,
            raw_signals=signals,
            discovery_score=discovery_score,
            discovered_at=datetime.now(UTC),
        )

    def _calculate_discovery_score(self, campaign: dict[str, Any]) -> float:
        """基于奖励类型和状态计算 discovery_score。"""
        reward_type = campaign.get("rewardType", "")
        status = campaign.get("status", "")

        score = 0.3
        if reward_type in {"TOKEN", "OAT"}:
            score += 0.4
        if status == "ACTIVE":
            score += 0.2
        if campaign.get("description"):
            score += 0.1

        return round(min(1.0, score), 3)
