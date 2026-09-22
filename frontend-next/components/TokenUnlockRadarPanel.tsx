"use client";

import React, { useState, useEffect } from "react";
import { apiFetch } from "@/lib/api";

interface UnlockItem {
  project_id: string;
  project_name: string;
  token_symbol: string;
  unlock_date: string;
  unlock_type: "cliff" | "linear";
  amount_tokens: number;
  usd_value_estimate: number;
  circulating_supply_pct: number;
  total_supply_pct: number;
  unlocked_for: string[];
  pressure_rating: "critical" | "high" | "moderate" | "low";
  analysis_summary: string;
  action_advice: string;
}

const PRESSURE_CONFIG: Record<string, { label: string; color: string; border: string; bg: string }> = {
  critical: {
    label: "极高悬崖抛压",
    color: "text-red-400",
    border: "border-red-500/40",
    bg: "bg-red-950/40",
  },
  high: {
    label: "较高抛压",
    color: "text-orange-400",
    border: "border-orange-500/40",
    bg: "bg-orange-950/40",
  },
  moderate: {
    label: "温和释放",
    color: "text-blue-400",
    border: "border-blue-500/40",
    bg: "bg-blue-950/40",
  },
  low: {
    label: "轻微影响",
    color: "text-emerald-400",
    border: "border-emerald-500/40",
    bg: "bg-emerald-950/40",
  },
};

export default function TokenUnlockRadarPanel() {
  const [unlocks, setUnlocks] = useState<UnlockItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedPressure, setSelectedPressure] = useState<string>("all");
  const [sortBy, setSortBy] = useState<string>("date");

  const fetchUnlocks = async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (selectedPressure !== "all") {
        params.set("min_pressure", selectedPressure);
      }
      params.set("sort_by", sortBy);

      const json = await apiFetch<any>(`/unlocks/schedule?${params.toString()}`);
      if (json?.ok && Array.isArray(json.data)) {
        setUnlocks(json.data);
      }
    } catch (e: any) {
      setError(e.message || "加载代币解锁日程失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchUnlocks();
  }, [selectedPressure, sortBy]);

  const formatNumber = (num: number) => {
    if (num >= 1e9) return `${(num / 1e9).toFixed(2)}B`;
    if (num >= 1e6) return `${(num / 1e6).toFixed(1)}M`;
    if (num >= 1e3) return `${(num / 1e3).toFixed(0)}K`;
    return num.toLocaleString();
  };

  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/90 backdrop-blur p-6 shadow-xl space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <span className="text-2xl">🔓</span>
            <h2 className="text-xl font-bold text-slate-100">代币归属解锁与悬崖抛压雷达</h2>
            <span className="px-2.5 py-0.5 text-xs font-semibold rounded-full bg-indigo-500/10 text-indigo-400 border border-indigo-500/30">
              Cliff & Vesting Radar
            </span>
          </div>
          <p className="text-xs text-slate-400 mt-1">
            监控主流协议早期投资人与团队巨额份额到期解锁，提前防范二级市场流动性抽干与做空冲击
          </p>
        </div>

        <div className="flex items-center gap-3">
          <select
            value={selectedPressure}
            onChange={(e) => setSelectedPressure(e.target.value)}
            className="rounded-lg bg-slate-800 border border-slate-700 px-3 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-indigo-500"
          >
            <option value="all">全部风险等级</option>
            <option value="critical">🔴 仅极高抛压 (Critical)</option>
            <option value="high">🟠 较高及以上 (High+)</option>
            <option value="moderate">🔵 温和及以上 (Moderate+)</option>
          </select>

          <select
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value)}
            className="rounded-lg bg-slate-800 border border-slate-700 px-3 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-indigo-500"
          >
            <option value="date">按解锁日期排序</option>
            <option value="value">按释放金额排序</option>
            <option value="pct">按流通占比排序</option>
          </select>

          <button
            onClick={fetchUnlocks}
            className="rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700 px-3 py-1.5 text-xs text-slate-300 transition"
          >
            🔄 刷新
          </button>
        </div>
      </div>

      {loading ? (
        <div className="py-12 text-center text-slate-500 text-sm animate-pulse">
          正在同步链上代币解锁合约与 Vesting 时间线...
        </div>
      ) : error ? (
        <div className="rounded-xl border border-red-900/50 bg-red-950/20 p-4 text-center text-red-400 text-xs">
          {error}
        </div>
      ) : unlocks.length === 0 ? (
        <div className="py-12 text-center text-slate-500 text-sm">
          暂无匹配的代币解锁事件
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {unlocks.map((item) => {
            const pConf = PRESSURE_CONFIG[item.pressure_rating] || PRESSURE_CONFIG.low;
            return (
              <div
                key={item.project_id}
                className="rounded-xl border border-slate-800 bg-slate-950/50 p-4 space-y-3 hover:border-slate-700 transition"
              >
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="font-bold text-slate-100 text-base">{item.project_name}</span>
                      <span className="text-xs px-2 py-0.5 rounded bg-slate-800 text-indigo-300 font-mono font-semibold">
                        ${item.token_symbol}
                      </span>
                      <span
                        className={`text-[10px] px-2 py-0.5 rounded uppercase font-medium border ${
                          item.unlock_type === "cliff"
                            ? "bg-amber-950/40 text-amber-400 border-amber-600/30"
                            : "bg-slate-800 text-slate-400 border-slate-700"
                        }`}
                      >
                        {item.unlock_type === "cliff" ? "⛰️ 悬崖突增" : "📈 线性释放"}
                      </span>
                    </div>
                    <div className="text-xs text-slate-400 mt-1">
                      📅 预计解锁: <span className="text-slate-200 font-medium">{item.unlock_date}</span>
                    </div>
                  </div>

                  <span
                    className={`px-2.5 py-1 text-xs font-semibold rounded-full border ${pConf.border} ${pConf.color} ${pConf.bg}`}
                  >
                    {pConf.label}
                  </span>
                </div>

                {/* Key Metrics Grid */}
                <div className="grid grid-cols-3 gap-2 rounded-lg bg-slate-900/60 p-2.5 text-center text-xs">
                  <div>
                    <div className="text-slate-400 text-[11px]">释放总数量</div>
                    <div className="text-slate-100 font-bold mt-0.5">
                      {formatNumber(item.amount_tokens)} {item.token_symbol}
                    </div>
                  </div>
                  <div>
                    <div className="text-slate-400 text-[11px]">预估总价值</div>
                    <div className="text-emerald-400 font-bold mt-0.5">
                      ${formatNumber(item.usd_value_estimate)}
                    </div>
                  </div>
                  <div>
                    <div className="text-slate-400 text-[11px]">占流通盘比</div>
                    <div className={`font-bold mt-0.5 ${item.circulating_supply_pct >= 10 ? "text-red-400" : "text-amber-300"}`}>
                      {item.circulating_supply_pct}%
                    </div>
                  </div>
                </div>

                {/* Unlocked For Tags */}
                <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
                  <span className="text-slate-400">释放流向:</span>
                  {item.unlocked_for.map((target, idx) => (
                    <span
                      key={idx}
                      className="px-2 py-0.5 rounded bg-slate-800/80 text-slate-300 border border-slate-700/50"
                    >
                      {target}
                    </span>
                  ))}
                </div>

                {/* Summary & Action Advice */}
                <div className="rounded-lg bg-slate-900/40 border border-slate-800/80 p-2.5 text-xs space-y-1.5">
                  <p className="text-slate-300 leading-relaxed text-[11px]">
                    <span className="text-slate-400 font-medium">深度研判: </span>
                    {item.analysis_summary}
                  </p>
                  <p className="text-indigo-300/90 leading-relaxed text-[11px]">
                    <span className="text-indigo-400 font-medium">💡 猎人操作建议: </span>
                    {item.action_advice}
                  </p>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
