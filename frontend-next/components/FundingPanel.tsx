'use client';

import { apiFetch } from '@/lib/api';
import { tierZh } from '@/lib/format';
import { useCallback, useEffect, useState } from 'react';

export interface FundingData {
  funding_total_usd?: number | null;
  funding_rounds?: number;
  funding_last_date?: string | null;
  funding_investors?: string[];
  funding_lead_investors?: string[];
  funding_tier?: string;
  funding_quality?: number;
  recent_funding?: boolean;
}

function formatUsd(v?: number | null) {
  if (v == null || !Number.isFinite(Number(v))) return '—';
  const n = Number(v);
  if (n >= 1_000_000_000) return `$${(n / 1_000_000_000).toFixed(2)}B`;
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(2)}M`;
  if (n >= 1_000) return `$${(n / 1_000).toFixed(1)}K`;
  return `$${n.toLocaleString()}`;
}

function parseList(s: string): string[] {
  return s
    .split(/[,，;；\n]/)
    .map((x) => x.trim())
    .filter(Boolean);
}

export function FundingPanel({
  projectId,
  initialFunding,
  initialNote,
  onSaved,
}: {
  projectId: string;
  initialFunding?: FundingData | null;
  initialNote?: string | null;
  onSaved?: () => void;
}) {
  const [loading, setLoading] = useState(!initialFunding);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [msg, setMsg] = useState('');
  const [scoreHint, setScoreHint] = useState('');

  const [totalUsd, setTotalUsd] = useState(
    initialFunding?.funding_total_usd != null ? String(initialFunding.funding_total_usd) : '',
  );
  const [rounds, setRounds] = useState(
    initialFunding?.funding_rounds != null ? String(initialFunding.funding_rounds) : '',
  );
  const [lastDate, setLastDate] = useState(
    (initialFunding?.funding_last_date || '').slice(0, 10),
  );
  const [investors, setInvestors] = useState(
    (initialFunding?.funding_investors || []).join(', '),
  );
  const [leads, setLeads] = useState(
    (initialFunding?.funding_lead_investors || []).join(', '),
  );
  const [recent, setRecent] = useState(Boolean(initialFunding?.recent_funding));
  const [note, setNote] = useState(initialNote || '');
  const [tier, setTier] = useState(initialFunding?.funding_tier || 'unknown');
  const [quality, setQuality] = useState(Number(initialFunding?.funding_quality || 0));

  const applyFunding = useCallback((f: FundingData, n?: string | null) => {
    setTotalUsd(f.funding_total_usd != null ? String(f.funding_total_usd) : '');
    setRounds(f.funding_rounds != null ? String(f.funding_rounds) : '');
    setLastDate((f.funding_last_date || '').slice(0, 10));
    setInvestors((f.funding_investors || []).join(', '));
    setLeads((f.funding_lead_investors || []).join(', '));
    setRecent(Boolean(f.recent_funding));
    setTier(f.funding_tier || 'unknown');
    setQuality(Number(f.funding_quality || 0));
    if (n !== undefined) setNote(n || '');
  }, []);

  const load = useCallback(async () => {
    if (!projectId) return;
    setLoading(true);
    setError('');
    try {
      const data = await apiFetch<{
        project_id: string;
        funding: FundingData;
        funding_note?: string | null;
      }>(`/projects/${projectId}/funding`);
      applyFunding(data.funding || {}, data.funding_note);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '加载融资信息失败');
    } finally {
      setLoading(false);
    }
  }, [projectId, applyFunding]);

  useEffect(() => {
    if (initialFunding) {
      applyFunding(initialFunding, initialNote);
      setLoading(false);
    } else {
      load();
    }
  }, [initialFunding, initialNote, load, applyFunding]);

  const parseNum = (s: string): number | null => {
    if (s.trim() === '') return null;
    const n = Number(s.replace(/,/g, ''));
    return Number.isFinite(n) ? n : null;
  };

  const submit = async () => {
    setSaving(true);
    setMsg('');
    setError('');
    setScoreHint('');
    const roundsNum = parseNum(rounds);
    const payload: Record<string, unknown> = {
      funding_total_usd: parseNum(totalUsd),
      funding_last_date: lastDate || null,
      funding_investors: parseList(investors),
      funding_lead_investors: parseList(leads),
      recent_funding: recent,
      note: note || null,
    };
    if (roundsNum != null) {
      payload.funding_rounds = Math.max(0, Math.floor(roundsNum));
    }
    try {
      const data = await apiFetch<{
        project_id: string;
        funding: FundingData;
        score?: { score?: number; label?: string; confidence?: number; error?: string } | null;
      }>(`/projects/${projectId}/funding?rescore=true`, {
        method: 'PATCH',
        body: JSON.stringify(payload),
      });
      applyFunding(data.funding || {});
      const sc = data.score;
      if (sc?.error) {
        setMsg('融资已保存，但重评失败');
        setScoreHint(sc.error);
      } else if (sc?.score != null) {
        setMsg('融资已保存并重评');
        setScoreHint(
          `分数 ${sc.score} · ${sc.label || '—'} · 置信度 ${
            sc.confidence != null ? (sc.confidence * 100).toFixed(0) + '%' : '—'
          }`,
        );
      } else {
        setMsg('融资已保存');
      }
      onSaved?.();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '保存失败');
    } finally {
      setSaving(false);
      setTimeout(() => setMsg(''), 4000);
    }
  };

  if (loading) {
    return (
      <section className="border border-line bg-surface p-4">
        <div className="skeleton mb-2 h-5 w-32" />
        <div className="skeleton h-24 w-full" />
      </section>
    );
  }

  return (
    <section className="overflow-hidden border border-line bg-surface">
      <div className="border-b border-line px-4 py-3 sm:px-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold text-ink">融资信息（手动）</h3>
            <p className="mt-0.5 text-xs text-ink-muted">
              可补全金额 / 投资方；保存后写入 meta.signals 并重算评分
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="badge bg-farm-soft text-farm dark:bg-farm/15 dark:text-farm">
              {tierZh(tier)}
            </span>
            <span className="badge bg-surface-3 text-ink-muted tabular-nums">
              质量 {(quality * 100).toFixed(0)}%
            </span>
          </div>
        </div>
      </div>

      <div className="grid gap-5 px-4 py-4 sm:px-5 lg:grid-cols-5">
        <div className="space-y-3 lg:col-span-3">
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
            <label className="text-xs text-ink-muted">
              累计融资 (USD)
              <input
                type="number"
                step="1000"
                className="input mt-1"
                placeholder="例如 25000000"
                value={totalUsd}
                onChange={(e) => setTotalUsd(e.target.value)}
              />
            </label>
            <label className="text-xs text-ink-muted">
              轮次数
              <input
                type="number"
                min={0}
                step={1}
                className="input mt-1"
                placeholder="2"
                value={rounds}
                onChange={(e) => setRounds(e.target.value)}
              />
            </label>
            <label className="text-xs text-ink-muted">
              最近一轮日期
              <input
                type="date"
                className="input mt-1"
                value={lastDate}
                onChange={(e) => setLastDate(e.target.value)}
              />
            </label>
          </div>

          <label className="block text-xs text-ink-muted">
            领投方（逗号分隔）
            <input
              className="input mt-1"
              placeholder="Paradigm, a16z"
              value={leads}
              onChange={(e) => setLeads(e.target.value)}
            />
          </label>

          <label className="block text-xs text-ink-muted">
            投资方（逗号分隔）
            <textarea
              className="input mt-1 min-h-[72px]"
              placeholder="Binance Labs, HashKey, …"
              value={investors}
              onChange={(e) => setInvestors(e.target.value)}
            />
          </label>

          <label className="flex items-center gap-2 text-sm text-ink">
            <input
              type="checkbox"
              className="h-4 w-4 rounded border-line"
              checked={recent}
              onChange={(e) => setRecent(e.target.checked)}
            />
            视为近期融资信号
          </label>

          <label className="block text-xs text-ink-muted">
            备注
            <input
              className="input mt-1"
              placeholder="来源：官方公告 / CryptoRank / …"
              value={note}
              onChange={(e) => setNote(e.target.value)}
            />
          </label>

          <div className="flex flex-wrap items-center gap-2 pt-1">
            <button type="button" className="btn-primary" disabled={saving} onClick={submit}>
              {saving ? '保存并重评…' : '保存并重评'}
            </button>
            <button type="button" className="btn-secondary" disabled={saving} onClick={load}>
              重新加载
            </button>
            {msg ? <span className="text-xs text-farm dark:text-farm">{msg}</span> : null}
          </div>
          {scoreHint ? <p className="text-xs text-ink-muted">{scoreHint}</p> : null}
          {error ? <p className="text-xs text-red-600 dark:text-red-300">{error}</p> : null}
        </div>

        <div className="space-y-3 rounded-lg border border-line bg-surface-2/40 p-4 lg:col-span-2">
          <div className="text-xs font-semibold uppercase tracking-wider text-ink-muted">当前摘要</div>
          <div className="space-y-2 text-sm">
            <div className="flex justify-between gap-2">
              <span className="text-ink-muted">累计</span>
              <span className="font-medium tabular-nums text-ink">{formatUsd(parseNum(totalUsd))}</span>
            </div>
            <div className="flex justify-between gap-2">
              <span className="text-ink-muted">轮次</span>
              <span className="font-medium tabular-nums text-ink">{rounds || '—'}</span>
            </div>
            <div className="flex justify-between gap-2">
              <span className="text-ink-muted">最近日期</span>
              <span className="font-medium text-ink">{lastDate || '—'}</span>
            </div>
            <div className="flex justify-between gap-2">
              <span className="text-ink-muted">档位</span>
              <span className="font-medium text-ink">{tierZh(tier)}</span>
            </div>
            <div className="flex justify-between gap-2">
              <span className="text-ink-muted">质量分</span>
              <span className="font-medium tabular-nums text-ink">{(quality * 100).toFixed(0)}%</span>
            </div>
          </div>
          <p className="text-[11px] leading-relaxed text-ink-faint">
            一线 VC（a16z / Paradigm / Binance Labs 等）会抬高团队分与空投档；金额与近 365 天轮次也会加分。
          </p>
        </div>
      </div>
    </section>
  );
}
