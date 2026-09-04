'use client';

import { LabelDoughnut, SectorBars } from '@/components/Charts';
import { TopBar } from '@/components/TopBar';
import { EmptyState, LabelBadge, SectionTitle, StatCard } from '@/components/ui';
import { apiFetch, isAbortError } from '@/lib/api';
import { LABEL_ORDER, LABEL_ZH, riskLevelZh } from '@/lib/format';
import { fetchAllProjects } from '@/lib/projects';
import type { InsightsData, Label, Project } from '@/lib/types';
import { useAsyncData } from '@/lib/useAsyncData';
import { AlertCircle, ArrowRight, CheckCircle2, ClipboardCheck, Download, Server, Shuffle, TrendingDown, TrendingUp } from 'lucide-react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useCallback, useEffect, useMemo, useState } from 'react';

/** 后端 /llm/status 返回的接口数据 */
interface LLMProviderStatus {
  name: string;
  base_url: string;
  api_key_masked: string;
  has_api_key: boolean;
  models: string[];
  model_count: number;
}

interface LLMStatus {
  enabled: boolean;
  provider_count: number;
  total_model_count: number;
  /** 轮询一圈的候选组合数（provider × model），ADR-016 */
  candidate_count?: number;
  /** 选择策略：每次调用从哪个组合开始。当前是 round_robin */
  selection_strategy?: string;
  /** 失败策略：这一次调用里遇到失败怎么走。当前是 provider_aware */
  failover_strategy: string;
  /** 人类可读的策略说明 */
  strategy_note?: string;
  providers: LLMProviderStatus[];
  temperature: number;
  max_tokens: number;
  daily_budget_usd: number;
  /** 当日（UTC）累计估算花费。账本读不出来时为 null，不是 0 */
  spend_today_usd?: number | null;
  calls_today?: number | null;
  /** 账本读取失败原因。非空表示预算按 fail-closed 拒绝调用 */
  ledger_error?: string | null;
  discovery_score_threshold: number;
}

function normalizeSectors(
  raw: InsightsData['sector_counts'] | undefined,
  fallback: { name: string; count: number }[],
): { name: string; count: number }[] {
  if (!raw) return fallback;
  if (Array.isArray(raw)) {
    return raw
      .map((item) => {
        if (Array.isArray(item)) return { name: String(item[0]), count: Number(item[1]) || 0 };
        const o = item as { sector?: string; count?: number; name?: string };
        return { name: String(o.sector || o.name || '未知'), count: Number(o.count) || 0 };
      })
      .filter((s) => s.count > 0)
      .sort((a, b) => b.count - a.count);
  }
  return Object.entries(raw)
    .map(([name, count]) => ({ name, count: Number(count) || 0 }))
    .sort((a, b) => b.count - a.count);
}

/**
 * ── Flag 中文化 + 正/负信号分色 ──
 *
 * 真值来源是后端 `app/agents/team.py` 的 `FLAG_ADJUSTMENTS`：那里每个 flag 都带
 * 一个正负分数调整，正负号决定了它是好信号还是坏信号。
 *
 * 这里此前漏了 `wash-trading VC`（后端给的是 **-0.20**，明确的负面信号）。
 * 漏掉的后果不是"少显示一个"，而是**显示成中性灰 + 英文原文** ——
 * 一个扣分项被渲染得像无关紧要的补充说明。
 *
 * `backend/tests/api/test_insights.py` 里有一条断言把这张表和后端
 * `FLAG_ADJUSTMENTS` 钉在一起：后端加新 flag 而这里没跟上，CI 会红。
 */
const FLAG_ZH: Record<string, string> = {
  'anonymous team': '匿名团队',
  'previous failed project': '历史失败项目',
  'wash-trading VC': '刷量 VC',
  'doxxed team': '已公开团队',
  'recent funding': '近期融资',
  'tier-1 vc backed': '一线 VC 投资',
  'reputable vc backed': '知名 VC 投资',
  'successful prior exit': '过往成功退出',
};

const POSITIVE_FLAGS = new Set([
  'doxxed team',
  'recent funding',
  'tier-1 vc backed',
  'reputable vc backed',
  'successful prior exit',
]);

const NEGATIVE_FLAGS = new Set([
  'anonymous team',
  'previous failed project',
  'wash-trading VC',
]);

function flagLabel(flag: string): string {
  return FLAG_ZH[flag] || flag;
}

function flagClass(flag: string): string {
  if (POSITIVE_FLAGS.has(flag)) return 'flag-chip-positive';
  if (NEGATIVE_FLAGS.has(flag)) return 'flag-chip-negative';
  return 'flag-chip-neutral';
}

/**
 * 「高风险团队」列表右侧徽章的配色。
 *
 * 这个列表实测返回 **270 条**，其中 `high` 只有 71 条、`medium` 有 199 条 ——
 * 也就是说 **74% 的条目是「中」**。此前徽章一律写死红底红字，于是四分之三的
 * 中风险项目被渲染成和高风险一模一样的红色警告。
 *
 * **同一种视觉强度代表两种严重程度，等于把分级取消掉了**：用户看到满屏红色，
 * 要么全都当真（于是把 199 个中风险当高危处理），要么全都不当真（于是漏掉
 * 真正的 71 个）。两种反应都比不分色更糟。
 *
 * 分档真值是后端 `app/agents/team.py::score_to_risk_level`（<0.4 high /
 * 0.4–0.7 medium / >0.7 low）。本端点只会返回 high 与 medium 两档
 * （low 不算「高风险团队」，不进这个列表），所以这里只需覆盖这两个 ——
 * 但仍保留 default 分支，后端将来放宽档位时会显示成中性灰而不是消失。
 */
function riskBadgeClass(level: string): string {
  if (level === 'high') return 'bg-red-50 text-red-700 dark:bg-red-500/15 dark:text-red-300';
  if (level === 'medium')
    return 'bg-amber-50 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300';
  return 'bg-slate-100 text-slate-600 dark:bg-slate-500/15 dark:text-slate-300';
}

/** 导出洞察为 CSV */
function exportInsightsCSV(projects: Project[], insights: InsightsData | null) {
  const rows: string[][] = [];
  // 表头
  rows.push(['项目名', '赛道', '标签', '分数', '置信度']);

  // 项目数据
  for (const p of projects) {
    rows.push([
      p.name ?? '',
      p.sector ?? '',
      LABEL_ZH[p.label as Label] ?? p.label ?? '',
      p.score != null ? String(p.score) : '',
      p.confidence != null ? String(p.confidence) : '',
    ]);
  }

  // 空行分隔
  rows.push([]);

  // 聚合数据
  rows.push(['— 聚合洞察 —']);
  rows.push(['项目总数', String(projects.length)]);
  if (insights) {
    rows.push(['标签分布', JSON.stringify(insights.label_counts || {})]);
    rows.push(['赛道分布', JSON.stringify(insights.sector_counts || {})]);
    if (insights.hottest_narratives?.length) {
      rows.push([]);
      rows.push(['— 最热叙事 —']);
      rows.push(['赛道', '项目数', '平均热度', '趋势']);
      for (const n of insights.hottest_narratives) {
        rows.push([
          n.sector,
          String(n.project_count),
          String(n.avg_heat_score),
          (n as Record<string, unknown>).trend as string || 'flat',
        ]);
      }
    }
    if (insights.risky_teams?.length) {
      rows.push([]);
      rows.push(['— 高风险团队 —']);
      rows.push(['项目名', '赛道', '风险等级', '团队分数', '标记']);
      for (const t of insights.risky_teams) {
        const flags = ((t as Record<string, unknown>).flags as string[] | undefined) ?? [];
        rows.push([
          t.name,
          t.sector,
          riskLevelZh(String(t.risk_level ?? '')),
          String(t.team_score ?? ''),
          flags.map(flagLabel).join('; '),
        ]);
      }
    }
  }

  // 下载
  const csv = '\uFEFF' + rows.map((r) => r.map((c) => `"${String(c).replace(/"/g, '""')}"`).join(',')).join('\n');
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `insights-${new Date().toISOString().slice(0, 10)}.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

export default function InsightsPage() {
  const [llmStatus, setLlmStatus] = useState<LLMStatus | null>(null);

  // 拉取 LLM 多接口状态（非阻塞，不影响页面主数据）
  useEffect(() => {
    const ac = new AbortController();
    apiFetch<LLMStatus>('/llm/status', { signal: ac.signal })
      .then(setLlmStatus)
      .catch((err) => {
        if (!isAbortError(err)) setLlmStatus(null);
      });
    return () => ac.abort();
  }, []);

  const loader = useCallback(
    async (signal: AbortSignal) => {
      const [all, i] = await Promise.all([
        fetchAllProjects(signal),
        apiFetch<InsightsData>('/insights', { signal }),
      ]);
      return {
        projects: [...all.projects].sort((a, b) => (b.score ?? 0) - (a.score ?? 0)),
        insights: i,
      };
    },
    [],
  );

  // useAsyncData 负责取消旧请求并丢弃过期响应，连点"刷新"不再出现旧数据覆盖新数据
  const { data, error, loading, reload: load } = useAsyncData(loader, []);
  const router = useRouter();
  const projects: Project[] = data?.projects ?? [];
  const insights: InsightsData | null = data?.insights ?? null;

  const labelCounts = useMemo(() => {
    const counts: Record<Label, number> = { FARM: 0, WATCH: 0, IGNORE: 0 };
    projects.forEach((p) => {
      if (p.label in counts) counts[p.label as Label] += 1;
    });
    return counts;
  }, [projects]);

  const sectorList = useMemo(() => {
    const fromProjects = Object.entries(
      projects.reduce<Record<string, number>>((acc, p) => {
        if (!p.sector) return acc;
        acc[p.sector] = (acc[p.sector] || 0) + 1;
        return acc;
      }, {}),
    )
      .map(([name, count]) => ({ name, count }))
      .sort((a, b) => b.count - a.count);
    return normalizeSectors(insights?.sector_counts, fromProjects);
  }, [projects, insights]);

  const topFarm = useMemo(() => projects.filter((p) => p.label === 'FARM').slice(0, 10), [projects]);
  const topWatch = useMemo(
    () => projects.filter((p) => p.label === 'WATCH').slice(0, 8),
    [projects],
  );

  if (loading) {
    return (
      <>
        <TopBar title="洞察" subtitle="标签分布 · 赛道热度 · 风险团队 · 机会榜" />
        <div className="app-content space-y-4 animate-fade-in">
          <div className="skeleton h-8 w-48" />
          <div className="grid gap-4 md:grid-cols-2">
            <div className="skeleton h-64" />
            <div className="skeleton h-64" />
          </div>
        </div>
      </>
    );
  }

  return (
    <>
      <TopBar title="洞察" subtitle="标签分布 · 赛道热度 · 风险团队 · 机会榜">
        <button type="button" className="btn-secondary inline-flex items-center gap-1.5" onClick={load} disabled={loading}>
          {loading ? '加载中…' : '刷新'}
        </button>
        <button type="button" className="btn-secondary inline-flex items-center gap-1.5" onClick={() => exportInsightsCSV(projects, insights)}>
          <Download className="h-4 w-4" strokeWidth={2} />
          <span className="hidden sm:inline">导出洞察</span>
        </button>
        <button type="button" className="btn-primary inline-flex items-center gap-1.5" onClick={() => router.push('/portfolio')}>
          <ClipboardCheck className="h-4 w-4" strokeWidth={2} />
          <span className="hidden sm:inline">查看复盘</span>
        </button>
      </TopBar>

    <div className="app-content space-y-6 animate-fade-in">

      {error ? (
        <div className="dash-card flex items-center justify-between gap-3 border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:bg-red-500/10 dark:text-red-300">
          <span>{error}</span>
          <button type="button" className="underline" onClick={load}>
            重试
          </button>
        </div>
      ) : null}

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatCard label="项目总数" value={projects.length} accent="brand" />
        {LABEL_ORDER.map((l) => (
          <StatCard
            key={l}
            label={LABEL_ZH[l]}
            value={labelCounts[l]}
            accent={l === 'FARM' ? 'farm' : l === 'WATCH' ? 'watch' : 'ignore'}
          />
        ))}
      </div>

      {/* LLM 引擎状态卡片 */}
      {llmStatus && (
        <div className="ins-llm-card">
          <div className="ins-llm-head">
            <div className="ins-llm-titles">
              <span className="ins-llm-name">
                <Shuffle className="h-4 w-4" strokeWidth={2} />
                LLM 多接口轮询
              </span>
              {/* 后端把「选择策略」与「失败策略」拆成两个字段（ADR-016）。
                  这里优先展示 strategy_note —— 一个英文枚举值（round_robin）
                  对运维没有信息量，读不出「多 worker 下不保证全局均衡」。
                  strategy_note 缺失时退回旧字段，兼容未升级的后端。 */}
              <span className="ins-llm-strategy">
                {llmStatus.strategy_note || llmStatus.failover_strategy}
              </span>
            </div>
            <span className={`ins-llm-badge ${llmStatus.enabled ? 'ok' : 'off'}`}>
              {llmStatus.enabled ? (
                <><CheckCircle2 className="h-3 w-3" strokeWidth={2} /> 已启用</>
              ) : (
                <><AlertCircle className="h-3 w-3" strokeWidth={2} /> 规则引擎</>
              )}
            </span>
          </div>
          <div className="ins-llm-stats">
            <div className="ins-llm-stat">
              <span className="ins-llm-stat-val">{llmStatus.provider_count}</span>
              <span className="ins-llm-stat-label">接口</span>
            </div>
            <div className="ins-llm-stat">
              <span className="ins-llm-stat-val">{llmStatus.total_model_count}</span>
              <span className="ins-llm-stat-label">模型</span>
            </div>
            <div className="ins-llm-stat">
              <span className="ins-llm-stat-val">{llmStatus.temperature}</span>
              <span className="ins-llm-stat-label">采样温度</span>
            </div>
            <div className="ins-llm-stat">
              <span className="ins-llm-stat-val">${llmStatus.daily_budget_usd}</span>
              <span className="ins-llm-stat-label">日预算</span>
            </div>
            {/* 只显示上限看不出余量。今日已用与上限并排，超预算时一眼可见。
                账本读不出来时显示 —— 而不是 0：坏掉的账本不该看起来像"还没花钱"。 */}
            <div className="ins-llm-stat">
              <span className="ins-llm-stat-val">
                {llmStatus.ledger_error || llmStatus.spend_today_usd == null
                  ? '—'
                  : `$${llmStatus.spend_today_usd.toFixed(4)}`}
              </span>
              <span className="ins-llm-stat-label">今日已用</span>
            </div>
          </div>
          <div className="ins-llm-providers">
            {llmStatus.providers.map((p, i) => (
              <div className="ins-llm-provider-row" key={i}>
                <div className="ins-llm-provider-info">
                  <Server className="h-3 w-3 shrink-0 text-ink-faint" strokeWidth={2} />
                  <span className="ins-llm-provider-name">接口{i + 1}</span>
                  <span className="ins-llm-provider-url">{p.base_url}</span>
                  {p.has_api_key && (
                    <span className="ins-llm-provider-key">{p.api_key_masked}</span>
                  )}
                </div>
                <div className="ins-llm-provider-models">
                  {p.models.map((m, j) => (
                    <span key={j} className="ins-llm-model-chip">{m}</span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
        <div className="ins-card lg:col-span-4">
          <SectionTitle title="标签占比" />
          <LabelDoughnut counts={labelCounts} />
          <div className="mt-4 space-y-2">
            {LABEL_ORDER.map((l) => {
              const n = labelCounts[l];
              const pct = projects.length ? Math.round((n / projects.length) * 100) : 0;
              return (
                <div key={l} className="flex items-center justify-between text-sm">
                  <LabelBadge label={l} />
                  <span className="tabular-nums text-ink-muted">
                    {n} · {pct}%
                  </span>
                </div>
              );
            })}
          </div>
        </div>

        <div className="ins-card lg:col-span-8">
          <SectionTitle title="赛道分布" />
          <SectorBars sectors={sectorList} />
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className="ins-card">
          <SectionTitle
            title="重点参与榜"
            action={
              <Link href="/" className="text-xs text-farm hover:underline dark:text-farm">
                返回工作台
              </Link>
            }
          />
          {topFarm.length === 0 ? (
            <EmptyState title="暂无重点参与项目" description="跑一轮采集评分后再来" />
          ) : (
            <div className="space-y-2">
              {topFarm.map((p, i) => (
                <Link
                  key={p.id}
                  href={`/project/${p.id}`}
                  className="flex items-center justify-between rounded-md border border-line px-3 py-2.5 transition hover:border-farm/40 hover:bg-farm-soft/30 dark:hover:bg-farm/10"
                >
                  <div className="flex min-w-0 items-center gap-3">
                    <span className="w-5 font-mono text-xs text-ink-faint">{i + 1}</span>
                    <div className="min-w-0">
                      <div className="truncate text-sm font-medium text-ink">{p.name}</div>
                      <div className="text-xs text-ink-faint">{p.sector}</div>
                    </div>
                  </div>
                  <span className="text-sm font-bold tabular-nums text-farm dark:text-farm">
                    {p.score}
                  </span>
                </Link>
              ))}
            </div>
          )}
        </div>

        <div className="ins-card">
          <SectionTitle title="观察列表精选" />
          {topWatch.length === 0 ? (
            <p className="py-8 text-center text-sm text-ink-faint">暂无观察中的项目</p>
          ) : (
            <div className="space-y-2">
              {topWatch.map((p) => (
                <Link
                  key={p.id}
                  href={`/project/${p.id}`}
                  className="flex items-center justify-between rounded-md border border-line px-3 py-2.5 transition hover:bg-surface-2"
                >
                  <div className="min-w-0">
                    <div className="truncate text-sm font-medium text-ink">{p.name}</div>
                    <div className="text-xs text-ink-faint">{p.sector}</div>
                  </div>
                  <div className="flex items-center gap-2">
                    <LabelBadge label={p.label} />
                    <span className="text-sm font-semibold tabular-nums">{p.score}</span>
                  </div>
                </Link>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className="ins-card">
          <SectionTitle title="最热叙事" />
          {(insights?.hottest_narratives || []).length === 0 ? (
            <p className="py-8 text-center text-sm text-ink-faint">暂无叙事热度数据</p>
          ) : (
            <div className="space-y-3">
              {insights!.hottest_narratives.map((n) => {
                const trend = (n as Record<string, unknown>).trend as string | undefined;
                const TrendIcon = trend === 'up' ? TrendingUp : trend === 'down' ? TrendingDown : ArrowRight;
                const trendColor = trend === 'up' ? 'text-farm' : trend === 'down' ? 'text-red-500' : 'text-ink-faint';
                return (
                  <div key={n.sector}>
                    <div className="mb-1 flex items-center justify-between text-sm">
                      <span className="flex items-center gap-1.5 font-medium text-ink">
                        {n.sector}
                        <TrendIcon className={`h-3.5 w-3.5 ${trendColor}`} strokeWidth={2} />
                      </span>
                      <span className="text-xs text-ink-muted">
                        热度 {Number(n.avg_heat_score).toFixed(2)} · {n.project_count} 个项目
                      </span>
                    </div>
                    <div className="h-1.5 overflow-hidden rounded-full bg-surface-3">
                      <div
                        className="h-full rounded-full bg-gradient-to-r from-farm to-farm-dark"
                        style={{ width: `${Math.min(100, Number(n.avg_heat_score) * 100)}%` }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        <div className="ins-card">
          <SectionTitle title="高风险团队" />
          {(insights?.risky_teams || []).length === 0 ? (
            <p className="py-8 text-center text-sm text-ink-faint">暂无高风险团队标记</p>
          ) : (
            <div className="space-y-2">
              {insights!.risky_teams.slice(0, 10).map((t) => {
                // 后端恒定返回 flags 数组（缺标记时为空数组），这里不编造兜底内容。
                // 曾经写的兜底是 ['匿名团队', '无公开仓库'] —— 一旦后端某天不发这个键，
                // 界面就会替后端凭空断言「这个团队是匿名的、没有公开仓库」。
                // 其中 '无公开仓库' 后端根本不存在这个 flag。
                // **编造一个看起来合理的默认值，比留空危险得多**：读者无法分辨
                // 「系统查到了这两条」和「系统什么都没查到」。
                const flags = ((t as Record<string, unknown>).flags as string[] | undefined) ?? [];
                const level = String(t.risk_level ?? '');
                return (
                  <Link
                    key={t.id}
                    href={`/project/${t.id}`}
                    className="flex items-center justify-between rounded-md border border-line px-3 py-2.5 transition hover:border-red-300/50 hover:bg-red-50/50 dark:hover:bg-red-500/10"
                  >
                    <div className="min-w-0">
                      <div className="truncate text-sm font-medium text-ink">{t.name}</div>
                      <div className="text-xs text-ink-faint">{t.sector}</div>
                      {flags.length > 0 && (
                        <div className="mt-1 flex flex-wrap gap-1">
                          {flags.map((f) => (
                            <span key={f} className={`flag-chip ${flagClass(f)}`}>
                              {flagLabel(f)}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                    <span className={`badge flex-shrink-0 ${riskBadgeClass(level)}`}>
                      {riskLevelZh(level)}
                    </span>
                  </Link>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
    </>
  );
}
