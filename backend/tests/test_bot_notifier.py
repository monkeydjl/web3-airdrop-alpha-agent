"""Unit tests for Bot Notifier Service and API."""

from app.services.bot_notifier import handle_bot_command


def test_handle_bot_command_help():
    """验证 /help 指令返回说明."""
    res = handle_bot_command("/help")
    assert res["ok"] is True
    assert "/alpha" in res["reply"]
    assert "/gas" in res["reply"]


def test_handle_bot_command_gas():
    """验证 /gas 指令返回全链 Gas 信息."""
    res = handle_bot_command("/gas")
    assert res["ok"] is True
    assert "Ethereum" in res["reply"]
    assert "Gwei" in res["reply"]


def test_handle_bot_command_alpha():
    """验证 /alpha 指令返回项目推荐."""
    res = handle_bot_command("/alpha")
    assert res["ok"] is True
    assert "reply" in res


def test_handle_bot_command_unknown():
    """验证非法指令提示未知."""
    res = handle_bot_command("/invalid_command_test")
    assert res["ok"] is False
    assert "未知指令" in res["reply"]
