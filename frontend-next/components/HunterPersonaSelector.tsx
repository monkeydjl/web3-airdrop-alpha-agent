'use client';

import { useState } from 'react';
import { HUNTER_PERSONAS, getPersonaConfig } from '@/lib/personas';
import type { HunterPersonaId } from '@/lib/types';

interface HunterPersonaSelectorProps {
  currentPersona: HunterPersonaId;
  onChange: (personaId: HunterPersonaId) => void;
  loading?: boolean;
}

const PERSONA_COLORS: Record<HunterPersonaId, { border: string; bg: string; text: string; glow: string; badge: string }> = {
  balanced: {
    border: 'border-cyan-500/50',
    bg: 'bg-cyan-500/10',
    text: 'text-cyan-400',
    glow: 'shadow-[0_0_15px_rgba(6,182,212,0.15)]',
    badge: 'bg-cyan-500/15 text-cyan-300 border-cyan-500/30',
  },
  zero_cost: {
    border: 'border-emerald-500/50',
    bg: 'bg-emerald-500/10',
    text: 'text-emerald-400',
    glow: 'shadow-[0_0_15px_rgba(16,185,129,0.15)]',
    badge: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30',
  },
  whale_restaking: {
    border: 'border-blue-500/50',
    bg: 'bg-blue-500/10',
    text: 'text-blue-400',
    glow: 'shadow-[0_0_15px_rgba(59,130,246,0.15)]',
    badge: 'bg-blue-500/15 text-blue-300 border-blue-500/30',
  },
  high_beta: {
    border: 'border-amber-500/50',
    bg: 'bg-amber-500/10',
    text: 'text-amber-400',
    glow: 'shadow-[0_0_15px_rgba(245,158,11,0.15)]',
    badge: 'bg-amber-500/15 text-amber-300 border-amber-500/30',
  },
};

export function HunterPersonaSelector({
  currentPersona,
  onChange,
  loading = false,
}: HunterPersonaSelectorProps) {
  const [showDetail, setShowDetail] = useState(false);
  const activeConfig = getPersonaConfig(currentPersona);
  const theme = PERSONA_COLORS[currentPersona] || PERSONA_COLORS.balanced;

  return (
    <div className="rounded-xl border border-line bg-surface p-3.5 shadow-sm transition-all duration-200">
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-3 pb-2.5">
        <div className="flex items-center gap-2">
          <span className="font-mono text-xs font-semibold uppercase tracking-wider text-ink-muted flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full bg-brand-500 animate-pulse" />
            猎人角色偏好 (Adaptive Persona)
          </span>
          <span className="text-[11px] text-ink-faint hidden sm:inline">
            — 动态重排 8 维自适应打分
          </span>
        </div>

        <button
          type="button"
          onClick={() => setShowDetail(!showDetail)}
          className="text-xs text-ink-muted hover:text-brand-400 flex items-center gap-1 transition self-start md:self-auto"
        >
          <span>{showDetail ? '收起权重解析 ▲' : '查看权重分布 ▼'}</span>
        </button>
      </div>

      {/* 药丸切换器 */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-2">
        {HUNTER_PERSONAS.map((p) => {
          const isActive = currentPersona === p.id;
          const pTheme = PERSONA_COLORS[p.id];
          return (
            <button
              key={p.id}
              type="button"
              disabled={loading}
              onClick={() => onChange(p.id)}
              className={`group relative flex flex-col items-start p-2.5 rounded-lg border text-left transition-all duration-200 ${
                isActive
                  ? `${pTheme.border} ${pTheme.bg} ${pTheme.glow} ring-1 ring-offset-0 ring-white/10`
                  : 'border-line/60 bg-surface-2/40 hover:bg-surface-2 hover:border-line text-ink-muted'
              } ${loading ? 'opacity-60 cursor-not-allowed' : ''}`}
            >
              <div className="flex items-center gap-1.5 w-full">
                <span className="text-base">{p.icon}</span>
                <span className={`text-xs font-bold transition-colors ${isActive ? pTheme.text : 'text-ink group-hover:text-brand-300'}`}>
                  {p.name}
                </span>
              </div>
              <span className="text-[11px] text-ink-faint mt-1 line-clamp-1 leading-snug">
                {p.tagline}
              </span>

              {isActive && (
                <div className="absolute top-2 right-2 flex h-2 w-2">
                  <span className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-75 ${pTheme.bg}`} />
                  <span className={`relative inline-flex rounded-full h-2 w-2 ${pTheme.text.replace('text-', 'bg-')}`} />
                </div>
              )}
            </button>
          );
        })}
      </div>

      {/* 当前生效提示条 */}
      <div className={`mt-3 flex flex-col sm:flex-row sm:items-center justify-between gap-2 text-xs rounded-lg px-3 py-2 border ${theme.border} ${theme.bg}`}>
        <div className="flex items-center gap-2">
          <span className="font-semibold text-ink flex items-center gap-1">
            <span>{activeConfig.icon}</span>
            <span>{activeConfig.name}</span>
          </span>
          <span className="text-ink-muted text-[11px]">
            {activeConfig.description}
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-1.5 shrink-0">
          {activeConfig.badges.map((b) => (
            <span
              key={b}
              className={`text-[10px] font-mono px-1.5 py-0.5 rounded border ${theme.badge}`}
            >
              {b}
            </span>
          ))}
        </div>
      </div>

      {/* 展开的权重矩阵 */}
      {showDetail && (
        <div className="mt-3 pt-3 border-t border-line/60 grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs animate-fade-in">
          {activeConfig.weights ? (
            Object.entries(activeConfig.weights).map(([k, v]) => (
              <div key={k} className="p-2 rounded bg-surface-2/60 border border-line/40 flex justify-between items-center">
                <span className="font-mono text-[11px] text-ink-muted">{k}</span>
                <span className="font-mono font-bold text-brand-400">{(v * 100).toFixed(0)}%</span>
              </div>
            ))
          ) : (
            <div className="col-span-full text-center text-ink-faint py-2">
              使用默认 8 维黄金配比 (空投信号 20%, 叙事 15%, 团队 15%, 风险 15%, 代币 15%, 执行 10%, 透明度 5%, 竞争 5%)
            </div>
          )}
        </div>
      )}
    </div>
  );
}
