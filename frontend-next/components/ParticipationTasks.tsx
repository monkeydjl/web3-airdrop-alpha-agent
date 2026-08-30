'use client';

import { apiFetch } from '@/lib/api';
import { safeExternalUrl } from '@/lib/format';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Check } from 'lucide-react';

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

function loadDone(projectId: string): Record<string, boolean> {
  try {
    const raw = localStorage.getItem(STORAGE_PREFIX + projectId);
    return raw ? (JSON.parse(raw) as Record<string, boolean>) : {};
  } catch {
    return {};
  }
}

function clearDone(projectId: string) {
  try {
    localStorage.removeItem(STORAGE_PREFIX + projectId);
  } catch {
    /* 隐私模式等场景下 localStorage 不可用 —— 本来就没存成，无需处理 */
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
  // 本地模式（尚未「开始参与」）的勾选，仅在无 plan 时使用
  const [done, setDone] = useState<Record<string, boolean>>({});
  const [planBusy, setPlanBusy] = useState(false);
  const [filter, setFilter] = useState<string>('all');

  const load = useCallback(async () => {
    if (!projectId) return;
    setLoading(true);
    setError('');
    try {
      const res = await apiFetch<ParticipationData>(`/projects/${projectId}/participation-tasks`);
      setData(res);
      setDone(loadDone(projectId));
      const listed = await apiFetch<{ items: Plan[] }>('/participation');
      setPlan(listed.items.find((p) => p.project_id === projectId) ?? null);
    } catch (e: unknown) {
      // 参与流水加载失败不应拖垮建议清单的展示：plan 置 null 走本地模式
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

  const taskIsDone = (taskId: string) => {
    if (plan) {
      const st = serverStatusByRef[taskId]?.status;
      return st === 'done';
    }
    return !!done[taskId];
  };

  const toggle = (taskId: string) => {
    if (!plan) {
      setDone((prev) => {
        const next = { ...prev, [taskId]: !prev[taskId] };
        try {
          localStorage.setItem(STORAGE_PREFIX + projectId, JSON.stringify(next));
        } catch {
          /* 忽略：隐私模式下勾选只存活在本次会话内存里 */
        }
        return next;
      });
      return;
    }
    const serverTask = serverStatusByRef[taskId];
    if (!serverTask) return; // 建议清单与 seed 时的生成结果不一致：无服务端任务可更新
    const nextStatus = serverTask.status === 'done' ? 'todo' : 'done';
    // 乐观更新：状态机 done↔todo 双向合法，失败回滚
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
      setError('同步失败，已回滚勾选状态');
    });
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
      // 一次性迁移：把本机已勾选的任务同步到服务端，然后清掉本地键 ——
      // 勾选从此跟人走（token 身份），不再跟设备走
      const localDone = loadDone(projectId);
      const listed = await apiFetch<{ items: Plan[] }>('/participation');
      const created = listed.items.find((p) => p.project_id === projectId);
      if (created) {
        for (const t of created.tasks) {
          if (t.ref && localDone[t.ref]) {
            await apiFetch(`/participation/tasks/${t.id}`, {
              method: 'PATCH',
              body: JSON.stringify({ status: 'done' }),
            });
          }
        }
      }
      clearDone(projectId);
      setPlan(created ?? null);
      setDone({});
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

  const doneCount = tasks.filter((t) => taskIsDone(t.id)).length;
  const pct = tasks.length ? Math.round((doneCount / tasks.length) * 100) : 0;

  return (
    <section className="overflow-hidden border border-line bg-surface">
      <div className="border-b border-line px-4 py-3 sm:px-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold text-ink">可参与任务</h3>
            <p className="mt-0.5 text-xs text-ink-muted">
              官方活动 · 测试网 · 社群 · 主网；
              {plan ? '进度已同步到服务端' : '勾选进度暂存本机，「开始参与」后同步到服务端'}
            </p>
          </div>
          {plan ? (
            <span className="badge bg-farm-soft text-farm dark:bg-farm/15 dark:text-farm">
              参与中
            </span>
          ) : (
            <button
              type="button"
              className="btn-secondary !py-1.5 text-xs"
              onClick={startParticipating}
              disabled={planBusy || loading}
            >
              {planBusy ? '创建中…' : '开始参与'}
            </button>
          )}
        </div>
        {!plan && doneCount > 0 ? (
          <p className="mt-2 text-xs text-watch dark:text-watch">
            本机已有 {doneCount} 条勾选，「开始参与」时会自动迁移到服务端。
          </p>
        ) : null}
        {tasks.length > 0 ? (
          <div className="mt-3">
            <div className="mb-1 flex justify-between text-xs text-ink-muted">
              <span>
                进度 {doneCount}/{tasks.length}
                {data?.summary?.required_count
                  ? ` · 建议优先 ${data.summary.required_count} 项`
                  : ''}
              </span>
              <span className="tabular-nums">{pct}%</span>
            </div>
            <div className="h-0.5 overflow-hidden bg-line">
              <div className="h-full bg-farm transition-all" style={{ width: `${pct}%` }} />
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
            {data?.tips && data.tips.length > 0 ? (
              <ul className="mb-4 space-y-1 rounded-xl border border-line/80 bg-surface-2/50 px-3 py-2.5 text-xs text-ink-muted">
                {data.tips.map((t) => (
                  <li key={t}>· {t}</li>
                ))}
              </ul>
            ) : null}

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
            ) : (
              <div className="space-y-2">
                {filtered.map((t) => {
                  const isDone = taskIsDone(t.id);
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
                          onClick={() => toggle(t.id)}
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
                              <span className="badge bg-farm-soft text-farm dark:bg-farm-soft0/15 dark:text-farm">
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
            )}
          </>
        )}
      </div>
    </section>
  );
}
