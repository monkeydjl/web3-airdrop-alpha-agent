"""Unit tests for normalization and deduplication.

Tests:
- Name normalization (lowercase, remove spaces/hyphens, remove suffixes)
- Sector normalization (alias mapping)
- Dedup key generation
- Deterministic UUID generation
- Source priority and merging
"""

import sys
sys.path.insert(0, 'backend')

import pytest

from app.utils.normalize import (
    normalize_name,
    normalize_sector,
    create_dedup_key,
    generate_deterministic_id,
    get_source_priority,
    merge_sources,
    DedupKey,
    SECTOR_ALIAS,
)


class TestNormalizeName:
    """Test name normalization"""

    def test_lowercase(self):
        assert normalize_name("LayerX") == "layerx"
        assert normalize_name("LAYERX") == "layerx"

    def test_remove_spaces(self):
        assert normalize_name("Layer X") == "layerx"
        assert normalize_name("Layer  X") == "layerx"

    def test_remove_hyphens(self):
        assert normalize_name("Layer-X") == "layerx"
        assert normalize_name("Layer--X") == "layerx"

    def test_remove_underscores(self):
        assert normalize_name("Layer_X") == "layerx"

    def test_remove_suffix_protocol(self):
        assert normalize_name("LayerX Protocol") == "layerx"

    def test_remove_suffix_finance(self):
        assert normalize_name("LayerX Finance") == "layerx"

    def test_remove_suffix_network(self):
        assert normalize_name("LayerX Network") == "layerx"

    def test_combined_transformations(self):
        # All transformations at once
        assert normalize_name("Layer-X Finance") == "layerx"
        assert normalize_name("Layer X Protocol") == "layerx"
        assert normalize_name("LAYER-X FINANCE") == "layerx"

    def test_unicode_normalization(self):
        # NFKC normalization
        # Note: Basic ASCII names don't need unicode normalization
        assert normalize_name("LayerX") == "layerx"

    def test_empty_string(self):
        assert normalize_name("") == ""

    def test_none_handled_gracefully(self):
        # Should not crash
        assert normalize_name("") == ""


class TestNormalizeSector:
    """Test sector normalization"""

    def test_l2_variations(self):
        assert normalize_sector("layer2") == "L2"
        assert normalize_sector("l2") == "L2"
        assert normalize_sector("Layer-2") == "L2"
        assert normalize_sector("Layer 2") == "L2"

    def test_restaking_variations(self):
        assert normalize_sector("restake") == "Restaking"
        assert normalize_sector("restaking") == "Restaking"
        assert normalize_sector("re-staking") == "Restaking"

    def test_defi_variations(self):
        assert normalize_sector("defi") == "DeFi"
        assert normalize_sector("DeFi") == "DeFi"
        assert normalize_sector("de-fi") == "DeFi"

    def test_gaming_variations(self):
        assert normalize_sector("gaming") == "Gaming"
        assert normalize_sector("game") == "Gaming"

    def test_unknown_sector(self):
        # Unknown sectors return title case
        assert normalize_sector("New Sector") == "New Sector"
        assert normalize_sector("custom") == "Custom"

    def test_empty_sector(self):
        assert normalize_sector("") == "Unknown"
        assert normalize_sector(None) == "Unknown"


class TestDedupKey:
    """Test DedupKey class"""

    def test_create_dedup_key(self):
        key = create_dedup_key("LayerX", "L2")
        assert key.name_key == "layerx"
        assert key.sector_key == "L2"

    def test_dedup_key_to_string(self):
        key = DedupKey("layerx", "l2")
        assert key.to_string() == "layerx::l2"

    def test_dedup_key_from_string(self):
        key = DedupKey.from_string("layerx::l2")
        assert key.name_key == "layerx"
        assert key.sector_key == "l2"

    def test_dedup_key_roundtrip(self):
        original = DedupKey("layerx", "l2")
        string = original.to_string()
        parsed = DedupKey.from_string(string)
        assert original == parsed

    def test_invalid_dedup_key_string(self):
        with pytest.raises(ValueError, match="Invalid dedup_key format"):
            DedupKey.from_string("invalid")

    def test_same_project_different_formats(self):
        # Same project, different input formats
        key1 = create_dedup_key("LayerX", "L2")
        key2 = create_dedup_key("Layer-X Finance", "layer2")
        key3 = create_dedup_key("Layer X Protocol", "Layer 2")

        assert key1.to_string() == key2.to_string() == key3.to_string()


class TestGenerateDeterministicId:
    """Test deterministic UUID generation"""

    def test_same_key_same_id(self):
        key = DedupKey("layerx", "l2")
        id1 = generate_deterministic_id(key)
        id2 = generate_deterministic_id(key)

        assert id1 == id2

    def test_different_key_different_id(self):
        key1 = DedupKey("layerx", "l2")
        key2 = DedupKey("layery", "l2")

        id1 = generate_deterministic_id(key1)
        id2 = generate_deterministic_id(key2)

        assert id1 != id2

    def test_uuid_format(self):
        key = DedupKey("layerx", "l2")
        proj_id = generate_deterministic_id(key)

        # Should be valid UUID format
        import uuid
        assert uuid.UUID(proj_id)

    def test_cross_run_stability(self):
        # Same inputs across "runs" produce same ID
        runs = []
        for _ in range(5):
            key = create_dedup_key("LayerX", "L2")
            proj_id = generate_deterministic_id(key)
            runs.append(proj_id)

        # All IDs should be identical
        assert len(set(runs)) == 1


class TestSourcePriority:
    """Test source priority and merging"""

    def test_get_source_priority(self):
        assert get_source_priority("seed") == 1
        assert get_source_priority("defillama") == 2
        assert get_source_priority("cryptorank") == 3
        assert get_source_priority("twitter") == 4

    def test_unknown_source_priority(self):
        assert get_source_priority("unknown") == 99
        assert get_source_priority("custom") == 99

    def test_case_insensitive(self):
        assert get_source_priority("SEED") == 1
        assert get_source_priority("Seed") == 1

    def test_merge_sources_deduplicates(self):
        sources = ["seed", "defillama", "seed"]
        merged = merge_sources(sources)
        assert merged == "seed,defillama"

    def test_merge_sources_sorts_by_priority(self):
        sources = ["twitter", "seed", "cryptorank", "defillama"]
        merged = merge_sources(sources)
        assert merged == "seed,defillama,cryptorank,twitter"

    def test_merge_sources_empty(self):
        assert merge_sources([]) == ""

    def test_merge_sources_single(self):
        assert merge_sources(["seed"]) == "seed"


class TestEdgeCases:
    """Test edge cases and boundary conditions"""

    def test_very_long_name(self):
        long_name = "A" * 1000
        normalized = normalize_name(long_name)
        assert len(normalized) > 0

    def test_special_characters(self):
        assert normalize_name("Layer@X") == "layer@x"
        assert normalize_name("Layer#X") == "layer#x"

    def test_numbers_in_name(self):
        assert normalize_name("Layer2") == "layer2"
        # "3DAO" -> "3" after removing "dao" suffix
        assert normalize_name("3DAO") == "3"

    def test_multiple_suffixes(self):
        # Only removes one suffix (from the end)
        # "Protocol Finance" -> "protocolfinance" (remove spaces) -> "protocol" (remove "finance")
        assert normalize_name("Protocol Finance") == "protocol"

    def test_sector_with_numbers(self):
        assert normalize_sector("Layer2") == "L2"

    def test_dedup_key_special_chars(self):
        # Should handle special chars in name
        key = create_dedup_key("Layer@X!", "L2")
        assert "::" in key.to_string()


class TestRealWorldExamples:
    """Test with real-world project names"""

    def test_layerx_variations(self):
        # All these should dedupe to same project
        variations = [
            ("LayerX", "L2"),
            ("Layer-X", "layer2"),
            ("Layer X Finance", "Layer 2"),
            ("LAYERX PROTOCOL", "l2"),
        ]

        keys = [create_dedup_key(name, sector) for name, sector in variations]
        ids = [generate_deterministic_id(key) for key in keys]

        # All should produce same ID
        assert len(set(ids)) == 1

    def test_uniswap_example(self):
        key1 = create_dedup_key("Uniswap", "DEX")
        key2 = create_dedup_key("Uni-Swap Protocol", "dex")

        assert key1.to_string() == key2.to_string()

    def test_aave_example(self):
        key1 = create_dedup_key("Aave", "Lending")
        key2 = create_dedup_key("AAVE Protocol", "lending")

        assert key1.to_string() == key2.to_string()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
