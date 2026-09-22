"use client";

import React, { useState, useEffect } from "react";
import { apiFetch } from "@/lib/api";

interface BoostPool {
  pool: string;
  multiplier: string;
  desc: string;
}

interface PointsResult {
  ok: boolean;
  protocol: {
    id: string;
    name: string;
    token_symbol: string;
    estimated_token_price_usd: number;
    airdrop_pool_tokens: number;
    total_points_supply: number;
  };
  user_input: {
    user_points: number;
    capital_invested_usd: number;
    days_active: number;
  };
  valuation: {
    share_of_pool_pct: number;
    estimated_tokens: number;
    estimated_usd_value: number;
    roi_multiple: number;
    tier: "whale" | "pioneer" | "active" | "dust";
    tier_label: string;
    percentile_text: string;
    next_tier_target_points: number | null;
  };
  sprint_advice: string;
  boost_strategies: BoostPool[];
}

interface Props {
  isOpen: boolean;
  onClose: () => void;
  defaultProtocolId?: string;
}

export default function PointsEpochEstimatorModal({
  isOpen,
  onClose,
  defaultProtocolId = "scroll_marks",
}: Props) {
  const [protocolId, setProtocolId] = useState(defaultProtocolId);
  const [userPoints, setUserPoints] = useState("35000");
  const [capitalUsd, setCapitalUsd] = useState("1500");
  const [daysActive, setDaysActive] = useState("45");

  const [result, setResult] = useState<PointsResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const runEstimate = async (pId?: string) => {
    const targetPid = pId || protocolId;
    const pts = parseFloat(userPoints);
    if (isNaN(pts) || pts < 0) {
      setError("请输入有效的积分数量");
      return;
    }

    setLoading(true);
    setError(null);
    try {
      const json = await apiFetch<PointsResult>("/points/estimate", {
        method: "POST",
        body: JSON.stringify({
          protocol_id: targetPid,
          user_points: pts,
          capital_invested_usd: parseFloat(capitalUsd) || 0.0,
          days_active: parseInt(daysActive, 10) || 30,
        }),
      });
      if (json?.ok) {
        setResult(json);
      }
    } catch (e: any) {
      setError(e.message || "估值推演失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (isOpen) {
      runEstimate();
    }
  }, [isOpen]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm animate-fade-in">
      <div className="relative w-full max-w-4xl max-h-[90vh] overflow-y-auto rounded-2xl border border-slate-700 bg-slate-900 shadow-2xl p-6 text-slate-100 space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-slate-800 pb-4">
          <div className="flex items-center gap-3">
            <span className="text-2xl">⏳</span>
            <div>
              <h3 className="text-lg font-bold text-slate-100">
                空投阶段积分估值与快照倍数推演器
              </h3>
              <p className="text-xs text-slate-400">
                对标主流 Season 积分发行模型，推演全网位次排位、代币折算值与高倍加速池推荐
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

        {/* Controls */}
        <div className="grid grid-cols-1 sm:grid-cols-4 gap-3 p-4 rounded-xl bg-slate-950/60 border border-slate-800">
          <div>
            <label className="text-[11px] text-slate-400 block mb-1">选择积分制协议</label>
            <select
              value={protocolId}
              onChange={(e) => {
                setProtocolId(e.target.value);
                runEstimate(e.target.value);
              }}
              className="w-full rounded-lg bg-slate-800 border border-slate-700 px-3 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-indigo-500"
            >
              <option value="scroll_marks">Scroll Marks (Session 2)</option>
              <option value="linea_voyage">Linea Voyage / LXP Points</option>
              <option value="hyperliquid_points">Hyperliquid Points (HYPE)</option>
              <option value="symbiotic_points">Symbiotic Restaking Points</option>
              <option value="karak_xp">Karak Network XP</option>
            </select>
          </div>

          <div>
            <label className="text-[11px] text-slate-400 block mb-1">您当前累积的积分</label>
            <input
              type="number"
              min="0"
              value={userPoints}
              onChange={(e) => setUserPoints(e.target.value)}
              className="w-full rounded-lg bg-slate-800 border border-slate-700 px-3 py-1.5 text-xs text-slate-100 font-mono focus:outline-none focus:border-indigo-500"
            />
          </div>

          <div>
            <label className="text-[11px] text-slate-400 block mb-1">投入本金/流动性 ($)</label>
            <input
              type="number"
              min="0"
              value={capitalUsd}
              onChange={(e) => setCapitalUsd(e.target.value)}
              className="w-full rounded-lg bg-slate-800 border border-slate-700 px-3 py-1.5 text-xs text-slate-100 font-mono focus:outline-none focus:border-indigo-500"
            />
          </div>

          <div>
            <label className="text-[11px] text-slate-400 block mb-1">持续活跃天数</label>
            <input
              type="number"
              min="1"
              value={daysActive}
              onChange={(e) => setDaysActive(e.target.value)}
              className="w-full rounded-lg bg-slate-800 border border-slate-700 px-3 py-1.5 text-xs text-slate-100 font-mono focus:outline-none focus:border-indigo-500"
            />
          </div>

          <div className="sm:col-span-4 flex justify-end">
            <button
              onClick={() => runEstimate()}
              disabled={loading}
              className="rounded-lg bg-indigo-600 hover:bg-indigo-500 px-4 py-1.5 text-xs font-semibold text-white transition disabled:opacity-50"
            >
              {loading ? "正在推演..." : "⚡ 重新推演估值与梯队"}
            </button>
          </div>
        </div>

        {error && (
          <div className="rounded-lg bg-red-950/40 border border-red-800/60 p-3 text-xs text-red-300">
            {error}
          </div>
        )}

        {result && (
          <div className="space-y-6">
            {/* Top Cards Grid */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              <div className="p-3.5 rounded-xl bg-slate-950/50 border border-slate-800 space-y-1">
                <div className="text-[11px] text-slate-400">预估空投代币</div>
                <div className="text-xl font-bold font-mono text-indigo-300">
                  {result.valuation.estimated_tokens.toLocaleString()}
                </div>
                <div className="text-[10px] text-slate-500 font-mono">
                  ${result.protocol.token_symbol} (~${result.protocol.estimated_token_price_usd}/币)
                </div>
              </div>

              <div className="p-3.5 rounded-xl bg-slate-950/50 border border-slate-800 space-y-1">
                <div className="text-[11px] text-slate-400">预估总价值 (USD)</div>
                <div className="text-xl font-bold font-mono text-emerald-400">
                  ${result.valuation.estimated_usd_value.toLocaleString()}
                </div>
                <div className="text-[10px] text-slate-500 font-mono">
                  池占比: {result.valuation.share_of_pool_pct}%
                </div>
              </div>

              <div className="p-3.5 rounded-xl bg-slate-950/50 border border-slate-800 space-y-1">
                <div className="text-[11px] text-slate-400">全网排位段位</div>
                <div className="text-sm font-bold text-slate-200 mt-1">
                  {result.valuation.tier_label}
                </div>
                <div className="text-[10px] text-indigo-400">
                  {result.valuation.percentile_text}
                </div>
              </div>

              <div className="p-3.5 rounded-xl bg-slate-950/50 border border-slate-800 space-y-1">
                <div className="text-[11px] text-slate-400">资金利用乘数</div>
                <div className="text-xl font-bold font-mono text-amber-300">
                  {result.valuation.roi_multiple > 0 ? `${result.valuation.roi_multiple}x` : "—"}
                </div>
                <div className="text-[10px] text-slate-500">
                  投入回报倍数
                </div>
              </div>
            </div>

            {/* Sprint Advice */}
            <div className="rounded-xl border border-indigo-500/40 bg-indigo-950/30 p-4 space-y-1.5">
              <div className="flex items-center gap-2 text-xs font-bold text-indigo-300">
                <span>🚀 冲刺与保级战术建议:</span>
              </div>
              <p className="text-xs text-slate-200 leading-relaxed">
                {result.sprint_advice}
              </p>
            </div>

            {/* Boost Multipliers Pools */}
            <div className="rounded-xl border border-slate-800 bg-slate-950/40 p-4 space-y-3">
              <div className="flex items-center justify-between text-xs font-bold text-slate-300">
                <span>⚡ {result.protocol.name} 专属加权加速池 (Multipliers)</span>
                <span className="text-[11px] text-slate-400 font-normal">
                  选择高倍池可大幅缩短达标周期
                </span>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                {result.boost_strategies.map((b, idx) => (
                  <div
                    key={idx}
                    className="p-3 rounded-lg border border-slate-800 bg-slate-900/60 space-y-1"
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-semibold text-slate-200 text-xs">{b.pool}</span>
                      <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-amber-500/20 text-amber-300 border border-amber-500/30">
                        {b.multiplier}
                      </span>
                    </div>
                    <p className="text-[11px] text-slate-400">{b.desc}</p>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* Footer */}
        <div className="flex justify-end pt-2 border-t border-slate-800">
          <button
            onClick={onClose}
            className="rounded-lg bg-slate-800 hover:bg-slate-700 px-4 py-1.5 text-xs text-slate-300 transition"
          >
            完成推演并关闭
          </button>
        </div>
      </div>
    </div>
  );
}
