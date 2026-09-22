import pytest
from app.services.calldata_decoder import decode_calldata


def test_decode_calldata_native_transfer():
    res = decode_calldata("0x1111111111111111111111111111111111111111", "0x", 0.5)
    assert res["ok"] is True
    assert res["function_name"] == "native_transfer"
    assert res["safety_rating"] == "safe"


def test_decode_calldata_erc20_transfer():
    # 0xa9059cbb + 32-byte recipient + 32-byte amount (1000)
    to_hex = "0000000000000000000000002222222222222222222222222222222222222222"
    amt_hex = "00000000000000000000000000000000000000000000000000000000000003e8" # 1000
    calldata = f"0xa9059cbb{to_hex}{amt_hex}"

    res = decode_calldata("0xdac17f958d2ee523a2206206994597c13d831ec7", calldata)
    assert res["ok"] is True
    assert res["function_name"] == "transfer"
    assert res["method_selector"] == "0xa9059cbb"
    assert len(res["decoded_params"]) == 2
    assert res["decoded_params"][0]["value"] == "0x2222222222222222222222222222222222222222"
    assert res["decoded_params"][1]["value"] == "1000"
    assert res["safety_rating"] == "safe"


def test_decode_calldata_unlimited_approve():
    # 0x095ea7b3 + 32-byte spender + max uint256
    spender_hex = "0000000000000000000000003333333333333333333333333333333333333333"
    max_uint = "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
    calldata = f"0x095ea7b3{spender_hex}{max_uint}"

    res = decode_calldata("0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48", calldata)
    assert res["ok"] is True
    assert res["function_name"] == "approve"
    assert "MAX_UINT256" in res["decoded_params"][1]["value"]
    assert res["safety_rating"] == "caution"
    assert len(res["security_warnings"]) > 0


def test_decode_calldata_critical_governance():
    # 0x3659cfe6: upgradeTo
    impl_hex = "0000000000000000000000004444444444444444444444444444444444444444"
    calldata = f"0x3659cfe6{impl_hex}"

    res = decode_calldata("0x9999999999999999999999999999999999999999", calldata)
    assert res["ok"] is True
    assert res["function_name"] == "upgradeTo"
    assert res["safety_rating"] == "critical"
