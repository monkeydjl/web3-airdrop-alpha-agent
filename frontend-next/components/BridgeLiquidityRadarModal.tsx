'use client';

import { useEffect, useState } from 'react';
import { apiFetch } from '@/lib/api';

interface BridgePool {
  bridge_id: string;
  bridge_name: string;
  route: string;
  asset: string;
  total_liquidity_usd: number;
  available_liquidity_usd: number;
  utilization_rate: number;
  avg_arrival_seconds: number;
  status: string;
  status_hint: string;
}

interface PeggedAsset {
  symbol: string;
  name: string;
  target_peg: string;
  current_rate: number;
  deviation_pct: number;
  status: string;
  risk_level: string;
  market_depth_usd: number;
}

interface RouteSimulation {
  from_chain: string;
  to_chain: string;
  asset: string;
  amount_usd: number;
  bridge_used: string;
  estimated_slippage_pct: number;
  estimated_loss_usd: number;
  net_received_usd: number;
  estimated_time_seconds: number;
  risk_tier: string;
  guidance: string;
  recommended_alternatives: { name: string; fee_est: string; time_est: string }[];
}

interface BridgeLiquidityRadarModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export default function BridgeLiquidityRadarModal({ isOpen, onClose }: BridgeLiquidityRadarModalProps) {
  const [pools, setPools] = useState<BridgePool[]>([]);
  const [peggedAssets, setPeggedAssets] = useState<PeggedAsset[]>([]);
  const [loading, setLoading] = useState(false);

  // Simulation form states
  const [simAmount, setSimAmount] = useState<number>(10000);
  const [simFrom, setSimFrom] = useState('Ethereum');
  const [simTo, setSimTo] = useState('Arbitrum');
  const [simAsset, setSimAsset] = useState('USDC');
  const [simulation, setSimulation] = useState<RouteSimulation | null>(null);
  const [simulating, setSimulating] = useState(false);

  useEffect(() => {
    if (!isOpen) return;
    setLoading(true);
    apiFetch<{ data: { bridge_pools: BridgePool[]; pegged_assets: PeggedAsset[] } }>(
      '/bridge-liquidity/overview'
    )
      .then((res) => {
        if (res?.data) {
          setPools(res.data.bridge_pools || []);
          setPeggedAssets(res.data.pegged_assets || []);
        }
      })
      .catch((err) => console.error('Failed to load bridge overview', err))
      .finally(() => setLoading(false));

    // Run initial simulation
    runSimulation(10000, 'Ethereum', 'Arbitrum', 'USDC');
  }, [isOpen]);

  const runSimulation = async (amount: number, from: string, to: string, asset: string) => {
    setSimulating(true);
    try {
      const res = await apiFetch<{ data: RouteSimulation }>('/bridge-liquidity/simulate-route', {
        method: 'POST',
        body: JSON.stringify({
          from_chain: from,
          to_chain: to,
          asset,
          amount_usd: amount,
          bridge_preference: 'across',
        }),
      });
      if (res?.data) {
        setSimulation(res.data);
      }
    } catch (e) {
      console.error('Simulation error', e);
    } finally {
      setSimulating(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm animate-fade-in">
      <div className="relative flex max-h-[92vh] w-full max-w-5xl flex-col rounded-2xl border border-line bg-surface p-6 shadow-2xl overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-line pb-4">
          <div className="flex items-center gap-2.5">
            <span className="text-2xl">💎</span>
            <div>
              <h3 className="text-lg font-bold text-ink">跨链桥流动性枯竭与脱锚风险雷达</h3>
              <p className="text-xs text-ink-muted">
                实时监控目标链储备深度、大额跨链滑点冲击、排队拥堵与 LRT / 稳定币脱锚风险
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

        {/* Content */}
        <div className="my-4 flex-1 overflow-y-auto pr-1 space-y-6">
          {loading ? (
            <div className="py-16 text-center text-sm text-ink-muted">正在同步全网跨链池与脱锚数据…</div>
          ) : (
            <>
              {/* Section 1: Route Slippage Simulator */}
              <div className="rounded-xl border border-brand-500/30 bg-gradient-to-br from-brand-500/10 via-surface-2/40 to-surface p-4">
                <div className="flex items-center justify-between mb-3">
                  <h4 className="text-sm font-bold text-ink flex items-center gap-1.5">
                    <span>⚡ 大额跨链资金滑点与枯竭推演器</span>
                  </h4>
                  <span className="text-[10px] font-mono text-ink-muted">
                    {simulating ? <span className="text-brand-400 animate-pulse">⚡ 实时推演中...</span> : 'Slippage & Drain Estimator'}
                  </span>
                </div>

                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5 mb-4">
                  <div>
                    <label className="text-[11px] text-ink-muted">源链 (From)</label>
                    <select
                      value={simFrom}
                      onChange={(e) => {
                        setSimFrom(e.target.value);
                        runSimulation(simAmount, e.target.value, simTo, simAsset);
                      }}
                      className="mt-1 w-full rounded-lg border border-line bg-surface p-2 text-xs text-ink"
                    >
                      <option value="Ethereum">Ethereum</option>
                      <option value="Arbitrum">Arbitrum</option>
                      <option value="Base">Base</option>
                      <option value="Optimism">Optimism</option>
                    </select>
                  </div>

                  <div>
                    <label className="text-[11px] text-ink-muted">目标链 (To)</label>
                    <select
                      value={simTo}
                      onChange={(e) => {
                        setSimTo(e.target.value);
                        runSimulation(simAmount, simFrom, e.target.value, simAsset);
                      }}
                      className="mt-1 w-full rounded-lg border border-line bg-surface p-2 text-xs text-ink"
                    >
                      <option value="Arbitrum">Arbitrum</option>
                      <option value="Base">Base</option>
                      <option value="Linea">Linea</option>
                      <option value="Optimism">Optimism</option>
                    </select>
                  </div>

                  <div>
                    <label className="text-[11px] text-ink-muted">资产 (Asset)</label>
                    <select
                      value={simAsset}
                      onChange={(e) => {
                        setSimAsset(e.target.value);
                        runSimulation(simAmount, simFrom, simTo, e.target.value);
                      }}
                      className="mt-1 w-full rounded-lg border border-line bg-surface p-2 text-xs text-ink"
                    >
                      <option value="USDC">USDC</option>
                      <option value="WETH">WETH / ETH</option>
                      <option value="USDT">USDT</option>
                    </select>
                  </div>

                  <div>
                    <label className="text-[11px] text-ink-muted">金额 ($ USD)</label>
                    <input
                      type="number"
                      value={simAmount}
                      step={1000}
                      onChange={(e) => {
                        const val = Number(e.target.value);
                        setSimAmount(val);
                        runSimulation(val, simFrom, simTo, simAsset);
                      }}
                      className="mt-1 w-full rounded-lg border border-line bg-surface p-2 text-xs font-mono text-ink"
                    />
                  </div>
                </div>

                {simulation && (
                  <div className="grid grid-cols-1 sm:grid-cols-4 gap-3 p-3 rounded-lg bg-surface/80 border border-line">
                    <div className="text-center">
                      <div className="text-[10px] text-ink-muted">预计滑点损耗</div>
                      <div className={`text-base font-bold font-mono ${simulation.estimated_slippage_pct > 0.3 ? 'text-amber-400' : 'text-emerald-400'}`}>
                        {simulation.estimated_slippage_pct}% (${simulation.estimated_loss_usd})
                      </div>
                    </div>

                    <div className="text-center">
                      <div className="text-[10px] text-ink-muted">净到账资金</div>
                      <div className="text-base font-bold font-mono text-ink">
                        ${simulation.net_received_usd.toLocaleString()}
                      </div>
                    </div>

                    <div className="text-center">
                      <div className="text-[10px] text-ink-muted">预估到账时效</div>
                      <div className="text-base font-bold font-mono text-cyan-400">
                        ~{Math.round(simulation.estimated_time_seconds / 60)} 分钟
                      </div>
                    </div>

                    <div className="text-center">
                      <div className="text-[10px] text-ink-muted">通道安全定级</div>
                      <div className="text-base font-bold font-mono text-brand-400">
                        {simulation.risk_tier}
                      </div>
                    </div>
                  </div>
                )}
                {simulation?.guidance && (
                  <div className="mt-2 text-xs text-ink-muted flex items-center gap-1.5">
                    <span>💡 {simulation.guidance}</span>
                  </div>
                )}
              </div>

              {/* Section 2: Bridge Pools Health Table */}
              <div>
                <h4 className="text-xs font-semibold text-ink-muted uppercase tracking-wider mb-2.5">
                  主流跨链桥通道与池子利用率 (Liquidity Pools)
                </h4>
                <div className="rounded-xl border border-line bg-surface-2/30 overflow-hidden">
                  <table className="w-full text-left text-xs">
                    <thead className="bg-surface-3/60 text-ink-muted text-[11px]">
                      <tr>
                        <th className="p-3">跨链桥与路径</th>
                        <th className="p-3">资产</th>
                        <th className="p-3">可用流动性</th>
                        <th className="p-3">资金池利用率</th>
                        <th className="p-3">时效与状态</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-line/60">
                      {pools.map((p, i) => {
                        const isHigh = p.utilization_rate > 0.8;
                        const isMed = p.utilization_rate > 0.5 && p.utilization_rate <= 0.8;
                        return (
                          <tr key={i} className="hover:bg-surface-2/60 transition">
                            <td className="p-3">
                              <div className="font-semibold text-ink">{p.bridge_name}</div>
                              <div className="text-[10px] font-mono text-ink-muted">{p.route}</div>
                            </td>
                            <td className="p-3 font-mono font-medium text-ink">{p.asset}</td>
                            <td className="p-3 font-mono">
                              ${(p.available_liquidity_usd / 1_000_000).toFixed(1)}M
                              <span className="text-[10px] text-ink-muted ml-1">
                                / ${(p.total_liquidity_usd / 1_000_000).toFixed(1)}M
                              </span>
                            </td>
                            <td className="p-3">
                              <div className="flex items-center gap-2">
                                <div className="h-1.5 w-24 bg-surface-3 rounded-full overflow-hidden">
                                  <div
                                    className={`h-full rounded-full ${
                                      isHigh ? 'bg-red-400' : isMed ? 'bg-amber-400' : 'bg-emerald-400'
                                    }`}
                                    style={{ width: `${Math.min(100, p.utilization_rate * 100)}%` }}
                                  />
                                </div>
                                <span className="font-mono text-[11px] text-ink">
                                  {(p.utilization_rate * 100).toFixed(0)}%
                                </span>
                              </div>
                            </td>
                            <td className="p-3">
                              <span
                                className={`px-2 py-0.5 rounded-full text-[10px] font-semibold ${
                                  p.status === 'HEALTHY'
                                    ? 'bg-emerald-500/15 text-emerald-400'
                                    : p.status === 'MODERATE_SLIPPAGE'
                                    ? 'bg-amber-500/15 text-amber-400'
                                    : 'bg-red-500/15 text-red-400'
                                }`}
                              >
                                {p.status}
                              </span>
                              <div className="text-[10px] text-ink-muted mt-0.5">{p.status_hint}</div>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>

              {/* Section 3: Pegged Assets & LRT Depeg Monitoring */}
              <div>
                <h4 className="text-xs font-semibold text-ink-muted uppercase tracking-wider mb-2.5">
                  LRT 重质押代币与合成资产脱锚监控 (Peg Defense)
                </h4>
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                  {peggedAssets.map((asset, i) => (
                    <div key={i} className="p-3.5 rounded-xl border border-line bg-surface-2/40 space-y-1.5">
                      <div className="flex items-center justify-between">
                        <span className="font-bold text-xs text-ink">{asset.name} ({asset.symbol})</span>
                        <span
                          className={`text-[10px] px-1.5 py-0.5 rounded font-semibold ${
                            asset.risk_level === 'LOW'
                              ? 'bg-emerald-500/15 text-emerald-400'
                              : 'bg-amber-500/15 text-amber-400'
                          }`}
                        >
                          {asset.status}
                        </span>
                      </div>
                      <div className="flex items-baseline justify-between pt-1">
                        <span className="text-[11px] text-ink-muted">当前比率:</span>
                        <span className="font-mono text-xs font-semibold text-ink">{asset.current_rate}</span>
                      </div>
                      <div className="flex items-baseline justify-between">
                        <span className="text-[11px] text-ink-muted">偏离率 (Deviation):</span>
                        <span
                          className={`font-mono text-xs font-bold ${
                            asset.deviation_pct < -0.2 ? 'text-amber-400' : 'text-emerald-400'
                          }`}
                        >
                          {asset.deviation_pct > 0 ? `+${asset.deviation_pct}%` : `${asset.deviation_pct}%`}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </>
          )}
        </div>

        {/* Footer */}
        <div className="border-t border-line pt-3 flex items-center justify-between text-xs text-ink-muted">
          <span>提示：跨链池利用率超过 85% 时，切忌一次性输入大额资金，可优先采用 Across 或分拆多次。</span>
          <button type="button" onClick={onClose} className="btn-secondary !py-1 !px-4">
            关闭
          </button>
        </div>
      </div>
    </div>
  );
}
