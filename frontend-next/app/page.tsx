'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { apiFetch } from '@/lib/api';
import { exportProjectsCsv } from '@/lib/export';
import { LABEL_ORDER, LABEL_ZH, sortProjects, stageZh } from '@/lib/format';
import { fetchAllProjects } from '@/lib/projects';
import { normalizeCollectionSource } from '@/lib/types';
import type { CollectionSourceApi, Label, Project } from '@/lib/types';
import { useAsyncData } from '@/lib/useAsyncData';
import { LabelDoughnut, SectorBars } from '@/components/Charts';
import { ProjectCard } from '@/components/ProjectCard';
import { EmptyState, LabelBadge, SkeletonGrid, StatCard, Toast } from '@/components/ui';

type SortBy = 'score' | 'name' | 'confidence';
type ViewMode = 'grid' | 'table';

export default function DashboardPage() {
  const router = useRouter();
  const [labelFilter, setLabelFilter] = useState<Label | ''>('');
  const [sectorFilter, setSectorFilter] = useState('');
  const [keyword, setKeyword] = useState('');
  const [hideIgnore, setHideIgnore] = useState(true);
  const [hasFundingOnly, setHasFundingOnly] = useState(false);
  const [sortBy, setSortBy] = useState<SortBy>('score');
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc');
  const [running, setRunning] = useState(false);
  const [runStatus, setRunStatus] = useState('');
  const [view, setView] = useState<ViewMode>('grid');
  const [toast, setToast] = useState<{ message: string; type: 'success' | 'error' | 'info' } | null>(null);

  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const showToast = (message: string, type: 'success' | 'error' | 'info' = 'info') => {
    if (toastTimer.current) clearTimeout(toastTimer.current);
    setToast({ message, type });
    toastTimer.current = setTimeout(() => setToast(null), 4200);
  };
  useEffect(() => () => { if (toastTimer.current) clearTimeout(toastTimer.current); }, []);

  const loader = useCallback(async (signal: AbortSignal) => {
    const all = await fetchAllProjects(signal);
    return { ...all, projects: sortProjects(all.projects, 'score', 'desc') };
  }, []);

  const { data, error, loading, reload: loadProjects } = useAsyncData(loader, []);
  const projects: Project[] = useMemo(() => data?.projects ?? [], [data]);
  const truncated = data?.truncated ?? false;

  const runPipeline = async () => {
    setRunning(true);
    setRunStatus('正在检查采集源…');
    try {
      const sources = await apiFetch<{ sources: CollectionSourceApi[] }>('/collections/sources');
      const enabled = (sources.sources || []).map(normalizeCollectionSource).filter((s) => s.enabled);
      let ok = 0, fail = 0;
      for (const s of enabled) {
        setRunStatus(`正在采集：${s.source_name || s.source_id}…`);
        try { await apiFetch(`/collections/${s.source_id}/trigger`, { method: 'POST', body: '{}' }); ok++; }
        catch { fail++; }
      }
      setRunStatus('正在运行评分队列…');
      const run = await apiFetch<{ scored_count?: number; top_score?: number }>('/run', { method: 'POST', body: '{}' });
      showToast(`完成 · 采集成功 ${ok}${fail ? ` / 失败 ${fail}` : ''} · 已评分 ${run.scored_count ?? 0} · 最高分 ${run.top_score ?? '—'}`, 'success');
      loadProjects();
    } catch (err: unknown) {
      showToast(err instanceof Error ? err.message : 'Pipeline 失败', 'error');
    } finally { setRunning(false); setRunStatus(''); }
  };

  const stats = useMemo(() => {
    const counts: Record<Label, number> = { FARM: 0, WATCH: 0, IGNORE: 0 };
    let sum = 0;
    projects.forEach((p) => { if (p.label in counts) counts[p.label as Label]++; sum += p.score || 0; });
    return { counts, total: projects.length, avg: projects.length ? Math.round(sum / projects.length) : 0 };
  }, [projects]);

  const sectors = useMemo(() => {
    const map = new Map<string, number>();
    projects.forEach((p) => { if (p.sector) map.set(p.sector, (map.get(p.sector) || 0) + 1); });
    return Array.from(map.entries()).map(([name, count]) => ({ name, count })).sort((a, b) => b.count - a.count);
  }, [projects]);

  const filtered = useMemo(() => {
    let list = projects.filter((p) => {
      if (hideIgnore && !labelFilter && p.label === 'IGNORE') return false;
      if (labelFilter && p.label !== labelFilter) return false;
      if (sectorFilter && p.sector !== sectorFilter) return false;
      if (keyword && !p.name.toLowerCase().includes(keyword.toLowerCase())) return false;
      if (hasFundingOnly && !p.funding?.funding_total_usd && !p.funding?.recent_funding) return false;
      return true;
    });
    return sortProjects(list, sortBy, sortOrder);
  }, [projects, hideIgnore, labelFilter, sectorFilter, keyword, hasFundingOnly, sortBy, sortOrder]);

  return (
    <div className="space-y-6 animate-fade-in">
      {toast && <Toast message={toast.message} type={toast.type} />}

      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-xs font-semibold tracking-[0.2em] text-farm dark:text-farm">指挥中心</p>
          <h1 className="page-title">项目雷达</h1>
          <p className="page-sub">自动发现 · 六维评分 · 重点参与 / 观察 / 忽略 · 共 {stats.total} 个项目</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button type="button" onClick={loadProjects} className="btn-secondary" disabled={loading || running}>刷新</button>
          <button type="button" onClick={runPipeline} className="btn-primary" disabled={running}>
            {running ? <><span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-white/30 border-t-white" />运行中</> : <>▶ 采集并评分</>}
          </button>
        </div>
      </div>

      {/* Running status */}
      {running && runStatus && (
        <div className="card flex items-center gap-3 border-farm/30 bg-farm-soft/50 px-4 py-3 text-sm text-farm dark:border-farm/20 dark:bg-farm/10 dark:text-farm">
          <span className="h-2 w-2 animate-pulse rounded-full bg-farm" />
          {runStatus}
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="card flex flex-wrap items-center justify-between gap-3 border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300">
          <span>加载失败：{error}</span>
          <button type="button" className="btn-secondary !py-1" onClick={loadProjects}>重试</button>
        </div>
      )}

      {/* Stats */}
      <div className="stat-grid">
        <StatCard label="重点参与" value={stats.counts.FARM} accent="farm" hint="优先交互" />
        <StatCard label="观察" value={stats.counts.WATCH} accent="watch" hint="持续跟踪" />
        <StatCard label="忽略" value={stats.counts.IGNORE} accent="ignore" hint="低优先级" />
        <StatCard label="平均分" value={stats.avg} accent="brand" hint={`共 ${stats.total} 个项目`} />
      </div>

      {/* Charts */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
        <div className="card p-5 lg:col-span-4">
          <h2 className="mb-4 text-sm font-semibold text-ink">标签分布</h2>
          <LabelDoughnut counts={stats.counts} />
          <div className="mt-4 flex flex-wrap justify-center gap-3">
            {LABEL_ORDER.map((l) => (
              <button key={l} type="button" onClick={() => setLabelFilter((cur) => (cur === l ? '' : l))}
                className={`transition ${labelFilter === l ? 'scale-105' : 'opacity-80 hover:opacity-100'}`}>
                <LabelBadge label={l} />
                <span className="ml-1 text-xs text-ink-muted">{stats.counts[l]}</span>
              </button>
            ))}
          </div>
        </div>
        <div className="card p-5 lg:col-span-8">
          <h2 className="mb-2 text-sm font-semibold text-ink">赛道分布（前 8）</h2>
          <SectorBars sectors={sectors} />
        </div>
      </div>

      {/* Toolbar */}
      <div className="card p-3">
        <div className="toolbar">
          <select className="select" value={labelFilter} onChange={(e) => setLabelFilter(e.target.value as Label | '')}>
            <option value="">全部标签</option>
            {LABEL_ORDER.map((l) => <option key={l} value={l}>{LABEL_ZH[l]}</option>)}
          </select>
          <select className="select" value={sectorFilter} onChange={(e) => setSectorFilter(e.target.value)}>
            <option value="">全部赛道</option>
            {sectors.map((s) => <option key={s.name} value={s.name}>{s.name} ({s.count})</option>)}
          </select>
          <select className="select" value={`${sortBy}-${sortOrder}`} onChange={(e) => {
            const [b, o] = e.target.value.split('-') as [SortBy, 'asc' | 'desc'];
            setSortBy(b); setSortOrder(o);
          }}>
            <option value="score-desc">评分从高到低</option>
            <option value="score-asc">评分从低到高</option>
            <option value="confidence-desc">置信度从高到低</option>
            <option value="name-asc">名称排序</option>
          </select>
          <input className="input flex-1 min-w-[200px]" placeholder="搜索项目名称…" value={keyword} onChange={(e) => setKeyword(e.target.value)} />
          <label className="flex cursor-pointer items-center gap-2 text-sm text-ink-muted">
            <input type="checkbox" className="rounded border-line text-farm focus:ring-farm/30" checked={hideIgnore} onChange={(e) => setHideIgnore(e.target.checked)} />
            隐藏「忽略」
          </label>
          <label className="flex cursor-pointer items-center gap-2 text-sm text-ink-muted">
            <input type="checkbox" className="rounded border-line text-farm focus:ring-farm/30" checked={hasFundingOnly} onChange={(e) => setHasFundingOnly(e.target.checked)} />
            有融资信号
          </label>
          <div className="toolbar-actions">
            <button type="button" className="btn-secondary btn-sm" disabled={filtered.length === 0} onClick={() => exportProjectsCsv(filtered)}>
              导出 CSV ({filtered.length})
            </button>
            <div className="seg">
              {(['grid', 'table'] as const).map((v) => (
                <button key={v} type="button" onClick={() => setView(v)} aria-pressed={view === v}
                  className={`seg-item ${view === v ? 'active' : ''}`}>
                  {v === 'grid' ? '卡片' : '表格'}
                </button>
              ))}
            </div>
          </div>
        </div>
        <div className="flex items-center justify-between text-xs text-ink-faint mt-2">
          <span>当前显示 {filtered.length} / 共 {projects.length} 个</span>
          {truncated && <span className="text-watch">数据量超出加载上限</span>}
        </div>
      </div>

      {/* Content */}
      {loading ? <SkeletonGrid n={8} /> : filtered.length === 0 ? (
        <EmptyState
          title={projects.length === 0 ? '还没有项目数据' : '当前筛选无结果'}
          description={projects.length === 0 ? '点击「采集并评分」从 DefiLlama / GitHub 等源拉取并写入评分结果' : '尝试清空筛选，或关闭「隐藏忽略」'}
          action={projects.length === 0 ? (
            <button type="button" className="btn-primary" onClick={runPipeline} disabled={running}>▶ 开始采集评分</button>
          ) : (
            <button type="button" className="btn-secondary" onClick={() => { setLabelFilter(''); setSectorFilter(''); setKeyword(''); setHideIgnore(false); setHasFundingOnly(false); }}>清除筛选</button>
          )}
        />
      ) : view === 'grid' ? (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {filtered.map((p, i) => <ProjectCard key={p.id} project={p} rank={i + 1} />)}
        </div>
      ) : (
        <div className="card overflow-hidden">
          <div className="overflow-x-auto">
            <table className="data-table">
              <thead>
                <tr><th>序号</th><th>项目</th><th>赛道</th><th>阶段</th><th>标签</th><th>评分</th><th>置信度</th></tr>
              </thead>
              <tbody>
                {filtered.map((p, i) => (
                  <tr key={p.id} onClick={() => router.push(`/project/${p.id}`)}>
                    <td className="font-mono text-xs text-ink-faint">{i + 1}</td>
                    <td className="font-medium text-ink">{p.name}</td>
                    <td className="text-ink-muted">{p.sector}</td>
                    <td className="text-ink-muted">{stageZh(p.stage)}</td>
                    <td><LabelBadge label={p.label} /></td>
                    <td className="font-semibold tabular-nums">{p.score}</td>
                    <td className="tabular-nums text-ink-muted">{Math.round((p.confidence || 0) * 100)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
