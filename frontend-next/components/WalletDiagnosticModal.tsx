"use client";

import React, { useState, useEffect } from "react";
import { apiFetch } from "@/lib/api";

interface DimensionInfo {
  score: number;
  label: string;
  detail: string;
  [key: string]: any;
}

interface DiagnosticResult {
  ok: boolean;
  wallet_address: string;
  overall_health_score: number;
  sybil_risk_level: "low" | "moderate" | "high" | "critical";
  sybil_risk_label: string;
  dimensions: {
    longevity: DimensionInfo;
    contract_breadth: DimensionInfo;
    protocol_diversity: DimensionInfo;
    gas_commitment: DimensionInfo;
    multichain_footprint: DimensionInfo;
  };
  vulnerabilities: string[];
  actionable_guide: string[];
}

interface Props {
  isOpen: boolean;
  onClose: () => void;
  initialAddress?: string;
}

export default function WalletDiagnosticModal({
  isOpen,
  onClose,
  initialAddress = "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045", // Vitalik address as default demo
}: Props) {
  const [address, setAddress] = useState(initialAddress);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [activeMonths, setActiveMonths] = useState<string>("");
  const [txCount, setTxCount] = useState<string>("");
  const [uniqueContracts, setUniqueContracts] = useState<string>("");
  const [gasEth, setGasEth] = useState<string>("");

  const [result, setResult] = useState<DiagnosticResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [checkedGuide, setCheckedGuide] = useState<Record<number, boolean>>({});

  const runDiagnostic = async (targetAddress?: string) => {
    const addr = targetAddress || address;
    if (!addr || !addr.startsWith("0x")) {
      setError("请输入以 0x 开头的有效 EVM 钱包地址");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const body: any = { wallet_address: addr };
      if (activeMonths) body.active_months = parseInt(activeMonths, 10);
      if (txCount) body.tx_count = parseInt(txCount, 10);
      if (uniqueContracts) body.unique_contracts = parseInt(uniqueContracts, 10);
      if (gasEth) body.total_gas_spent_eth = parseFloat(gasEth);

      const json = await apiFetch<any>('/diagnostic/wallet', {
        method: "POST",
        body: JSON.stringify(body),
      });
      if (json?.ok) {
        setResult(json);
        setCheckedGuide({});
      }
    } catch (e: any) {
      setError(e.message || "体检失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (isOpen) {
      runDiagnostic();
    }
  }, [isOpen]);

  const toggleCheck = (idx: number) => {
    setCheckedGuide((prev) => ({ ...prev, [idx]: !prev[idx] }));
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm animate-fade-in">
      <div className="relative w-full max-w-4xl max-h-[90vh] overflow-y-auto rounded-2xl border border-slate-700 bg-slate-900 shadow-2xl p-6 text-slate-100 space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-slate-800 pb-4">
          <div className="flex items-center gap-3">
            <span className="text-2xl">🩺</span>
            <div>
              <h3 className="text-lg font-bold text-slate-100">钱包交互广度与链上履历健康度诊断仪</h3>
              <p className="text-xs text-slate-400">
                按 LayerZero / Celestia / ZKsync 严苛反女巫标准，5 维体检链上画像并提供补刀方案
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

        {/* Search & Quick Fill */}
        <div className="p-4 rounded-xl bg-slate-950/60 border border-slate-800 space-y-3">
          <div className="flex flex-col sm:flex-row items-center gap-2">
            <div className="relative flex-1 w-full">
              <input
                type="text"
                value={address}
                onChange={(e) => setAddress(e.target.value)}
                placeholder="输入待诊断的 EVM 钱包地址 (0x...)"
                className="w-full rounded-lg bg-slate-800 border border-slate-700 px-3 py-2 text-xs text-slate-100 font-mono focus:outline-none focus:border-indigo-500"
              />
            </div>
            <button
              onClick={() => runDiagnostic()}
              disabled={loading}
              className="w-full sm:w-auto rounded-lg bg-indigo-600 hover:bg-indigo-500 px-5 py-2 text-xs font-semibold text-white transition shrink-0 disabled:opacity-50"
            >
              {loading ? "诊断中..." : "🚀 开始 5 维健康体检"}
            </button>
          </div>

          <div className="flex flex-wrap items-center justify-between gap-2 pt-1 text-[11px] text-slate-400">
            <div className="flex items-center gap-2">
              <span>快速测试预设:</span>
              <button
                type="button"
                onClick={() => {
                  const a = "0x8888888888888888888888888888888888888888";
                  setAddress(a);
                  setActiveMonths("14");
                  setTxCount("160");
                  setUniqueContracts("45");
                  setGasEth("0.15");
                  runDiagnostic(a);
                }}
                className="px-2 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-emerald-400 border border-emerald-900/40"
              >
                🌟 顶级白名单猎人
              </button>
              <button
                type="button"
                onClick={() => {
                  const a = "0x1111111111111111111111111111111111111111";
                  setAddress(a);
                  setActiveMonths("1");
                  setTxCount("12");
                  setUniqueContracts("2");
                  setGasEth("0.001");
                  runDiagnostic(a);
                }}
                className="px-2 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-rose-400 border border-rose-900/40"
              >
                ⚠️ 工业化高危女巫号
              </button>
            </div>

            <button
              type="button"
              onClick={() => setShowAdvanced(!showAdvanced)}
              className="text-indigo-400 hover:text-indigo-300 transition"
            >
              {showAdvanced ? "收起高级参数 ▲" : "自定义链上参数 ▼"}
            </button>
          </div>

          {showAdvanced && (
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 pt-3 border-t border-slate-800/80 text-xs">
              <div>
                <label className="text-[11px] text-slate-400 block mb-1">活跃月数</label>
                <input
                  type="number"
                  placeholder="留空自动模拟"
                  value={activeMonths}
                  onChange={(e) => setActiveMonths(e.target.value)}
                  className="w-full rounded bg-slate-800 border border-slate-700 p-1.5 font-mono text-xs"
                />
              </div>
              <div>
                <label className="text-[11px] text-slate-400 block mb-1">总交互交易数</label>
                <input
                  type="number"
                  placeholder="留空自动模拟"
                  value={txCount}
                  onChange={(e) => setTxCount(e.target.value)}
                  className="w-full rounded bg-slate-800 border border-slate-700 p-1.5 font-mono text-xs"
                />
              </div>
              <div>
                <label className="text-[11px] text-slate-400 block mb-1">独立交互合约数</label>
                <input
                  type="number"
                  placeholder="留空自动模拟"
                  value={uniqueContracts}
                  onChange={(e) => setUniqueContracts(e.target.value)}
                  className="w-full rounded bg-slate-800 border border-slate-700 p-1.5 font-mono text-xs"
                />
              </div>
              <div>
                <label className="text-[11px] text-slate-400 block mb-1">消耗 Gas (ETH)</label>
                <input
                  type="number"
                  step="any"
                  placeholder="留空自动模拟"
                  value={gasEth}
                  onChange={(e) => setGasEth(e.target.value)}
                  className="w-full rounded bg-slate-800 border border-slate-700 p-1.5 font-mono text-xs"
                />
              </div>
            </div>
          )}
        </div>

        {error && (
          <div className="rounded-lg bg-red-950/40 border border-red-800/60 p-3 text-xs text-red-300">
            {error}
          </div>
        )}

        {result && (
          <div className="space-y-6">
            {/* Top Score & Risk Level */}
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 p-5 rounded-2xl bg-slate-950/50 border border-slate-800">
              <div className="sm:col-span-1 flex flex-col items-center justify-center p-3 text-center border-b sm:border-b-0 sm:border-r border-slate-800">
                <div className="text-xs text-slate-400 mb-1">综合链上健康评分</div>
                <div
                  className={`text-5xl font-extrabold font-mono ${
                    result.overall_health_score >= 80
                      ? "text-emerald-400"
                      : result.overall_health_score >= 60
                      ? "text-amber-400"
                      : "text-rose-400"
                  }`}
                >
                  {result.overall_health_score}
                </div>
                <div className="text-[10px] text-slate-500 mt-1">满分 100 分</div>
              </div>

              <div className="sm:col-span-2 flex flex-col justify-center space-y-2 pl-0 sm:pl-2">
                <div className="flex items-center gap-2">
                  <span className="text-xs text-slate-400">女巫审查防御判定:</span>
                  <span
                    className={`px-2.5 py-0.5 rounded-full text-xs font-bold border ${
                      result.sybil_risk_level === "low"
                        ? "bg-emerald-950/60 text-emerald-300 border-emerald-500/40"
                        : result.sybil_risk_level === "moderate"
                        ? "bg-amber-950/60 text-amber-300 border-amber-500/40"
                        : "bg-rose-950/60 text-rose-300 border-rose-500/40"
                    }`}
                  >
                    {result.sybil_risk_label}
                  </span>
                </div>
                <p className="text-xs text-slate-300 leading-relaxed">
                  当前钱包在多维度时间跨度、合约离散度与真实经济投入上
                  {result.overall_health_score >= 80
                    ? "表现卓越，完全符合一线项目空投最高档位白名单特征。"
                    : result.overall_health_score >= 60
                    ? "具备基本交互行为，但部分核心反女巫特征存在短板，建议对照下方补刀指南进行补足。"
                    : "呈现显著的单薄流水线特征，极易被多链空投项目女巫集群聚类排除，需紧急补刀修复。"}
                </p>
              </div>
            </div>

            {/* 5-Dimension Radar Progress */}
            <div className="space-y-3">
              <div className="text-xs font-bold text-slate-300">📊 5 维反女巫体检细分指标</div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                {Object.entries(result.dimensions).map(([key, dim]) => (
                  <div
                    key={key}
                    className="rounded-xl border border-slate-800 bg-slate-950/40 p-3.5 space-y-2"
                  >
                    <div className="flex items-center justify-between text-xs">
                      <span className="font-semibold text-slate-200">{dim.label}</span>
                      <span
                        className={`font-mono font-bold ${
                          dim.score >= 80
                            ? "text-emerald-400"
                            : dim.score >= 60
                            ? "text-amber-400"
                            : "text-rose-400"
                        }`}
                      >
                        {dim.score} 分
                      </span>
                    </div>

                    <div className="w-full h-2 rounded-full bg-slate-800 overflow-hidden">
                      <div
                        className={`h-full rounded-full transition-all duration-500 ${
                          dim.score >= 80
                            ? "bg-emerald-500"
                            : dim.score >= 60
                            ? "bg-amber-500"
                            : "bg-rose-500"
                        }`}
                        style={{ width: `${dim.score}%` }}
                      />
                    </div>

                    <p className="text-[11px] text-slate-400 leading-relaxed">{dim.detail}</p>
                  </div>
                ))}
              </div>
            </div>

            {/* Vulnerabilities Callout */}
            {result.vulnerabilities.length > 0 && (
              <div className="rounded-xl border border-rose-500/30 bg-rose-950/20 p-4 space-y-2">
                <div className="flex items-center gap-2 text-xs font-bold text-rose-400">
                  <span>⚠️ 检测到的潜在女巫风险项 ({result.vulnerabilities.length})</span>
                </div>
                <ul className="list-disc list-inside text-xs text-rose-300/90 space-y-1">
                  {result.vulnerabilities.map((v, i) => (
                    <li key={i}>{v}</li>
                  ))}
                </ul>
              </div>
            )}

            {/* Actionable Guide Checklist */}
            <div className="rounded-xl border border-indigo-500/30 bg-indigo-950/20 p-4 space-y-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2 text-xs font-bold text-indigo-300">
                  <span>💡 专属精准补刀交互指南 (Checklist)</span>
                </div>
                <span className="text-[10px] text-slate-400">完成可打勾标记</span>
              </div>

              <div className="space-y-2">
                {result.actionable_guide.map((item, idx) => {
                  const isDone = !!checkedGuide[idx];
                  return (
                    <div
                      key={idx}
                      onClick={() => toggleCheck(idx)}
                      className={`flex items-start gap-2.5 p-2.5 rounded-lg border text-xs cursor-pointer transition select-none ${
                        isDone
                          ? "border-emerald-500/30 bg-emerald-950/20 text-emerald-300 line-through opacity-70"
                          : "border-slate-800 bg-slate-900/60 text-slate-200 hover:border-slate-700"
                      }`}
                    >
                      <input
                        type="checkbox"
                        checked={isDone}
                        onChange={() => {}}
                        className="mt-0.5 rounded text-indigo-600 focus:ring-0"
                      />
                      <span>{item}</span>
                    </div>
                  );
                })}
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
            完成体检并关闭
          </button>
        </div>
      </div>
    </div>
  );
}
