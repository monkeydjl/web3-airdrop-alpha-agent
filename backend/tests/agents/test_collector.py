"""Tests for Collector Agent.

Reference:
- backend/app/agents/collector.py
- ENGINEERING_ROADMAP.md §6.2
"""

import pytest

from app.agents.collector import CollectorAgent
from app.agents.base import RawProject, PipelineState, AgentContext


@pytest.fixture
def collector():
    """Collector agent fixture."""
    return CollectorAgent()


@pytest.fixture
def sample_seed_data():
    """Sample seed data for testing."""
    return [
        {
            "name": "LayerX",
            "url": "https://layerx.xyz",
            "sector": "L2",
            "stage": "testnet",
            "source": "seed",
            "has_testnet": True,
            "has_points_program": True,
            "no_token_yet": True,
            "recent_funding": True,
        },
        {
            "name": "RestakeDAO",
            "url": "https://restakedao.xyz",
            "sector": "Restaking",
            "stage": "mainnet",
            "source": "seed",
            "has_testnet": False,
            "has_points_program": True,
            "no_token_yet": True,
        },
    ]


class TestCollectorAgent:
    """Test Collector Agent creation and basic flow."""

    def test_agent_creation(self, collector):
        """Test collector can be created."""
        assert collector.name == "collector"

    @pytest.mark.asyncio
    async def test_run_method_exists(self, collector):
        """Test run method exists (even if no-op for now)."""
        project = RawProject(
            id="test-001",
            name="TestProject",
            sector="L2",
            stage="testnet",
            source="seed",
        )
        context = AgentContext(run_id="test-run")
        state = PipelineState(project=project, context=context)

        # Should not raise
        result_state = await collector.run(state)
        assert result_state is not None


class TestCollectFromSeed:
    """Test collect_from_seed method."""

    def test_collect_basic(self, collector, sample_seed_data):
        """Test basic collection from seed data."""
        projects = collector.collect_from_seed(sample_seed_data)

        assert len(projects) == 2
        assert all(isinstance(p, RawProject) for p in projects)

    def test_collect_preserves_fields(self, collector, sample_seed_data):
        """Test that all fields are preserved."""
        projects = collector.collect_from_seed(sample_seed_data)
        layerx = projects[0]

        assert layerx.name == "LayerX"
        assert layerx.url == "https://layerx.xyz"
        assert layerx.sector == "L2"
        assert layerx.stage == "testnet"
        assert layerx.source == "seed"
        assert layerx.has_testnet is True
        assert layerx.has_points_program is True
        assert layerx.no_token_yet is True
        assert layerx.recent_funding is True

    def test_collect_empty_list(self, collector):
        """Test collecting from empty list."""
        projects = collector.collect_from_seed([])
        assert projects == []

    def test_collect_minimal_fields(self, collector):
        """Test collecting with minimal required fields."""
        minimal_data = [
            {
                "name": "MinimalProject",
            }
        ]

        projects = collector.collect_from_seed(minimal_data)
        assert len(projects) == 1

        project = projects[0]
        assert project.name == "MinimalProject"
        assert project.url is None
        assert project.sector is None
        assert project.stage is None
        assert project.has_testnet is False
        assert project.has_points_program is False


class TestDeduplication:
    """Test deduplication logic."""

    def test_exact_duplicates(self, collector):
        """Test exact duplicate removal."""
        data = [
            {
                "name": "LayerX",
                "sector": "L2",
                "source": "seed",
            },
            {
                "name": "LayerX",
                "sector": "L2",
                "source": "defillama",
            },
        ]

        projects = collector.collect_from_seed(data)
        assert len(projects) == 1
        assert projects[0].source == "seed,defillama"

    def test_case_insensitive_dedup(self, collector):
        """Test case-insensitive deduplication."""
        data = [
            {
                "name": "LayerX",
                "sector": "L2",
                "source": "seed",
            },
            {
                "name": "layerx",
                "sector": "L2",
                "source": "defillama",
            },
        ]

        projects = collector.collect_from_seed(data)
        assert len(projects) == 1

    def test_name_variant_dedup(self, collector):
        """Test deduplication of name variants."""
        data = [
            {
                "name": "Layer X",
                "sector": "L2",
                "source": "seed",
            },
            {
                "name": "Layer-X",
                "sector": "L2",
                "source": "defillama",
            },
            {
                "name": "LayerX Protocol",
                "sector": "L2",
                "source": "cryptorank",
            },
        ]

        projects = collector.collect_from_seed(data)
        assert len(projects) == 1
        assert "seed" in projects[0].source
        assert "defillama" in projects[0].source
        assert "cryptorank" in projects[0].source

    def test_sector_normalization_dedup(self, collector):
        """Test deduplication with sector normalization."""
        data = [
            {
                "name": "LayerX",
                "sector": "L2",
                "source": "seed",
            },
            {
                "name": "LayerX",
                "sector": "layer2",
                "source": "defillama",
            },
        ]

        projects = collector.collect_from_seed(data)
        assert len(projects) == 1

    def test_different_projects_not_deduped(self, collector):
        """Test that different projects are not deduped."""
        data = [
            {
                "name": "LayerX",
                "sector": "L2",
                "source": "seed",
            },
            {
                "name": "LayerY",
                "sector": "L2",
                "source": "seed",
            },
        ]

        projects = collector.collect_from_seed(data)
        assert len(projects) == 2

    def test_same_name_different_sector_not_deduped(self, collector):
        """Test that same name but different sector are not deduped."""
        data = [
            {
                "name": "Phoenix",
                "sector": "L2",
                "source": "seed",
            },
            {
                "name": "Phoenix",
                "sector": "DeFi",
                "source": "seed",
            },
        ]

        projects = collector.collect_from_seed(data)
        assert len(projects) == 2


class TestSourcePriority:
    """Test source priority and merging."""

    def test_seed_has_highest_priority(self, collector):
        """Test that seed source has highest priority."""
        data = [
            {
                "name": "LayerX",
                "url": "https://cryptorank.com",
                "sector": "L2",
                "source": "cryptorank",
            },
            {
                "name": "LayerX",
                "url": "https://layerx.xyz",
                "sector": "L2",
                "source": "seed",
            },
        ]

        projects = collector.collect_from_seed(data)
        assert len(projects) == 1
        # Should use seed URL (higher priority)
        assert projects[0].url == "https://layerx.xyz"

    def test_source_merging(self, collector):
        """Test that sources are merged correctly."""
        data = [
            {
                "name": "LayerX",
                "sector": "L2",
                "source": "seed",
            },
            {
                "name": "LayerX",
                "sector": "L2",
                "source": "defillama",
            },
            {
                "name": "LayerX",
                "sector": "L2",
                "source": "cryptorank",
            },
        ]

        projects = collector.collect_from_seed(data)
        assert len(projects) == 1
        assert "seed" in projects[0].source
        assert "defillama" in projects[0].source
        assert "cryptorank" in projects[0].source


class TestDeterministicIds:
    """Test deterministic UUID generation."""

    def test_same_project_same_id(self, collector):
        """Test that same project gets same ID across runs."""
        data = [
            {
                "name": "LayerX",
                "sector": "L2",
                "source": "seed",
            }
        ]

        projects1 = collector.collect_from_seed(data)
        projects2 = collector.collect_from_seed(data)

        assert projects1[0].id == projects2[0].id

    def test_different_projects_different_ids(self, collector):
        """Test that different projects get different IDs."""
        data = [
            {
                "name": "LayerX",
                "sector": "L2",
                "source": "seed",
            },
            {
                "name": "LayerY",
                "sector": "L2",
                "source": "seed",
            },
        ]

        projects = collector.collect_from_seed(data)
        assert projects[0].id != projects[1].id

    def test_id_stability_with_dedup(self, collector):
        """Test that ID remains stable when deduplicating."""
        data1 = [
            {
                "name": "LayerX",
                "sector": "L2",
                "source": "seed",
            }
        ]

        data2 = [
            {
                "name": "LayerX",
                "sector": "L2",
                "source": "seed",
            },
            {
                "name": "Layer-X",
                "sector": "L2",
                "source": "defillama",
            },
        ]

        projects1 = collector.collect_from_seed(data1)
        projects2 = collector.collect_from_seed(data2)

        # Should get same ID whether or not there are duplicates
        assert projects1[0].id == projects2[0].id


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_missing_name_handled(self, collector):
        """Test handling of missing name field."""
        data = [
            {
                "sector": "L2",
                "source": "seed",
            }
        ]

        projects = collector.collect_from_seed(data)
        assert len(projects) == 1
        assert projects[0].name == ""

    def test_none_values_handled(self, collector):
        """Test handling of None values."""
        data = [
            {
                "name": "Project",
                "url": None,
                "sector": None,
                "stage": None,
                "source": "seed",
            }
        ]

        projects = collector.collect_from_seed(data)
        assert len(projects) == 1
        assert projects[0].url is None
        assert projects[0].sector is None
        assert projects[0].stage is None

    def test_large_batch(self, collector):
        """Test collecting large batch of projects."""
        data = [
            {
                "name": f"Project{i}",
                "sector": "L2",
                "source": "seed",
            }
            for i in range(100)
        ]

        projects = collector.collect_from_seed(data)
        assert len(projects) == 100

    def test_all_duplicates(self, collector):
        """Test when all projects are duplicates."""
        data = [
            {
                "name": "LayerX",
                "sector": "L2",
                "source": f"source{i}",
            }
            for i in range(10)
        ]

        projects = collector.collect_from_seed(data)
        assert len(projects) == 1


class TestIntegration:
    """Integration tests for Collector Agent."""

    def test_realistic_scenario(self, collector):
        """Test realistic multi-source collection scenario."""
        data = [
            # Seed data (highest priority)
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
            # DeFiLlama variant
            {
                "name": "Layer-X Protocol",
                "url": "https://defillama.com/protocol/layerx",
                "sector": "layer2",
                "stage": "testnet",
                "source": "defillama",
            },
            # Completely different project
            {
                "name": "RestakeDAO",
                "url": "https://restakedao.xyz",
                "sector": "Restaking",
                "stage": "mainnet",
                "source": "cryptorank",
                "has_points_program": True,
            },
        ]

        projects = collector.collect_from_seed(data)

        # Should dedupe LayerX variants, keep RestakeDAO
        assert len(projects) == 2

        # Find LayerX
        layerx = [p for p in projects if "layer" in p.name.lower()][0]
        assert layerx.url == "https://layerx.xyz"  # Seed URL wins
        assert "seed" in layerx.source
        assert "defillama" in layerx.source

        # Find RestakeDAO
        restake = [p for p in projects if "restake" in p.name.lower()][0]
        assert restake.sector == "Restaking"
        assert restake.source == "cryptorank"
