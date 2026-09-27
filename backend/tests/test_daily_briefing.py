from app.services.daily_briefing import generate_daily_briefing

# 显式建库：此文件的用例直连 DB_PATH 但自身不 init_db()，过去依赖
# conftest pytest_configure 的会话级兜底（主仓库 data/test.db 的历史残留
# schema）侥幸通过；全新 checkout / CI runner 上单跑必红（no such table）。
# 现改为模块内显式 autouse fixture 幂等建库，消除对兜底的隐式依赖。

import pytest


@pytest.fixture(autouse=True)
def _ensure_db_schema():
    """显式幂等建库（不删库、不清数据）；详见文件头注释。"""
    from app.db import init_db

    init_db()


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
