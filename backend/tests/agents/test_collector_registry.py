"""Tests for CollectorAgent integration with registry and repository.

Reference:
- backend/app/agents/collector.py
- backend/app/collectors/registry.py
"""

import json
import sqlite3
from datetime import UTC, datetime

import pytest

from app.agents.collector import CollectorAgent
from app.collectors.base import CollectorResult, DataCollector, RawDiscovery
from app.collectors.persistence import CollectionRepository
from app.collectors.registry import CollectorRegistry
from app.db import init_db


class FakeCollector(DataCollector):
    """Test-only collector that returns predefined discoveries."""

    def __init__(self, source_id: str, items: list[RawDiscovery] | None = None):
        super().__init__(source_id, source_id)
        self._items = items or []
        self._enabled = True

    @property
    def source_type(self) -> str:
        return "api"

    def is_enabled(self) -> bool:
        return self._enabled

    async def collect(self) -> CollectorResult:
        return CollectorResult(
            source_id=self.source_id,
            status="success",
            items=self._items,
        )


def discovery(
    source_id: str,
    name: str,
    sector: str | None = "DeFi",
    stage: str = "testnet",
    score: float = 0.5,
    signals: dict[str, bool] | None = None,
) -> RawDiscovery:
    """Build a RawDiscovery for tests."""
    signals = signals or {}
    return RawDiscovery(
        source_id=source_id,
        raw_id=f"{source_id}-{name}",
        name=name,
        url=f"https://{name.lower()}.xyz",
        sector=sector,
        stage=stage,
        raw_data={
            "name": name,
            "url": f"https://{name.lower()}.xyz",
            "sector": sector,
            "stage": stage,
            **signals,
        },
        discovery_score=score,
        discovered_at=datetime.now(UTC),
    )


@pytest.fixture
def collector():
    return CollectorAgent()


@pytest.mark.asyncio
class TestCollectFromRegistry:
    async def test_registry_collects_enabled_collectors(self, collector):
        fake = FakeCollector(
            "defillama",
            items=[discovery("defillama", "NovaLayer")],
        )
        registry = CollectorRegistry()
        registry.register(fake)

        projects = await collector.collect_from_registry(registry)

        assert len(projects) == 1
        assert projects[0].name == "NovaLayer"
        assert projects[0].source == "defillama"
        assert projects[0].auto_discovered is True

    async def test_registry_skips_disabled_collectors(self, collector):
        enabled = FakeCollector(
            "defillama",
            items=[discovery("defillama", "NovaLayer")],
        )
        disabled = FakeCollector(
            "github",
            items=[discovery("github", "NovaLayer")],
        )
        disabled._enabled = False

        registry = CollectorRegistry()
        registry.register(enabled)
        registry.register(disabled)

        projects = await collector.collect_from_registry(registry)
        assert len(projects) == 1
        assert projects[0].source == "defillama"

    async def test_registry_dedupes_across_sources(self, collector):
        defi = FakeCollector(
            "defillama",
            items=[discovery("defillama", "NovaLayer", sector="L2")],
        )
        github = FakeCollector(
            "github",
            items=[discovery("github", "NovaLayer", sector="L2")],
        )

        registry = CollectorRegistry()
        registry.register(defi)
        registry.register(github)

        projects = await collector.collect_from_registry(registry)
        assert len(projects) == 1
        assert "defillama" in projects[0].source
        assert "github" in projects[0].source

    async def test_registry_persists_to_repository(self, collector):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        init_db(conn)
        repo = CollectionRepository(conn)

        fake = FakeCollector(
            "defillama",
            items=[discovery("defillama", "NovaLayer")],
        )
        registry = CollectorRegistry()
        registry.register(fake)

        projects = await collector.collect_from_registry(registry, repo=repo)

        assert len(projects) == 1
        cursor = conn.execute(
            "SELECT COUNT(*) FROM raw_projects WHERE source_id = ?",
            ("defillama",),
        )
        assert cursor.fetchone()[0] == 1
        conn.close()

    async def test_registry_ignores_collector_error(self, collector):
        class ErrorCollector(DataCollector):
            def __init__(self):
                super().__init__("error", "error")

            @property
            def source_type(self) -> str:
                return "api"

            async def collect(self) -> CollectorResult:
                raise RuntimeError("API down")

        good = FakeCollector(
            "defillama",
            items=[discovery("defillama", "NovaLayer")],
        )
        registry = CollectorRegistry()
        registry.register(good)
        registry.register(ErrorCollector())

        projects = await collector.collect_from_registry(registry)
        assert len(projects) == 1


class TestCollectFromRepository:
    def test_repository_loads_unprocessed_projects(self, collector):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        init_db(conn)
        repo = CollectionRepository(conn)

        raw_data = json.dumps(
            {
                "name": "NovaLayer",
                "url": "https://novalayer.xyz",
                "sector": "L2",
                "stage": "testnet",
            }
        )
        conn.execute(
            """
            INSERT INTO raw_projects (raw_id, source_id, dedup_key, raw_data, discovered_at, discovery_score)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("r1", "defillama", "novalayer::l2", raw_data, datetime.now(UTC).isoformat(), 0.6),
        )
        conn.commit()

        projects = collector.collect_from_repository(repo)

        assert len(projects) == 1
        assert projects[0].name == "NovaLayer"
        assert projects[0].source == "defillama"
        assert projects[0].auto_discovered is True
        conn.close()

    def test_repository_filters_by_discovery_score(self, collector):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        init_db(conn)
        repo = CollectionRepository(conn)

        for idx, score in enumerate([0.2, 0.5, 0.9]):
            raw_data = json.dumps({"name": f"Project{idx}", "sector": "L2"})
            conn.execute(
                """
                INSERT INTO raw_projects (raw_id, source_id, dedup_key, raw_data, discovered_at, discovery_score)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (f"r{idx}", "defillama", f"project{idx}::l2", raw_data, datetime.now(UTC).isoformat(), score),
            )
        conn.commit()

        projects = collector.collect_from_repository(repo, min_discovery_score=0.4)
        assert len(projects) == 2
        assert all(p.discovery_score >= 0.4 for p in projects)
        conn.close()

    def test_repository_dedupes_and_merges(self, collector):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        init_db(conn)
        repo = CollectionRepository(conn)

        for source_id in ["defillama", "github"]:
            raw_data = json.dumps({"name": "NovaLayer", "sector": "L2", "has_testnet": True})
            conn.execute(
                """
                INSERT INTO raw_projects (raw_id, source_id, dedup_key, raw_data, discovered_at, discovery_score)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (f"r-{source_id}", source_id, "novalayer::l2", raw_data, datetime.now(UTC).isoformat(), 0.5),
            )
        conn.commit()

        projects = collector.collect_from_repository(repo)
        assert len(projects) == 1
        conn.close()
        assert "defillama" in projects[0].source
        assert "github" in projects[0].source
