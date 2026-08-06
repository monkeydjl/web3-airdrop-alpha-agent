'use client';

import { LabelDoughnut, SectorBars } from '@/components/Charts';
import { EmptyState, LabelBadge, SectionTitle, StatCard } from '@/components/ui';
import { apiFetch } from '@/lib/api';
import { LABEL_ORDER, LABEL_ZH } from '@/lib/format';
import { fetchAllProjects } from '@/lib/projects';
import type { InsightsData, Label, Project } from '@/lib/types';
import { useAsyncData } from '@/lib/useAsyncData';
import Link from 'next/link';
import { useCallback, useMemo } from 'react';

function normalizeSectors(
  raw: InsightsData['sector_counts'] | undefined,
  fallback: { name: string; count: number }[],
): { name: string; count: number }[] {
  if (!raw) return fallback;
  if (Array.isArray(raw)) {
    return raw
      .map((item) => {
        if (Array.isArray(item)) return { name: String(item[0]), count: Number(item[1]) || 0 };
        const o = item as { sector?: string; count?: number; name?: string };
        return { name: String(o.sector || o.name || 'Unknown'), count: Number(o.count) || 0 };
      })
      .filter((s) => s.count > 0)
      .sort((a, b) => b.count - a.count);
  }
  return Object.entries(raw)
    .map(([name, count]) => ({ name, count: Number(count) || 0 }))
    .sort((a, b) => b.count - a.count);
}

export default function InsightsPage() {
  const loader = useCallback(
    async (signal: AbortSignal) => {
      const [all, i] = await Promise.all([
        fetchAllProjects(signal),
        apiFetch<InsightsData>('/insights', { signal }),
      ]);
      return {
        projects: [...all.projects].sort((a, b) => (b.score ?? 0) - (a.score ?? 0)),
        insights: i,
      };
    },
    [],
  );

  // useAsyncData 负责取消旧请求并丢弃过期响应，连点"刷新"不再出现旧数据覆盖新数据
  const { data, error, loading, reload: load } = useAsyncData(loader, []);
  const projects: Project[] = data?.projects ?? [];
  const insights: InsightsData | null = data?.insights ?? null;

  const labelCounts = useMemo(() => {
    const counts: Record<Label, number> = { FARM: 0, WATCH: 0, IGNORE: 0 };
    projects.forEach((p) => {
      if (p.label in counts) counts[p.label as Label] += 1;
    });
    return counts;
  }, [projects]);

  const sectorList = useMemo(() => {
    const fromProjects = Object.entries(
      projects.reduce<Record<string, number>>((acc, p) => {
        if (!p.sector) return acc;
        acc[p.sector] = (acc[p.sector] || 0) + 1;
        return acc;
      }, {}),
    )
      .map(([name, count]) => ({ name, count }))
      .sort((a, b) => b.count - a.count);
    return normalizeSectors(insights?.sector_counts, fromProjects);
  }, [projects, insights]);

  const topFarm = useMemo(() => projects.filter((p) => p.label === 'FARM').slice(0, 10), [projects]);
  const topWatch = useMemo(
    () => projects.filter((p) => p.label === 'WATCH').slice(0, 8),
    [projects],
  );

  if (loading) {
    return (
      <div className="space-y-4 animate-fade-in">
        <div className="skeleton h-8 w-48" />
        <div className="grid gap-4 md:grid-cols-2">
          <div className="skeleton h-64" />
          <div className="skeleton h-64" />
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-xs font-semibold tracking-[0.2em] text-brand-600 dark:text-brand-300">
            数据分析
          </p>
          <h1 className="page-title">洞察</h1>
          <p className="page-sub">标签分布 · 赛道热度 · 风险团队 · 机会榜</p>
        </div>
        <button type="button" className="btn-secondary" onClick={load} disabled={loading}>
          {loading ? '加载中…' : '刷新'}
        </button>
      </div>

      {error ? (
        <div className="card flex items-center justify-between gap-3 border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:bg-red-500/10 dark:text-red-300">
          <span>{error}</span>
          <button type="button" className="underline" onClick={load}>
            重试
          </button>
        </div>
      ) : null}

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatCard label="项目总数" value={projects.length} accent="brand" />
        {LABEL_ORDER.map((l) => (
          <StatCard
            key={l}
            label={LABEL_ZH[l]}
            value={labelCounts[l]}
            accent={l === 'FARM' ? 'farm' : l === 'WATCH' ? 'watch' : 'ignore'}
          />
        ))}
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
        <div className="card p-5 lg:col-span-4">
          <SectionTitle title="标签占比" />
          <LabelDoughnut counts={labelCounts} />
          <div className="mt-4 space-y-2">
            {LABEL_ORDER.map((l) => {
              const n = labelCounts[l];
              const pct = projects.length ? Math.round((n / projects.length) * 100) : 0;
              return (
                <div key={l} className="flex items-center justify-between text-sm">
                  <LabelBadge label={l} />
                  <span className="tabular-nums text-ink-muted">
                    {n} · {pct}%
                  </span>
                </div>
              );
            })}
          </div>
        </div>

        <div className="card p-5 lg:col-span-8">
          <SectionTitle title="赛道分布" />
          <SectorBars sectors={sectorList} />
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className="card p-5">
          <SectionTitle
            title="重点参与榜"
            action={
              <Link href="/" className="text-xs text-brand-600 hover:underline dark:text-brand-300">
                返回工作台
              </Link>
            }
          />
          {topFarm.length === 0 ? (
            <EmptyState title="暂无重点参与项目" description="跑一轮采集评分后再来" />
          ) : (
            <div className="space-y-2">
              {topFarm.map((p, i) => (
                <Link
                  key={p.id}
                  href={`/project/${p.id}`}
                  className="flex items-center justify-between rounded-xl border border-line/70 px-3 py-2.5 transition hover:border-farm/40 hover:bg-farm-soft/30 dark:hover:bg-farm/10"
                >
                  <div className="flex min-w-0 items-center gap-3">
                    <span className="w-5 font-mono text-xs text-ink-faint">{i + 1}</span>
                    <div className="min-w-0">
                      <div className="truncate text-sm font-medium text-ink">{p.name}</div>
                      <div className="text-xs text-ink-faint">{p.sector}</div>
                    </div>
                  </div>
                  <span className="text-sm font-bold tabular-nums text-farm-dark dark:text-farm">
                    {p.score}
                  </span>
                </Link>
              ))}
            </div>
          )}
        </div>

        <div className="card p-5">
          <SectionTitle title="观察列表精选" />
          {topWatch.length === 0 ? (
            <p className="py-8 text-center text-sm text-ink-faint">暂无观察中的项目</p>
          ) : (
            <div className="space-y-2">
              {topWatch.map((p) => (
                <Link
                  key={p.id}
                  href={`/project/${p.id}`}
                  className="flex items-center justify-between rounded-xl border border-line/70 px-3 py-2.5 transition hover:bg-surface-2"
                >
                  <div className="min-w-0">
                    <div className="truncate text-sm font-medium text-ink">{p.name}</div>
                    <div className="text-xs text-ink-faint">{p.sector}</div>
                  </div>
                  <div className="flex items-center gap-2">
                    <LabelBadge label={p.label} />
                    <span className="text-sm font-semibold tabular-nums">{p.score}</span>
                  </div>
                </Link>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className="card p-5">
          <SectionTitle title="最热叙事" />
          {(insights?.hottest_narratives || []).length === 0 ? (
            <p className="py-8 text-center text-sm text-ink-faint">暂无叙事热度数据</p>
          ) : (
            <div className="space-y-3">
              {insights!.hottest_narratives.map((n) => (
                <div key={n.sector}>
                  <div className="mb-1 flex items-center justify-between text-sm">
                    <span className="font-medium text-ink">{n.sector}</span>
                    <span className="text-xs text-ink-muted">
                      热度 {Number(n.avg_heat_score).toFixed(2)} · {n.project_count} 个项目
                    </span>
                  </div>
                  <div className="h-1.5 overflow-hidden rounded-full bg-surface-3">
                    <div
                      className="h-full rounded-full bg-gradient-to-r from-brand-500 to-farm"
                      style={{ width: `${Math.min(100, Number(n.avg_heat_score) * 100)}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="card p-5">
          <SectionTitle title="高风险团队" />
          {(insights?.risky_teams || []).length === 0 ? (
            <p className="py-8 text-center text-sm text-ink-faint">暂无高风险团队标记</p>
          ) : (
            <div className="space-y-2">
              {insights!.risky_teams.slice(0, 10).map((t) => (
                <Link
                  key={t.id}
                  href={`/project/${t.id}`}
                  className="flex items-center justify-between rounded-xl border border-line/70 px-3 py-2.5 transition hover:border-red-300/50 hover:bg-red-50/50 dark:hover:bg-red-500/10"
                >
                  <div className="min-w-0">
                    <div className="truncate text-sm font-medium text-ink">{t.name}</div>
                    <div className="text-xs text-ink-faint">{t.sector}</div>
                  </div>
                  <span className="badge bg-red-50 text-red-700 dark:bg-red-500/15 dark:text-red-300">
                    {t.risk_level}
                  </span>
                </Link>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
