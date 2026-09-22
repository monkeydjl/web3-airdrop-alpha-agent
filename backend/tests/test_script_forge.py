"""Unit tests for Script Forge Service and API."""

from app.services.script_forge import generate_interaction_scripts


def test_generate_interaction_scripts():
    """验证生成三种格式的完整脚本代码."""
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

    # 验证 Web3.py 脚本中包含随机等待与 Jitter 逻辑
    py_code = scripts["web3_py"]
    assert "random.uniform(10, 30)" in py_code
    assert "ExtraDataToPOAMiddleware" in py_code

    # 验证 Foundry 单行指令正确绑定合约与 RPC
    cast_code = scripts["foundry_cast"]
    assert "cast send" in cast_code
    assert "https://rpc.monad.xyz" in cast_code
