'use client';

import { apiFetch } from '@/lib/api';
import { safeExternalUrl } from '@/lib/format';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Check, Plus, Trash2, Copy, CheckCheck, ExternalLink, Zap } from 'lucide-react';
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
  estimated_gas?: string | null;
  recommended_asset?: string | null;
  dapp_url?: string | null;
  execution_steps?: string[];
  anti_sybil_tip?: string | null;
  protocol_highlight?: string | null;
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
  note?: string | null;
  due_at?: string | null;
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

  // Sub-steps & note state
  const [subStepsDone, setSubStepsDone] = useState<Record<string, Record<string, Record<number, boolean>>>>({});
  const [notesByTask, setNotesByTask] = useState<Record<string, string>>({});
  const [editingNoteTaskId, setEditingNoteTaskId] = useState<string | null>(null);
  const [savingNoteId, setSavingNoteId] = useState<string | null>(null);

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

      // Load sub-steps from localStorage
      try {
        const rawSubSteps = localStorage.getItem('aa-substeps:' + projectId);
        if (rawSubSteps) setSubStepsDone(JSON.parse(rawSubSteps));
      } catch {}

      // Load notes (first from localStorage fallback, then server plan)
      const initialNotes: Record<string, string> = {};
      try {
        const rawNotes = localStorage.getItem('aa-notes:' + projectId);
        if (rawNotes) Object.assign(initialNotes, JSON.parse(rawNotes));
      } catch {}

      const listed = await apiFetch<{ items: Plan[] }>('/participation');
      const foundPlan = listed.items.find((p) => p.project_id === projectId) ?? null;
      setPlan(foundPlan);
      if (foundPlan) {
        for (const t of foundPlan.tasks) {
          if (t.ref && t.note) {
            initialNotes[t.ref] = t.note;
          }
        }
      }
      setNotesByTask(initialNotes);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '加载任务失败');
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    load();
  }, [load]);

  const toggleSubStep = (wallet: string, taskId: string, stepIdx: number) => {
    setSubStepsDone((prev) => {
      const walletSteps = prev[wallet] || {};
      const taskSteps = walletSteps[taskId] || {};
      const nextDone = !taskSteps[stepIdx];
      const nextTaskSteps = { ...taskSteps, [stepIdx]: nextDone };
      const nextWalletSteps = { ...walletSteps, [taskId]: nextTaskSteps };
      const updated = { ...prev, [wallet]: nextWalletSteps };
      try {
        localStorage.setItem('aa-substeps:' + projectId, JSON.stringify(updated));
      } catch {}
      return updated;
    });
  };

  const saveTaskNote = async (taskId: string, noteContent: string) => {
    setSavingNoteId(taskId);
    const updated = { ...notesByTask, [taskId]: noteContent };
    setNotesByTask(updated);
    try {
      localStorage.setItem('aa-notes:' + projectId, JSON.stringify(updated));
    } catch {}

    const serverTask = serverStatusByRef[taskId];
    if (serverTask) {
      try {
        await apiFetch(`/participation/tasks/${serverTask.id}`, {
          method: 'PATCH',
          body: JSON.stringify({ note: noteContent }),
        });
      } catch (e) {
        console.error('Failed to sync note to server', e);
      }
    }
    setSavingNoteId(null);
    setEditingNoteTaskId(null);
  };

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

  const [autoChecking, setAutoChecking] = useState(false);
  const [autoCheckMsg, setAutoCheckMsg] = useState<{ text: string; isSuccess: boolean } | null>(null);

  const handleAutoCheckOnchain = async () => {
    setAutoChecking(true);
    setAutoCheckMsg(null);
    try {
      if (!plan) {
        await startParticipating();
      }
      const res = await apiFetch<{
        matched: boolean;
        target_chain: string;
        wallet_address?: string;
        transaction_count: number;
        balance_eth: number;
        message: string;
        updated_task_ids: number[];
      }>(`/participation/tasks/auto-check?project_id=${projectId}&auto_commit=true`, {
        method: 'POST',
      });
      if (res.matched) {
        setAutoCheckMsg({
          text: `⚡ 链上已核销：在 ${res.target_chain} 探测到钱包 ${res.wallet_address?.slice(0, 6)}...${res.wallet_address?.slice(-4)} 产生交互 (Nonce=${res.transaction_count}, 余额=${res.balance_eth} ETH)，已自动为您完成任务打卡！`,
          isSuccess: true,
        });
        const updatedPlans = await apiFetch<Plan[]>(`/participation?project_id=${projectId}`);
        const cur = updatedPlans.find((p) => p.project_id === projectId && p.status === 'active');
        if (cur) setPlan(cur);
      } else {
        setAutoCheckMsg({
          text: res.message || `在 ${res.target_chain} 暂未检测到登记钱包的链上 Nonce 或余额。`,
          isSuccess: false,
        });
      }
    } catch (e: unknown) {
      setAutoCheckMsg({
        text: e instanceof Error ? e.message : '自动核销检测失败',
        isSuccess: false,
      });
    } finally {
      setAutoChecking(false);
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
            <button
              type="button"
              className="btn-secondary !py-1 text-xs text-amber-600 dark:text-amber-400 border-amber-500/30 hover:bg-amber-500/10 flex items-center gap-1"
              onClick={handleAutoCheckOnchain}
              disabled={autoChecking || loading}
              title="通过公共 RPC 探测观察钱包链上交互 Nonce 并自动打卡"
            >
              <Zap className={`h-3.5 w-3.5 ${autoChecking ? 'animate-spin' : ''}`} />
              {autoChecking ? '链上核验中…' : '⚡ 链上自动核销'}
            </button>
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

        {autoCheckMsg && (
          <div
            className={`mt-3 rounded-lg border p-2.5 text-xs flex items-center justify-between gap-2 ${
              autoCheckMsg.isSuccess
                ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-400'
                : 'border-amber-500/30 bg-amber-500/10 text-amber-300'
            }`}
          >
            <span>{autoCheckMsg.text}</span>
            <button
              type="button"
              onClick={() => setAutoCheckMsg(null)}
              className="text-ink-muted hover:text-ink text-[11px] shrink-0"
            >
              ✕
            </button>
          </div>
        )}

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
                            {t.protocol_highlight ? (
                              <span className="badge bg-purple-500/10 text-purple-700 dark:text-purple-300 font-semibold">
                                ✨ {t.protocol_highlight}
                              </span>
                            ) : null}
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

                          {/* Quick indicators: Gas, Asset, dApp Entry */}
                          <div className="mt-1.5 flex flex-wrap items-center gap-2">
                            {t.estimated_gas ? (
                              <span className="inline-flex items-center gap-1 rounded bg-amber-500/10 px-2 py-0.5 text-[11px] font-medium text-amber-800 dark:text-amber-300">
                                ⛽ 预估 Gas: {t.estimated_gas}
                              </span>
                            ) : null}
                            {t.recommended_asset ? (
                              <span className="inline-flex items-center gap-1 rounded bg-blue-500/10 px-2 py-0.5 text-[11px] font-medium text-blue-800 dark:text-blue-300">
                                🎯 推荐资产: {t.recommended_asset}
                              </span>
                            ) : null}
                            {safeExternalUrl(t.dapp_url || t.link) ? (
                              <a
                                href={safeExternalUrl(t.dapp_url || t.link) as string}
                                target="_blank"
                                rel="noreferrer"
                                className="inline-flex items-center gap-1 rounded bg-farm/10 px-2 py-0.5 text-[11px] font-semibold text-farm hover:bg-farm/20 transition"
                              >
                                🔗 官方安全入口
                                <ExternalLink className="h-3 w-3" />
                              </a>
                            ) : null}
                          </div>

                          <p className="mt-1.5 text-xs leading-relaxed text-ink-muted">{t.description}</p>
                          <p className="mt-1 text-xs text-ink-faint">为什么：{t.why}</p>
                          {t.action_hint ? (
                            <p className="mt-0.5 text-xs text-farm dark:text-farm">
                              做法：{t.action_hint}
                            </p>
                          ) : null}

                          {/* Execution Sub-Steps Checklist */}
                          {t.execution_steps && t.execution_steps.length > 0 ? (
                            <div className="mt-2.5 rounded-lg border border-line/70 bg-surface-2/40 p-2.5">
                              <div className="flex items-center justify-between text-[11px] font-medium text-ink-muted mb-1.5">
                                <span className="font-semibold text-ink">📋 分步执行核对清单（可逐项打勾完成）：</span>
                                <span className="font-mono text-[10px] text-brand-600 dark:text-brand-400">
                                  {t.execution_steps.filter((_, idx) => subStepsDone[activeWallet]?.[t.id]?.[idx]).length} / {t.execution_steps.length} 完成
                                </span>
                              </div>
                              <div className="space-y-1">
                                {t.execution_steps.map((step, sIdx) => {
                                  const stepDone = !!subStepsDone[activeWallet]?.[t.id]?.[sIdx];
                                  return (
                                    <div
                                      key={sIdx}
                                      onClick={() => toggleSubStep(activeWallet, t.id, sIdx)}
                                      className={`flex items-start gap-2 rounded px-2 py-1 cursor-pointer text-xs transition ${
                                        stepDone
                                          ? 'bg-farm-soft/30 text-ink-muted line-through'
                                          : 'hover:bg-surface text-ink'
                                      }`}
                                    >
                                      <input
                                        type="checkbox"
                                        checked={stepDone}
                                        onChange={() => {}}
                                        className="mt-0.5 h-3.5 w-3.5 rounded border-line text-farm focus:ring-farm"
                                      />
                                      <span className="leading-snug">{step}</span>
                                    </div>
                                  );
                                })}
                              </div>
                            </div>
                          ) : null}

                          {/* Anti-Sybil Tip Card */}
                          {t.anti_sybil_tip ? (
                            <div className="mt-2 flex items-start gap-2 rounded-lg border border-amber-500/25 bg-amber-500/5 px-2.5 py-1.5 text-[11px] text-amber-800 dark:text-amber-300">
                              <span className="text-sm shrink-0">🛡️</span>
                              <p className="leading-relaxed">
                                <strong>防女巫要诀：</strong>{t.anti_sybil_tip}
                              </p>
                            </div>
                          ) : null}

                          {/* Interaction Logging / TxHash Memo */}
                          <div className="mt-2.5 pt-2 border-t border-line/40 flex flex-wrap items-center justify-between gap-2 text-xs">
                            <div className="flex items-center gap-2 flex-1 min-w-[200px]">
                              <span className="text-[11px] text-ink-faint shrink-0">✍️ 交互打卡:</span>
                              {editingNoteTaskId === t.id ? (
                                <div className="flex items-center gap-1.5 flex-1">
                                  <input
                                    type="text"
                                    defaultValue={notesByTask[t.id] || ''}
                                    id={`note-input-${t.id}`}
                                    placeholder="例: 质押 0.1 wstETH, tx: 0xabc... 消耗 Gas 0.002"
                                    className="flex-1 rounded border border-line bg-surface px-2 py-0.5 text-xs text-ink focus:border-brand-500 focus:outline-hidden"
                                    onKeyDown={(e) => {
                                      if (e.key === 'Enter') {
                                        const val = (e.currentTarget as HTMLInputElement).value;
                                        saveTaskNote(t.id, val);
                                      }
                                    }}
                                  />
                                  <button
                                    type="button"
                                    disabled={savingNoteId === t.id}
                                    onClick={() => {
                                      const el = document.getElementById(`note-input-${t.id}`) as HTMLInputElement;
                                      saveTaskNote(t.id, el?.value || '');
                                    }}
                                    className="rounded bg-farm px-2 py-0.5 text-[11px] text-white font-medium hover:bg-farm/90 transition"
                                  >
                                    {savingNoteId === t.id ? '保存中…' : '保存'}
                                  </button>
                                  <button
                                    type="button"
                                    onClick={() => setEditingNoteTaskId(null)}
                                    className="text-[11px] text-ink-faint hover:text-ink"
                                  >
                                    取消
                                  </button>
                                </div>
                              ) : (
                                <div className="flex items-center gap-2 flex-wrap">
                                  <span className={`text-[11px] ${notesByTask[t.id] ? 'text-ink font-mono bg-surface-2 px-1.5 py-0.5 rounded border border-line/50' : 'text-ink-faint italic'}`}>
                                    {notesByTask[t.id] || '未填写打卡凭据'}
                                  </span>
                                  <button
                                    type="button"
                                    onClick={() => setEditingNoteTaskId(t.id)}
                                    className="text-[11px] text-brand-600 dark:text-brand-400 hover:underline cursor-pointer"
                                  >
                                    {notesByTask[t.id] ? '修改' : '打卡记录'}
                                  </button>
                                </div>
                              )}
                            </div>
                          </div>
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
