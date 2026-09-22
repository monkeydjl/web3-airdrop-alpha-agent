"""Tests for Team Studio Manager."""

from app.services.team_studio_manager import (
    assign_task_to_operator,
    get_team_studio_dashboard,
    register_or_update_operator,
)


def test_get_team_studio_dashboard() -> None:
    data = get_team_studio_dashboard()
    assert "summary" in data
    assert data["summary"]["active_operators_count"] >= 3
    assert data["summary"]["total_managed_wallets"] >= 50
    assert len(data["operators"]) >= 3
    assert len(data["assigned_tasks"]) >= 3


def test_assign_task_to_operator() -> None:
    res = assign_task_to_operator(
        title="Monad Testnet Faucet Batch",
        project="Monad",
        operator_id="op_alice",
        target_wallet_count=20,
        priority="high",
    )
    assert res["success"] is True
    assert res["task"]["operator_id"] == "op_alice"
    assert res["task"]["priority"] == "high"


def test_register_or_update_operator() -> None:
    # Update existing
    res = register_or_update_operator(
        operator_id="op_alice",
        name="Alice (Promoted Lead)",
        role="Studio Lead",
        assigned_wallets=25,
    )
    assert res["action"] == "updated"
    assert res["operator"]["name"] == "Alice (Promoted Lead)"

    # Create new
    res_new = register_or_update_operator(
        operator_id="op_david",
        name="David (Junior)",
        role="Operator",
        assigned_wallets=10,
    )
    assert res_new["action"] == "created"
    assert res_new["operator"]["operator_id"] == "op_david"
