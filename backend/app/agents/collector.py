"""Collector Agent - Data collection and deduplication.

Collects projects from multiple sources, normalizes names/sectors,
deduplicates across sources, and generates deterministic UUIDs.

Reference:
- ENGINEERING_ROADMAP.md §6.2 Collector
- TASK_BREAKDOWN.md W2-03
"""

import time
from typing import List

import structlog

from app.agents.base import BaseAgent, PipelineState, RawProject, AgentError
from app.utils.normalize import (
    create_dedup_key,
    generate_deterministic_id,
    get_source_priority,
    merge_sources,
)

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
                agent_name=self.name,
                kind="collection_error",
                message=str(e),
                project_id=state.project.id
            )
            state.add_error(error)

        duration_ms = (time.time() - start_time) * 1000
        self._log_complete(state, duration_ms)

        return state

    def collect_from_seed(self, seed_projects: List[dict]) -> List[RawProject]:
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
        logger.info(
            "collector.seed.started",
            count=len(seed_projects)
        )

        # Step 1: Normalize and assign dedup keys
        projects_with_keys = []
        for raw in seed_projects:
            dedup_key = create_dedup_key(
                raw.get("name", ""),
                raw.get("sector")
            )

            projects_with_keys.append({
                "raw": raw,
                "dedup_key": dedup_key,
                "source": raw.get("source", "seed"),
            })

        # Step 2: Deduplicate (group by dedup_key)
        dedup_map = {}
        for item in projects_with_keys:
            key_str = item["dedup_key"].to_string()

            if key_str not in dedup_map:
                dedup_map[key_str] = []

            dedup_map[key_str].append(item)

        # Step 3: Resolve conflicts and create RawProject
        results = []
        for key_str, items in dedup_map.items():
            # Sort by source priority (seed > defillama > cryptorank > twitter)
            items_sorted = sorted(
                items,
                key=lambda x: get_source_priority(x["source"])
            )

            # Take primary record (highest priority)
            primary = items_sorted[0]
            raw = primary["raw"]

            # Merge sources
            all_sources = [item["source"] for item in items]
            merged_source = merge_sources(all_sources)

            # Generate deterministic UUID
            project_id = generate_deterministic_id(primary["dedup_key"])

            # Create RawProject
            project = RawProject(
                id=project_id,
                name=raw.get("name", ""),
                url=raw.get("url"),
                sector=raw.get("sector"),
                stage=raw.get("stage"),
                source=merged_source,
                has_testnet=raw.get("has_testnet", False),
                has_points_program=raw.get("has_points_program", False),
                no_token_yet=raw.get("no_token_yet", False),
                recent_funding=raw.get("recent_funding", False),
            )

            results.append(project)

            # Log deduplication
            if len(items) > 1:
                logger.info(
                    "collector.dedup",
                    project_id=project_id,
                    name=project.name,
                    dedup_key=key_str,
                    sources=merged_source,
                    duplicates=len(items)
                )

        logger.info(
            "collector.seed.completed",
            input_count=len(seed_projects),
            output_count=len(results),
            deduped=len(seed_projects) - len(results)
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
        assert len(projects) == 2, "Should dedupe LayerX variants"
        layerx = [p for p in projects if "layer" in p.name.lower()][0]
        assert layerx.source == "seed,defillama", "Should merge sources"

        print("✓ All tests passed!")

    asyncio.run(test())
