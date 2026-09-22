"""Contract Calldata Decoder & Safe Sandbox (智能合约 Calldata 逆向解码与安全沙箱).

逆向解析 EVM 4-byte 函数选择器与 ABI 参数，深度审计无限授权、代理后门升级、
恶意偷渡转账与钓鱼签名风险。
"""

from __future__ import annotations

from typing import Any
import structlog

logger = structlog.get_logger(__name__)

# 常用 EVM 4-byte 方法签名库
KNOWN_SELECTORS: dict[str, dict[str, Any]] = {
    "0xa9059cbb": {
        "name": "transfer",
        "signature": "transfer(address to, uint256 amount)",
        "params": [{"name": "to", "type": "address"}, {"name": "amount", "type": "uint256"}],
        "category": "ERC-20 代币转账",
        "base_risk": "safe",
    },
    "0x095ea7b3": {
        "name": "approve",
        "signature": "approve(address spender, uint256 amount)",
        "params": [{"name": "spender", "type": "address"}, {"name": "amount", "type": "uint256"}],
        "category": "ERC-20 代币授权",
        "base_risk": "caution",
    },
    "0x23b872dd": {
        "name": "transferFrom",
        "signature": "transferFrom(address from, address to, uint256 amount)",
        "params": [
            {"name": "from", "type": "address"},
            {"name": "to", "type": "address"},
            {"name": "amount", "type": "uint256"},
        ],
        "category": "代币划扣转账",
        "base_risk": "caution",
    },
    "0xd0e30db0": {
        "name": "deposit",
        "signature": "deposit()",
        "params": [],
        "category": "WETH 包装/资金存入",
        "base_risk": "safe",
    },
    "0x2e1a7d4d": {
        "name": "withdraw",
        "signature": "withdraw(uint256 wad)",
        "params": [{"name": "wad", "type": "uint256"}],
        "category": "WETH 解包/资金取回",
        "base_risk": "safe",
    },
    "0x4e71d92d": {
        "name": "claim",
        "signature": "claim()",
        "params": [],
        "category": "空投/奖励无参认领",
        "base_risk": "safe",
    },
    "0x1249c58b": {
        "name": "mint",
        "signature": "mint()",
        "params": [],
        "category": "NFT/测试币免费铸造",
        "base_risk": "safe",
    },
    "0xa0712d68": {
        "name": "mint",
        "signature": "mint(uint256 amount)",
        "params": [{"name": "amount", "type": "uint256"}],
        "category": "指定数量铸造",
        "base_risk": "safe",
    },
    "0x6a627842": {
        "name": "mint",
        "signature": "mint(address to)",
        "params": [{"name": "to", "type": "address"}],
        "category": "定向铸造空投",
        "base_risk": "safe",
    },
    "0xd547741f": {
        "name": "castVote",
        "signature": "castVote(uint256 proposalId, uint8 support)",
        "params": [{"name": "proposalId", "type": "uint256"}, {"name": "support", "type": "uint8"}],
        "category": "DAO 链上治理投票",
        "base_risk": "safe",
    },
    "0x5c19a95c": {
        "name": "delegate",
        "signature": "delegate(address delegatee)",
        "params": [{"name": "delegatee", "type": "address"}],
        "category": "DAO 投票权委托",
        "base_risk": "safe",
    },
    "0x3659cfe6": {
        "name": "upgradeTo",
        "signature": "upgradeTo(address newImplementation)",
        "params": [{"name": "newImplementation", "type": "address"}],
        "category": "代理合约实现升级 (高权限)",
        "base_risk": "critical",
    },
    "0xf2fde38b": {
        "name": "transferOwnership",
        "signature": "transferOwnership(address newOwner)",
        "params": [{"name": "newOwner", "type": "address"}],
        "category": "合约最高所有权转让",
        "base_risk": "critical",
    },
    "0x8456cb59": {
        "name": "pause",
        "signature": "pause()",
        "params": [],
        "category": "紧急熔断暂停",
        "base_risk": "critical",
    },
    "0xd505accf": {
        "name": "permit",
        "signature": "permit(address owner, address spender, uint256 value, uint256 deadline, uint8 v, bytes32 r, bytes32 s)",
        "params": [
            {"name": "owner", "type": "address"},
            {"name": "spender", "type": "address"},
            {"name": "value", "type": "uint256"},
            {"name": "deadline", "type": "uint256"},
        ],
        "category": "EIP-2612 离线无 Gas 签名授权",
        "base_risk": "caution",
    }
}

MAX_UINT256_STR = "115792089237316195423570985008687907853269984665640564039457584007913129639935"


def decode_calldata(
    contract_address: str,
    calldata: str,
    value_eth: float = 0.0,
) -> dict[str, Any]:
    """解析 Calldata 字节流，提取函数签名、解构参数并提供安全评级."""
    c_addr = contract_address.lower().strip()
    data = calldata.strip()
    if not data.startswith("0x"):
        data = "0x" + data

    # 1. 纯 ETH 转账检测
    if data == "0x" or len(data) == 2:
        return {
            "ok": True,
            "contract_address": c_addr,
            "method_selector": "0x",
            "function_name": "native_transfer",
            "signature": "ETH 直接原生转账",
            "category": "原生资产流动",
            "safety_rating": "safe",
            "safety_label": "安全 (普通 ETH 交互)",
            "decoded_params": [{"name": "value_eth", "type": "ether", "value": value_eth}],
            "security_warnings": [],
            "human_readable_action": f"向地址 {c_addr} 直接转账 {value_eth} ETH，未执行任何合约逻辑代码。",
        }

    # 2. 提取 4 字节 selector
    selector = data[:10].lower()
    raw_params_hex = data[10:]

    known = KNOWN_SELECTORS.get(selector)
    fn_name = known["name"] if known else f"unknown_{selector}"
    sig = known["signature"] if known else f"UnknownMethod({selector})"
    category = known["category"] if known else "自定义/未录入函数"
    safety_rating = known["base_risk"] if known else "caution"

    # 3. 按 32 字节 (64 hex 字符) 切片解码参数
    decoded_params: list[dict[str, Any]] = []
    warnings: list[str] = []

    chunks = [raw_params_hex[i:i+64] for i in range(0, len(raw_params_hex), 64) if len(raw_params_hex[i:i+64]) == 64]

    if known and known.get("params"):
        param_defs = known["params"]
        for idx, pdef in enumerate(param_defs):
            if idx < len(chunks):
                chunk = chunks[idx]
                val_repr: Any = chunk
                if pdef["type"] == "address":
                    # 地址在 32 字节末尾 20 字节 (40 hex chars)
                    val_repr = "0x" + chunk[24:].lower()
                elif pdef["type"] in ["uint256", "uint8"]:
                    num_val = int(chunk, 16)
                    val_repr = str(num_val)

                    # 检查是否无限授权
                    if pdef["name"] in ["amount", "value"] and (num_val >= int("0xffffffffffffffffffffffff", 16)):
                        val_repr = "MAX_UINT256 (无限额度)"
                        safety_rating = "caution"
                        warnings.append("⚠️ 检测到无限额度 (Unlimited Allowance) 授权，请确认调用方为知名协议，防范授权被盗。")

                decoded_params.append({
                    "name": pdef["name"],
                    "type": pdef["type"],
                    "value": val_repr,
                })
    else:
        # 未知签名通用按槽位展示
        for idx, chunk in enumerate(chunks):
            # 尝试推测是否是 address
            if chunk.startswith("000000000000000000000000"):
                val = "0x" + chunk[24:].lower()
                t = "address (推测)"
            else:
                val = str(int(chunk, 16))
                t = "uint256 / bytes32 (推测)"
            decoded_params.append({
                "name": f"param_{idx + 1}",
                "type": t,
                "value": val,
            })

    # 4. 关键风险规则
    if safety_rating == "critical":
        warnings.append("🚨 极高危权限操作: 该函数涉及管理权限升级或合约暂停，常规用户交互极少涉及，切勿盲目签名！")

    if fn_name == "transferOwnership":
        warnings.append("🚨 发现所有权转让行为: 调用后将合约控制权移交其他地址。")

    if fn_name == "permit":
        warnings.append("⚠️ 离线无 Gas 签名 (Permit): 钓鱼网站最常见的盗币函数，请仔细核对被授权方地址。")

    # 5. 人性化行为解读
    if fn_name == "approve":
        spender = next((p["value"] for p in decoded_params if p["name"] == "spender"), "未知合约")
        amt = next((p["value"] for p in decoded_params if p["name"] == "amount"), "未知数量")
        action_text = f"正在授权合约 {spender} 扣除您的代币，额度为: {amt}。"
    elif fn_name == "transfer":
        to_addr = next((p["value"] for p in decoded_params if p["name"] == "to"), "未知地址")
        amt = next((p["value"] for p in decoded_params if p["name"] == "amount"), "未知数量")
        action_text = f"正在将您的代币直接转出至 {to_addr}，数量为 {amt}。"
    elif fn_name in ["mint", "claim"]:
        action_text = f"正在调用 {c_addr} 的 {fn_name} 接口领取/铸造资产。"
    else:
        action_text = f"正在对合约 {c_addr} 执行函数 {sig}。"

    rating_label = {
        "safe": "安全 (常规交互)",
        "caution": "警惕 (涉及代币授权或离线签名)",
        "critical": "极高危 (管理权限与资产易主)",
    }.get(safety_rating, "中度风险")

    return {
        "ok": True,
        "contract_address": c_addr,
        "method_selector": selector,
        "function_name": fn_name,
        "signature": sig,
        "category": category,
        "safety_rating": safety_rating,
        "safety_label": rating_label,
        "decoded_params": decoded_params,
        "security_warnings": warnings,
        "human_readable_action": action_text,
    }
