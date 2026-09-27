"""Tests for Smart Money Radar — 诚实口径契约.

2026-09-23 审计后，此服务不再编造巨鲸动态与社交增速：
- smart_money_activities 恒为空（无真实链上数据源时如实为 0 条）
- tracked_whales 是公开可验证的静态白名单
- social_velocity_spikes 排序基于真实项目评分，增速字段不编造
"""

from app.services.smart_money_radar import get_smart_money_and_social_feed


def test_feed_returns_empty_activities_honestly():
    """无真实数据源时，巨鲸动态必须为空——禁止编造动态冒充实时情报."""
    feed = get_smart_money_and_social_feed()
    assert feed["ok"] is True
    assert feed["smart_money_activities"] == []


def test_feed_tracked_whales_are_public_whitelist():
    """监控目标是公开人物地址白名单（静态知识），不含编造的动态描述."""
    feed = get_smart_money_and_social_feed()
    whales = feed["tracked_whales"]
    assert isinstance(whales, list)
    for w in whales:
        assert w["address"].startswith("0x")
        assert w["tier"] == "public_figure"
        # 白名单条目不得包含"最近做了什么"类的编造动态
        assert "action" not in w
        assert "time_ago" not in w


def test_feed_social_spikes_use_real_score_not_fabricated_growth():
    """热度榜基于真实项目评分；增速字段为 None 而非编造的百分比."""
    feed = get_smart_money_and_social_feed()
    spikes = feed["social_velocity_spikes"]
    assert isinstance(spikes, list)
    scores = [s["score"] for s in spikes if s["score"] is not None]
    # 真实评分必须非升序排列（按 score DESC 查询）
    assert scores == sorted(scores, reverse=True)
    for s in spikes:
        assert s["social_velocity_growth_pct"] is None
        assert s["velocity_rank_basis"] == "project_score"
