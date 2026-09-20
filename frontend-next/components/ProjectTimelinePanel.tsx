'use client';

import { LabelBadge } from '@/components/ui';
import { apiFetch } from '@/lib/api';
import { relativeTime, stageZh } from '@/lib/format';
import type { ProjectEvolution, TimelinePoint } from '@/lib/types';
import { Activity, Clock, History, Milestone, Minus, Sparkles, TrendingDown, TrendingUp } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';

const trendConfig: Record<string, { label: string; className: string; icon: typeof Activity }> = {
  rising: {
    label: '稳步上升',
    className: 'bg-farm-soft text-farm dark:bg-farm/15 dark:text-farm border-farm/20',
    icon: TrendingUp,
  },
  falling: {
    label: '高位回调',
    className: 'bg-red-50 text-red-700 dark:bg-red-500/15 dark:text-red-300 border-red-200 dark:border-red-800/40',
    icon: TrendingDown,
  },
  stable: {
    label: '平稳演化',
    className: 'bg-blue-50 text-blue-700 dark:bg-blue-500/15 dark:text-blue-300 border-blue-200 dark:border-blue-800/40',
    icon: Minus,
  },
  insufficient_data: {
    label: '样本积累中',
    className: 'bg-surface-3 text-ink-muted border-line',
    icon: Activity,
  },
};

export function ProjectTimelinePanel({ projectId }: { projectId: string }) {
  const [data, setData] = useState<ProjectEvolution | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    if (!projectId) return;
    setLoading(true);
    setError('');
    try {
      const res = await apiFetch<ProjectEvolution>(`/projects/${projectId}/timeline`);
      setData(res);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '加载项目演化历史失败');
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
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-4">
          <div className="skeleton h-20" />
          <div className="skeleton h-20" />
          <div className="skeleton h-20" />
          <div className="skeleton h-20" />
        </div>
        <div className="skeleton h-28" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:bg-red-500/10 dark:text-red-300">
        {error}
        <button type="button" className="ml-3 font-medium underline" onClick={load}>
          重试
        </button>
      </div>
    );
  }

  if (!data) return null;

  const trendInfo = trendConfig[data.score_trend] || trendConfig.insufficient_data;
  const TrendIcon = trendInfo.icon;
  const sortedTimeline = [...data.timeline].reverse(); // newest first

  return (
    <div className="space-y-5">
      {/* 顶部状态与量化指标卡片 */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-4">
        <div className="rounded-xl border border-line/80 bg-surface-2/40 p-3.5">
          <div className="text-[12px] text-ink-muted">评分趋势</div>
          <div className="mt-1.5 flex items-center gap-2">
            <span
              className={`inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs font-semibold ${trendInfo.className}`}
            >
              <TrendIcon className="h-3.5 w-3.5" />
              {trendInfo.label}
            </span>
          </div>
        </div>

        <div className="rounded-xl border border-line/80 bg-surface-2/40 p-3.5">
          <div className="text-[12px] text-ink-muted">评分波动率 (StdDev)</div>
          <div className="mt-1.5 flex items-baseline gap-1">
            <span className="font-mono text-lg font-bold text-ink">
              ±{data.score_volatility.toFixed(1)}
            </span>
            <span className="text-[11px] text-ink-faint">pts</span>
          </div>
        </div>

        <div className="rounded-xl border border-line/80 bg-surface-2/40 p-3.5">
          <div className="text-[12px] text-ink-muted">评估快照积累</div>
          <div className="mt-1.5 flex items-baseline gap-1">
            <span className="font-mono text-lg font-bold text-ink">{data.snapshot_count}</span>
            <span className="text-[11px] text-ink-faint">次历史快照</span>
          </div>
        </div>

        <div className="rounded-xl border border-line/80 bg-surface-2/40 p-3.5">
          <div className="text-[12px] text-ink-muted">生命周期演进</div>
          <div className="mt-1.5 truncate font-mono text-xs font-medium text-ink" title={data.stage_progression.map(s => stageZh(s)).join(' → ')}>
            {data.stage_progression.length > 0
              ? data.stage_progression.map((s) => stageZh(s)).join(' → ')
              : '—'}
          </div>
        </div>
      </div>

      {/* AI Agent 记忆上下文摘要 */}
      {data.llm_context_summary && (
        <div className="rounded-xl border border-brand/20 bg-brand-soft/20 p-4 dark:border-brand/30 dark:bg-brand/5">
          <div className="mb-2 flex items-center gap-2 text-xs font-semibold text-brand dark:text-brand-bright">
            <Sparkles className="h-4 w-4" />
            <span>Agent 演化记忆上下文 (LLM Memory Context)</span>
          </div>
          <p className="text-[13px] leading-relaxed text-ink/90 dark:text-ink-soft">
            {data.llm_context_summary}
          </p>
        </div>
      )}

      {/* 阶段变迁关键里程碑 */}
      {data.stage_transitions && data.stage_transitions.length > 0 && (
        <div className="rounded-xl border border-line/80 bg-surface-2/30 p-4">
          <div className="mb-2.5 flex items-center gap-1.5 text-xs font-semibold text-ink-muted">
            <Milestone className="h-3.5 w-3.5" />
            <span>部署阶段跨越里程碑</span>
          </div>
          <div className="flex flex-wrap gap-2">
            {data.stage_transitions.map((st, idx) => (
              <div
                key={`${st.from_stage}-${st.to_stage}-${idx}`}
                className="flex items-center gap-2 rounded-lg border border-line bg-surface px-3 py-1.5 text-xs"
              >
                <span className="font-medium text-ink-muted">{stageZh(st.from_stage)}</span>
                <span className="text-ink-faint">→</span>
                <span className="font-semibold text-farm dark:text-farm">{stageZh(st.to_stage)}</span>
                <span className="font-mono text-[11px] text-ink-faint">
                  ({relativeTime(st.timestamp)})
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 历史评估时间轴流 */}
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <h4 className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-ink-muted">
            <History className="h-3.5 w-3.5" />
            历史评估记录 ({sortedTimeline.length})
          </h4>
          {data.first_seen_at && (
            <span className="text-[11px] text-ink-faint">
              最早建档: {relativeTime(data.first_seen_at)}
            </span>
          )}
        </div>

        {sortedTimeline.length === 0 ? (
          <div className="rounded-xl border border-dashed border-line p-6 text-center text-xs text-ink-muted">
            暂无评估快照记录
          </div>
        ) : (
          <div className="divide-y divide-line rounded-xl border border-line bg-surface">
            {sortedTimeline.map((item: TimelinePoint, idx: number) => {
              const diff = item.diff_from_previous_score;
              return (
                <div
                  key={item.snapshot_id || idx}
                  className="flex flex-col gap-2 p-3 sm:flex-row sm:items-center sm:justify-between"
                >
                  <div className="flex flex-wrap items-center gap-2.5">
                    <span className="font-mono text-[11px] text-ink-faint" title={`Run ID: ${item.run_id}`}>
                      #{item.snapshot_id}
                    </span>
                    {item.label && <LabelBadge label={item.label} />}
                    <span className="rounded bg-surface-3 px-1.5 py-0.5 font-mono text-[11px] text-ink-muted">
                      {stageZh(item.stage)}
                    </span>
                    {item.weight_version && (
                      <span className="font-mono text-[11px] text-ink-faint">
                        v:{item.weight_version}
                      </span>
                    )}
                  </div>

                  <div className="flex items-center gap-4 sm:justify-end">
                    <div className="flex items-center gap-1.5 font-mono">
                      <span className="text-xs text-ink-muted">评分:</span>
                      <span className="text-sm font-bold text-ink">
                        {item.score !== null ? item.score.toFixed(1) : '—'}
                      </span>
                      {diff !== null && diff !== undefined && (
                        <span
                          className={`text-[11px] font-semibold ${
                            diff > 0
                              ? 'text-farm dark:text-farm'
                              : diff < 0
                                ? 'text-red-500 dark:text-red-400'
                                : 'text-ink-faint'
                          }`}
                        >
                          {diff > 0 ? `+${diff.toFixed(1)}` : diff.toFixed(1)}
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-1 text-[11px] text-ink-faint">
                      <Clock className="h-3 w-3" />
                      <span>{relativeTime(item.created_at)}</span>
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
