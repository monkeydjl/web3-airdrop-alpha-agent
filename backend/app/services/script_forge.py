"""Automated Interaction Script Forge Service (自动化交互 CLI 脚本与防女巫模板工坊).

为高阶猎人自动生成无后门、开源透明且内置随机时间抖动 (Jitter) 与随机 Gas 扰动的交互脚本模板：
- Foundry Cast (命令行单行快速执行)
- Web3.py (Python 脚本，防女巫离散度控制)
- Viem / TypeScript (Node.js/前端执行)
"""

from typing import Any
import structlog

logger = structlog.get_logger(__name__)


def generate_interaction_scripts(
    project_name: str = "Story Protocol",
    task_type: str = "contract_mint",
    contract_address: str = "0x7777777254eeb25477b68fb85ed929f73a960582",
    rpc_url: str = "https://odyssey.storyrpc.io",
    jitter_min: int = 15,
    jitter_max: int = 60,
) -> dict[str, Any]:
    """生成防女巫交互代码模版."""
    c_addr = contract_address.strip()
    rpc = rpc_url.strip()

    # 1. Foundry Cast 模版
    foundry_script = f"""# [Foundry Cast] 一键单行链上交互模版 (项目: {project_name})
# 依赖: curl -L https://foundry.paradigm.xyz | bash && foundryup

export RPC_URL="{rpc}"
export CONTRACT="{c_addr}"
export PRIVATE_KEY="0x_YOUR_LOCAL_PRIVATE_KEY"

# 执行铸造 / 交互指令 (随机附加微量优先费防拥堵)
cast send $CONTRACT "mint(address,uint256)" $(cast wallet address --private-key $PRIVATE_KEY) 1 \\
  --rpc-url $RPC_URL \\
  --private-key $PRIVATE_KEY \\
  --priority-gas-price 1.5gwei
"""

    # 2. Web3.py Python 模版（内嵌防女巫随机抖动 Jitter）
    python_script = f'''"""Web3.py 自动化交互模版 (带防女巫时间离散度控制)
项目: {project_name} | 任务: {task_type}
"""

import os
import time
import random
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

RPC_URL = os.getenv("RPC_URL", "{rpc}")
CONTRACT_ADDRESS = os.getenv("CONTRACT_ADDRESS", "{c_addr}")
PRIVATE_KEY = os.getenv("PRIVATE_KEY", "0x_YOUR_PRIVATE_KEY_HERE")

w3 = Web3(Web3.HTTPProvider(RPC_URL))
# 兼容部分测试网与 L2 POA 共识
w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)

def execute_organic_interaction():
    account = w3.eth.account.from_key(PRIVATE_KEY)
    my_addr = account.address
    print(f"[*] 当前执行钱包: {{my_addr}}")

    # 1. 防女巫随机时间抖动 (Jitter: {jitter_min}~{jitter_max}s)
    delay = random.uniform({jitter_min}, {jitter_max})
    print(f"[*] 注入防女巫人类随机等待时间: {{delay:.2f}} 秒...")
    time.sleep(delay)

    # 2. 动态随机微量 Gas 扰动 (避免同质化 Gas 签名特征)
    base_gas_price = w3.eth.gas_price
    gas_jitter = random.uniform(1.02, 1.08) # 上浮 2%~8% 随机值
    effective_gas_price = int(base_gas_price * gas_jitter)

    nonce = w3.eth.get_transaction_count(my_addr)

    # 标准 ERC-721 / 测试网 Mint 方法签名: mint(address,uint256) -> 0x40c10f19
    data = "0x40c10f19" + my_addr[2:].zfill(64) + hex(1)[2:].zfill(64)

    tx = {{
        "to": w3.to_checksum_address(CONTRACT_ADDRESS),
        "from": my_addr,
        "value": 0,
        "gas": 150000,
        "gasPrice": effective_gas_price,
        "nonce": nonce,
        "chainId": w3.eth.chain_id,
        "data": data,
    }}

    signed = w3.eth.account.sign_transaction(tx, PRIVATE_KEY)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    print(f"[+] 交易已成功广播，Tx Hash: {{tx_hash.hex()}}")

if __name__ == "__main__":
    execute_organic_interaction()
'''

    # 3. Viem / TypeScript 模版
    ts_script = f"""// Viem / TypeScript 交互模版 (现代轻量高兼容)
// 依赖: npm i viem

import {{ createWalletClient, http, parseEther }} from 'viem';
import {{ privateKeyToAccount }} from 'viem/accounts';

const account = privateKeyToAccount(process.env.PRIVATE_KEY as `0x${{string}}`);
const client = createWalletClient({{
  account,
  transport: http('{rpc}'),
}});

async function main() {{
  console.log(`正在执行 {{account.address}} 在 {project_name} 上的合约交互...`);

  // 随机等待防女巫
  const waitMs = Math.floor(Math.random() * ({jitter_max} - {jitter_min} + 1) + {jitter_min}) * 1000;
  console.log(`防女巫等待: ${{waitMs / 1000}}s`);
  await new Promise((r) => setTimeout(r, waitMs));

  const hash = await client.sendTransaction({{
    to: '{c_addr}',
    value: 0n,
    // mint(address,uint256) ABI 编码数据
    data: '0x40c10f19' + account.address.slice(2).padStart(64, '0') + '1'.padStart(64, '0'),
  }});

  console.log(`交互广播成功! Tx: ${{hash}}`);
}}

main().catch(console.error);
"""

    return {
        "ok": True,
        "project_name": project_name,
        "task_type": task_type,
        "contract_address": c_addr,
        "rpc_url": rpc,
        "jitter_window": f"{jitter_min}s - {jitter_max}s",
        "scripts": {
            "foundry_cast": foundry_script.strip(),
            "web3_py": python_script.strip(),
            "viem_ts": ts_script.strip(),
        },
        "safety_notes": "声明：所有脚本均在您的本地环境独立运行，私钥直接在本地签名，绝不经由任何第三方服务端传输。",
    }
