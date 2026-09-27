import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import {
  DASHBOARD_FILTERS_STORAGE_KEY,
  dashboardFilterSearchParams,
  defaultDashboardFilters,
  loadStoredFilterPairs,
  saveStoredFilters,
  storedFilterPairs,
  type MinimalStorage,
} from './dashboardFilters.ts';

/** 内存 Storage 桩（node:test 无 window，注入用）。 */
function memoryStorage(initial: Record<string, string> = {}): MinimalStorage & { dump: () => Record<string, string> } {
  const map = new Map(Object.entries(initial));
  return {
    getItem: (k) => map.get(k) ?? null,
    setItem: (k, v) => void map.set(k, v),
    removeItem: (k) => void map.delete(k),
    dump: () => Object.fromEntries(map),
  };
}

/** 抛异常的 Storage 桩：QuotaExceeded / 隐私模式禁写。 */
function brokenStorage(): MinimalStorage {
  return {
    getItem: () => {
      throw new Error('blocked');
    },
    setItem: () => {
      throw new Error('QuotaExceeded');
    },
    removeItem: () => {
      throw new Error('blocked');
    },
  };
}

describe('loadStoredFilterPairs', () => {
  it('正常读回 canonical pairs', () => {
    const s = memoryStorage({
      [DASHBOARD_FILTERS_STORAGE_KEY]: JSON.stringify([['label', 'FARM'], ['highrisk', '1']]),
    });
    assert.deepEqual(loadStoredFilterPairs(s), [
      ['label', 'FARM'],
      ['highrisk', '1'],
    ]);
  });

  it('无存储 / 空串 / null 返回 null', () => {
    assert.equal(loadStoredFilterPairs(null), null);
    assert.equal(loadStoredFilterPairs(memoryStorage()), null);
    assert.equal(loadStoredFilterPairs(memoryStorage({ [DASHBOARD_FILTERS_STORAGE_KEY]: '' })), null);
  });

  it('keyword 键整批拒收（宁缺毋错）', () => {
    const s = memoryStorage({
      [DASHBOARD_FILTERS_STORAGE_KEY]: JSON.stringify([['label', 'FARM'], ['keyword', 'perp']]),
    });
    assert.equal(loadStoredFilterPairs(s), null);
  });

  it('未知键 / 非对数组 / 非 JSON 一律 null，绝不抛错', () => {
    const bad = [
      JSON.stringify([['evil_key', '1']]),
      JSON.stringify([['label']]),
      JSON.stringify([['label', 'FARM', 'extra']]),
      JSON.stringify([['label', 42]]),
      'not json',
      JSON.stringify({ label: 'FARM' }),
      JSON.stringify([]),
    ];
    for (const raw of bad) {
      const s = memoryStorage({ [DASHBOARD_FILTERS_STORAGE_KEY]: raw });
      assert.equal(loadStoredFilterPairs(s), null, `应拒收: ${raw}`);
    }
  });

  it('存储抛异常时返回 null', () => {
    assert.equal(loadStoredFilterPairs(brokenStorage()), null);
  });
});

describe('saveStoredFilters', () => {
  it('保存后可读回（经 save 的 canonical 路径）', () => {
    const s = memoryStorage();
    saveStoredFilters({ ...defaultDashboardFilters(), label: 'WATCH', hideHighRisk: false }, s);
    assert.deepEqual(loadStoredFilterPairs(s), [
      ['label', 'WATCH'],
      ['hidehighrisk', '0'],
    ]);
  });

  it('keyword 不入库', () => {
    const s = memoryStorage();
    saveStoredFilters({ ...defaultDashboardFilters(), keyword: 'perp', label: 'FARM' }, s);
    const pairs = loadStoredFilterPairs(s);
    assert.ok(pairs);
    assert.ok(pairs.every(([k]) => k !== 'keyword'));
  });

  it('全默认清键不留垃圾', () => {
    const s = memoryStorage({ [DASHBOARD_FILTERS_STORAGE_KEY]: JSON.stringify([['label', 'FARM']]) });
    saveStoredFilters(defaultDashboardFilters(), s);
    assert.equal(s.dump()[DASHBOARD_FILTERS_STORAGE_KEY], undefined);
  });

  it('存储不可用 / 写入异常静默跳过', () => {
    assert.doesNotThrow(() => saveStoredFilters(defaultDashboardFilters(), null));
    assert.doesNotThrow(() => saveStoredFilters({ ...defaultDashboardFilters(), label: 'FARM' }, brokenStorage()));
  });

  it('与 URL 序列化产物形状一致（同一条 canonical 路径）', () => {
    const f = { ...defaultDashboardFilters(), label: 'WATCH' as const, view: 'table' as const };
    const s = memoryStorage();
    saveStoredFilters(f, s);
    const stored = loadStoredFilterPairs(s);
    const fromUrl = dashboardFilterSearchParams(f);
    assert.deepEqual(stored, fromUrl.filter(([k]) => k !== 'keyword'));
  });

  it('storedFilterPairs 与 saveStoredFilters 实际入库内容同源', () => {
    const f = { ...defaultDashboardFilters(), keyword: 'perp', label: 'FARM' as const, hideHighRisk: false };
    const pairs = storedFilterPairs(f);
    assert.ok(pairs.every(([k]) => k !== 'keyword'));
    const s = memoryStorage();
    saveStoredFilters(f, s);
    assert.deepEqual(loadStoredFilterPairs(s), pairs);
    // 默认筛选入库集合为空 —— 「已记住偏好」提示以此为判定，不显示假提示
    assert.deepEqual(storedFilterPairs(defaultDashboardFilters()), []);
  });
});
