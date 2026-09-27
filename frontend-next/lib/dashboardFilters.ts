import type { Label } from './types';

/**
 * 工作台筛选状态与 URL 的双向序列化。
 *
 * 为什么独立成模块：筛选键有 16 个，解析校验与「只写非默认值」的序列化规则
 * 都是纯逻辑，放组件里没法进 node:test（本仓库前端测试跑在 node:test 上，
 * 不渲染 React）。抽出来后 parse/serialize 的往返一致性、非法值回退默认
 * 都有测试钉住。
 *
 * 契约：
 * - URL 里只出现**非默认值**（URL 保持干净，分享链接短）
 * - 非法值（label=FOO / sort=foo-bar / view=mobile）一律回退默认，不抛错
 * - 布尔开关：默认 true 的（hideignore / hidehighrisk）只在关闭时写 `=0`；
 *   默认 false 的只在开启时写 `=1`
 * - DASHBOARD_FILTER_KEYS 是工作台页「接管」的键集合：写 URL 前先整组删掉
 *   再按当前状态重写，其余键（persona 等他处管理的）原样保留
 * - localStorage（跨会话记忆）：只存 canonical pairs（与 URL 同一条校验路径），
 *   keyword 刻意不入库；恢复时逐键让位给 URL（URL 优先）
 */

export type SortBy = 'score' | 'name' | 'confidence';
export type ViewMode = 'grid' | 'table';

export interface DashboardFilters {
  keyword: string;
  label: Label | '';
  sector: string;
  stage: string;
  minScore: string;
  sortBy: SortBy;
  sortOrder: 'asc' | 'desc';
  view: ViewMode;
  hideIgnore: boolean;
  hideHighRisk: boolean;
  showSkipped: boolean;
  hasFundingOnly: boolean;
  zeroCostOnly: boolean;
  explicitAirdropOnly: boolean;
  highRiskSignalsOnly: boolean;
  needsVerifyOnly: boolean;
  curatedOnly: boolean;
}

export const DASHBOARD_FILTER_KEYS = [
  'keyword',
  'label',
  'sector',
  'stage',
  'min',
  'sort',
  'view',
  'hideignore',
  'showskipped',
  'hidehighrisk',
  'funding',
  'zerocost',
  'airdrop',
  'highrisk',
  'verify',
  'curated',
] as const;

export function defaultDashboardFilters(): DashboardFilters {
  return {
    keyword: '',
    label: '',
    sector: '',
    stage: '',
    minScore: '',
    sortBy: 'score',
    sortOrder: 'desc',
    view: 'grid',
    hideIgnore: true,
    hideHighRisk: true,
    showSkipped: false,
    hasFundingOnly: false,
    zeroCostOnly: false,
    explicitAirdropOnly: false,
    highRiskSignalsOnly: false,
    needsVerifyOnly: false,
    curatedOnly: false,
  };
}

/** 从任意 get(key) 读取（URLSearchParams.get 兼容），非法值一律回退默认。 */
export function parseDashboardFilters(get: (key: string) => string | null): DashboardFilters {
  const rawLabel = get('label');
  const [rawSortBy = '', rawSortOrder = ''] = (get('sort') || '').split('-');
  return {
    keyword: get('keyword') || '',
    label: rawLabel === 'FARM' || rawLabel === 'WATCH' || rawLabel === 'IGNORE' ? rawLabel : '',
    sector: get('sector') || '',
    stage: get('stage') || '',
    minScore: get('min') || '',
    sortBy: rawSortBy === 'name' || rawSortBy === 'confidence' ? rawSortBy : 'score',
    sortOrder: rawSortOrder === 'asc' ? 'asc' : 'desc',
    view: get('view') === 'table' ? 'table' : 'grid',
    hideIgnore: get('hideignore') !== '0',
    hideHighRisk: get('hidehighrisk') !== '0',
    showSkipped: get('showskipped') === '1',
    hasFundingOnly: get('funding') === '1',
    zeroCostOnly: get('zerocost') === '1',
    explicitAirdropOnly: get('airdrop') === '1',
    highRiskSignalsOnly: get('highrisk') === '1',
    needsVerifyOnly: get('verify') === '1',
    curatedOnly: get('curated') === '1',
  };
}

/** 序列化为键值对，只含非默认值（顺序稳定，便于测试与幂等写回）。 */
export function dashboardFilterSearchParams(f: DashboardFilters): [string, string][] {
  const out: [string, string][] = [];
  const put = (key: string, value: string, def: string) => {
    if (value !== def) out.push([key, value]);
  };
  put('keyword', f.keyword, '');
  put('label', f.label, '');
  put('sector', f.sector, '');
  put('stage', f.stage, '');
  put('min', f.minScore, '');
  put('sort', `${f.sortBy}-${f.sortOrder}`, 'score-desc');
  put('view', f.view, 'grid');
  put('hideignore', f.hideIgnore ? '1' : '0', '1');
  put('hidehighrisk', f.hideHighRisk ? '1' : '0', '1');
  put('showskipped', f.showSkipped ? '1' : '0', '0');
  put('funding', f.hasFundingOnly ? '1' : '0', '0');
  put('zerocost', f.zeroCostOnly ? '1' : '0', '0');
  put('airdrop', f.explicitAirdropOnly ? '1' : '0', '0');
  put('highrisk', f.highRiskSignalsOnly ? '1' : '0', '0');
  put('verify', f.needsVerifyOnly ? '1' : '0', '0');
  put('curated', f.curatedOnly ? '1' : '0', '0');
  return out;
}

/* ── 跨会话记忆（localStorage）──
 *
 * URL 与 localStorage 的分工：URL 是「这次视图」（分享/刷新用），storage 是
 * 「上次的手动选择」（无参打开时兜底恢复）。恢复合并逐键 URL 优先，因此：
 * 带参链接永远精确还原分享者的视图；无参打开则回到用户上次的筛选。
 */

/** v1 后缀留出 schema 演进空间；换结构时换键名，旧键自然废弃。 */
export const DASHBOARD_FILTERS_STORAGE_KEY = 'dashboard_filters_v1';

export type MinimalStorage = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;

/** 浏览器 localStorage 的安全取用：SSR / 隐私模式 / 被禁用时返回 null，调用方跳过即可。 */
export function browserStorage(): MinimalStorage | null {
  if (typeof window === 'undefined') return null;
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

/**
 * 实际会入库的 canonical pairs（keyword 不入库）。
 *
 * saveStoredFilters 与 UI 的「已记住偏好」提示共用本函数：保存的内容与提示的
 * 口径同源 —— 提示说「已记住」时，存储里就一定有这些键，永不漂移。
 */
export function storedFilterPairs(f: DashboardFilters): [string, string][] {
  return dashboardFilterSearchParams(f).filter(([key]) => key !== 'keyword');
}

/**
 * 读取上次保存的筛选 canonical pairs（未解析，键已白名单校验）。
 *
 * keyword 刻意不入库：顶栏搜索是易变意图，把一次搜索固化成跨会话默认，
 * 用户只会看到「为什么我每次进来都被过滤」。任何损坏/未知结构返回 null。
 */
export function loadStoredFilterPairs(storage: MinimalStorage | null | undefined): [string, string][] | null {
  if (!storage) return null;
  try {
    const raw = storage.getItem(DASHBOARD_FILTERS_STORAGE_KEY);
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed) || parsed.length === 0) return null;
    const pairs: [string, string][] = [];
    for (const entry of parsed) {
      if (!Array.isArray(entry) || entry.length !== 2) return null;
      const [key, value] = entry as unknown[];
      if (typeof key !== 'string' || typeof value !== 'string') return null;
      if (key === 'keyword') return null; // 历史脏数据：整批拒收，宁缺毋错
      if (!(DASHBOARD_FILTER_KEYS as readonly string[]).includes(key)) return null;
      pairs.push([key, value]);
    }
    return pairs;
  } catch {
    return null;
  }
}

/** 保存当前筛选（排除 keyword，见 storedFilterPairs）；全默认时清键不留垃圾。存储不可用/异常静默跳过。 */
export function saveStoredFilters(f: DashboardFilters, storage: MinimalStorage | null | undefined): void {
  if (!storage) return;
  try {
    const pairs = storedFilterPairs(f);
    if (pairs.length === 0) {
      storage.removeItem(DASHBOARD_FILTERS_STORAGE_KEY);
    } else {
      storage.setItem(DASHBOARD_FILTERS_STORAGE_KEY, JSON.stringify(pairs));
    }
  } catch {
    return;
  }
}
