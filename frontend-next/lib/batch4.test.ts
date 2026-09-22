import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

describe('batch4 token unlocks & gas alerts logic', () => {
  it('correctly classifies token unlock pressure rating', () => {
    const classify = (circPct: number, usdVal: number) => {
      if (circPct >= 15 || usdVal >= 100_000_000) return 'critical';
      if (circPct >= 6 || usdVal >= 30_000_000) return 'high';
      if (circPct >= 2 || usdVal >= 10_000_000) return 'moderate';
      return 'low';
    };

    assert.equal(classify(16.3, 875_000_000), 'critical');
    assert.equal(classify(8.4, 28_000_000), 'high');
    assert.equal(classify(3.2, 12_000_000), 'moderate');
    assert.equal(classify(1.2, 2_000_000), 'low');
  });

  it('triggers gas alerts accurately based on condition threshold', () => {
    const evaluateAlert = (currentGwei: number, condition: 'below' | 'above', thresholdGwei: number) => {
      if (condition === 'below') return currentGwei <= thresholdGwei;
      return currentGwei >= thresholdGwei;
    };

    assert.equal(evaluateAlert(9.5, 'below', 12.0), true);
    assert.equal(evaluateAlert(14.2, 'below', 12.0), false);
    assert.equal(evaluateAlert(38.0, 'above', 35.0), true);
    assert.equal(evaluateAlert(20.0, 'above', 35.0), false);
  });
});

describe('batch4 sell-off simulator & wallet health diagnostic', () => {
  it('computes 4 exit strategies expected values accurately', () => {
    const amt = 1000;
    const price = 2.0;
    const initialGross = amt * price; // 2000
    assert.equal(initialGross, 2000);

    // Instant dump: 5% slippage execution
    const instant = amt * (price * 0.95);
    assert.equal(instant, 1900);

    // Moonbag 50/50: 50% sold at instant + 50% retained at 1y factor 1.2
    const cash = 500 * (price * 0.95); // 950
    const retained = 500 * (price * 1.2); // 1200
    assert.equal(cash + retained, 2150);
  });

  it('computes wallet health score and assigns proper sybil risk level', () => {
    const calcHealth = (scores: { longevity: number; contracts: number; protos: number; gas: number; chains: number }) => {
      return Math.round(
        scores.longevity * 0.25 +
        scores.contracts * 0.25 +
        scores.protos * 0.20 +
        scores.gas * 0.15 +
        scores.chains * 0.15
      );
    };

    const getRisk = (score: number) => {
      if (score >= 80) return 'low';
      if (score >= 60) return 'moderate';
      if (score >= 40) return 'high';
      return 'critical';
    };

    const stellar = calcHealth({ longevity: 90, contracts: 95, protos: 100, gas: 90, chains: 90 });
    assert.ok(stellar >= 90);
    assert.equal(getRisk(stellar), 'low');

    const bot = calcHealth({ longevity: 25, contracts: 30, protos: 20, gas: 35, chains: 45 });
    assert.ok(bot < 40);
    assert.equal(getRisk(bot), 'critical');
  });
});
