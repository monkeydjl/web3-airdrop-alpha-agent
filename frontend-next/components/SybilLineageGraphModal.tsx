"use client";

import React, { useState, useEffect } from "react";
import { apiFetch } from "@/lib/api";
import { SimulatedDataBadge } from "@/components/SimulatedDataBadge";

interface NodeItem {
  id: string;
  label: string;
  role: "target_wallet" | "common_funder" | "cex_sweeper" | "wallet";
  risk: string;
}

interface LinkItem {
  source: string;
  target: string;
  type: string;
  label: string;
  severity: "fatal" | "high" | "normal";
  amount_eth?: number;
}

interface LineageResult {
  ok: boolean;
  data_quality?: { quality?: string; note?: string };
  wallets_analyzed: number;
  lineage_status?: string;
  isolation_score: number | null;
  risk_level: string | null;
  sybil_cluster_detected: boolean;
  analysis_summary?: string;
  nodes: NodeItem[];
  links: LinkItem[];
  fatal_red_flags: string[];
  recommendations: string[];
  education?: { critical_rules: string[] };
}

interface Props {
  isOpen: boolean;
  onClose: () => void;
}

export default function SybilLineageGraphModal({ isOpen, onClose }: Props) {
  const [addressInput, setAddressInput] = useState(
    "0x1111111111111111111111111111111111111111\n0x2222222222222222222222222222222222222222\n0x3333333333333333333333333333333333333333"
  );
  const [result, setResult] = useState<LineageResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const runDetection = async (inputVal?: string) => {
    const raw = inputVal !== undefined ? inputVal : addressInput;
    const addrs = raw
      .split(/[\n,;]+/)
      .map((a) => a.trim())
      .filter((a) => a.startsWith("0x"));

    if (addrs.length === 0) {
      setError("请至少输入一个以 0x 开头的有效 EVM 钱包地址");
      return;
    }

    setLoading(true);
    setError(null);
    try {
      const json = await apiFetch<LineageResult>("/lineage/detect", {
        method: "POST",
        body: JSON.stringify({ wallet_addresses: addrs }),
      });
      if (json?.ok) {
        setResult(json);
      }
    } catch (e: any) {
      setError(e.message || "血缘检测计算失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (isOpen) {
      runDetection();
    }
  }, [isOpen]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm animate-fade-in">
      <div className="relative w-full max-w-4xl max-h-[90vh] overflow-y-auto rounded-2xl border border-slate-700 bg-slate-900 shadow-2xl p-6 text-slate-100 space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-slate-800 pb-4">
          <div className="flex items-center gap-3">
            <span className="text-2xl">🕸️</span>
            <div>
              <h3 className="text-lg font-bold text-slate-100 flex items-center gap-2 flex-wrap">
                <span>多钱包隔离自查与防关联教学图谱</span>
                <SimulatedDataBadge dataQuality={result?.data_quality} />
              </h3>
              <p className="text-xs text-slate-400">
                真实血缘检测需要链上数据源；当前版本提供结构性自查（基于你显式声明的关联）与隔离教学红线
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

        {/* Input Area */}
        <div className="p-4 rounded-xl bg-slate-950/60 border border-slate-800 space-y-3">
          <div className="flex items-center justify-between text-xs">
            <span className="font-bold text-slate-300">
              输入待测钱包列表 (每行一个或逗号隔开):
            </span>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => {
                  const clean =
                    "0x7111111111111111111111111111111111111111\n0x8222222222222222222222222222222222222222\n0x9333333333333333333333333333333333333333";
                  setAddressInput(clean);
                  runDetection(clean);
                }}
                className="text-[11px] text-emerald-400 hover:underline"
              >
                载入无关联纯净号
              </button>
              <span className="text-slate-600">|</span>
              <button
                type="button"
                onClick={() => {
                  const linked =
                    "0x1111111111111111111111111111111111111111\n0x1111111111111111111111111111111111111122\n0x3333333333333333333333333333333333333311";
                  setAddressInput(linked);
                  runDetection(linked);
                }}
                className="text-[11px] text-rose-400 hover:underline"
              >
                载入高危关联集群
              </button>
            </div>
          </div>

          <textarea
            rows={3}
            value={addressInput}
            onChange={(e) => setAddressInput(e.target.value)}
            placeholder="0x1234...&#10;0x5678...&#10;0x9abc..."
            className="w-full rounded-lg bg-slate-800 border border-slate-700 p-2.5 text-xs text-slate-100 font-mono focus:outline-none focus:border-indigo-500"
          />

          <div className="flex justify-end">
            <button
              onClick={() => runDetection()}
              disabled={loading}
              className="rounded-lg bg-indigo-600 hover:bg-indigo-500 px-5 py-2 text-xs font-semibold text-white transition disabled:opacity-50"
            >
              {loading ? "正在解析图谱..." : "🚀 开始图拓扑连通性扫描"}
            </button>
          </div>
        </div>

        {error && (
          <div className="rounded-lg bg-red-950/40 border border-red-800/60 p-3 text-xs text-red-300">
            {error}
          </div>
        )}

        {result && (
          <div className="space-y-5">
            {/* Top Score & Result Banner —— isolation_score 仅在用户声明关联时才有意义 */}
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 p-5 rounded-2xl bg-slate-950/50 border border-slate-800">
              <div className="sm:col-span-1 flex flex-col items-center justify-center p-3 text-center border-b sm:border-b-0 sm:border-r border-slate-800">
                <div className="text-xs text-slate-400 mb-1">资金链隔离自查</div>
                {result.isolation_score != null ? (
                  <div
                    className={`text-5xl font-extrabold font-mono ${
                      result.isolation_score >= 80
                        ? "text-emerald-400"
                        : result.isolation_score >= 60
                        ? "text-amber-400"
                        : "text-rose-400"
                    }`}
                  >
                    {result.isolation_score}
                  </div>
                ) : (
                  <div className="text-2xl font-bold font-mono text-slate-400 mt-2">待链上数据源</div>
                )}
                <div className="text-[10px] text-slate-500 mt-1">
                  已自查 {result.wallets_analyzed} 个钱包
                </div>
              </div>

              <div className="sm:col-span-2 flex flex-col justify-center space-y-2 pl-0 sm:pl-2">
                <div className="flex items-center gap-2">
                  <span className="text-xs text-slate-400">自查结论:</span>
                  <span
                    className={`px-2.5 py-0.5 rounded-full text-xs font-bold border ${
                      result.risk_level === null
                        ? "bg-slate-800/60 text-slate-300 border-slate-600/40"
                        : result.risk_level === "user_declared_risk"
                        ? "bg-rose-950/60 text-rose-300 border-rose-500/40"
                        : "bg-emerald-950/60 text-emerald-300 border-emerald-500/40"
                    }`}
                  >
                    {result.risk_level === null
                      ? "ℹ️ 未发现声明关联（真实检测需链上数据）"
                      : result.risk_level === "user_declared_risk"
                      ? "🚨 存在你声明的关联 (致命红线)"
                      : "✅ 结构自查通过"}
                  </span>
                </div>
                <p className="text-xs text-slate-300 leading-relaxed">
                  {result.analysis_summary ||
                    "服务端不猜测链上事实；只有你显式声明的关联才会被标记。可在输入中附加 declared_links 声明确知的关联。"}
                </p>
              </div>
            </div>

            {/* Fatal Red Flags Callout */}
            {result.fatal_red_flags.length > 0 && (
              <div className="rounded-xl border border-rose-500/40 bg-rose-950/20 p-4 space-y-2">
                <div className="flex items-center gap-2 text-xs font-bold text-rose-400">
                  <span>🚨 触发的反女巫强审查特征 ({result.fatal_red_flags.length})</span>
                </div>
                <ul className="space-y-1.5 text-xs text-rose-300/90 pl-1">
                  {result.fatal_red_flags.map((flag, idx) => (
                    <li key={idx} className="flex items-start gap-1.5">
                      <span>•</span>
                      <span>{flag}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* Graph Node Topology View */}
            <div className="rounded-xl border border-slate-800 bg-slate-950/40 p-4 space-y-3">
              <div className="flex items-center justify-between text-xs">
                <span className="font-bold text-slate-300">
                  🌐 资金流动网络拓扑 ({result.nodes.length} 个节点, {result.links.length} 条关联边)
                </span>
                <div className="flex items-center gap-3 text-[11px] text-slate-400">
                  <span className="flex items-center gap-1">
                    <span className="h-2 w-2 rounded-full bg-indigo-400" />
                    目标钱包
                  </span>
                  <span className="flex items-center gap-1">
                    <span className="h-2 w-2 rounded-full bg-purple-400" />
                    母钱包
                  </span>
                  <span className="flex items-center gap-1">
                    <span className="h-2 w-2 rounded-full bg-amber-400" />
                    归集点
                  </span>
                </div>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 max-h-52 overflow-y-auto pr-1">
                {result.nodes.map((node) => (
                  <div
                    key={node.id}
                    className="p-2.5 rounded-lg border border-slate-800 bg-slate-900/60 flex items-center justify-between text-xs"
                  >
                    <div className="flex items-center gap-2">
                      <span
                        className={`h-2.5 w-2.5 rounded-full ${
                          node.role === "target_wallet"
                            ? "bg-indigo-400"
                            : node.role === "common_funder"
                            ? "bg-purple-400 animate-pulse"
                            : "bg-amber-400 animate-pulse"
                        }`}
                      />
                      <span className="font-mono text-slate-200">{node.label}</span>
                    </div>
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-400 uppercase">
                      {node.role === "target_wallet" ? "子号" : node.role === "common_funder" ? "出资母号" : "充值归集"}
                    </span>
                  </div>
                ))}
              </div>

              {result.links.length > 0 && (
                <div className="pt-2 border-t border-slate-800/80 space-y-1.5">
                  <div className="text-[11px] text-slate-400 font-medium">检测到的关联流动边:</div>
                  <div className="space-y-1 text-xs">
                    {result.links.map((link, idx) => (
                      <div
                        key={idx}
                        className="flex items-center justify-between p-2 rounded bg-slate-900/40 border border-slate-800/60 text-slate-300 text-[11px]"
                      >
                        <div className="flex items-center gap-1.5 font-mono">
                          <span className="text-indigo-300">{link.source.slice(0, 8)}...</span>
                          <span className="text-slate-500">──────►</span>
                          <span className="text-purple-300">{link.target.slice(0, 8)}...</span>
                        </div>
                        <span
                          className={`px-2 py-0.5 rounded text-[10px] font-semibold ${
                            link.severity === "fatal"
                              ? "bg-rose-950/60 text-rose-300 border border-rose-800/40"
                              : "bg-amber-950/60 text-amber-300 border border-amber-800/40"
                          }`}
                        >
                          {link.label}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {/* Recommendations */}
            <div className="rounded-xl border border-indigo-500/30 bg-indigo-950/20 p-4 space-y-2">
              <div className="flex items-center gap-2 text-xs font-bold text-indigo-300">
                <span>🛡️ 女巫防范与资金链物理隔离建议</span>
              </div>
              <ul className="space-y-1 text-xs text-slate-300 pl-1">
                {result.recommendations.map((rec, idx) => (
                  <li key={idx} className="flex items-start gap-1.5">
                    <span>✓</span>
                    <span>{rec}</span>
                  </li>
                ))}
              </ul>
              {result.education?.critical_rules && result.education.critical_rules.length > 0 && (
                <div className="pt-2 border-t border-indigo-500/20">
                  <div className="text-[11px] font-bold text-indigo-300/80 mb-1">防关联教学红线：</div>
                  <ul className="space-y-1 text-[11px] text-slate-400 pl-1 list-disc list-inside">
                    {result.education.critical_rules.map((rule, idx) => (
                      <li key={idx}>{rule}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Footer */}
        <div className="flex justify-end pt-2 border-t border-slate-800">
          <button
            onClick={onClose}
            className="rounded-lg bg-slate-800 hover:bg-slate-700 px-4 py-1.5 text-xs text-slate-300 transition"
          >
            完成检测并关闭
          </button>
        </div>
      </div>
    </div>
  );
}
