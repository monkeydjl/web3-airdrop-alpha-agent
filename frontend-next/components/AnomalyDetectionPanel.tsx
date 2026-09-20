'use client';

import { apiFetch } from '@/lib/api';
import { formatPct, relativeTime } from '@/lib/format';
import type { AnomalyItem, AnomalyReport } from '@/lib/types';
import {
  AlertTriangle,
  CheckCircle2,
  Database,
  RefreshCw,
  ShieldAlert,
  ShieldCheck,
  TrendingUp,
} from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';

const severityBadgeConfig: Record<string, { label: string; badgeClass: string; cardClass: string }> = {
  critical: {
    label: '严重',
    badgeClass: 'bg-red-50 text-red-700 dark:bg-red-500/15 dark:text-red-300 border-red-200 dark:border-red-800/40',
    cardClass: 'border-red-200 bg-red-50/40 dark:border-red-900/30 dark:bg-red-950/20',
  },
  warning: {
    label: '预警',
    badgeClass: 'bg-watch-soft text-watch dark:bg-watch/15 dark:text-watch border-watch/20',
    cardClass: 'border-watch/20 bg-watch-soft/20 dark:border-watch/20 dark:bg-watch/5',
  },
  info: {
    label: '提示',
    badgeClass: 'bg-blue-50 text-blue-700 dark:bg-blue-500/15 dark:text-blue-300 border-blue-200 dark:border-blue-800/40',
    cardClass: 'border-line bg-surface-2/40',
  },
};

export function AnomalyDetectionPanel() {
  const [report, setReport] = useState<AnomalyReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState('');

  const fetchAnomalies = useCallback(async (force = false) => {
    if (force) setRefreshing(true);
    else setLoading(true);
    setError('');

    try {
      const url = force ? '/anomalies?force_refresh=true' : '/anomalies';
      const res = await apiFetch<AnomalyReport>(url);
      setReport(res);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '获取异常检测报告失败');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    fetchAnomalies(false);
  }, [fetchAnomalies]);

  if (loading) {
    return (
      <div className="rounded-xl border border-line bg-surface p-5 space-y-4">
        <div className="flex items-center justify-between">
          <div className="skeleton h-6 w-48" />
          <div className="skeleton h-8 w-24" />
        </div>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-4">
          <div className="skeleton h-20" />
          <div className="skeleton h-20" />
          <div className="skeleton h-20" />
          <div className="skeleton h-20" />
        </div>
        <div className="skeleton h-24" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700 dark:bg-red-500/10 dark:text-red-300">
        <div className="flex items-center justify-between">
          <span>{error}</span>
          <button
            type="button"
            className="font-medium underline"
            onClick={() => fetchAnomalies(true)}
          >
            重试
          </button>
        </div>
      </div>
    );
  }

  if (!report) return null;

  const isHealthy = report.overall_status === 'healthy';
  const isCritical = report.overall_status === 'critical';
  const drift = report.drift_summary;
  const quality = report.quality_summary;

  return (
    <div className="rounded-xl border border-line bg-surface p-5 space-y-5">
      {/* 顶部标题栏与健康状态 */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between border-b border-line pb-4">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <h3 className="text-base font-semibold text-ink">系统异常检测与数据质量巡检</h3>
            <span
              className={`inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs font-semibold ${
                isHealthy
                  ? 'bg-farm-soft text-farm dark:bg-farm/15 dark:text-farm border-farm/20'
                  : isCritical
                    ? 'bg-red-50 text-red-700 dark:bg-red-500/15 dark:text-red-300 border-red-200 dark:border-red-800/40'
                    : 'bg-watch-soft text-watch dark:bg-watch/15 dark:text-watch border-watch/20'
              }`}
            >
              {isHealthy ? (
                <>
                  <ShieldCheck className="h-3.5 w-3.5" />
                  正常运行
                </>
              ) : isCritical ? (
                <>
                  <ShieldAlert className="h-3.5 w-3.5" />
                  严重告警
                </>
              ) : (
                <>
                  <AlertTriangle className="h-3.5 w-3.5" />
                  存在预警
                </>
              )}
            </span>
          </div>
          <p className="text-xs text-ink-muted">
            全仓评分漂移（均值/标签分布/0分激增）与数据质量（P0/P1完整性、时效性、隔离积压）实时巡检 · W12-04
          </p>
        </div>

        <div className="flex items-center gap-3">
          <span className="text-xs text-ink-faint">
            上次巡检: {relativeTime(report.checked_at)}
          </span>
          <button
            type="button"
            onClick={() => fetchAnomalies(true)}
            disabled={refreshing}
            className="inline-flex items-center gap-1.5 rounded-lg border border-line bg-surface-2 px-3 py-1.5 text-xs font-medium text-ink hover:bg-surface-3 transition-colors disabled:opacity-50"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${refreshing ? 'animate-spin' : ''}`} />
            {refreshing ? '正在扫描...' : '立即巡检'}
          </button>
        </div>
      </div>

      {/* 4 栏量化指标矩阵 */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-4">
        <div className="rounded-xl border border-line/80 bg-surface-2/40 p-3.5 space-y-1">
          <div className="text-[12px] text-ink-muted flex items-center justify-between">
            <span>评分均值漂移</span>
            <TrendingUp className="h-3.5 w-3.5 text-ink-faint" />
          </div>
          <div className="flex items-baseline gap-1.5">
            <span className="font-mono text-lg font-bold text-ink">{drift.mean_score.toFixed(1)}</span>
            <span
              className={`font-mono text-xs font-semibold ${
                Math.abs(drift.mean_drift) > 15.0
                  ? 'text-watch'
                  : 'text-ink-muted'
              }`}
            >
              ({drift.mean_drift >= 0 ? `+${drift.mean_drift}` : drift.mean_drift} vs 基准)
            </span>
          </div>
          <div className="text-[11px] text-ink-faint">
            中位数: {drift.median_score.toFixed(1)} · 波动率: ±{drift.stddev_score.toFixed(1)}
          </div>
        </div>

        <div className="rounded-xl border border-line/80 bg-surface-2/40 p-3.5 space-y-1">
          <div className="text-[12px] text-ink-muted">FARM 标签比例</div>
          <div className="flex items-baseline gap-1.5">
            <span className="font-mono text-lg font-bold text-ink">
              {formatPct(drift.label_ratios.FARM || 0, 1)}
            </span>
            <span className="text-[11px] text-ink-faint">
              ({drift.label_counts.FARM || 0} / {drift.total_projects} 项目)
            </span>
          </div>
          <div className="text-[11px] text-ink-faint">
            WATCH: {formatPct(drift.label_ratios.WATCH || 0, 1)} · IGNORE: {formatPct(drift.label_ratios.IGNORE || 0, 1)}
          </div>
        </div>

        <div className="rounded-xl border border-line/80 bg-surface-2/40 p-3.5 space-y-1">
          <div className="text-[12px] text-ink-muted flex items-center justify-between">
            <span>P0 核心完整性</span>
            <Database className="h-3.5 w-3.5 text-ink-faint" />
          </div>
          <div className="flex items-baseline gap-1.5">
            <span
              className={`font-mono text-lg font-bold ${
                quality.p0_completeness < 1.0 ? 'text-red-500' : 'text-farm'
              }`}
            >
              {formatPct(quality.p0_completeness, 1)}
            </span>
            {quality.p0_missing_count > 0 && (
              <span className="text-[11px] text-red-500 font-medium">
                ({quality.p0_missing_count} 处缺失)
              </span>
            )}
          </div>
          <div className="text-[11px] text-ink-faint">
            P1 关键字段: {formatPct(quality.p1_completeness, 1)}
          </div>
        </div>

        <div className="rounded-xl border border-line/80 bg-surface-2/40 p-3.5 space-y-1">
          <div className="text-[12px] text-ink-muted">隔离区与时效性</div>
          <div className="flex items-baseline gap-1.5">
            <span className="font-mono text-lg font-bold text-ink">
              {quality.quarantine_pending}
            </span>
            <span className="text-[11px] text-ink-faint">条脏数据待审</span>
          </div>
          <div className="text-[11px] text-ink-faint">
            {quality.stale_sources.length > 0 ? (
              <span className="text-watch font-medium">
                {quality.stale_sources.length} 个采集源超时
              </span>
            ) : (
              '全部采集源新鲜度正常'
            )}
          </div>
        </div>
      </div>

      {/* 异常与告警详细清单 */}
      <div className="space-y-2.5">
        <h4 className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
          告警条目清单 ({report.anomalies.length})
        </h4>

        {report.anomalies.length === 0 ? (
          <div className="rounded-xl border border-dashed border-line p-6 text-center space-y-1">
            <div className="flex items-center justify-center gap-1.5 text-farm font-medium text-sm">
              <CheckCircle2 className="h-4 w-4" />
              <span>未发现任何评分漂移或数据质量异常</span>
            </div>
            <p className="text-xs text-ink-faint">
              全仓评分分布正常，P0 字段 100% 完整，无隔离积压或采集源超时。
            </p>
          </div>
        ) : (
          <div className="space-y-2">
            {report.anomalies.map((item: AnomalyItem) => {
              const cfg = severityBadgeConfig[item.severity] || severityBadgeConfig.info;
              return (
                <div
                  key={item.id}
                  className={`rounded-xl border p-3.5 transition-all ${cfg.cardClass}`}
                >
                  <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                    <div className="space-y-1">
                      <div className="flex items-center gap-2">
                        <span
                          className={`inline-flex items-center rounded px-1.5 py-0.5 font-mono text-[11px] font-semibold border ${cfg.badgeClass}`}
                        >
                          {cfg.label}
                        </span>
                        <span className="text-xs font-bold text-ink">{item.title}</span>
                        <span className="text-[11px] font-mono text-ink-faint">[{item.type}]</span>
                      </div>
                      <p className="text-xs leading-relaxed text-ink/90 dark:text-ink-soft">
                        {item.description}
                      </p>
                    </div>

                    <div className="shrink-0 font-mono text-xs text-right sm:text-right">
                      <div className="text-ink font-semibold">
                        当前: {typeof item.metric_value === 'number' ? item.metric_value.toFixed(2) : item.metric_value}
                      </div>
                      <div className="text-[11px] text-ink-faint">
                        阈值: {typeof item.threshold === 'number' ? item.threshold.toFixed(2) : item.threshold}
                      </div>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
