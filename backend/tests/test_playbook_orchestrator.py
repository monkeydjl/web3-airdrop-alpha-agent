"""Tests for Playbook Orchestrator & Script Studio — 占位合约拦截契约.

2026-09-23 审计后：步骤含占位合约（0x7777.../0xTBD）时拒绝生成可执行脚本，
防止用户照抄脚本向无效合约发交易。
"""

from app.services.playbook_orchestrator import (
    _is_placeholder_contract,
    is_faucet_sentinel_addr,
    list_playbook_templates,
    validate_and_generate_playbook_script,
)

# Ambient 官方 Scroll vanity 地址（docs.ambient.finance，前 8 位同为 a）
AMBIENT_SCROLL_CROCSWAPDEX = "0xaaaaAAAACB71BF2C8CaE522EA5fa455571A74106"


def test_placeholder_detection_does_not_kill_vanity_addresses() -> None:
    """前缀重复但尾部多样的真实 vanity 地址（Ambient 等）不得误判为占位."""
    assert _is_placeholder_contract(AMBIENT_SCROLL_CROCSWAPDEX) is False
    assert _is_placeholder_contract("0x7777777777777777777777777777777777777777") is True
    assert _is_placeholder_contract("0xTBD-REPLACE-ME") is True
    assert _is_placeholder_contract("") is True
    assert _is_placeholder_contract("0x1111") is True


def test_faucet_sentinel_zero_address_allowed() -> None:
    """faucet 类无合约交互步骤的零地址哨兵不参与占位校验."""
    assert is_faucet_sentinel_addr("0x0000000000000000000000000000000000000000") is True
    assert is_faucet_sentinel_addr("") is True
    assert is_faucet_sentinel_addr(AMBIENT_SCROLL_CROCSWAPDEX) is False


def test_list_playbook_templates() -> None:
    templates = list_playbook_templates()
    assert len(templates) >= 3
    ids = [t["id"] for t in templates]
    assert "playbook_scroll_marks" in ids
    assert "playbook_monad_testnet" in ids


def test_scroll_playbook_generates_with_real_contracts() -> None:
    """Scroll 模板步骤带真实合约地址，可正常生成."""
    res = validate_and_generate_playbook_script(
        playbook_id="playbook_scroll_marks",
        jitter_range_seconds=(45, 120),
    )
    assert res["ok"] is True
    assert res["step_count"] == 4
    assert res["total_estimated_gas_usd"] > 0
    assert "Scroll Marks" in res["title"]
    assert "random.uniform(45, 120)" in res["executable_code"]
    assert "0x6f26Bf09B1C792e3228e5467807a900A503c0281" in res["executable_code"]
    # Ambient vanity 地址恢复后必须重新进入可执行脚本
    assert AMBIENT_SCROLL_CROCSWAPDEX in res["executable_code"]


def test_monad_playbook_blocked_by_placeholder_contracts() -> None:
    """Monad 测试网模板含未登记合约，必须拒绝生成可执行脚本（审计 P1）。"""
    res = validate_and_generate_playbook_script(playbook_id="playbook_monad_testnet")
    assert res["ok"] is False
    assert res["error"]["code"] == "PLACEHOLDER_CONTRACT"
    assert "executable_code" not in res
    # 拦截信息必须列出具体步骤
    assert len(res["error"]["placeholder_steps"]) >= 3


def test_custom_placeholder_step_is_blocked() -> None:
    custom_steps = [
        {"action": "swap", "title": "Swap", "contract": "0x1111", "gas_usd": 0.2},
    ]
    res = validate_and_generate_playbook_script(custom_title="Custom", custom_steps=custom_steps)
    assert res["ok"] is False
    assert res["error"]["code"] == "PLACEHOLDER_CONTRACT"


def test_custom_real_contracts_generate() -> None:
    custom_steps = [
        {
            "action": "swap",
            "title": "Swap ETH to USDC",
            "contract": "0x6f26Bf09B1C792e3228e5467807a900A503c0281",
            "gas_usd": 0.2,
        },
        {
            "action": "stake",
            "title": "Stake USDC",
            "contract": "0x1b0e765F6224C21223AeA2af16c1C46E38885a40",
            "gas_usd": 0.4,
        },
    ]
    res = validate_and_generate_playbook_script(
        custom_title="Custom 2-Step Flow",
        custom_steps=custom_steps,
    )
    assert res["ok"] is True
    assert res["step_count"] == 2
    assert res["total_estimated_gas_usd"] == 0.6
    assert "Custom 2-Step Flow" in res["executable_code"]


def test_templates_carry_no_fake_repeating_addresses() -> None:
    """模板里不得出现全长重复的伪装地址；显式 TBD（待登记）与 faucet 哨兵除外。"""
    for pb in list_playbook_templates():
        for step in pb["steps"]:
            addr = str(step.get("contract", ""))
            body = addr.lower()[2:]
            is_faucet_step = step.get("action") == "faucet"
            is_disguised = (
                # 伪装：像真地址但全长同一字符（0x8888...8888）
                len(body) >= 8 and len(set(body)) == 1 and not (is_faucet_step and is_faucet_sentinel_addr(addr))
            )
            assert not is_disguised, f"{pb['id']} step {step.get('step_no')} 仍是伪装占位地址: {addr}"
            # 非 faucet 步骤要么是真地址，要么显式 TBD（生成时会被拦截）
            if not is_faucet_step and not addr.upper().startswith("0XTBD"):
                assert _is_placeholder_contract(addr) is False, (
                    f"{pb['id']} step {step.get('step_no')} 合约地址无效: {addr}"
                )
