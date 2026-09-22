'use client';

import { useEffect, useState } from 'react';
import { apiFetch } from '@/lib/api';

interface IlResult {
  initial_deposit_usd: number;
  price_change_pct: number;
  impermanent_loss_pct: number;
  impermanent_loss_usd: number;
  earned_fee_usd: number;
  net_pnl_usd: number;
  is_profitable: boolean;
  risk_evaluation: string;
}

interface LendingResult {
  collateral_asset: string;
  collateral_value_usd: number;
  borrowed_usd: number;
  health_factor: number;
  liquidation_price_usd: number;
  price_drop_to_liquidation_pct: number;
  status: string;
  action_advice: string;
  deleveraging_simulation: {
    repay_usd_to_reach_1_8_hf: number;
    add_eth_to_reach_1_8_hf: number;
  };
}

interface ImpermanentLossModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export default function ImpermanentLossModal({ isOpen, onClose }: ImpermanentLossModalProps) {
  const [activeTab, setActiveTab] = useState<'il' | 'lending'>('il');

  // IL inputs
  const [depositUsd, setDepositUsd] = useState(5000);
  const [priceChange, setPriceChange] = useState(30);
  const [isV3, setIsV3] = useState(true);
  const [feeApy, setFeeApy] = useState(25);
  const [days, setDays] = useState(30);
  const [ilResult, setIlResult] = useState<IlResult | null>(null);

  // Lending inputs
  const [ethAmount, setEthAmount] = useState(5);
  const [ethPrice, setEthPrice] = useState(3200);
  const [borrowUsd, setBorrowUsd] = useState(10000);
  const [lendingResult, setLendingResult] = useState<LendingResult | null>(null);

  const calcIl = async () => {
    try {
      const res = await apiFetch<{ data: IlResult }>('/il-sentinel/calculate-il', {
        method: 'POST',
        body: JSON.stringify({
          initial_deposit_usd: depositUsd,
          price_change_pct: priceChange,
          is_concentrated_v3: isV3,
          fee_apy_pct: feeApy,
          holding_days: days,
        }),
      });
      if (res?.data) setIlResult(res.data);
    } catch (e) {
      console.error('IL calculation failed', e);
    }
  };

  const calcLending = async () => {
    try {
      const res = await apiFetch<{ data: LendingResult }>('/il-sentinel/check-lending-health', {
        method: 'POST',
        body: JSON.stringify({
          collateral_asset: 'ETH',
          collateral_amount: ethAmount,
          collateral_price_usd: ethPrice,
          liquidation_threshold: 0.825,
          borrowed_usd: borrowUsd,
        }),
      });
      if (res?.data) setLendingResult(res.data);
    } catch (e) {
      console.error('Lending calculation failed', e);
    }
  };

  useEffect(() => {
    if (!isOpen) return;
    calcIl();
    calcLending();
  }, [isOpen]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm animate-fade-in">
      <div className="relative flex max-h-[92vh] w-full max-w-4xl flex-col rounded-2xl border border-line bg-surface p-6 shadow-2xl overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-line pb-4">
          <div className="flex items-center gap-2.5">
            <span className="text-2xl">📉</span>
            <div>
              <h3 className="text-lg font-bold text-ink">无常损失 (IL) 与借贷清算健康度预警机</h3>
              <p className="text-xs text-ink-muted">
                Uniswap V3 集中流动性净盈亏推演与 Aave / Mendi 借贷健康因子防清算红线预警
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

        {/* Tab Switcher */}
        <div className="flex gap-4 border-b border-line pt-4 text-xs font-semibold">
          <button
            type="button"
            onClick={() => setActiveTab('il')}
            className={`pb-2 ${
              activeTab === 'il'
                ? 'border-b-2 border-brand-500 text-brand-500'
                : 'text-ink-muted hover:text-ink'
            }`}
          >
            🦄 AMM 流动性无常损失测算 (IL)
          </button>
          <button
            type="button"
            onClick={() => setActiveTab('lending')}
            className={`pb-2 ${
              activeTab === 'lending'
                ? 'border-b-2 border-brand-500 text-brand-500'
                : 'text-ink-muted hover:text-ink'
            }`}
          >
            🏦 借贷加杠杆健康因子 (Health Factor)
          </button>
        </div>

        {/* Content */}
        <div className="my-4 flex-1 overflow-y-auto pr-1 space-y-4">
          {activeTab === 'il' ? (
            <div className="space-y-4">
              {/* Inputs */}
              <div className="p-4 rounded-xl border border-line bg-surface-2/40 space-y-3">
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                  <div>
                    <label className="text-[11px] text-ink-muted">存入 LP 本金 ($)</label>
                    <input
                      type="number"
                      value={depositUsd}
                      step={500}
                      onChange={(e) => {
                        setDepositUsd(Number(e.target.value));
                      }}
                      className="mt-1 w-full rounded-lg border border-line bg-surface p-2 text-xs font-mono text-ink"
                    />
                  </div>

                  <div>
                    <label className="text-[11px] text-ink-muted">价格偏离百分比 (%)</label>
                    <input
                      type="number"
                      value={priceChange}
                      onChange={(e) => {
                        setPriceChange(Number(e.target.value));
                      }}
                      className="mt-1 w-full rounded-lg border border-line bg-surface p-2 text-xs font-mono text-ink"
                    />
                  </div>

                  <div>
                    <label className="text-[11px] text-ink-muted">预期手续费年化 (%)</label>
                    <input
                      type="number"
                      value={feeApy}
                      onChange={(e) => {
                        setFeeApy(Number(e.target.value));
                      }}
                      className="mt-1 w-full rounded-lg border border-line bg-surface p-2 text-xs font-mono text-ink"
                    />
                  </div>

                  <div>
                    <label className="text-[11px] text-ink-muted">做市时长 (天)</label>
                    <input
                      type="number"
                      value={days}
                      onChange={(e) => {
                        setDays(Number(e.target.value));
                      }}
                      className="mt-1 w-full rounded-lg border border-line bg-surface p-2 text-xs font-mono text-ink"
                    />
                  </div>
                </div>

                <div className="flex items-center justify-between pt-1">
                  <label className="flex items-center gap-2 text-xs text-ink cursor-pointer">
                    <input
                      type="checkbox"
                      checked={isV3}
                      onChange={(e) => setIsV3(e.target.checked)}
                      className="rounded border-line"
                    />
                    <span>启用 Uniswap V3 集中流动性区间放大模拟</span>
                  </label>
                  <button
                    type="button"
                    onClick={calcIl}
                    className="btn-primary !py-1 !px-3 text-xs"
                  >
                    重新测算
                  </button>
                </div>
              </div>

              {/* IL Result Cards */}
              {ilResult && (
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                  <div className="p-3.5 rounded-xl border border-line bg-surface-2/40 text-center">
                    <div className="text-[10px] text-ink-muted">无常损失率</div>
                    <div className="text-lg font-bold font-mono text-red-400 mt-0.5">
                      -{ilResult.impermanent_loss_pct}%
                    </div>
                    <div className="text-[10px] text-ink-muted">-${ilResult.impermanent_loss_usd}</div>
                  </div>

                  <div className="p-3.5 rounded-xl border border-line bg-surface-2/40 text-center">
                    <div className="text-[10px] text-ink-muted">累计手续费收益</div>
                    <div className="text-lg font-bold font-mono text-emerald-400 mt-0.5">
                      +${ilResult.earned_fee_usd}
                    </div>
                    <div className="text-[10px] text-ink-muted">{days} 天收益</div>
                  </div>

                  <div className="p-3.5 rounded-xl border border-line bg-surface-2/40 text-center">
                    <div className="text-[10px] text-ink-muted">扣除 IL 净损益</div>
                    <div
                      className={`text-lg font-bold font-mono mt-0.5 ${
                        ilResult.net_pnl_usd >= 0 ? 'text-emerald-400' : 'text-red-400'
                      }`}
                    >
                      {ilResult.net_pnl_usd >= 0 ? `+$${ilResult.net_pnl_usd}` : `-$${Math.abs(ilResult.net_pnl_usd)}`}
                    </div>
                    <div className="text-[10px] text-ink-muted">Net PnL</div>
                  </div>

                  <div className="p-3.5 rounded-xl border border-line bg-surface-2/40 text-center">
                    <div className="text-[10px] text-ink-muted">做市可行性评估</div>
                    <div className="text-xs font-bold text-ink mt-2">
                      {ilResult.is_profitable ? '✅ 覆盖磨损' : '⚠️ 产生净亏损'}
                    </div>
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div className="space-y-4">
              {/* Lending Inputs */}
              <div className="p-4 rounded-xl border border-line bg-surface-2/40 space-y-3">
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                  <div>
                    <label className="text-[11px] text-ink-muted">抵押品数量 (ETH)</label>
                    <input
                      type="number"
                      value={ethAmount}
                      step={0.5}
                      onChange={(e) => setEthAmount(Number(e.target.value))}
                      className="mt-1 w-full rounded-lg border border-line bg-surface p-2 text-xs font-mono text-ink"
                    />
                  </div>
                  <div>
                    <label className="text-[11px] text-ink-muted">以太坊当前价格 ($)</label>
                    <input
                      type="number"
                      value={ethPrice}
                      step={50}
                      onChange={(e) => setEthPrice(Number(e.target.value))}
                      className="mt-1 w-full rounded-lg border border-line bg-surface p-2 text-xs font-mono text-ink"
                    />
                  </div>
                  <div>
                    <label className="text-[11px] text-ink-muted">已借出稳定币负债 ($)</label>
                    <input
                      type="number"
                      value={borrowUsd}
                      step={1000}
                      onChange={(e) => setBorrowUsd(Number(e.target.value))}
                      className="mt-1 w-full rounded-lg border border-line bg-surface p-2 text-xs font-mono text-ink"
                    />
                  </div>
                </div>
                <div className="flex justify-end pt-1">
                  <button
                    type="button"
                    onClick={calcLending}
                    className="btn-primary !py-1 !px-3 text-xs"
                  >
                    更新健康因子
                  </button>
                </div>
              </div>

              {/* Lending Result Cards */}
              {lendingResult && (
                <div className="space-y-3">
                  <div className="p-4 rounded-xl border border-line bg-surface-2/40 flex items-center justify-between">
                    <div>
                      <div className="text-xs text-ink-muted">健康因子 (Health Factor)</div>
                      <div className="flex items-baseline gap-2 mt-0.5">
                        <span
                          className={`text-3xl font-extrabold font-mono ${
                            lendingResult.health_factor >= 1.5
                              ? 'text-emerald-400'
                              : lendingResult.health_factor >= 1.25
                              ? 'text-amber-400'
                              : 'text-red-400'
                          }`}
                        >
                          {lendingResult.health_factor}
                        </span>
                        <span className="text-xs text-ink-muted font-mono">(及格线: 1.25)</span>
                      </div>
                      <div className="text-xs text-ink-muted mt-1">{lendingResult.action_advice}</div>
                    </div>

                    <div className="text-right p-3 rounded-lg bg-surface border border-line">
                      <div className="text-[10px] text-ink-muted">以太坊清算临界单价</div>
                      <div className="text-xl font-bold font-mono text-red-400 mt-0.5">
                        ${lendingResult.liquidation_price_usd.toLocaleString()}
                      </div>
                      <div className="text-[10px] text-ink-muted">
                        跌幅缓冲: <strong>{lendingResult.price_drop_to_liquidation_pct}%</strong>
                      </div>
                    </div>
                  </div>

                  {/* Deleveraging Plan */}
                  <div className="p-3.5 rounded-xl border border-line bg-surface-2/30 space-y-1.5 text-xs text-ink-muted">
                    <div className="font-bold text-ink text-xs">🛡️ 恢复至安全线 (HF 1.8) 紧急预案：</div>
                    <div>• 方案 A (还款): 提前偿还 <strong>${lendingResult.deleveraging_simulation.repay_usd_to_reach_1_8_hf}</strong> 稳定币负债；</div>
                    <div>• 方案 B (补仓): 补充抵押 <strong>{lendingResult.deleveraging_simulation.add_eth_to_reach_1_8_hf} ETH</strong>。</div>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="border-t border-line pt-3 flex items-center justify-between text-xs text-ink-muted">
          <span>提示：借贷质押博空投请始终将 Health Factor 保持在 1.5 以上，以避免黑天鹅插针被清算。</span>
          <button type="button" onClick={onClose} className="btn-secondary !py-1 !px-4">
            关闭
          </button>
        </div>
      </div>
    </div>
  );
}
