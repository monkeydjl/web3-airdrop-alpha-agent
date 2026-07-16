"""Collector Agent - Data collection and deduplication.

Collects projects from multiple sources, normalizes names/sectors,
deduplicates across sources, and generates deterministic UUIDs.

Reference:
- ENGINEERING_ROADMAP.md §6.2 Collector
- TASK_BREAKDOWN.md W2-03
- ADR-012-system-direction-auto-scan.md
"""

import json
import time
from datetime import datetime
from typing import TYPE_CHECKING

import structlog

from app.agents.base import AgentError, BaseAgent, PipelineState, RawProject
from app.collectors.noise import is_noise_raw_project
from app.utils.normalize import (
    create_dedup_key,
    generate_deterministic_id,
    merge_raw_records,
    normalize_sector,
)

if TYPE_CHECKING:
    from app.collectors.base import CollectorResult
    from app.collectors.persistence import CollectionRepository
    from app.collectors.registry import CollectorRegistry

logger = structlog.get_logger(__name__)


class CollectorAgent(BaseAgent):
    """Collector Agent - MVP implementation.

    Collects projects from seed data (MVP) or external sources (V2).
    Normalizes, deduplicates, and assigns deterministic UUIDs.

    MVP: Uses seed data from config/database
    V2: Fetches from DefiLlama, CryptoRank, Twitter
    """

    def __init__(self):
        super().__init__("collector")

    def _raw_to_record(self, raw: dict) -> dict:
        """Normalize a raw seed/API record and assign deterministic project_id."""
        name = raw.get("name", "")
        sector = raw.get("sector")
        dedup_key = create_dedup_key(name, sector)
        project_id = generate_deterministic_id(dedup_key)
        ext = self._infer_airdrop_flags(str(raw.get("source") or "seed"), raw)
        return {
            "project_id": project_id,
            "name": name,
            "url": raw.get("url"),
            "sector": normalize_sector(sector) if sector else None,
            "stage": raw.get("stage") or ext.get("stage"),
            "source": raw.get("source", "seed"),
            "has_testnet": bool(raw.get("has_testnet", ext.get("has_testnet", False))),
            "has_points_program": bool(raw.get("has_points_program", ext.get("has_points_program", False))),
            "no_token_yet": bool(raw.get("no_token_yet", ext.get("no_token_yet", False))),
            "recent_funding": bool(raw.get("recent_funding", ext.get("recent_funding", False))),
            "has_docs": bool(ext.get("has_docs", False)),
            "has_whitepaper": bool(ext.get("has_whitepaper", False)),
            "has_roadmap": bool(ext.get("has_roadmap", False)),
            "has_github": bool(ext.get("has_github", False)),
            "has_twitter": bool(ext.get("has_twitter", False)),
            "has_discord": bool(ext.get("has_discord", False)),
            "github_stars": int(ext.get("github_stars") or 0),
            "github_recent_push_days": ext.get("github_recent_push_days"),
            "explicit_airdrop_mention": bool(ext.get("explicit_airdrop_mention", False)),
            "tvl_usd": ext.get("tvl_usd"),
            "description": ext.get("description"),
            "has_task_portal": bool(ext.get("has_task_portal", False)),
            "has_contract": bool(ext.get("has_contract", False)),
            "source_count": int(ext.get("source_count") or 1),
            "roadmap_delivery": ext.get("roadmap_delivery") or "unknown",
            "sybil_friction": ext.get("sybil_friction") or "unknown",
            "funding_total_usd": ext.get("funding_total_usd"),
            "funding_rounds": int(ext.get("funding_rounds") or 0),
            "funding_last_date": ext.get("funding_last_date"),
            "funding_investors": list(ext.get("funding_investors") or []),
            "funding_lead_investors": list(ext.get("funding_lead_investors") or []),
            "funding_tier": ext.get("funding_tier") or "unknown",
            "funding_quality": float(ext.get("funding_quality") or 0),
            "discovery_score": raw.get("discovery_score", 0.0),
            "auto_discovered": raw.get("auto_discovered", False),
            "discovered_at": raw.get("discovered_at"),
            "_dedup_key": dedup_key,
        }

    @staticmethod
    def _infer_airdrop_flags(source_id: str, raw_data: dict) -> dict:
        """Map collector raw_data → scoring flags used by Scorer/Risk.

        DefiLlama unlisted protocols should set no_token_yet; GitHub text
        may hint testnet/points. Explicit fields in raw_data always win.

        v1.2 also infers docs/social/repo health for execution & transparency.
        """
        from datetime import UTC, datetime

        stage = (raw_data.get("stage") or "").lower()
        text = " ".join(
            str(raw_data.get(k) or "")
            for k in (
                "name",
                "description",
                "full_name",
                "slug",
                "category",
                "homepage",
                "url",
                "twitter",
                "github",
                "docs",
            )
        ).lower()

        def _explicit(key: str) -> bool | None:
            if key not in raw_data:
                return None
            return bool(raw_data.get(key))

        no_token = _explicit("no_token_yet")
        has_testnet = _explicit("has_testnet")
        has_points = _explicit("has_points_program")
        recent_funding = _explicit("recent_funding")

        # Source-aware defaults when flags missing
        if no_token is None:
            if source_id == "defillama":
                gecko = raw_data.get("gecko_id")
                no_token = not gecko
            elif source_id in ("coingecko", "cryptorank"):
                no_token = False
            elif source_id == "github":
                no_token = "airdrop" in text or "no token" in text
            else:
                no_token = False

        if has_testnet is None:
            has_testnet = stage == "testnet" or "testnet" in text

        if has_points is None:
            has_points = (
                "points program" in text
                or ("points" in text and ("airdrop" in text or "loyalty" in text))
                or "incentive" in text
            )

        if recent_funding is None:
            recent_funding = "funding" in text or "raised" in text

        if not stage and source_id == "github":
            stage = "ideation"
        if not stage and source_id == "defillama":
            stage = raw_data.get("stage") or "mainnet"

        # ── v1.2 extended signals ──
        has_whitepaper = bool(
            raw_data.get("has_whitepaper") or "whitepaper" in text or "litepaper" in text or "white paper" in text
        )
        has_docs = bool(
            raw_data.get("has_docs")
            or has_whitepaper
            or "docs." in text
            or "documentation" in text
            or "/docs" in text
            or "gitbook" in text
            or raw_data.get("docs")
        )
        has_roadmap = bool(
            raw_data.get("has_roadmap") or "roadmap" in text or "milestones" in text or "timeline" in text
        )
        has_github = bool(
            raw_data.get("has_github")
            or raw_data.get("github")
            or raw_data.get("full_name")
            or source_id == "github"
            or "github.com" in text
        )
        has_twitter = bool(
            raw_data.get("has_twitter")
            or raw_data.get("twitter")
            or "twitter.com" in text
            or "x.com/" in text
            or source_id in ("twitter", "twitter_kol", "twitter_keyword")
        )
        has_discord = bool(
            raw_data.get("has_discord") or raw_data.get("discord") or "discord.gg" in text or "discord.com" in text
        )
        explicit_airdrop = bool(
            raw_data.get("explicit_airdrop_mention")
            or "airdrop confirmed" in text
            or "confirmed airdrop" in text
            or "official airdrop" in text
            or "token generation event" in text
            or "tge soon" in text
            or ("airdrop" in text and ("snapshot" in text or "eligible" in text))
        )

        # Verifiable task / quest / points portal (not just wording)
        has_task_portal = bool(
            raw_data.get("has_task_portal")
            or source_id in ("galxe", "layer3")
            or "galxe.com" in text
            or "layer3.xyz" in text
            or "zealy.io" in text
            or "questn.com" in text
            or "crew3" in text
            or "taskon" in text
            or "intract.io" in text
            or "quest." in text
            or "/quests" in text
            or "campaign portal" in text
            or ("points" in text and ("portal" in text or "dashboard" in text or "app." in text))
        )

        has_contract = bool(
            raw_data.get("has_contract")
            or raw_data.get("address")
            or raw_data.get("contract_address")
            or source_id == "etherscan"
            or "etherscan.io/address" in text
            or ("0x" in text and "contract" in text)
            or (tvl := raw_data.get("tvl") or raw_data.get("tvl_usd")) not in (None, 0, "0")
        )

        # Sybil friction: higher = harder to farm with many wallets (good for real users)
        sybil_friction = str(raw_data.get("sybil_friction") or "unknown").lower()
        if sybil_friction not in ("high", "medium", "low", "unknown"):
            sybil_friction = "unknown"
        if sybil_friction == "unknown":
            if any(
                k in text
                for k in (
                    "kyc",
                    "identity verification",
                    "passport",
                    "unique human",
                    "proof of humanity",
                    "gitcoin passport",
                    "world id",
                    "biometric",
                )
            ):
                sybil_friction = "high"
            elif any(
                k in text
                for k in (
                    "wallet screening",
                    "sybil",
                    "anti-sybil",
                    "one wallet",
                    "social account required",
                    "discord verify",
                    "twitter verify",
                )
            ):
                sybil_friction = "medium"
            elif has_points or has_task_portal:
                # open points campaigns are often easy to multi-wallet
                sybil_friction = "low"

        stars = raw_data.get("stars") or raw_data.get("stargazers_count") or raw_data.get("github_stars") or 0
        try:
            github_stars = int(stars)
        except (TypeError, ValueError):
            github_stars = 0

        push_days = raw_data.get("github_recent_push_days")
        if push_days is None:
            for key in ("updated_at", "pushed_at", "last_updated"):
                val = raw_data.get(key)
                if not val:
                    continue
                try:
                    if isinstance(val, str):
                        dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
                    else:
                        continue
                    push_days = max(0, (datetime.now(UTC) - dt).days)
                    break
                except (TypeError, ValueError) as exc:
                    logger.debug("collector.invalid_push_timestamp", value=val, error=str(exc))
                    continue

        tvl = raw_data.get("tvl") or raw_data.get("tvl_usd")
        try:
            tvl_usd = float(tvl) if tvl is not None else None
        except (TypeError, ValueError):
            tvl_usd = None

        description = raw_data.get("description") or raw_data.get("about")

        # Lightweight roadmap delivery: does shipping signal align with claimed stage?
        roadmap_delivery = str(raw_data.get("roadmap_delivery") or "unknown").lower()
        if roadmap_delivery not in ("aligned", "partial", "unclear", "unknown"):
            roadmap_delivery = "unknown"
        if roadmap_delivery == "unknown":
            stage_l = (stage or "").lower()
            shipping = bool(
                has_testnet
                or stage_l in ("testnet", "mainnet", "growth")
                or (tvl_usd is not None and tvl_usd > 0)
                or (push_days is not None and push_days <= 45)
            )
            if has_roadmap and shipping:
                roadmap_delivery = "aligned"
            elif has_roadmap and not shipping and stage_l in ("ideation", ""):
                roadmap_delivery = "unclear"  # paper roadmap only
            elif has_roadmap:
                roadmap_delivery = "partial"
            elif shipping and (has_github or tvl_usd):
                roadmap_delivery = "partial"  # shipping without public roadmap text
            else:
                roadmap_delivery = "unknown"

        # source_count filled at merge time; single-source default 1
        source_count = int(raw_data.get("source_count") or 1)

        # Funding quality (RootData / CryptoRank / manual)
        from app.services.funding import extract_funding_from_raw

        funding = extract_funding_from_raw(raw_data)
        if funding.get("funding_quality", 0) > 0.2:
            recent_funding = True

        return {
            "has_testnet": bool(has_testnet),
            "has_points_program": bool(has_points),
            "no_token_yet": bool(no_token),
            "recent_funding": bool(recent_funding),
            "stage": stage or raw_data.get("stage"),
            "has_docs": bool(has_docs),
            "has_whitepaper": bool(has_whitepaper),
            "has_roadmap": bool(has_roadmap),
            "has_github": bool(has_github),
            "has_twitter": bool(has_twitter),
            "has_discord": bool(has_discord),
            "github_stars": github_stars,
            "github_recent_push_days": push_days,
            "explicit_airdrop_mention": bool(explicit_airdrop),
            "tvl_usd": tvl_usd,
            "description": description,
            "has_task_portal": bool(has_task_portal),
            "has_contract": bool(has_contract),
            "source_count": source_count,
            "roadmap_delivery": roadmap_delivery,
            "sybil_friction": sybil_friction,
            "funding_total_usd": funding.get("funding_total_usd"),
            "funding_rounds": int(funding.get("funding_rounds") or 0),
            "funding_last_date": funding.get("funding_last_date"),
            "funding_investors": list(funding.get("funding_investors") or []),
            "funding_lead_investors": list(funding.get("funding_lead_investors") or []),
            "funding_tier": funding.get("funding_tier") or "unknown",
            "funding_quality": float(funding.get("funding_quality") or 0),
        }

    def _dedup_records(self, records: list[dict]) -> list[RawProject]:
        """Group records by dedup key, merge conflicts, and return RawProjects."""
        groups: dict[str, list[dict]] = {}
        for rec in records:
            key = rec.pop("_dedup_key")
            key_str = key.to_string()
            groups.setdefault(key_str, []).append(rec)

        results: list[RawProject] = []
        for key_str, items in groups.items():
            merged = merge_raw_records(items, source_key="source")
            project_id = merged.get("project_id") or generate_deterministic_id(
                create_dedup_key(merged.get("name", ""), merged.get("sector"))
            )

            if len(items) > 1:
                logger.info(
                    "collector.dedup",
                    project_id=project_id,
                    name=merged.get("name"),
                    dedup_key=key_str,
                    sources=merged.get("source"),
                    duplicates=len(items),
                )

            raw_ids: list[str] = []
            for item in items:
                rid = item.get("raw_id")
                if rid:
                    raw_ids.append(str(rid))
            for rid in merged.get("raw_ids") or []:
                if rid and rid not in raw_ids:
                    raw_ids.append(str(rid))

            results.append(
                RawProject(
                    id=project_id,
                    name=merged.get("name", ""),
                    url=merged.get("url"),
                    sector=merged.get("sector"),
                    stage=merged.get("stage"),
                    source=merged.get("source", "unknown"),
                    has_testnet=bool(merged.get("has_testnet", False)),
                    has_points_program=bool(merged.get("has_points_program", False)),
                    no_token_yet=bool(merged.get("no_token_yet", False)),
                    recent_funding=bool(merged.get("recent_funding", False)),
                    has_docs=bool(merged.get("has_docs", False)),
                    has_whitepaper=bool(merged.get("has_whitepaper", False)),
                    has_roadmap=bool(merged.get("has_roadmap", False)),
                    has_github=bool(merged.get("has_github", False)),
                    has_twitter=bool(merged.get("has_twitter", False)),
                    has_discord=bool(merged.get("has_discord", False)),
                    github_stars=int(merged.get("github_stars") or 0),
                    github_recent_push_days=merged.get("github_recent_push_days"),
                    explicit_airdrop_mention=bool(merged.get("explicit_airdrop_mention", False)),
                    tvl_usd=merged.get("tvl_usd"),
                    description=merged.get("description"),
                    has_task_portal=bool(merged.get("has_task_portal", False)),
                    has_contract=bool(merged.get("has_contract", False)),
                    source_count=max(
                        1,
                        int(merged.get("source_count") or 0)
                        or len({s.strip() for s in str(merged.get("source") or "unknown").split(",") if s.strip()}),
                    ),
                    roadmap_delivery=str(merged.get("roadmap_delivery") or "unknown"),
                    sybil_friction=str(merged.get("sybil_friction") or "unknown"),
                    funding_total_usd=merged.get("funding_total_usd"),
                    funding_rounds=int(merged.get("funding_rounds") or 0),
                    funding_last_date=merged.get("funding_last_date"),
                    funding_investors=list(merged.get("funding_investors") or [])
                    if isinstance(merged.get("funding_investors"), list)
                    else [],
                    funding_lead_investors=list(merged.get("funding_lead_investors") or [])
                    if isinstance(merged.get("funding_lead_investors"), list)
                    else [],
                    funding_tier=str(merged.get("funding_tier") or "unknown"),
                    funding_quality=float(merged.get("funding_quality") or 0),
                    discovery_source=merged.get("discovery_source") or merged.get("source", "unknown").split(",")[0],
                    auto_discovered=bool(merged.get("auto_discovered", False)),
                    discovered_at=merged.get("discovered_at"),
                    discovery_score=float(merged.get("discovery_score", 0.0)),
                    raw_ids=raw_ids,
                )
            )

        return results

    async def collect_from_registry(
        self,
        registry: "CollectorRegistry",
        repo: "CollectionRepository | None" = None,
    ) -> list[RawProject]:
        """Collect from all enabled collectors in registry.

        Args:
            registry: CollectorRegistry with registered collectors
            repo: Optional repository to persist raw results

        Returns:
            List of merged RawProject objects
        """
        logger.info("collector.registry.started", collector_count=len(registry.list_enabled()))
        start_time = time.time()

        records: list[dict] = []
        for collector in registry.list_enabled():
            try:
                result: CollectorResult = await collector.collect()
                for discovery in result.items:
                    raw_data = discovery.raw_data or {}
                    airdrop_signals = raw_data.get("airdrop_signals", {})
                    records.append(
                        {
                            "project_id": discovery.project_id,
                            "name": discovery.name,
                            "url": discovery.url,
                            "sector": normalize_sector(discovery.sector) if discovery.sector else None,
                            "stage": discovery.stage,
                            "source": discovery.source_id,
                            "has_testnet": airdrop_signals.get("has_testnet", False),
                            "has_points_program": airdrop_signals.get("has_points_program", False),
                            "no_token_yet": airdrop_signals.get("no_token_yet", False),
                            "recent_funding": airdrop_signals.get("recent_funding", False),
                            "discovery_score": discovery.discovery_score,
                            "auto_discovered": True,
                            "discovered_at": discovery.discovered_at,
                            "_dedup_key": create_dedup_key(discovery.name, discovery.sector),
                        }
                    )
                if repo is not None:
                    repo.persist_collection_result(result)
            except Exception as e:
                logger.error(
                    "collector.registry.error",
                    source_id=collector.source_id,
                    error=str(e),
                )

        projects = self._dedup_records(records)
        duration_ms = (time.time() - start_time) * 1000
        logger.info(
            "collector.registry.completed",
            input_count=len(records),
            output_count=len(projects),
            deduped=len(records) - len(projects),
            duration_ms=round(duration_ms, 2),
        )
        return projects

    def collect_from_repository(
        self,
        repo: "CollectionRepository",
        min_discovery_score: float = 0.3,
        limit: int = 100,
    ) -> list[RawProject]:
        """Collect unprocessed raw projects from repository.

        Args:
            repo: CollectionRepository to read raw_projects table
            min_discovery_score: Minimum discovery score to include
            limit: Maximum number of records to read

        Returns:
            List of merged RawProject objects
        """
        logger.info(
            "collector.repository.started",
            min_discovery_score=min_discovery_score,
            limit=limit,
        )
        start_time = time.time()

        # Over-fetch so denylist skips still leave enough for analysis
        fetch_limit = max(limit * 3, limit)
        rows = repo.get_unprocessed_raw_projects(
            min_discovery_score=min_discovery_score,
            limit=fetch_limit,
        )

        records: list[dict] = []
        noise_skipped = 0
        for row in rows:
            if len(records) >= limit:
                break
            raw_data = json.loads(row["raw_data"]) if row["raw_data"] else {}
            source_id = row["source_id"]
            name = raw_data.get("name", "") or ""
            sector = raw_data.get("sector")
            if is_noise_raw_project(name, sector, raw_data):
                noise_skipped += 1
                # Prefer same DB connection as repository (in-memory tests)
                repo_conn = getattr(repo, "_conn", None)
                try:
                    from app.quarantine import quarantine_raw

                    ok = quarantine_raw(
                        row["raw_id"],
                        f"denylist:{source_id}:{name[:80]}",
                        conn=repo_conn,
                    )
                    if not ok:
                        repo.mark_raw_project_processed(
                            raw_id=row["raw_id"],
                            project_id=row.get("project_id"),
                        )
                except Exception as e:
                    try:
                        repo.mark_raw_project_processed(
                            raw_id=row["raw_id"],
                            project_id=row.get("project_id"),
                        )
                    except Exception as e2:
                        logger.warning(
                            "collector.noise_mark_failed",
                            raw_id=row.get("raw_id"),
                            error=str(e2),
                        )
                    logger.warning(
                        "collector.quarantine_failed",
                        raw_id=row.get("raw_id"),
                        error=str(e),
                    )
                logger.info(
                    "collector.noise_quarantined",
                    name=name,
                    source_id=source_id,
                    raw_id=row.get("raw_id"),
                )
                continue

            flags = self._infer_airdrop_flags(source_id, raw_data)
            dedup = create_dedup_key(name, sector)
            project_id = row.get("project_id") or generate_deterministic_id(dedup)
            records.append(
                {
                    "project_id": project_id,
                    "raw_id": row["raw_id"],
                    "name": name,
                    "url": raw_data.get("url") or raw_data.get("homepage"),
                    "sector": normalize_sector(sector) if sector else None,
                    "stage": raw_data.get("stage") or flags.get("stage"),
                    "source": source_id,
                    "has_testnet": flags["has_testnet"],
                    "has_points_program": flags["has_points_program"],
                    "no_token_yet": flags["no_token_yet"],
                    "recent_funding": flags["recent_funding"],
                    "has_docs": flags.get("has_docs", False),
                    "has_whitepaper": flags.get("has_whitepaper", False),
                    "has_roadmap": flags.get("has_roadmap", False),
                    "has_github": flags.get("has_github", False),
                    "has_twitter": flags.get("has_twitter", False),
                    "has_discord": flags.get("has_discord", False),
                    "github_stars": flags.get("github_stars") or 0,
                    "github_recent_push_days": flags.get("github_recent_push_days"),
                    "explicit_airdrop_mention": flags.get("explicit_airdrop_mention", False),
                    "tvl_usd": flags.get("tvl_usd"),
                    "description": flags.get("description"),
                    "has_task_portal": flags.get("has_task_portal", False),
                    "has_contract": flags.get("has_contract", False),
                    "source_count": flags.get("source_count") or 1,
                    "roadmap_delivery": flags.get("roadmap_delivery") or "unknown",
                    "sybil_friction": flags.get("sybil_friction") or "unknown",
                    "funding_total_usd": flags.get("funding_total_usd"),
                    "funding_rounds": flags.get("funding_rounds") or 0,
                    "funding_last_date": flags.get("funding_last_date"),
                    "funding_investors": flags.get("funding_investors") or [],
                    "funding_lead_investors": flags.get("funding_lead_investors") or [],
                    "funding_tier": flags.get("funding_tier") or "unknown",
                    "funding_quality": flags.get("funding_quality") or 0,
                    "discovery_score": row["discovery_score"],
                    "auto_discovered": True,
                    "discovered_at": datetime.fromisoformat(row["discovered_at"]) if row["discovered_at"] else None,
                    "_dedup_key": dedup,
                }
            )

        projects = self._dedup_records(records)
        duration_ms = (time.time() - start_time) * 1000
        logger.info(
            "collector.repository.completed",
            input_count=len(rows),
            output_count=len(projects),
            noise_skipped=noise_skipped,
            deduped=len(records) - len(projects),
            duration_ms=round(duration_ms, 2),
        )
        return projects

    async def run(self, state: PipelineState) -> PipelineState:
        """Execute collector logic.

        Note: In normal pipeline flow, Collector runs once per batch,
        not per project. This method signature matches BaseAgent contract
        but Collector should be invoked differently in Orchestrator.

        For now, returns state unchanged (actual collection happens
        in Orchestrator's collect_projects() method).
        """
        self._log_start(state)
        start_time = time.time()

        try:
            # Collector doesn't modify individual project state
            # It runs once to produce the list of projects
            # This is here to satisfy BaseAgent contract
            pass

        except Exception as e:
            error = AgentError(
                agent_name=self.name, kind="collection_error", message=str(e), project_id=state.project.id
            )
            state.add_error(error)

        duration_ms = (time.time() - start_time) * 1000
        self._log_complete(state, duration_ms)

        return state

    def collect_from_seed(self, seed_projects: list[dict]) -> list[RawProject]:
        """Collect projects from seed data.

        Args:
            seed_projects: List of seed project dicts

        Returns:
            List of RawProject with deduplication applied

        Example seed_projects format:
        [
            {
                "name": "LayerX",
                "url": "https://layerx.xyz",
                "sector": "L2",
                "stage": "testnet",
                "has_testnet": True,
                "has_points_program": True,
                "no_token_yet": True,
            }
        ]
        """
        logger.info("collector.seed.started", count=len(seed_projects))
        start_time = time.time()

        records = [self._raw_to_record(raw) for raw in seed_projects]
        results = self._dedup_records(records)

        duration_ms = (time.time() - start_time) * 1000
        logger.info(
            "collector.seed.completed",
            input_count=len(seed_projects),
            output_count=len(results),
            deduped=len(seed_projects) - len(results),
            duration_ms=round(duration_ms, 2),
        )

        return results


if __name__ == "__main__":
    # Test collector
    import asyncio

    async def test():
        print("=== Testing Collector Agent ===\n")

        # Create test seed data with duplicates
        seed_data = [
            {
                "name": "LayerX",
                "url": "https://layerx.xyz",
                "sector": "L2",
                "stage": "testnet",
                "source": "seed",
                "has_testnet": True,
                "has_points_program": True,
                "no_token_yet": True,
            },
            {
                "name": "Layer-X Finance",  # Duplicate (different format)
                "url": "https://layer-x.com",
                "sector": "layer2",  # Different format
                "stage": "testnet",
                "source": "defillama",
                "has_testnet": True,
            },
            {
                "name": "UniswapX",
                "url": "https://uniswap.org",
                "sector": "DEX",
                "stage": "mainnet",
                "source": "cryptorank",
            },
        ]

        collector = CollectorAgent()
        projects = collector.collect_from_seed(seed_data)

        print(f"Input: {len(seed_data)} projects")
        print(f"Output: {len(projects)} projects (after dedup)\n")

        for p in projects:
            print(f"✓ {p.name}")
            print(f"  ID: {p.id}")
            print(f"  Sector: {p.sector}")
            print(f"  Source: {p.source}")
            print(f"  Signals: testnet={p.has_testnet}, points={p.has_points_program}")
            print()

        # Verify deduplication
        if len(projects) != 2:
            raise RuntimeError("Should dedupe LayerX variants")
        layerx = next(p for p in projects if "layer" in p.name.lower())
        if layerx.source != "seed,defillama":
            raise RuntimeError("Should merge sources")

        print("✓ All tests passed!")

    asyncio.run(test())
