'use client';

import { useEffect, useState } from 'react';
import { apiFetch } from '@/lib/api';

interface WhaleBenchmark {
  airdrop_id: string;
  name: string;
  top_reward_tokens: string;
  active_months_required: number;
  total_txs_required: number;
  distinct_contracts_required: number;
  bridged_volume_usd_required: number;
  retained_balance_eth_required: number;
  key_actions: string[];
}

interface GapItem {
  dimension: string;
  user_val: string;
  whale_val: string;
  status: 'PASS' | 'GAP';
  gap_advice: string;
}

interface CompareResult {
  benchmark_used: string;
  target_project: string;
  match_score: number;
  match_tier: string;
  gap_analysis: GapItem[];
  action_plan_for_target: string[];
}

interface WhaleMirrorModalProps {
  isOpen: boolean;
  onClose: () => void;
  initialProjectName?: string;
}

export default function WhaleMirrorModal({
  isOpen,
  onClose,
  initialProjectName,
}: WhaleMirrorModalProps) {
  const [benchmarks, setBenchmarks] = useState<WhaleBenchmark[]>([]);
  const [selectedBenchmark, setSelectedBenchmark] = useState('arbitrum_top_tier');
  const [targetProject, setTargetProject] = useState(initialProjectName || 'Monad');

  // User input metrics
  const [months, setMonths] = useState(4);
  const [txs, setTxs] = useState(25);
  const [contracts, setContracts] = useState(12);
  const [bridgedUsd, setBridgedUsd] = useState(3200);
  const [retainedEth, setRetainedEth] = useState(0.02);

  const [compareResult, setCompareResult] = useState<CompareResult | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!isOpen) return;
    apiFetch<{ data: { benchmarks: WhaleBenchmark[] } }>('/whale-mirror/benchmarks')
      .then((res) => {
        if (res?.data?.benchmarks) {
          setBenchmarks(res.data.benchmarks);
        }
      })
      .catch((err) => console.error('Failed to load whale benchmarks', err));

    runCompare(selectedBenchmark, months, txs, contracts, bridgedUsd, retainedEth, targetProject);
  }, [isOpen]);

  const runCompare = async (
    bmId = selectedBenchmark,
    m = months,
    t = txs,
    c = contracts,
    v = bridgedUsd,
    b = retainedEth,
    p = targetProject
  ) => {
    setLoading(true);
    try {
      const res = await apiFetch<{ data: CompareResult }>('/whale-mirror/compare', {
        method: 'POST',
        body: JSON.stringify({
          benchmark_id: bmId,
          user_active_months: m,
          user_total_txs: t,
          user_contracts: c,
          user_bridged_usd: v,
          user_retained_eth: b,
          target_project: p,
        }),
      });
      if (res?.data) {
        setCompareResult(res.data);
      }
    } catch (e) {
      console.error('Failed to run whale compare', e);
    } finally {
      setLoading(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm animate-fade-in">
      <div className="relative flex max-h-[92vh] w-full max-w-4xl flex-col rounded-2xl border border-line bg-surface p-6 shadow-2xl overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-line pb-4">
          <div className="flex items-center gap-2.5">
            <span className="text-2xl">🧠</span>
            <div>
              <h3 className="text-lg font-bold text-ink">顶级空投巨鲸链上轨迹镜像与快照反推仪</h3>
              <p className="text-xs text-ink-muted">
                逆向复盘 Arbitrum / LayerZero / ZKsync 战神胜者模型，对标生成新项目满档作业
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
        <div className="my-4 flex-1 overflow-y-auto pr-1 space-y-5">
          {/* Controls Bar */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 p-3.5 rounded-xl border border-line bg-surface-2/40">
            <div>
              <label className="text-[11px] text-ink-muted">对标历史大毛战神基准</label>
              <select
                value={selectedBenchmark}
                onChange={(e) => {
                  setSelectedBenchmark(e.target.value);
                  runCompare(e.target.value, months, txs, contracts, bridgedUsd, retainedEth, targetProject);
                }}
                className="mt-1 w-full rounded-lg border border-line bg-surface p-2 text-xs text-ink font-semibold"
              >
                {benchmarks.map((b) => (
                  <option key={b.airdrop_id} value={b.airdrop_id}>
                    {b.name} ({b.top_reward_tokens})
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-[11px] text-ink-muted">目标发币作业项目</label>
              <input
                type="text"
                value={targetProject}
                onChange={(e) => {
                  setTargetProject(e.target.value);
                  runCompare(selectedBenchmark, months, txs, contracts, bridgedUsd, retainedEth, e.target.value);
                }}
                className="mt-1 w-full rounded-lg border border-line bg-surface p-2 text-xs text-ink font-semibold"
              />
            </div>
          </div>

          {/* User Metrics Inputs */}
          <div className="p-3.5 rounded-xl border border-line bg-surface-2/30">
            <div className="text-xs font-semibold text-ink-muted uppercase tracking-wider mb-2">
              当前目标钱包历史履历数据输入
            </div>
            <div className="grid grid-cols-2 sm:grid-cols-5 gap-2.5">
              <div>
                <label className="text-[10px] text-ink-muted">活跃月数</label>
                <input
                  type="number"
                  value={months}
                  min={1}
                  max={48}
                  onChange={(e) => {
                    const v = Number(e.target.value);
                    setMonths(v);
                    runCompare(selectedBenchmark, v, txs, contracts, bridgedUsd, retainedEth, targetProject);
                  }}
                  className="mt-1 w-full rounded border border-line bg-surface p-1.5 text-xs font-mono text-ink"
                />
              </div>
              <div>
                <label className="text-[10px] text-ink-muted">总交互笔数</label>
                <input
                  type="number"
                  value={txs}
                  min={1}
                  onChange={(e) => {
                    const v = Number(e.target.value);
                    setTxs(v);
                    runCompare(selectedBenchmark, months, v, contracts, bridgedUsd, retainedEth, targetProject);
                  }}
                  className="mt-1 w-full rounded border border-line bg-surface p-1.5 text-xs font-mono text-ink"
                />
              </div>
              <div>
                <label className="text-[10px] text-ink-muted">独立合约数</label>
                <input
                  type="number"
                  value={contracts}
                  min={1}
                  onChange={(e) => {
                    const v = Number(e.target.value);
                    setContracts(v);
                    runCompare(selectedBenchmark, months, txs, v, bridgedUsd, retainedEth, targetProject);
                  }}
                  className="mt-1 w-full rounded border border-line bg-surface p-1.5 text-xs font-mono text-ink"
                />
              </div>
              <div>
                <label className="text-[10px] text-ink-muted">跨链流水 ($)</label>
                <input
                  type="number"
                  value={bridgedUsd}
                  step={500}
                  onChange={(e) => {
                    const v = Number(e.target.value);
                    setBridgedUsd(v);
                    runCompare(selectedBenchmark, months, txs, contracts, v, retainedEth, targetProject);
                  }}
                  className="mt-1 w-full rounded border border-line bg-surface p-1.5 text-xs font-mono text-ink"
                />
              </div>
              <div>
                <label className="text-[10px] text-ink-muted">常驻余额 (ETH)</label>
                <input
                  type="number"
                  value={retainedEth}
                  step={0.01}
                  onChange={(e) => {
                    const v = Number(e.target.value);
                    setRetainedEth(v);
                    runCompare(selectedBenchmark, months, txs, contracts, bridgedUsd, v, targetProject);
                  }}
                  className="mt-1 w-full rounded border border-line bg-surface p-1.5 text-xs font-mono text-ink"
                />
              </div>
            </div>
          </div>

          {/* Compare Results */}
          {compareResult && (
            <div className="space-y-4">
              {/* Score Card */}
              <div className="p-4 rounded-xl border border-line bg-gradient-to-r from-brand-500/10 via-surface-2 to-surface flex items-center justify-between">
                <div>
                  <div className="text-xs text-ink-muted">巨鲸战神标准吻合度</div>
                  <div className="flex items-baseline gap-2 mt-0.5">
                    <span className="text-2xl font-extrabold font-mono text-brand-400">
                      {compareResult.match_score}%
                    </span>
                    <span className="text-xs font-semibold px-2 py-0.5 rounded bg-surface border border-line text-ink">
                      {compareResult.match_tier}
                    </span>
                  </div>
                </div>
                <div className="text-right text-xs text-ink-muted">
                  <div>对标基准: <strong className="text-ink">{compareResult.benchmark_used}</strong></div>
                  <div>目标作业: <strong className="text-brand-400">{compareResult.target_project}</strong></div>
                </div>
              </div>

              {/* Gap Analysis Table */}
              <div>
                <h4 className="text-xs font-semibold text-ink-muted uppercase tracking-wider mb-2">
                  核心 5 维指标差距与补刀建议 (Gap Analysis)
                </h4>
                <div className="rounded-xl border border-line bg-surface-2/30 overflow-hidden">
                  <table className="w-full text-left text-xs">
                    <thead className="bg-surface-3/60 text-ink-muted text-[11px]">
                      <tr>
                        <th className="p-3">指标维度</th>
                        <th className="p-3">当前数值</th>
                        <th className="p-3">巨鲸战神标准</th>
                        <th className="p-3">补齐建议</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-line/60">
                      {compareResult.gap_analysis.map((gap, idx) => (
                        <tr key={idx} className="hover:bg-surface-2/60 transition">
                          <td className="p-3 font-semibold text-ink">{gap.dimension}</td>
                          <td className="p-3 font-mono text-ink">{gap.user_val}</td>
                          <td className="p-3 font-mono text-brand-400">{gap.whale_val}</td>
                          <td className="p-3">
                            <span
                              className={`inline-block px-1.5 py-0.5 rounded text-[10px] font-bold mr-1.5 ${
                                gap.status === 'PASS'
                                  ? 'bg-emerald-500/15 text-emerald-400'
                                  : 'bg-amber-500/15 text-amber-400'
                              }`}
                            >
                              {gap.status === 'PASS' ? '✓ 达标' : '缺口'}
                            </span>
                            <span className="text-[11px] text-ink-muted">{gap.gap_advice}</span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              {/* Target Project Action Plan */}
              <div className="p-3.5 rounded-xl border border-line bg-surface-2/40 space-y-2">
                <h4 className="text-xs font-bold text-ink">
                  🎯 战神作业落地清单 (针对 {compareResult.target_project})
                </h4>
                <ul className="space-y-1.5 text-xs text-ink-muted">
                  {compareResult.action_plan_for_target.map((plan, i) => (
                    <li key={i} className="flex items-start gap-2">
                      <span className="text-brand-400 font-bold">•</span>
                      <span>{plan}</span>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="border-t border-line pt-3 flex items-center justify-between text-xs text-ink-muted">
          <span>提示：巨鲸钱包最大的特征是「高频跨月自然交互」与「充足的底仓留存」，绝非快照前突击刷单。</span>
          <button type="button" onClick={onClose} className="btn-secondary !py-1 !px-4">
            关闭
          </button>
        </div>
      </div>
    </div>
  );
}
