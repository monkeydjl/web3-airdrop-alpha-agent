"use client";

import React, { useState, useEffect } from "react";
import { apiFetch } from "@/lib/api";

interface StrategyItem {
  strategy_id: string;
  name: string;
  tag: string;
  expected_return_usd: number;
  immediate_cash_usd: number;
  risk_level: "low" | "medium" | "high";
  risk_score: number;
  suitability: string;
  pros: string[];
  cons: string[];
}

interface SimulationResult {
  ok: boolean;
  input_summary: {
    token_amount: number;
    initial_price_usd: number;
    initial_gross_value_usd: number;
    sector: string;
    persona: string;
  };
  strategies: StrategyItem[];
  recommended_strategy: string;
  recommendation_rationale: string;
}

interface Props {
  isOpen: boolean;
  onClose: () => void;
  defaultTokenAmount?: number;
  defaultPriceUsd?: number;
  defaultSector?: string;
}

export default function SellOffSimulatorModal({
  isOpen,
  onClose,
  defaultTokenAmount = 1000,
  defaultPriceUsd = 2.5,
  defaultSector = "layer2",
}: Props) {
  const [tokenAmount, setTokenAmount] = useState(defaultTokenAmount.toString());
  const [priceUsd, setPriceUsd] = useState(defaultPriceUsd.toString());
  const [sector, setSector] = useState(defaultSector);
  const [persona, setPersona] = useState<"conservative" | "balanced" | "aggressive" | "farmer_whale">("balanced");

  const [result, setResult] = useState<SimulationResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const runSimulation = async () => {
    setLoading(true);
    setError(null);
    try {
      const amt = parseFloat(tokenAmount);
      const prc = parseFloat(priceUsd);
      if (isNaN(amt) || amt <= 0) throw new Error("请输入有效的代币数量");
      if (isNaN(prc) || prc <= 0) throw new Error("请输入有效的代币预估单价");

      const json = await apiFetch<any>('/sell-off/simulate', {
        method: "POST",
        body: JSON.stringify({
          token_amount: amt,
          initial_price_usd: prc,
          sector,
          persona,
        }),
      });
      if (json?.ok) {
        setResult(json);
      }
    } catch (e: any) {
      setError(e.message || "模拟计算失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (isOpen) {
      runSimulation();
    }
  }, [isOpen]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm animate-fade-in">
      <div className="relative w-full max-w-4xl max-h-[90vh] overflow-y-auto rounded-2xl border border-slate-700 bg-slate-900 shadow-2xl p-6 text-slate-100 space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-slate-800 pb-4">
          <div className="flex items-center gap-3">
            <span className="text-2xl">💰</span>
            <div>
              <h3 className="text-lg font-bold text-slate-100">空投领取代币出局与止盈模拟器</h3>
              <p className="text-xs text-slate-400">
                对比「开盘秒砸」、「分批 DCA」、「保本底仓」与「生态质押」4 大出局方案预期收益
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

        {/* Input Controls */}
        <div className="grid grid-cols-1 sm:grid-cols-4 gap-3 p-4 rounded-xl bg-slate-950/60 border border-slate-800">
          <div>
            <label className="text-[11px] text-slate-400 block mb-1">空投代币数量</label>
            <input
              type="number"
              min="1"
              value={tokenAmount}
              onChange={(e) => setTokenAmount(e.target.value)}
              className="w-full rounded-lg bg-slate-800 border border-slate-700 px-3 py-1.5 text-xs text-slate-100 font-mono focus:outline-none focus:border-indigo-500"
            />
          </div>

          <div>
            <label className="text-[11px] text-slate-400 block mb-1">初始/开盘预估单价 ($)</label>
            <input
              type="number"
              step="any"
              min="0.0001"
              value={priceUsd}
              onChange={(e) => setPriceUsd(e.target.value)}
              className="w-full rounded-lg bg-slate-800 border border-slate-700 px-3 py-1.5 text-xs text-slate-100 font-mono focus:outline-none focus:border-indigo-500"
            />
          </div>

          <div>
            <label className="text-[11px] text-slate-400 block mb-1">项目所属赛道</label>
            <select
              value={sector}
              onChange={(e) => setSector(e.target.value)}
              className="w-full rounded-lg bg-slate-800 border border-slate-700 px-3 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-indigo-500"
            >
              <option value="layer2">Layer 2 (如 STRK, ZK, ARB)</option>
              <option value="infrastructure">模块化/基础设施 (如 TIA, ZRO)</option>
              <option value="defi">DeFi 协议 (如 ENA, JUP, UNI)</option>
              <option value="ai">AI / DePIN 概念</option>
              <option value="other">常规其它项目</option>
            </select>
          </div>

          <div>
            <label className="text-[11px] text-slate-400 block mb-1">猎人操作风格</label>
            <select
              value={persona}
              onChange={(e) => setPersona(e.target.value as any)}
              className="w-full rounded-lg bg-slate-800 border border-slate-700 px-3 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-indigo-500"
            >
              <option value="balanced">均衡研投型 (Balanced)</option>
              <option value="conservative">稳健保守型 (落袋为安)</option>
              <option value="aggressive">激进冲锋型 (博超额爆发)</option>
              <option value="farmer_whale">巨鲸质押大户 (生态二期)</option>
            </select>
          </div>

          <div className="sm:col-span-4 flex justify-end">
            <button
              onClick={runSimulation}
              disabled={loading}
              className="rounded-lg bg-indigo-600 hover:bg-indigo-500 px-4 py-1.5 text-xs font-semibold text-white transition disabled:opacity-50"
            >
              {loading ? "正在运算推演..." : "⚡ 重新运行策略模拟"}
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
            {/* Top AI Recommendation Banner */}
            <div className="rounded-xl border border-indigo-500/40 bg-indigo-950/30 p-4 space-y-2">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="text-xl">🏆</span>
                  <span className="text-xs font-bold text-indigo-300 uppercase tracking-wide">
                    算法优选推荐策略
                  </span>
                </div>
                <span className="text-xs px-2.5 py-0.5 rounded-full bg-indigo-500/20 text-indigo-300 border border-indigo-500/30 font-semibold">
                  {result.strategies.find((s) => s.strategy_id === result.recommended_strategy)?.name}
                </span>
              </div>
              <p className="text-xs text-slate-300 leading-relaxed">
                {result.recommendation_rationale}
              </p>
            </div>

            {/* Expected Value Visual Comparison */}
            <div className="rounded-xl bg-slate-950/40 border border-slate-800 p-4 space-y-3">
              <div className="text-xs font-bold text-slate-300">📊 4 大策略预期总收益对比 (USD)</div>
              <div className="space-y-2.5">
                {result.strategies.map((s) => {
                  const maxVal = Math.max(...result.strategies.map((x) => x.expected_return_usd));
                  const pct = Math.max(10, Math.round((s.expected_return_usd / (maxVal || 1)) * 100));
                  const isRec = s.strategy_id === result.recommended_strategy;
                  return (
                    <div key={s.strategy_id} className="space-y-1">
                      <div className="flex items-center justify-between text-xs">
                        <span className={`font-medium ${isRec ? "text-indigo-300 font-bold" : "text-slate-300"}`}>
                          {s.name} {isRec && "★"}
                        </span>
                        <span className="font-mono font-bold text-emerald-400">
                          ${s.expected_return_usd.toLocaleString()}
                        </span>
                      </div>
                      <div className="w-full h-2.5 rounded-full bg-slate-800 overflow-hidden">
                        <div
                          className={`h-full rounded-full transition-all duration-500 ${
                            isRec ? "bg-indigo-500" : "bg-emerald-600/70"
                          }`}
                          style={{ width: `${pct}%` }}
                        />
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* 4 Strategy Cards Grid */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              {result.strategies.map((s) => {
                const isRec = s.strategy_id === result.recommended_strategy;
                return (
                  <div
                    key={s.strategy_id}
                    className={`rounded-xl border p-4 space-y-3 transition ${
                      isRec
                        ? "border-indigo-500/60 bg-indigo-950/20 ring-1 ring-indigo-500/30"
                        : "border-slate-800 bg-slate-950/40"
                    }`}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="font-bold text-slate-100 text-sm">{s.name}</span>
                          <span className="text-[10px] px-2 py-0.5 rounded bg-slate-800 text-slate-300 border border-slate-700">
                            {s.tag}
                          </span>
                        </div>
                        <div className="text-[11px] text-slate-400 mt-0.5">{s.suitability}</div>
                      </div>
                      {isRec && (
                        <span className="px-2 py-0.5 text-[10px] font-bold rounded-full bg-indigo-500 text-white shadow">
                          首选推荐
                        </span>
                      )}
                    </div>

                    <div className="grid grid-cols-2 gap-2 p-2.5 rounded-lg bg-slate-900/60 text-xs">
                      <div>
                        <div className="text-slate-400 text-[11px]">预期总收益</div>
                        <div className="text-emerald-400 font-bold font-mono text-sm mt-0.5">
                          ${s.expected_return_usd.toLocaleString()}
                        </div>
                      </div>
                      <div>
                        <div className="text-slate-400 text-[11px]">首日即时到手现金</div>
                        <div className="text-slate-200 font-bold font-mono text-sm mt-0.5">
                          ${s.immediate_cash_usd.toLocaleString()}
                        </div>
                      </div>
                    </div>

                    <div className="space-y-1 text-[11px]">
                      <div className="text-emerald-400 font-medium">✓ 优势:</div>
                      <ul className="list-disc list-inside text-slate-300 space-y-0.5 pl-1">
                        {s.pros.map((pro, idx) => (
                          <li key={idx}>{pro}</li>
                        ))}
                      </ul>
                      <div className="text-rose-400 font-medium pt-1">✕ 风险/权衡:</div>
                      <ul className="list-disc list-inside text-slate-400 space-y-0.5 pl-1">
                        {s.cons.map((con, idx) => (
                          <li key={idx}>{con}</li>
                        ))}
                      </ul>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Footer */}
        <div className="flex justify-end pt-2 border-t border-slate-800">
          <button
            onClick={onClose}
            className="rounded-lg bg-slate-800 hover:bg-slate-700 px-4 py-1.5 text-xs text-slate-300 transition"
          >
            关闭
          </button>
        </div>
      </div>
    </div>
  );
}
