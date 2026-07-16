"""Participation checklist generation tests."""

from app.services.participation_tasks import generate_participation_tasks


def test_testnet_and_portal_generate_core_tasks():
    data = generate_participation_tasks(
        {
            "id": "p1",
            "name": "QuestNet",
            "url": "https://questnet.xyz",
            "label": "FARM",
            "stage": "testnet",
            "has_testnet": True,
            "has_points_program": True,
            "no_token_yet": True,
            "has_task_portal": True,
            "has_discord": True,
            "has_twitter": True,
            "has_docs": True,
            "has_github": True,
            "sybil_friction": "low",
        }
    )
    ids = {t["id"] for t in data["tasks"]}
    assert "official-task-portal" in ids
    assert "testnet-faucet-and-tx" in ids
    assert "social-discord-join" in ids
    assert "track-log-interaction" in ids
    assert data["summary"]["total"] >= 5
    assert any(t["required"] for t in data["tasks"])


def test_ignore_sparse_project_has_deprioritize():
    data = generate_participation_tasks(
        {
            "id": "p2",
            "name": "Ghost",
            "label": "IGNORE",
            "stage": "ideation",
            "no_token_yet": True,
        }
    )
    ids = {t["id"] for t in data["tasks"]}
    assert "track-deprioritize" in ids or "official-watch-announcement" in ids
