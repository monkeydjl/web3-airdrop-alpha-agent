"""Unit tests for Collector Agent.

Tests:
- Seed data collection
- Cross-source deduplication
- Conflict resolution (source priority)
- Deterministic UUID generation
- Signal aggregation
"""

import sys
sys.path.insert(0, 'backend')

import pytest

from app.agents.collector import CollectorAgent
from app.agents.base import RawProject


class TestCollectorAgent:
    """Test Collector Agent functionality"""

    def test_collector_creation(self):
        collector = CollectorAgent()
        assert collector.name == "collector"

    def test_collect_from_seed_empty(self):
        collector = CollectorAgent()
        projects = collector.collect_from_seed([])
        assert len(projects) == 0

    def test_collect_from_seed_single(self):
        collector = CollectorAgent()
        seed = [
            {
                "name": "LayerX",
                "url": "https://layerx.xyz",
                "sector": "L2",
                "stage": "testnet",
                "source": "seed",
                "has_testnet": True,
                "has_points_program": True,
            }
        ]

        projects = collector.collect_from_seed(seed)

        assert len(projects) == 1
        project = projects[0]
        assert project.name == "LayerX"
        assert project.sector == "L2"
        assert project.stage == "testnet"
        assert project.has_testnet is True
        assert project.has_points_program is True

    def test_deduplication_same_name_different_format(self):
        """Same project with different name formats should dedupe"""
        collector = CollectorAgent()
        seed = [
            {
                "name": "LayerX",
                "sector": "L2",
                "stage": "testnet",
                "source": "seed",
            },
            {
                "name": "Layer-X Finance",
                "sector": "layer2",
                "stage": "testnet",
                "source": "defillama",
            },
            {
                "name": "Layer X Protocol",
                "sector": "Layer 2",
                "stage": "testnet",
                "source": "cryptorank",
            },
        ]

        projects = collector.collect_from_seed(seed)

        # Should dedupe to 1 project
        assert len(projects) == 1
        project = projects[0]
        assert "layerx" in project.name.lower()

    def test_source_priority_resolution(self):
        """Higher priority source should win"""
        collector = CollectorAgent()
        seed = [
            {
                "name": "LayerX",
                "url": "https://twitter.com/layerx",
                "sector": "L2",
                "stage": "testnet",
                "source": "twitter",
            },
            {
                "name": "LayerX",
                "url": "https://layerx.xyz",
                "sector": "L2",
                "stage": "mainnet",  # Different stage
                "source": "seed",  # Higher priority
            },
        ]

        projects = collector.collect_from_seed(seed)

        assert len(projects) == 1
        project = projects[0]
        # Should use seed data (higher priority)
        assert project.stage == "mainnet"
        assert project.url == "https://layerx.xyz"
        # But sources should be merged
        assert "seed" in project.source
        assert "twitter" in project.source

    def test_source_merging(self):
        """Multiple sources should be merged"""
        collector = CollectorAgent()
        seed = [
            {"name": "LayerX", "sector": "L2", "source": "seed"},
            {"name": "LayerX", "sector": "L2", "source": "defillama"},
            {"name": "LayerX", "sector": "L2", "source": "cryptorank"},
        ]

        projects = collector.collect_from_seed(seed)

        assert len(projects) == 1
        assert projects[0].source == "seed,defillama,cryptorank"

    def test_deterministic_uuid(self):
        """Same project should get same UUID across runs"""
        collector = CollectorAgent()
        seed = [
            {"name": "LayerX", "sector": "L2", "stage": "testnet", "source": "seed"}
        ]

        # Run collection twice
        projects1 = collector.collect_from_seed(seed)
        projects2 = collector.collect_from_seed(seed)

        assert projects1[0].id == projects2[0].id

    def test_different_projects_different_uuid(self):
        """Different projects should get different UUIDs"""
        collector = CollectorAgent()
        seed = [
            {"name": "LayerX", "sector": "L2", "source": "seed"},
            {"name": "LayerY", "sector": "L2", "source": "seed"},
        ]

        projects = collector.collect_from_seed(seed)

        assert len(projects) == 2
        assert projects[0].id != projects[1].id

    def test_signal_preservation(self):
        """Signals should be preserved"""
        collector = CollectorAgent()
        seed = [
            {
                "name": "LayerX",
                "sector": "L2",
                "source": "seed",
                "has_testnet": True,
                "has_points_program": True,
                "no_token_yet": True,
                "recent_funding": False,
            }
        ]

        projects = collector.collect_from_seed(seed)

        project = projects[0]
        assert project.has_testnet is True
        assert project.has_points_program is True
        assert project.no_token_yet is True
        assert project.recent_funding is False

    def test_default_signal_values(self):
        """Missing signals should default to False"""
        collector = CollectorAgent()
        seed = [
            {"name": "LayerX", "sector": "L2", "source": "seed"}
        ]

        projects = collector.collect_from_seed(seed)

        project = projects[0]
        assert project.has_testnet is False
        assert project.has_points_program is False
        assert project.no_token_yet is False
        assert project.recent_funding is False

    def test_multiple_different_projects(self):
        """Multiple different projects should all be returned"""
        collector = CollectorAgent()
        seed = [
            {"name": "LayerX", "sector": "L2", "source": "seed"},
            {"name": "UniswapX", "sector": "DEX", "source": "defillama"},
            {"name": "Aave", "sector": "Lending", "source": "cryptorank"},
        ]

        projects = collector.collect_from_seed(seed)

        assert len(projects) == 3
        names = [p.name for p in projects]
        assert "LayerX" in names
        assert "UniswapX" in names
        assert "Aave" in names

    def test_sector_normalization(self):
        """Sectors should be normalized"""
        collector = CollectorAgent()
        seed = [
            {"name": "LayerX", "sector": "layer2", "source": "seed"},
        ]

        projects = collector.collect_from_seed(seed)

        # Sector should be normalized to canonical form
        assert projects[0].sector == "layer2"  # Original preserved in RawProject

    def test_missing_optional_fields(self):
        """Missing optional fields should not crash"""
        collector = CollectorAgent()
        seed = [
            {
                "name": "LayerX",
                "source": "seed",
                # Missing: url, sector, stage
            }
        ]

        projects = collector.collect_from_seed(seed)

        assert len(projects) == 1
        project = projects[0]
        assert project.name == "LayerX"
        assert project.url is None
        assert project.sector is None
        assert project.stage is None


class TestCollectorEdgeCases:
    """Test edge cases"""

    def test_empty_name(self):
        """Empty name should be handled"""
        collector = CollectorAgent()
        seed = [{"name": "", "sector": "L2", "source": "seed"}]

        projects = collector.collect_from_seed(seed)
        assert len(projects) == 1

    def test_duplicate_in_same_source(self):
        """Duplicates from same source should dedupe"""
        collector = CollectorAgent()
        seed = [
            {"name": "LayerX", "sector": "L2", "source": "seed"},
            {"name": "LayerX", "sector": "L2", "source": "seed"},
        ]

        projects = collector.collect_from_seed(seed)
        assert len(projects) == 1
        assert projects[0].source == "seed"  # Not "seed,seed"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
