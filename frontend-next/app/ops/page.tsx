'use client';

import { EmptyState, Switch, Toast } from '@/components/ui';
import { apiFetch, fetchHealth } from '@/lib/api';
import { relativeTime, sourceZh } from '@/lib/format';
import { normalizeCollectionSource } from '@/lib/types';
import type { CollectionSource, CollectionSourceApi, HealthData } from '@/lib/types';
import { useCallback, useEffect, useState } from 'react';

interface QuarantineItem {
  raw_id: string;
  source_id?: string;
  discovery_score?: number;
  quarantine_reason?: string;
  raw_data?: { name?: string; sector?: string };
}

function formatUsd(n?: number | null) {
  if (n == null || Number.isNaN(Number(n))) return '—';
  const v = Number(n);
  const sign = v < 0 ? '-' : '';
  const abs = Math.abs(v);
  if (abs >= 1e6) return `${sign}$${(abs / 1e6).toFixed(2)}M`;
  if (abs >= 1e3) return `${sign}$${(abs / 1e3).toFixed(1)}K`;
  return `${sign}$${abs.toFixed(0)}`;
}

function syncStatusZh(s?: string | null) {
  if (!s) return null;
  if (s === 'idle') return '空闲';
  if (s === 'success' || s === 'ok') return '成功';
  if (s === 'error') return '错误';
  if (s === 'disabled') return '已禁用';
  if (s === 'not_registered') return '未注册';
  return s;
}

function Kv({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3 border-b border-line py-2 text-[13px] last:border-b-0">
      <span className="text-ink-muted">{k}</span>
      <span className="font-mono text-[12.5px] font-medium tabular-nums text-ink">{v}</span>
    </div>
  );
}

function Metric({
  label,
  value,
  hint,
  tone,
}: {
  label: string;
  value: React.ReactNode;
  hint?: string;
  tone?: 'farm' | 'watch' | 'default';
}) {
  const valueCls =
    tone === 'farm'
      ? 'text-farm dark:text-farm'
      : tone === 'watch'
        ? 'text-watch dark:text-watch'
        : 'text-ink';
  return (
    <div className="ops-card px-4 py-3.5">
      <div className="font-mono text-[10px] font-semibold uppercase tracking-[0.06em] text-ink-muted">
        {label}
      </div>
      <div className={`mt-1.5 font-mono text-2xl font-semibold tabular-nums leading-none ${valueCls}`}>
        {value}
      </div>
      {hint ? <div className="mt-1.5 text-xs text-ink-faint">{hint}</div> : null}
    </div>
  );
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
  const [health, setHealth] = useState<HealthData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [partialError, setPartialError] = useState<string[]>([]);
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
    setPartialError([]);
    try {
      const [src, q, ix, h] = await Promise.all([
        apiFetch<{ sources: CollectionSourceApi[] }>('/collections/sources'),
        apiFetch<{ count: number; items: QuarantineItem[] }>('/quarantine?limit=50').catch(
          (err: unknown) => {
            setPartialError((prev) => [...prev, '隔离区加载失败']);
            void err;
            return { count: -1, items: [] as QuarantineItem[] };
          },
        ),
        apiFetch<{
          total?: number;
          total_cost_usd?: number;
          total_profit_usd?: number;
          net_usd?: number;
          total_hours?: number;
        }>('/interactions/summary').catch((err: unknown) => {
          setPartialError((prev) => [...prev, '成本汇总加载失败']);
          void err;
          return null;
        }),
        fetchHealth().catch(() => null),
      ]);
      setSources((src.sources || []).map(normalizeCollectionSource));
      setQuarantine(q.items || []);
      setQCount(typeof q.count === 'number' ? q.count : 0);
      setIxSummary(ix);
      if (h) setHealth(h as HealthData);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '加载失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const setSourceEnabled = async (sourceId: string, enabled: boolean) => {
    const prev = sources;
    setSources((list) =>
      list.map((s) =>
        s.source_id === sourceId
          ? { ...s, operatorEnabled: enabled, enabled: s.configReady && enabled }
          : s,
      ),
    );
    setBusy(`toggle-${sourceId}`);
    try {
      const res = await apiFetch<CollectionSourceApi>(`/collections/${sourceId}`, {
        method: 'PATCH',
        body: JSON.stringify({ enabled }),
      });
      const next = normalizeCollectionSource(res);
      setSources((list) => list.map((s) => (s.source_id === sourceId ? next : s)));
      const name = next.source_name || sourceZh(sourceId);
      showToast(
        `${name} ${next.operatorEnabled ? '已启用' : '已禁用'}${
          next.operatorEnabled && !next.configReady ? '（配置未就绪，仍不可采集）' : ''
        }`,
        next.operatorEnabled ? 'success' : 'info',
      );
    } catch (err: unknown) {
      setSources(prev);
      showToast(err instanceof Error ? err.message : '更新开关失败', 'error');
    } finally {
      setBusy(null);
    }
  };

  const trigger = async (sourceId: string) => {
    setBusy(sourceId);
    try {
      const res = await apiFetch<{ status?: string; items_collected?: number }>(
        `/collections/${sourceId}/trigger`,
        { method: 'POST', body: '{}' },
      );
      showToast(
        `${sourceZh(sourceId)} 完成 · ${res.items_collected ?? '—'} items`,
        'success',
      );
      load();
    } catch (err: unknown) {
      showToast(err instanceof Error ? err.message : `${sourceId} 失败`, 'error');
    } finally {
      setBusy(null);
    }
  };

  const triggerAllEnabled = async () => {
    const list = sources.filter((s) => s.enabled);
    if (!list.length) {
      showToast('没有可触发的采集源（需开关打开且配置就绪）', 'error');
      return;
    }
    setBusy('all');
    let ok = 0;
    let fail = 0;
    for (const s of list) {
      try {
        await apiFetch(`/collections/${s.source_id}/trigger`, { method: 'POST', body: '{}' });
        ok += 1;
      } catch {
        fail += 1;
      }
    }
    showToast(`已触发 ${ok} 个源${fail ? ` · 失败 ${fail}` : ''}`, fail ? 'error' : 'success');
    setBusy(null);
    load();
  };

  const release = async (rawId: string) => {
    setBusy(rawId);
    try {
      await apiFetch('/quarantine/release', {
        method: 'POST',
        body: JSON.stringify({ raw_id: rawId }),
      });
      showToast('已释放出隔离区', 'success');
      load();
    } catch (err: unknown) {
      showToast(err instanceof Error ? err.message : '释放失败', 'error');
    } finally {
      setBusy(null);
    }
  };

  const operatorOn = sources.filter((s) => s.operatorEnabled).length;
  const runnable = sources.filter((s) => s.enabled).length;
  const net = ixSummary?.net_usd ?? 0;

  return (
    <div className="animate-fade-in">
      {toast ? <Toast message={toast.message} type={toast.type} /> : null}

      {/* header — match design: title left, one primary CTA right */}
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="font-mono text-[11px] font-semibold uppercase tracking-[0.08em] text-farm dark:text-farm">
            运营
          </p>
          <h1 className="page-title">运维台</h1>
          <p className="page-sub max-w-[54ch]">
            每个采集源可单独启用 / 禁用；禁用后不参与定时与「触发全部」。开关写入{' '}
            <code className="font-mono text-[11px]">data_sources.enabled</code>。
          </p>
        </div>
        <button
          type="button"
          className="btn-primary"
          onClick={triggerAllEnabled}
          disabled={busy === 'all' || runnable === 0 || loading}
          title={runnable === 0 ? '请先启用至少一个可触发源' : `触发 ${runnable} 个源`}
        >
          {busy === 'all' ? '触发中…' : '触发全部已启用源'}
        </button>
      </div>

      {error ? (
        <div className="mt-4 border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300">
          {error}
          <button type="button" className="ml-3 underline" onClick={load}>
            重试
          </button>
        </div>
      ) : null}

      {partialError.length > 0 ? (
        <div className="mt-4 border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-300">
          部分数据加载失败：{partialError.join('、')}
        </div>
      ) : null}

      {/* 4 metrics like design */}
      <div className="mt-5 grid grid-cols-2 gap-2.5 lg:grid-cols-4">
        <Metric
          label="采集源"
          value={loading ? '—' : sources.length}
          hint={`启用 ${operatorOn}`}
        />
        <Metric
          label="健康"
          value={health == null ? '…' : health.ok ? 'OK' : 'DOWN'}
          hint={health?.db_backend || health?.status || '—'}
          tone={health?.ok ? 'farm' : 'default'}
        />
        <Metric
          label="隔离"
          value={qCount < 0 ? '—' : qCount}
          hint="待复核"
          tone="watch"
        />
        <Metric
          label="净成本"
          value={formatUsd(net)}
          hint={`${ixSummary?.total ?? 0} 条记录`}
          tone={net < 0 ? 'watch' : 'farm'}
        />
      </div>

      {/* main grid: sources | cost + health */}
      <div className="mt-4 grid grid-cols-1 gap-3 lg:grid-cols-[1.25fr_0.75fr]">
        {/* sources panel */}
        <section className="ops-card">
          <div className="flex items-baseline justify-between gap-3 border-b border-line px-4 py-3 sm:px-5">
            <h2 className="text-sm font-semibold text-ink">采集源</h2>
            <span className="font-mono text-[11px] text-ink-faint">
              {operatorOn} / {sources.length} 启用 · 可触发 {runnable}
            </span>
          </div>

          {loading ? (
            <div className="space-y-2 p-4">
              <div className="skeleton h-14" />
              <div className="skeleton h-14" />
              <div className="skeleton h-14" />
            </div>
          ) : sources.length === 0 ? (
            <div className="p-5">
              <EmptyState title="无采集源" description="后端未注册采集器" />
            </div>
          ) : (
            <div role="list">
              {sources.map((s) => {
                const name = s.source_name || sourceZh(s.source_id);
                const toggling = busy === `toggle-${s.source_id}`;
                const statusText = !s.operatorEnabled
                  ? '已禁用'
                  : !s.configReady
                    ? '配置未就绪'
                    : '运行中可触发';
                return (
                  <div
                    key={s.source_id}
                    role="listitem"
                    className={`grid grid-cols-1 items-center gap-3 border-b border-line px-4 py-3.5 last:border-b-0 sm:grid-cols-[minmax(0,1fr)_auto_auto_auto] sm:gap-4 sm:px-5 ${
                      !s.operatorEnabled ? 'opacity-75' : ''
                    }`}
                  >
                    <div className="min-w-0">
                      <div
                        className={`text-[13px] font-semibold leading-snug ${
                          s.operatorEnabled ? 'text-ink' : 'text-ink-muted'
                        }`}
                      >
                        {name}
                      </div>
                      <div className="mt-0.5 font-mono text-[11px] tracking-wide text-ink-faint">
                        {s.source_id}
                      </div>
                    </div>

                    <div className="text-left font-mono text-[11px] tracking-wide text-ink-muted sm:text-right">
                      <div>{statusText}</div>
                      <div className="mt-1 text-ink-faint">
                        {s.last_sync ? `上次 ${relativeTime(s.last_sync)}` : '从未同步'}
                        {s.sync_status && s.operatorEnabled
                          ? ` · ${syncStatusZh(s.sync_status)}`
                          : ''}
                      </div>
                    </div>

                    <Switch
                      checked={s.operatorEnabled}
                      disabled={toggling || busy === s.source_id}
                      label={`${name}${s.operatorEnabled ? '：已启用，点击禁用' : '：已禁用，点击启用'}`}
                      onChange={(next) => setSourceEnabled(s.source_id, next)}
                    />

                    <button
                      type="button"
                      className="btn-secondary !min-h-8 !px-3 !text-xs sm:justify-self-end"
                      disabled={!s.enabled || busy === s.source_id || toggling}
                      title={
                        !s.operatorEnabled
                          ? '请先打开开关'
                          : !s.configReady
                            ? '配置未就绪（缺少 key 或 env 关闭）'
                            : '立即采集'
                      }
                      onClick={() => trigger(s.source_id)}
                    >
                      {busy === s.source_id ? '…' : '触发'}
                    </button>
                  </div>
                );
              })}
            </div>
          )}
        </section>

        {/* right rail */}
        <div className="flex flex-col gap-3">
          <section className="ops-card p-4 sm:p-5">
            <h2 className="mb-3 text-sm font-semibold text-ink">交互成本汇总</h2>
            <Kv k="记录数" v={ixSummary?.total ?? 0} />
            <Kv k="总成本" v={formatUsd(ixSummary?.total_cost_usd)} />
            <Kv k="总收益" v={formatUsd(ixSummary?.total_profit_usd)} />
            <Kv k="净额" v={formatUsd(ixSummary?.net_usd)} />
            <Kv k="总工时" v={`${(ixSummary?.total_hours ?? 0).toFixed(1)} h`} />
          </section>

          <section className="ops-card p-4 sm:p-5">
            <div className="mb-3 flex items-center justify-between gap-2">
              <h2 className="text-sm font-semibold text-ink">健康检查</h2>
              <button
                type="button"
                className="btn-ghost !min-h-7 !px-2 !text-xs"
                onClick={load}
                disabled={loading}
              >
                刷新
              </button>
            </div>
            <Kv
              k="状态"
              v={
                <span
                  className={`badge ${
                    health?.ok
                      ? 'bg-farm-soft text-farm dark:bg-farm/15 dark:text-farm'
                      : 'bg-surface-3 text-ink-muted'
                  }`}
                >
                  {health?.status || (health?.ok ? 'healthy' : '—')}
                </span>
              }
            />
            <Kv k="版本" v={health?.version || '—'} />
            <Kv k="数据库" v={health?.db_backend || health?.db || '—'} />
            <Kv k="鉴权" v={health?.auth_required ? '需要' : '关闭'} />
            <Kv k="反馈" v={health?.feedback_enabled === false ? '关闭' : '开启'} />
          </section>
        </div>
      </div>

      {/* quarantine table full width */}
      <section className="mt-3 ops-card">
        <div className="flex items-baseline justify-between gap-3 border-b border-line px-4 py-3 sm:px-5">
          <h2 className="text-sm font-semibold text-ink">隔离区 Quarantine</h2>
          <span className="font-mono text-[11px] text-ink-faint">
            {qCount < 0 ? '加载失败' : `${qCount} 条`}
          </span>
        </div>

        {quarantine.length === 0 ? (
          <div className="px-5 py-10 text-center text-sm text-ink-faint">
            {qCount < 0 ? '隔离区数据加载失败' : '隔离区为空'}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px] text-left text-sm">
              <thead className="border-b border-line bg-surface-2/80">
                <tr className="font-mono text-[10px] font-semibold uppercase tracking-[0.06em] text-ink-muted">
                  <th className="px-4 py-2.5 font-semibold sm:px-5">名称</th>
                  <th className="px-3 py-2.5 font-semibold">源</th>
                  <th className="px-3 py-2.5 font-semibold">发现分</th>
                  <th className="px-3 py-2.5 font-semibold">原因</th>
                  <th className="px-4 py-2.5 font-semibold sm:px-5" />
                </tr>
              </thead>
              <tbody>
                {quarantine.map((q) => (
                  <tr key={q.raw_id} className="border-b border-line last:border-b-0">
                    <td className="px-4 py-3 sm:px-5">
                      <div className="font-medium text-ink">{q.raw_data?.name || q.raw_id}</div>
                      <div className="font-mono text-[11px] text-ink-faint">
                        {q.raw_data?.sector || '—'}
                      </div>
                    </td>
                    <td className="px-3 py-3 font-mono text-xs text-ink-muted">
                      {q.source_id || '—'}
                    </td>
                    <td className="px-3 py-3 font-mono text-xs tabular-nums text-ink-muted">
                      {q.discovery_score != null ? q.discovery_score.toFixed(2) : '—'}
                    </td>
                    <td className="max-w-[240px] px-3 py-3 text-xs text-ink-muted">
                      {q.quarantine_reason || '—'}
                    </td>
                    <td className="px-4 py-3 text-right sm:px-5">
                      <button
                        type="button"
                        className="btn-secondary !min-h-8 !px-3 !text-xs"
                        disabled={busy === q.raw_id}
                        onClick={() => release(q.raw_id)}
                      >
                        {busy === q.raw_id ? '…' : '释放'}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
