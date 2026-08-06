import type { Label } from './types';

/** 展示用中文标签（API 仍传 FARM/WATCH/IGNORE） */
export const LABEL_ZH: Record<Label, string> = {
  FARM: '重点参与',
  WATCH: '观察',
  IGNORE: '忽略',
};

export function labelZh(label: string): string {
  if (label in LABEL_ZH) return LABEL_ZH[label as Label];
  return label;
}

export function stageZh(stage?: string | null): string {
  if (!stage) return '—';
  const map: Record<string, string> = {
    ideation: '构想期',
    testnet: '测试网',
    mainnet: '主网',
    growth: '成长期',
    peak: '高峰期',
    mature: '成熟期',
    early: '早期',
    late: '后期',
  };
  return map[stage.toLowerCase()] || stage;
}

export function timingZh(timing?: string | null): string {
  if (!timing) return '—';
  const map: Record<string, string> = {
    early: '早期窗口',
    peak: '过热',
    late: '偏晚',
    growth: '上升期',
  };
  return map[timing.toLowerCase()] || timing;
}

export function riskLevelZh(level?: string | null): string {
  if (!level) return '—';
  const map: Record<string, string> = {
    high: '高',
    medium: '中',
    low: '低',
    unknown: '未知',
  };
  return map[level.toLowerCase()] || level;
}

export function teamTypeZh(t?: string | null): string {
  if (!t) return '—';
  const map: Record<string, string> = {
    doxxed: '实名',
    semi_anon: '半匿名',
    anon: '匿名',
    unknown: '未知',
  };
  return map[t.toLowerCase()] || t;
}

export function tierZh(tier?: string | null): string {
  switch ((tier || '').toLowerCase()) {
    case 'tier1':
      return '一线 VC';
    case 'tier2':
      return '二线 VC';
    case 'tier3':
      return '其他机构';
    case 'none':
      return '无融资';
    default:
      return '未知';
  }
}

export function sourceZh(source?: string | null): string {
  if (!source) return '—';
  const map: Record<string, string> = {
    defillama: 'DefiLlama',
    github: 'GitHub',
    coingecko: 'CoinGecko',
    cryptorank: 'CryptoRank',
    etherscan: 'Etherscan',
    twitter: 'Twitter',
    twitter_kol: 'Twitter KOL',
    twitter_keyword: 'Twitter 关键词',
    galxe: 'Galxe',
    layer3: 'Layer3',
    seed: '种子数据',
    manual: '手动',
  };
  return map[source.toLowerCase()] || source;
}

export function labelStyles(label: string): { badge: string; dot: string; text: string } {
  switch (label) {
    case 'FARM':
      return {
        badge: 'bg-farm-soft text-farm-dark dark:bg-farm/20 dark:text-farm',
        dot: 'bg-farm',
        text: 'text-farm-dark dark:text-farm',
      };
    case 'WATCH':
      return {
        badge: 'bg-watch-soft text-watch-dark dark:bg-watch/20 dark:text-watch',
        dot: 'bg-watch',
        text: 'text-watch-dark dark:text-watch',
      };
    default:
      return {
        badge: 'bg-ignore-soft text-ignore-dark dark:bg-ignore/20 dark:text-slate-300',
        dot: 'bg-ignore',
        text: 'text-ignore-dark dark:text-slate-300',
      };
  }
}

export function confColor(c: number): string {
  if (c >= 0.75) return 'text-farm-dark dark:text-farm';
  if (c >= 0.5) return 'text-watch-dark dark:text-watch';
  return 'text-red-500';
}

export function reasonTone(r: string): 'pos' | 'neg' | 'warn' | 'neutral' {
  const s = r.toLowerCase();
  if (
    s.includes('strong') ||
    s.includes('early') ||
    s.includes('low competition') ||
    s.includes('useful') ||
    s.startsWith('+')
  ) {
    return 'pos';
  }
  if (s.includes('high risk') || s.includes('high competition') || s.includes('no airdrop') || s.startsWith('-')) {
    return 'neg';
  }
  if (s.includes('uncertain') || s.includes('missing') || s.includes('weak') || s.startsWith('!')) {
    return 'warn';
  }
  return 'neutral';
}

export function formatPct(n: number, digits = 0): string {
  return `${(n * 100).toFixed(digits)}%`;
}

export function formatNumber(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return '—';
  return String(n);
}

export function relativeTime(iso?: string | null): string {
  if (!iso) return '—';
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return String(iso);
  const diff = Date.now() - t;
  const m = Math.floor(diff / 60000);
  if (m < 1) return '刚刚';
  if (m < 60) return `${m} 分钟前`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h} 小时前`;
  const d = Math.floor(h / 24);
  return `${d} 天前`;
}

export function sortProjects<T extends { score?: number; name?: string; confidence?: number }>(
  list: T[],
  by: 'score' | 'name' | 'confidence' = 'score',
  order: 'asc' | 'desc' = 'desc',
): T[] {
  const dir = order === 'asc' ? 1 : -1;
  return [...list].sort((a, b) => {
    if (by === 'name') return dir * String(a.name || '').localeCompare(String(b.name || ''));
    const av = Number(a[by] ?? 0);
    const bv = Number(b[by] ?? 0);
    return dir * (av - bv);
  });
}

export const LABEL_ORDER: Label[] = ['FARM', 'WATCH', 'IGNORE'];

/**
 * 安全外链：仅放行 http/https，拦截 javascript:/data: 等可执行伪协议，
 * 防止来自采集源（可控性弱）的项目 URL 触发存储型 XSS。
 * 返回 null 表示不可信，调用方应据此禁用/隐藏链接。
 */
export function safeExternalUrl(raw?: string | null): string | null {
  if (!raw) return null;
  const trimmed = String(raw).trim();
  if (!/^https?:\/\//i.test(trimmed)) return null;
  try {
    const u = new URL(trimmed);
    if (u.protocol === 'http:' || u.protocol === 'https:') return trimmed;
  } catch {
    return null;
  }
  return null;
}
