'use client';

import { useEffect, useState } from 'react';
import { apiFetch } from '@/lib/api';
import { StatCard } from './ui';
import SellOffSimulatorModal from '@/components/SellOffSimulatorModal';

export function AirdropPnlPanel() {
  const [data, setData] = useState<any | null>(null);
  const [loading, setLoading] = useState(true);
  const [showAddModal, setShowAddModal] = useState(false);
  const [showSimulator, setShowSimulator] = useState(false);
  const [copiedTrophy, setCopiedTrophy] = useState(false);

  // 表单输入
  const [projectName, setProjectName] = useState('');
  const [tokenSymbol, setTokenSymbol] = useState('');
  const [amount, setAmount] = useState('');
  const [currentPrice, setCurrentPrice] = useState('');
  const [athPrice, setAthPrice] = useState('');
  const [gasSpent, setGasSpent] = useState('');
  const [notes, setNotes] = useState('');

  const fetchPnl = async () => {
    setLoading(true);
    try {
      const res = await apiFetch<any>('/pnl/summary');
      if (res?.ok) {
        setData(res);
      }
    } catch {
      // 捕获异常
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchPnl();
  }, []);

  const handleAddHarvest = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await apiFetch('/pnl/records', {
        method: 'POST',
        body: JSON.stringify({
          project_name: projectName,
          token_symbol: tokenSymbol.startsWith('$') ? tokenSymbol : `$${tokenSymbol}`,
          amount_claimed: Number(amount),
          current_price_usd: Number(currentPrice),
          ath_price_usd: Number(athPrice || currentPrice),
          gas_spent_usd: Number(gasSpent || 0),
          notes,
        }),
      });
      setShowAddModal(false);
      setProjectName('');
      setTokenSymbol('');
      setAmount('');
      setCurrentPrice('');
      setAthPrice('');
      setGasSpent('');
      setNotes('');
      fetchPnl();
    } catch {
      // 错误处理
    }
  };

  const copyTrophyReport = () => {
    if (!data) return;
    const text = `🏆 【Web3 空投猎人荣誉战绩单】\n` +
      `👑 荣誉段位：${data.hunter_tier_badge}\n` +
      `💰 累计落袋估值：$${data.total_current_value_usd.toLocaleString()} (历史峰值 $${data.total_ath_value_usd.toLocaleString()})\n` +
      `⛽ 投入总 Gas 成本：$${data.total_gas_spent_usd.toLocaleString()}\n` +
      `📈 真实净利润：+$${data.net_current_profit_usd.toLocaleString()}\n` +
      `🚀 综合投入产出比：${data.overall_roi_multiple}x 倍收益\n` +
      `🎯 击中优质项目数：${data.total_claimed_projects} 个\n` +
      `—— 来自 Web3 Airdrop Alpha Agent 实战复盘系统`;

    navigator.clipboard.writeText(text);
    setCopiedTrophy(true);
    setTimeout(() => setCopiedTrophy(false), 2500);
  };

  return (
    <div className="space-y-6 animate-fade-in">
      {/* 顶部荣誉卡片 */}
      <div className="rounded-2xl border border-brand-500/30 bg-gradient-to-r from-brand-500/15 via-surface-2 to-surface p-5 shadow-lg relative overflow-hidden">
        <div className="flex flex-col md:flex-row items-start md:items-center justify-between gap-4 relative z-10">
          <div>
            <div className="flex items-center gap-2">
              <span className="text-xl">🏆</span>
              <span className="text-xs font-mono font-bold uppercase tracking-wider text-brand-400">
                Airdrop Harvest & PnL Ledger
              </span>
              <span className="text-xs font-bold px-2.5 py-0.5 rounded-full bg-brand-500/20 text-brand-300 border border-brand-500/30">
                {data?.hunter_tier_badge || '段位评估中'}
              </span>
            </div>
            <h1 className="text-xl sm:text-2xl font-black text-ink mt-1.5 flex items-baseline gap-2">
              <span>实收净利润：</span>
              <span className="font-mono text-emerald-400">
                +${data ? data.net_current_profit_usd.toLocaleString() : '0'}
              </span>
              <span className="text-xs font-normal text-ink-muted">
                (全周期 Gas 投入产出比：<strong className="text-brand-400 font-mono">{data?.overall_roi_multiple || 0}x</strong>)
              </span>
            </h1>
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={copyTrophyReport}
              className="btn-secondary !py-2 text-xs flex items-center gap-1.5"
            >
              <span>{copiedTrophy ? '✅ 已复制战绩' : '📋 复制战绩海报'}</span>
            </button>
            <button
              type="button"
              onClick={() => setShowSimulator(true)}
              className="rounded-lg bg-emerald-600/20 hover:bg-emerald-600/30 border border-emerald-500/40 text-emerald-300 px-3 py-2 text-xs font-semibold flex items-center gap-1.5 transition"
            >
              <span>💰 止盈出局模拟器</span>
            </button>
            <button
              type="button"
              onClick={() => setShowAddModal(true)}
              className="btn-primary !py-2 text-xs flex items-center gap-1.5 shadow-md shadow-brand-500/20"
            >
              <span>+ 记一笔新到账空投</span>
            </button>
          </div>
        </div>
      </div>

      {/* 统计指标卡 */}
      <div className="stat-grid">
        <StatCard
          label="累计落袋现值"
          value={`$${data ? data.total_current_value_usd.toLocaleString() : '0'}`}
          accent="farm"
          hint={`历史峰值现值: $${data ? data.total_ath_value_usd.toLocaleString() : '0'}`}
        />
        <StatCard
          label="累计 Gas 消耗"
          value={`$${data ? data.total_gas_spent_usd.toLocaleString() : '0'}`}
          accent="watch"
          hint="多链交互总手续费支出"
        />
        <StatCard
          label="平均 Gas 收益倍数"
          value={`${data?.overall_roi_multiple || 0}x`}
          accent="brand"
          hint="以小博大平均杠杆倍数"
        />
        <StatCard
          label="落袋项目数"
          value={data?.total_claimed_projects || 0}
          accent="brand"
          hint="成功领到空投的协议数"
        />
      </div>

      {/* 历史到账清单 */}
      <div className="dash-card p-5 space-y-4">
        <div className="flex items-center justify-between border-b border-line pb-3">
          <span className="text-xs font-bold text-ink flex items-center gap-2">
            <span>📜</span>
            <span>已落袋空投资产流水与投入产出复盘</span>
          </span>
          <button
            type="button"
            onClick={fetchPnl}
            disabled={loading}
            className="text-xs text-brand-400 hover:text-brand-300 disabled:opacity-50"
          >
            {loading ? '刷新中...' : '刷新战报 ⟳'}
          </button>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-xs text-left">
            <thead>
              <tr className="border-b border-line text-[11px] text-ink-muted uppercase">
                <th className="py-2.5 px-3">项目与代币</th>
                <th className="py-2.5 px-3">领取数量</th>
                <th className="py-2.5 px-3">当前单价 / 现值</th>
                <th className="py-2.5 px-3">历史最高 ATH 估值</th>
                <th className="py-2.5 px-3">Gas 磨损成本</th>
                <th className="py-2.5 px-3">单项净赚 / RoI</th>
                <th className="py-2.5 px-3">领取日期</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line/50">
              {data?.records?.map((r: any) => (
                <tr key={r.id} className="hover:bg-surface-2/60 transition">
                  <td className="py-3 px-3 font-semibold text-ink">
                    <div>{r.project_name}</div>
                    <div className="font-mono text-brand-400 text-[11px]">{r.token_symbol}</div>
                  </td>
                  <td className="py-3 px-3 font-mono font-bold text-ink">
                    {r.amount_claimed.toLocaleString()}
                  </td>
                  <td className="py-3 px-3 font-mono">
                    <div className="text-ink">${r.current_value_usd.toLocaleString()}</div>
                    <div className="text-[10px] text-ink-faint">@ ${r.current_price_usd}</div>
                  </td>
                  <td className="py-3 px-3 font-mono text-ink-muted">
                    ${r.ath_value_usd.toLocaleString()}
                  </td>
                  <td className="py-3 px-3 font-mono text-rose-400">
                    -${r.gas_spent_usd}
                  </td>
                  <td className="py-3 px-3">
                    <div className="font-mono font-bold text-emerald-400">
                      +${r.net_profit_usd.toLocaleString()}
                    </div>
                    <span className="text-[10px] font-mono font-semibold px-1.5 py-0.5 rounded bg-brand-500/10 text-brand-300 border border-brand-500/20">
                      {r.gas_roi_multiple}x RoI
                    </span>
                  </td>
                  <td className="py-3 px-3 font-mono text-ink-faint text-[11px]">
                    {r.claimed_at}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* 新增空投弹窗 */}
      {showAddModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm animate-fade-in">
          <div className="dash-card w-full max-w-md p-6 shadow-2xl border-line bg-surface relative">
            <button
              type="button"
              onClick={() => setShowAddModal(false)}
              className="absolute top-4 right-4 text-ink-muted hover:text-ink text-sm"
            >
              ✕
            </button>
            <h3 className="text-sm font-bold text-ink mb-3 flex items-center gap-1.5">
              <span>🎁</span>
              <span>记录新到账空投代币</span>
            </h3>

            <form onSubmit={handleAddHarvest} className="space-y-3">
              <div>
                <label className="text-[11px] font-semibold text-ink-muted">项目名称</label>
                <input
                  type="text"
                  required
                  value={projectName}
                  onChange={(e) => setProjectName(e.target.value)}
                  placeholder="如 Berachain"
                  className="input text-xs w-full mt-1"
                />
              </div>

              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="text-[11px] font-semibold text-ink-muted">代币符号</label>
                  <input
                    type="text"
                    required
                    value={tokenSymbol}
                    onChange={(e) => setTokenSymbol(e.target.value)}
                    placeholder="$BERA"
                    className="input font-mono text-xs w-full mt-1"
                  />
                </div>
                <div>
                  <label className="text-[11px] font-semibold text-ink-muted">领取数量</label>
                  <input
                    type="number"
                    step="any"
                    required
                    value={amount}
                    onChange={(e) => setAmount(e.target.value)}
                    placeholder="1000"
                    className="input font-mono text-xs w-full mt-1"
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="text-[11px] font-semibold text-ink-muted">当前单价 (USD)</label>
                  <input
                    type="number"
                    step="any"
                    required
                    value={currentPrice}
                    onChange={(e) => setCurrentPrice(e.target.value)}
                    placeholder="2.5"
                    className="input font-mono text-xs w-full mt-1"
                  />
                </div>
                <div>
                  <label className="text-[11px] font-semibold text-ink-muted">消耗 Gas (USD)</label>
                  <input
                    type="number"
                    step="any"
                    value={gasSpent}
                    onChange={(e) => setGasSpent(e.target.value)}
                    placeholder="25"
                    className="input font-mono text-xs w-full mt-1"
                  />
                </div>
              </div>

              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setShowAddModal(false)}
                  className="btn-secondary !py-1.5 text-xs"
                >
                  取消
                </button>
                <button type="submit" className="btn-primary !py-1.5 text-xs">
                  确认录入
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* 空投止盈策略模拟器弹窗 */}
      <SellOffSimulatorModal isOpen={showSimulator} onClose={() => setShowSimulator(false)} />
    </div>
  );
}
