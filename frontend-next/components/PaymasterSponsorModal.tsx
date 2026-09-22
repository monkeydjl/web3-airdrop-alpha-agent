'use client';

import { useEffect, useState } from 'react';
import { apiFetch } from '@/lib/api';

interface PaymasterCampaign {
  campaign_id: string;
  protocol: string;
  chain: string;
  chain_id: number;
  action_type: string;
  action_desc: string;
  provider: string;
  paymaster_address: string;
  sponsor_pool_remaining_eth: number;
  sponsor_pool_remaining_usd: number;
  is_active: boolean;
  eligibility_condition: string;
  gas_saved_per_tx_usd: number;
  app_url: string;
}

interface PaymasterSponsorModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export default function PaymasterSponsorModal({ isOpen, onClose }: PaymasterSponsorModalProps) {
  const [campaigns, setCampaigns] = useState<PaymasterCampaign[]>([]);
  const [loading, setLoading] = useState(false);
  const [testAddress, setTestAddress] = useState('0x71c505ea5815a5bb182f25b290919ea0ff4d3204');
  const [simResult, setSimResult] = useState<string | null>(null);

  useEffect(() => {
    if (!isOpen) return;
    setLoading(true);
    apiFetch<{ data: { sponsorships: PaymasterCampaign[] } }>('/paymaster/active-sponsorships')
      .then((res) => {
        if (res?.data?.sponsorships) {
          setCampaigns(res.data.sponsorships);
        }
      })
      .catch((err) => console.error('Failed to load paymaster sponsorships', err))
      .finally(() => setLoading(false));
  }, [isOpen]);

  const testEligibility = async (campaignId: string) => {
    try {
      const res = await apiFetch<{ data: { is_sponsored: boolean; verdict_notes: string } }>(
        '/paymaster/simulate-gasless-tx',
        {
          method: 'POST',
          body: JSON.stringify({
            campaign_id: campaignId,
            user_address: testAddress,
          }),
        }
      );
      if (res?.data) {
        setSimResult(res.data.verdict_notes);
      }
    } catch (e) {
      console.error('Test eligibility failed', e);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm animate-fade-in">
      <div className="relative flex max-h-[92vh] w-full max-w-4xl flex-col rounded-2xl border border-line bg-surface p-6 shadow-2xl overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-line pb-4">
          <div className="flex items-center gap-2.5">
            <span className="text-2xl">🛰️</span>
            <div>
              <h3 className="text-lg font-bold text-ink">账户抽象 EIP-4337 全链 Gas 赞助与 Paymaster 零成本雷达</h3>
              <p className="text-xs text-ink-muted">
                实时探测全网 100% 免 Gas 交互项目，打卡签到、DEX Swap 与勋章铸造零摩擦执行
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

        {/* Address Simulator Bar */}
        <div className="pt-4 flex flex-col sm:flex-row gap-2 items-center">
          <input
            type="text"
            value={testAddress}
            onChange={(e) => {
              setTestAddress(e.target.value);
              setSimResult(null);
            }}
            placeholder="输入钱包地址检测 AA 赞助资格"
            className="w-full sm:flex-1 rounded-xl border border-line bg-surface-2/60 px-3.5 py-2 text-xs font-mono text-ink"
          />
          <span className="text-xs text-ink-muted whitespace-nowrap">
            点击下方卡片即可为该地址校验
          </span>
        </div>

        {simResult && (
          <div className="mt-2 p-2.5 rounded-lg bg-brand-500/10 border border-brand-500/30 text-xs text-brand-400 flex items-center justify-between">
            <span>💡 {simResult}</span>
            <button
              type="button"
              onClick={() => setSimResult(null)}
              className="text-ink-muted hover:text-ink text-[11px]"
            >
              关闭
            </button>
          </div>
        )}

        {/* Content */}
        <div className="my-4 flex-1 overflow-y-auto pr-1 space-y-3">
          {loading ? (
            <div className="py-16 text-center text-sm text-ink-muted">正在探测全网活跃 Paymaster 补贴池…</div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {campaigns.map((c) => (
                <div
                  key={c.campaign_id}
                  className="p-4 rounded-xl border border-line bg-surface-2/40 hover:bg-surface-2/70 transition space-y-2.5 flex flex-col justify-between"
                >
                  <div>
                    <div className="flex items-start justify-between">
                      <div>
                        <div className="font-bold text-xs text-ink">{c.protocol}</div>
                        <span className="font-mono text-[10px] px-1.5 py-0.5 rounded bg-surface-3 text-ink-muted">
                          {c.chain}
                        </span>
                      </div>
                      <span className="px-2 py-0.5 rounded-full bg-emerald-500/15 text-emerald-400 font-mono text-[10px] font-bold">
                        100% 免 Gas
                      </span>
                    </div>

                    <div className="text-xs text-ink mt-2 font-medium">{c.action_desc}</div>
                    <div className="text-[11px] text-ink-muted mt-0.5">{c.eligibility_condition}</div>

                    <div className="mt-3 p-2 rounded bg-surface border border-line flex items-center justify-between text-[11px]">
                      <span className="text-ink-muted">补贴池剩余额度:</span>
                      <span className="font-mono font-bold text-emerald-400">
                        {c.sponsor_pool_remaining_eth} ETH (${c.sponsor_pool_remaining_usd.toLocaleString()})
                      </span>
                    </div>
                  </div>

                  <div className="pt-2 border-t border-line/60 flex items-center justify-between gap-2">
                    <button
                      type="button"
                      onClick={() => testEligibility(c.campaign_id)}
                      className="text-[11px] font-semibold text-brand-400 hover:underline"
                    >
                      🔍 校验免Gas资格
                    </button>
                    <a
                      href={c.app_url}
                      target="_blank"
                      rel="noreferrer"
                      className="btn-primary !py-1 !px-2.5 text-[11px] inline-flex items-center gap-1"
                    >
                      <span>前往参与</span>
                      <span>→</span>
                    </a>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="border-t border-line pt-3 flex items-center justify-between text-xs text-ink-muted">
          <span>提示：利用 ERC-4337 Paymaster 交互不仅零成本，还能积累高权重的账户抽象 (AA) 链上合约足迹。</span>
          <button type="button" onClick={onClose} className="btn-secondary !py-1 !px-4">
            关闭
          </button>
        </div>
      </div>
    </div>
  );
}
