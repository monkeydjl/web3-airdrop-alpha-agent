'use client';

import { apiFetch } from '@/lib/api';
import { useCallback, useEffect, useState } from 'react';
import { Calculator, TrendingUp, Clock, DollarSign, Sparkles, PieChart, ArrowUpRight } from 'lucide-react';
import Link from 'next/link';

interface PortfolioAllocation {
  project_id: string;
  project_name: string;
  score: number;
  role: string;
  allocated_budget_usd: number;
  allocated_hours_weekly: number;
  expected_multiple: number;
  expected_reward_usd: number;
  priority: string;
}

interface PortfolioSimulationData {
  total_budget_usd: number;
  weekly_hours: number;
  risk_appetite: string;
  allocations: PortfolioAllocation[];
  total_expected_return_usd: number;
  conservative_return_usd: number;
  optimistic_return_usd: number;
  portfolio_roi_multiple: number;
  monthly_hourly_yield_usd: number;
  summary_advice: string;
}

export function RoiSimulatorPanel() {
  const [budget, setBudget] = useState(300);
  const [hours, setHours] = useState(5);
  const [risk, setRisk] = useState<'balanced' | 'aggressive' | 'conservative'>('balanced');
  const [data, setData] = useState<PortfolioSimulationData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const runSimulation = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const res = await apiFetch<{ ok: boolean; data: PortfolioSimulationData }>(
        '/roi/simulate/portfolio',
        {
          method: 'POST',
          body: JSON.stringify({
            total_budget_usd: budget,
            weekly_hours: hours,
            risk_appetite: risk,
          }),
        },
      );
      if (res.data) {
        setData(res.data);
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '测算失败');
    } finally {
      setLoading(false);
    }
  }, [budget, hours, risk]);

  useEffect(() => {
    runSimulation();
  }, [runSimulation]);

  return (
    <div className="card space-y-5 p-4 sm:p-5">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line pb-3">
        <div className="flex items-center gap-2.5">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-500/15 text-brand-500">
            <Calculator className="h-4 w-4" />
          </div>
          <div>
            <h2 className="text-sm font-semibold text-ink flex items-center gap-2">
              <span>空投投前 ROI 收益预测与资本分配模拟器</span>
              <span className="badge bg-brand-500/15 text-brand-600 dark:text-brand-400 border border-brand-500/30 text-[10px]">
                投前量化测算
              </span>
            </h2>
            <p className="text-xs text-ink-muted">
              基于真实估值、TVL、空投池分配与背包算法，测算资金与时间投入的最优项目组合。
            </p>
          </div>
        </div>

        <button
          type="button"
          onClick={() => runSimulation()}
          disabled={loading}
          className="btn-secondary !py-1 text-xs flex items-center gap-1"
        >
          <Sparkles className={`h-3 w-3 ${loading ? 'animate-spin' : ''}`} />
          <span>{loading ? '测算中…' : '重新模拟'}</span>
        </button>
      </div>

      {/* Input Sliders */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 rounded-xl border border-line bg-surface-2/40 p-4">
        {/* Budget Slider */}
        <div className="space-y-2">
          <div className="flex items-center justify-between text-xs">
            <span className="font-medium text-ink flex items-center gap-1">
              <DollarSign className="h-3.5 w-3.5 text-emerald-500" />
              总资金预算 (Gas + 质押本金)
            </span>
            <span className="font-mono text-sm font-bold text-emerald-500">
              ${budget}
            </span>
          </div>
          <input
            type="range"
            min="20"
            max="3000"
            step="20"
            value={budget}
            onChange={(e) => setBudget(Number(e.target.value))}
            className="w-full accent-emerald-500 cursor-pointer"
          />
          <div className="flex justify-between text-[10px] text-ink-faint">
            <span>$20 (纯 Gas / 轻量)</span>
            <span>$500 (中度参与)</span>
            <span>$3,000 (重仓质押)</span>
          </div>
        </div>

        {/* Hours Slider */}
        <div className="space-y-2">
          <div className="flex items-center justify-between text-xs">
            <span className="font-medium text-ink flex items-center gap-1">
              <Clock className="h-3.5 w-3.5 text-brand-500" />
              每周可支配时间 (小时)
            </span>
            <span className="font-mono text-sm font-bold text-brand-500">
              {hours} 小时/周
            </span>
          </div>
          <input
            type="range"
            min="1"
            max="25"
            step="1"
            value={hours}
            onChange={(e) => setHours(Number(e.target.value))}
            className="w-full accent-brand-500 cursor-pointer"
          />
          <div className="flex justify-between text-[10px] text-ink-faint">
            <span>1h (佛系打卡)</span>
            <span>5h (精细化多号)</span>
            <span>25h (全职工作室)</span>
          </div>
        </div>
      </div>

      {error && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-xs text-red-400">
          {error}
        </div>
      )}

      {/* Projection Results */}
      {data && (
        <div className="space-y-4">
          {/* Metrics summary cards */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <div className="rounded-xl border border-line bg-surface p-3.5 space-y-1">
              <span className="text-[11px] text-ink-muted flex items-center gap-1">
                <TrendingUp className="h-3.5 w-3.5 text-brand-500" />
                基准预期总回报
              </span>
              <div className="text-xl font-bold font-mono text-ink">
                ${data.total_expected_return_usd}
              </div>
              <div className="text-[10px] text-ink-faint flex items-center justify-between">
                <span>悲观: ${data.conservative_return_usd}</span>
                <span>乐观: ${data.optimistic_return_usd}</span>
              </div>
            </div>

            <div className="rounded-xl border border-line bg-surface p-3.5 space-y-1">
              <span className="text-[11px] text-ink-muted flex items-center gap-1">
                <PieChart className="h-3.5 w-3.5 text-emerald-500" />
                资本回报倍数 (ROI)
              </span>
              <div className="text-xl font-bold font-mono text-emerald-500">
                {data.portfolio_roi_multiple}x
              </div>
              <div className="text-[10px] text-ink-faint">
                每投入 $1 预估捕获 ${data.portfolio_roi_multiple} 代币价值
              </div>
            </div>

            <div className="rounded-xl border border-line bg-surface p-3.5 space-y-1">
              <span className="text-[11px] text-ink-muted flex items-center gap-1">
                <Clock className="h-3.5 w-3.5 text-purple-500" />
                时间效率 (时薪折算)
              </span>
              <div className="text-xl font-bold font-mono text-purple-500">
                ~${data.monthly_hourly_yield_usd}/h
              </div>
              <div className="text-[10px] text-ink-faint">
                按月均投入总时间折算预期产出
              </div>
            </div>
          </div>

          {/* Allocation Recommendation Table */}
          <div className="rounded-xl border border-line overflow-hidden">
            <div className="bg-surface-2/60 px-3.5 py-2 border-b border-line text-xs font-semibold text-ink flex items-center justify-between">
              <span>推荐资本与时间最优分配方案 (基于当前活跃 FARM 库)</span>
              <span className="text-[11px] font-normal text-ink-muted">
                共推荐 {data.allocations.length} 个核心标的
              </span>
            </div>
            <div className="divide-y divide-line/60 bg-surface">
              {data.allocations.map((a) => (
                <div key={a.project_id} className="p-3.5 flex flex-col sm:flex-row sm:items-center justify-between gap-3 text-xs">
                  <div className="space-y-1">
                    <div className="flex items-center gap-2">
                      <Link
                        href={`/project/${a.project_id}`}
                        className="font-semibold text-ink hover:text-brand-500 transition-colors flex items-center gap-1"
                      >
                        <span>{a.project_name}</span>
                        <ArrowUpRight className="h-3 w-3 opacity-60" />
                      </Link>
                      <span className="rounded bg-surface-2 px-1.5 py-0.2 font-mono text-[10px] text-ink-muted">
                        评分 {a.score}
                      </span>
                    </div>
                    <div className="text-[11px] text-ink-muted">
                      {a.role}
                    </div>
                  </div>

                  <div className="flex flex-wrap items-center gap-4 text-ink-muted text-[11px] sm:text-right">
                    <div>
                      <span className="block text-ink-faint text-[10px]">分配资金</span>
                      <span className="font-mono font-semibold text-emerald-500">
                        ${a.allocated_budget_usd}
                      </span>
                    </div>
                    <div>
                      <span className="block text-ink-faint text-[10px]">每周精力</span>
                      <span className="font-mono font-semibold text-brand-500">
                        {a.allocated_hours_weekly}h
                      </span>
                    </div>
                    <div>
                      <span className="block text-ink-faint text-[10px]">预估产出</span>
                      <span className="font-mono font-semibold text-ink">
                        ~${a.expected_reward_usd}
                      </span>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Advice callout */}
          <div className="rounded-xl border border-brand-500/20 bg-brand-500/5 p-3.5 text-xs text-brand-600 dark:text-brand-400">
            <strong>智能配置建议：</strong> {data.summary_advice}
          </div>
        </div>
      )}
    </div>
  );
}
