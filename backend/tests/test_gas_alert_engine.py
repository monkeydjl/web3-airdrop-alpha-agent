import sqlite3

import pytest

from app.services.gas_alert_engine import (
    create_rule,
    delete_rule,
    evaluate_active_alerts,
    get_all_rules,
    reset_rules_to_default,
    toggle_rule,
)


@pytest.fixture
def db_conn() -> sqlite3.Connection:
    """每条用例独立 :memory: 库；ensure 的 seed 逻辑负责播种默认规则."""
    conn = sqlite3.connect(":memory:")
    yield conn
    conn.close()


def test_rule_crud(db_conn: sqlite3.Connection) -> None:
    initial = get_all_rules(db_conn)
    assert len(initial) >= 4  # 默认规则由 ensure seed 播种

    # Create
    new_r = create_rule("polygon", "below", 25.0, "Polygon Cheap Gas", conn=db_conn)
    assert new_r["chain"] == "polygon"
    assert new_r["condition"] == "below"
    assert new_r["threshold_gwei"] == 25.0

    # Toggle
    toggled = toggle_rule(new_r["id"], False, conn=db_conn)
    assert toggled is not None
    assert toggled["enabled"] is False

    # Delete
    assert delete_rule(new_r["id"], conn=db_conn) is True
    assert delete_rule("non-existent-rule-id", conn=db_conn) is False


def test_default_rules_seeded_once_and_persist(tmp_path) -> None:
    """默认规则只在空表播种一次，且跨连接存活（模拟重启）."""
    import sqlite3 as _sqlite3

    db_file = tmp_path / "gas_rules.db"
    first = _sqlite3.connect(str(db_file))
    try:
        rules = get_all_rules(first)
        assert len(rules) >= 4
        # 再次 ensure 不重复播种
        rules_again = get_all_rules(first)
        assert rules_again == rules
    finally:
        first.close()

    second = _sqlite3.connect(str(db_file))
    try:
        rules_reopened = get_all_rules(second)
        assert len(rules_reopened) >= 4
        assert {r["id"] for r in rules_reopened} == {r["id"] for r in rules}
    finally:
        second.close()


def test_evaluate_active_alerts_with_real_shape(db_conn: sqlite3.Connection) -> None:
    """钉住与 get_all_chains_gas_summary() 一致的真实契约。

    历史 bug：此处曾喂 {"data": {chain: {"gas_gwei"}}} 的错误形态，
    恰好匹配实现里同样错误的读取路径，生产告警永远为空却测试全绿。
    """
    real_shape = {
        "ok": True,
        "chains": {
            "ethereum": {"gwei": 9.5, "status": "cheap"},
            "arbitrum": {"gwei": 0.08, "status": "cheap"},
            "base": {"gwei": 0.004, "status": "cheap"},
        },
    }

    # In default rules:
    # - rule-eth-low: condition below 12.0 Gwei -> 9.5 <= 12.0 (triggers!)
    # - rule-eth-high: condition above 35.0 Gwei -> 9.5 not >= 35.0
    # - rule-base-low: condition below 0.01 Gwei -> 0.004 <= 0.01 (triggers!)
    alerts = evaluate_active_alerts(real_shape, conn=db_conn)
    assert len(alerts) >= 2

    triggered_chains = [a["chain"] for a in alerts]
    assert "ethereum" in triggered_chains
    assert "base" in triggered_chains


def test_evaluate_active_alerts_ignores_disabled_rules(db_conn: sqlite3.Connection) -> None:
    """禁用的规则即使满足阈值条件也不应触发."""
    real_shape = {"ok": True, "chains": {"ethereum": {"gwei": 9.5}}}
    rules_before = {a["rule_id"] for a in evaluate_active_alerts(real_shape, conn=db_conn)}
    assert "rule-eth-low" in rules_before

    assert toggle_rule("rule-eth-low", False, conn=db_conn) is not None
    rules_after = {a["rule_id"] for a in evaluate_active_alerts(real_shape, conn=db_conn)}
    assert "rule-eth-low" not in rules_after


def test_evaluate_active_alerts_default_summary_matches_engine(db_conn: sqlite3.Connection) -> None:
    """集成口径：不传自定义 summary 时，引擎必须能消费真实的 gas 概览形态."""
    from app.services.gas_tracker import get_all_chains_gas_summary

    alerts = evaluate_active_alerts(get_all_chains_gas_summary(), conn=db_conn)
    # 只断言可运行且返回列表；触发与否取决于实时 gas，不在此处断言具体内容
    assert isinstance(alerts, list)
    for alert in alerts:
        assert {"rule_id", "chain", "current_gwei", "condition"} <= set(alert)


def test_reset_rules_to_default(db_conn: sqlite3.Connection) -> None:
    create_rule("polygon", "below", 25.0, "Extra", conn=db_conn)
    assert len(get_all_rules(db_conn)) >= 5

    reset_rules_to_default(db_conn)
    rules = get_all_rules(db_conn)
    assert len(rules) >= 4
    assert not any(r["label"] == "Extra" for r in rules)
    assert all(r["chain"] in {"ethereum", "arbitrum", "base"} for r in rules)
