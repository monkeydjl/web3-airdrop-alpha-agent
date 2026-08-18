'use client';

import { TopBar } from '@/components/TopBar';
import { LabelBadge } from '@/components/ui';
import Link from 'next/link';
import { Download, Plus } from 'lucide-react';

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

/** 标签 × 结果校准矩阵（mock） */
const MATRIX: MatrixRow[] = [
  {
    label: 'FARM',
    total: 23,
    segments: [
      { count: 8, pct: 34.8, color: 'var(--state-success)', title: '空投成功 8' },
      { count: 2, pct: 8.7, color: 'var(--label-ignore)', title: '未空投 2' },
      { count: 3, pct: 13.0, color: 'var(--state-info)', title: '上涨 3' },
      { count: 10, pct: 43.5, color: 'var(--alpha-300)', title: '进行中 10' },
    ],
    hitRate: 62,
    color: 'var(--label-farm)',
  },
  {
    label: 'WATCH',
    total: 18,
    segments: [
      { count: 2, pct: 11.1, color: 'var(--state-success)', title: '空投成功 2' },
      { count: 6, pct: 33.3, color: 'var(--label-ignore)', title: '未空投 6' },
      { count: 2, pct: 11.1, color: 'var(--state-info)', title: '上涨 2' },
      { count: 1, pct: 5.6, color: 'var(--state-error)', title: '下跌 1' },
      { count: 7, pct: 38.9, color: 'var(--alpha-300)', title: '进行中 7' },
    ],
    hitRate: 18,
    color: 'var(--label-watch)',
  },
  {
    label: 'IGNORE',
    total: 12,
    segments: [
      { count: 9, pct: 75.0, color: 'var(--label-ignore)', title: '未空投 9' },
      { count: 1, pct: 8.3, color: 'var(--state-error)', title: '下跌 1' },
      { count: 2, pct: 16.7, color: 'var(--alpha-300)', title: '进行中 2' },
    ],
    hitRate: 8,
    color: 'var(--label-ignore)',
  },
];

/** SVG 命中率环：r=17，周长 = 2π·17 ≈ 106.8 */
const RING_CIRCUMFERENCE = 2 * Math.PI * 17;

/** 结果分布（by_outcome，mock） */
const OUTCOMES = [
  { name: 'airdropped', count: 10, pct: 53, fillClass: 'is-success' },
  { name: 'not_airdropped', count: 17, pct: 89, fillClass: 'is-ignore' },
  { name: 'pumped', count: 5, pct: 26, fillClass: 'is-info' },
  { name: 'dumped', count: 2, pct: 11, fillClass: 'is-error' },
  { name: '进行中', count: 19, pct: 100, fillClass: 'is-warning' },
];

/** 状态分布（by_status，mock） */
const STATUSES = [
  { name: 'planned', count: 6, pct: 29, opacity: 1 },
  { name: 'active', count: 9, pct: 43, opacity: 0.75 },
  { name: 'done', count: 21, pct: 100, opacity: 0.55 },
  { name: 'abandoned', count: 4, pct: 19, opacity: 0.4 },
];

interface ParticipationRecord {
  id: number;
  project: string;
  label: Label;
  outcome: string;
  cost: string;
  gain: string;
  hours: string;
  date: string;
}

/** 最近参与记录（mock） */
const RECORDS: ParticipationRecord[] = [
  { id: 1, project: 'Zephyr Protocol', label: 'FARM', outcome: 'airdropped', cost: '$120', gain: '+$890', hours: '6.5h', date: '2025-07-28' },
  { id: 2, project: 'Nova Protocol', label: 'FARM', outcome: '进行中', cost: '$80', gain: '—', hours: '4.0h', date: '2025-07-25' },
  { id: 3, project: 'Poly Oracle', label: 'WATCH', outcome: 'pumped', cost: '$50', gain: '+$320', hours: '3.5h', date: '2025-07-20' },
  { id: 4, project: 'Kite Network', label: 'WATCH', outcome: 'not_airdropped', cost: '$40', gain: '$0', hours: '2.0h', date: '2025-07-15' },
  { id: 5, project: 'Echo Social', label: 'IGNORE', outcome: 'dumped', cost: '$10', gain: '-$5', hours: '1.0h', date: '2025-07-10' },
];

export default function PortfolioPage() {
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
            <span className="pf-kpi-value">34</span>
            <span className="pf-kpi-caption">进行中 9 · 已完成 21 · 已放弃 4</span>
          </div>
          <div className="pf-kpi">
            <span className="pf-kpi-label">净收益</span>
            <span className="pf-kpi-value is-positive">+$12,480</span>
            <span className="pf-kpi-caption">收益率 384%</span>
          </div>
          <div className="pf-kpi">
            <span className="pf-kpi-label">总成本</span>
            <span className="pf-kpi-value">$3,250</span>
            <span className="pf-kpi-caption">硬成本 + Gas</span>
          </div>
          <div className="pf-kpi">
            <span className="pf-kpi-label">总工时</span>
            <span className="pf-kpi-value">186h</span>
            <span className="pf-kpi-caption">平均 5.5h / 项目</span>
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
              {MATRIX.map((row) => {
                const dash = (row.hitRate / 100) * RING_CIRCUMFERENCE;
                return (
                  <div className="pf-mx-row" key={row.label}>
                    <div className="pf-mx-head">
                      <LabelBadge label={row.label} />
                      <span className="pf-mx-total">{row.total} 项</span>
                    </div>
                    <div className="pf-mx-track" role="img" aria-label={`${row.label} 各结果分布`}>
                      {row.segments.map((seg) => (
                        <span
                          key={seg.title}
                          className="pf-mx-seg"
                          style={{ width: `${seg.pct}%`, background: seg.color }}
                          title={seg.title}
                        />
                      ))}
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
              <strong>FARM 命中率 62%</strong> · WATCH 18% · IGNORE 8% — 标签区分度健康
            </p>
          </div>
        </section>

        {/* 3. 双栏分布行 */}
        <div className="pf-dist-grid">
          {/* 结果分布 */}
          <section className="pf-card" aria-label="结果分布">
            <div className="pf-card-head">
              <h2 className="pf-card-title">结果分布</h2>
              <p className="pf-card-caption">by_outcome · 53 条交互记录</p>
            </div>
            <div className="pf-card-body pf-bars">
              {OUTCOMES.map((o) => (
                <div className="pf-bar-row" key={o.name}>
                  <span className={`pf-bar-name ${/^[a-z]/.test(o.name) ? 'is-mono' : ''}`}>
                    {o.name}
                  </span>
                  <span className="pf-bar-count">{o.count}</span>
                  <span className="pf-bar-track">
                    <span className={`pf-bar-fill ${o.fillClass}`} style={{ width: `${o.pct}%` }} />
                  </span>
                </div>
              ))}
              <p className="pf-dist-foot">终态：airdropped / not_airdropped / pumped / dumped · 进行中为可变态</p>
            </div>
          </section>

          {/* 状态分布 */}
          <section className="pf-card" aria-label="状态分布">
            <div className="pf-card-head">
              <h2 className="pf-card-title">状态分布</h2>
              <p className="pf-card-caption">by_status · 40 条管线项目</p>
            </div>
            <div className="pf-card-body pf-bars">
              {STATUSES.map((s) => (
                <div className="pf-bar-row" key={s.name}>
                  <span className="pf-bar-name is-mono">{s.name}</span>
                  <span className="pf-bar-count">{s.count}</span>
                  <span className="pf-bar-track">
                    <span
                      className="pf-bar-fill"
                      style={{ width: `${s.pct}%`, opacity: s.opacity }}
                    />
                  </span>
                </div>
              ))}
              <p className="pf-dist-foot">状态机：planned → active → done/abandoned，终态不可变</p>
            </div>
          </section>
        </div>

        {/* 4. 参与记录表 */}
        <section className="pf-card overflow-hidden" aria-label="参与记录">
          <div className="pf-card-head">
            <h2 className="pf-card-title">参与记录</h2>
            <p className="pf-card-caption">最近 5 条 · 总 34 条</p>
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
                {RECORDS.map((r) => (
                  <tr key={r.id} className="border-b border-line last:border-b-0 hover:bg-surface-2">
                    <td className="px-4 py-3 sm:px-5">
                      <Link
                        href={`/project/${r.project.toLowerCase().replace(/\s+/g, '-')}`}
                        className="text-sm font-medium text-ink hover:text-farm"
                      >
                        {r.project}
                      </Link>
                    </td>
                    <td className="px-3 py-3">
                      <LabelBadge label={r.label} />
                    </td>
                    <td className="px-3 py-3 text-xs text-ink-muted">{r.outcome}</td>
                    <td className="px-3 py-3 font-mono text-xs">{r.cost}</td>
                    <td
                      className="px-3 py-3 font-mono text-xs"
                      style={{
                        color: r.gain.startsWith('+')
                          ? 'rgb(var(--farm))'
                          : r.gain.startsWith('-')
                            ? 'var(--state-error)'
                            : undefined,
                      }}
                    >
                      {r.gain}
                    </td>
                    <td className="px-3 py-3 font-mono text-xs text-ink-muted">{r.hours}</td>
                    <td className="px-4 py-3 sm:px-5 font-mono text-xs text-ink-muted">{r.date}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </>
  );
}
