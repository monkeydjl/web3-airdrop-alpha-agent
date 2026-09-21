'use client';

import { apiFetch } from '@/lib/api';
import { safeExternalUrl } from '@/lib/format';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Check, Plus, Trash2, Copy, CheckCheck } from 'lucide-react';
import { FaucetTrackerPanel } from '@/components/FaucetTrackerPanel';

export interface ParticipationTask {
  id: string;
  category: string;
  category_zh: string;
  title: string;
  description: string;
  priority: number;
  effort: string;
  effort_zh: string;
  why: string;
  action_hint?: string | null;
  link?: string | null;
  required?: boolean;
}

interface ParticipationData {
  project_id?: string;
  project_name?: string;
  label?: string;
  summary?: {
    total?: number;
    required_count?: number;
    by_category?: Record<string, number>;
    focus?: string[];
  };
  tips?: string[];
  tasks?: ParticipationTask[];
}

/** 服务端参与流水（F2）：一个项目一条 plan，任务按 `ref`（建议 id）对回建议清单 */
interface PlanTask {
  id: number;
  plan_id: number;
  ref: string | null;
  title: string;
  status: 'todo' | 'doing' | 'done' | 'skipped' | string;
  completed_at?: string | null;
}

interface Plan {
  id: number;
  project_id: string;
  status: string;
  tasks: PlanTask[];
}

const STORAGE_PREFIX = 'aa-task-done:';
const MULTI_STORAGE_PREFIX = 'aa-multi-wallet-done:';
const WALLET_LIST_PREFIX = 'aa-wallets:';
const DEFAULT_WALLETS = ['钱包 #1 (主号)', '钱包 #2 (小号A)', '钱包 #3 (小号B)'];

function loadWallets(projectId: string): string[] {
  try {
    const raw = localStorage.getItem(WALLET_LIST_PREFIX + projectId);
    if (raw) {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed) && parsed.length > 0) return parsed;
    }
  } catch {
    /* fallback */
  }
  return DEFAULT_WALLETS;
}

function saveWallets(projectId: string, wallets: string[]) {
  try {
    localStorage.setItem(WALLET_LIST_PREFIX + projectId, JSON.stringify(wallets));
  } catch {
    /* ignore */
  }
}

function loadMultiDone(projectId: string, wallets: string[]): Record<string, Record<string, boolean>> {
  const result: Record<string, Record<string, boolean>> = {};
  for (const w of wallets) {
    result[w] = {};
  }

  try {
    const raw = localStorage.getItem(MULTI_STORAGE_PREFIX + projectId);
    if (raw) {
      const parsed = JSON.parse(raw) as Record<string, Record<string, boolean>>;
      for (const w of wallets) {
        if (parsed[w]) result[w] = parsed[w];
      }
      return result;
    }
  } catch {
    /* ignore */
  }

  // Backward compatibility: migrate legacy single-wallet done
  try {
    const legacyRaw = localStorage.getItem(STORAGE_PREFIX + projectId);
    if (legacyRaw) {
      const legacy = JSON.parse(legacyRaw) as Record<string, boolean>;
      if (wallets[0]) {
        result[wallets[0]] = legacy;
      }
    }
  } catch {
    /* ignore */
  }

  return result;
}

function saveMultiDone(projectId: string, multiDone: Record<string, Record<string, boolean>>) {
  try {
    localStorage.setItem(MULTI_STORAGE_PREFIX + projectId, JSON.stringify(multiDone));
  } catch {
    /* ignore */
  }
}

const effortColor: Record<string, string> = {
  low: 'bg-farm-soft text-farm dark:bg-farm/15 dark:text-farm',
  medium: 'bg-watch-soft text-watch dark:bg-watch/15 dark:text-watch',
  high: 'bg-red-50 text-red-700 dark:bg-red-500/15 dark:text-red-300',
};

export function ParticipationTasks({ projectId }: { projectId: string }) {
  const [data, setData] = useState<ParticipationData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [plan, setPlan] = useState<Plan | null>(null);
  const [planBusy, setPlanBusy] = useState(false);
  const [filter, setFilter] = useState<string>('all');
  const [showFaucetHub, setShowFaucetHub] = useState(false);

  // Multi-wallet state
  const [wallets, setWallets] = useState<string[]>(DEFAULT_WALLETS);
  const [activeWallet, setActiveWallet] = useState<string>(DEFAULT_WALLETS[0]);
  const [multiDone, setMultiDone] = useState<Record<string, Record<string, boolean>>>({});
  const [viewMode, setViewMode] = useState<'checklist' | 'matrix'>('checklist');
  const [copiedSummary, setCopiedSummary] = useState(false);

  const load = useCallback(async () => {
    if (!projectId) return;
    setLoading(true);
    setError('');
    try {
      const res = await apiFetch<ParticipationData>(`/projects/${projectId}/participation-tasks`);
      setData(res);

      const loadedWallets = loadWallets(projectId);
      setWallets(loadedWallets);
      setActiveWallet(loadedWallets[0] || '钱包 #1 (主号)');
      setMultiDone(loadMultiDone(projectId, loadedWallets));

      const listed = await apiFetch<{ items: Plan[] }>('/participation');
      setPlan(listed.items.find((p) => p.project_id === projectId) ?? null);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '加载任务失败');
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    load();
  }, [load]);

  const serverStatusByRef = useMemo(() => {
    const map: Record<string, PlanTask> = {};
    for (const t of plan?.tasks ?? []) {
      if (t.ref) map[t.ref] = t;
    }
    return map;
  }, [plan]);

  const isWalletTaskDone = (wallet: string, taskId: string) => {
    // If on main wallet and server plan is active, check server status
    if (plan && wallet === wallets[0]) {
      const st = serverStatusByRef[taskId]?.status;
      return st === 'done';
    }
    return !!multiDone[wallet]?.[taskId];
  };

  const toggleWalletTask = (wallet: string, taskId: string) => {
    const isMainAndHasPlan = plan && wallet === wallets[0];

    // Optimistic local update
    const current = isWalletTaskDone(wallet, taskId);
    const updated = {
      ...multiDone,
      [wallet]: {
        ...(multiDone[wallet] || {}),
        [taskId]: !current,
      },
    };
    setMultiDone(updated);
    saveMultiDone(projectId, updated);

    // If main wallet and server plan exists, sync to server
    if (isMainAndHasPlan) {
      const serverTask = serverStatusByRef[taskId];
      if (!serverTask) return;
      const nextStatus = !current ? 'done' : 'todo';
      setPlan((prev) =>
        prev
          ? {
              ...prev,
              tasks: prev.tasks.map((t) =>
                t.id === serverTask.id
                  ? {
                      ...t,
                      status: nextStatus,
                      completed_at: nextStatus === 'done' ? new Date().toISOString() : null,
                    }
                  : t,
              ),
            }
          : prev,
      );
      apiFetch<{ task_id: number }>(`/participation/tasks/${serverTask.id}`, {
        method: 'PATCH',
        body: JSON.stringify({ status: nextStatus }),
      }).catch(() => {
        setPlan((prev) =>
          prev
            ? {
                ...prev,
                tasks: prev.tasks.map((t) =>
                  t.id === serverTask.id ? { ...t, status: serverTask.status } : t,
                ),
              }
            : prev,
        );
      });
    }
  };

  const addWallet = () => {
    const nextIdx = wallets.length + 1;
    const newName = `钱包 #${nextIdx}`;
    const nextWallets = [...wallets, newName];
    setWallets(nextWallets);
    saveWallets(projectId, nextWallets);
    setActiveWallet(newName);
    const updated = { ...multiDone, [newName]: {} };
    setMultiDone(updated);
    saveMultiDone(projectId, updated);
  };

  const removeWallet = (walletToRemove: string) => {
    if (wallets.length <= 1) return;
    const nextWallets = wallets.filter((w) => w !== walletToRemove);
    setWallets(nextWallets);
    saveWallets(projectId, nextWallets);
    if (activeWallet === walletToRemove) {
      setActiveWallet(nextWallets[0]);
    }
    const updated = { ...multiDone };
    delete updated[walletToRemove];
    setMultiDone(updated);
    saveMultiDone(projectId, updated);
  };

  const markAllDoneForActiveWallet = () => {
    const tasks = data?.tasks || [];
    const updatedWalletDone: Record<string, boolean> = {};
    for (const t of tasks) {
      updatedWalletDone[t.id] = true;
    }
    const updated = {
      ...multiDone,
      [activeWallet]: updatedWalletDone,
    };
    setMultiDone(updated);
    saveMultiDone(projectId, updated);
  };

  const resetActiveWallet = () => {
    const updated = {
      ...multiDone,
      [activeWallet]: {},
    };
    setMultiDone(updated);
    saveMultiDone(projectId, updated);
  };

  const copyProgressReport = () => {
    const tasks = data?.tasks || [];
    const lines = [
      `📊 [${data?.project_name || projectId}] 多钱包交互进度汇报`,
      `项目 ID: ${projectId}`,
      `更新时间: ${new Date().toLocaleString()}`,
      '----------------------------------------',
    ];
    for (const w of wallets) {
      const done = tasks.filter((t) => isWalletTaskDone(w, t.id)).length;
      const pct = tasks.length ? Math.round((done / tasks.length) * 100) : 0;
      lines.push(`• ${w}: 完成 ${done}/${tasks.length} (${pct}%)`);
    }
    navigator.clipboard.writeText(lines.join('\n'));
    setCopiedSummary(true);
    setTimeout(() => setCopiedSummary(false), 2000);
  };

  const startParticipating = async () => {
    if (!projectId) return;
    setPlanBusy(true);
    setError('');
    try {
      await apiFetch<{ plan_id: number }>(`/projects/${projectId}/participation`, {
        method: 'POST',
        body: JSON.stringify({ seed_from_generated: true }),
      });
      const listed = await apiFetch<{ items: Plan[] }>('/participation');
      const created = listed.items.find((p) => p.project_id === projectId);
      if (created) {
        const mainDone = multiDone[wallets[0]] || {};
        for (const t of created.tasks) {
          if (t.ref && mainDone[t.ref]) {
            await apiFetch(`/participation/tasks/${t.id}`, {
              method: 'PATCH',
              body: JSON.stringify({ status: 'done' }),
            });
          }
        }
      }
      setPlan(created ?? null);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '开始参与失败');
    } finally {
      setPlanBusy(false);
    }
  };

  const tasks = data?.tasks || [];
  const categories = useMemo(() => {
    const set = new Set(tasks.map((t) => t.category_zh));
    return ['全部', ...Array.from(set)];
  }, [tasks]);

  const filtered = useMemo(() => {
    if (filter === 'all' || filter === '全部') return tasks;
    return tasks.filter((t) => t.category_zh === filter);
  }, [tasks, filter]);

  const currentWalletDoneCount = tasks.filter((t) => isWalletTaskDone(activeWallet, t.id)).length;
  const currentPct = tasks.length ? Math.round((currentWalletDoneCount / tasks.length) * 100) : 0;

  // Aggregate multi-wallet stats
  const totalSlots = tasks.length * wallets.length;
  const totalDoneSlots = wallets.reduce(
    (acc, w) => acc + tasks.filter((t) => isWalletTaskDone(w, t.id)).length,
    0,
  );
  const overallPct = totalSlots ? Math.round((totalDoneSlots / totalSlots) * 100) : 0;

  return (
    <section className="overflow-hidden border border-line bg-surface">
      <div className="border-b border-line px-4 py-3 sm:px-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-sm font-semibold text-ink">可参与任务清单</h3>
              <span className="rounded bg-brand-500/10 px-1.5 py-0.5 text-[10px] font-medium text-brand-600 dark:text-brand-400">
                多钱包跟进模式
              </span>
            </div>
            <p className="mt-0.5 text-xs text-ink-muted">
              官方活动 · 测试网 · 社群 · 主网；支持多钱包独立标记、矩阵总览与防女巫进度隔离。
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <div className="flex rounded-lg bg-surface-2 p-0.5 text-xs">
              <button
                type="button"
                onClick={() => setViewMode('checklist')}
                className={`rounded px-2.5 py-1 transition ${
                  viewMode === 'checklist' ? 'bg-surface text-ink font-semibold shadow-xs' : 'text-ink-muted'
                }`}
              >
                📋 单钱包清单
              </button>
              <button
                type="button"
                onClick={() => setViewMode('matrix')}
                className={`rounded px-2.5 py-1 transition ${
                  viewMode === 'matrix' ? 'bg-surface text-ink font-semibold shadow-xs' : 'text-ink-muted'
                }`}
              >
                📊 多钱包矩阵
              </button>
            </div>
            {plan ? (
              <span className="badge bg-farm-soft text-farm dark:bg-farm/15 dark:text-farm">
                服务端同步中
              </span>
            ) : (
              <button
                type="button"
                className="btn-secondary !py-1 text-xs"
                onClick={startParticipating}
                disabled={planBusy || loading}
              >
                {planBusy ? '同步中…' : '同步主号至服务端'}
              </button>
            )}
          </div>
        </div>

        {/* Multi-Wallet Tabs Bar */}
        <div className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-line/60 pt-3">
          <div className="flex flex-wrap items-center gap-1.5">
            {wallets.map((w) => {
              const isSelected = activeWallet === w;
              const wDone = tasks.filter((t) => isWalletTaskDone(w, t.id)).length;
              return (
                <div key={w} className="flex items-center">
                  <button
                    type="button"
                    onClick={() => setActiveWallet(w)}
                    className={`flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-xs font-medium transition ${
                      isSelected
                        ? 'border-brand-500 bg-brand-50 text-brand-700 dark:border-brand-500/40 dark:bg-brand-500/10 dark:text-brand-300'
                        : 'border-line bg-surface text-ink-muted hover:border-ink/20 hover:text-ink'
                    }`}
                  >
                    <span>{w}</span>
                    <span className="rounded bg-surface-2 px-1 text-[10px] tabular-nums font-mono text-ink-faint">
                      {wDone}/{tasks.length}
                    </span>
                  </button>
                  {wallets.length > 1 ? (
                    <button
                      type="button"
                      onClick={() => removeWallet(w)}
                      className="ml-0.5 p-1 text-ink-faint hover:text-red-500 transition-colors"
                      title="移除该钱包"
                    >
                      <Trash2 className="h-3 w-3" />
                    </button>
                  ) : null}
                </div>
              );
            })}
            <button
              type="button"
              onClick={addWallet}
              className="flex items-center gap-1 rounded-lg border border-dashed border-line px-2 py-1 text-xs text-ink-muted hover:border-brand-500/60 hover:text-brand-600 transition"
              title="添加新钱包地址/标签"
            >
              <Plus className="h-3 w-3" />
              <span>加钱包</span>
            </button>
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={markAllDoneForActiveWallet}
              className="text-xs text-ink-muted hover:text-farm transition flex items-center gap-1"
            >
              <CheckCheck className="h-3.5 w-3.5 text-farm" />
              <span>本钱包全清</span>
            </button>
            <button
              type="button"
              onClick={resetActiveWallet}
              className="text-xs text-ink-faint hover:text-red-500 transition"
            >
              重置
            </button>
            <button
              type="button"
              onClick={copyProgressReport}
              className="rounded bg-surface-2 px-2 py-1 text-xs text-ink-muted hover:text-ink transition flex items-center gap-1"
            >
              <Copy className="h-3 w-3" />
              <span>{copiedSummary ? '已复制汇报' : '复制进度'}</span>
            </button>
          </div>
        </div>

        {/* Progress Bar */}
        {tasks.length > 0 ? (
          <div className="mt-3 grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <div className="mb-1 flex justify-between text-xs text-ink-muted">
                <span>当前钱包 ({activeWallet}) 进度: {currentWalletDoneCount}/{tasks.length}</span>
                <span className="tabular-nums font-semibold">{currentPct}%</span>
              </div>
              <div className="h-1.5 overflow-hidden rounded-full bg-line">
                <div className="h-full bg-farm transition-all" style={{ width: `${currentPct}%` }} />
              </div>
            </div>
            <div>
              <div className="mb-1 flex justify-between text-xs text-ink-muted">
                <span>全钱包矩阵总进度: {totalDoneSlots}/{totalSlots}</span>
                <span className="tabular-nums font-semibold text-brand-600 dark:text-brand-400">{overallPct}%</span>
              </div>
              <div className="h-1.5 overflow-hidden rounded-full bg-line">
                <div className="h-full bg-brand-500 transition-all" style={{ width: `${overallPct}%` }} />
              </div>
            </div>
          </div>
        ) : null}
      </div>

      <div className="px-4 py-3 sm:px-5">
        {loading && !data ? (
          <div className="space-y-2">
            <div className="skeleton h-16" />
            <div className="skeleton h-16" />
            <div className="skeleton h-16" />
          </div>
        ) : error ? (
          <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:bg-red-500/10 dark:text-red-300">
            {error}
            <button type="button" className="ml-3 underline" onClick={load}>
              重试
            </button>
          </div>
        ) : (
          <>
            {tasks.some((t) => t.category === 'testnet') ? (
              <div className="mb-4 space-y-2">
                <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-3.5 py-2.5 text-xs text-emerald-800 dark:text-emerald-300 flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-start gap-2 max-w-xl">
                    <span className="text-base">🛡️</span>
                    <p className="leading-relaxed">
                      <strong>零资金成本提示：</strong>本项目支持免费测试网交互。请优先通过水龙头 (Faucet) 领取测试币，全程无需投入真实本金即可完成全套核心交互。
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => setShowFaucetHub((prev) => !prev)}
                    className="shrink-0 rounded-lg bg-emerald-500/20 px-2.5 py-1 text-xs font-semibold text-emerald-700 dark:text-emerald-300 hover:bg-emerald-500/30 transition-colors"
                  >
                    {showFaucetHub ? '收起水龙头' : '🚰 水龙头中心'}
                  </button>
                </div>
                {showFaucetHub ? (
                  <div className="mt-2">
                    <FaucetTrackerPanel />
                  </div>
                ) : null}
              </div>
            ) : null}

            {data?.tips && data.tips.length > 0 ? (
              <ul className="mb-4 space-y-1 rounded-xl border border-line/80 bg-surface-2/50 px-3 py-2.5 text-xs text-ink-muted">
                {data.tips.map((t) => (
                  <li key={t}>· {t}</li>
                ))}
              </ul>
            ) : null}

            {/* Category Filter */}
            <div className="mb-3 flex flex-wrap gap-1.5">
              {categories.map((c) => {
                const key = c === '全部' ? 'all' : c;
                const active = filter === key || (filter === 'all' && c === '全部');
                return (
                  <button
                    key={c}
                    type="button"
                    onClick={() => setFilter(key)}
                    className={`rounded-lg px-2.5 py-1 text-xs font-medium transition ${
                      active
                        ? 'bg-farm text-white'
                        : 'bg-surface-2 text-ink-muted hover:text-ink'
                    }`}
                  >
                    {c}
                  </button>
                );
              })}
            </div>

            {filtered.length === 0 ? (
              <p className="py-8 text-center text-sm text-ink-faint">当前分类无任务</p>
            ) : viewMode === 'checklist' ? (
              /* Checklist View (Per-Wallet) */
              <div className="space-y-2">
                {filtered.map((t) => {
                  const isDone = isWalletTaskDone(activeWallet, t.id);
                  return (
                    <div
                      key={t.id}
                      className={`rounded-xl border px-3 py-3 transition ${
                        isDone
                          ? 'border-farm/30 bg-farm-soft/20 opacity-80 dark:bg-farm/5'
                          : 'border-line/80 bg-surface hover:border-brand-300/40'
                      }`}
                    >
                      <div className="flex gap-3">
                        <button
                          type="button"
                          onClick={() => toggleWalletTask(activeWallet, t.id)}
                          className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-md border text-xs ${
                            isDone
                              ? 'border-farm bg-farm text-white'
                              : 'border-line bg-surface-2 text-transparent'
                          }`}
                          aria-label={isDone ? '标为未完成' : '标为完成'}
                        >
                          {isDone ? <Check className="h-3 w-3" strokeWidth={3} /> : null}
                        </button>
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center gap-2">
                            <span
                              className={`text-sm font-semibold text-ink ${isDone ? 'line-through opacity-70' : ''}`}
                            >
                              {t.title}
                            </span>
                            {t.required ? (
                              <span className="badge bg-farm-soft text-farm dark:bg-farm/15 dark:text-farm">
                                建议优先
                              </span>
                            ) : null}
                            <span className="badge bg-surface-3 text-ink-muted">{t.category_zh}</span>
                            <span className={`badge ${effortColor[t.effort] || effortColor.medium}`}>
                              精力 {t.effort_zh}
                            </span>
                            <span className="text-[10px] text-ink-faint">P{t.priority}</span>
                          </div>
                          <p className="mt-1 text-xs leading-relaxed text-ink-muted">{t.description}</p>
                          <p className="mt-1 text-xs text-ink-faint">为什么：{t.why}</p>
                          {t.action_hint ? (
                            <p className="mt-0.5 text-xs text-farm dark:text-farm">
                              做法：{t.action_hint}
                            </p>
                          ) : null}
                          {safeExternalUrl(t.link) ? (
                            <a
                              href={safeExternalUrl(t.link) as string}
                              target="_blank"
                              rel="noreferrer"
                              className="mt-1 inline-block text-xs text-farm underline dark:text-farm"
                            >
                              打开相关链接
                            </a>
                          ) : null}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : (
              /* Matrix View (Multi-Wallet Comparison) */
              <div className="overflow-x-auto rounded-xl border border-line">
                <table className="w-full text-left text-xs">
                  <thead className="bg-surface-2 border-b border-line text-ink-muted font-medium">
                    <tr>
                      <th className="py-2.5 px-3">任务名称</th>
                      <th className="py-2.5 px-2">类型</th>
                      <th className="py-2.5 px-2">优先级</th>
                      {wallets.map((w) => (
                        <th key={w} className="py-2.5 px-3 text-center">
                          {w}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-line/60">
                    {filtered.map((t) => (
                      <tr key={t.id} className="hover:bg-surface-2/40 transition-colors">
                        <td className="py-2.5 px-3 max-w-xs truncate font-medium text-ink">
                          {t.title}
                          {t.required ? (
                            <span className="ml-1 text-[10px] text-farm">★优先</span>
                          ) : null}
                        </td>
                        <td className="py-2.5 px-2 text-ink-muted">{t.category_zh}</td>
                        <td className="py-2.5 px-2 font-mono text-ink-faint">P{t.priority}</td>
                        {wallets.map((w) => {
                          const isDone = isWalletTaskDone(w, t.id);
                          return (
                            <td key={w} className="py-2.5 px-3 text-center">
                              <button
                                type="button"
                                onClick={() => toggleWalletTask(w, t.id)}
                                className={`inline-flex h-5 w-5 items-center justify-center rounded border transition ${
                                  isDone
                                    ? 'border-farm bg-farm text-white'
                                    : 'border-line bg-surface-2 text-transparent hover:border-ink/40'
                                }`}
                              >
                                {isDone ? <Check className="h-3 w-3" strokeWidth={3} /> : null}
                              </button>
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
      </div>
    </section>
  );
}
