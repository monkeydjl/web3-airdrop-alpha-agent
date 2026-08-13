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

const STORAGE_PREFIX = 'aa-task-done:';

function loadDone(projectId: string): Record<string, boolean> {
  try {
    const raw = localStorage.getItem(STORAGE_PREFIX + projectId);
    return raw ? (JSON.parse(raw) as Record<string, boolean>) : {};
  } catch {
    return {};
  }
}

function saveDone(projectId: string, map: Record<string, boolean>) {
  localStorage.setItem(STORAGE_PREFIX + projectId, JSON.stringify(map));
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
  const [done, setDone] = useState<Record<string, boolean>>({});
  const [filter, setFilter] = useState<string>('all');

  const load = useCallback(async () => {
    if (!projectId) return;
    setLoading(true);
    setError('');
    try {
      const res = await apiFetch<ParticipationData>(
        `/projects/${projectId}/participation-tasks`,
      );
      setData(res);
      setDone(loadDone(projectId));
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '加载任务失败');
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    load();
  }, [load]);

  const toggle = (taskId: string) => {
    setDone((prev) => {
      const next = { ...prev, [taskId]: !prev[taskId] };
      saveDone(projectId, next);
      return next;
    });
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

  const doneCount = tasks.filter((t) => done[t.id]).length;
  const pct = tasks.length ? Math.round((doneCount / tasks.length) * 100) : 0;

  return (
    <section className="overflow-hidden border border-line bg-surface">
      <div className="border-b border-line px-4 py-3 sm:px-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold text-ink">可参与任务</h3>
            <p className="mt-0.5 text-xs text-ink-muted">
              官方活动 · 测试网 · 社群 · 主网；勾选进度保存在本机
            </p>
          </div>
          <button type="button" className="btn-secondary !py-1.5 text-xs" onClick={load} disabled={loading}>
            {loading ? '加载中…' : '刷新'}
          </button>
        </div>
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
                  const isDone = !!done[t.id];
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
