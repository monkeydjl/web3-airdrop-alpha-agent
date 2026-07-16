'use client';

import { EmptyState, SectionTitle, StatCard, Toast } from '@/components/ui';
import { apiFetch } from '@/lib/api';
import { sourceZh } from '@/lib/format';
import type { CollectionSource } from '@/lib/types';
import { useCallback, useEffect, useState } from 'react';

interface QuarantineItem {
  raw_id: string;
  source_id?: string;
  discovery_score?: number;
  quarantine_reason?: string;
  raw_data?: { name?: string; sector?: string };
}

export default function OpsPage() {
  const [sources, setSources] = useState<CollectionSource[]>([]);
  const [quarantine, setQuarantine] = useState<QuarantineItem[]>([]);
  const [qCount, setQCount] = useState(0);
  const [ixSummary, setIxSummary] = useState<{
    total?: number;
    total_cost_usd?: number;
    total_profit_usd?: number;
    net_usd?: number;
    total_hours?: number;
  } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState<string | null>(null);
  const [toast, setToast] = useState<{ message: string; type: 'success' | 'error' | 'info' } | null>(
    null,
  );

  const showToast = (message: string, type: 'success' | 'error' | 'info' = 'info') => {
    setToast({ message, type });
    setTimeout(() => setToast(null), 3500);
  };

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const [src, q, ix] = await Promise.all([
        apiFetch<{ sources: CollectionSource[] }>('/collections/sources'),
        apiFetch<{ count: number; items: QuarantineItem[] }>('/quarantine?limit=50').catch(() => ({
          count: 0,
          items: [] as QuarantineItem[],
        })),
        apiFetch<{
          total?: number;
          total_cost_usd?: number;
          total_profit_usd?: number;
          net_usd?: number;
          total_hours?: number;
        }>('/interactions/summary').catch(() => null),
      ]);
      setSources(src.sources || []);
      setQuarantine(q.items || []);
      setQCount(q.count || 0);
      setIxSummary(ix);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '加载失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const trigger = async (sourceId: string) => {
    setBusy(sourceId);
    try {
      const res = await apiFetch<{ status?: string; items_collected?: number }>(
        `/collections/${sourceId}/trigger`,
        { method: 'POST', body: '{}' },
      );
      showToast(`${sourceId} 完成 · ${res.items_collected ?? '—'} items`, 'success');
      load();
    } catch (err: unknown) {
      showToast(err instanceof Error ? err.message : `${sourceId} 失败`, 'error');
    } finally {
      setBusy(null);
    }
  };

  const release = async (rawId: string) => {
    setBusy(rawId);
    try {
      await apiFetch('/quarantine/release', {
        method: 'POST',
        body: JSON.stringify({ raw_id: rawId }),
      });
      showToast('已释放回分析队列', 'success');
      load();
    } catch (err: unknown) {
      showToast(err instanceof Error ? err.message : '释放失败', 'error');
    } finally {
      setBusy(null);
    }
  };

  const runScore = async () => {
    setBusy('run');
    try {
      const res = await apiFetch<{ scored_count?: number; top_score?: number }>('/run', {
        method: 'POST',
        body: '{}',
      });
      showToast(`评分完成 · ${res.scored_count ?? 0} · top ${res.top_score ?? '—'}`, 'success');
    } catch (err: unknown) {
      showToast(err instanceof Error ? err.message : '评分失败', 'error');
    } finally {
      setBusy(null);
    }
  };

  const enabled = sources.filter((s) => s.enabled).length;

  return (
    <div className="space-y-6 animate-fade-in">
      {toast ? <Toast message={toast.message} type={toast.type} /> : null}

      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-xs font-semibold tracking-[0.2em] text-brand-600 dark:text-brand-300">
            运维
          </p>
          <h1 className="page-title">运维台</h1>
          <p className="page-sub">采集源 · 隔离区 · 一键评分</p>
        </div>
        <div className="flex gap-2">
          <button type="button" className="btn-secondary" onClick={load} disabled={loading}>
            刷新
          </button>
          <button type="button" className="btn-primary" onClick={runScore} disabled={busy === 'run'}>
            {busy === 'run' ? '评分中…' : '▶ 仅运行评分'}
          </button>
        </div>
      </div>

      {error ? (
        <div className="card border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:bg-red-500/10 dark:text-red-300">
          {error}
        </div>
      ) : null}

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <StatCard label="数据源总数" value={sources.length} accent="brand" />
        <StatCard label="已启用" value={enabled} accent="farm" />
        <StatCard label="隔离中" value={qCount} accent="watch" />
        <StatCard label="交互记录" value={ixSummary?.total ?? 0} accent="brand" />
        <StatCard
          label="累计净收益"
          value={`$${(ixSummary?.net_usd ?? 0).toFixed(0)}`}
          accent={(ixSummary?.net_usd ?? 0) >= 0 ? 'farm' : 'ignore'}
        />
        <StatCard
          label="累计用时 h"
          value={(ixSummary?.total_hours ?? 0).toFixed(1)}
          accent="watch"
        />
      </div>

      <div className="card overflow-hidden">
        <div className="border-b border-line px-5 py-4">
          <SectionTitle title="数据源" />
          <p className="text-xs text-ink-faint">触发采集会写入原始项目池；达标项进入评分队列</p>
        </div>
        {loading ? (
          <div className="space-y-2 p-5">
            <div className="skeleton h-12" />
            <div className="skeleton h-12" />
          </div>
        ) : sources.length === 0 ? (
          <div className="p-5">
            <EmptyState title="无采集源" description="后端未注册采集器" />
          </div>
        ) : (
          <div className="divide-y divide-line">
            {sources.map((s) => (
              <div
                key={s.source_id}
                className="flex flex-col gap-3 px-5 py-4 sm:flex-row sm:items-center sm:justify-between"
              >
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-semibold text-ink">
                      {s.source_name || sourceZh(s.source_id)}
                    </span>
                    <span
                      className={`badge ${
                        s.enabled
                          ? 'bg-farm-soft text-farm-dark dark:bg-farm/15 dark:text-farm'
                          : 'bg-surface-3 text-ink-faint'
                      }`}
                    >
                      {s.enabled ? '已启用' : '已禁用'}
                    </span>
                    {s.sync_status ? (
                      <span className="badge bg-surface-3 text-ink-muted">
                        {s.sync_status === 'idle'
                          ? '空闲'
                          : s.sync_status === 'success'
                            ? '成功'
                            : s.sync_status === 'error'
                              ? '错误'
                              : s.sync_status}
                      </span>
                    ) : null}
                  </div>
                  <p className="mt-0.5 font-mono text-xs text-ink-faint">{s.source_id}</p>
                </div>
                <button
                  type="button"
                  className="btn-secondary shrink-0"
                  disabled={!s.enabled || busy === s.source_id}
                  onClick={() => trigger(s.source_id)}
                >
                  {busy === s.source_id ? '采集中…' : '触发采集'}
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="card overflow-hidden">
        <div className="border-b border-line px-5 py-4">
          <SectionTitle title="隔离区" />
          <p className="text-xs text-ink-faint">
            噪声 / 黑名单命中项会自动隔离，不进入分析队列。可释放回队列。
          </p>
        </div>
        {quarantine.length === 0 ? (
          <div className="p-8 text-center text-sm text-ink-faint">隔离区为空 · 共 {qCount} 条</div>
        ) : (
          <div className="divide-y divide-line">
            {quarantine.map((q) => (
              <div
                key={q.raw_id}
                className="flex flex-col gap-3 px-5 py-3 sm:flex-row sm:items-center sm:justify-between"
              >
                <div className="min-w-0">
                  <div className="truncate text-sm font-medium text-ink">
                    {q.raw_data?.name || q.raw_id}
                  </div>
                  <div className="text-xs text-ink-faint">
                    {sourceZh(q.source_id)} · 发现分 {q.discovery_score ?? '—'} ·{' '}
                    {q.quarantine_reason || '—'}
                  </div>
                </div>
                <button
                  type="button"
                  className="btn-secondary shrink-0"
                  disabled={busy === q.raw_id}
                  onClick={() => release(q.raw_id)}
                >
                  释放回队列
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
