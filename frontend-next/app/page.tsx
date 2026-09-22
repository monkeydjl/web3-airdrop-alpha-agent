'use client';

import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { apiFetch } from '@/lib/api';
import { exportProjectsCsv } from '@/lib/export';
import { LABEL_ORDER, hasExplicitAirdropSignal, sortProjects, stageZh } from '@/lib/format';
import { fetchAllProjects } from '@/lib/projects';
import { normalizeCollectionSource } from '@/lib/types';
import { useAsyncData } from '@/lib/useAsyncData';
import { ActionQueue } from '@/components/ActionQueue';
import { LabelDoughnut, SectorBars } from '@/components/Charts';
import { ProjectCard } from '@/components/ProjectCard';
import { TopBar } from '@/components/TopBar';
import { EmptyState, LabelBadge, SkeletonGrid, StatCard, Toast } from '@/components/ui';
import { AlphaDigestModal } from '@/components/AlphaDigestModal';
import DailyBriefingModal from '@/components/DailyBriefingModal';
import { HunterPersonaSelector } from '@/components/HunterPersonaSelector';
import { GasTrackerWidget } from '@/components/GasTrackerWidget';
import type { CollectionSourceApi, HunterPersonaId, Label, Project } from '@/lib/types';

type SortBy = 'score' | 'name' | 'confidence';
type ViewMode = 'grid' | 'table';

/** apiFetch 已解包后端 data 字段 */
interface DashboardOverview {
  today?: {
    collection_runs?: { total?: number; success?: number; failed?: number };
    new_projects?: number;
    new_farm_projects?: number;
  };
  discovery?: { pending_count?: number; today_new?: number; total?: number };
  shadow?: { saved_today?: number; label_counts?: Record<string, number> };
}

export default function DashboardPage() {
  return (
    <Suspense>
      <DashboardContent />
    </Suspense>
  );
}

function DashboardContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const initialPersona = (searchParams.get('persona') as HunterPersonaId) || 'balanced';
  const [persona, setPersona] = useState<HunterPersonaId>(initialPersona);
  const [labelFilter, setLabelFilter] = useState<Label | ''>('');
  const [sectorFilter, setSectorFilter] = useState('');
  const [keyword, setKeyword] = useState('');
  const [hideIgnore, setHideIgnore] = useState(true);
  const [hasFundingOnly, setHasFundingOnly] = useState(false);
  const [zeroCostOnly, setZeroCostOnly] = useState(false);
  const [explicitAirdropOnly, setExplicitAirdropOnly] = useState(false);
  // 「分数已达 FARM 线、但缺参与路径」是库里唯一上不去的一批 —— 单独抽出来做
  // 人工验证清单（被 veto=no_participation_path 压回 WATCH 的那 86 行）。
  const [needsVerifyOnly, setNeedsVerifyOnly] = useState(false);
  // 「不参与」默认从工作台隐藏（这是它的主要用途：说不要了就别天天出现），
  // 可以从「显示不参与」开关找回 —— 找回入口必须存在，否则就是单向墙。
  const [showSkipped, setShowSkipped] = useState(false);
  const [stageFilter, setStageFilter] = useState('');
  const [minScore, setMinScore] = useState('');
  const [sortBy, setSortBy] = useState<SortBy>('score');
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc');
  const [running, setRunning] = useState(false);
  const [runStatus, setRunStatus] = useState('');
  const [view, setView] = useState<ViewMode>('grid');
  const [showCharts, setShowCharts] = useState(false);
  const [showDigestModal, setShowDigestModal] = useState(false);
  const [showBriefingModal, setShowBriefingModal] = useState(false);
  const [dailyFlash, setDailyFlash] = useState<{ ticker_text: string } | null>(null);
  const [toast, setToast] = useState<{ message: string; type: 'success' | 'error' | 'info' } | null>(null);

  useEffect(() => {
    apiFetch<{ data: { ticker_text: string } }>('/dashboard/daily-flash')
      .then((res) => {
        if (res?.data?.ticker_text) {
          setDailyFlash(res.data);
        }
      })
      .catch(() => {});
  }, []);

  // 顶栏搜索 → ?keyword=xxx → 同步到本地筛选
  useEffect(() => {
    const q = searchParams.get('keyword');
    if (q != null) setKeyword(q);
    const p = searchParams.get('persona') as HunterPersonaId;
    if (p && ['balanced', 'zero_cost', 'whale_restaking', 'high_beta'].includes(p)) {
      setPersona(p);
    }
  }, [searchParams]);

  const handlePersonaChange = (newPersona: HunterPersonaId) => {
    setPersona(newPersona);
    const params = new URLSearchParams(searchParams.toString());
    if (newPersona === 'balanced') {
      params.delete('persona');
    } else {
      params.set('persona', newPersona);
    }
    const newUrl = params.toString() ? `?${params.toString()}` : window.location.pathname;
    router.replace(newUrl, { scroll: false });
  };

  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const showToast = (message: string, type: 'success' | 'error' | 'info' = 'info') => {
    if (toastTimer.current) clearTimeout(toastTimer.current);
    setToast({ message, type });
    toastTimer.current = setTimeout(() => setToast(null), 4200);
  };
  useEffect(() => () => { if (toastTimer.current) clearTimeout(toastTimer.current); }, []);

  const [curatedOnly, setCuratedOnly] = useState(false);
  // 工作台默认展示全部候选池（实时监控与评分项目）。
  // 可随时点击「✨ 精选模式」过滤查看同时满足 90 天内链上任务凭证的强证据项目。

  const loader = useCallback(
    async (signal: AbortSignal) => {
      const all = await fetchAllProjects(signal, { curated: curatedOnly, persona });
      return { ...all, projects: sortProjects(all.projects, 'score', 'desc') };
    },
    [curatedOnly, persona],
  );

  const { data, error, loading, reload: loadProjects } = useAsyncData(loader, [curatedOnly, persona]);
  const [projectOverrides, setProjectOverrides] = useState<Record<string, Partial<Project>>>({});

  const projects: Project[] = useMemo(() => {
    const raw = data?.projects ?? [];
    if (Object.keys(projectOverrides).length === 0) return raw;
    return raw.map((p) => (projectOverrides[p.id] ? { ...p, ...projectOverrides[p.id] } : p));
  }, [data, projectOverrides]);
  const truncated = data?.truncated ?? false;

  // 「今日流水线」真实聚合数据（发现队列 / 影子引擎 / 采集运行）
  const [overview, setOverview] = useState<DashboardOverview | null>(null);
  useEffect(() => {
    apiFetch<DashboardOverview>('/dashboard/overview')
      .then((res) => setOverview(res ?? null))
      .catch(() => setOverview(null));
  }, [loading]);

  const overviewRuns = overview?.today?.collection_runs ?? {};
  const overviewFarm = overview?.shadow?.label_counts?.FARM ?? 0;
  const overviewSavedToday = overview?.shadow?.saved_today ?? 0;
  const pendingDiscoveries = overview?.discovery?.pending_count ?? 0;
  const todayNew = overview?.discovery?.today_new ?? 0;

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

  const handleProjectUpdate = useCallback(
    (updated: { id: string; label: 'FARM' | 'WATCH' | 'IGNORE'; veto: string | null; reason?: string[] }) => {
      setProjectOverrides((prev) => ({
        ...prev,
        [updated.id]: {
          ...(prev[updated.id] || {}),
          ...updated,
        },
      }));
    },
    [],
  );

  const handleActionQueueDone = useCallback(
    (message: string, type: 'success' | 'error', projectId?: string) => {
      showToast(message, type);
      if (type === 'success' && projectId) {
        handleProjectUpdate({
          id: projectId,
          label: 'FARM',
          veto: null,
        });
        loadProjects();
      }
    },
    [showToast, handleProjectUpdate, loadProjects],
  );

  const stats = useMemo(() => {
    const counts: Record<Label, number> = { FARM: 0, WATCH: 0, IGNORE: 0 };
    let sum = 0;
    let top = 0;
    let needsVerify = 0;
    let explicitAirdrop = 0;
    projects.forEach((p) => {
      if (p.label in counts) counts[p.label as Label]++;
      if (p.veto === 'no_participation_path') needsVerify++;
      if (hasExplicitAirdropSignal(p)) explicitAirdrop++;
      sum += p.score || 0;
      top = Math.max(top, p.score || 0);
    });
    return { counts, total: projects.length, avg: projects.length ? Math.round(sum / projects.length) : 0, top, needsVerify, explicitAirdrop };
  }, [projects]);

  const sectors = useMemo(() => {
    const map = new Map<string, number>();
    projects.forEach((p) => { if (p.sector) map.set(p.sector, (map.get(p.sector) || 0) + 1); });
    return Array.from(map.entries()).map(([name, count]) => ({ name, count })).sort((a, b) => b.count - a.count);
  }, [projects]);

  const stages = useMemo(() => {
    const map = new Map<string, number>();
    projects.forEach((p) => { if (p.stage) map.set(p.stage, (map.get(p.stage) || 0) + 1); });
    return Array.from(map.entries()).map(([name, count]) => ({ name, count })).sort((a, b) => b.count - a.count);
  }, [projects]);

  const filtered = useMemo(() => {
    const list = projects.filter((p) => {
      if (hideIgnore && !labelFilter && p.label === 'IGNORE') return false;
      if (!showSkipped && p.skipped) return false;
      if (labelFilter && p.label !== labelFilter) return false;
      if (sectorFilter && p.sector !== sectorFilter) return false;
      if (stageFilter && p.stage !== stageFilter) return false;
      if (minScore && (p.score ?? 0) < Number(minScore)) return false;
      if (keyword && !p.name.toLowerCase().includes(keyword.toLowerCase())) return false;
      if (explicitAirdropOnly && !hasExplicitAirdropSignal(p)) return false;
      if (hasFundingOnly && !p.funding?.funding_total_usd && !p.funding?.recent_funding) return false;
      if (zeroCostOnly) {
        const hasTestnet = Boolean(p.signals?.has_testnet || p.stage === 'testnet');
        const isNotUnviable = !p.reason?.includes('LOW_RUNWAY_RISK') && !p.reason?.includes('HEAVY_CAPITAL_LOCKUP');
        if (!hasTestnet || !isNotUnviable) return false;
      }
      if (needsVerifyOnly && p.veto !== 'no_participation_path') return false;
      return true;
    });
    return sortProjects(list, sortBy, sortOrder);
  }, [projects, hideIgnore, showSkipped, labelFilter, sectorFilter, stageFilter, minScore, keyword, explicitAirdropOnly, hasFundingOnly, zeroCostOnly, needsVerifyOnly, sortBy, sortOrder]);

  return (
    <>
      {toast && <Toast message={toast.message} type={toast.type} />}

      <TopBar title="项目雷达" subtitle={`自动发现 · 六维评分 · 重点参与 / 观察 / 忽略 · 共 ${stats.total} 个项目`}>
        <GasTrackerWidget />
        <button type="button" onClick={loadProjects} className="btn-secondary" disabled={loading || running}>刷新</button>
        <button type="button" onClick={runPipeline} className="btn-primary" disabled={running}>
          {running ? <><span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-white/30 border-t-white" />运行中</> : <>▶ 采集并评分</>}
        </button>
      </TopBar>

    <div className="app-content space-y-6 animate-fade-in">

      {/* Running status */}
      {running && runStatus && (
        <div className="dash-card flex items-center gap-3 border-farm/30 bg-farm-soft/50 px-4 py-3 text-sm text-farm dark:border-farm/20 dark:bg-farm/10 dark:text-farm">
          <span className="h-2 w-2 animate-pulse rounded-full bg-farm" />
          {runStatus}
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="dash-card flex flex-wrap items-center justify-between gap-3 border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300">
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

      {/* 今日焦点行动与流水线动态：高优先级首屏置顶 */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
        <div className="lg:col-span-8">
          <ActionQueue limit={5} onDone={handleActionQueueDone} />
        </div>
        <div className="lg:col-span-4">
          <div className="dash-card p-5 h-full flex flex-col justify-between">
            <div>
              <div className="mb-3 flex items-center justify-between">
                <h2 className="text-sm font-bold text-ink flex items-center gap-1.5">
                  <span className="h-2 w-2 rounded-full bg-farm animate-ping" />
                  今日流水线动态
                </h2>
                <span className="font-mono text-[10px] text-ink-faint uppercase tracking-wider">Agent Stream</span>
              </div>
              <ul className="pipeline-list space-y-2.5 text-xs">
                <li className="pipeline-row flex items-center justify-between p-2.5 rounded-lg bg-surface-2/60 border border-line/60">
                  <span className="font-mono text-[11px] font-semibold text-farm px-1.5 py-0.5 rounded bg-farm/10">采集引擎</span>
                  <span className="pipeline-text font-mono">
                    运行 <strong>{overviewRuns.total ?? 0}</strong> 次
                    {overviewRuns.success ? <span className="text-farm"> · 成功 {overviewRuns.success}</span> : ''}
                    {overviewRuns.failed ? <span className="text-watch"> · 失败 {overviewRuns.failed}</span> : ''}
                  </span>
                </li>
                <li className="pipeline-row flex items-center justify-between p-2.5 rounded-lg bg-surface-2/60 border border-line/60">
                  <span className="font-mono text-[11px] font-semibold text-cyan-400 px-1.5 py-0.5 rounded bg-cyan-400/10">新增项目</span>
                  <span className="pipeline-text font-mono">
                    今日发现 <strong>{overview?.today?.new_projects ?? 0}</strong> 个
                    {overview?.today?.new_farm_projects ? <span className="text-farm font-bold"> · FARM {overview.today.new_farm_projects}</span> : ''}
                  </span>
                </li>
                <li className="pipeline-row flex items-center justify-between p-2.5 rounded-lg bg-surface-2/60 border border-line/60">
                  <span className="font-mono text-[11px] font-semibold text-indigo-400 px-1.5 py-0.5 rounded bg-indigo-400/10">影子评估</span>
                  <span className="pipeline-text font-mono">
                    评估 <strong>{overviewSavedToday}</strong> · FARM <strong className="text-farm">{overviewFarm}</strong>
                  </span>
                </li>
              </ul>
            </div>
            <div className="pt-3.5 border-t border-line/60 mt-3 flex items-center justify-between text-xs">
              <span className="text-ink-muted">
                待处理发现 <strong className="text-ink font-mono">{pendingDiscoveries}</strong> 条
                <span className="text-ink-faint"> (今日新入 {todayNew})</span>
              </span>
              <button
                type="button"
                onClick={() => router.push('/discoveries')}
                className="font-semibold text-farm hover:underline whitespace-nowrap transition flex items-center gap-1"
              >
                进入队列 →
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Daily Alpha Flash Banner */}
      {dailyFlash && (
        <div className="rounded-xl border border-brand-500/25 bg-gradient-to-r from-brand-500/10 via-surface-2 to-surface p-3 sm:px-4 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-2.5">
          <div className="flex items-center gap-2 text-xs">
            <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-brand-500/20 text-brand-500 font-bold">
              ⚡
            </span>
            <span className="text-ink font-medium leading-relaxed">
              {dailyFlash.ticker_text}
            </span>
          </div>
          <div className="flex items-center gap-2 shrink-0 text-xs">
            <button
              type="button"
              onClick={() => setShowDigestModal(true)}
              className="text-brand-600 dark:text-brand-400 hover:underline font-semibold whitespace-nowrap"
            >
              投研速递 →
            </button>
            <span className="text-line">|</span>
            <button
              type="button"
              onClick={() => setShowBriefingModal(true)}
              className="px-2.5 py-1 rounded-lg bg-indigo-500/20 text-indigo-300 border border-indigo-500/30 hover:bg-indigo-500/30 font-semibold whitespace-nowrap flex items-center gap-1 transition"
            >
              <span>📰</span>
              <span>今日晚报</span>
            </button>
          </div>
        </div>
      )}

      {/* Hunter Persona & Adaptive Weights Selector */}
      <HunterPersonaSelector
        currentPersona={persona}
        onChange={handlePersonaChange}
        loading={loading}
      />

      {/* Modern Cyber Toolbar */}
      <div className="dash-card p-4 space-y-3.5">
        {/* Row 1: Fast Filter Pills + Search + Sort + Actions */}
        <div className="flex flex-col xl:flex-row items-stretch xl:items-center justify-between gap-3">
          {/* Quick Filter Pills */}
          <div className="flex flex-wrap items-center gap-1.5">
            <button
              type="button"
              onClick={() => setCuratedOnly((prev) => !prev)}
              className={`px-3 py-1.5 rounded-xl text-xs font-semibold transition ${
                curatedOnly
                  ? 'bg-cyan-400 text-slate-950 shadow-md shadow-cyan-400/20'
                  : 'bg-surface-2 text-cyan-300 hover:bg-surface-3 border border-cyan-500/25'
              }`}
            >
              ✨ 精选模式
            </button>
            <button
              type="button"
              onClick={() => { setLabelFilter(''); setNeedsVerifyOnly(false); setHasFundingOnly(false); setZeroCostOnly(false); setExplicitAirdropOnly(false); }}
              className={`px-3 py-1.5 rounded-xl text-xs font-semibold transition ${
                !labelFilter && !needsVerifyOnly && !hasFundingOnly && !zeroCostOnly && !explicitAirdropOnly
                  ? 'bg-farm text-slate-950 shadow-md shadow-farm/20'
                  : 'bg-surface-2 text-ink-muted hover:text-ink border border-line'
              }`}
            >
              全部 ({projects.length})
            </button>
            <button
              type="button"
              onClick={() => { setLabelFilter('FARM'); setNeedsVerifyOnly(false); }}
              className={`px-3 py-1.5 rounded-xl text-xs font-semibold transition ${
                labelFilter === 'FARM'
                  ? 'bg-farm text-slate-950 shadow-md shadow-farm/20'
                  : 'bg-surface-2 text-emerald-400 hover:bg-surface-3 border border-emerald-500/25'
              }`}
            >
              重点 FARM ({stats.counts.FARM})
            </button>
            <button
              type="button"
              onClick={() => { setLabelFilter('WATCH'); setNeedsVerifyOnly(false); }}
              className={`px-3 py-1.5 rounded-xl text-xs font-semibold transition ${
                labelFilter === 'WATCH' && !needsVerifyOnly
                  ? 'bg-amber-500 text-slate-950 shadow-md shadow-amber-500/20'
                  : 'bg-surface-2 text-amber-400 hover:bg-surface-3 border border-amber-500/25'
              }`}
            >
              观察 WATCH ({stats.counts.WATCH})
            </button>
            <button
              type="button"
              onClick={() => setExplicitAirdropOnly((prev) => !prev)}
              className={`px-3 py-1.5 rounded-xl text-xs font-semibold transition ${
                explicitAirdropOnly
                  ? 'bg-indigo-500 text-white shadow-md shadow-indigo-500/20'
                  : 'bg-surface-2 text-indigo-300 hover:bg-surface-3 border border-indigo-500/25'
              }`}
              title="过滤具备官方明确提及空投、积分计划或强空投信号的项目"
            >
              🪂 明确空投信号 ({stats.explicitAirdrop})
            </button>
            <button
              type="button"
              onClick={() => setHasFundingOnly((prev) => !prev)}
              className={`px-3 py-1.5 rounded-xl text-xs font-semibold transition ${
                hasFundingOnly
                  ? 'bg-cyan-400 text-slate-950 shadow-md shadow-cyan-400/20'
                  : 'bg-surface-2 text-cyan-300 hover:bg-surface-3 border border-cyan-500/25'
              }`}
            >
              💰 大额融资
            </button>
            <button
              type="button"
              onClick={() => setZeroCostOnly((prev) => !prev)}
              className={`px-3 py-1.5 rounded-xl text-xs font-semibold transition ${
                zeroCostOnly
                  ? 'bg-emerald-400 text-slate-950 shadow-md shadow-emerald-400/20'
                  : 'bg-surface-2 text-emerald-400 hover:bg-surface-3 border border-emerald-500/25'
              }`}
            >
              🛡️ 零资金成本
            </button>
            <button
              type="button"
              onClick={() => { setNeedsVerifyOnly((prev) => !prev); if (!needsVerifyOnly) setLabelFilter(''); }}
              className={`px-3 py-1.5 rounded-xl text-xs font-semibold transition ${
                needsVerifyOnly
                  ? 'bg-watch text-slate-950 shadow-md shadow-watch/20'
                  : 'bg-surface-2 text-watch hover:bg-surface-3 border border-watch/30'
              }`}
            >
              ⚠️ 待核验路径 ({stats.needsVerify})
            </button>
          </div>

          {/* Search, Sort & Export */}
          <div className="flex flex-wrap items-center gap-2">
            <div className="relative min-w-[200px] flex-1 sm:flex-initial">
              <input
                className="input !h-9 !py-1.5 !text-xs font-mono"
                placeholder="搜索项目名称…"
                value={keyword}
                onChange={(e) => setKeyword(e.target.value)}
              />
              {keyword && (
                <button
                  type="button"
                  onClick={() => setKeyword('')}
                  className="absolute right-2.5 top-2 text-xs text-ink-faint hover:text-ink"
                >
                  ✕
                </button>
              )}
            </div>

            <select
              className="select !h-9 !py-1.5 !text-xs font-mono"
              value={`${sortBy}-${sortOrder}`}
              onChange={(e) => {
                const [b, o] = e.target.value.split('-') as [SortBy, 'asc' | 'desc'];
                setSortBy(b);
                setSortOrder(o);
              }}
            >
              <option value="score-desc">评分 ↓ (最高优先)</option>
              <option value="score-asc">评分 ↑ (从低到高)</option>
              <option value="confidence-desc">置信度优先</option>
              <option value="name-asc">名称排序 A-Z</option>
            </select>

            <button
              type="button"
              className="btn-secondary !h-9 !py-1.5 !text-xs"
              disabled={filtered.length === 0}
              onClick={() => exportProjectsCsv(filtered)}
            >
              导出 CSV
            </button>

            <button
              type="button"
              className="btn-secondary !h-9 !py-1.5 !text-xs border-brand-500/30 text-brand-600 dark:text-brand-400 hover:bg-brand-500/10 flex items-center gap-1.5 font-semibold"
              onClick={() => setShowDigestModal(true)}
              title="生成每日/每周 Alpha 投研周报合辑"
            >
              <span>📰</span>
              <span>Alpha 投研周报</span>
            </button>

            {/* View Mode Toggle */}
            <div className="seg !h-9">
              {(['grid', 'table'] as const).map((v) => (
                <button
                  key={v}
                  type="button"
                  onClick={() => setView(v)}
                  aria-pressed={view === v}
                  className={`seg-item !py-1 !text-xs ${view === v ? 'active' : ''}`}
                >
                  {v === 'grid' ? '卡片' : '表格'}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Row 2: Secondary refinement filters */}
        <div className="flex flex-wrap items-center justify-between gap-3 pt-2.5 border-t border-line/60 text-xs">
          <div className="flex flex-wrap items-center gap-3 text-ink-muted">
            <select
              className="select !h-8 !py-1 !text-xs !w-auto"
              value={sectorFilter}
              onChange={(e) => setSectorFilter(e.target.value)}
            >
              <option value="">全部赛道</option>
              {sectors.map((s) => (
                <option key={s.name} value={s.name}>
                  {s.name} ({s.count})
                </option>
              ))}
            </select>

            <select
              className="select !h-8 !py-1 !text-xs !w-auto"
              value={stageFilter}
              onChange={(e) => setStageFilter(e.target.value)}
            >
              <option value="">全部阶段</option>
              {stages.map((s) => (
                <option key={s.name} value={s.name}>
                  {stageZh(s.name)} ({s.count})
                </option>
              ))}
            </select>

            <div className="flex items-center gap-1.5">
              <span className="text-ink-faint">最低分:</span>
              <input
                className="select !h-8 !py-1 !text-xs w-16 font-mono text-center"
                type="number"
                min="0"
                max="100"
                placeholder="≥0"
                value={minScore}
                onChange={(e) => setMinScore(e.target.value)}
                aria-label="最低分"
              />
            </div>

            <label className="flex cursor-pointer items-center gap-1.5 text-xs text-ink-muted hover:text-ink transition">
              <input
                type="checkbox"
                className="rounded border-line text-farm focus:ring-farm/30"
                checked={hideIgnore}
                onChange={(e) => setHideIgnore(e.target.checked)}
              />
              隐藏「忽略」
            </label>

            <label className="flex cursor-pointer items-center gap-1.5 text-xs text-ink-muted hover:text-ink transition">
              <input
                type="checkbox"
                className="rounded border-line text-ink-muted focus:ring-ink-muted/30"
                checked={showSkipped}
                onChange={(e) => setShowSkipped(e.target.checked)}
              />
              显示不参与
            </label>
          </div>

          <div className="flex items-center gap-3 text-ink-faint font-mono text-[11px] ml-auto">
            <span>显示 {filtered.length} / 共 {projects.length} 项</span>
            {truncated && <span className="text-watch">超过上限</span>}
          </div>
        </div>
      </div>

      {/* Content */}
      {loading ? <SkeletonGrid n={8} /> : filtered.length === 0 ? (
        <EmptyState
          title={projects.length === 0 ? (curatedOnly ? '精选模式下暂无强凭证项目' : '还没有项目数据') : '当前筛选无结果'}
          description={
            projects.length === 0
              ? curatedOnly
                ? '当前候选池已有大量实时监控项目，但尚未关联到 90 天内链上任务凭证。点击下方按钮即可查看全部实时项目。'
                : '点击「采集并评分」从 DefiLlama / GitHub 等源拉取并写入评分结果'
              : '尝试清空筛选，或关闭「隐藏忽略」'
          }
          action={
            projects.length === 0 ? (
              curatedOnly ? (
                <button type="button" className="btn-primary" onClick={() => setCuratedOnly(false)}>查看全部实时项目</button>
              ) : (
                <button type="button" className="btn-primary" onClick={runPipeline} disabled={running}>▶ 开始采集评分</button>
              )
            ) : (
              <button type="button" className="btn-secondary" onClick={() => { setLabelFilter(''); setSectorFilter(''); setStageFilter(''); setMinScore(''); setKeyword(''); setHideIgnore(false); setHasFundingOnly(false); setZeroCostOnly(false); setNeedsVerifyOnly(false); setExplicitAirdropOnly(false); }}>清除筛选</button>
            )
          }
        />
      ) : view === 'grid' ? (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 min-[1600px]:grid-cols-5 min-[1920px]:grid-cols-6">
          {filtered.map((p, i) => (
            <ProjectCard key={p.id} project={p} rank={i + 1} onUpdate={handleProjectUpdate} />
          ))}
        </div>
      ) : (
        <div className="dash-card overflow-hidden">
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

      {/* 宏观生态洞察与赛道分布：低频参考内容折叠后置 */}
      <div className="dash-card p-4 transition-all duration-200">
        <button
          type="button"
          onClick={() => setShowCharts((v) => !v)}
          className="w-full flex items-center justify-between text-left group cursor-pointer select-none"
          aria-expanded={showCharts}
        >
          <div className="flex items-center gap-2.5">
            <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-surface-2 border border-line text-sm text-farm">
              📊
            </span>
            <div>
              <div className="flex items-center gap-2">
                <h3 className="text-sm font-bold text-ink group-hover:text-farm transition-colors">
                  宏观生态分布与赛道洞察
                </h3>
                <span className="font-mono text-[10px] px-2 py-0.5 rounded-full bg-surface-2 text-ink-faint border border-line">
                  {showCharts ? '已展开' : '已折叠'}
                </span>
              </div>
              <p className="text-xs text-ink-muted mt-0.5">
                包含标签分布（FARM/WATCH/IGNORE 权重）与前 8 热门赛道项目占比
              </p>
            </div>
          </div>
          <div className="btn-secondary !py-1 !px-3 text-xs flex items-center gap-1.5 shrink-0 ml-3">
            <span>{showCharts ? '收起图表' : '展开图表分析'}</span>
            <span className={`transition-transform duration-200 ${showCharts ? 'rotate-180' : ''}`}>▼</span>
          </div>
        </button>

        {showCharts && (
          <div className="mt-4 pt-4 border-t border-line/60 grid grid-cols-1 gap-5 lg:grid-cols-12 animate-fade-in">
            <div className="p-4 rounded-xl bg-surface-2/40 border border-line/60 lg:col-span-6">
              <h4 className="mb-3 text-xs font-semibold text-ink uppercase tracking-wider flex items-center justify-between">
                <span>标签分布</span>
                <span className="text-[10px] text-ink-faint font-mono">点击标签快速筛选</span>
              </h4>
              <LabelDoughnut counts={stats.counts} />
              <div className="mt-4 flex flex-wrap justify-center gap-2.5">
                {LABEL_ORDER.map((l) => (
                  <button
                    key={l}
                    type="button"
                    onClick={() => setLabelFilter((cur) => (cur === l ? '' : l))}
                    className={`transition ${labelFilter === l ? 'scale-105 ring-2 ring-farm' : 'opacity-85 hover:opacity-100'}`}
                  >
                    <LabelBadge label={l} />
                    <span className="ml-1 text-xs text-ink-muted font-mono">{stats.counts[l]}</span>
                  </button>
                ))}
              </div>
            </div>
            <div className="p-4 rounded-xl bg-surface-2/40 border border-line/60 lg:col-span-6">
              <h4 className="mb-3 text-xs font-semibold text-ink uppercase tracking-wider">
                赛道分布（前 8）
              </h4>
              <SectorBars sectors={sectors} />
            </div>
          </div>
        )}
      </div>
    </div>
    <AlphaDigestModal isOpen={showDigestModal} onClose={() => setShowDigestModal(false)} />
    <DailyBriefingModal isOpen={showBriefingModal} onClose={() => setShowBriefingModal(false)} />
    </>
  );
}
