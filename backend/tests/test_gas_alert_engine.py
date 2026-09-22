import pytest
from app.services.gas_alert_engine import (
    get_all_rules,
    create_rule,
    delete_rule,
    toggle_rule,
    reset_rules_to_default,
    evaluate_active_alerts,
)


@pytest.fixture(autouse=True)
def setup_rules():
    reset_rules_to_default()
    yield
    reset_rules_to_default()


def test_rule_crud():
    initial = get_all_rules()
    assert len(initial) >= 4

    # Create
    new_r = create_rule("polygon", "below", 25.0, "Polygon Cheap Gas")
    assert new_r["chain"] == "polygon"
    assert new_r["condition"] == "below"
    assert new_r["threshold_gwei"] == 25.0

    # Toggle
    toggled = toggle_rule(new_r["id"], False)
    assert toggled is not None
    assert toggled["enabled"] is False

    # Delete
    deleted = delete_rule(new_r["id"])
    assert deleted is True
    assert delete_rule("non-existent-rule-id") is False


def test_evaluate_active_alerts_mocked():
    mock_gas = {
        "ok": True,
        "data": {
            "ethereum": {"gas_gwei": 9.5, "network_status": "optimal"},
            "arbitrum": {"gas_gwei": 0.08, "network_status": "busy"},
            "base": {"gas_gwei": 0.004, "network_status": "optimal"},
        }
    }

    # In default rules:
    # - rule-eth-low: condition below 12.0 Gwei -> 9.5 <= 12.0 (triggers!)
    # - rule-eth-high: condition above 35.0 Gwei -> 9.5 not >= 35.0
    # - rule-base-low: condition below 0.01 Gwei -> 0.004 <= 0.01 (triggers!)
    alerts = evaluate_active_alerts(mock_gas)
    assert len(alerts) >= 2

    triggered_chains = [a["chain"] for a in alerts]
    assert "ethereum" in triggered_chains
    assert "base" in triggered_chains
