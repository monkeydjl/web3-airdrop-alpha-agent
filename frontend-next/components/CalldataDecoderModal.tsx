"use client";

import React, { useState, useEffect } from "react";
import { apiFetch } from "@/lib/api";

interface DecodedParam {
  name: string;
  type: string;
  value: any;
}

interface CalldataResult {
  ok: boolean;
  contract_address: string;
  method_selector: string;
  function_name: string;
  signature: string;
  category: string;
  safety_rating: "safe" | "caution" | "critical";
  safety_label: string;
  decoded_params: DecodedParam[];
  security_warnings: string[];
  human_readable_action: string;
}

interface Props {
  isOpen: boolean;
  onClose: () => void;
  initialContract?: string;
  initialCalldata?: string;
}

export default function CalldataDecoderModal({
  isOpen,
  onClose,
  initialContract = "0xdac17f958d2ee523a2206206994597c13d831ec7", // USDT as default
  initialCalldata = "0x095ea7b30000000000000000000000001111111254fb6c44bac0bed2854e76f90643097dffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff", // Unlimited approve
}: Props) {
  const [contractAddress, setContractAddress] = useState(initialContract);
  const [calldata, setCalldata] = useState(initialCalldata);
  const [valueEth, setValueEth] = useState("0");

  const [result, setResult] = useState<CalldataResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const runDecode = async (cAddr?: string, cData?: string) => {
    const targetAddr = cAddr !== undefined ? cAddr : contractAddress;
    const targetData = cData !== undefined ? cData : calldata;

    if (!targetAddr || !targetAddr.startsWith("0x")) {
      setError("请输入有效的合约地址 (0x...)");
      return;
    }

    setLoading(true);
    setError(null);
    try {
      const json = await apiFetch<CalldataResult>("/calldata/decode", {
        method: "POST",
        body: JSON.stringify({
          contract_address: targetAddr,
          calldata: targetData || "0x",
          value_eth: parseFloat(valueEth) || 0.0,
        }),
      });
      if (json?.ok) {
        setResult(json);
      }
    } catch (e: any) {
      setError(e.message || "解码失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (isOpen) {
      runDecode();
    }
  }, [isOpen]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm animate-fade-in">
      <div className="relative w-full max-w-3xl max-h-[90vh] overflow-y-auto rounded-2xl border border-slate-700 bg-slate-900 shadow-2xl p-6 text-slate-100 space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-slate-800 pb-4">
          <div className="flex items-center gap-3">
            <span className="text-2xl">📜</span>
            <div>
              <h3 className="text-lg font-bold text-slate-100">
                智能合约 Calldata 逆向解码与安全沙箱
              </h3>
              <p className="text-xs text-slate-400">
                逆向解构 4-byte 签名与参数树，防范无限额度授权洗劫、钓鱼 Permit 签名与恶意升级
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

        {/* Input Form & Presets */}
        <div className="p-4 rounded-xl bg-slate-950/60 border border-slate-800 space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2 text-[11px] text-slate-400">
            <span>常用典型签名测试预设:</span>
            <div className="flex flex-wrap items-center gap-1.5">
              <button
                type="button"
                onClick={() => {
                  const c = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48";
                  const d =
                    "0x095ea7b30000000000000000000000001111111254fb6c44bac0bed2854e76f90643097dffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff";
                  setContractAddress(c);
                  setCalldata(d);
                  runDecode(c, d);
                }}
                className="px-2 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-amber-400 border border-amber-900/40"
              >
                ⚠️ 无限授权 (Approve Max)
              </button>
              <button
                type="button"
                onClick={() => {
                  const c = "0xdac17f958d2ee523a2206206994597c13d831ec7";
                  const d =
                    "0xa9059cbb00000000000000000000000099999999999999999999999999999999999999990000000000000000000000000000000000000000000000000000000005f5e100";
                  setContractAddress(c);
                  setCalldata(d);
                  runDecode(c, d);
                }}
                className="px-2 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-emerald-400 border border-emerald-900/40"
              >
                ✓ 代币转账 (Transfer)
              </button>
              <button
                type="button"
                onClick={() => {
                  const c = "0x8888888888888888888888888888888888888888";
                  const d =
                    "0x3659cfe60000000000000000000000004444444444444444444444444444444444444444";
                  setContractAddress(c);
                  setCalldata(d);
                  runDecode(c, d);
                }}
                className="px-2 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-rose-400 border border-rose-900/40"
              >
                🚨 代理升级 (UpgradeTo)
              </button>
            </div>
          </div>

          <div className="space-y-2">
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5">
              <div className="sm:col-span-2">
                <label className="text-[11px] text-slate-400 block mb-1">交互合约地址</label>
                <input
                  type="text"
                  value={contractAddress}
                  onChange={(e) => setContractAddress(e.target.value)}
                  placeholder="0x..."
                  className="w-full rounded-lg bg-slate-800 border border-slate-700 p-2 text-xs text-slate-100 font-mono focus:outline-none focus:border-indigo-500"
                />
              </div>
              <div>
                <label className="text-[11px] text-slate-400 block mb-1">交易 Value (ETH)</label>
                <input
                  type="number"
                  step="0.01"
                  value={valueEth}
                  onChange={(e) => setValueEth(e.target.value)}
                  placeholder="0.0"
                  className="w-full rounded-lg bg-slate-800 border border-slate-700 p-2 text-xs text-slate-100 font-mono focus:outline-none focus:border-indigo-500"
                />
              </div>
            </div>

            <div>
              <label className="text-[11px] text-slate-400 block mb-1">
                原始 Calldata (十六进制字节码)
              </label>
              <textarea
                rows={2}
                value={calldata}
                onChange={(e) => setCalldata(e.target.value)}
                placeholder="0xa9059cbb..."
                className="w-full rounded-lg bg-slate-800 border border-slate-700 p-2 text-xs text-slate-100 font-mono focus:outline-none focus:border-indigo-500"
              />
            </div>
          </div>

          <div className="flex justify-end">
            <button
              onClick={() => runDecode()}
              disabled={loading}
              className="rounded-lg bg-indigo-600 hover:bg-indigo-500 px-5 py-2 text-xs font-semibold text-white transition disabled:opacity-50"
            >
              {loading ? "解码中..." : "⚡ 逆向解析安全沙箱"}
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
            {/* Top Rating & Action Banner */}
            <div
              className={`rounded-2xl p-5 border ${
                result.safety_rating === "safe"
                  ? "border-emerald-500/40 bg-emerald-950/20"
                  : result.safety_rating === "caution"
                  ? "border-amber-500/40 bg-amber-950/20"
                  : "border-rose-500/40 bg-rose-950/20"
              } space-y-3`}
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="text-xl">
                    {result.safety_rating === "safe"
                      ? "🛡️"
                      : result.safety_rating === "caution"
                      ? "⚠️"
                      : "🚨"}
                  </span>
                  <span className="text-sm font-bold text-slate-100">
                    {result.safety_label}
                  </span>
                  <span className="text-xs px-2 py-0.5 rounded bg-slate-800/80 text-slate-300 border border-slate-700">
                    {result.category}
                  </span>
                </div>

                <div className="flex items-center gap-2 font-mono text-xs">
                  <span className="text-slate-400">函数选择器:</span>
                  <span className="px-2 py-0.5 rounded bg-slate-800 text-indigo-300 font-bold">
                    {result.method_selector}
                  </span>
                </div>
              </div>

              <div className="p-3 rounded-xl bg-slate-950/60 border border-slate-800/80 text-xs text-slate-200 leading-relaxed">
                <span className="text-indigo-400 font-bold">📢 链上意图解读: </span>
                {result.human_readable_action}
              </div>
            </div>

            {/* Security Warnings */}
            {result.security_warnings.length > 0 && (
              <div className="rounded-xl border border-rose-500/40 bg-rose-950/20 p-4 space-y-1.5">
                <div className="text-xs font-bold text-rose-400">⚠️ 风险预警提示:</div>
                <ul className="space-y-1 text-xs text-rose-300/90 pl-1">
                  {result.security_warnings.map((w, idx) => (
                    <li key={idx}>• {w}</li>
                  ))}
                </ul>
              </div>
            )}

            {/* Decoded Parameters Table */}
            <div className="rounded-xl border border-slate-800 bg-slate-950/40 p-4 space-y-3">
              <div className="flex items-center justify-between text-xs font-bold text-slate-300">
                <span>📋 解构参数列表 ({result.decoded_params.length} 个参数)</span>
                <span className="font-mono text-slate-400 font-normal">
                  {result.signature}
                </span>
              </div>

              {result.decoded_params.length === 0 ? (
                <div className="py-4 text-center text-xs text-slate-500">
                  该函数无额外输入参数
                </div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-xs text-left">
                    <thead>
                      <tr className="border-b border-slate-800 text-[11px] text-slate-400 uppercase">
                        <th className="py-2 px-3">参数名</th>
                        <th className="py-2 px-3">类型</th>
                        <th className="py-2 px-3">解析值</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-800/60 font-mono">
                      {result.decoded_params.map((param, idx) => (
                        <tr key={idx} className="hover:bg-slate-900/40 transition">
                          <td className="py-2.5 px-3 font-semibold text-slate-200">
                            {param.name}
                          </td>
                          <td className="py-2.5 px-3 text-indigo-400 text-[11px]">
                            {param.type}
                          </td>
                          <td className="py-2.5 px-3 text-slate-100 break-all select-all">
                            {param.value}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
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
            完成并关闭
          </button>
        </div>
      </div>
    </div>
  );
}
