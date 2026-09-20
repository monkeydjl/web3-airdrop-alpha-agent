'use client';

import type { Label } from '@/lib/types';
import { confColor, formatPct, labelStyles, labelZh } from '@/lib/format';
import type { ReactNode } from 'react';
import { Inbox } from 'lucide-react';

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
  const isFarm = accent === 'farm';
  const isWatch = accent === 'watch';
  const isIgnore = accent === 'ignore';

  const accentBorder = isFarm
    ? 'border-emerald-500/30 hover:border-emerald-500/60'
    : isWatch
      ? 'border-amber-500/30 hover:border-amber-500/60'
      : isIgnore
        ? 'border-slate-700/50 hover:border-slate-500/60'
        : 'border-cyan-500/30 hover:border-cyan-500/60';

  const glowBg = isFarm
    ? 'bg-gradient-to-br from-emerald-500/10 to-transparent'
    : isWatch
      ? 'bg-gradient-to-br from-amber-500/10 to-transparent'
      : isIgnore
        ? 'bg-gradient-to-br from-slate-500/10 to-transparent'
        : 'bg-gradient-to-br from-cyan-500/10 to-transparent';

  const valueColor = isFarm
    ? 'text-emerald-400 font-mono'
    : isWatch
      ? 'text-amber-400 font-mono'
      : isIgnore
        ? 'text-slate-400 font-mono'
        : 'text-cyan-300 font-mono';

  const badgeText = isFarm ? 'PRIORITY' : isWatch ? 'MONITOR' : isIgnore ? 'NOISE' : 'RADAR';
  const badgeClass = isFarm
    ? 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30'
    : isWatch
      ? 'bg-amber-500/15 text-amber-400 border border-amber-500/30'
      : isIgnore
        ? 'bg-slate-800 text-slate-400 border border-slate-700'
        : 'bg-cyan-500/15 text-cyan-400 border border-cyan-500/30';

  const progressBg = isFarm
    ? 'bg-gradient-to-r from-emerald-500 to-cyan-400'
    : isWatch
      ? 'bg-amber-400'
      : isIgnore
        ? 'bg-slate-600'
        : 'bg-cyan-400';

  return (
    <div className={`dash-card relative overflow-hidden p-4 sm:p-5 border ${accentBorder} transition-all duration-200 group`}>
      <div className={`pointer-events-none absolute inset-0 ${glowBg}`} />
      <div className="relative">
        <div className="flex items-center justify-between">
          <span className="text-xs font-semibold uppercase tracking-wider text-ink-muted">{label}</span>
          <span className={`font-mono text-[9px] font-bold px-1.5 py-0.5 rounded ${badgeClass}`}>
            {badgeText}
          </span>
        </div>
        <div className={`mt-2 text-3xl font-extrabold tabular-nums tracking-tight ${valueColor}`}>{value}</div>
        {hint ? <div className="mt-1 text-xs text-ink-faint">{hint}</div> : null}
        <div className="w-full bg-surface-3 h-1 rounded-full mt-3 overflow-hidden">
          <div className={`h-full rounded-full ${progressBg}`} style={{ width: isFarm ? '75%' : isWatch ? '45%' : isIgnore ? '85%' : '95%' }} />
        </div>
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
    label === 'FARM' ? '#00f5a0' : label === 'WATCH' ? '#ffb800' : label === 'IGNORE' ? '#64748b' : '#00d2ff';

  return (
    <div className="relative inline-flex items-center justify-center shrink-0" style={{ width: size, height: size }}>
      <svg viewBox="0 0 100 100" className="h-full w-full -rotate-90">
        <circle cx="50" cy="50" r={r} fill="none" stroke="currentColor" className="text-surface-3" strokeWidth="7" />
        <circle
          cx="50"
          cy="50"
          r={r}
          fill="none"
          stroke={color}
          strokeWidth="7"
          strokeLinecap="round"
          strokeDasharray={c}
          strokeDashoffset={c * (1 - pct)}
          className="transition-all duration-700 drop-shadow-[0_0_8px_rgba(0,245,160,0.3)]"
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-xl font-mono font-extrabold tabular-nums text-ink leading-tight">{Math.round(score)}</span>
        <span className="text-[9px] font-mono tracking-wider text-ink-faint uppercase">SCORE</span>
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
        <span className={`font-mono font-semibold tabular-nums ${confColor(value)}`}>{formatPct(value)}</span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-surface-3">
        <div
          className="h-full rounded-full bg-gradient-to-r from-cyan-500 to-emerald-400 transition-all duration-500 shadow-sm shadow-emerald-500/30"
          style={{ width: `${pct}%` }}
        />
      </div>
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
    <div className="dash-card flex flex-col items-center justify-center border-dashed px-6 py-16 text-center animate-fade-in">
      <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-2xl bg-farm-soft text-farm dark:bg-farm-soft0/15 dark:text-farm">
        <Inbox className="h-6 w-6" strokeWidth={1.5} />
      </div>
      <h3 className="text-base font-semibold text-ink">{title}</h3>
      {description ? <p className="mt-1 max-w-md text-sm text-ink-muted">{description}</p> : null}
      {action ? <div className="mt-5">{action}</div> : null}
    </div>
  );
}

export function SkeletonGrid({ n = 8 }: { n?: number }) {
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 min-[1600px]:grid-cols-5 min-[1920px]:grid-cols-6">
      {Array.from({ length: n }).map((_, i) => (
        <div key={i} className="dash-card p-4 space-y-3">
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
