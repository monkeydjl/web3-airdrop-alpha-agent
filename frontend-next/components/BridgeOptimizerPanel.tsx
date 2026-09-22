'use client';

import { useCallback, useEffect, useState } from 'react';
import { apiFetch } from '@/lib/api';
import { safeExternalUrl } from '@/lib/format';
import { ArrowRight, ArrowRightLeft, ExternalLink, ShieldCheck, Sparkles } from 'lucide-react';

interface BridgeChain {
  id: string;
  name: string;
  type: string;
  avg_gas_usd: number;
}

interface BridgeRoute {
  protocol_id: string;
  protocol_name: string;
  type: string;
  security_score: string;
  url: string;
  bridge_fee_usd: number;
  gas_cost_usd: number;
  total_cost_usd: number;
  duration_min: number;
  duration_human: string;
  token: string;
  amount: number;
}

interface BridgeRouteResult {
  source_chain: string;
  source_chain_name: string;
  target_chain: string;
  target_chain_name: string;
  token: string;
  amount: number;
  transfer_value_usd: number;
  routes: BridgeRoute[];
  cheapest_route: BridgeRoute | null;
  fastest_route: BridgeRoute | null;
  estimated_savings_usd: number;
  savings_percentage: number;
  sybil_safe_tips: string[];
}

export function BridgeOptimizerPanel() {
  const [chains, setChains] = useState<BridgeChain[]>([]);
  const [sourceChain, setSourceChain] = useState('arbitrum');
  const [targetChain, setTargetChain] = useState('base');
  const [token, setToken] = useState('ETH');
  const [amount, setAmount] = useState('0.5');

  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<BridgeRouteResult | null>(null);

  const fetchChains = useCallback(async () => {
    try {
      const res = await apiFetch<{ ok: boolean; chains: BridgeChain[] }>('/bridge/supported-chains');
      if (res?.chains) {
        setChains(res.chains);
      }
    } catch {
      // non-blocking
    }
  }, []);

  const calculateRoute = useCallback(async () => {
    setLoading(true);
    try {
      const res = await apiFetch<{ ok: boolean; data: BridgeRouteResult }>('/bridge/route', {
        method: 'POST',
        body: JSON.stringify({
          source_chain: sourceChain,
          target_chain: targetChain,
          token,
          amount: Number(amount) || 0.1,
        }),
      });
      if (res?.data) {
        setResult(res.data);
      }
    } catch {
      // non-blocking
    } finally {
      setLoading(false);
    }
  }, [sourceChain, targetChain, token, amount]);

  useEffect(() => {
    fetchChains();
    calculateRoute();
  }, [fetchChains, calculateRoute]);

  const handleSwapChains = () => {
    const prevSrc = sourceChain;
    setSourceChain(targetChain);
    setTargetChain(prevSrc);
  };

  return (
    <div className="dash-card p-5 space-y-6">
      {/* 头部标题与省钱横幅 */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-line pb-4">
        <div>
          <h2 className="text-sm font-bold text-ink flex items-center gap-2">
            <span className="text-brand-400">🔀</span>
            <span>全链跨链路由与低磨损资金规划器</span>
            <span className="badge bg-brand-500/15 text-brand-400 border border-brand-500/30 text-[10px]">
              省手续费 ~{result?.savings_percentage || 75}%
            </span>
          </h2>
          <p className="text-xs text-ink-muted mt-0.5">
            实时比对 Across、Stargate、Orbiter 等头部跨链桥，计算极低磨损归集路径与防女巫分批打散策略
          </p>
        </div>

        {result?.estimated_savings_usd ? (
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 text-xs">
            <Sparkles className="h-4 w-4 shrink-0" />
            <span>预计节省 <strong>${result.estimated_savings_usd}</strong> 磨损</span>
          </div>
        ) : null}
      </div>

      {/* 参数选择器 */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3 items-end">
        <div>
          <label className="text-[11px] font-medium text-ink-muted mb-1 block">源链 (From)</label>
          <select
            value={sourceChain}
            onChange={(e) => setSourceChain(e.target.value)}
            className="w-full bg-surface-2 border border-line rounded-lg px-3 py-2 text-xs text-ink focus:outline-none focus:border-brand"
          >
            {chains.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name} (~${c.avg_gas_usd} Gas)
              </option>
            ))}
          </select>
        </div>

        <div className="flex items-center gap-2">
          <div className="flex-1">
            <label className="text-[11px] font-medium text-ink-muted mb-1 block">目标链 (To)</label>
            <select
              value={targetChain}
              onChange={(e) => setTargetChain(e.target.value)}
              className="w-full bg-surface-2 border border-line rounded-lg px-3 py-2 text-xs text-ink focus:outline-none focus:border-brand"
            >
              {chains.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name} (~${c.avg_gas_usd} Gas)
                </option>
              ))}
            </select>
          </div>
          <button
            type="button"
            onClick={handleSwapChains}
            className="p-2 mt-5 rounded-lg bg-surface-2 hover:bg-surface-3 border border-line text-ink-muted hover:text-ink transition"
            title="对调网络"
          >
            <ArrowRightLeft className="h-4 w-4" />
          </button>
        </div>

        <div>
          <label className="text-[11px] font-medium text-ink-muted mb-1 block">转移代币 (Token)</label>
          <div className="flex rounded-lg border border-line overflow-hidden">
            {['ETH', 'USDC'].map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => setToken(t)}
                className={`flex-1 py-2 text-xs font-semibold transition ${
                  token === t ? 'bg-brand text-white' : 'bg-surface-2 text-ink-muted hover:text-ink'
                }`}
              >
                {t}
              </button>
            ))}
          </div>
        </div>

        <div>
          <label className="text-[11px] font-medium text-ink-muted mb-1 block">数量 (Amount)</label>
          <input
            type="number"
            step="0.01"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            className="w-full bg-surface-2 border border-line rounded-lg px-3 py-2 text-xs font-mono text-ink focus:outline-none focus:border-brand"
          />
        </div>

        <div>
          <button
            type="button"
            onClick={calculateRoute}
            disabled={loading}
            className="w-full btn-primary !py-2 text-xs flex items-center justify-center gap-1.5 shadow-sm"
          >
            <span>{loading ? '计算中…' : '重新计算路线'}</span>
            <ArrowRight className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      {/* 最佳路线双卡片 */}
      {result && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {result.cheapest_route && (
            <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/5 p-4 flex flex-col justify-between">
              <div>
                <div className="flex items-center justify-between">
                  <span className="badge bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 text-[10px] font-semibold">
                    🏆 极低磨损最佳路线 (Cheapest)
                  </span>
                  <span className="text-[10px] font-mono text-ink-muted">
                    安全评级: {result.cheapest_route.security_score}
                  </span>
                </div>
                <h3 className="text-base font-bold text-ink mt-2">
                  {result.cheapest_route.protocol_name}
                </h3>
                <p className="text-xs text-ink-muted mt-1">
                  总成本约 <strong className="text-emerald-400 font-mono text-sm">${result.cheapest_route.total_cost_usd}</strong>（含跨链费 ${result.cheapest_route.bridge_fee_usd} + 估算 Gas ${result.cheapest_route.gas_cost_usd}）
                </p>
              </div>
              <div className="mt-4 flex items-center justify-between border-t border-emerald-500/20 pt-3">
                <span className="text-xs text-ink-faint">
                  ⏱️ 耗时约 {result.cheapest_route.duration_human}
                </span>
                <a
                  href={safeExternalUrl(result.cheapest_route.url) ?? undefined}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-xs text-emerald-400 hover:text-emerald-300 font-medium flex items-center gap-1"
                >
                  <span>直达跨链桥</span>
                  <ExternalLink className="h-3 w-3" />
                </a>
              </div>
            </div>
          )}

          {result.fastest_route && (
            <div className="rounded-xl border border-cyan-500/30 bg-cyan-500/5 p-4 flex flex-col justify-between">
              <div>
                <div className="flex items-center justify-between">
                  <span className="badge bg-cyan-500/20 text-cyan-400 border border-cyan-500/30 text-[10px] font-semibold">
                    ⚡ 极速到账路线 (Fastest)
                  </span>
                  <span className="text-[10px] font-mono text-ink-muted">
                    安全评级: {result.fastest_route.security_score}
                  </span>
                </div>
                <h3 className="text-base font-bold text-ink mt-2">
                  {result.fastest_route.protocol_name}
                </h3>
                <p className="text-xs text-ink-muted mt-1">
                  总成本约 <strong className="text-cyan-400 font-mono text-sm">${result.fastest_route.total_cost_usd}</strong> · 极速意图结算
                </p>
              </div>
              <div className="mt-4 flex items-center justify-between border-t border-cyan-500/20 pt-3">
                <span className="text-xs text-ink-faint">
                  ⏱️ 耗时约 {result.fastest_route.duration_human}
                </span>
                <a
                  href={safeExternalUrl(result.fastest_route.url) ?? undefined}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-xs text-cyan-400 hover:text-cyan-300 font-medium flex items-center gap-1"
                >
                  <span>直达跨链桥</span>
                  <ExternalLink className="h-3 w-3" />
                </a>
              </div>
            </div>
          )}
        </div>
      )}

      {/* 跨链方案对比表 */}
      {result && result.routes.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-line">
          <table className="w-full text-left text-xs">
            <thead className="bg-surface-2 text-ink-muted border-b border-line">
              <tr>
                <th className="px-3.5 py-2.5 font-medium">协议</th>
                <th className="px-3.5 py-2.5 font-medium">跨链类型</th>
                <th className="px-3.5 py-2.5 font-medium">预估跨链费</th>
                <th className="px-3.5 py-2.5 font-medium">预估 Gas</th>
                <th className="px-3.5 py-2.5 font-medium font-bold text-ink">总预估磨损</th>
                <th className="px-3.5 py-2.5 font-medium">预估到账耗时</th>
                <th className="px-3.5 py-2.5 text-right font-medium">操作</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {result.routes.map((r) => {
                const isCheapest = r.protocol_id === result.cheapest_route?.protocol_id;
                return (
                  <tr key={r.protocol_id} className={`hover:bg-surface-2/60 transition ${isCheapest ? 'bg-emerald-500/5' : ''}`}>
                    <td className="px-3.5 py-2.5 font-medium text-ink flex items-center gap-1.5">
                      <span>{r.protocol_name}</span>
                      {isCheapest && <span className="text-[10px] text-emerald-400 font-bold">✓ 最省</span>}
                    </td>
                    <td className="px-3.5 py-2.5 text-ink-muted font-mono">{r.type}</td>
                    <td className="px-3.5 py-2.5 text-ink-muted font-mono">${r.bridge_fee_usd}</td>
                    <td className="px-3.5 py-2.5 text-ink-muted font-mono">${r.gas_cost_usd}</td>
                    <td className="px-3.5 py-2.5 font-mono font-bold text-ink">${r.total_cost_usd}</td>
                    <td className="px-3.5 py-2.5 text-ink-muted">{r.duration_human}</td>
                    <td className="px-3.5 py-2.5 text-right">
                      <a
                        href={safeExternalUrl(r.url) ?? undefined}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-xs text-brand hover:underline inline-flex items-center gap-0.5"
                      >
                        前往
                        <ExternalLink className="h-3 w-3" />
                      </a>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* 防女巫资金归集准则 */}
      {result?.sybil_safe_tips && (
        <div className="rounded-xl border border-brand-500/20 bg-brand-500/5 p-4 space-y-2">
          <div className="flex items-center gap-2 text-xs font-bold text-ink">
            <ShieldCheck className="h-4 w-4 text-brand-400" />
            <span>防女巫资金分散与多账号归集风控指南</span>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2 text-xs text-ink-muted">
            {result.sybil_safe_tips.map((tip, i) => (
              <div key={i} className="flex items-start gap-1.5">
                <span className="text-brand-400 font-bold">•</span>
                <span>{tip}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
