'use client';

import { useEffect, useState } from 'react';
import { apiFetch } from '@/lib/api';

interface PassportStamp {
  id: string;
  name: string;
  provider: string;
  category: string;
  weight: number;
  cost_usd: number;
  difficulty: string;
  guide: string;
}

interface IdentityEvaluation {
  wallet_address: string;
  passport_score: number;
  human_threshold: number;
  is_human_verified: boolean;
  tier: string;
  tier_description: string;
  active_stamps_count: number;
  missing_stamps_count: number;
  active_stamps: PassportStamp[];
  missing_stamps: PassportStamp[];
  recommended_next_stamps: PassportStamp[];
}

interface IdentityPassportModalProps {
  isOpen: boolean;
  onClose: () => void;
  initialWallet?: string;
}

export default function IdentityPassportModal({
  isOpen,
  onClose,
  initialWallet,
}: IdentityPassportModalProps) {
  const [wallet, setWallet] = useState(
    initialWallet || '0x71c505ea5815a5bb182f25b290919ea0ff4d3204'
  );
  const [data, setData] = useState<IdentityEvaluation | null>(null);
  const [guide, setGuide] = useState<PassportStamp[]>([]);
  const [loading, setLoading] = useState(false);
  const [activeTab, setActiveTab] = useState<'my_stamps' | 'guide'>('my_stamps');

  const evaluate = async (addr: string) => {
    if (!addr.trim()) return;
    setLoading(true);
    try {
      const [resEval, resGuide] = await Promise.all([
        apiFetch<{ data: IdentityEvaluation }>('/identity/evaluate', {
          method: 'POST',
          body: JSON.stringify({ wallet_address: addr }),
        }),
        apiFetch<{ data: { guide: PassportStamp[] } }>('/identity/stamping-guide'),
      ]);
      if (resEval?.data) setData(resEval.data);
      if (resGuide?.data?.guide) setGuide(resGuide.data.guide);
    } catch (e) {
      console.error('Failed to evaluate identity', e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!isOpen) return;
    evaluate(wallet);
  }, [isOpen]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm animate-fade-in">
      <div className="relative flex max-h-[92vh] w-full max-w-4xl flex-col rounded-2xl border border-line bg-surface p-6 shadow-2xl overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-line pb-4">
          <div className="flex items-center gap-2.5">
            <span className="text-2xl">🪪</span>
            <div>
              <h3 className="text-lg font-bold text-ink">链上人机身份凭证聚合与 Gitcoin Passport 戳记提升仪</h3>
              <p className="text-xs text-ink-muted">
                聚合 Gitcoin Passport, Linea POH, EAS 与 ENS 凭证，检测 20+ 分防女巫真人及格线
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1.5 text-ink-muted hover:bg-surface-2 hover:text-ink transition"
          >
            ✕
          </button>
        </div>

        {/* Search / Evaluate Bar */}
        <div className="pt-4 flex gap-2">
          <input
            type="text"
            value={wallet}
            onChange={(e) => setWallet(e.target.value)}
            placeholder="输入 EVM 钱包地址 (0x...)"
            className="flex-1 rounded-xl border border-line bg-surface-2/60 px-3.5 py-2 text-xs font-mono text-ink placeholder:text-ink-muted"
          />
          <button
            type="button"
            disabled={loading}
            onClick={() => evaluate(wallet)}
            className="btn-primary !py-2 !px-4 text-xs font-semibold"
          >
            {loading ? '评估中…' : '🔍 评估得分'}
          </button>
        </div>

        {/* Content */}
        <div className="my-4 flex-1 overflow-y-auto pr-1 space-y-4">
          {loading && !data ? (
            <div className="py-16 text-center text-sm text-ink-muted">正在连接各去中心化身份注册表…</div>
          ) : data ? (
            <>
              {/* Score Indicator Banner */}
              <div className="p-4 rounded-xl border border-line bg-surface-2/40 flex flex-col sm:flex-row items-center justify-between gap-4">
                <div className="flex items-center gap-4">
                  <div className="flex h-16 w-16 shrink-0 items-center justify-center rounded-2xl bg-surface border border-line font-mono font-bold">
                    <span
                      className={`text-2xl ${
                        data.passport_score >= 20 ? 'text-emerald-400' : 'text-amber-400'
                      }`}
                    >
                      {data.passport_score}
                    </span>
                  </div>
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-bold text-ink">综合人机凭证得分</span>
                      <span
                        className={`px-2 py-0.5 rounded-full text-[10px] font-bold ${
                          data.is_human_verified
                            ? 'bg-emerald-500/15 text-emerald-400'
                            : 'bg-amber-500/15 text-amber-400'
                        }`}
                      >
                        {data.is_human_verified ? '✓ 达到 20分 认证线' : '未达 20分 及格线'}
                      </span>
                    </div>
                    <div className="text-xs text-ink-muted mt-0.5">{data.tier_description}</div>
                  </div>
                </div>

                <div className="flex gap-4 text-center text-xs">
                  <div className="p-2 rounded bg-surface border border-line">
                    <div className="text-[10px] text-ink-muted">已激活戳记</div>
                    <div className="text-base font-bold font-mono text-emerald-400">
                      {data.active_stamps_count} 项
                    </div>
                  </div>
                  <div className="p-2 rounded bg-surface border border-line">
                    <div className="text-[10px] text-ink-muted">待补齐戳记</div>
                    <div className="text-base font-bold font-mono text-ink-muted">
                      {data.missing_stamps_count} 项
                    </div>
                  </div>
                </div>
              </div>

              {/* Quick Recommendations */}
              {!data.is_human_verified && data.recommended_next_stamps.length > 0 && (
                <div className="p-3.5 rounded-xl border border-brand-500/30 bg-brand-500/10 space-y-2">
                  <div className="text-xs font-bold text-brand-400 flex items-center gap-1.5">
                    <span>⚡ 极速冲刺 20分 盖戳捷径推荐 (低成本高权重)</span>
                  </div>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                    {data.recommended_next_stamps.map((st) => (
                      <div key={st.id} className="p-2.5 rounded-lg bg-surface/80 border border-line text-xs">
                        <div className="flex items-center justify-between">
                          <span className="font-semibold text-ink">{st.name}</span>
                          <span className="font-mono text-emerald-400 font-bold">+{st.weight} 分</span>
                        </div>
                        <div className="text-[10px] text-ink-muted mt-1">{st.guide}</div>
                        <div className="mt-1 text-[10px] font-mono text-ink-faint">
                          费用: {st.cost_usd === 0 ? '0 成本免费' : `$${st.cost_usd}`}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Tabs */}
              <div className="flex gap-4 border-b border-line text-xs font-semibold">
                <button
                  type="button"
                  onClick={() => setActiveTab('my_stamps')}
                  className={`pb-2 ${
                    activeTab === 'my_stamps'
                      ? 'border-b-2 border-brand-500 text-brand-500'
                      : 'text-ink-muted hover:text-ink'
                  }`}
                >
                  已点亮凭证 ({data.active_stamps.length})
                </button>
                <button
                  type="button"
                  onClick={() => setActiveTab('guide')}
                  className={`pb-2 ${
                    activeTab === 'guide'
                      ? 'border-b-2 border-brand-500 text-brand-500'
                      : 'text-ink-muted hover:text-ink'
                  }`}
                >
                  性价比盖戳指南 ({guide.length})
                </button>
              </div>

              {activeTab === 'my_stamps' ? (
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
                  {data.active_stamps.map((st) => (
                    <div
                      key={st.id}
                      className="p-3 rounded-xl border border-emerald-500/20 bg-emerald-500/5 flex items-start justify-between gap-2"
                    >
                      <div>
                        <div className="flex items-center gap-1.5">
                          <span className="text-emerald-400 font-bold">✓</span>
                          <span className="font-semibold text-xs text-ink">{st.name}</span>
                        </div>
                        <div className="text-[11px] text-ink-muted mt-0.5">{st.provider}</div>
                      </div>
                      <span className="font-mono text-xs font-bold text-emerald-400">+{st.weight}</span>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="space-y-2">
                  {guide.map((st) => (
                    <div
                      key={st.id}
                      className="p-3 rounded-xl border border-line bg-surface-2/40 flex items-center justify-between text-xs"
                    >
                      <div>
                        <div className="font-semibold text-ink">{st.name}</div>
                        <div className="text-[11px] text-ink-muted">{st.guide}</div>
                      </div>
                      <div className="text-right shrink-0">
                        <div className="font-mono font-bold text-brand-400">+{st.weight} 分</div>
                        <div className="text-[10px] text-ink-muted">
                          {st.cost_usd === 0 ? '免费' : `$${st.cost_usd}`}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </>
          ) : null}
        </div>

        {/* Footer */}
        <div className="border-t border-line pt-3 flex items-center justify-between text-xs text-ink-muted">
          <span>提示：绝大多数主流 L2 空投将 20 分设立为人机硬性门槛，建议重点点亮 GitHub, ZK-ID 与 Snapshot 凭证。</span>
          <button type="button" onClick={onClose} className="btn-secondary !py-1 !px-4">
            关闭
          </button>
        </div>
      </div>
    </div>
  );
}
