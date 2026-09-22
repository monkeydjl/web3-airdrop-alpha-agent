import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

describe('batch5 sybil lineage & fund linkage logic', () => {
  it('computes isolation score and classifies cluster risk tier', () => {
    const classifyRisk = (score: number) => {
      if (score >= 80) return 'SAFE';
      if (score >= 60) return 'LOW_RISK';
      if (score >= 40) return 'MEDIUM_RISK';
      return 'HIGH_RISK';
    };

    assert.equal(classifyRisk(95), 'SAFE');
    assert.equal(classifyRisk(72), 'LOW_RISK');
    assert.equal(classifyRisk(50), 'MEDIUM_RISK');
    assert.equal(classifyRisk(25), 'HIGH_RISK');
  });

  it('detects critical red flags in wallet cluster graph', () => {
    interface LinkageEdge {
      from: string;
      to: string;
      type: 'direct_transfer' | 'cex_deposit' | 'mixer' | 'normal';
    }

    const inspectRedFlags = (edges: LinkageEdge[]) => {
      const redFlags: string[] = [];
      const hasDirectTransfer = edges.some((e) => e.type === 'direct_transfer');
      const hasCexReuse = edges.filter((e) => e.type === 'cex_deposit').length >= 2;
      const hasMixer = edges.some((e) => e.type === 'mixer');

      if (hasDirectTransfer) redFlags.push('DIRECT_WALLET_TRANSFER');
      if (hasCexReuse) redFlags.push('SHARED_CEX_DEPOSIT_ADDRESS');
      if (hasMixer) redFlags.push('PRIVACY_POOL_MIXER_TAINT');

      return redFlags;
    };

    const cleanCluster: LinkageEdge[] = [
      { from: '0x1', to: '0xUniswap', type: 'normal' },
      { from: '0x2', to: '0xCurve', type: 'normal' },
    ];
    assert.deepEqual(inspectRedFlags(cleanCluster), []);

    const taintedCluster: LinkageEdge[] = [
      { from: '0x1', to: '0x2', type: 'direct_transfer' },
      { from: '0x2', to: '0xBinanceHot', type: 'cex_deposit' },
      { from: '0x3', to: '0xBinanceHot', type: 'cex_deposit' },
    ];
    const flags = inspectRedFlags(taintedCluster);
    assert.ok(flags.includes('DIRECT_WALLET_TRANSFER'));
    assert.ok(flags.includes('SHARED_CEX_DEPOSIT_ADDRESS'));
  });
});

describe('batch5 calldata decoder & safe sandbox logic', () => {
  it('extracts 4-byte selector and matches method signature accurately', () => {
    const extractSelector = (calldata: string): string => {
      const clean = calldata.trim().startsWith('0x') ? calldata.trim().slice(2) : calldata.trim();
      return clean.length >= 8 ? '0x' + clean.slice(0, 8).toLowerCase() : '0x';
    };

    const KNOWN_SELECTORS: Record<string, string> = {
      '0x095ea7b3': 'approve(address,uint256)',
      '0xa9059cbb': 'transfer(address,uint256)',
      '0x23b872dd': 'transferFrom(address,address,uint256)',
      '0xf242432a': 'safeTransferFrom(address,address,uint256,uint256,bytes)',
      '0x38ed1739': 'swapExactTokensForTokens(uint256,uint256,address[],address,uint256)',
      '0xf2fde38b': 'transferOwnership(address)',
    };

    const approveCalldata = '0x095ea7b3000000000000000000000000def1c0ded9bec7f1a1670819833240f027b25effffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff';
    const selector = extractSelector(approveCalldata);
    assert.equal(selector, '0x095ea7b3');
    assert.equal(KNOWN_SELECTORS[selector], 'approve(address,uint256)');

    const transferCalldata = '0xa9059cbb00000000000000000000000088888888888888888888888888888888888888880000000000000000000000000000000000000000000000000de0b6b3a7640000';
    assert.equal(extractSelector(transferCalldata), '0xa9059cbb');
    assert.equal(KNOWN_SELECTORS[extractSelector(transferCalldata)], 'transfer(address,uint256)');
  });

  it('flags unlimited token approval as security warning', () => {
    const isUnlimitedApproval = (calldata: string): boolean => {
      const clean = calldata.trim().toLowerCase();
      return clean.includes('ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff');
    };

    assert.equal(
      isUnlimitedApproval('0x095ea7b3000000000000000000000000def1c0ded9bec7f1a1670819833240f027b25effffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff'),
      true
    );
    assert.equal(
      isUnlimitedApproval('0x095ea7b3000000000000000000000000def1c0ded9bec7f1a1670819833240f027b25eff0000000000000000000000000000000000000000000000000de0b6b3a7640000'),
      false
    );
  });
});

describe('batch5 points epoch valuation & snapshot estimator logic', () => {
  it('calculates user token allocation from points share and booster', () => {
    const calcAllocation = (
      userPoints: number,
      boosterMultiplier: number,
      totalPoolPoints: number,
      totalAirdropSupply: number,
      tokenPriceUsd: number
    ) => {
      const effectivePoints = userPoints * boosterMultiplier;
      const share = effectivePoints / totalPoolPoints;
      const tokens = share * totalAirdropSupply;
      const usdValue = tokens * tokenPriceUsd;
      return { tokens: Math.round(tokens), usdValue: Math.round(usdValue * 100) / 100 };
    };

    // User has 10,000 marks, 1.5x multiplier -> 15,000 effective marks out of 100,000,000 pool
    // 70,000,000 airdrop token pool, $1.20 token price
    const res = calcAllocation(10000, 1.5, 100_000_000, 70_000_000, 1.2);
    assert.equal(res.tokens, 10500); // 15000 / 100,000,000 * 70,000,000 = 10,500
    assert.equal(res.usdValue, 12600); // 10,500 * 1.2 = 12,600
  });
});

describe('batch5 daily alpha briefing & gas window logic', () => {
  it('identifies best ethereum interaction time window', () => {
    const isGoldenGasHour = (utcHour: number): boolean => {
      // Golden gas hours are typically early UTC mornings (02:00 - 06:00 UTC)
      return utcHour >= 2 && utcHour <= 6;
    };

    assert.equal(isGoldenGasHour(3), true);
    assert.equal(isGoldenGasHour(5), true);
    assert.equal(isGoldenGasHour(14), false); // US peak hours
    assert.equal(isGoldenGasHour(20), false);
  });
});
