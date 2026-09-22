"use client";

import React, { useState, useEffect } from "react";
import { apiFetch } from "@/lib/api";

interface GasRule {
  id: string;
  chain: string;
  condition: "below" | "above";
  threshold_gwei: number;
  label: string;
  enabled: boolean;
  created_at: string;
}

interface ActiveAlert {
  rule_id: string;
  label: string;
  chain: string;
  current_gwei: number;
  threshold_gwei: number;
  condition: "below" | "above";
  severity: "success" | "warning";
  message: string;
  triggered_at: string;
}

interface Props {
  isOpen: boolean;
  onClose: () => void;
}

export default function GasAlertRuleModal({ isOpen, onClose }: Props) {
  const [rules, setRules] = useState<GasRule[]>([]);
  const [activeAlerts, setActiveAlerts] = useState<ActiveAlert[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // New rule form
  const [chain, setChain] = useState("ethereum");
  const [condition, setCondition] = useState<"below" | "above">("below");
  const [thresholdGwei, setThresholdGwei] = useState("12");
  const [label, setLabel] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const fetchAlertsAndRules = async () => {
    setLoading(true);
    setError(null);
    try {
      const [rJson, aJson] = await Promise.all([
        apiFetch<any>('/gas/alerts/rules'),
        apiFetch<any>('/gas/alerts/active'),
      ]);
      if (rJson?.ok) setRules(rJson.data);
      if (aJson?.ok) setActiveAlerts(aJson.data);
    } catch (e: any) {
      setError(e.message || "获取 Gas 告警规则失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (isOpen) {
      fetchAlertsAndRules();
    }
  }, [isOpen]);

  const handleCreateRule = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const val = parseFloat(thresholdGwei);
      if (isNaN(val) || val <= 0) throw new Error("请输入有效的 Gas 阈值");

      await apiFetch('/gas/alerts/rules', {
        method: "POST",
        body: JSON.stringify({
          chain,
          condition,
          threshold_gwei: val,
          label: label.trim() || `${chain.toUpperCase()} Gas ${condition === "below" ? "<" : ">"} ${val} Gwei`,
          enabled: true,
        }),
      });
      setLabel("");
      await fetchAlertsAndRules();
    } catch (err: any) {
      setError(err.message || "创建规则出错");
    } finally {
      setSubmitting(false);
    }
  };

  const handleToggle = async (ruleId: string, currentEnabled: boolean) => {
    try {
      await apiFetch(`/gas/alerts/rules/${ruleId}`, {
        method: "PATCH",
        body: JSON.stringify({ enabled: !currentEnabled }),
      });
      await fetchAlertsAndRules();
    } catch {
      // ignore
    }
  };

  const handleDelete = async (ruleId: string) => {
    try {
      await apiFetch(`/gas/alerts/rules/${ruleId}`, {
        method: "DELETE",
      });
      await fetchAlertsAndRules();
    } catch {
      // ignore
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm animate-fade-in">
      <div className="relative w-full max-w-2xl max-h-[90vh] overflow-y-auto rounded-2xl border border-slate-700 bg-slate-900 shadow-2xl p-6 text-slate-100 space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-slate-800 pb-4">
          <div className="flex items-center gap-3">
            <span className="text-2xl">🔔</span>
            <div>
              <h3 className="text-lg font-bold text-slate-100">全链 Gas 异动智能预警与阈值规则</h3>
              <p className="text-xs text-slate-400">捕获超低 Gas 交互窗口，规避异常拥堵磨损</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-800 hover:text-slate-100 transition"
          >
            ✕
          </button>
        </div>

        {/* Active Alerts */}
        {activeAlerts.length > 0 && (
          <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-4 space-y-2">
            <div className="flex items-center gap-2 text-xs font-bold text-amber-300">
              <span>⚡ 当前触发中的链上预警 ({activeAlerts.length})</span>
            </div>
            <div className="space-y-1.5">
              {activeAlerts.map((a, i) => (
                <div
                  key={i}
                  className="text-xs p-2 rounded-lg bg-slate-950/60 border border-slate-800 text-slate-200 flex items-center justify-between"
                >
                  <span>{a.message}</span>
                  <span className="text-[10px] text-slate-400 font-mono ml-2 shrink-0">
                    {a.triggered_at.split("T")[1]?.slice(0, 8)}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Create Rule Form */}
        <form onSubmit={handleCreateRule} className="rounded-xl border border-slate-800 bg-slate-950/60 p-4 space-y-3">
          <div className="text-xs font-bold text-slate-300 flex items-center gap-1.5">
            <span>➕ 新建 Gas 告警规则</span>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <div>
              <label className="text-[11px] text-slate-400 block mb-1">监控公链</label>
              <select
                value={chain}
                onChange={(e) => setChain(e.target.value)}
                className="w-full rounded-lg bg-slate-800 border border-slate-700 px-3 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-indigo-500"
              >
                <option value="ethereum">Ethereum (以太坊)</option>
                <option value="arbitrum">Arbitrum (One)</option>
                <option value="base">Base</option>
                <option value="optimism">Optimism</option>
                <option value="polygon">Polygon</option>
                <option value="bsc">BNB Chain</option>
              </select>
            </div>

            <div>
              <label className="text-[11px] text-slate-400 block mb-1">触发条件</label>
              <select
                value={condition}
                onChange={(e) => setCondition(e.target.value as any)}
                className="w-full rounded-lg bg-slate-800 border border-slate-700 px-3 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-indigo-500"
              >
                <option value="below">低于阈值 (低费率交互窗口)</option>
                <option value="above">高于阈值 (异常拥堵避险)</option>
              </select>
            </div>

            <div>
              <label className="text-[11px] text-slate-400 block mb-1">阈值 (Gwei)</label>
              <input
                type="number"
                step="any"
                min="0.0001"
                value={thresholdGwei}
                onChange={(e) => setThresholdGwei(e.target.value)}
                required
                className="w-full rounded-lg bg-slate-800 border border-slate-700 px-3 py-1.5 text-xs text-slate-100 focus:outline-none focus:border-indigo-500 font-mono"
              />
            </div>
          </div>

          <div>
            <label className="text-[11px] text-slate-400 block mb-1">备注说明 (可选)</label>
            <input
              type="text"
              placeholder="例如: 主网大额质押黄金窗口"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              className="w-full rounded-lg bg-slate-800 border border-slate-700 px-3 py-1.5 text-xs text-slate-100 focus:outline-none focus:border-indigo-500"
            />
          </div>

          <div className="flex justify-end">
            <button
              type="submit"
              disabled={submitting}
              className="rounded-lg bg-indigo-600 hover:bg-indigo-500 px-4 py-1.5 text-xs font-semibold text-white transition disabled:opacity-50"
            >
              {submitting ? "正在保存..." : "添加预警规则"}
            </button>
          </div>
        </form>

        {error && (
          <div className="rounded-lg bg-red-950/40 border border-red-800/60 p-2.5 text-xs text-red-300">
            {error}
          </div>
        )}

        {/* Existing Rules List */}
        <div className="space-y-3">
          <div className="flex items-center justify-between text-xs font-bold text-slate-300">
            <span>📋 已配置规则列表 ({rules.length})</span>
            <button
              onClick={fetchAlertsAndRules}
              disabled={loading}
              className="text-[11px] text-indigo-400 hover:text-indigo-300"
            >
              {loading ? "同步中..." : "🔄 刷新状态"}
            </button>
          </div>

          <div className="space-y-2 max-h-60 overflow-y-auto pr-1">
            {rules.map((r) => (
              <div
                key={r.id}
                className="rounded-xl border border-slate-800 bg-slate-950/40 p-3 flex items-center justify-between gap-3 text-xs"
              >
                <div className="space-y-0.5">
                  <div className="flex items-center gap-2">
                    <span className="font-semibold text-slate-200">{r.label}</span>
                    <span className="px-2 py-0.5 rounded bg-slate-800 text-[10px] uppercase font-mono text-indigo-300">
                      {r.chain}
                    </span>
                    <span
                      className={`px-2 py-0.5 rounded text-[10px] font-mono ${
                        r.condition === "below"
                          ? "bg-emerald-950/50 text-emerald-400 border border-emerald-800/40"
                          : "bg-rose-950/50 text-rose-400 border border-rose-800/40"
                      }`}
                    >
                      {r.condition === "below" ? "<" : ">"} {r.threshold_gwei} Gwei
                    </span>
                  </div>
                  <div className="text-[10px] text-slate-500">
                    创建时间: {r.created_at.slice(0, 10)}
                  </div>
                </div>

                <div className="flex items-center gap-2 shrink-0">
                  <button
                    onClick={() => handleToggle(r.id, r.enabled)}
                    className={`px-2.5 py-1 rounded text-[11px] font-medium transition ${
                      r.enabled
                        ? "bg-emerald-600/20 text-emerald-300 border border-emerald-500/30"
                        : "bg-slate-800 text-slate-400 border border-slate-700"
                    }`}
                  >
                    {r.enabled ? "已启用" : "已暂停"}
                  </button>
                  <button
                    onClick={() => handleDelete(r.id)}
                    className="p-1 text-slate-500 hover:text-red-400 transition"
                    title="删除规则"
                  >
                    🗑️
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>

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
