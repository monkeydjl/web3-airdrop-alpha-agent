"""Tests for normalization and deduplication utilities.

Reference:
- backend/app/utils/normalize.py
- ENGINEERING_ROADMAP.md §6.2.1
"""

from datetime import UTC

import pytest

from app.utils.normalize import (
    DedupKey,
    create_dedup_key,
    generate_deterministic_id,
    get_source_priority,
    merge_raw_records,
    merge_sources,
    normalize_name,
    normalize_sector,
)


class TestNormalizeName:
    """Test name normalization."""

    def test_lowercase(self):
        """Test conversion to lowercase."""
        assert normalize_name("LayerX") == "layerx"
        assert normalize_name("LAYERX") == "layerx"

    def test_remove_spaces(self):
        """Test space removal."""
        assert normalize_name("Layer X") == "layerx"
        assert normalize_name("Layer  X") == "layerx"

    def test_remove_hyphens(self):
        """Test hyphen removal."""
        assert normalize_name("Layer-X") == "layerx"
        assert normalize_name("Layer--X") == "layerx"

    def test_remove_suffixes(self):
        """Test suffix removal."""
        assert normalize_name("LayerX Protocol") == "layerx"
        assert normalize_name("LayerX Finance") == "layerx"
        assert normalize_name("LayerX Network") == "layerx"
        assert normalize_name("LayerX DAO") == "layerx"

    def test_multiple_operations(self):
        """Test multiple normalization operations."""
        assert normalize_name("Layer-X Protocol") == "layerx"
        assert normalize_name("LAYER X FINANCE") == "layerx"

    def test_unicode_normalization(self):
        """Test Unicode normalization."""
        # Should handle different Unicode representations
        result = normalize_name("Café")
        assert result == "café"

    def test_empty_string(self):
        """Test empty string handling."""
        assert normalize_name("") == ""

    def test_preserves_core_name(self):
        """Test that core name is preserved."""
        assert normalize_name("Uniswap") == "uniswap"
        assert normalize_name("Aave") == "aave"


class TestNormalizeSector:
    """Test sector normalization."""

    def test_l2_variants(self):
        """Test Layer 2 variants."""
        assert normalize_sector("L2") == "L2"
        assert normalize_sector("layer2") == "L2"
        assert normalize_sector("Layer 2") == "L2"
        assert normalize_sector("layer-2") == "L2"

    def test_restaking_variants(self):
        """Test Restaking variants."""
        assert normalize_sector("Restaking") == "Restaking"
        assert normalize_sector("restake") == "Restaking"
        assert normalize_sector("re-staking") == "Restaking"

    def test_defi_variants(self):
        """Test DeFi variants."""
        assert normalize_sector("DeFi") == "DeFi"
        assert normalize_sector("defi") == "DeFi"
        assert normalize_sector("de-fi") == "DeFi"

    def test_gaming_variants(self):
        """Test Gaming variants."""
        assert normalize_sector("Gaming") == "Gaming"
        assert normalize_sector("game") == "Gaming"

    def test_unknown_sector(self):
        """Test unknown sector handling."""
        result = normalize_sector("UnknownSector")
        # Should return capitalized unknown sector
        assert result == "Unknownsector"

    def test_none_sector(self):
        """Test None sector handling."""
        # Returns "Unknown" for None
        assert normalize_sector(None) == "Unknown"

    def test_empty_sector(self):
        """Test empty sector handling."""
        # Returns "Unknown" for empty string
        assert normalize_sector("") == "Unknown"


class TestCreateDedupKey:
    """Test deduplication key creation."""

    def test_basic_key_creation(self):
        """Test basic dedup key creation."""
        key = create_dedup_key("LayerX", "L2")

        assert isinstance(key, DedupKey)
        assert key.name_key == "layerx"
        assert key.sector_key == "L2"

    def test_key_with_normalization(self):
        """Test key with name/sector normalization."""
        key = create_dedup_key("Layer-X Protocol", "layer2")

        assert key.name_key == "layerx"
        assert key.sector_key == "L2"

    def test_key_to_string(self):
        """Test converting key to string."""
        key = create_dedup_key("LayerX", "L2")
        key_str = key.to_string()

        assert key_str == "layerx::L2"

    def test_none_sector(self):
        """Test key creation with None sector."""
        key = create_dedup_key("LayerX", None)

        assert key.name_key == "layerx"
        assert key.sector_key == "Unknown"  # None becomes "Unknown"

    def test_empty_name(self):
        """Test key creation with empty name."""
        key = create_dedup_key("", "L2")

        assert key.name_key == ""
        assert key.sector_key == "L2"


class TestGenerateDeterministicId:
    """Test deterministic UUID generation."""

    def test_same_key_same_id(self):
        """Test that same key generates same ID."""
        key = create_dedup_key("LayerX", "L2")

        id1 = generate_deterministic_id(key)
        id2 = generate_deterministic_id(key)

        assert id1 == id2

    def test_different_keys_different_ids(self):
        """Test that different keys generate different IDs."""
        key1 = create_dedup_key("LayerX", "L2")
        key2 = create_dedup_key("LayerY", "L2")

        id1 = generate_deterministic_id(key1)
        id2 = generate_deterministic_id(key2)

        assert id1 != id2

    def test_id_format(self):
        """Test that generated ID is valid UUID format."""
        key = create_dedup_key("LayerX", "L2")
        project_id = generate_deterministic_id(key)

        # Should be valid UUID string format
        assert isinstance(project_id, str)
        assert len(project_id) > 0
        # Try parsing as UUID (will raise if invalid)
        import uuid

        uuid.UUID(project_id)

    def test_normalization_produces_same_id(self):
        """Test that normalized names produce same ID."""
        key1 = create_dedup_key("LayerX", "L2")
        key2 = create_dedup_key("Layer-X Protocol", "layer2")

        id1 = generate_deterministic_id(key1)
        id2 = generate_deterministic_id(key2)

        assert id1 == id2


class TestGetSourcePriority:
    """Test source priority logic."""

    def test_seed_highest_priority(self):
        """Test that seed has highest priority (lowest number)."""
        assert get_source_priority("seed") < get_source_priority("defillama")
        assert get_source_priority("seed") < get_source_priority("cryptorank")
        assert get_source_priority("seed") < get_source_priority("twitter")

    def test_priority_order(self):
        """Test complete priority order."""
        seed = get_source_priority("seed")
        defillama = get_source_priority("defillama")
        cryptorank = get_source_priority("cryptorank")
        twitter = get_source_priority("twitter")

        assert seed < defillama < cryptorank < twitter

    def test_unknown_source(self):
        """Test unknown source priority."""
        unknown = get_source_priority("unknown_source")
        twitter = get_source_priority("twitter")

        # Unknown should be lowest priority (highest number)
        assert unknown > twitter


class TestMergeSources:
    """Test source merging logic."""

    def test_single_source(self):
        """Test merging single source."""
        result = merge_sources(["seed"])
        assert result == "seed"

    def test_multiple_sources(self):
        """Test merging multiple sources."""
        result = merge_sources(["seed", "defillama", "cryptorank"])
        assert result == "seed,defillama,cryptorank"

    def test_duplicate_sources_removed(self):
        """Test that duplicate sources are removed."""
        result = merge_sources(["seed", "seed", "defillama"])
        assert result == "seed,defillama"

    def test_sources_sorted_by_priority(self):
        """Test that sources are sorted by priority."""
        result = merge_sources(["twitter", "seed", "cryptorank"])
        assert result == "seed,cryptorank,twitter"

    def test_empty_source_list(self):
        """Test merging empty source list."""
        result = merge_sources([])
        assert result == ""


class TestDedupKeyComparison:
    """Test DedupKey comparison and hashing."""

    def test_key_equality(self):
        """Test that equal keys are equal."""
        key1 = create_dedup_key("LayerX", "L2")
        key2 = create_dedup_key("LayerX", "L2")

        assert key1.to_string() == key2.to_string()

    def test_key_inequality_name(self):
        """Test that keys with different names are not equal."""
        key1 = create_dedup_key("LayerX", "L2")
        key2 = create_dedup_key("LayerY", "L2")

        assert key1.to_string() != key2.to_string()

    def test_key_inequality_sector(self):
        """Test that keys with different sectors are not equal."""
        key1 = create_dedup_key("LayerX", "L2")
        key2 = create_dedup_key("LayerX", "DeFi")

        assert key1.to_string() != key2.to_string()


class TestIntegration:
    """Integration tests for normalization pipeline."""

    def test_full_normalization_pipeline(self):
        """Test complete normalization and dedup key generation."""
        # Different representations of same project
        variants = [
            ("LayerX", "L2"),
            ("Layer-X", "layer2"),
            ("Layer X Protocol", "Layer 2"),
            ("LAYERX FINANCE", "l2"),
        ]

        keys = [create_dedup_key(name, sector) for name, sector in variants]
        ids = [generate_deterministic_id(key) for key in keys]

        # All should generate same ID
        assert len(set(ids)) == 1

    def test_different_projects_different_keys(self):
        """Test that different projects generate different keys."""
        projects = [
            ("LayerX", "L2"),
            ("LayerY", "L2"),
            ("LayerX", "DeFi"),
        ]

        keys = [create_dedup_key(name, sector) for name, sector in projects]
        key_strs = [key.to_string() for key in keys]

        # All should be different
        assert len(set(key_strs)) == 3

    def test_realistic_dedup_scenario(self):
        """Test realistic deduplication scenario."""
        # Simulate data from different sources
        projects = [
            {
                "name": "LayerX Protocol",
                "sector": "layer2",
                "source": "defillama",
            },
            {
                "name": "Layer-X",
                "sector": "L2",
                "source": "seed",
            },
            {
                "name": "RestakeDAO",
                "sector": "restaking",
                "source": "cryptorank",
            },
        ]

        # Create dedup keys
        keys_with_source = []
        for p in projects:
            key = create_dedup_key(p["name"], p["sector"])
            keys_with_source.append((key, p["source"]))

        # Group by dedup key
        dedup_map = {}
        for key, source in keys_with_source:
            key_str = key.to_string()
            if key_str not in dedup_map:
                dedup_map[key_str] = []
            dedup_map[key_str].append(source)

        # Should have 2 unique projects
        assert len(dedup_map) == 2

        # LayerX should have merged sources
        layerx_key = create_dedup_key("LayerX", "L2").to_string()
        assert len(dedup_map[layerx_key]) == 2


class TestMergeRawRecords:
    """Test merge_raw_records helper used by CollectorAgent."""

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            merge_raw_records([])

    def test_single_record_returns_itself(self):
        rec = {"name": "LayerX", "source": "seed", "has_testnet": True}
        merged = merge_raw_records([rec])
        assert merged["name"] == "LayerX"
        assert merged["source"] == "seed"
        assert merged["has_testnet"] is True

    def test_manual_priority_over_auto(self):
        records = [
            {"name": "LayerX", "source": "defillama", "url": "https://defillama.com"},
            {"name": "LayerX", "source": "manual", "url": "https://layerx.xyz"},
        ]
        merged = merge_raw_records(records)
        assert merged["source"] == "manual,defillama"
        # Primary record is manual, so URL comes from manual
        assert merged["url"] == "https://layerx.xyz"

    def test_boolean_signals_or(self):
        records = [
            {"name": "LayerX", "source": "defillama", "has_testnet": True},
            {"name": "LayerX", "source": "github", "has_points_program": True},
        ]
        merged = merge_raw_records(records)
        assert merged["has_testnet"] is True
        assert merged["has_points_program"] is True

    def test_discovery_score_max(self):
        records = [
            {"name": "LayerX", "source": "defillama", "discovery_score": 0.4},
            {"name": "LayerX", "source": "twitter", "discovery_score": 0.8},
        ]
        merged = merge_raw_records(records)
        assert merged["discovery_score"] == 0.8

    def test_auto_discovered_any_true(self):
        records = [
            {"name": "LayerX", "source": "manual", "auto_discovered": False},
            {"name": "LayerX", "source": "defillama", "auto_discovered": True},
        ]
        merged = merge_raw_records(records)
        assert merged["auto_discovered"] is True

    def test_discovers_at_earliest(self):
        from datetime import datetime

        t1 = datetime(2026, 1, 1, tzinfo=UTC)
        t2 = datetime(2026, 1, 2, tzinfo=UTC)
        records = [
            {"name": "LayerX", "source": "defillama", "discovered_at": t2},
            {"name": "LayerX", "source": "manual", "discovered_at": t1},
        ]
        merged = merge_raw_records(records)
        assert merged["discovered_at"] == t1


class TestNoTokenYetMergeSemantics:
    """no_token_yet 按 AND 合并：任一 token 状态源看到代币即判已发币（2026-09 修复）。

    此前它混在 _MERGE_BOOL_OR 里，defillama 子条目的"没看到代币"
    （no_token_yet=True）会覆盖 coingecko 的已上市确认，让已发币项目以
    pre-TGE 身份绕过 eligibility veto。
    """

    def test_token_status_source_confirms_listed_wins(self):
        records = [
            {"name": "X", "source": "defillama", "no_token_yet": True},
            {"name": "X", "source": "coingecko", "no_token_yet": False},
        ]
        merged = merge_raw_records(records)
        assert merged["no_token_yet"] is False

    def test_all_token_status_sources_agree_pre_tge(self):
        records = [
            {"name": "X", "source": "defillama", "no_token_yet": True},
            {"name": "X", "source": "rootdata", "no_token_yet": True},
        ]
        merged = merge_raw_records(records)
        assert merged["no_token_yet"] is True

    def test_text_sources_are_neutral(self):
        """文本类来源的 no_token_yet 是"正文没提"翻平出的缺省值，不参与投票。"""
        records = [
            {"name": "X", "source": "defillama", "no_token_yet": True},
            {"name": "X", "source": "medium", "no_token_yet": False},
            {"name": "X", "source": "twitter", "no_token_yet": False},
        ]
        merged = merge_raw_records(records)
        assert merged["no_token_yet"] is True

    def test_manual_assertion_still_overrides(self):
        records = [
            {"name": "X", "source": "coingecko", "no_token_yet": False},
            {"name": "X", "source": "manual", "no_token_yet": True},
        ]
        merged = merge_raw_records(records)
        assert merged["no_token_yet"] is True

    def test_no_token_status_sources_keeps_primary(self):
        """没有 token 状态源投票时，保持 primary 记录的取值。"""
        records = [
            {"name": "X", "source": "medium", "no_token_yet": True},
            {"name": "X", "source": "twitter", "no_token_yet": False},
        ]
        merged = merge_raw_records(records)
        # primary 是优先级最高的 medium；无投票 → 不改写
        assert merged["no_token_yet"] is True
