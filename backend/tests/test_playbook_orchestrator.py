"""Tests for Playbook Orchestrator & Script Studio."""

from app.services.playbook_orchestrator import (
    list_playbook_templates,
    validate_and_generate_playbook_script,
)


def test_list_playbook_templates() -> None:
    templates = list_playbook_templates()
    assert len(templates) >= 3
    ids = [t["id"] for t in templates]
    assert "playbook_scroll_marks" in ids
    assert "playbook_monad_testnet" in ids


def test_validate_and_generate_scroll_playbook() -> None:
    res = validate_and_generate_playbook_script(
        playbook_id="playbook_scroll_marks",
        jitter_range_seconds=(45, 120),
    )
    assert res["step_count"] == 4
    assert res["total_estimated_gas_usd"] > 0
    assert "Scroll Marks" in res["title"]
    assert "random.uniform(45, 120)" in res["executable_code"]
    assert "0x6f26Bf09B1C792e3228e5467807a900A503c0281" in res["executable_code"]


def test_validate_and_generate_custom_steps() -> None:
    custom_steps = [
        {"action": "swap", "title": "Swap ETH to USDC", "contract": "0x1111", "gas_usd": 0.2},
        {"action": "stake", "title": "Stake USDC", "contract": "0x2222", "gas_usd": 0.4},
    ]
    res = validate_and_generate_playbook_script(
        custom_title="Custom 2-Step Flow",
        custom_steps=custom_steps,
    )
    assert res["step_count"] == 2
    assert res["total_estimated_gas_usd"] == 0.6
    assert "Custom 2-Step Flow" in res["executable_code"]
