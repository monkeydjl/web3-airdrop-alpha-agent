import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import { pnlTierZh, securityRiskZh } from './format.ts';

describe('batch2 formatters (pnlTierZh & securityRiskZh)', () => {
  it('correctly maps pnl tiers', () => {
    assert.equal(pnlTierZh('legendary'), '传奇巨鲸领主');
    assert.equal(pnlTierZh('diamond'), '钻石手资深猎人');
    assert.equal(pnlTierZh('gold'), '黄金活跃先锋');
    assert.equal(pnlTierZh('novice'), '萌新链上探险家');
    assert.equal(pnlTierZh(null), '萌新猎人');
    assert.equal(pnlTierZh('custom_tier'), 'custom_tier');
  });

  it('correctly maps security risk levels', () => {
    assert.equal(securityRiskZh('critical'), '极度危险');
    assert.equal(securityRiskZh('high'), '高风险');
    assert.equal(securityRiskZh('medium'), '中风险');
    assert.equal(securityRiskZh('low'), '低风险');
    assert.equal(securityRiskZh('safe'), '安全');
    assert.equal(securityRiskZh(null), '未知');
  });
});
