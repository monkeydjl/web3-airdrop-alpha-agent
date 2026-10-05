"""Tests for alpha_dossier service."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from app.services.alpha_dossier import _format_usd, generate_alpha_dossier


def test_format_usd():
    assert _format_usd(None) == "未公开"
    assert _format_usd(0) == "未公开 / 0"
    assert _format_usd(-50) == "未公开 / 0"
    assert _format_usd("invalid") == "未公开"
    assert _format_usd(500) == "$500.00"
    assert _format_usd(5_000) == "$5.0K"
    assert _format_usd(15_500_000) == "$15.50M"
    assert _format_usd(2_500_000_000) == "$2.50B"


def test_generate_alpha_dossier_not_found():
    with patch("app.services.alpha_dossier.ProjectRepository") as mock_repo_cls:
        mock_repo = MagicMock()
        mock_repo.get_by_id.return_value = None
        mock_repo_cls.return_value = mock_repo

        with pytest.raises(ValueError, match="Project not found"):
            generate_alpha_dossier("nonexistent-id")


def test_generate_alpha_dossier_full_flow():
    mock_project = {
        "id": "proj-1",
        "name": "AlphaTestProject",
        "url": "https://alphatest.xyz",
        "sector": "defi",
        "stage": "testnet",
        "score": 88,
        "label": "FARM",
        "confidence": 0.85,
        "reason": json.dumps(["High testnet participation", "Strong TVL growth"]),
        "source": "defillama",
        "meta": json.dumps(
            {
                "signals": {
                    "funding_total_usd": 25_000_000,
                    "funding_rounds": 2,
                    "funding_tier": "tier_1",
                    "funding_investors": ["Paradigm", "a16z"],
                    "funding_last_date": "2026-01-01",
                    "has_points_program": True,
                    "has_testnet": True,
                    "farming_days": 180,
                    "season_count": 2,
                    "tge_transparency": "announced",
                    "lockup_days": 30,
                    "gas_spent_usd": 5.0,
                    "tvl_deposited_usd": 0.0,
                    "github_inactive_days": 10,
                    "interaction_contract": "0x1234567890abcdef1234567890abcdef12345678",
                }
            }
        ),
    }

    with (
        patch("app.services.alpha_dossier.ProjectRepository") as mock_repo_cls,
        patch("app.services.alpha_dossier.list_faucets_with_status") as mock_faucets,
        patch("app.services.script_forge.generate_interaction_scripts") as mock_scripts,
    ):
        mock_repo = MagicMock()
        mock_repo.get_by_id.return_value = mock_project
        mock_repo_cls.return_value = mock_repo

        mock_faucets.return_value = [
            {
                "name": "Sepolia Faucet",
                "chain_name": "Ethereum Sepolia",
                "url": "https://sepoliafaucet.com",
                "cooldown_hours": 24,
            }
        ]
        mock_scripts.return_value = {
            "scripts": {
                "foundry_cast": 'cast send 0x1234567890abcdef1234567890abcdef12345678 "mint()" --private-key $PRIVATE_KEY'
            }
        }

        dossier = generate_alpha_dossier("proj-1")

        assert dossier["project_id"] == "proj-1"
        assert dossier["project_name"] == "AlphaTestProject"
        assert "Alpha 深度投研研报: AlphaTestProject" in dossier["markdown"]
        assert "AlphaTestProject" in dossier["markdown"]
        assert "Sepolia Faucet" in dossier["markdown"]
        assert "cast send 0x1234" in dossier["markdown"]
        assert dossier["summary"]["score"] == 88
        assert dossier["summary"]["label"] == "FARM"
        assert dossier["summary"]["tasks_count"] > 0


def test_generate_alpha_dossier_no_contract_and_watch_label():
    mock_project = {
        "id": "proj-2",
        "name": "WatchProject",
        "url": "",
        "sector": "infra",
        "stage": "mainnet",
        "score": 60,
        "label": "WATCH",
        "confidence": 0.6,
        "reason": "Single reason text",
        "source": "manual",
        "meta": json.dumps(
            {
                "signals": {
                    "funding_total_usd": 0,
                    "farming_days": 400,
                    "github_inactive_days": 200,
                }
            }
        ),
    }

    with patch("app.services.alpha_dossier.ProjectRepository") as mock_repo_cls:
        mock_repo = MagicMock()
        mock_repo.get_by_id.return_value = mock_project
        mock_repo_cls.return_value = mock_repo

        dossier = generate_alpha_dossier("proj-2")

        assert dossier["project_id"] == "proj-2"
        assert dossier["summary"]["label"] == "WATCH"
        assert "重点观察" in dossier["markdown"]
        assert "未登记可信的目标交互合约地址" in dossier["markdown"]
