import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import {
  labelZh,
  hiddenReasonZh,
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
  hasExplicitAirdropSignal,
  structuredSignalRows,
  structuredSignalBadges,
  hasHighRiskStructuredSignal,
  tgeClarityZh,
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
    assert.equal(sourceZh('github_curated'), 'GitHub 精选测试网');
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

describe('hiddenReasonZh', () => {
  it('映射已知隐藏原因', () => {
    assert.equal(hiddenReasonZh('already_launched_no_path'), '已发币·无参与路径');
  });

  it('未知原因原样透出、空值返回空串（不吞掉后端新增原因）', () => {
    assert.equal(hiddenReasonZh('some_future_reason'), 'some_future_reason');
    assert.equal(hiddenReasonZh(null), '');
    assert.equal(hiddenReasonZh(undefined), '');
    assert.equal(hiddenReasonZh(''), '');
  });
});

describe('confColor', () => {
  it('根据置信度返回正确颜色类名', () => {
    assert.ok(confColor(0.85).includes('text-farm'));
    assert.ok(confColor(0.6).includes('text-watch'));
    assert.ok(confColor(0.3).includes('text-red-500'));
  });
});

describe('hasExplicitAirdropSignal', () => {
  it('识别包含 strong airdrop signal 或 explicit mention 的项目', () => {
    assert.equal(hasExplicitAirdropSignal({ reason: ['strong airdrop signal', 'credible team'] }), true);
    assert.equal(hasExplicitAirdropSignal({ reason: ['explicit airdrop mention'] }), true);
    assert.equal(hasExplicitAirdropSignal({ reason: ['clear airdrop / points path'] }), true);
    assert.equal(hasExplicitAirdropSignal({ reason_zh: ['明确的空投信号'] }), true);
  });

  it('识别 signals 标记或高分积分活动', () => {
    assert.equal(hasExplicitAirdropSignal({ signals: { explicit_airdrop_mention: true } }), true);
    assert.equal(hasExplicitAirdropSignal({ signals: { has_points_program: true, no_token_yet: true } }), true);
    assert.equal(hasExplicitAirdropSignal({ sub_scores: { airdrop_signal: 85 } }), true);
  });

  it('对无空投信号项目返回 false', () => {
    assert.equal(hasExplicitAirdropSignal(null), false);
    assert.equal(hasExplicitAirdropSignal({}), false);
    assert.equal(hasExplicitAirdropSignal({ reason: ['credible team', 'late narrative'] }), false);
    assert.equal(hasExplicitAirdropSignal({ signals: { explicit_airdrop_mention: false } }), false);
  });
});

describe('structuredSignalRows & tgeClarityZh', () => {
  it('三行固定顺序与键', () => {
    const rows = structuredSignalRows({});
    assert.deepEqual(
      rows.map((r) => r.key),
      ['points_season_count', 'tge_clarity', 'is_perp'],
    );
  });

  it('空/脏 signals 全部未观测且永不抛错', () => {
    for (const sig of [undefined, null, {}, { tge_clarity: 42 }, { points_season_count: '3' }, { is_perp: 'yes' }]) {
      const rows = structuredSignalRows(sig as Record<string, unknown>);
      assert.ok(rows.every((r) => !r.observed));
      assert.ok(rows.every((r) => r.display === '未观测'));
    }
  });

  it('观测值正确展示', () => {
    const rows = structuredSignalRows({
      points_season_count: 4,
      tge_clarity: 'confirmed_quarter',
      is_perp: true,
    });
    const byKey = Object.fromEntries(rows.map((r) => [r.key, r]));
    const season = byKey.points_season_count;
    const tge = byKey.tge_clarity;
    const perp = byKey.is_perp;
    assert.ok(season && tge && perp);
    assert.equal(season.display, '4 季');
    assert.equal(season.observed, true);
    assert.equal(season.tone, 'watch');
    assert.equal(tge.display, '已确认·季度锚定');
    assert.equal(tge.tone, 'pos');
    assert.equal(perp.display, '是');
    assert.equal(perp.tone, 'watch');
  });

  it('is_perp=false 是观测而非未观测（与后端「False 是观测」契约一致）', () => {
    const perp = structuredSignalRows({ is_perp: false }).find((r) => r.key === 'is_perp');
    assert.ok(perp);
    assert.equal(perp.observed, true);
    assert.equal(perp.display, '否');
    assert.equal(perp.tone, 'muted');
  });

  it('tge unannounced 是观测（后端默认档），脏枚举值按未观测处理', () => {
    const announced = structuredSignalRows({ tge_clarity: 'unannounced' }).find(
      (r) => r.key === 'tge_clarity',
    );
    assert.ok(announced);
    assert.equal(announced.observed, true);
    const dirty = structuredSignalRows({ tge_clarity: 'maybe_quarter' }).find(
      (r) => r.key === 'tge_clarity',
    );
    assert.ok(dirty);
    assert.equal(dirty.observed, false);
  });

  it('season 超出后端钳制范围按未观测处理', () => {
    const season = structuredSignalRows({ points_season_count: 99 }).find(
      (r) => r.key === 'points_season_count',
    );
    assert.ok(season);
    assert.equal(season.observed, false);
  });

  it('tgeClarityZh 覆盖三档并透传未知值', () => {
    assert.equal(tgeClarityZh('confirmed_quarter'), '已确认·季度锚定');
    assert.equal(tgeClarityZh('vague_soon'), '模糊·仅称近期');
    assert.equal(tgeClarityZh('unannounced'), '未公布');
    assert.equal(tgeClarityZh('weird'), 'weird');
    assert.equal(tgeClarityZh(null), '');
  });
});

describe('structuredSignalBadges', () => {
  it('空/脏/未观测不出任何角标', () => {
    for (const sig of [
      undefined,
      null,
      {},
      { is_perp: false },
      { tge_clarity: 'unannounced' },
      { points_season_count: 1 },
      { is_perp: 'yes' },
      { points_season_count: 99 },
    ]) {
      assert.deepEqual(structuredSignalBadges(sig as Record<string, unknown>), []);
    }
  });

  it('perp 与多季出角标且带口径说明', () => {
    const badges = structuredSignalBadges({ is_perp: true, points_season_count: 4 });
    assert.equal(badges.length, 2);
    assert.ok(badges.every((b) => b.hint.includes('结构化信号')));
    const texts = badges.map((b) => b.text);
    assert.ok(texts.includes('永续盘'));
    assert.ok(texts.includes('4 季积分'));
  });

  it('单季（=1，与默认档等价）与 vague tge 不出角标', () => {
    assert.deepEqual(
      structuredSignalBadges({ points_season_count: 1, tge_clarity: 'vague_soon' }),
      [],
    );
  });

  it('confirmed tge 出正向角标', () => {
    const badges = structuredSignalBadges({ tge_clarity: 'confirmed_quarter' });
    assert.equal(badges.length, 1);
    assert.equal(badges[0]?.key, 'tge_clarity');
    assert.equal(badges[0]?.text, 'TGE 已锚定');
  });
});

describe('hasHighRiskStructuredSignal', () => {
  it('与 structuredSignalBadges 的 watch 侧同口径：perp 或多季算高危', () => {
    assert.equal(hasHighRiskStructuredSignal({ is_perp: true }), true);
    assert.equal(hasHighRiskStructuredSignal({ points_season_count: 2 }), true);
    assert.equal(hasHighRiskStructuredSignal({ points_season_count: 10 }), true);
    assert.equal(hasHighRiskStructuredSignal({ is_perp: true, points_season_count: 3 }), true);
  });

  it('非高危/未观测/脏类型返回 false', () => {
    assert.equal(hasHighRiskStructuredSignal(undefined), false);
    assert.equal(hasHighRiskStructuredSignal(null), false);
    assert.equal(hasHighRiskStructuredSignal({}), false);
    assert.equal(hasHighRiskStructuredSignal({ is_perp: false }), false);
    assert.equal(hasHighRiskStructuredSignal({ points_season_count: 1 }), false);
    assert.equal(hasHighRiskStructuredSignal({ is_perp: 'yes' }), false);
    assert.equal(hasHighRiskStructuredSignal({ points_season_count: 99 }), false);
  });

  it('confirmed tge 是利好侧，不算高危', () => {
    assert.equal(hasHighRiskStructuredSignal({ tge_clarity: 'confirmed_quarter' }), false);
  });
});

