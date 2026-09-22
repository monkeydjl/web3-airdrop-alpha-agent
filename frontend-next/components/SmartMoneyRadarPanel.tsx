'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { apiFetch } from '@/lib/api';

export function SmartMoneyRadarPanel() {
  const [data, setData] = useState<any | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchFeed = async () => {
    setLoading(true);
    try {
      const res = await apiFetch<any>('/smart-money/feed');
      if (res?.ok) {
        setData(res);
      }
    } catch {
      // 异常捕获
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchFeed();
  }, []);

  return (
    <div className="dash-card p-5 space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-line pb-3">
        <div>
          <h2 className="text-sm font-bold text-ink flex items-center gap-2">
            <span>🌐</span>
            <span>聪明钱巨鲸潜伏与社交讨论爆发雷达</span>
          </h2>
          <p className="text-xs text-ink-muted mt-0.5">
            监控顶级 VC、加密领袖与头部空投工作室最新初次交互未知协议
          </p>
        </div>
        <button
          type="button"
          onClick={fetchFeed}
          disabled={loading}
          className="text-xs text-brand-400 hover:text-brand-300 disabled:opacity-50 self-start sm:self-auto"
        >
          {loading ? '刷新中...' : '刷新信号 ⟳'}
        </button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-5">
        {/* 左栏：聪明钱链上异动 */}
        <div className="lg:col-span-7 space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold text-ink flex items-center gap-1.5">
              <span>🐋</span>
              <span>巨鲸与头部机构最新潜伏动向</span>
            </span>
            <span className="text-[10px] font-mono text-ink-faint">
              监听中地址: {data?.tracked_whales_count || 4} 个
            </span>
          </div>

          <div className="space-y-2.5">
            {data?.smart_money_activities?.map((act: any) => (
              <div
                key={act.id}
                className="p-3.5 rounded-xl border border-line bg-surface-2/70 hover:bg-surface-2 transition space-y-1.5"
              >
                <div className="flex items-center justify-between text-xs">
                  <span className="font-semibold text-brand-400 flex items-center gap-1">
                    <span>{act.whale_label}</span>
                  </span>
                  <span className="font-mono text-[10px] text-ink-faint">{act.time_ago}</span>
                </div>

                <div className="text-xs text-ink font-bold flex items-center gap-2">
                  <span>目标协议:</span>
                  <span className="text-emerald-400 font-mono">{act.target_project}</span>
                  {act.est_value_usd > 0 && (
                    <span className="text-[10px] font-mono font-normal px-1.5 py-0.2 rounded bg-surface-3 text-ink-muted">
                      ≈ ${act.est_value_usd.toLocaleString()}
                    </span>
                  )}
                </div>

                <p className="text-[11px] text-ink-muted leading-relaxed">
                  {act.action}
                </p>

                <div className="text-[10px] text-brand-300 bg-brand-500/10 border border-brand-500/20 p-2 rounded-lg leading-relaxed">
                  💡 <strong>Agent 研判：</strong> {act.insight}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* 右栏：全网社交讨论爆发榜 */}
        <div className="lg:col-span-5 space-y-3">
          <span className="text-xs font-bold text-ink flex items-center gap-1.5">
            <span>🔥</span>
            <span>24h 社交讨论环比增速飙升榜</span>
          </span>

          <div className="rounded-xl border border-line bg-surface-2 divide-y divide-line/60 overflow-hidden text-xs">
            {data?.social_velocity_spikes?.map((sp: any, idx: number) => (
              <div key={sp.project_id} className="p-3 flex items-center justify-between hover:bg-surface-3/50 transition">
                <div className="space-y-0.5">
                  <div className="flex items-center gap-1.5 font-bold text-ink">
                    <span className="text-ink-faint font-mono text-[11px]">{idx + 1}.</span>
                    <Link
                      href={`/projects/${sp.project_id}`}
                      className="hover:text-brand-400 hover:underline transition"
                    >
                      {sp.project_name}
                    </Link>
                    <span className="text-[10px] font-mono text-ink-muted">({sp.sector})</span>
                  </div>
                  <div className="text-[10px] text-ink-faint">{sp.primary_narrative}</div>
                </div>

                <div className="text-right">
                  <span className="font-mono text-xs font-black text-rose-400 flex items-center gap-0.5">
                    <span>▲</span>
                    <span>+{sp.social_velocity_growth_pct}%</span>
                  </span>
                  <div className="text-[10px] text-ink-faint font-mono">24h 讨论增速</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
