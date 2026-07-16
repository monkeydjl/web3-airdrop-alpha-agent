"""RootData Collector — project search + funding enrichment.

API (documented on rootdata.com/Api/Doc):
  POST https://api.rootdata.com/open/ser_inv     search projects/VCs
  POST https://api.rootdata.com/open/get_item    project details
  POST https://api.rootdata.com/open/get_fac     fundraising rounds

Auth: JSON body field ``apikey`` (and/or header depending on plan).

Requires ROOTDATA_API_KEY. Free Basic plan supports search + partial project
info; funding rounds may need Plus/Pro — collector degrades gracefully.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import structlog

from app.collectors.base import CollectorResult, DataCollector, RawDiscovery, RawSignal
from app.collectors.rate_limiter import TokenBucketRateLimiter
from app.config import settings
from app.services.funding import extract_funding_from_raw
from app.utils.normalize import normalize_sector

logger = structlog.get_logger(__name__)


class RootDataCollector(DataCollector):
    """Pull recent / searchable projects and attach funding quality signals."""

    MAX_ITEMS = 80
    # Seed queries: early-stage / fundraising oriented
    DEFAULT_QUERIES = (
        "testnet",
        "layer2",
        "restaking",
        "airdrop",
        "defi",
        "infra",
    )

    def __init__(self) -> None:
        super().__init__(source_id="rootdata", source_name="RootData")
        self.base_url = getattr(settings, "rootdata_base_url", "https://api.rootdata.com").rstrip("/")
        self.timeout = getattr(settings, "rootdata_timeout", 30)
        self.api_key = getattr(settings, "rootdata_api_key", "") or ""
        self.rate_limiter = TokenBucketRateLimiter("rootdata")
        self.logger = logger.bind(source_id=self.source_id)

    @property
    def source_type(self) -> str:
        return "api"

    def is_enabled(self) -> bool:
        return bool(getattr(settings, "rootdata_enabled", False) and self.api_key)

    async def collect(self) -> CollectorResult:
        result = CollectorResult(source_id=self.source_id)
        result.started_at = datetime.now(UTC)
        try:
            items: list[dict[str, Any]] = []
            for q in self.DEFAULT_QUERIES:
                found = await self._search(q)
                items.extend(found)
                if len(items) >= self.MAX_ITEMS * 2:
                    break

            # dedupe by project_id / name
            seen: set[str] = set()
            unique: list[dict[str, Any]] = []
            for it in items:
                key = str(it.get("project_id") or it.get("id") or it.get("name") or "")
                if not key or key in seen:
                    continue
                seen.add(key)
                unique.append(it)

            discoveries: list[RawDiscovery] = []
            for it in unique[: self.MAX_ITEMS]:
                # optional detail + funding enrichment
                detail = await self._get_item(it.get("project_id") or it.get("id"))
                if detail:
                    it = {**it, **detail}
                fac = await self._get_fac(it.get("project_id") or it.get("id"))
                if fac:
                    it["fac"] = fac
                disc = self._build_discovery(it)
                if disc:
                    discoveries.append(disc)

            discoveries.sort(key=lambda d: d.discovery_score, reverse=True)
            result.items = discoveries[: self.MAX_ITEMS]
            result.status = "success" if result.items else "partial"
            self.logger.info("rootdata.collected", count=len(result.items))
        except Exception as e:
            self.logger.error("rootdata.error", error=str(e))
            result.status = "error"
            result.error_message = str(e)
        finally:
            result.finished_at = datetime.now(UTC)
        return result

    async def _post(self, path: str, body: dict[str, Any]) -> Any:
        url = f"{self.base_url}{path}"
        payload = {"apikey": self.api_key, **body}
        headers = {
            "Content-Type": "application/json",
            "apikey": self.api_key,
        }
        async with self.rate_limiter, httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code == 401 or resp.status_code == 403:
                raise RuntimeError(f"RootData auth failed HTTP {resp.status_code}")
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()

    async def _search(self, query: str) -> list[dict[str, Any]]:
        """POST /open/ser_inv — search project/VC/people."""
        try:
            data = await self._post(
                "/open/ser_inv",
                {"query": query, "precise_x_search": False},
            )
        except Exception as e:
            self.logger.warning("rootdata.search_failed", query=query, error=str(e))
            return []
        return self._as_list(data)

    async def _get_item(self, project_id: Any) -> dict[str, Any] | None:
        if project_id is None:
            return None
        try:
            pid = int(project_id)
        except (TypeError, ValueError):
            return None
        try:
            data = await self._post("/open/get_item", {"project_id": pid})
        except Exception as e:
            self.logger.debug("rootdata.get_item_failed", project_id=pid, error=str(e))
            return None
        if isinstance(data, dict):
            # some plans wrap under data/result
            for k in ("data", "result", "project"):
                if isinstance(data.get(k), dict):
                    return data[k]
            return data
        return None

    async def _get_fac(self, project_id: Any) -> list[dict[str, Any]]:
        """Fundraising rounds — may require Plus plan."""
        if project_id is None:
            return []
        try:
            pid = int(project_id)
        except (TypeError, ValueError):
            return []
        try:
            data = await self._post("/open/get_fac", {"project_id": pid})
        except Exception as e:
            self.logger.debug("rootdata.get_fac_failed", project_id=pid, error=str(e))
            return []
        return self._as_list(data)

    def _as_list(self, data: Any) -> list[dict[str, Any]]:
        if data is None:
            return []
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
        if isinstance(data, dict):
            for k in ("data", "result", "list", "items", "projects"):
                v = data.get(k)
                if isinstance(v, list):
                    return [x for x in v if isinstance(x, dict)]
            # single project dict
            if data.get("name") or data.get("project_name") or data.get("project_id"):
                return [data]
        return []

    def _build_discovery(self, item: dict[str, Any]) -> RawDiscovery | None:
        name = (item.get("name") or item.get("project_name") or item.get("projectName") or "").strip()
        if not name:
            return None

        pid = item.get("project_id") or item.get("id") or name
        sector = normalize_sector(
            str(item.get("one_liner") or item.get("tag") or item.get("tags") or "DeFi")
            if not isinstance(item.get("tags"), list)
            else (item.get("tags") or ["DeFi"])[0]
        )
        if isinstance(item.get("tags"), list) and item["tags"]:
            sector = normalize_sector(str(item["tags"][0]))

        funding = extract_funding_from_raw(item)
        recent = bool(funding.get("funding_quality", 0) > 0.2) or bool(
            funding.get("days_since_round") is not None and funding["days_since_round"] <= 365
        )

        # RootData projects often pre-TGE — mild airdrop relevance
        no_token = bool(
            item.get("no_token")
            or str(item.get("token_status") or "").lower() in ("no", "none", "unissued", "")
            or item.get("tge") in (False, "false", 0, "0", None)
        )

        investors = funding.get("funding_investors") or []
        score = 0.35 + float(funding.get("funding_quality") or 0) * 0.45
        if recent:
            score += 0.05
        if funding.get("funding_tier") == "tier1":
            score += 0.08
        score = max(0.2, min(0.85, score))

        raw = {
            **item,
            "name": name,
            "sector": sector,
            "recent_funding": recent,
            "no_token_yet": no_token,
            "has_twitter": bool(item.get("twitter") or item.get("X") or item.get("x")),
            "has_github": bool(item.get("github") or item.get("Github")),
            "has_docs": bool(item.get("gitbook") or item.get("docs") or item.get("website")),
            "url": item.get("website") or item.get("url") or item.get("rootdata_url"),
            "description": item.get("description") or item.get("one_liner") or item.get("brief"),
            **{k: funding[k] for k in funding},
            "airdrop_signals": {
                "recent_funding": recent,
                "no_token_yet": no_token,
            },
        }

        signals = [
            RawSignal(
                signal_type="funding",
                signal_source="rootdata",
                signal_data={
                    "tier": funding.get("funding_tier"),
                    "quality": funding.get("funding_quality"),
                    "total_usd": funding.get("funding_total_usd"),
                    "rounds": funding.get("funding_rounds"),
                    "investors": investors[:10],
                },
                signal_strength=float(funding.get("funding_quality") or 0),
            )
        ]

        return RawDiscovery(
            source_id=self.source_id,
            raw_id=str(pid),
            name=name,
            url=raw.get("url"),
            sector=sector,
            stage="testnet" if no_token else "mainnet",
            raw_data=raw,
            raw_signals=signals,
            discovery_score=round(score, 4),
            discovered_at=datetime.now(UTC),
        )

    async def health_check(self) -> dict[str, Any]:
        if not self.is_enabled():
            return {"status": "disabled", "reason": "no api key or disabled"}
        try:
            data = await self._search("ethereum")
            return {"status": "healthy", "sample_hits": len(data)}
        except Exception as e:
            return {"status": "unhealthy", "error": str(e)}
