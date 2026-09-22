'use client';

import { useEffect, useRef, useState } from 'react';
import { apiFetch } from '@/lib/api';

interface ChainGas {
  chain: string;
  name: string;
  icon: string;
  symbol: string;
  gwei: number;
  status: 'cheap' | 'moderate' | 'expensive';
  status_zh: string;
  level_color: 'emerald' | 'amber' | 'rose';
  is_fallback?: boolean;
}

interface GasSummaryResponse {
  ok: boolean;
  chains: Record<string, ChainGas>;
  recommendations: {
    current_recommendation: string;
    best_weekly_windows: Array<{ period: string; savings: string; desc: string }>;
    high_friction_alert: string;
  };
  timestamp: number;
}

export function GasTrackerWidget() {
  const [data, setData] = useState<GasSummaryResponse | null>(null);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const fetchGas = async () => {
    setLoading(true);
    try {
      const res = await apiFetch<GasSummaryResponse>('/gas/summary');
      if (res && res.ok) {
        setData(res);
      }
    } catch {
      // 忽略前端异常
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchGas();
    const timer = setInterval(fetchGas, 30000); // 30秒轮询
    return () => clearInterval(timer);
  }, []);

  // 点击外部关闭弹层
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const eth = data?.chains?.ethereum;
  const dotColor = eth?.status === 'cheap' ? 'bg-emerald-400 animate-pulse' : eth?.status === 'moderate' ? 'bg-amber-400' : 'bg-rose-500 animate-ping';
  const badgeBorder = eth?.status === 'cheap' ? 'border-emerald-500/40 text-emerald-300 bg-emerald-500/10' : eth?.status === 'moderate' ? 'border-amber-500/40 text-amber-300 bg-amber-500/10' : 'border-rose-500/40 text-rose-300 bg-rose-500/10';

  return (
    <div className="relative" ref={containerRef}>
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className={`flex items-center gap-2 px-2.5 py-1 rounded-full border text-xs font-mono font-medium transition shadow-sm hover:brightness-110 ${badgeBorder}`}
        title="点击查看全链实时 Gas 与黄金时段预测"
      >
        <span className="flex items-center gap-1.5">
          <span className={`h-2 w-2 rounded-full ${dotColor}`} />
          <span>⛽ ETH {eth ? `${eth.gwei} Gwei` : '探测中...'}</span>
        </span>
        <span className="text-[10px] opacity-80 border-l border-current/30 pl-1.5 hidden sm:inline">
          {eth?.status_zh || '适宜交互'}
        </span>
      </button>

      {/* 弹层详情 */}
      {open && (
        <div className="absolute right-0 top-full mt-2 w-80 sm:w-96 rounded-2xl border border-line bg-surface-2 p-4 shadow-2xl z-50 animate-fade-in backdrop-blur-xl">
          <div className="flex items-center justify-between border-b border-line pb-2.5 mb-3">
            <div className="flex items-center gap-2">
              <span className="text-base">⛽</span>
              <span className="text-xs font-bold text-ink">全链实时 Gas 极佳交互雷达</span>
            </div>
            <button
              type="button"
              onClick={fetchGas}
              disabled={loading}
              className="text-[11px] text-brand-400 hover:text-brand-300 disabled:opacity-50"
            >
              {loading ? '刷新中...' : '立即刷新 ⟳'}
            </button>
          </div>

          {/* 各链列表 */}
          <div className="grid grid-cols-2 gap-2 mb-3">
            {data && Object.values(data.chains).map((c) => {
              const cColor = c.status === 'cheap' ? 'text-emerald-400 border-emerald-500/30 bg-emerald-500/10' : c.status === 'moderate' ? 'text-amber-400 border-amber-500/30 bg-amber-500/10' : 'text-rose-400 border-rose-500/30 bg-rose-500/10';
              return (
                <div key={c.chain} className={`p-2 rounded-xl border flex flex-col justify-between ${cColor}`}>
                  <div className="flex items-center justify-between text-xs">
                    <span className="font-semibold flex items-center gap-1">
                      <span>{c.icon}</span>
                      <span>{c.name}</span>
                    </span>
                    <span className="font-mono text-[10px] font-bold">{c.status_zh.split(' ')[0]}</span>
                  </div>
                  <div className="mt-1 text-right">
                    <span className="font-mono text-sm font-bold">{c.gwei}</span>
                    <span className="text-[10px] ml-1 opacity-75">Gwei</span>
                  </div>
                </div>
              );
            })}
          </div>

          {/* 交互建议与黄金窗口 */}
          {data?.recommendations && (
            <div className="space-y-2 text-[11px] pt-2 border-t border-line/60">
              <div className="p-2 rounded-lg bg-surface border border-line text-ink leading-relaxed">
                💡 <span className="font-semibold text-ink-muted">当前操作建议：</span>
                <span className="text-ink-strong">{data.recommendations.current_recommendation}</span>
              </div>
              <div className="p-2 rounded-lg bg-emerald-500/10 border border-emerald-500/20 text-emerald-300">
                <span className="font-bold">✨ 全周黄金低谷时段：</span>
                <ul className="list-disc list-inside mt-1 space-y-0.5 text-[10px]">
                  {data.recommendations.best_weekly_windows.map((w) => (
                    <li key={w.period}>
                      <strong>{w.period}</strong>：{w.savings} ({w.desc})
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
