import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import {
  labelZh,
  stageZh,
  lifecycleStageZh,
  timingZh,
  riskLevelZh,
  teamTypeZh,
  tierZh,
  sourceZh,
  confColor,
  reasonZh,
  viabilityTierZh,
  capitalFrictionTierZh,
  blockerCodeZh,
  severityZh,
} from './format.ts';

describe('labelZh', () => {
  it('正确映射三档标签', () => {
    assert.equal(labelZh('FARM'), '重点参与');
    assert.equal(labelZh('WATCH'), '观察');
    assert.equal(labelZh('IGNORE'), '忽略');
  });

  it('未知标签保留原值', () => {
    assert.equal(labelZh('UNKNOWN_LABEL'), 'UNKNOWN_LABEL');
  });
});

describe('stageZh & lifecycleStageZh & timingZh', () => {
  it('正确映射部署阶段', () => {
    assert.equal(stageZh('testnet'), '测试网');
    assert.equal(stageZh('mainnet'), '主网');
    assert.equal(stageZh('ideation'), '构想期');
    assert.equal(stageZh(null), '—');
    assert.equal(stageZh(''), '—');
  });

  it('正确映射叙事生命周期', () => {
    assert.equal(lifecycleStageZh('early'), '早期');
    assert.equal(lifecycleStageZh('growth'), '成长期');
    assert.equal(lifecycleStageZh('peak'), '高峰期');
    assert.equal(lifecycleStageZh('mature'), '成熟期');
    assert.equal(lifecycleStageZh(undefined), '—');
  });

  it('正确映射时机', () => {
    assert.equal(timingZh('early'), '早期窗口');
    assert.equal(timingZh('peak'), '过热');
    assert.equal(timingZh('late'), '偏晚');
    assert.equal(timingZh(''), '—');
  });
});

describe('sourceZh', () => {
  it('覆盖新增的零成本免费公开源', () => {
    assert.equal(sourceZh('telegram'), 'Telegram 频道');
    assert.equal(sourceZh('farcaster'), 'Farcaster 社区');
  });

  it('覆盖常规数据源与种子导入', () => {
    assert.equal(sourceZh('github'), 'GitHub');
    assert.equal(sourceZh('defillama'), 'DefiLlama');
    assert.equal(sourceZh('seed'), '种子数据');
    assert.equal(sourceZh('import'), '文件导入');
    assert.equal(sourceZh(null), '—');
  });
});

describe('riskLevelZh & teamTypeZh & tierZh', () => {
  it('正确映射风险级别', () => {
    assert.equal(riskLevelZh('high'), '高');
    assert.equal(riskLevelZh('medium'), '中');
    assert.equal(riskLevelZh('low'), '低');
    assert.equal(riskLevelZh(null), '—');
  });

  it('正确映射团队类型与 VC Tier', () => {
    assert.equal(teamTypeZh('doxxed'), '实名');
    assert.equal(teamTypeZh('anon'), '匿名');
    assert.equal(tierZh('tier1'), '一线 VC');
    assert.equal(tierZh('none'), '无融资');
  });
});

describe('reasonZh & viabilityTierZh & capitalFrictionTierZh', () => {
  it('正确映射存活率风险理由与决策理由', () => {
    assert.equal(reasonZh('LOW_RUNWAY_RISK'), '存活跑道风险：融资过小或缺乏知名机构支持');
    assert.equal(reasonZh('strong airdrop signal'), '明确的空投信号');
    assert.equal(reasonZh('low_funding_unviable'), '公开融资 < $3M 且缺乏顶级机构背书，低迷行情下极易倒闭');
  });

  it('正确映射存活率等级', () => {
    assert.equal(viabilityTierZh('viable'), '资金充裕');
    assert.equal(viabilityTierZh('borderline'), '跑道观察');
    assert.equal(viabilityTierZh('unviable'), '存活预警');
  });

  it('正确映射资本摩擦等级', () => {
    assert.equal(capitalFrictionTierZh('zero_cost'), '零资金成本');
    assert.equal(capitalFrictionTierZh('low_cost'), '极低磨损');
    assert.equal(capitalFrictionTierZh('heavy_capital'), '重度质押/高磨损');
  });

  it('正确映射阻断项与严重程度', () => {
    assert.equal(blockerCodeZh('SAFETY_BLOCK'), '安全阻断');
    assert.equal(blockerCodeZh('RULE_BLOCK'), '规则限制阻断');
    assert.equal(severityZh('critical'), '严重');
    assert.equal(severityZh('high'), '高');
  });
});

describe('confColor', () => {
  it('根据置信度返回正确颜色类名', () => {
    assert.ok(confColor(0.85).includes('text-farm'));
    assert.ok(confColor(0.6).includes('text-watch'));
    assert.ok(confColor(0.3).includes('text-red-500'));
  });
});
