'use client';

import type { Label } from '@/lib/types';
import { confColor, formatPct, labelStyles, labelZh, reasonTone } from '@/lib/format';
import type { ReactNode } from 'react';

export function LabelBadge({ label, className = '' }: { label: string; className?: string }) {
  const s = labelStyles(label);
  return (
    <span className={`badge ${s.badge} ${className}`} title={label}>
      {labelZh(label)}
    </span>
  );
}

export function StatCard({
  label,
  value,
  hint,
  accent,
}: {
  label: string;
  value: number | string;
  hint?: string;
  accent?: 'farm' | 'watch' | 'ignore' | 'brand';
}) {
  const ring =
    accent === 'farm'
      ? 'from-farm/20 to-transparent'
      : accent === 'watch'
        ? 'from-watch/20 to-transparent'
        : accent === 'ignore'
          ? 'from-ignore/15 to-transparent'
          : 'from-brand-500/15 to-transparent';
  const valueColor =
    accent === 'farm'
      ? 'text-farm dark:text-farm'
      : accent === 'watch'
        ? 'text-watch dark:text-watch'
        : accent === 'ignore'
          ? 'text-ignore-dark dark:text-slate-300'
          : 'text-farm dark:text-farm';

  return (
    <div className={`card relative overflow-hidden p-4 sm:p-5`}>
      <div className={`pointer-events-none absolute inset-0 bg-gradient-to-br ${ring}`} />
      <div className="relative">
        <div className="text-xs font-medium uppercase tracking-wider text-ink-muted">{label}</div>
        <div className={`mt-1 text-3xl font-bold tabular-nums ${valueColor}`}>{value}</div>
        {hint ? <div className="mt-1 text-xs text-ink-faint">{hint}</div> : null}
      </div>
    </div>
  );
}

export function ScoreRing({
  score,
  size = 96,
  label,
}: {
  score: number;
  size?: number;
  label?: Label | string;
}) {
  const r = 40;
  const c = 2 * Math.PI * r;
  const pct = Math.max(0, Math.min(100, score)) / 100;
  const color =
    label === 'FARM' ? '#10b981' : label === 'WATCH' ? '#f59e0b' : label === 'IGNORE' ? '#64748b' : '#6366f1';

  return (
    <div className="relative inline-flex items-center justify-center" style={{ width: size, height: size }}>
      <svg viewBox="0 0 100 100" className="h-full w-full -rotate-90">
        <circle cx="50" cy="50" r={r} fill="none" stroke="currentColor" className="text-line" strokeWidth="8" />
        <circle
          cx="50"
          cy="50"
          r={r}
          fill="none"
          stroke={color}
          strokeWidth="8"
          strokeLinecap="round"
          strokeDasharray={c}
          strokeDashoffset={c * (1 - pct)}
          className="transition-all duration-700"
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-2xl font-bold tabular-nums text-ink">{score}</span>
        <span className="text-[10px] tracking-wide text-ink-faint">评分</span>
      </div>
    </div>
  );
}

export function ConfidenceBar({ value }: { value: number }) {
  const pct = Math.round(Math.max(0, Math.min(1, value)) * 100);
  return (
    <div>
      <div className="mb-1 flex justify-between text-xs">
        <span className="text-ink-muted">置信度</span>
        <span className={`font-semibold tabular-nums ${confColor(value)}`}>{formatPct(value)}</span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-surface-3">
        <div
          className="h-full rounded-full bg-gradient-to-r from-brand-500 to-farm transition-all duration-500"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

export function ReasonChips({ reasons }: { reasons?: string[] | null }) {
  if (!reasons?.length) {
    return <p className="text-sm text-ink-faint">暂无评分理由</p>;
  }
  return (
    <div className="flex flex-wrap gap-2">
      {reasons.map((r) => {
        const tone = reasonTone(r);
        const cls =
          tone === 'pos'
            ? 'bg-farm-soft text-farm dark:bg-farm/15 dark:text-farm'
            : tone === 'neg'
              ? 'bg-red-50 text-red-700 dark:bg-red-500/15 dark:text-red-300'
              : tone === 'warn'
                ? 'bg-watch-soft text-watch dark:bg-watch/15 dark:text-watch'
                : 'bg-surface-3 text-ink-muted';
        const prefix = tone === 'pos' ? '+' : tone === 'neg' ? '−' : tone === 'warn' ? '!' : '·';
        return (
          <span key={r} className={`badge ${cls}`}>
            <span className="mr-1 opacity-70">{prefix}</span>
            {r}
          </span>
        );
      })}
    </div>
  );
}

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="card flex flex-col items-center justify-center border-dashed px-6 py-16 text-center animate-fade-in">
      <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-2xl bg-farm-soft text-farm dark:bg-farm-soft0/15 dark:text-farm">
        <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 6.75h16.5M3.75 12h16.5m-16.5 5.25H12" />
        </svg>
      </div>
      <h3 className="text-base font-semibold text-ink">{title}</h3>
      {description ? <p className="mt-1 max-w-md text-sm text-ink-muted">{description}</p> : null}
      {action ? <div className="mt-5">{action}</div> : null}
    </div>
  );
}

export function SkeletonGrid({ n = 8 }: { n?: number }) {
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
      {Array.from({ length: n }).map((_, i) => (
        <div key={i} className="card p-4 space-y-3">
          <div className="skeleton h-4 w-2/3" />
          <div className="skeleton h-3 w-1/2" />
          <div className="skeleton h-8 w-16" />
        </div>
      ))}
    </div>
  );
}

/** 采集源启用开关 */
export function Switch({
  checked,
  onChange,
  disabled,
  label,
  id,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  disabled?: boolean;
  label: string;
  id?: string;
}) {
  return (
    <label
      className={`inline-flex min-h-8 cursor-pointer items-center gap-2 select-none ${
        disabled ? 'cursor-not-allowed opacity-50' : ''
      }`}
    >
      <span className="relative inline-flex h-[22px] w-10 shrink-0 items-center">
        <input
          id={id}
          type="checkbox"
          role="switch"
          className="peer sr-only"
          checked={checked}
          disabled={disabled}
          aria-checked={checked}
          aria-label={label}
          onChange={(e) => onChange(e.target.checked)}
        />
        <span
          className={`absolute inset-0 rounded-full border transition ${
            checked
              ? 'border-transparent bg-farm'
              : 'border-line bg-surface-3'
          } peer-focus-visible:ring-2 peer-focus-visible:ring-farm/40`}
          aria-hidden
        />
        <span
          className={`absolute top-[3px] left-[3px] h-4 w-4 rounded-full bg-white shadow transition ${
            checked ? 'translate-x-[18px]' : ''
          }`}
          aria-hidden
        />
      </span>
      <span className={`text-xs font-medium ${checked ? 'text-farm dark:text-farm' : 'text-ink-muted'}`}>
        {checked ? '开' : '关'}
      </span>
    </label>
  );
}

export function Toast({
  message,
  type,
}: {
  message: string;
  type: 'success' | 'error' | 'info';
}) {
  const cls =
    type === 'success'
      ? 'border-farm/30 bg-farm-soft text-farm dark:bg-farm/20 dark:text-farm'
      : type === 'error'
        ? 'border-red-200 bg-red-50 text-red-700 dark:bg-red-500/15 dark:text-red-300'
        : 'border-farm/30 bg-farm-soft text-farm dark:bg-farm-soft0/15 dark:text-farm';
  return (
    <div
      className={`fixed right-4 top-20 z-[80] max-w-sm animate-slide-up rounded-xl border px-4 py-3 text-sm font-medium shadow-lift ${cls}`}
    >
      {message}
    </div>
  );
}

export function ProgressBar({ value, max = 1, color = 'bg-farm-soft0' }: { value: number; max?: number; color?: string }) {
  const pct = Math.max(0, Math.min(100, (value / (max || 1)) * 100));
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-surface-3">
      <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
    </div>
  );
}

export function SectionTitle({ title, action }: { title: string; action?: ReactNode }) {
  return (
    <div className="mb-3 flex items-center justify-between gap-3">
      <h2 className="text-sm font-semibold uppercase tracking-wider text-ink-muted">{title}</h2>
      {action}
    </div>
  );
}
