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

/**
 * 部署阶段中文名 —— 对应 `projects.stage`，由采集器写入。
 *
 * **这张表只认部署口径**（`ideation` / `testnet` / `mainnet`）。
 * 此前它同时收录了叙事生命周期的 `growth` / `peak` / `mature` / `early` / `late`，
 * 于是「阶段」这两个字在界面上悄悄代表了两种完全不同的含义：
 * 一个说的是「代码上到哪张网了」，一个说的是「赛道热度处于周期哪一段」。
 * 一张表同时接受两套词汇，等于把口径错配变成了看不出来的错配 ——
 * 传错词汇不会显示原文，而是显示另一套口径下一个看着很合理的中文。
 * 叙事生命周期请用 `lifecycleStageZh`。
 */
export function stageZh(stage?: string | null): string {
  if (!stage) return '—';
  const map: Record<string, string> = {
    ideation: '构想期',
    testnet: '测试网',
    mainnet: '主网',
  };
  return map[stage.toLowerCase()] || stage;
}

/**
 * 叙事生命周期中文名 —— 对应 `NarrativeResult.stage`
 * （后端 pattern 限定 `early|growth|peak|mature`）。
 *
 * 与 `stageZh` 刻意分开：两者取值域不相交，混用必须显形。
 */
export function lifecycleStageZh(stage?: string | null): string {
  if (!stage) return '—';
  const map: Record<string, string> = {
    early: '早期',
    growth: '成长期',
    peak: '高峰期',
    mature: '成熟期',
  };
  return map[stage.toLowerCase()] || stage;
}

/**
 * 入场时机中文名 —— 对应 `NarrativeResult.timing`
 * （后端 pattern 限定 `early|peak|late`）。
 *
 * 曾经多一个 `growth: '上升期'` 条目。实测穷举 `stage_to_timing()` 的全部
 * 4 个合法输入，输出只可能是 `early` / `peak` / `late`，**`growth` 不可达** ——
 * 那一行是永远走不到的死代码，却让人以为系统还有第四种时机判断。
 */
export function timingZh(timing?: string | null): string {
  if (!timing) return '—';
  const map: Record<string, string> = {
    early: '早期窗口',
    peak: '过热',
    late: '偏晚',
  };
  return map[timing.toLowerCase()] || timing;
}

/**
 * 风险档位中文名。
 *
 * 覆盖范围**只有 low / medium / high** —— 实测四个调用点传进来的值都被后端
 * 约束在这三档：
 * - `team.risk_level`：`score_to_risk_level()` 穷举 0.00–1.00 全部取值，
 *   输出只有 high / medium / low
 * - `risk.sybil_difficulty` / `risk.farming_cost` / `risk.unlock_pressure`：
 *   `RiskResult` 三个字段的 pattern 都是 `^(low|medium|high)$`
 *
 * 曾经多一个 `unknown: '未知'` 条目 —— **不可达的死条目**，
 * 跟此前 `timingZh` 里那个 `growth` 是同一类问题：
 * 它让人以为系统还有第四种风险档位，而缺值走的是上面 `if (!level)` 那一支
 * 直接显示「—」，永远到不了这张表。
 *
 * ⚠️ 后端 `opportunity.models.RiskLevel` 还有第四档 `critical`，
 * 但它只出现在 `OpportunityAssessment.risks` 的 5 个维度里，
 * 而那 5 个维度**目前前端一处都没渲染**（实测 253 条评估记录里
 * 5 个维度全是 `null`，后端也还没在填）。真要展示 `risks` 时，
 * 必须先给 `critical` 补中文名和配色，否则会渲染成英文原文。
 * 这条由 `test_frontend_enum_parity.py::TestRiskLevelVocabulary` 钉住。
 */
export function riskLevelZh(level?: string | null): string {
  if (!level) return '—';
  const map: Record<string, string> = {
    high: '高',
    medium: '中',
    low: '低',
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

/**
 * 数据来源中文名。
 *
 * 覆盖范围必须与后端真的会写进 `projects.source` 的值一致，来源有三处：
 * 1. 各采集器的 `source_id`（`app/collectors/*.py` 里 `source_id="..."`）
 * 2. 种子数据 `seed`（`app/seed.py`）
 * 3. Excel/CSV 导入 `import`（`app/routers/v1/export_import.py`）
 *
 * 此前这张表**漏了 `rootdata` 和 `import`**，多了一个后端从不产出的 `manual`。
 * 漏掉的后果：导入的项目在详情页「数据来源」一栏显示英文 `import`，
 * rootdata 采到的项目显示 `rootdata`——中文界面里突然冒出原始标识。
 * 多出来的 `manual` 是死条目，且会让人以为系统支持手动录入。
 *
 * `backend/tests/test_frontend_enum_parity.py` 有断言把这张表和后端实际
 * 产出的来源集合钉在一起：后端加新采集器而这里没跟上，CI 会红。
 */
export function sourceZh(source?: string | null): string {
  if (!source) return '—';
  const map: Record<string, string> = {
    defillama: 'DefiLlama',
    github: 'GitHub',
    coingecko: 'CoinGecko',
    cryptorank: 'CryptoRank',
    rootdata: 'RootData',
    etherscan: 'Etherscan',
    twitter: 'Twitter',
    twitter_kol: 'Twitter KOL',
    twitter_keyword: 'Twitter 关键词',
    galxe: 'Galxe',
    layer3: 'Layer3',
    discord: 'Discord',
    reddit: 'Reddit',
    medium: 'Medium',
    mirror: 'Mirror',
    seed: '种子数据',
    import: '文件导入',
  };
  return map[source.toLowerCase()] || source;
}

export function labelStyles(label: string): { badge: string; dot: string; text: string } {
  switch (label) {
    case 'FARM':
      return {
        badge: 'bg-farm-soft text-farm dark:bg-farm/20 dark:text-farm',
        dot: 'bg-farm',
        text: 'text-farm dark:text-farm',
      };
    case 'WATCH':
      return {
        badge: 'bg-watch-soft text-watch dark:bg-watch/20 dark:text-watch',
        dot: 'bg-watch',
        text: 'text-watch dark:text-watch',
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
  if (c >= 0.75) return 'text-farm dark:text-farm';
  if (c >= 0.5) return 'text-watch dark:text-watch';
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
