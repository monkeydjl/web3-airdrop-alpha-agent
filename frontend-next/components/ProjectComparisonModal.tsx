'use client';

import { useCallback, useEffect, useState } from 'react';
import { apiFetch } from '@/lib/api';
import { X, Swords, Trophy, Sparkles, AlertCircle } from 'lucide-react';
import { LabelBadge } from './ui';

interface Dimension {
  key: string;
  name: string;
  description: string;
}

interface ComparedProject {
  id: string;
  name: string;
  sector: string;
  stage: string;
  score: number;
  label: 'FARM' | 'WATCH' | 'IGNORE';
  url: string;
  dimension_scores: Record<string, number>;
}

interface RadarAxis {
  key: string;
  name: string;
  description: string;
  values: Record<string, number>;
}

interface ComparisonData {
  ok: boolean;
  projects: ComparedProject[];
  dimensions: Dimension[];
  radar_axes: RadarAxis[];
  verdict: {
    winner_overall_id: string;
    winner_overall_name: string;
    best_for_low_capital_id: string;
    best_for_low_capital_name: string;
    best_for_whale_staking_id: string;
    best_for_whale_staking_name: string;
    tradeoffs: string[];
  };
}

const COLORS = [
  { stroke: '#10b981', fill: 'rgba(16, 185, 129, 0.2)', text: 'text-emerald-400' },
  { stroke: '#06b6d4', fill: 'rgba(6, 182, 212, 0.2)', text: 'text-cyan-400' },
  { stroke: '#a855f7', fill: 'rgba(168, 85, 247, 0.2)', text: 'text-purple-400' },
];

export function ProjectComparisonModal({
  initialProjectIds,
  onClose,
}: {
  initialProjectIds: string[];
  onClose: () => void;
}) {
  const [data, setData] = useState<ComparisonData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const fetchComparison = useCallback(async () => {
    if (!initialProjectIds || initialProjectIds.length === 0) return;
    setLoading(true);
    setError('');
    try {
      const res = await apiFetch<ComparisonData>(
        `/projects/compare?ids=${encodeURIComponent(initialProjectIds.join(','))}`
      );
      if (res?.ok) {
        setData(res);
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '获取项目对比失败');
    } finally {
      setLoading(false);
    }
  }, [initialProjectIds]);

  useEffect(() => {
    fetchComparison();
  }, [fetchComparison]);

  // SVG Radar generator
  const renderRadarSvg = () => {
    if (!data || data.radar_axes.length === 0) return null;
    const size = 300;
    const center = size / 2;
    const radius = 100;
    const totalAxes = data.radar_axes.length;

    // Grid circles
    const levels = [0.25, 0.5, 0.75, 1.0];

    return (
      <svg width={size} height={size} className="mx-auto overflow-visible">
        {/* Background web */}
        {levels.map((lvl) => {
          const points = data.radar_axes.map((_, i) => {
            const angle = (Math.PI * 2 / totalAxes) * i - Math.PI / 2;
            const x = center + Math.cos(angle) * radius * lvl;
            const y = center + Math.sin(angle) * radius * lvl;
            return `${x},${y}`;
          }).join(' ');
          return (
            <polygon
              key={lvl}
              points={points}
              fill="none"
              stroke="currentColor"
              className="text-line"
              strokeDasharray={lvl < 1.0 ? '2 2' : undefined}
            />
          );
        })}

        {/* Axis lines and labels */}
        {data.radar_axes.map((axis, i) => {
          const angle = (Math.PI * 2 / totalAxes) * i - Math.PI / 2;
          const x = center + Math.cos(angle) * radius;
          const y = center + Math.sin(angle) * radius;
          const labelX = center + Math.cos(angle) * (radius + 20);
          const labelY = center + Math.sin(angle) * (radius + 15);

          return (
            <g key={axis.key}>
              <line
                x1={center}
                y1={center}
                x2={x}
                y2={y}
                stroke="currentColor"
                className="text-line"
              />
              <text
                x={labelX}
                y={labelY}
                textAnchor="middle"
                dominantBaseline="central"
                className="text-[10px] fill-ink-muted font-medium"
              >
                {axis.name}
              </text>
            </g>
          );
        })}

        {/* Project polygons */}
        {data.projects.map((p, pIdx) => {
          const color = COLORS[pIdx % COLORS.length];
          const points = data.radar_axes.map((axis, i) => {
            const val = (axis.values[p.id] || 50) / 100;
            const angle = (Math.PI * 2 / totalAxes) * i - Math.PI / 2;
            const x = center + Math.cos(angle) * radius * val;
            const y = center + Math.sin(angle) * radius * val;
            return `${x},${y}`;
          }).join(' ');

          return (
            <polygon
              key={p.id}
              points={points}
              fill={color.fill}
              stroke={color.stroke}
              strokeWidth="2"
              className="transition-all duration-300"
            />
          );
        })}
      </svg>
    );
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/75 backdrop-blur-sm animate-fade-in">
      <div className="dash-card w-full max-w-4xl max-h-[90vh] flex flex-col p-6 shadow-2xl border-line bg-surface relative overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between pb-4 border-b border-line">
          <div className="flex items-center gap-2.5">
            <div className="p-2 rounded-lg bg-brand-500/15 text-brand-400 border border-brand-500/30">
              <Swords className="h-5 w-5" />
            </div>
            <div>
              <h2 className="text-base font-bold text-ink flex items-center gap-2">
                <span>重点项目多维雷达对比与竞品 PK 矩阵</span>
                <span className="badge bg-purple-500/15 text-purple-400 border border-purple-500/30 text-[10px]">
                  8 维深度对齐
                </span>
              </h2>
              <p className="text-xs text-ink-muted mt-0.5">
                横向比对团队背景、融资储备、开发活跃度与资本门槛，输出差异化投资偏好
              </p>
            </div>
          </div>

          <button
            type="button"
            onClick={onClose}
            className="p-1.5 rounded-lg hover:bg-surface-2 text-ink-muted hover:text-ink transition"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto py-4 space-y-6">
          {loading && (
            <div className="py-20 text-center text-sm text-ink-muted">
              正在加载并对齐 8 维指标数据…
            </div>
          )}

          {error && (
            <div className="p-4 rounded-lg bg-red-500/10 border border-red-500/30 text-xs text-red-400 flex items-center gap-2">
              <AlertCircle className="h-4 w-4 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          {data && (
            <>
              {/* 项目概览图例 */}
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                {data.projects.map((p, idx) => {
                  const color = COLORS[idx % COLORS.length];
                  return (
                    <div
                      key={p.id}
                      className="p-3.5 rounded-xl border bg-surface-2/70 flex items-center justify-between"
                      style={{ borderColor: color.stroke }}
                    >
                      <div>
                        <div className="flex items-center gap-1.5">
                          <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: color.stroke }} />
                          <h3 className="text-sm font-bold text-ink">{p.name}</h3>
                        </div>
                        <p className="text-xs text-ink-muted mt-0.5">{p.sector} · {p.stage}</p>
                      </div>
                      <div className="flex flex-col items-end gap-1">
                        <LabelBadge label={p.label} />
                        <span className="text-xs font-mono font-bold text-ink">{p.score} 分</span>
                      </div>
                    </div>
                  );
                })}
              </div>

              {/* 中间区：雷达图 + 裁决建议 */}
              <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-center">
                <div className="lg:col-span-5 flex flex-col items-center justify-center p-4 rounded-xl bg-surface-2/40 border border-line">
                  <span className="text-xs font-bold text-ink mb-2">8 边形多维对比雷达</span>
                  {renderRadarSvg()}
                </div>

                <div className="lg:col-span-7 space-y-3">
                  <div className="p-3.5 rounded-xl bg-brand-500/10 border border-brand-500/20">
                    <div className="flex items-center gap-2 text-xs font-bold text-brand-400">
                      <Trophy className="h-4 w-4" />
                      <span>综合裁决偏好 (Strategic Verdict)</span>
                    </div>
                    <div className="mt-2 space-y-1.5 text-xs text-ink">
                      <div>
                        🏆 <strong>综合实力优选:</strong> {data.verdict.winner_overall_name}
                      </div>
                      <div>
                        🚀 <strong>散户/小资金多号首选:</strong> {data.verdict.best_for_low_capital_name}
                      </div>
                      <div>
                        🐋 <strong>巨鲸大额稳健质押首选:</strong> {data.verdict.best_for_whale_staking_name}
                      </div>
                    </div>
                  </div>

                  <div className="p-3.5 rounded-xl bg-surface-2/60 border border-line space-y-1.5 text-xs text-ink-muted">
                    <div className="flex items-center gap-1.5 font-bold text-ink">
                      <Sparkles className="h-3.5 w-3.5 text-brand-400" />
                      <span>关键权衡对比</span>
                    </div>
                    {data.verdict.tradeoffs.map((t, idx) => (
                      <p key={idx} className="leading-relaxed text-ink-muted">
                        • {t}
                      </p>
                    ))}
                  </div>
                </div>
              </div>

              {/* 8 维指标表格 */}
              <div className="overflow-x-auto rounded-xl border border-line">
                <table className="w-full text-left text-xs">
                  <thead className="bg-surface-2 text-ink-muted border-b border-line">
                    <tr>
                      <th className="px-3.5 py-2.5 font-medium">对比维度</th>
                      <th className="px-3.5 py-2.5 font-medium">定义说明</th>
                      {data.projects.map((p) => (
                        <th key={p.id} className="px-3.5 py-2.5 font-medium font-bold text-ink">
                          {p.name}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-line">
                    {data.radar_axes.map((axis) => {
                      const maxVal = Math.max(...Object.values(axis.values));
                      return (
                        <tr key={axis.key} className="hover:bg-surface-2/40 transition">
                          <td className="px-3.5 py-2.5 font-medium text-ink">{axis.name}</td>
                          <td className="px-3.5 py-2.5 text-ink-muted">{axis.description}</td>
                          {data.projects.map((p) => {
                            const val = axis.values[p.id];
                            const isWin = val === maxVal;
                            return (
                              <td key={p.id} className="px-3.5 py-2.5 font-mono">
                                <span className={isWin ? 'font-bold text-emerald-400' : 'text-ink-muted'}>
                                  {val}
                                </span>
                                {isWin && <span className="ml-1 text-[10px] text-emerald-400">★</span>}
                              </td>
                            );
                          })}
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </div>

        {/* Footer */}
        <div className="pt-3 border-t border-line flex justify-end">
          <button
            type="button"
            onClick={onClose}
            className="btn-secondary text-xs px-4 py-1.5"
          >
            关闭
          </button>
        </div>
      </div>
    </div>
  );
}
