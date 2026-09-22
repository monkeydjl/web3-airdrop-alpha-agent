import pytest
from app.services.daily_briefing import generate_daily_briefing


def test_generate_daily_briefing():
    res = generate_daily_briefing()
    assert res["ok"] is True
    assert "date" in res
    assert "title" in res
    assert len(res["top_three_actions"]) == 3
    assert len(res["top_projects"]) > 0
    assert "gas_advice" in res
    assert len(res["weekly_windows"]) > 0
    assert len(res["markdown_content"]) > 100
    assert "# 📰 Web3 空投猎人 Alpha 晚报" in res["markdown_content"]
