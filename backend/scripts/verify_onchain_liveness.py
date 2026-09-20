"""CLI tool to verify EVM contract address liveness using free public RPCs.

Usage:
    python backend/scripts/verify_onchain_liveness.py 0x1234567890123456789012345678901234567890 --chain sepolia
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Add backend directory to sys.path
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.public_rpc_verifier import SUPPORTED_CHAINS, verify_contract_liveness


async def main() -> int:
    # Set console encoding to UTF-8 on Windows
    if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Verify EVM contract liveness via keyless public RPCs.")
    parser.add_argument("address", help="EVM address to verify (0x...)")
    parser.add_argument(
        "--chain",
        default="sepolia",
        choices=list(SUPPORTED_CHAINS.keys()),
        help="Target chain (default: sepolia)",
    )
    args = parser.parse_args()

    print(f"[探测] 开始对网络 '{args.chain}' 探测地址 {args.address}...")
    res = await verify_contract_liveness(args.address, chain=args.chain)

    if res.get("error"):
        print(f"[错误] 探测失败: {res['error']}")
        return 1

    print("\n--- 探测结果 ---")
    print(f"目标网络: {res.get('chain_name')} ({res.get('chain')})")
    print(f"是否为合约: {'[是]' if res.get('is_contract') else '[否 (可能为 EOA/未部署)]'}")
    print(f"链上部署状态: {'[已部署]' if res.get('deployed') else '[空地址]'}")
    print(f"字节码体积: {res.get('bytecode_size')} 字节")
    print(f"历史交易数 (Nonce): {res.get('transaction_count')}")
    print(f"使用公共 RPC: {res.get('rpc_endpoint')}")
    print(f"响应延迟: {res.get('latency_ms')} ms")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
