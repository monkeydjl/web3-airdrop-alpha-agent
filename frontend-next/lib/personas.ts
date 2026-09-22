import type { HunterPersona, HunterPersonaId } from './types';

export const HUNTER_PERSONAS: HunterPersona[] = [
  {
    id: 'balanced',
    name: '全能平衡模式',
    icon: '⚖️',
    tagline: '官方标准 8 维黄金配比',
    description: '均衡考量空投概率、项目叙事、团队履历、代币模型与安全风险，适合日常全面跟进与大多数参与者。',
    weights: {
      airdrop_signal: 0.2,
      narrative_timing: 0.15,
      team_reputation: 0.15,
      risk: 0.15,
      tokenomics: 0.15,
      execution: 0.1,
      transparency: 0.05,
      competition: 0.05,
    },
    badges: ['官方黄金比例', '稳健防坑', '全赛道兼顾'],
    key_factors: ['全方位综合表现', '团队信誉与风控平衡', '空投概率与发币时机'],
  },
  {
    id: 'zero_cost',
    name: '零成本测试网党',
    icon: '🎒',
    tagline: '0 本金低摩擦，专攻水龙头与测试网',
    description: '痛恨大额资金质押与 Gas 磨损，重度倾斜公开测试网、免费水龙头领水与清晰明牌任务路径，追求以小博大零资金风险。',
    weights: {
      airdrop_signal: 0.28,
      execution: 0.22,
      narrative_timing: 0.15,
      risk: 0.1,
      transparency: 0.1,
      team_reputation: 0.05,
      tokenomics: 0.05,
      competition: 0.05,
    },
    badges: ['0 本金测试网', '高频水龙头', '规避流动性质押'],
    key_factors: ['是否有公开测试网', '水龙头与任务指引健全度', '交互执行确定性与低门槛'],
  },
  {
    id: 'whale_restaking',
    name: '巨鲸质押生息党',
    icon: '💎',
    tagline: '本金绝对安全，主打顶流 VC 领投与高 TVL',
    description: '拥有充沛闲置资金，追求本金安全、顶级机构 (Paradigm/Pantera) 背书、真实 TVL 与重质押 (Restaking/LRT) 双重生息收益。',
    weights: {
      team_reputation: 0.25,
      risk: 0.2,
      tokenomics: 0.2,
      airdrop_signal: 0.15,
      execution: 0.1,
      transparency: 0.05,
      narrative_timing: 0.03,
      competition: 0.02,
    },
    badges: ['Tier-1 顶尖机构', '千万级高 TVL', '严控团队与合约风险'],
    key_factors: ['领投机构背景与知名度', '资金池与审计风控级别', '代币经济学分配与锁仓安全'],
  },
  {
    id: 'high_beta',
    name: '高弹性叙事追逐者',
    icon: '⚡',
    tagline: '风口浪尖抓催化剂，早期布局高爆发 Alpha',
    description: '敏锐嗅探加密前沿叙事（AI Agent、BTC L2、DePIN、并行 EVM），把握早期红利期，紧跟发币催化剂与爆发期。',
    weights: {
      narrative_timing: 0.3,
      airdrop_signal: 0.25,
      execution: 0.15,
      team_reputation: 0.1,
      tokenomics: 0.1,
      risk: 0.05,
      competition: 0.03,
      transparency: 0.02,
    },
    badges: ['新兴叙事龙头', '代币 TGE 窗口期', '超额爆发回报'],
    key_factors: ['叙事热度与窗口期 (Timing)', '代币分配与刺激预期', '早期上线爆发力'],
  },
];

export function getPersonaConfig(id: HunterPersonaId | string | null | undefined): HunterPersona {
  const found = HUNTER_PERSONAS.find((p) => p.id === id);
  return found || HUNTER_PERSONAS[0];
}

export type { HunterPersonaId };
