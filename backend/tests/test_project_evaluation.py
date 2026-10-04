"""Tests for project_evaluation service."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.project_evaluation import evaluate_single_project


@pytest.mark.asyncio
async def test_evaluate_single_project_not_found():
    with patch("app.services.project_evaluation.ProjectRepository") as mock_repo_cls:
        mock_repo = MagicMock()
        mock_repo.get_by_id.return_value = None
        mock_repo_cls.return_value = mock_repo

        with pytest.raises(ValueError, match="Project not found"):
            await evaluate_single_project("nonexistent-id")


@pytest.mark.asyncio
async def test_evaluate_single_project_success():
    mock_project = {
        "id": "proj-1",
        "name": "SingleEvalTest",
        "url": "https://test.io",
        "sector": "infra",
        "stage": "testnet",
        "source": "defillama,cryptorank",
        "meta": json.dumps(
            {
                "signals": {
                    "has_testnet": True,
                    "no_token_yet": False,  # Should be preserved
                    "explicit_no_airdrop": True,  # Should be preserved
                    "github_stars": 120,
                }
            }
        ),
    }

    updated_mock_project = {
        **mock_project,
        "score": 85,
        "label": "FARM",
        "confidence": 0.9,
    }

    mock_state = MagicMock()
    mock_state.score = 85
    mock_state.label = "FARM"
    mock_state.confidence = 0.9

    with (
        patch("app.services.project_evaluation.ProjectRepository") as mock_repo_cls,
        patch("app.services.project_evaluation.SimpleOrchestrator") as mock_orch_cls,
        patch("app.services.project_evaluation.OpportunityService") as mock_opp_cls,
    ):
        mock_repo = MagicMock()
        mock_repo.get_by_id.side_effect = [mock_project, updated_mock_project]
        mock_repo_cls.return_value = mock_repo

        mock_orch = MagicMock()
        mock_orch._run_single_project = AsyncMock(return_value=mock_state)
        mock_orch_cls.return_value = mock_orch

        mock_opp_service = MagicMock()
        mock_opp_cls.return_value.__enter__.return_value = mock_opp_service

        res = await evaluate_single_project("proj-1")

        assert res["id"] == "proj-1"
        assert res["score"] == 85
        assert res["label"] == "FARM"
        mock_repo.save.assert_called_once_with(mock_state)
        mock_opp_service.evaluate.assert_called_once_with("proj-1", persist=True)


@pytest.mark.asyncio
async def test_evaluate_single_project_opp_service_failure_is_resilient():
    """OpportunityService 异常不应中断整体评估流程。"""
    mock_project = {
        "id": "proj-2",
        "name": "ResilientEvalTest",
        "url": "https://resilient.io",
        "sector": "defi",
        "stage": "mainnet",
        "source": "manual",
        "meta": json.dumps({"signals": {}}),
    }

    updated_mock_project = {
        **mock_project,
        "score": 70,
        "label": "WATCH",
    }

    mock_state = MagicMock()
    mock_state.score = 70
    mock_state.label = "WATCH"

    with (
        patch("app.services.project_evaluation.ProjectRepository") as mock_repo_cls,
        patch("app.services.project_evaluation.SimpleOrchestrator") as mock_orch_cls,
        patch("app.services.project_evaluation.OpportunityService") as mock_opp_cls,
    ):
        mock_repo = MagicMock()
        mock_repo.get_by_id.side_effect = [mock_project, updated_mock_project]
        mock_repo_cls.return_value = mock_repo

        mock_orch = MagicMock()
        mock_orch._run_single_project = AsyncMock(return_value=mock_state)
        mock_orch_cls.return_value = mock_orch

        # 模拟 OpportunityService 抛出异常
        mock_opp_cls.side_effect = RuntimeError("Opportunity DB lock")

        res = await evaluate_single_project("proj-2")

        assert res["id"] == "proj-2"
        assert res["score"] == 70
        mock_repo.save.assert_called_once_with(mock_state)


@pytest.mark.asyncio
async def test_evaluate_single_project_reload_failed():
    mock_project = {
        "id": "proj-3",
        "name": "ReloadFailTest",
        "url": "https://test.io",
        "sector": "infra",
        "stage": "mainnet",
        "source": "defillama",
        "meta": json.dumps({}),
    }

    mock_state = MagicMock()
    mock_state.score = 75
    mock_state.label = "FARM"

    with (
        patch("app.services.project_evaluation.ProjectRepository") as mock_repo_cls,
        patch("app.services.project_evaluation.SimpleOrchestrator") as mock_orch_cls,
        patch("app.services.project_evaluation.OpportunityService"),
    ):
        mock_repo = MagicMock()
        # 第一次成功加载，第二次重载返回 None 模拟异常
        mock_repo.get_by_id.side_effect = [mock_project, None]
        mock_repo_cls.return_value = mock_repo

        mock_orch = MagicMock()
        mock_orch._run_single_project = AsyncMock(return_value=mock_state)
        mock_orch_cls.return_value = mock_orch

        with pytest.raises(RuntimeError, match="Failed to reload updated project"):
            await evaluate_single_project("proj-3")
