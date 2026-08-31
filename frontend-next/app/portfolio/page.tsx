'use client';

import { RoiLedger } from '@/components/RoiLedger';
import { TopBar } from '@/components/TopBar';
import { EmptyState, LabelBadge } from '@/components/ui';
import { apiFetch } from '@/lib/api';
import { relativeTime } from '@/lib/format';
import { Download, Plus } from 'lucide-react';
import Link from 'next/link';
import { useCallback, useEffect, useMemo, useState } from 'react';

type Label = 'FARM' | 'WATCH' | 'IGNORE';

interface Segment {
  count: number;
  pct: number;
  color: string;
  title: string;
}

interface MatrixRow {
  label: Label;
  total: number;
  segments: Segment[];
  hitRate: number;
  color: string;
}

interface Summary {
  total?: number;
  by_status?: Record<string, number>;
  by_outcome?: Record<string, number>;
  label_outcome_matrix?: { label_at_start: string; outcome: string; c: number }[];
  total_cost_usd?: number;
  total_profit_usd?: number;
  net_usd?: number;
  total_hours?: number;
}

interface InteractionItem {
  id: number;
  project_id: string;
  status?: string;
  outcome?: string;
  cost_usd?: number;
  profit_usd?: number;
  net_usd?: number;
  hours_spent?: number;
  started_at?: string;
  created_at?: string;
  label_at_start?: string;
}

interface InteractionsList {
  items?: InteractionItem[];
  total?: number;
}

/** SVG 命中率环：r=17，周长 = 2π·17 ≈ 106.8 */
const RING_CIRCUMFERENCE = 2 * Math.PI * 17;

const LABEL_COLOR: Record<string, string> = {
  FARM: 'var(--label-farm)',
  WATCH: 'var(--label-watch)',
  IGNORE: 'var(--label-ignore)',
};

const OUTCOME_COLOR: Record<string, string> = {
  airdropped: 'var(--state-success)',
  not_airdropped: 'var(--label-ignore)',
  profit: 'var(--state-info)',
  loss: 'var(--state-error)',
  breakeven: 'var(--alpha-300)',
  pending: 'var(--alpha-300)',
  unknown: 'var(--alpha-300)',
};

const OUTCOME_LABEL: Record<string, string> = {
  airdropped: '空投成功',
  not_airdropped: '未空投',
  profit: '上涨',
  loss: '下跌',
  breakeven: '持平',
  pending: '进行中',
  unknown: '未知',
};

const STATUS_LABEL: Record<string, string> = {
  planned: 'planned',
  active: 'active',
  done: 'done',
  abandoned: 'abandoned',
};

/** 命中率：FARM/WATCH 标签下 outcome=airdropped 或 profit 的比例 */
function computeHitRate(rows: { label_at_start: string; outcome: string; c: number }[], label: string): number {
  const subset = rows.filter((r) => r.label_at_start === label);
  const total = subset.reduce((s, r) => s + r.c, 0);
  if (total === 0) return 0;
  const hits = subset
    .filter((r) => r.outcome === 'airdropped' || r.outcome === 'profit')
    .reduce((s, r) => s + r.c, 0);
  return Math.round((hits / total) * 100);
}

function buildMatrix(
  matrix: { label_at_start: string; outcome: string; c: number }[],
): MatrixRow[] {
  const labels: Label[] = ['FARM', 'WATCH', 'IGNORE'];
  return labels.map((label) => {
    const subset = matrix.filter((r) => r.label_at_start === label);
    const total = subset.reduce((s, r) => s + r.c, 0);
    const segments: Segment[] = subset.map((r) => {
      const pct = total > 0 ? Math.round((r.c / total) * 1000) / 10 : 0;
      return {
        count: r.c,
        pct,
        color: OUTCOME_COLOR[r.outcome] || 'var(--alpha-300)',
        title: `${OUTCOME_LABEL[r.outcome] || r.outcome} ${r.c}`,
      };
    });
    return {
      label,
      total,
      segments,
      hitRate: computeHitRate(matrix, label),
      color: LABEL_COLOR[label] || 'var(--alpha-300)',
    };
  });
}

function fmtMoney(v: number | undefined | null): string {
  if (v == null) return '—';
  const sign = v > 0 ? '+' : '';
  return `${sign}$${Math.round(v).toLocaleString()}`;
}

function fmtCost(v: number | undefined | null): string {
  if (v == null) return '—';
  return `$${Math.round(v).toLocaleString()}`;
}

function fmtHours(v: number | undefined | null): string {
  if (v == null) return '—';
  return `${v}h`;
}

export default function PortfolioPage() {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [interactions, setInteractions] = useState<InteractionItem[]>([]);
  const [projectNames, setProjectNames] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [sum, list] = await Promise.all([
        apiFetch<Summary>('/interactions/summary'),
        apiFetch<InteractionsList>('/interactions?limit=5'),
      ]);
      setSummary(sum ?? null);
      setInteractions(list?.items ?? []);

      // 批量取项目名
      const pids = (list?.items ?? [])
        .map((i) => i.project_id)
        .filter((pid, idx, arr) => pid && arr.indexOf(pid) === idx);
      if (pids.length > 0) {
        const names: Record<string, string> = {};
        await Promise.all(
          pids.map(async (pid) => {
            try {
              const p = await apiFetch<{ name?: string } | { data?: { name?: string } }>(
                `/projects?project_id=${encodeURIComponent(pid)}`,
              );
              const name = (p as { name?: string }).name || (p as { data?: { name?: string } }).data?.name;
              if (name) names[pid] = name;
              else names[pid] = pid.slice(0, 8);
            } catch {
              names[pid] = pid.slice(0, 8);
            }
          }),
        );
        setProjectNames(names);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const matrix = useMemo(
    () => buildMatrix(summary?.label_outcome_matrix ?? []),
    [summary],
  );

  const outcomes = useMemo(() => {
    const raw = summary?.by_outcome ?? {};
    return Object.entries(raw).map(([name, count]) => ({
      name,
      count,
      label: OUTCOME_LABEL[name] || name,
      color: OUTCOME_COLOR[name] || 'var(--alpha-300)',
    }));
  }, [summary]);

  const maxOutcome = Math.max(1, ...outcomes.map((o) => o.count));

  const statuses = useMemo(() => {
    const raw = summary?.by_status ?? {};
    return Object.entries(raw).map(([name, count]) => ({
      name: STATUS_LABEL[name] || name,
      count,
    }));
  }, [summary]);

  const maxStatus = Math.max(1, ...statuses.map((s) => s.count));

  const totalInter = summary?.total ?? 0;
  const byStatus = summary?.by_status ?? {};
  const totalCost = summary?.total_cost_usd ?? 0;
  const totalProfit = summary?.total_profit_usd ?? 0;
  const netUsd = summary?.net_usd ?? totalProfit - totalCost;
  const totalHours = summary?.total_hours ?? 0;
  const activeCount = (byStatus.active ?? 0) + (byStatus.planned ?? 0);
  const doneCount = byStatus.done ?? 0;
  const abandonedCount = byStatus.abandoned ?? 0;
  const avgHours = totalInter > 0 ? (totalHours / totalInter).toFixed(1) : '—';
  const roi = totalCost > 0 ? Math.round((netUsd / totalCost) * 100) : 0;

  if (loading) {
    return (
      <>
        <TopBar title="参与复盘" subtitle="标签校准 · 收益分析 · 工时统计">
          <button type="button" className="btn-secondary inline-flex items-center gap-1.5">
            <Plus className="h-4 w-4" strokeWidth={2} />
            <span className="hidden sm:inline">新建记录</span>
          </button>
        </TopBar>
        <div className="app-content flex items-center justify-center py-20">
          <span className="text-sm text-ink-muted">加载中…</span>
        </div>
      </>
    );
  }

  if (error) {
    return (
      <>
        <TopBar title="参与复盘" subtitle="标签校准 · 收益分析 · 工时统计">
          <button type="button" className="btn-secondary inline-flex items-center gap-1.5">
            <Plus className="h-4 w-4" strokeWidth={2} />
            <span className="hidden sm:inline">新建记录</span>
          </button>
        </TopBar>
        <div className="app-content py-20">
          <EmptyState title="加载失败" description={error} />
        </div>
      </>
    );
  }

  if (totalInter === 0) {
    return (
      <>
        <TopBar title="参与复盘" subtitle="标签校准 · 收益分析 · 工时统计">
          <button type="button" className="btn-secondary inline-flex items-center gap-1.5">
            <Plus className="h-4 w-4" strokeWidth={2} />
            <span className="hidden sm:inline">新建记录</span>
          </button>
        </TopBar>
        <div className="app-content space-y-5 py-10">
          <EmptyState
            title="还没有参与记录"
            description="在项目详情页点击「我的投入」添加第一条交互记录，这里会自动汇总校准矩阵和收益分析。"
          />
          {/* 台账独立于 interactions：没有参与记录时也要能录第一笔投入，
              否则空态会把台账入口一起藏掉。 */}
          <RoiLedger projectNames={projectNames} />
        </div>
      </>
    );
  }

  return (
    <>
      <TopBar title="参与复盘" subtitle="标签校准 · 收益分析 · 工时统计">
        <button type="button" className="btn-secondary inline-flex items-center gap-1.5">
          <Download className="h-4 w-4" strokeWidth={2} />
          <span className="hidden sm:inline">导出记录</span>
        </button>
        <button type="button" className="btn-primary inline-flex items-center gap-1.5">
          <Plus className="h-4 w-4" strokeWidth={2} />
          <span className="hidden sm:inline">新建记录</span>
        </button>
      </TopBar>

      <div className="app-content space-y-5 animate-fade-in">
        {/* 1. KPI 汇总 */}
        <div className="pf-kpi-grid">
          <div className="pf-kpi">
            <span className="pf-kpi-label">总参与</span>
            <span className="pf-kpi-value">{totalInter}</span>
            <span className="pf-kpi-caption">
              进行中 {activeCount} · 已完成 {doneCount} · 已放弃 {abandonedCount}
            </span>
          </div>
          <div className="pf-kpi">
            <span className="pf-kpi-label">净收益</span>
            <span
              className="pf-kpi-value"
              style={{ color: netUsd >= 0 ? 'rgb(var(--farm))' : 'var(--state-error)' }}
            >
              {fmtMoney(netUsd)}
            </span>
            <span className="pf-kpi-caption">收益率 {roi}%</span>
          </div>
          <div className="pf-kpi">
            <span className="pf-kpi-label">总成本</span>
            <span className="pf-kpi-value">{fmtCost(totalCost)}</span>
            <span className="pf-kpi-caption">硬成本 + Gas</span>
          </div>
          <div className="pf-kpi">
            <span className="pf-kpi-label">总工时</span>
            <span className="pf-kpi-value">{fmtHours(totalHours)}</span>
            <span className="pf-kpi-caption">平均 {avgHours}h / 项目</span>
          </div>
        </div>

        {/* 2. 标签 × 结果校准矩阵 */}
        <section className="pf-card" aria-label="标签结果校准矩阵">
          <div className="pf-card-head">
            <h2 className="pf-card-title">标签 × 结果校准矩阵</h2>
            <p className="pf-card-caption">score-v1.4 标签在实际结果上的命中率 · 权重校准核心输入</p>
          </div>
          <div className="pf-mx-legend">
            <span className="pf-mx-legend-item">
              <span className="pf-mx-dot" style={{ background: 'var(--state-success)' }} />
              空投成功
            </span>
            <span className="pf-mx-legend-item">
              <span className="pf-mx-dot" style={{ background: 'var(--label-ignore)' }} />
              未空投
            </span>
            <span className="pf-mx-legend-item">
              <span className="pf-mx-dot" style={{ background: 'var(--state-info)' }} />
              上涨
            </span>
            <span className="pf-mx-legend-item">
              <span className="pf-mx-dot" style={{ background: 'var(--state-error)' }} />
              下跌
            </span>
            <span className="pf-mx-legend-item">
              <span className="pf-mx-dot" style={{ background: 'var(--alpha-300)' }} />
              进行中
            </span>
          </div>
          <div className="pf-card-body">
            <div className="pf-mx">
              {matrix.map((row) => {
                const dash = (row.hitRate / 100) * RING_CIRCUMFERENCE;
                return (
                  <div className="pf-mx-row" key={row.label}>
                    <div className="pf-mx-head">
                      <LabelBadge label={row.label} />
                      <span className="pf-mx-total">{row.total} 项</span>
                    </div>
                    <div className="pf-mx-track" role="img" aria-label={`${row.label} 各结果分布`}>
                      {row.segments.length === 0 ? (
                        <span className="pf-mx-seg" style={{ width: '100%', background: 'var(--border)' }} title="无数据" />
                      ) : (
                        row.segments.map((seg) => (
                          <span
                            key={seg.title}
                            className="pf-mx-seg"
                            style={{ width: `${seg.pct}%`, background: seg.color }}
                            title={seg.title}
                          />
                        ))
                      )}
                    </div>
                    <div className="pf-mx-side">
                      <svg width="46" height="46" viewBox="0 0 46 46" aria-hidden="true">
                        <circle cx="23" cy="23" r="17" fill="none" stroke="var(--border)" strokeWidth="4" />
                        <circle
                          cx="23"
                          cy="23"
                          r="17"
                          fill="none"
                          stroke={row.color}
                          strokeWidth="4"
                          strokeLinecap="round"
                          strokeDasharray={`${dash} ${RING_CIRCUMFERENCE - dash}`}
                          transform="rotate(-90 23 23)"
                        />
                        <text
                          x="23"
                          y="23"
                          textAnchor="middle"
                          dominantBaseline="central"
                          className="pf-mx-ring-text"
                        >
                          {row.hitRate}%
                        </text>
                      </svg>
                      <span className="pf-mx-rate-note">命中率</span>
                    </div>
                  </div>
                );
              })}
            </div>
            <p className="pf-matrix-foot">
              <strong>FARM 命中率 {matrix[0]?.hitRate ?? 0}%</strong> · WATCH {matrix[1]?.hitRate ?? 0}% · IGNORE {matrix[2]?.hitRate ?? 0}% — 标签区分度健康
            </p>
          </div>
        </section>

        {/* 3. 双栏分布行 */}
        <div className="pf-dist-grid">
          {/* 结果分布 */}
          <section className="pf-card" aria-label="结果分布">
            <div className="pf-card-head">
              <h2 className="pf-card-title">结果分布</h2>
              <p className="pf-card-caption">by_outcome · {totalInter} 条交互记录</p>
            </div>
            <div className="pf-card-body pf-bars">
              {outcomes.length === 0 ? (
                <p className="text-xs text-ink-muted">暂无数据</p>
              ) : (
                outcomes.map((o) => (
                  <div className="pf-bar-row" key={o.name}>
                    <span className={`pf-bar-name ${/^[a-z]/.test(o.name) ? 'is-mono' : ''}`}>
                      {o.label}
                    </span>
                    <span className="pf-bar-count">{o.count}</span>
                    <span className="pf-bar-track">
                      <span
                        className="pf-bar-fill is-success"
                        style={{ width: `${(o.count / maxOutcome) * 100}%`, background: o.color }}
                      />
                    </span>
                  </div>
                ))
              )}
              <p className="pf-dist-foot">终态：airdropped / not_airdropped / profit / loss · pending 为可变态</p>
            </div>
          </section>

          {/* 状态分布 */}
          <section className="pf-card" aria-label="状态分布">
            <div className="pf-card-head">
              <h2 className="pf-card-title">状态分布</h2>
              <p className="pf-card-caption">by_status · {totalInter} 条交互记录</p>
            </div>
            <div className="pf-card-body pf-bars">
              {statuses.length === 0 ? (
                <p className="text-xs text-ink-muted">暂无数据</p>
              ) : (
                statuses.map((s) => (
                  <div className="pf-bar-row" key={s.name}>
                    <span className="pf-bar-name is-mono">{s.name}</span>
                    <span className="pf-bar-count">{s.count}</span>
                    <span className="pf-bar-track">
                      <span
                        className="pf-bar-fill"
                        style={{ width: `${(s.count / maxStatus) * 100}%` }}
                      />
                    </span>
                  </div>
                ))
              )}
              <p className="pf-dist-foot">状态机：planned → active → done/abandoned，终态不可变</p>
            </div>
          </section>
        </div>

        {/* 4. 参与记录表 */}
        <section className="pf-card overflow-hidden" aria-label="参与记录">
          <div className="pf-card-head">
            <h2 className="pf-card-title">参与记录</h2>
            <p className="pf-card-caption">最近 {interactions.length} 条 · 总 {totalInter} 条</p>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px] text-left text-sm">
              <thead className="border-b border-line bg-surface-2/50">
                <tr className="font-mono text-[10px] font-semibold uppercase tracking-wider text-ink-muted">
                  <th className="px-4 py-2.5 sm:px-5">项目</th>
                  <th className="px-3 py-2.5">标签</th>
                  <th className="px-3 py-2.5">结果</th>
                  <th className="px-3 py-2.5">成本</th>
                  <th className="px-3 py-2.5">收益</th>
                  <th className="px-3 py-2.5">工时</th>
                  <th className="px-4 py-2.5 sm:px-5">日期</th>
                </tr>
              </thead>
              <tbody>
                {interactions.map((r) => {
                  const name = projectNames[r.project_id] || r.project_id.slice(0, 8);
                  const label = (r.label_at_start || '') as Label;
                  const profit = r.profit_usd ?? null;
                  const net = r.net_usd ?? null;
                  return (
                    <tr key={r.id} className="border-b border-line last:border-b-0 hover:bg-surface-2">
                      <td className="px-4 py-3 sm:px-5">
                        <Link
                          href={`/project/${r.project_id}`}
                          className="text-sm font-medium text-ink hover:text-farm"
                        >
                          {name}
                        </Link>
                      </td>
                      <td className="px-3 py-3">
                        {label ? <LabelBadge label={label} /> : <span className="text-xs text-ink-faint">—</span>}
                      </td>
                      <td className="px-3 py-3 text-xs text-ink-muted">
                        {OUTCOME_LABEL[r.outcome || ''] || r.outcome || '—'}
                      </td>
                      <td className="px-3 py-3 font-mono text-xs">{fmtCost(r.cost_usd)}</td>
                      <td
                        className="px-3 py-3 font-mono text-xs"
                        style={{
                          color:
                            net != null && net > 0
                              ? 'rgb(var(--farm))'
                              : net != null && net < 0
                                ? 'var(--state-error)'
                                : undefined,
                        }}
                      >
                        {net != null ? fmtMoney(net) : fmtMoney(profit)}
                      </td>
                      <td className="px-3 py-3 font-mono text-xs text-ink-muted">{fmtHours(r.hours_spent)}</td>
                      <td className="px-4 py-3 sm:px-5 font-mono text-xs text-ink-muted">
                        {r.started_at || (r.created_at ? relativeTime(r.created_at) : '—')}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>

        {/* 5. 收益台账（F3）—— 与上方 interactions 是两套数据，见组件注释 */}
        <RoiLedger projectNames={projectNames} />
      </div>
    </>
  );
}
