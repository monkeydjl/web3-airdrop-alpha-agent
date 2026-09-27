"""Tests for Script Forge — 必填契约.

2026-09-23 审计后，脚本生成不再内置占位合约地址：缺合约/RPC 时返回
校验失败，绝不生成「开箱即可向任意合约发交易」的危险脚本。
"""

from app.services.script_forge import generate_interaction_scripts


def test_generate_interaction_scripts():
    """提供真实合约与 RPC 时，生成三种格式脚本且绑定传入值."""
    res = generate_interaction_scripts(
        project_name="Monad Devnet",
        contract_address="0x1234567890123456789012345678901234567890",
        rpc_url="https://rpc.monad.xyz",
        jitter_min=10,
        jitter_max=30,
    )
    assert res["ok"] is True
    scripts = res["scripts"]
    assert "foundry_cast" in scripts
    assert "web3_py" in scripts
    assert "viem_ts" in scripts

    # 随机等待与 Jitter 逻辑
    py_code = scripts["web3_py"]
    assert "random.uniform(10, 30)" in py_code
    assert "ExtraDataToPOAMiddleware" in py_code

    # Foundry 单行指令正确绑定合约与 RPC
    cast_code = scripts["foundry_cast"]
    assert "cast send" in cast_code
    assert "https://rpc.monad.xyz" in cast_code
    # 传入的合约地址必须进入脚本
    assert "0x1234567890123456789012345678901234567890" in cast_code


def test_missing_contract_address_is_rejected():
    """缺合约地址时必须拒绝——审计前这里会静默使用占位地址 0x7777...."""
    res = generate_interaction_scripts(project_name="X", contract_address="", rpc_url="https://rpc.x")
    assert res["ok"] is False
    assert res["error"]["code"] == "CONTRACT_ADDRESS_REQUIRED"


def test_missing_rpc_is_rejected():
    res = generate_interaction_scripts(
        project_name="X",
        contract_address="0x1234567890123456789012345678901234567890",
        rpc_url="",
    )
    assert res["ok"] is False
    assert res["error"]["code"] == "RPC_URL_REQUIRED"


def test_no_placeholder_address_in_generated_scripts():
    """生成的脚本不得包含任何历史占位地址."""
    res = generate_interaction_scripts(
        project_name="X",
        contract_address="0xabcdefabcdefabcdefabcdefabcdefabcdefabcd",
        rpc_url="https://rpc.x",
    )
    all_code = "".join(res["scripts"].values())
    assert "0x7777777254eeb25477b68fb85ed929f73a960582" not in all_code
