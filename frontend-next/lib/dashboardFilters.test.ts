import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import {
  dashboardFilterSearchParams,
  defaultDashboardFilters,
  parseDashboardFilters,
  DASHBOARD_FILTER_KEYS,
  type DashboardFilters,
} from './dashboardFilters.ts';

/** 便捷构造：从键值对数组读（模拟 URLSearchParams.get 行为，缺失键返回 null）。 */
function getter(pairs: [string, string][]) {
  const map = new Map(pairs);
  return (k: string) => map.get(k) ?? null;
}

describe('parseDashboardFilters', () => {
  it('空 URL 得到默认筛选（hideIgnore / hideHighRisk 默认 true）', () => {
    const f = parseDashboardFilters(() => null);
    assert.deepEqual(f, defaultDashboardFilters());
    assert.equal(f.hideIgnore, true);
    assert.equal(f.hideHighRisk, true);
  });

  it('解析全部合法键', () => {
    const f = parseDashboardFilters(
      getter([
        ['keyword', 'perp'],
        ['label', 'FARM'],
        ['sector', 'DEX'],
        ['stage', 'testnet'],
        ['min', '70'],
        ['sort', 'confidence-asc'],
        ['view', 'table'],
        ['hideignore', '0'],
        ['hidehighrisk', '0'],
        ['showskipped', '1'],
        ['showhidden', '1'],
        ['funding', '1'],
        ['zerocost', '1'],
        ['airdrop', '1'],
        ['highrisk', '1'],
        ['verify', '1'],
        ['curated', '1'],
      ]),
    );
    assert.equal(f.keyword, 'perp');
    assert.equal(f.label, 'FARM');
    assert.equal(f.sector, 'DEX');
    assert.equal(f.stage, 'testnet');
    assert.equal(f.minScore, '70');
    assert.equal(f.sortBy, 'confidence');
    assert.equal(f.sortOrder, 'asc');
    assert.equal(f.view, 'table');
    assert.equal(f.hideIgnore, false);
    assert.equal(f.hideHighRisk, false);
    assert.equal(f.showSkipped, true);
    assert.equal(f.showHidden, true);
    assert.equal(f.hasFundingOnly, true);
    assert.equal(f.zeroCostOnly, true);
    assert.equal(f.explicitAirdropOnly, true);
    assert.equal(f.highRiskSignalsOnly, true);
    assert.equal(f.needsVerifyOnly, true);
    assert.equal(f.curatedOnly, true);
  });

  it('非法值全部回退默认（label/sort/view/布尔非 0 非 1）', () => {
    const f = parseDashboardFilters(
      getter([
        ['label', 'FOO'],
        ['sort', 'foo-bar'],
        ['view', 'mobile'],
        ['showskipped', 'yes'],
        ['showhidden', 'true'],
        ['hideignore', 'off'],
      ]),
    );
    assert.equal(f.label, '');
    assert.equal(f.sortBy, 'score');
    assert.equal(f.sortOrder, 'desc');
    assert.equal(f.view, 'grid');
    assert.equal(f.showSkipped, false);
    assert.equal(f.showHidden, false);
    // hideignore 非 '0' 即视为开启（宽松读取，与 URLSearchParams 容错一致）
    assert.equal(f.hideIgnore, true);
  });
});

describe('dashboardFilterSearchParams', () => {
  it('默认筛选序列化为空（URL 只放非默认值）', () => {
    assert.deepEqual(dashboardFilterSearchParams(defaultDashboardFilters()), []);
  });

  it('只写非默认值', () => {
    const f = { ...defaultDashboardFilters(), label: 'WATCH' as const, minScore: '80', showSkipped: true };
    assert.deepEqual(dashboardFilterSearchParams(f), [
      ['label', 'WATCH'],
      ['min', '80'],
      ['showskipped', '1'],
    ]);
  });

  it('hideIgnore/hideHighRisk 只在关闭时写 =0', () => {
    const f = { ...defaultDashboardFilters(), hideIgnore: false, hideHighRisk: false };
    assert.deepEqual(dashboardFilterSearchParams(f), [
      ['hideignore', '0'],
      ['hidehighrisk', '0'],
    ]);
  });

  it('往返一致：parse(serialize(f)) === f', () => {
    const f: DashboardFilters = {
      ...defaultDashboardFilters(),
      keyword: 'x',
      label: 'IGNORE',
      highRiskSignalsOnly: true,
      hideHighRisk: false,
      view: 'table',
      sortBy: 'name',
      sortOrder: 'asc',
      showHidden: true,
    };
    const pairs = dashboardFilterSearchParams(f);
    assert.deepEqual(parseDashboardFilters(getter(pairs)), f);
  });
});

describe('DASHBOARD_FILTER_KEYS', () => {
  it('覆盖序列化器产出的全部键（整组重写不漏键）', () => {
    const f = { ...defaultDashboardFilters(), keyword: 'k', label: 'FARM' as const, sector: 's', stage: 't', minScore: '1', sortBy: 'name' as const, sortOrder: 'asc' as const, view: 'table' as const, hideIgnore: false, showSkipped: true, showHidden: true, hideHighRisk: false, hasFundingOnly: true, zeroCostOnly: true, explicitAirdropOnly: true, highRiskSignalsOnly: true, needsVerifyOnly: true, curatedOnly: true };
    const keys = dashboardFilterSearchParams(f).map(([k]) => k);
    for (const k of keys) {
      assert.ok(
        (DASHBOARD_FILTER_KEYS as readonly string[]).includes(k),
        `序列化产出的键 ${k} 不在 DASHBOARD_FILTER_KEYS 里`,
      );
    }
  });
});
