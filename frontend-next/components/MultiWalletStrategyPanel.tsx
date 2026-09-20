'use client';

import { apiFetch } from '@/lib/api';
import type { MultiWalletStrategy } from '@/lib/types';
import { AlertTriangle, Clock, DollarSign, ShieldAlert, ShieldCheck, Wallet } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';

const statusBadgeConfig: Record<string, { label: string; className: string }> = {
  recommended: {
    label: '推荐多号布局',
    className: 'bg-farm-soft text-farm dark:bg-farm/15 dark:text-farm border-farm/20',
  },
  selective: {
    label: '谨慎精选单号',
    className: 'bg-watch-soft text-watch dark:bg-watch/15 dark:text-watch border-watch/20',
  },
  ineligible: {
    label: '暂不建议多号',
    className: 'bg-surface-3 text-ink-muted border-line',
  },
};

const severityBadgeConfig: Record<string, { label: string; badgeClass: string; cardClass: string }> = {
  critical: {
    label: '红线准则',
    badgeClass: 'bg-red-50 text-red-700 dark:bg-red-500/15 dark:text-red-300 border-red-200 dark:border-red-800/40',
    cardClass: 'border-red-200/80 bg-red-50/30 dark:border-red-900/30 dark:bg-red-950/10',
  },
  warning: {
    label: '重点关注',
    badgeClass: 'bg-watch-soft text-watch dark:bg-watch/15 dark:text-watch border-watch/20',
    cardClass: 'border-line/80 bg-surface',
  },
  tip: {
    label: '优化建议',
    badgeClass: 'bg-blue-50 text-blue-700 dark:bg-blue-500/15 dark:text-blue-300 border-blue-200 dark:border-blue-800/40',
    cardClass: 'border-line/80 bg-surface',
  },
};

export function MultiWalletStrategyPanel({ projectId }: { projectId: string }) {
  const [data, setData] = useState<MultiWalletStrategy | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    if (!projectId) return;
    setLoading(true);
    setError('');
    try {
      const res = await apiFetch<MultiWalletStrategy>(`/projects/${projectId}/multi-wallet-strategy`);
      setData(res);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '加载多钱包策略失败');
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    load();
  }, [load]);

  if (loading) {
    return (
      <div className="space-y-3 py-2">
        <div className="skeleton h-8 w-1/3" />
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <div className="skeleton h-24" />
          <div className="skeleton h-24" />
          <div className="skeleton h-24" />
        </div>
        <div className="skeleton h-32" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:bg-red-500/10 dark:text-red-300">
        {error}
        <button type="button" className="ml-3 underline font-medium" onClick={load}>
          重试
        </button>
      </div>
    );
  }

  if (!data) return null;

  const statusInfo = statusBadgeConfig[data.status] || statusBadgeConfig.ineligible;

  return (
    <div className="space-y-5">
      {/* Header Banner */}
      <div className="flex flex-col gap-2 rounded-xl border border-line/80 bg-surface-2/40 p-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <span className={`inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs font-semibold ${statusInfo.className}`}>
              {data.status === 'recommended' ? (
                <ShieldCheck className="h-3.5 w-3.5" />
              ) : (
                <ShieldAlert className="h-3.5 w-3.5" />
              )}
              {statusInfo.label}
            </span>
            <span className="rounded-md border border-line bg-surface px-2 py-0.5 text-xs font-medium text-ink">
              {data.tier_zh}
            </span>
          </div>
          <p className="mt-2 text-sm leading-relaxed text-ink-muted">
            {data.strategy_summary}
          </p>
        </div>
      </div>

      {/* KPI Cards Grid */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        {/* Wallet Count */}
        <div className="rounded-xl border border-line/80 bg-surface p-3.5 shadow-sm">
          <div className="flex items-center justify-between text-ink-muted">
            <span className="text-xs font-medium">推荐钱包数量</span>
            <Wallet className="h-4 w-4 text-ink-faint" />
          </div>
          <div className="mt-2 flex items-baseline gap-1.5">
            <span className="font-mono text-2xl font-bold tabular-nums text-ink">
              {data.recommended_wallets_optimal}
            </span>
            <span className="text-xs text-ink-muted">
              号 (建议范围: {data.recommended_wallets_min} ~ {data.recommended_wallets_max})
            </span>
          </div>
          <p className="mt-1.5 text-[11px] text-ink-faint">
            基于女巫审查难度与操作复杂度综合测算
          </p>
        </div>

        {/* Capital Budget */}
        <div className="rounded-xl border border-line/80 bg-surface p-3.5 shadow-sm">
          <div className="flex items-center justify-between text-ink-muted">
            <span className="text-xs font-medium">资金预算预估</span>
            <DollarSign className="h-4 w-4 text-ink-faint" />
          </div>
          <div className="mt-2 flex items-baseline gap-1.5">
            <span className="font-mono text-xl font-bold tabular-nums text-ink">
              ${data.total_capital_usd_min} ~ ${data.total_capital_usd_max}
            </span>
            <span className="text-xs text-ink-muted">总计</span>
          </div>
          <div className="mt-1 flex items-center justify-between text-[11px] text-ink-muted">
            <span>单号: ${data.capital_per_wallet_usd_min} ~ ${data.capital_per_wallet_usd_max}</span>
          </div>
          <p className="mt-1 truncate text-[11px] text-ink-faint" title={data.capital_notes}>
            {data.capital_notes}
          </p>
        </div>

        {/* Weekly Time */}
        <div className="rounded-xl border border-line/80 bg-surface p-3.5 shadow-sm">
          <div className="flex items-center justify-between text-ink-muted">
            <span className="text-xs font-medium">时间投入预估</span>
            <Clock className="h-4 w-4 text-ink-faint" />
          </div>
          <div className="mt-2 flex items-baseline gap-1.5">
            <span className="font-mono text-2xl font-bold tabular-nums text-ink">
              {data.total_weekly_hours}
            </span>
            <span className="text-xs text-ink-muted">小时 / 周</span>
          </div>
          <div className="mt-1 text-[11px] text-ink-muted">
            单号约 {data.weekly_hours_per_wallet} 小时 / 周（含离散操作间隔）
          </div>
          <p className="mt-1.5 text-[11px] text-ink-faint">
            多号操作需严格遵循时间错峰分散
          </p>
        </div>
      </div>

      {/* Anti-Sybil Hygiene Guidelines */}
      {data.hygiene_guidelines && data.hygiene_guidelines.length > 0 && (
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="font-mono text-xs font-semibold uppercase tracking-wider text-ink-muted">
              防女巫隔离准则（Sybil Hygiene Checklist）
            </h3>
            <span className="text-[11px] text-ink-faint">
              共 {data.hygiene_guidelines.length} 条规范
            </span>
          </div>

          <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
            {data.hygiene_guidelines.map((rule) => {
              const config = severityBadgeConfig[rule.severity] || severityBadgeConfig.warning;
              return (
                <div
                  key={rule.rule_id}
                  className={`flex flex-col justify-between rounded-xl border p-3 transition ${config.cardClass}`}
                >
                  <div>
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-xs font-semibold text-ink">
                        {rule.title}
                      </span>
                      <span className={`inline-flex rounded border px-1.5 py-0.5 font-mono text-[10px] font-semibold ${config.badgeClass}`}>
                        {config.label}
                      </span>
                    </div>
                    <p className="mt-1.5 text-xs leading-relaxed text-ink-muted">
                      {rule.description}
                    </p>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Risk Warnings */}
      {data.risk_warnings && data.risk_warnings.length > 0 && (
        <div className="rounded-xl border border-watch/30 bg-watch-soft/20 p-3.5 text-xs text-ink-muted dark:bg-watch/10">
          <div className="flex items-center gap-1.5 font-semibold text-watch dark:text-watch">
            <AlertTriangle className="h-4 w-4 shrink-0" />
            <span>策略风险警示</span>
          </div>
          <ul className="mt-2 space-y-1 pl-5 list-disc text-ink-muted">
            {data.risk_warnings.map((w, idx) => (
              <li key={idx} className="leading-relaxed">
                {w}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Red-Line Compliance Callout */}
      <div className="rounded-xl border border-line/60 bg-surface-2/30 px-3.5 py-2.5 text-[11px] text-ink-faint">
        <span className="font-semibold text-ink-muted">纯策略建议声明：</span>
        本系统严格遵循纯决策辅助原则，绝不管理私钥，亦不提供自动化代投或批量脚本上链。所有多钱包行为须由用户在隔离环境中独立手动操作，防范资产交叉污染与链上女巫清洗。
      </div>
    </div>
  );
}
