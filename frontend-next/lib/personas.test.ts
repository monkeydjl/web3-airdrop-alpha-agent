import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import { HUNTER_PERSONAS, getPersonaConfig } from './personas.ts';

describe('hunter personas presets & helpers', () => {
  it('包含完整的 4 种预设角色且 ID 唯一', () => {
    assert.equal(HUNTER_PERSONAS.length, 4);
    const ids = HUNTER_PERSONAS.map((p) => p.id);
    assert.deepEqual(ids, ['balanced', 'zero_cost', 'whale_restaking', 'high_beta']);
  });

  it('非 balanced 角色的权重之和均严格为 1.0 (精度误差 < 1e-6)', () => {
    for (const persona of HUNTER_PERSONAS) {
      if (persona.weights) {
        const sum = Object.values(persona.weights).reduce((a, b) => a + b, 0);
        assert.ok(Math.abs(sum - 1.0) < 1e-6, `${persona.id} 权重和应为 1.0，实际为 ${sum}`);
        assert.equal(Object.keys(persona.weights).length, 8, `${persona.id} 应包含全部 8 维指标`);
      }
    }
  });

  it('getPersonaConfig 针对已知和未知 ID 返回正确的配置', () => {
    const zeroCost = getPersonaConfig('zero_cost');
    assert.equal(zeroCost.id, 'zero_cost');
    assert.equal(zeroCost.name, '零成本测试网党');

    const whale = getPersonaConfig('whale_restaking');
    assert.equal(whale.id, 'whale_restaking');
    assert.equal(whale.name, '巨鲸质押生息党');

    // 未知或空 ID 回退为 balanced
    const fallback = getPersonaConfig('unknown_persona' as any);
    assert.equal(fallback.id, 'balanced');
    assert.equal(fallback.name, '全能平衡模式');

    const nullFallback = getPersonaConfig(null);
    assert.equal(nullFallback.id, 'balanced');
  });
});
