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

/* ── 动态 API 内容中文化字典与解析器 (任务 #42) ── */

const REASONS_ZH_MAP: Record<string, string> = {
  // Positive reasons
  'strong airdrop signal': '明确的空投信号',
  'clear airdrop / points path': '清晰的空投/积分路径',
  'moderate airdrop signal': '中等强度的空投信号',
  'explicit airdrop mention': '官方明确提及空投',
  'verifiable task / points portal': '可验证的任务/积分门户',
  'multi-source evidence': '多源交叉证据支撑',
  'early narrative, high heat': '早期叙事，高热度',
  'early narrative': '早期叙事',
  'heated narrative, peak timing': '热门叙事，最佳时机',
  'peak narrative': '顶级叙事热度',
  'credible team': '团队背景可靠',
  'low competition': '赛道竞争较低',
  'active development / roadmap traction': '开发活跃/路线图扎实推进',
  'roadmap delivery looks aligned with shipping': '路线图交付与产品上线吻合',
  'strong public docs / social presence': '公开文档与社群活跃度高',
  'on-chain product / contract signal': '有链上产品/智能合约信号',
  'high evidence confidence': '证据置信度高',
  'tier-1 / high-quality funding': '顶级/高质量融资背景',
  'solid disclosed fundraising': '公开披露融资扎实',
  'recent funding signal': '近期有融资动态',
  'reputable vc backed': '知名风投机构参投',

  // Negative reasons
  'no airdrop signal': '无明显空投信号',
  'late narrative': '叙事热度滞后',
  'mature narrative, late timing': '叙事成熟，进入时机偏晚',
  'team risk: anonymous or prior failure': '团队风险：匿名或过往有失败记录',
  'elevated token structure risk': '代币经济学结构风险较高',
  'high token unlock pressure': '代币解锁抛压偏高',
  'high competition': '赛道竞争激烈',
  'weak execution signals (stale repo or no roadmap)': '执行信号偏弱（代码库停滞或无路线图）',
  'roadmap unclear vs shipping signals': '路线图交付进展不明确',
  'low transparency (thin docs/social)': '透明度较低（文档或社群匮乏）',
  'low data confidence': '数据置信度偏低',

  // Fallback pool reasons
  'airdrop signal detected': '检测到空投信号',
  'early-stage opportunity': '早期潜力机会',
  'mixed signals, monitor closely': '信号参差，保持密切观察',
  'insufficient standout signals': '缺乏显著优势信号',
  'weak overall signals': '整体信号偏弱',
  'limited airdrop evidence': '空投相关证据有限',

  // Eligibility gate reasons
  'token already launched with no verified follow-on airdrop path': '已发币且无可验证的后续空投路径',
  'team or official source explicitly disclaimed airdrop / token incentives': '团队或官方已明确否认空投/代币激励',
  'no verified testnet, points program, task portal, or explicit airdrop mention': '暂无可验证的测试网、积分体系、任务门户或官方空投声明',
};

export function reasonZh(r: string): string {
  if (!r) return '';
  const trimmed = r.trim();
  const lower = trimmed.toLowerCase();
  if (REASONS_ZH_MAP[lower]) {
    return REASONS_ZH_MAP[lower];
  }
  for (const [en, zh] of Object.entries(REASONS_ZH_MAP)) {
    if (lower === en.toLowerCase()) return zh;
  }
  return trimmed;
}

const BLOCKER_CODE_ZH: Record<string, string> = {
  SAFETY_BLOCK: '安全阻断',
  INTEGRITY_BLOCK: '数据完整性阻断',
  RULE_BLOCK: '规则限制阻断',
};

export function blockerCodeZh(code: string): string {
  return BLOCKER_CODE_ZH[code] || code;
}

const SEVERITY_ZH: Record<string, string> = {
  critical: '严重',
  high: '高',
  medium: '中',
  low: '低',
};

export function severityZh(sev?: string): string {
  if (!sev) return '';
  return SEVERITY_ZH[sev.toLowerCase()] || sev;
}

const FACTOR_KEY_ZH: Record<string, string> = {
  event_probability: '空投事件概率',
  eligibility_probability: '资格准入概率',
  survival_probability: '存活/防女巫概率',
  reward_probability: '奖励发放概率',
  conditional_reward_usd: '预期奖励 (USD)',
  conditional_reward: '预期奖励',
  hard_cost_usd: '硬性成本 (USD)',
  hard_cost: '硬性成本',
  weekly_maintenance_minutes: '每周维护时间 (分)',
  weekly_maintenance: '每周维护时间',
  participation_open: '参与通道开放',
  multiwallet_policy: '多钱包政策',
  distribution_catalyst_3_6m: '3-6个月分发催化剂',
  capital_at_risk_usd: '风险资金 (USD)',
  expected_capital_loss_usd: '预期资本损失 (USD)',
  liquidity_cost_usd: '流动性成本 (USD)',
  total_time_hours: '总耗时 (小时)',
  economics_direct_evidence: '经济学直接证据',
};

export function factorKeyZh(key: string): string {
  return FACTOR_KEY_ZH[key] || key;
}

const ACTION_REASON_ZH: Record<string, string> = {
  // Blocker actions
  SAFETY_BLOCK: '在可信整改证据核实前切勿交互。',
  INTEGRITY_BLOCK: '在可信整改证据核实前切勿交互。',
  RULE_BLOCK: '在官方规则明朗或完成整改前切勿交互。',

  // Watch reasons
  WAIT_TASK_OPEN: '等待官方参与通道开启后再行评估。',
  WAIT_RULES: '等待官方资格与多钱包规则明朗后再行评估。',
  WAIT_CATALYST: '关注 3-6 个月内的官方分发催化剂。',
  WAIT_COST_DROP: '等待推荐硬性成本回落至画像限额内。',
  WAIT_MORE_EVIDENCE: '针对未达标的 FARM 门槛收集更有力的独立证据。',
  WAIT_EARLY_ENTRY: '观察可参与的时间窗口或更清晰的资格路径。',
  REWARD_TOO_UNCERTAIN: '在参与前先核验保守收益预期。',
  SINGLE_WALLET_ONLY: '若官方规则允许，使用兼容的单钱包画像参与。',

  // Ignore reasons
  NEGATIVE_EXPECTED_VALUE: '在基准预期净收益为负时切勿参与。',
  DUST_REWARD: '在乐观预估收益仍微不足道时不建议参与。',
  TOO_EXPENSIVE: '当最低硬性成本超出当前画像承受能力时不参与。',
  TOO_TIME_INTENSIVE: '当最低维护时间超出当前画像设定时不参与。',
  TOO_LATE: '资格准入窗口关闭后切勿参与。',
  NO_AIRDROP_CASE: '在缺乏可行分发依据时不建议参与。',
  PROJECT_INACTIVE: '项目已确认处于非活跃状态，切勿参与。',
  PROFILE_MISMATCH: '在当前用户画像下不建议参与。',
};

export function reasonActionZh(msg: string, code?: string): string {
  if (code && ACTION_REASON_ZH[code]) {
    return ACTION_REASON_ZH[code];
  }
  if (!msg) return '';

  const missingMatch = msg.match(/^Provide verified evidence for critical factor (.+)\.$/i);
  if (missingMatch) {
    const factor = missingMatch[1].trim();
    const factorZh = factorKeyZh(factor);
    return `请为关键因子【${factorZh}】补齐核验证据。`;
  }

  for (const [c, zh] of Object.entries(ACTION_REASON_ZH)) {
    if (msg.includes(c)) return zh;
  }
  if (msg.includes('Do not interact until')) {
    return '在可信整改证据核实前切勿交互。';
  }
  return msg;
}

const RECOMMENDED_ACTION_ZH: Record<string, string> = {
  'run 1-2 wallets, record actual cost and time, then reassess before expanding.':
    '建议先运行 1-2 个钱包，记录实际成本与时间，再评估是否扩容。',
  'collect the missing critical evidence before participating.':
    '在参与前先补齐缺失的关键证据。',
  'do not allocate time or funds under the current profile.':
    '在当前画像下切勿投入时间或资金。',
  'do not interact until credible remediation evidence is verified.':
    '在可信整改证据核实前切勿交互。',
};

export function recommendedActionZh(act?: string | null): string {
  if (!act) return '';
  const lower = act.trim().toLowerCase();
  return RECOMMENDED_ACTION_ZH[lower] || act;
}

const FRESHNESS_ZH: Record<string, string> = {
  CURRENT: '有效',
  EXPIRED: '已过期',
};

export function freshnessZh(f?: string | null): string {
  if (!f) return '';
  return FRESHNESS_ZH[f.toUpperCase()] || f;
}

const SOURCE_TYPE_ZH: Record<string, string> = {
  official: '官方渠道',
  third_party: '第三方',
  on_chain: '链上数据',
  manual: '人工录入',
  community: '社群线索',
};

export function sourceTypeZh(t?: string | null): string {
  if (!t) return '';
  return SOURCE_TYPE_ZH[t.toLowerCase()] || t;
}

const VERIFICATION_STATUS_ZH: Record<string, string> = {
  verified: '已核实',
  unverified: '未核实',
  disputed: '有争议',
  rejected: '已驳回',
};

export function verificationStatusZh(s?: string | null): string {
  if (!s) return '';
  return VERIFICATION_STATUS_ZH[s.toLowerCase()] || s;
}

