'use client';

/**
 * 收益台账（F3，ACTION_LOOP_DESIGN §4）。
 *
 * 与同页的「参与复盘」区块（interactions）是**两套不同的数据**，刻意分开展示：
 * - interactions = 一条参与的整体记录（状态/结果/粗粒度成本）
 * - roi_entries/outcomes = 逐笔投入与产出流水，是校准真值的来源
 *
 * 展示上的诚实边界（照后端 §4.2 的口径，别在前端悄悄"优化"）：
 * - 工时**不折算成钱**：折算要引入一个凭空捏造的时薪，会让数字看起来精确但不可信。
 * - `roi_ratio === null`（零投入）显示 `—` 而不是 `0%`：零投入下 ROI 没有定义，
 *   显示 0% 会被读成"没赚没赔"。
 */

import { apiFetch } from '@/lib/api';
import { Plus, Trash2 } from 'lucide-react';
import Link from 'next/link';
import { useCallback, useEffect, useState } from 'react';

export interface RoiSummaryTotals {
  cost_usd: number;
  hours: number;
  returned_usd: number;
  tokens: number;
  net_usd: number;
  roi_ratio: number | null;
  project_count: number;
}

export interface RoiSummaryItem {
  project_id: string;
  cost_usd: number;
  hours: number;
  returned_usd: number;
  tokens: number;
  net_usd: number;
  roi_ratio: number | null;
}

interface RoiSummary {
  totals?: RoiSummaryTotals;
  items?: RoiSummaryItem[];
}

const ENTRY_KINDS = [
  { value: 'gas', label: 'Gas' },
  { value: 'infra', label: '基础设施' },
  { value: 'time', label: '时间' },
  { value: 'other', label: '其他' },
] as const;

const OUTCOME_EVENTS = [
  { value: 'airdrop_received', label: '空投到账' },
  { value: 'airdrop_missed', label: '未领到' },
  { value: 'token_launched', label: '已发币' },
  { value: 'campaign_ended', label: '活动结束' },
] as const;

function fmtUsd(v: number | null | undefined): string {
  if (v == null) return '—';
  return `$${Math.round(v).toLocaleString()}`;
}

function fmtSigned(v: number | null | undefined): string {
  if (v == null) return '—';
  return `${v > 0 ? '+' : ''}$${Math.round(v).toLocaleString()}`;
}

/** null 是「无定义」而不是 0 —— 见文件头注释。 */
function fmtRatio(v: number | null | undefined): string {
  if (v == null) return '—';
  return `${Math.round(v * 100)}%`;
}

export function RoiLedger({ projectNames = {} }: { projectNames?: Record<string, string> }) {
  const [summary, setSummary] = useState<RoiSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [formOpen, setFormOpen] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setSummary(await apiFetch<RoiSummary>('/roi/summary'));
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const totals = summary?.totals;
  const items = summary?.items ?? [];

  return (
    <section className="pf-card overflow-hidden" aria-label="收益台账">
      <div className="pf-card-head flex items-start justify-between gap-3">
        <div>
          <h2 className="pf-card-title">收益台账</h2>
          <p className="pf-card-caption">
            逐笔投入与产出 · 权重校准的真值来源 · 工时不折算成金额
          </p>
        </div>
        <button
          type="button"
          className="btn-secondary inline-flex items-center gap-1.5 whitespace-nowrap"
          onClick={() => setFormOpen((v) => !v)}
        >
          <Plus className="h-4 w-4" strokeWidth={2} />
          <span className="hidden sm:inline">记一笔</span>
        </button>
      </div>

      {formOpen && <RoiEntryForm onSaved={load} onClose={() => setFormOpen(false)} />}

      <div className="pf-card-body">
        {loading ? (
          <p className="text-xs text-ink-muted">加载中…</p>
        ) : error ? (
          <p className="text-xs" style={{ color: 'var(--state-error)' }}>
            {error}
          </p>
        ) : !totals || totals.project_count === 0 ? (
          <p className="text-xs text-ink-muted">
            还没有台账记录。点「记一笔」录入 gas / 工时投入或空投到账，
            这里会汇总净收益，并作为校准的真值样本。
          </p>
        ) : (
          <>
            <div className="pf-kpi-grid mb-4">
              <div className="pf-kpi">
                <span className="pf-kpi-label">总投入</span>
                <span className="pf-kpi-value">{fmtUsd(totals.cost_usd)}</span>
                <span className="pf-kpi-caption">另有 {totals.hours} 小时工时</span>
              </div>
              <div className="pf-kpi">
                <span className="pf-kpi-label">总产出</span>
                <span className="pf-kpi-value">{fmtUsd(totals.returned_usd)}</span>
                <span className="pf-kpi-caption">{totals.tokens} 枚代币（人工录入）</span>
              </div>
              <div className="pf-kpi">
                <span className="pf-kpi-label">净收益</span>
                <span
                  className="pf-kpi-value"
                  style={{ color: totals.net_usd >= 0 ? 'rgb(var(--farm))' : 'var(--state-error)' }}
                >
                  {fmtSigned(totals.net_usd)}
                </span>
                <span className="pf-kpi-caption">收益率 {fmtRatio(totals.roi_ratio)}</span>
              </div>
              <div className="pf-kpi">
                <span className="pf-kpi-label">覆盖项目</span>
                <span className="pf-kpi-value">{totals.project_count}</span>
                <span className="pf-kpi-caption">有台账记录的项目数</span>
              </div>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full min-w-[560px] text-left text-sm">
                <thead className="border-b border-line bg-surface-2/50">
                  <tr className="font-mono text-[10px] font-semibold uppercase tracking-wider text-ink-muted">
                    <th className="px-4 py-2.5 sm:px-5">项目</th>
                    <th className="px-3 py-2.5">投入</th>
                    <th className="px-3 py-2.5">工时</th>
                    <th className="px-3 py-2.5">产出</th>
                    <th className="px-3 py-2.5">净额</th>
                    <th className="px-4 py-2.5 sm:px-5">收益率</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((it) => (
                    <tr key={it.project_id} className="border-b border-line last:border-b-0 hover:bg-surface-2">
                      <td className="px-4 py-3 sm:px-5">
                        <Link
                          href={`/project/${it.project_id}`}
                          className="text-sm font-medium text-ink hover:text-farm"
                        >
                          {projectNames[it.project_id] || it.project_id.slice(0, 8)}
                        </Link>
                      </td>
                      <td className="px-3 py-3 font-mono text-xs">{fmtUsd(it.cost_usd)}</td>
                      <td className="px-3 py-3 font-mono text-xs text-ink-muted">{it.hours}h</td>
                      <td className="px-3 py-3 font-mono text-xs">{fmtUsd(it.returned_usd)}</td>
                      <td
                        className="px-3 py-3 font-mono text-xs"
                        style={{
                          color:
                            it.net_usd > 0
                              ? 'rgb(var(--farm))'
                              : it.net_usd < 0
                                ? 'var(--state-error)'
                                : undefined,
                        }}
                      >
                        {fmtSigned(it.net_usd)}
                      </td>
                      <td className="px-4 py-3 sm:px-5 font-mono text-xs text-ink-muted">
                        {fmtRatio(it.roi_ratio)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>
    </section>
  );
}

/** 录入表单。投入与产出共用一个面板，靠 mode 切换。 */
function RoiEntryForm({ onSaved, onClose }: { onSaved: () => void; onClose: () => void }) {
  const [mode, setMode] = useState<'entry' | 'outcome'>('entry');
  const [projectId, setProjectId] = useState('');
  const [kind, setKind] = useState<string>('gas');
  const [event, setEvent] = useState<string>('airdrop_received');
  const [amount, setAmount] = useState('');
  const [hours, setHours] = useState('');
  const [tokens, setTokens] = useState('');
  const [note, setNote] = useState('');
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const submit = async () => {
    setErr(null);
    if (!projectId.trim()) {
      setErr('请填项目 ID');
      return;
    }
    const amountNum = amount.trim() ? Number(amount) : null;
    const hoursNum = hours.trim() ? Number(hours) : null;
    if (mode === 'entry' && amountNum == null && hoursNum == null) {
      // 与后端 422 MISSING_AMOUNT 同一规则：两个量纲都空的行对台账没有贡献
      setErr('金额与工时至少填一个');
      return;
    }
    setSaving(true);
    try {
      const pid = encodeURIComponent(projectId.trim());
      if (mode === 'entry') {
        await apiFetch(`/projects/${pid}/roi/entries`, {
          method: 'POST',
          body: JSON.stringify({ kind, amount_usd: amountNum, hours: hoursNum, note: note || null }),
        });
      } else {
        await apiFetch(`/projects/${pid}/roi/outcomes`, {
          method: 'POST',
          body: JSON.stringify({
            event,
            amount_usd: amountNum,
            tokens: tokens.trim() ? Number(tokens) : null,
            note: note || null,
          }),
        });
      }
      setAmount('');
      setHours('');
      setTokens('');
      setNote('');
      onSaved();
      onClose();
    } catch (e) {
      setErr(e instanceof Error ? e.message : '保存失败');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="border-b border-line bg-surface-2/40 px-4 py-4 sm:px-5">
      <div className="mb-3 flex gap-2">
        <button
          type="button"
          className={mode === 'entry' ? 'btn-primary' : 'btn-secondary'}
          onClick={() => setMode('entry')}
        >
          投入
        </button>
        <button
          type="button"
          className={mode === 'outcome' ? 'btn-primary' : 'btn-secondary'}
          onClick={() => setMode('outcome')}
        >
          产出
        </button>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <label className="flex flex-col gap-1">
          <span className="text-[10px] font-semibold uppercase tracking-wider text-ink-muted">项目 ID</span>
          <input
            className="rounded border border-line bg-surface px-2 py-1.5 text-sm"
            value={projectId}
            onChange={(e) => setProjectId(e.target.value)}
            placeholder="proj-xxxx"
          />
        </label>

        {mode === 'entry' ? (
          <label className="flex flex-col gap-1">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-ink-muted">类型</span>
            <select
              className="rounded border border-line bg-surface px-2 py-1.5 text-sm"
              value={kind}
              onChange={(e) => setKind(e.target.value)}
            >
              {ENTRY_KINDS.map((k) => (
                <option key={k.value} value={k.value}>
                  {k.label}
                </option>
              ))}
            </select>
          </label>
        ) : (
          <label className="flex flex-col gap-1">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-ink-muted">事件</span>
            <select
              className="rounded border border-line bg-surface px-2 py-1.5 text-sm"
              value={event}
              onChange={(e) => setEvent(e.target.value)}
            >
              {OUTCOME_EVENTS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </label>
        )}

        <label className="flex flex-col gap-1">
          <span className="text-[10px] font-semibold uppercase tracking-wider text-ink-muted">金额（USD）</span>
          <input
            type="number"
            min={0}
            className="rounded border border-line bg-surface px-2 py-1.5 text-sm"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            placeholder="选填"
          />
        </label>

        {mode === 'entry' ? (
          <label className="flex flex-col gap-1">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-ink-muted">工时（小时）</span>
            <input
              type="number"
              min={0}
              className="rounded border border-line bg-surface px-2 py-1.5 text-sm"
              value={hours}
              onChange={(e) => setHours(e.target.value)}
              placeholder="选填"
            />
          </label>
        ) : (
          <label className="flex flex-col gap-1">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-ink-muted">代币数量</span>
            <input
              type="number"
              min={0}
              className="rounded border border-line bg-surface px-2 py-1.5 text-sm"
              value={tokens}
              onChange={(e) => setTokens(e.target.value)}
              placeholder="选填"
            />
          </label>
        )}

        <label className="flex flex-col gap-1 sm:col-span-2 lg:col-span-1">
          <span className="text-[10px] font-semibold uppercase tracking-wider text-ink-muted">备注</span>
          <input
            className="rounded border border-line bg-surface px-2 py-1.5 text-sm"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="选填"
          />
        </label>
      </div>

      {err && (
        <p className="mt-2 text-xs" style={{ color: 'var(--state-error)' }}>
          {err}
        </p>
      )}

      <div className="mt-3 flex items-center gap-2">
        <button type="button" className="btn-primary" onClick={submit} disabled={saving}>
          {saving ? '保存中…' : '保存'}
        </button>
        <button type="button" className="btn-secondary" onClick={onClose} disabled={saving}>
          取消
        </button>
        <span className="ml-auto inline-flex items-center gap-1 text-[10px] text-ink-faint">
          <Trash2 className="h-3 w-3" strokeWidth={2} />
          金额为人工录入，系统不做链上取价
        </span>
      </div>
    </div>
  );
}
