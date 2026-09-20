'use client';

import { apiFetch } from '@/lib/api';
import { safeExternalUrl } from '@/lib/format';
import { useCallback, useEffect, useState } from 'react';
import { CheckCircle2, Clock, ExternalLink, RefreshCw, Sparkles } from 'lucide-react';

export interface FaucetItem {
  id: string;
  name: string;
  chain: string;
  chain_name: string;
  url: string;
  requires_auth: boolean;
  cooldown_hours: number;
  description: string;
  daily_quota: string;
  status: 'ready' | 'cooling' | string;
  status_zh: string;
  remaining_seconds: number;
  remaining_human: string;
  last_claimed_at?: string | null;
  next_claim_at?: string | null;
}

interface FaucetsResponse {
  faucets: FaucetItem[];
  total: number;
  ready_count: number;
  cooling_count: number;
}

export function FaucetTrackerPanel() {
  const [faucets, setFaucets] = useState<FaucetItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [chainFilter, setChainFilter] = useState('all');
  const [actionBusy, setActionBusy] = useState<Record<string, boolean>>({});

  const loadFaucets = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const res = await apiFetch<FaucetsResponse>('/faucets');
      setFaucets(res.faucets || []);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '加载水龙头数据失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadFaucets();
  }, [loadFaucets]);

  const handleClaim = async (id: string) => {
    setActionBusy((prev) => ({ ...prev, [id]: true }));
    try {
      await apiFetch(`/faucets/${id}/claim`, { method: 'POST' });
      await loadFaucets();
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : '打卡记录失败');
    } finally {
      setActionBusy((prev) => ({ ...prev, [id]: false }));
    }
  };

  const handleReset = async (id: string) => {
    setActionBusy((prev) => ({ ...prev, [id]: true }));
    try {
      await apiFetch(`/faucets/${id}/claim`, { method: 'DELETE' });
      await loadFaucets();
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : '重置失败');
    } finally {
      setActionBusy((prev) => ({ ...prev, [id]: false }));
    }
  };

  const filteredFaucets = faucets.filter((f) => {
    if (chainFilter === 'all') return true;
    return f.chain.toLowerCase() === chainFilter.toLowerCase();
  });

  const readyCount = faucets.filter((f) => f.status === 'ready').length;
  const coolingCount = faucets.filter((f) => f.status === 'cooling').length;

  return (
    <div className="card space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line pb-3">
        <div className="flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-emerald-500/15 text-emerald-400">
            <Sparkles className="h-4 w-4" />
          </div>
          <div>
            <h2 className="text-sm font-semibold text-ink flex items-center gap-2">
              <span>测试网水龙头中心 (Faucet Hub)</span>
              <span className="badge bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 text-[10px]">
                100% 零成本
              </span>
            </h2>
            <p className="text-xs text-ink-muted">
              精选免 Key 优质水龙头，24h 冷却倒计时自动追踪，保本零成本交互首选。
            </p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2 text-xs">
            <span className="flex items-center gap-1 text-emerald-400">
              <span className="inline-block h-2 w-2 rounded-full bg-emerald-400" />
              可领: <strong>{readyCount}</strong>
            </span>
            <span className="text-ink-faint">|</span>
            <span className="flex items-center gap-1 text-amber-400">
              <span className="inline-block h-2 w-2 rounded-full bg-amber-400" />
              冷却中: <strong>{coolingCount}</strong>
            </span>
          </div>

          <button
            type="button"
            onClick={() => loadFaucets()}
            disabled={loading}
            className="btn-ghost text-xs p-1.5"
            title="刷新水龙头状态"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {/* Chain Filter Tabs */}
      <div className="flex flex-wrap items-center gap-1.5">
        {[
          { key: 'all', label: '全部网络' },
          { key: 'sepolia', label: 'Sepolia' },
          { key: 'arbitrum_sepolia', label: 'Arbitrum' },
          { key: 'base_sepolia', label: 'Base' },
          { key: 'berachain_bartio', label: 'Berachain' },
          { key: 'polygon_amoy', label: 'Polygon' },
        ].map((tab) => (
          <button
            key={tab.key}
            type="button"
            onClick={() => setChainFilter(tab.key)}
            className={`rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
              chainFilter === tab.key
                ? 'bg-ink text-surface shadow-sm'
                : 'bg-surface-2 text-ink-muted hover:bg-surface-3 hover:text-ink'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {error ? (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-xs text-red-400">
          {error}
        </div>
      ) : null}

      {/* Faucets List */}
      <div className="grid gap-3 sm:grid-cols-2">
        {filteredFaucets.map((faucet) => {
          const isCooling = faucet.status === 'cooling';
          const isBusy = actionBusy[faucet.id];
          const safeUrl = safeExternalUrl(faucet.url);

          return (
            <div
              key={faucet.id}
              className={`flex flex-col justify-between rounded-lg border p-3.5 transition-all ${
                isCooling
                  ? 'border-line/70 bg-surface-1/40 opacity-85'
                  : 'border-emerald-500/20 bg-surface-2 hover:border-emerald-500/40 shadow-sm'
              }`}
            >
              <div className="space-y-2">
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <span className="badge bg-surface-3 text-ink-faint text-[10px] font-mono">
                      {faucet.chain_name}
                    </span>
                    <h3 className="mt-1 text-sm font-semibold text-ink">{faucet.name}</h3>
                  </div>

                  {isCooling ? (
                    <span className="badge bg-amber-500/20 text-amber-300 border border-amber-500/30 text-[10px] flex items-center gap-1 font-mono">
                      <Clock className="h-3 w-3" />
                      {faucet.remaining_human}
                    </span>
                  ) : (
                    <span className="badge bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 text-[10px] flex items-center gap-1">
                      <CheckCircle2 className="h-3 w-3" />
                      可领取
                    </span>
                  )}
                </div>

                <p className="text-xs text-ink-muted">{faucet.description}</p>

                <div className="text-[11px] text-ink-faint">
                  单次额度: <span className="font-mono text-ink-muted">{faucet.daily_quota}</span>
                  {faucet.requires_auth ? (
                    <span className="ml-2 text-amber-400/80">(需登录验证)</span>
                  ) : (
                    <span className="ml-2 text-emerald-400/80">(免登录直接领)</span>
                  )}
                </div>
              </div>

              <div className="mt-3.5 flex items-center justify-between border-t border-line/50 pt-2.5">
                {safeUrl ? (
                  <a
                    href={safeUrl}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="inline-flex items-center gap-1 text-xs font-medium text-farm hover:underline"
                  >
                    <span>领水页面</span>
                    <ExternalLink className="h-3 w-3" />
                  </a>
                ) : (
                  <span />
                )}

                <div className="flex items-center gap-2">
                  {isCooling ? (
                    <button
                      type="button"
                      onClick={() => handleReset(faucet.id)}
                      disabled={isBusy}
                      className="btn-ghost text-[11px] py-1 px-2 text-ink-faint hover:text-ink"
                    >
                      重置
                    </button>
                  ) : (
                    <button
                      type="button"
                      onClick={() => handleClaim(faucet.id)}
                      disabled={isBusy}
                      className="btn-primary text-[11px] py-1 px-2.5"
                    >
                      {isBusy ? '打卡中...' : '标记已领'}
                    </button>
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
