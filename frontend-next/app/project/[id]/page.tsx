'use client';

import { AiBriefPanel } from '@/components/AiBriefPanel';
import { FundingPanel } from '@/components/FundingPanel';
import { InteractionPanel } from '@/components/InteractionPanel';
import { OpportunityWorkflowPanel } from '@/components/OpportunityWorkflowPanel';
import { ParticipationTasks } from '@/components/ParticipationTasks';
import { TopBar } from '@/components/TopBar';
import { LabelBadge, ProgressBar, Toast } from '@/components/ui';
import { apiFetch, isAbortError } from '@/lib/api';
import { ArrowLeft, Plus } from 'lucide-react';
import {
  formatPct,
  lifecycleStageZh,
  relativeTime,
  riskLevelZh,
  safeExternalUrl,
  sourceZh,
  stageZh,
  teamTypeZh,
  timingZh,
} from '@/lib/format';
import type { Project } from '@/lib/types';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { useCallback, useEffect, useRef, useState } from 'react';

const SIGNALS = [
  { id: 'useful', label: '有用' },
  { id: 'useless', label: '没用' },
  { id: 'wrong_label', label: '标签错了' },
  { id: 'correct_outcome', label: '结果对上了' },
] as const;

const OUTCOMES = [
  { id: '', label: '先不标' },
  { id: 'airdropped', label: '已空投' },
  { id: 'not_airdropped', label: '未空投' },
  { id: 'pumped', label: '拉升' },
  { id: 'dumped', label: '下跌' },
] as const;

const SIGNAL_CHECKS: { key: string; label: string }[] = [
  { key: 'has_testnet', label: '测试网' },
  { key: 'has_points_program', label: '积分计划' },
  { key: 'no_token_yet', label: '未发币' },
  { key: 'has_docs', label: '文档' },
  { key: 'has_github', label: 'GitHub' },
  { key: 'has_twitter', label: '社媒' },
];

/**
 * 8 个评分维度。
 *
 * 这里只保留维度顺序和中文口径，**权重不再写死** —— 原先每一项都带
 * `weight: '0.18'` 这样的字面量，而权重的真值在后端（`WEIGHT_*` 环境变量，
 * 启动时断言 Σ=1.0）。写死的那份不会跟着 .env 变，只会静默变成错的。
 * 现在权重从 `GET /settings/config` 的 `weights` 块按 `envKey` 取。
 */
const DIMENSIONS = [
  { id: 'airdrop_signal', label: '空投信号', envKey: 'WEIGHT_AIRDROP_SIGNAL' },
  { id: 'narrative_timing', label: '叙事时机', envKey: 'WEIGHT_NARRATIVE_TIMING' },
  { id: 'execution', label: '执行力', envKey: 'WEIGHT_EXECUTION' },
  { id: 'team_reputation', label: '团队声誉', envKey: 'WEIGHT_TEAM_REPUTATION' },
  { id: 'risk', label: '风险', envKey: 'WEIGHT_RISK' },
  { id: 'competition', label: '竞争格局', envKey: 'WEIGHT_COMPETITION' },
  { id: 'tokenomics', label: '代币经济学', envKey: 'WEIGHT_TOKENOMICS' },
  { id: 'transparency', label: '透明度', envKey: 'WEIGHT_TRANSPARENCY' },
] as const;

/** GET /settings/config 里本页真正用到的两块 */
interface RuntimeThresholds {
  weights?: Record<string, number | string>;
  thresholds?: Record<string, number>;
}

function num(v: unknown, fallback = 0): number {
  const n = typeof v === 'number' ? v : Number(v);
  return Number.isFinite(n) ? n : fallback;
}

function scoreTone(label?: string): string {
  if (label === 'FARM') return 'text-farm dark:text-farm';
  if (label === 'WATCH') return 'text-watch dark:text-watch';
  return 'text-ink-muted';
}

function Fact({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[5.5rem_1fr] gap-2 text-[12.5px] leading-snug">
      <dt className="text-ink-muted font-normal">{label}</dt>
      <dd className="m-0 text-right font-medium text-ink tabular-nums break-words">{value ?? '—'}</dd>
    </div>
  );
}

function SecHead({ title, meta }: { title: string; meta?: string }) {
  return (
    <div className="mb-3.5 flex items-baseline justify-between gap-3">
      <h2 className="m-0 font-mono text-[11px] font-semibold uppercase tracking-[0.08em] text-ink-muted">
        {title}
      </h2>
      {meta ? (
        <span className="font-mono text-[10px] tracking-wide text-ink-faint">{meta}</span>
      ) : null}
    </div>
  );
}

function ScoreRing({ score, label }: { score: number; label?: string }) {
  const color = label === 'FARM' ? 'var(--farm)' : label === 'WATCH' ? 'var(--watch)' : 'var(--ignore)';
  return (
    <div className="score-ring" style={{ '--score': score, '--ring': color, width: 112, height: 112 } as React.CSSProperties}>
      <div className="score-ring-inner">
        <div className="text-center">
          <div className="score-ring-value">{score}</div>
          <div className="text-[10px] uppercase tracking-wider text-ink-faint">综合分</div>
        </div>
      </div>
    </div>
  );
}

export default function ProjectPage() {
  const params = useParams<{ id: string }>();
  const projectId = params?.id ?? '';
  const [project, setProject] = useState<Project | null>(null);
  const [runtimeCfg, setRuntimeCfg] = useState<RuntimeThresholds | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [rescoring, setRescoring] = useState(false);
  const [feedbackSending, setFeedbackSending] = useState(false);
  const [selectedSignal, setSelectedSignal] = useState<string | null>(null);
  const [outcome, setOutcome] = useState('');
  const [note, setNote] = useState('');
  const [toast, setToast] = useState<{ message: string; type: 'success' | 'error' | 'info' } | null>(
    null,
  );

  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(
    () => () => {
      if (toastTimer.current) clearTimeout(toastTimer.current);
    },
    [],
  );
  const showToast = (message: string, type: 'success' | 'error' | 'info' = 'info') => {
    setToast({ message, type });
    if (toastTimer.current) clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(null), 3200);
  };

  const generation = useRef(0);
  const inflight = useRef<AbortController | null>(null);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      inflight.current?.abort();
    };
  }, []);

  const loadProject = useCallback(() => {
    if (!projectId) return;
    inflight.current?.abort();
    const ac = new AbortController();
    inflight.current = ac;
    const myGeneration = ++generation.current;

    setLoading(true);
    setError('');
    // 顺带拉一次运行时配置：8 维权重和 FARM/WATCH 阈值以前是写死在本文件里的
    // （见 DIMENSIONS 注释）。这一路失败不影响项目详情本身，所以单独 catch。
    //
    // 用 `/public-config` 而非 `/settings/config`：本页面向普通访客，而后者是
    // 管理员专属（回显哪些密钥已配、采集源地址、cron、LLM 预算）。前端代理
    // 已改为只给管理动作注入管理员密钥，继续打 /settings/config 会拿到 403。
    apiFetch<RuntimeThresholds>('/public-config', { signal: ac.signal })
      .then((cfg) => {
        if (!mounted.current || myGeneration !== generation.current) return;
        setRuntimeCfg(cfg ?? null);
      })
      .catch(() => {
        /* 配置拉不到就退回显示「—」，不编造数字 */
      });
    apiFetch<{ project: Project }>(`/projects/${projectId}`, { signal: ac.signal })
      .then((data) => {
        if (!mounted.current || myGeneration !== generation.current) return;
        if (!data?.project) throw new Error('项目数据为空或格式不正确');
        setProject(data.project);
      })
      .catch((err: unknown) => {
        if (isAbortError(err)) return;
        if (!mounted.current || myGeneration !== generation.current) return;
        setError(err instanceof Error ? err.message : '加载失败');
      })
      .finally(() => {
        if (!mounted.current || myGeneration !== generation.current) return;
        setLoading(false);
      });
  }, [projectId]);

  useEffect(() => {
    loadProject();
  }, [loadProject]);

  const rescore = async () => {
    if (!project) return;
    setRescoring(true);
    try {
      const data = await apiFetch<{
        score?: { score?: number; label?: string; error?: string } | null;
      }>(`/projects/${project.id}/funding?rescore=true`, {
        method: 'PATCH',
        body: JSON.stringify({}),
      });
      if (data.score?.error) {
        showToast(`重评失败：${data.score.error}`, 'error');
      } else {
        showToast(
          data.score?.score != null
            ? `重新评分完成：${data.score.score} · ${data.score.label || ''}`
            : '重新评分完成',
          'success',
        );
      }
      loadProject();
    } catch (err: unknown) {
      showToast(err instanceof Error ? err.message : '重新评分失败', 'error');
    } finally {
      setRescoring(false);
    }
  };

  const sendFeedback = async () => {
    if (!project) return;
    if (!selectedSignal) {
      showToast('请先选择一种反馈类型', 'error');
      return;
    }
    setFeedbackSending(true);
    try {
      await apiFetch('/feedback', {
        method: 'POST',
        body: JSON.stringify({
          project_id: project.id,
          signal: selectedSignal,
          note: note || undefined,
          outcome: outcome || undefined,
        }),
      });
      showToast('反馈已提交', 'success');
      setNote('');
      setSelectedSignal(null);
    } catch (err: unknown) {
      showToast(err instanceof Error ? err.message : '反馈提交失败', 'error');
    } finally {
      setFeedbackSending(false);
    }
  };

  if (loading) {
    return (
      <>
        <TopBar title="加载中…" subtitle="正在获取项目数据" />
        <div className="app-content animate-fade-in">
          <div className="mx-auto max-w-[1080px] space-y-4 py-2">
        <div className="skeleton h-3 w-24" />
        <div className="skeleton h-9 w-1/2" />
        <div className="skeleton h-4 w-2/5" />
        <div className="mt-8 grid gap-10 lg:grid-cols-[1fr_280px]">
          <div className="space-y-3">
            <div className="skeleton h-3 w-full" />
            <div className="skeleton h-3 w-5/6" />
            <div className="skeleton h-3 w-4/6" />
            <div className="skeleton mt-6 h-28 w-full" />
          </div>
          <div className="space-y-3">
            <div className="skeleton h-3 w-3/4" />
            <div className="skeleton h-20 w-full" />
          </div>
        </div>
          </div>
        </div>
      </>
    );
  }

  if (error) {
    return (
      <>
        <TopBar title="加载失败" subtitle={error} />
        <div className="app-content animate-fade-in">
          <div className="mx-auto max-w-lg border-t border-line py-12">
        <h1 className="text-xl font-semibold text-ink" style={{ lineHeight: 1.35 }}>
          加载失败
        </h1>
        <p className="mt-2 text-sm text-ink-muted" style={{ lineHeight: 1.65 }}>
          {error}
        </p>
        <div className="mt-4 flex gap-2">
          <button type="button" className="btn-primary" onClick={loadProject}>
            重试
          </button>
          <Link href="/" className="btn-secondary">
            回工作台
          </Link>
        </div>
          </div>
        </div>
      </>
    );
  }

  if (!project) {
    return (
      <>
        <TopBar title="未找到项目" subtitle="ID 无效或库中不存在" />
        <div className="app-content animate-fade-in">
          <div className="mx-auto max-w-lg border-t border-line py-12">
            <h1 className="text-xl font-semibold text-ink" style={{ lineHeight: 1.35 }}>
              没有这条项目
            </h1>
            <p className="mt-2 text-sm text-ink-muted">ID 无效或库中不存在。从工作台列表重新点开即可。</p>
            <Link href="/" className="btn-primary mt-4 inline-flex">
              回工作台
            </Link>
          </div>
        </div>
      </>
    );
  }

  const narrative = project.narrative || {};
  const team = project.team || {};
  const risk = project.risk || {};
  const tokenomics = project.tokenomics || {};
  const signals = (project.signals || {}) as Record<string, unknown>;
  const subScores = (project.sub_scores ?? {}) as Record<string, number>;
  const heat = num(narrative.heat_score);
  const teamScore = num(team.score ?? team.team_score, 0.5);
  const tokenRisk = num(risk.token_risk, 0.5);
  const conf = project.confidence ?? 0;
  const confPct = Math.round(conf * 100);
  const confWarn = conf < 0.5;
  const reasons = Array.isArray(project.reason) ? project.reason : [];
  const site = safeExternalUrl(project.url);
  const score = project.score ?? 0;
  const evalTime = project.updated_at
    ? new Date(project.updated_at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
    : '—';

  // 权重 / 标签阈值 / 权重版本一律来自后端，不再在本文件写死副本。
  // weight_version 优先取这条项目记录自己的值（它记录的是"当初用哪版权重打的分"），
  // 项目上没有时退到后端当前生效的版本，两者都没有才显示「—」。
  const runtimeWeights = (runtimeCfg?.weights ?? {}) as Record<string, number | string>;
  const cfgWeightVersion = runtimeWeights.weight_version;
  const weightVersion =
    project.weight_version ||
    (typeof cfgWeightVersion === 'string' ? cfgWeightVersion : '') ||
    '—';
  const farmThreshold = runtimeCfg?.thresholds?.LABEL_FARM_THRESHOLD;
  const watchThreshold = runtimeCfg?.thresholds?.LABEL_WATCH_THRESHOLD;

  // 后端真实字段名是 `team_flags`（`flags` 从不出现在 API 里）。
  // 保留 `flags` 作次选只为兼容任何旧形状。
  const teamFlags: string[] = Array.isArray(team.team_flags)
    ? (team.team_flags as string[])
    : Array.isArray(team.flags)
      ? (team.flags as string[])
      : [];

  // 解锁压力真实出在 `risk` 块（`RiskResult.unlock_pressure`）；tokenomics 块里
  // 只有 `unlock_penalty`（一个 0~1 的数）。此前「代币经济」那一格读
  // `tokenomics.unlock_pressure`，因此永远显示「—」；该格已删除，压力只在
  // 左侧「风险」面板显示一次。

  return (
    <>
      {toast ? <Toast message={toast.message} type={toast.type} /> : null}

      <TopBar
        title={project.name}
        subtitle={`${sourceZh(project.source)} · ${relativeTime(project.updated_at)}`}
      >
        <Link
          href="/"
          className="btn-secondary"
          aria-label="返回工作台"
        >
          <ArrowLeft className="h-4 w-4" strokeWidth={2} />
          <span className="hidden sm:inline">返回</span>
        </Link>
        <button
          type="button"
          className="btn-primary inline-flex items-center gap-1.5"
          onClick={() => {
            const el = document.getElementById('pd-participation');
            if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
          }}
        >
          <Plus className="h-4 w-4" strokeWidth={2} />
          <span className="hidden sm:inline">记录参与</span>
        </button>
      </TopBar>

    <div className="app-content animate-fade-in">
      <div className="mx-auto max-w-[1080px]">

      {/* masthead */}
      <header className="mb-9 grid gap-8 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-start">
        <div className="min-w-0">
          <p className="m-0 max-w-[52ch] text-sm text-ink-muted" style={{ lineHeight: 1.65 }}>
            {project.sector || '未分赛道'} · {stageZh(project.stage)}
            {project.funding?.funding_tier &&
            project.funding.funding_tier !== 'none' &&
            project.funding.funding_tier !== 'unknown'
              ? ` · 融资 ${project.funding.funding_tier}`
              : ''}
            {confWarn ? ' · 置信度偏低，先别重仓时间' : ''}
          </p>
          <div className="mt-3.5 flex flex-wrap items-center gap-x-2.5 gap-y-1.5 text-xs">
            <LabelBadge label={project.label} />
            <span className="font-mono text-[11px] font-medium tracking-wide text-ink-muted">
              score-v1.4
            </span>
            {confWarn ? (
              <span className="font-mono text-[11px] text-watch dark:text-watch">
                置信 {confPct}%
              </span>
            ) : null}
          </div>
          <div className="mt-4 flex flex-wrap items-center gap-2 pt-1">
            <button
              type="button"
              className="btn-primary min-h-9"
              onClick={rescore}
              disabled={rescoring}
            >
              {rescoring ? '评分中…' : '重新评分'}
            </button>
            {site ? (
              <a
                href={site}
                target="_blank"
                rel="noreferrer"
                className="px-1 py-2 text-[13px] text-ink-muted underline decoration-1 underline-offset-[3px] hover:text-ink"
              >
                官网
                <span className="sr-only">（新窗口）</span>
              </a>
            ) : null}
          </div>
        </div>

        <div className="flex flex-wrap items-end gap-x-7 gap-y-4 lg:flex-col lg:items-end lg:text-right">
          <div className="flex gap-7 lg:flex-col lg:gap-3.5">
            {/* 「排名」原先写死为 1（后端无排名接口），任何项目都显示"排名第 1"，
                属于误导信息 —— 直接不展示，改为展示真实的置信度 */}
            <div className="pd-mini-stat">
              <span className="pd-mini-value">评于 {evalTime}</span>
              <span className="pd-mini-label">权威引擎 score-v1.4</span>
            </div>
          </div>
          <ScoreRing score={score} label={project.label} />
          <div className="min-w-[140px] lg:w-36">
            <div className="mb-1.5 flex justify-between gap-3 font-mono text-[11px] tracking-wide text-ink-muted">
              <span>置信</span>
              <span>{formatPct(conf)}</span>
            </div>
            <div
              className="h-0.5 overflow-hidden bg-line"
              role="progressbar"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={confPct}
              aria-label="置信度"
            >
              <i
                className={`block h-full ${
                  project.label === 'FARM'
                    ? 'bg-farm'
                    : project.label === 'WATCH'
                      ? 'bg-watch'
                      : 'bg-ink'
                }`}
                style={{ width: `${confPct}%` }}
              />
            </div>
            {confWarn ? (
              <p className="mt-2 text-left text-[11px] leading-snug text-watch dark:text-watch lg:text-right">
                证据面不足，补信号后再加大投入。
              </p>
            ) : null}
          </div>
        </div>
      </header>

      {/* body */}
      <div className="grid gap-x-12 gap-y-8 lg:grid-cols-[minmax(0,1fr)_280px] lg:items-start">
        <div className="min-w-0 space-y-0">
          {/* reasons */}
          <section className="border-t border-line py-5 first:border-t-0 first:pt-0">
            <SecHead title="为何是这个标签" meta="权威主决策" />
            {reasons.length ? (
              <ol className="m-0 list-none space-y-0 p-0">
                {reasons.map((r, i) => (
                  <li
                    key={`${i}-${r}`}
                    className="grid grid-cols-[1.5rem_1fr] gap-2.5 border-b border-line py-2 text-sm last:border-b-0"
                    style={{ lineHeight: 1.55 }}
                  >
                    <span className="pt-0.5 font-mono text-[11px] font-semibold tracking-wide text-ink-faint">
                      {String(i + 1).padStart(2, '0')}
                    </span>
                    <span className="text-ink">{r}</span>
                  </li>
                ))}
              </ol>
            ) : (
              <p className="m-0 text-[13px] text-ink-muted">暂无写入的决策理由。</p>
            )}
          </section>

          {/* agents matrix */}
          <section className="border-t border-line py-5">
            <SecHead title="四路分析" meta="并行 Agent" />
            <div className="grid border-t border-line sm:grid-cols-2">
              <div className="border-b border-line py-3.5 sm:border-r sm:pr-5">
                <p className="mb-2.5 text-xs font-semibold text-ink">叙事</p>
                <dl className="m-0 space-y-1.5">
                  <Fact label="热度" value={heat ? heat.toFixed(2) : '—'} />
                  <div className="py-0.5" aria-hidden>
                    <ProgressBar value={heat} max={1} color="bg-ink" />
                  </div>
                  <Fact label="时机" value={timingZh(String(narrative.timing ?? ''))} />
                  <Fact
                    label="阶段"
                    /* 这里是叙事面板，「阶段」指赛道生命周期（early/growth/peak/mature），
                       与页头显示的部署阶段（testnet/mainnet/ideation）是两套词汇。
                       此前这里在 narrative.stage 缺失时兜底到 project.stage，
                       于是那 7 个没有叙事结果的项目会在生命周期这一格显示「主网」——
                       一个来自另一套口径、但看着完全合理的答案。缺就显示「—」。 */
                    value={lifecycleStageZh(String(narrative.stage ?? ''))}
                  />
                </dl>
              </div>
              <div className="border-b border-line py-3.5 sm:pl-5">
                <p className="mb-2.5 text-xs font-semibold text-ink">团队</p>
                <dl className="m-0 space-y-1.5">
                  <Fact label="得分" value={formatPct(teamScore)} />
                  <Fact label="风险" value={riskLevelZh(String(team.risk_level ?? ''))} />
                  <Fact label="身份" value={teamTypeZh(String(team.team_type ?? ''))} />
                  <Fact
                    label="风险标记"
                    value={
                      /* 后端字段名是 `team_flags`。此前这里读 `team.flags`，
                         而 API 从不返回这个键，所以这一行永远显示「无」——
                         哪怕项目确实带着「匿名团队」这样的风险标记。
                         保留 `flags` 作次选只为兼容任何旧形状。 */
                      teamFlags.length ? teamFlags.join(', ') : '无'
                    }
                  />
                </dl>
              </div>
              <div className="border-b border-line py-3.5 sm:border-b-0 sm:border-r sm:pr-5">
                <p className="mb-2.5 text-xs font-semibold text-ink">风险</p>
                <dl className="m-0 space-y-1.5">
                  <Fact label="女巫难度" value={riskLevelZh(String(risk.sybil_difficulty ?? ''))} />
                  <Fact label="交互成本" value={riskLevelZh(String(risk.farming_cost ?? ''))} />
                  <Fact label="解锁压力" value={riskLevelZh(String(risk.unlock_pressure ?? ''))} />
                  <Fact label="代币风险" value={tokenRisk.toFixed(2)} />
                </dl>
              </div>
              <div className="py-3.5 sm:border-b-0 sm:pl-5">
                <p className="mb-2.5 text-xs font-semibold text-ink">代币经济</p>
                <dl className="m-0 space-y-1.5">
                  <Fact
                    label="VC 份额"
                    value={
                      tokenomics.vc_share != null ? formatPct(num(tokenomics.vc_share)) : '—'
                    }
                  />
                  <Fact
                    label="团队份额"
                    value={
                      tokenomics.team_share != null ? formatPct(num(tokenomics.team_share)) : '—'
                    }
                  />
                  {/* 原先这里还有一行「解锁压力」读 `tokenomics.unlock_pressure`，
                      但该键只存在于 `risk` 块（已在左侧「风险」面板显示），
                      tokenomics 块里只有下面这个 unlock_penalty。
                      去掉后不再有一格永远显示「—」，也不与风险面板重复。 */}
                  <Fact
                    label="解锁惩罚"
                    value={
                      tokenomics.unlock_penalty != null
                        ? num(tokenomics.unlock_penalty).toFixed(2)
                        : '—'
                    }
                  />
                </dl>
              </div>
            </div>
          </section>

          {/* 8 dim scores */}
          <section className="border-t border-line py-5">
            <SecHead title="8 维子分" meta={weightVersion} />
            <div className="pd-dims">
              {DIMENSIONS.map((dim) => {
                const val = subScores[dim.id] ?? 0;
                const pct = Math.round(val);
                const fillClass = val >= 80 ? '' : val >= 65 ? 'pd-fill-70' : 'pd-fill-45';
                const w = runtimeWeights[dim.envKey];
                return (
                  <div className="pd-dim" key={dim.id}>
                    <span className="pd-dim-name">{dim.label}</span>
                    {/* 权重来自后端；拿不到就显示「×—」，不回落到写死的旧值 */}
                    <span className="pd-dim-weight">
                      ×{typeof w === 'number' ? w.toFixed(2) : '—'}
                    </span>
                    <div className="pd-dim-bar">
                      <div className={`pd-dim-bar-fill ${fillClass}`} style={{ width: `${pct}%` }} />
                    </div>
                    <span className="pd-dim-value">{val}</span>
                  </div>
                );
              })}
            </div>
            <p className="mt-3 text-xs text-ink-faint">
              {/* FARM/WATCH 分档以前写死成「FARM≥65 / WATCH≥50」。这两个数已经调过
                  一次（v1.1 把 FARM 从 70 降到 65），写死就意味着下次再调时这行会
                  静默变成错的。现在读后端 thresholds 块的真值。 */}
              <span className="font-mono">{weightVersion}</span> · 阈值 FARM≥
              {farmThreshold ?? '—'} / WATCH≥{watchThreshold ?? '—'}
            </p>
          </section>

          {/* signals */}
          <section className="border-t border-line py-5">
            <SecHead title="可核验信号" />
            <div className="grid gap-x-6 sm:grid-cols-2">
              {SIGNAL_CHECKS.map(({ key, label }) => {
                const on = Boolean(signals[key]);
                return (
                  <div
                    key={key}
                    className="flex items-baseline justify-between gap-3 border-b border-line py-2 text-[13px]"
                  >
                    <span className="text-ink-muted">{label}</span>
                    <span
                      className={`font-mono text-[11px] font-semibold tracking-wide ${
                        on ? 'text-farm dark:text-farm' : 'text-ink-faint'
                      }`}
                    >
                      {on ? '有' : '无'}
                    </span>
                  </div>
                );
              })}
            </div>
          </section>

          {/* participation */}
          <section id="pd-participation" className="border-t border-line py-5">
            <SecHead title="参与清单" />
            <ParticipationTasks projectId={project.id} />
          </section>

          {/* opportunity */}
          <section className="border-t border-line py-5">
            <SecHead title="Opportunity 行动流" meta="非权威旁路" />
            <OpportunityWorkflowPanel projectId={project.id} />
          </section>

          {/* AI brief */}
          <section className="border-t border-line py-5">
            <SecHead title="简报" meta="规则 / 可选 LLM" />
            <AiBriefPanel projectId={project.id} autoLoad />
          </section>

          {/* funding */}
          <section className="border-t border-line py-5">
            <SecHead title="融资" meta="可编辑 → 重评" />
            <FundingPanel
              projectId={project.id}
              initialFunding={project.funding}
              initialNote={project.funding_note}
              onSaved={loadProject}
            />
          </section>

          {/* interactions */}
          <section className="border-t border-line py-5">
            <SecHead title="我的投入" />
            <InteractionPanel projectId={project.id} />
          </section>

          {/* feedback */}
          <section className="border-t border-line py-5">
            <SecHead title="校正这条判断" meta="进入校准样本" />
            <p className="mb-3 text-[13px] text-ink-muted" style={{ lineHeight: 1.55 }}>
              样本累计足够后可跑权重校准。先选类型，再可选填事后结果与备注。
            </p>
            <div className="flex flex-wrap gap-1.5" role="group" aria-label="反馈类型">
              {SIGNALS.map((s) => {
                const on = selectedSignal === s.id;
                return (
                  <button
                    key={s.id}
                    type="button"
                    aria-pressed={on}
                    disabled={feedbackSending}
                    onClick={() => setSelectedSignal(on ? null : s.id)}
                    className={`min-h-8 rounded-sm border px-2.5 text-xs font-medium tracking-wide transition ${
                      on
                        ? 'border-ink bg-surface-2 text-ink'
                        : 'border-line bg-transparent text-ink-muted hover:border-line hover:bg-surface-2 hover:text-ink'
                    }`}
                  >
                    {s.label}
                  </button>
                );
              })}
            </div>
            <div className="mt-3.5 grid gap-3 sm:grid-cols-[12rem_1fr]">
              <select
                className="select"
                value={outcome}
                onChange={(e) => setOutcome(e.target.value)}
                aria-label="事后结果"
              >
                {OUTCOMES.map((o) => (
                  <option key={o.id || 'none'} value={o.id}>
                    {o.label}
                  </option>
                ))}
              </select>
              <input
                className="input"
                placeholder="可选：哪里判断偏了"
                value={note}
                maxLength={500}
                onChange={(e) => setNote(e.target.value)}
                aria-label="备注"
              />
            </div>
            <p className="mt-1 font-mono text-[10px] tracking-wide text-ink-faint">
              {note.length} / 500
            </p>
            <button
              type="button"
              className="btn-secondary mt-3 min-h-8 text-xs"
              disabled={feedbackSending}
              onClick={sendFeedback}
            >
              {feedbackSending ? '提交中…' : '提交反馈'}
            </button>
          </section>
        </div>

        {/* rail — sticky summary on desktop */}
        <aside className="min-w-0 border-t border-line pt-5 lg:sticky lg:top-[calc(3.5rem+1rem)] lg:self-start lg:border-t-0 lg:pt-0">
          <div className="space-y-5">
            <div className="border-b border-line pb-5">
              <h3 className="mb-3 font-mono text-[11px] font-semibold uppercase tracking-[0.08em] text-ink-muted">
                摘要
              </h3>
              <dl className="m-0 space-y-0">
                <div className="flex justify-between gap-3 border-b border-line/70 py-1.5 text-[12.5px]">
                  <dt className="text-ink-muted">标签</dt>
                  <dd className="m-0">
                    <LabelBadge label={project.label} />
                  </dd>
                </div>
                <div className="flex justify-between gap-3 border-b border-line/70 py-1.5 text-[12.5px]">
                  <dt className="text-ink-muted">分数</dt>
                  <dd className={`m-0 font-mono font-semibold tabular-nums ${scoreTone(project.label)}`}>
                    {score}
                  </dd>
                </div>
                <div className="flex justify-between gap-3 border-b border-line/70 py-1.5 text-[12.5px]">
                  <dt className="text-ink-muted">置信</dt>
                  <dd className="m-0 font-mono tabular-nums">{formatPct(conf)}</dd>
                </div>
                <div className="flex justify-between gap-3 border-b border-line/70 py-1.5 text-[12.5px]">
                  <dt className="text-ink-muted">赛道</dt>
                  <dd className="m-0 max-w-[58%] text-right font-medium break-words">
                    {project.sector || '—'}
                  </dd>
                </div>
                <div className="flex justify-between gap-3 py-1.5 text-[12.5px]">
                  <dt className="text-ink-muted">来源</dt>
                  <dd className="m-0 font-medium">{sourceZh(project.source)}</dd>
                </div>
              </dl>
              <p className="mt-3 text-[12px] leading-relaxed text-ink-muted">
                {project.name} / {project.sector || '—'} / {stageZh(project.stage)}。分 {score}，
                {project.label}。
                {reasons[0] ? `${reasons[0]}。` : ''}
                置信 {formatPct(conf)}
                {confWarn ? '，证据偏薄。' : '。'}
              </p>
            </div>

            <div>
              <h3 className="mb-2 font-mono text-[11px] font-semibold uppercase tracking-[0.08em] text-ink-muted">
                编号
              </h3>
              <p className="m-0 break-all font-mono text-[11px] text-ink-faint">{project.id}</p>
              <p className="mt-2 text-[11px] text-ink-faint">
                更新 {relativeTime(project.updated_at)}
              </p>
            </div>
          </div>
        </aside>
      </div>
    </div>
    </div>
    </>
  );
}
