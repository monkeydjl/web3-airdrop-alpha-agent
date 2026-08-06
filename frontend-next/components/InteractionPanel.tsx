'use client';

import { apiFetch } from '@/lib/api';
import { labelZh } from '@/lib/format';
import { useCallback, useEffect, useMemo, useState } from 'react';

export interface Interaction {
  id: number;
  project_id: string;
  status: string;
  started_at?: string | null;
  ended_at?: string | null;
  cost_usd?: number | null;
  profit_usd?: number | null;
  net_usd?: number | null;
  hours_spent?: number | null;
  activities?: string | null;
  note?: string | null;
  outcome?: string | null;
  score_at_start?: number | null;
  label_at_start?: string | null;
  created_at?: string | null;
}

const STATUS_OPTS = [
  { id: 'planned', label: '计划中' },
  { id: 'active', label: '进行中' },
  { id: 'done', label: '已完成' },
  { id: 'abandoned', label: '已放弃' },
] as const;

const OUTCOME_OPTS = [
  { id: 'pending', label: '待定' },
  { id: 'airdropped', label: '已空投' },
  { id: 'not_airdropped', label: '未空投' },
  { id: 'profit', label: '盈利' },
  { id: 'loss', label: '亏损' },
  { id: 'breakeven', label: '打平' },
  { id: 'unknown', label: '未知' },
] as const;

function statusZh(s?: string | null) {
  return STATUS_OPTS.find((x) => x.id === s)?.label || s || '—';
}
function outcomeZh(s?: string | null) {
  return OUTCOME_OPTS.find((x) => x.id === s)?.label || s || '—';
}

function todayISO() {
  return new Date().toISOString().slice(0, 10);
}

export function InteractionPanel({ projectId }: { projectId: string }) {
  const [items, setItems] = useState<Interaction[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [msg, setMsg] = useState('');

  const [status, setStatus] = useState<string>('active');
  const [startedAt, setStartedAt] = useState(todayISO());
  const [endedAt, setEndedAt] = useState('');
  const [cost, setCost] = useState('');
  const [profit, setProfit] = useState('');
  const [hours, setHours] = useState('');
  const [activities, setActivities] = useState('');
  const [note, setNote] = useState('');
  const [outcome, setOutcome] = useState('pending');
  const [editingId, setEditingId] = useState<number | null>(null);

  const load = useCallback(async () => {
    if (!projectId) return;
    setLoading(true);
    setError('');
    try {
      const data = await apiFetch<{ items: Interaction[]; total: number }>(
        `/projects/${projectId}/interactions?limit=50`,
      );
      setItems(data.items || []);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '加载失败');
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    load();
  }, [load]);

  const totals = useMemo(() => {
    let costSum = 0;
    let profitSum = 0;
    let hoursSum = 0;
    for (const it of items) {
      costSum += Number(it.cost_usd || 0);
      profitSum += Number(it.profit_usd || 0);
      hoursSum += Number(it.hours_spent || 0);
    }
    return { costSum, profitSum, net: profitSum - costSum, hoursSum };
  }, [items]);

  const resetForm = () => {
    setEditingId(null);
    setStatus('active');
    setStartedAt(todayISO());
    setEndedAt('');
    setCost('');
    setProfit('');
    setHours('');
    setActivities('');
    setNote('');
    setOutcome('pending');
  };

  const fillFrom = (it: Interaction) => {
    setEditingId(it.id);
    setStatus(it.status || 'active');
    setStartedAt((it.started_at || '').slice(0, 10));
    setEndedAt((it.ended_at || '').slice(0, 10));
    setCost(it.cost_usd != null ? String(it.cost_usd) : '');
    setProfit(it.profit_usd != null ? String(it.profit_usd) : '');
    setHours(it.hours_spent != null ? String(it.hours_spent) : '');
    setActivities(it.activities || '');
    setNote(it.note || '');
    setOutcome(it.outcome || 'pending');
  };

  const parseNum = (s: string): number | null => {
    if (s.trim() === '') return null;
    const n = Number(s);
    return Number.isFinite(n) ? n : null;
  };

  const submit = async () => {
    setSaving(true);
    setMsg('');
    setError('');
    const payload = {
      status,
      started_at: startedAt || null,
      ended_at: endedAt || null,
      cost_usd: parseNum(cost),
      profit_usd: parseNum(profit),
      hours_spent: parseNum(hours),
      activities: activities || null,
      note: note || null,
      outcome: outcome || 'pending',
    };
    try {
      if (editingId != null) {
        await apiFetch(`/interactions/${editingId}`, {
          method: 'PATCH',
          body: JSON.stringify(payload),
        });
        setMsg('已更新交互记录');
      } else {
        await apiFetch('/interactions', {
          method: 'POST',
          body: JSON.stringify({ project_id: projectId, ...payload }),
        });
        setMsg('已保存交互记录');
      }
      resetForm();
      await load();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '保存失败');
    } finally {
      setSaving(false);
      setTimeout(() => setMsg(''), 3000);
    }
  };

  const remove = async (id: number) => {
    if (!confirm('确定删除这条交互记录？')) return;
    try {
      await apiFetch(`/interactions/${id}`, { method: 'DELETE' });
      if (editingId === id) resetForm();
      await load();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '删除失败');
    }
  };

  return (
    <section className="card overflow-hidden">
      <div className="border-b border-line bg-gradient-to-r from-farm/10 via-transparent to-watch/10 px-5 py-4 sm:px-6">
        <h2 className="text-base font-bold text-ink">我的交互记录</h2>
        <p className="mt-0.5 text-xs text-ink-muted">
          记录是否做过、起止日期、成本与收益，用于复盘与后期系统优化
        </p>
      </div>

      <div className="grid gap-5 px-5 py-5 sm:px-6 lg:grid-cols-5">
        {/* form */}
        <div className="space-y-3 lg:col-span-2">
          <div className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
            {editingId != null ? `编辑记录 #${editingId}` : '新建记录'}
          </div>
          <div className="grid grid-cols-2 gap-2">
            <label className="text-xs text-ink-muted">
              状态
              <select className="select mt-1" value={status} onChange={(e) => setStatus(e.target.value)}>
                {STATUS_OPTS.map((o) => (
                  <option key={o.id} value={o.id}>
                    {o.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-xs text-ink-muted">
              结果
              <select className="select mt-1" value={outcome} onChange={(e) => setOutcome(e.target.value)}>
                {OUTCOME_OPTS.map((o) => (
                  <option key={o.id} value={o.id}>
                    {o.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-xs text-ink-muted">
              开始日期
              <input
                type="date"
                className="input mt-1"
                value={startedAt}
                onChange={(e) => setStartedAt(e.target.value)}
              />
            </label>
            <label className="text-xs text-ink-muted">
              结束日期
              <input
                type="date"
                className="input mt-1"
                value={endedAt}
                onChange={(e) => setEndedAt(e.target.value)}
              />
            </label>
            <label className="text-xs text-ink-muted">
              成本 (USD)
              <input
                type="number"
                step="0.01"
                className="input mt-1"
                placeholder="0"
                value={cost}
                onChange={(e) => setCost(e.target.value)}
              />
            </label>
            <label className="text-xs text-ink-muted">
              收益 (USD)
              <input
                type="number"
                step="0.01"
                className="input mt-1"
                placeholder="0"
                value={profit}
                onChange={(e) => setProfit(e.target.value)}
              />
            </label>
            <label className="col-span-2 text-xs text-ink-muted">
              花费时间 (小时)
              <input
                type="number"
                step="0.1"
                className="input mt-1"
                placeholder="例如 3.5"
                value={hours}
                onChange={(e) => setHours(e.target.value)}
              />
            </label>
            <label className="col-span-2 text-xs text-ink-muted">
              做了什么
              <input
                className="input mt-1"
                placeholder="Do not enter wallet addresses or sensitive identifiers"
                aria-describedby="interaction-free-text-help"
                value={activities}
                onChange={(e) => setActivities(e.target.value)}
              />
            </label>
            <label className="col-span-2 text-xs text-ink-muted">
              备注
              <textarea
                className="input mt-1 min-h-[72px] resize-y"
                placeholder="Do not enter wallet addresses or sensitive identifiers"
                aria-describedby="interaction-free-text-help"
                value={note}
                onChange={(e) => setNote(e.target.value)}
              />
            </label>
            <p id="interaction-free-text-help" className="col-span-2 text-xs text-ink-faint">
              Do not enter wallet addresses or sensitive identifiers. Label transaction hashes with tx: or transaction:.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button type="button" className="btn-primary" disabled={saving} onClick={submit}>
              {saving ? '保存中…' : editingId != null ? '更新记录' : '保存记录'}
            </button>
            {editingId != null ? (
              <button type="button" className="btn-secondary" onClick={resetForm}>
                取消编辑
              </button>
            ) : null}
          </div>
          {msg ? <p className="text-xs text-farm-dark dark:text-farm">{msg}</p> : null}
          {error ? <p className="text-xs text-red-600 dark:text-red-300">{error}</p> : null}
        </div>

        {/* list */}
        <div className="lg:col-span-3">
          <div className="mb-3 flex flex-wrap gap-3 text-xs text-ink-muted">
            <span className="badge bg-surface-3">
              记录 {items.length} 条
            </span>
            <span className="badge bg-surface-3">成本 ${totals.costSum.toFixed(2)}</span>
            <span className="badge bg-surface-3">收益 ${totals.profitSum.toFixed(2)}</span>
            <span
              className={`badge ${
                totals.net >= 0
                  ? 'bg-farm-soft text-farm-dark dark:bg-farm/15 dark:text-farm'
                  : 'bg-red-50 text-red-700 dark:bg-red-500/15 dark:text-red-300'
              }`}
            >
              净收益 ${totals.net.toFixed(2)}
            </span>
            <span className="badge bg-surface-3">用时 {totals.hoursSum.toFixed(1)} h</span>
          </div>

          {loading ? (
            <div className="space-y-2">
              <div className="skeleton h-16" />
              <div className="skeleton h-16" />
            </div>
          ) : items.length === 0 ? (
            <div className="rounded-xl border border-dashed border-line px-4 py-10 text-center text-sm text-ink-faint">
              还没有交互记录。填好左侧表单后点「保存记录」。
            </div>
          ) : (
            <div className="space-y-2">
              {items.map((it) => (
                <div
                  key={it.id}
                  className="rounded-xl border border-line/80 bg-surface-2/40 px-3 py-3 transition hover:border-brand-300/40"
                >
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="badge bg-brand-50 text-brand-700 dark:bg-brand-500/15 dark:text-brand-200">
                          {statusZh(it.status)}
                        </span>
                        <span className="badge bg-surface-3 text-ink-muted">{outcomeZh(it.outcome)}</span>
                        {it.label_at_start ? (
                          <span className="text-[11px] text-ink-faint">
                            开始时标签 {labelZh(it.label_at_start)}
                            {it.score_at_start != null ? ` · ${it.score_at_start} 分` : ''}
                          </span>
                        ) : null}
                      </div>
                      <p className="mt-1.5 text-xs text-ink-muted">
                        {(it.started_at || '—').slice(0, 10)} → {(it.ended_at || '进行中').toString().slice(0, 10)}
                        {it.activities ? ` · ${it.activities}` : ''}
                      </p>
                      {it.note ? <p className="mt-1 text-xs text-ink-faint line-clamp-2">{it.note}</p> : null}
                    </div>
                    <div className="text-right text-xs">
                      <div className="tabular-nums text-ink-muted">
                        成本 ${Number(it.cost_usd || 0).toFixed(2)}
                      </div>
                      <div className="tabular-nums text-ink-muted">
                        收益 ${Number(it.profit_usd || 0).toFixed(2)}
                      </div>
                      <div
                        className={`font-semibold tabular-nums ${
                          Number(it.net_usd || 0) >= 0 ? 'text-farm-dark dark:text-farm' : 'text-red-600'
                        }`}
                      >
                        净 ${Number(it.net_usd || 0).toFixed(2)}
                      </div>
                      <div className="mt-2 flex justify-end gap-2">
                        <button type="button" className="btn-ghost !px-2 !py-1 text-xs" onClick={() => fillFrom(it)}>
                          编辑
                        </button>
                        <button
                          type="button"
                          className="btn-ghost !px-2 !py-1 text-xs text-red-600"
                          onClick={() => remove(it.id)}
                        >
                          删除
                        </button>
                      </div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
