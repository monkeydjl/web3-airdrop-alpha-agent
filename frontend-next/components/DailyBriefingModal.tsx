"use client";

import React, { useState, useEffect } from "react";
import { apiFetch } from "@/lib/api";

interface TopProject {
  id: string;
  name: string;
  sector: string;
  score: number;
  label: string;
  reason?: string;
  url?: string;
}

interface GasWindow {
  period: string;
  savings: string;
  desc: string;
}

interface UnlockItem {
  project_name: string;
  token_symbol: string;
  unlock_date: string;
  usd_value_estimate: number;
  circulating_supply_pct: number;
  pressure_rating: string;
}

interface WhaleSignal {
  whale_label: string;
  action: string;
  est_value_usd: number;
  time_ago: string;
}

interface BriefingData {
  ok: boolean;
  date: string;
  title: string;
  top_three_actions: string[];
  top_projects: TopProject[];
  gas_advice: string;
  weekly_windows: GasWindow[];
  imminent_unlocks: UnlockItem[];
  whale_signals: WhaleSignal[];
  markdown_content: string;
}

interface Props {
  isOpen: boolean;
  onClose: () => void;
}

export default function DailyBriefingModal({ isOpen, onClose }: Props) {
  const [data, setData] = useState<BriefingData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const fetchBriefing = async () => {
    setLoading(true);
    setError(null);
    try {
      const json = await apiFetch<BriefingData>("/daily-briefing/today");
      if (json?.ok) {
        setData(json);
      }
    } catch (e: any) {
      setError(e.message || "获取晚报失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (isOpen) {
      fetchBriefing();
    }
  }, [isOpen]);

  const handleCopyMarkdown = () => {
    if (data?.markdown_content) {
      navigator.clipboard.writeText(data.markdown_content);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm animate-fade-in">
      <div className="relative w-full max-w-3xl max-h-[90vh] overflow-y-auto rounded-2xl border border-slate-700 bg-slate-900 shadow-2xl p-6 text-slate-100 space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-slate-800 pb-4">
          <div className="flex items-center gap-3">
            <span className="text-2xl">📰</span>
            <div>
              <h3 className="text-lg font-bold text-slate-100">
                {data ? data.title : "今日链上 Alpha 晚报"}
              </h3>
              <p className="text-xs text-slate-400">
                24h 热门标的 · 48h 截止日历 · 明日 Gas 黄金时段 · 巨鲸异动全景摘要
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-800 hover:text-slate-100 transition"
          >
            ✕
          </button>
        </div>

        {loading ? (
          <div className="py-16 text-center text-slate-500 text-sm animate-pulse">
            正在聚合全网 24 小时链上情报与投研模型...
          </div>
        ) : error ? (
          <div className="rounded-lg bg-red-950/40 border border-red-800/60 p-3 text-xs text-red-300">
            {error}
          </div>
        ) : data ? (
          <div className="space-y-5">
            {/* Top 3 Actions Banner */}
            <div className="rounded-xl border border-indigo-500/40 bg-indigo-950/30 p-4 space-y-2.5">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2 text-xs font-bold text-indigo-300">
                  <span>🌟 次日极佳交互三大待办 (Top 3 Action Plan)</span>
                </div>
                <button
                  onClick={handleCopyMarkdown}
                  className="px-3 py-1 rounded bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-medium transition"
                >
                  {copied ? "✅ 已复制 Markdown" : "📋 复制晚报全文"}
                </button>
              </div>

              <div className="space-y-2">
                {data.top_three_actions.map((act, idx) => (
                  <div
                    key={idx}
                    className="p-2.5 rounded-lg bg-slate-900/60 border border-slate-800/80 text-xs text-slate-200"
                  >
                    {act}
                  </div>
                ))}
              </div>
            </div>

            {/* Top 3 Projects */}
            <div className="rounded-xl border border-slate-800 bg-slate-950/40 p-4 space-y-3">
              <div className="text-xs font-bold text-slate-300">
                💎 今日综合评分榜首标的 (Top Picks)
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                {data.top_projects.map((p, idx) => (
                  <div
                    key={idx}
                    className="p-3 rounded-lg border border-slate-800 bg-slate-900/50 space-y-1 text-xs"
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-bold text-slate-100">{p.name}</span>
                      <span className="px-1.5 py-0.5 rounded text-[10px] font-mono font-bold bg-emerald-500/20 text-emerald-300">
                        {p.score}分
                      </span>
                    </div>
                    <div className="text-[11px] text-slate-400">{p.sector}</div>
                  </div>
                ))}
              </div>
            </div>

            {/* Gas & Unlock Forecast Grid */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              {/* Gas Forecast */}
              <div className="p-4 rounded-xl border border-slate-800 bg-slate-950/40 space-y-2 text-xs">
                <div className="flex items-center gap-2 font-bold text-amber-300">
                  <span>⛽ 全网 Gas 黄金窗口预测</span>
                </div>
                <p className="text-slate-300 leading-relaxed text-[11px]">
                  {data.gas_advice}
                </p>
                <div className="pt-2 border-t border-slate-800 space-y-1">
                  {data.weekly_windows.slice(0, 2).map((w, idx) => (
                    <div key={idx} className="flex items-center justify-between text-[11px]">
                      <span className="font-mono text-slate-300">{w.period}</span>
                      <span className="text-emerald-400 font-semibold">{w.savings}</span>
                    </div>
                  ))}
                </div>
              </div>

              {/* Unlock Watch */}
              <div className="p-4 rounded-xl border border-slate-800 bg-slate-950/40 space-y-2 text-xs">
                <div className="flex items-center gap-2 font-bold text-indigo-300">
                  <span>🔓 近期代币解锁抛压雷达</span>
                </div>
                {data.imminent_unlocks.length === 0 ? (
                  <div className="text-slate-500 text-[11px]">近期无高危悬崖解锁</div>
                ) : (
                  <div className="space-y-2">
                    {data.imminent_unlocks.map((u, idx) => (
                      <div
                        key={idx}
                        className="p-2 rounded bg-slate-900/60 border border-slate-800 text-[11px] space-y-0.5"
                      >
                        <div className="flex items-center justify-between">
                          <span className="font-semibold text-slate-200">
                            {u.project_name} (${u.token_symbol})
                          </span>
                          <span className="text-rose-400 font-bold uppercase text-[10px]">
                            {u.pressure_rating}
                          </span>
                        </div>
                        <div className="text-slate-400 flex items-center justify-between">
                          <span>预计: {u.unlock_date}</span>
                          <span className="text-emerald-400">
                            ${Math.round(u.usd_value_estimate / 1e6)}M (占 {u.circulating_supply_pct}%)
                          </span>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>

            {/* Whale Activity */}
            {data.whale_signals.length > 0 && (
              <div className="p-4 rounded-xl border border-slate-800 bg-slate-950/40 space-y-2 text-xs">
                <div className="flex items-center gap-2 font-bold text-slate-300">
                  <span>🐋 过去 24 小时巨鲸聪明钱异动</span>
                </div>
                <div className="space-y-1.5">
                  {data.whale_signals.map((w, idx) => (
                    <div
                      key={idx}
                      className="p-2 rounded bg-slate-900/60 border border-slate-800 flex items-center justify-between text-[11px]"
                    >
                      <div className="flex items-center gap-2">
                        <span className="text-slate-200 font-semibold">{w.whale_label}</span>
                        <span className="text-slate-400">{w.action}</span>
                      </div>
                      <span className="text-slate-500 shrink-0 font-mono">{w.time_ago}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        ) : null}

        {/* Footer */}
        <div className="flex justify-end pt-2 border-t border-slate-800">
          <button
            onClick={onClose}
            className="rounded-lg bg-slate-800 hover:bg-slate-700 px-4 py-1.5 text-xs text-slate-300 transition"
          >
            完成并关闭
          </button>
        </div>
      </div>
    </div>
  );
}
