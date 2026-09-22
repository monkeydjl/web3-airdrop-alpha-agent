"""Unit tests for Smart Money Radar Service and API."""

from app.services.smart_money_radar import get_smart_money_and_social_feed


def test_get_smart_money_and_social_feed():
    """验证获取聪明钱动态与社交讨论暴增榜."""
    feed = get_smart_money_and_social_feed()
    assert feed["ok"] is True
    assert len(feed["smart_money_activities"]) > 0
    assert len(feed["social_velocity_spikes"]) > 0

    first_act = feed["smart_money_activities"][0]
    assert "whale_label" in first_act
    assert "target_project" in first_act
    assert "insight" in first_act

    first_spike = feed["social_velocity_spikes"][0]
    assert "social_velocity_growth_pct" in first_spike
    assert first_spike["social_velocity_growth_pct"] > 0
