'use client';

import { AiBriefPanel } from '@/components/AiBriefPanel';
import { FundingPanel } from '@/components/FundingPanel';
import { InteractionPanel } from '@/components/InteractionPanel';
import { ParticipationTasks } from '@/components/ParticipationTasks';
import {
  ConfidenceBar,
  LabelBadge,
  ProgressBar,
  ReasonChips,
  ScoreRing,
  Toast,
} from '@/components/ui';
import { apiFetch } from '@/lib/api';
import {
  formatPct,
  relativeTime,
  riskLevelZh,
  sourceZh,
  stageZh,
  teamTypeZh,
  timingZh,
} from '@/lib/format';
import type { Project } from '@/lib/types';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { useCallback, useEffect, useState } from 'react';

const SIGNALS = [
  { id: 'useful', label: '👍 有用', hint: 'useful' },
  { id: 'useless', label: '👎 无用', hint: 'useless' },
  { id: 'wrong_label', label: '🏷 标签错误', hint: 'wrong_label' },
  { id: 'correct_outcome', label: '✓ 结果正确', hint: 'correct_outcome' },
] as const;

const OUTCOMES = [
  { id: '', label: '事后结果（可选）' },
  { id: 'airdropped', label: '已空投' },
  { id: 'not_airdropped', label: '未空投' },
  { id: 'pumped', label: '拉盘' },
  { id: 'dumped', label: '砸盘' },
] as const;

function num(v: unknown, fallback = 0): number {
  const n = typeof v === 'number' ? v : Number(v);
  return Number.isFinite(n) ? n : fallback;
}

function AgentPanel({
  title,
  accent,
  children,
  defaultOpen = true,
}: {
  title: string;
  accent: string;
  children: React.ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="card overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between px-4 py-3 text-left hover:bg-surface-2/50"
      >
        <div className="flex items-center gap-2">
          <span className={`h-2 w-2 rounded-full ${accent}`} />
          <span className="text-sm font-semibold text-ink">{title}</span>
        </div>
        <span className="text-xs text-ink-faint">{open ? '收起' : '展开'}</span>
      </button>
      {open ? <div className="border-t border-line px-4 py-4">{children}</div> : null}
    </div>
  );
}

function Field({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-3 py-1.5 text-sm">
      <span className="text-ink-muted">{label}</span>
      <span className="max-w-[60%] text-right font-medium text-ink break-all">{value ?? '—'}</span>
    </div>
  );
}

export default function ProjectPage() {
  const params = useParams<{ id: string }>();
  const projectId = params?.id ?? '';
  const [project, setProject] = useState<Project | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [rescoring, setRescoring] = useState(false);
  const [feedbackSending, setFeedbackSending] = useState(false);
  const [outcome, setOutcome] = useState('');
  const [note, setNote] = useState('');
  const [toast, setToast] = useState<{ message: string; type: 'success' | 'error' | 'info' } | null>(
    null,
  );

  const showToast = (message: string, type: 'success' | 'error' | 'info' = 'info') => {
    setToast({ message, type });
    setTimeout(() => setToast(null), 3200);
  };

  const loadProject = useCallback(() => {
    if (!projectId) return;
    setLoading(true);
    setError('');
    apiFetch<{ project: Project }>(`/projects/${projectId}`)
      .then((data) => {
        if (!data?.project) throw new Error('项目数据为空或格式不正确');
        setProject(data.project);
      })
      .catch((err) => setError(err.message || '加载失败'))
      .finally(() => setLoading(false));
  }, [projectId]);

  useEffect(() => {
    loadProject();
  }, [loadProject]);

  const rescore = async () => {
    if (!project) return;
    setRescoring(true);
    try {
      // 用已存 meta.signals（含融资）重评，避免 /run 丢信号
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

  const sendFeedback = async (signal: string) => {
    if (!project) return;
    setFeedbackSending(true);
    try {
      await apiFetch('/feedback', {
        method: 'POST',
        body: JSON.stringify({
          project_id: project.id,
          signal,
          note: note || undefined,
          outcome: outcome || undefined,
        }),
      });
      showToast(`反馈已提交：${signal}`, 'success');
      setNote('');
    } catch (err: unknown) {
      showToast(err instanceof Error ? err.message : '反馈提交失败', 'error');
    } finally {
      setFeedbackSending(false);
    }
  };

  if (loading) {
    return (
      <div className="space-y-4 animate-fade-in">
        <div className="skeleton h-4 w-32" />
        <div className="card p-6">
          <div className="skeleton mb-3 h-8 w-1/2" />
          <div className="skeleton h-4 w-1/3" />
        </div>
        <div className="grid gap-4 md:grid-cols-2">
          <div className="skeleton h-40" />
          <div className="skeleton h-40" />
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="card mx-auto max-w-lg p-8 text-center">
        <p className="text-red-600 dark:text-red-300">加载失败：{error}</p>
        <button type="button" className="btn-primary mt-4" onClick={loadProject}>
          重试
        </button>
      </div>
    );
  }

  if (!project) {
    return <div className="py-16 text-center text-ink-muted">未找到项目</div>;
  }

  const narrative = project.narrative || {};
  const team = project.team || {};
  const risk = project.risk || {};
  const tokenomics = project.tokenomics || {};
  const heat = num(narrative.heat_score);
  const teamScore = num(team.score ?? team.team_score, 0.5);
  const tokenRisk = num(risk.token_risk, 0.5);
  const conf = project.confidence ?? 0;

  return (
    <div className="space-y-6 animate-fade-in">
      {toast ? <Toast message={toast.message} type={toast.type} /> : null}

      <div className="flex flex-wrap items-center gap-2 text-sm text-ink-muted">
        <Link href="/" className="hover:text-brand-600 dark:hover:text-brand-300">
          ← 工作台
        </Link>
        <span className="text-ink-faint">/</span>
        <span className="text-ink">{project.name}</span>
      </div>

      {/* hero */}
      <div className="card overflow-hidden">
        <div className="border-b border-line bg-gradient-to-r from-brand-500/10 via-transparent to-farm/5 px-5 py-5 sm:px-6">
          <div className="flex flex-col gap-6 lg:flex-row lg:items-center lg:justify-between">
            <div className="min-w-0 flex-1">
              <div className="mb-3 flex flex-wrap items-center gap-2">
                <LabelBadge label={project.label} />
                {project.sector ? (
                  <span className="badge bg-surface-3 text-ink-muted">{project.sector}</span>
                ) : null}
                {project.stage ? (
                  <span className="badge bg-surface-3 text-ink-muted">{stageZh(project.stage)}</span>
                ) : null}
                {project.source ? (
                  <span className="badge bg-brand-50 text-brand-700 dark:bg-brand-500/15 dark:text-brand-300">
                    {sourceZh(project.source)}
                  </span>
                ) : null}
              </div>
              <h1 className="text-2xl font-bold tracking-tight text-ink sm:text-3xl">{project.name}</h1>
              {project.url ? (
                <a
                  href={project.url}
                  target="_blank"
                  rel="noreferrer"
                  className="mt-1 inline-block text-sm text-brand-600 hover:underline dark:text-brand-300"
                >
                  {project.url}
                </a>
              ) : (
                <p className="mt-1 text-sm text-ink-faint">无官网链接</p>
              )}
              <p className="mt-2 text-xs text-ink-faint">
                更新于 {relativeTime(project.updated_at)} · 编号{' '}
                <span className="font-mono">{project.id.slice(0, 8)}…</span>
              </p>
            </div>

            <div className="flex flex-wrap items-center gap-6">
              <ScoreRing score={project.score ?? 0} size={112} label={project.label} />
              <div className="w-44 space-y-3">
                <ConfidenceBar value={conf} />
                {conf < 0.5 ? (
                  <p className="text-xs text-watch-dark dark:text-watch">⚠ 置信度偏低，建议复核 Agent 输出</p>
                ) : null}
                <button type="button" className="btn-primary w-full" onClick={rescore} disabled={rescoring}>
                  {rescoring ? '评分中…' : '↻ 重新评分'}
                </button>
              </div>
            </div>
          </div>
        </div>

        <div className="px-5 py-4 sm:px-6">
          <h2 className="mb-2 text-xs font-semibold tracking-wider text-ink-muted">系统评分要点</h2>
          <ReasonChips reasons={project.reason} />
        </div>
      </div>

      {/* AI 解读：把冷冰冰的因子讲成人话 */}
      <AiBriefPanel projectId={project.id} autoLoad />

      {/* 可参与任务：官方活动 / 测试网 / Discord 等 */}
      <ParticipationTasks projectId={project.id} />

      {/* 融资：手动补全 → meta.signals → 重评 */}
      <FundingPanel
        projectId={project.id}
        initialFunding={project.funding}
        initialNote={project.funding_note}
        onSaved={loadProject}
      />

      {/* agents */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <AgentPanel title="叙事时机" accent="bg-brand-500">
          <Field label="时机" value={timingZh(String(narrative.timing ?? ''))} />
          <Field
            label="阶段"
            value={stageZh(String(narrative.stage ?? project.stage ?? ''))}
          />
          <div className="mt-2">
            <div className="mb-1 flex justify-between text-xs text-ink-muted">
              <span>热度分</span>
              <span className="tabular-nums">{heat.toFixed(2)}</span>
            </div>
            <ProgressBar value={heat} max={1} color="bg-brand-500" />
          </div>
        </AgentPanel>

        <AgentPanel title="团队信誉" accent="bg-farm">
          <Field label="风险等级" value={riskLevelZh(String(team.risk_level ?? ''))} />
          <Field label="团队类型" value={teamTypeZh(String(team.team_type ?? ''))} />
          <div className="mt-2">
            <div className="mb-1 flex justify-between text-xs text-ink-muted">
              <span>团队分</span>
              <span className="tabular-nums">{formatPct(teamScore)}</span>
            </div>
            <ProgressBar value={teamScore} max={1} color="bg-farm" />
          </div>
          {Array.isArray(team.flags) && team.flags.length ? (
            <div className="mt-3 flex flex-wrap gap-1.5">
              {(team.flags as string[]).map((f) => (
                <span key={f} className="badge bg-surface-3 text-ink-muted">
                  {f}
                </span>
              ))}
            </div>
          ) : null}
        </AgentPanel>

        <AgentPanel title="风险" accent="bg-red-500">
          <Field label="女巫难度" value={riskLevelZh(String(risk.sybil_difficulty ?? ''))} />
          <Field label="交互成本" value={riskLevelZh(String(risk.farming_cost ?? ''))} />
          <Field label="解锁压力" value={riskLevelZh(String(risk.unlock_pressure ?? ''))} />
          <div className="mt-2">
            <div className="mb-1 flex justify-between text-xs text-ink-muted">
              <span>代币风险</span>
              <span className="tabular-nums">{tokenRisk.toFixed(2)}</span>
            </div>
            <ProgressBar value={tokenRisk} max={1} color="bg-red-500" />
          </div>
        </AgentPanel>

        <AgentPanel title="代币结构" accent="bg-watch">
          <Field
            label="VC 占比"
            value={
              tokenomics.vc_share != null ? formatPct(num(tokenomics.vc_share)) : '—'
            }
          />
          <Field
            label="团队占比"
            value={
              tokenomics.team_share != null ? formatPct(num(tokenomics.team_share)) : '—'
            }
          />
          <Field label="解锁压力" value={riskLevelZh(String(tokenomics.unlock_pressure ?? ''))} />
          <Field
            label="解锁惩罚"
            value={
              tokenomics.unlock_penalty != null
                ? String(num(tokenomics.unlock_penalty).toFixed(2))
                : '—'
            }
          />
        </AgentPanel>
      </div>

      {/* 交互记录：做过/日期/成本收益 */}
      <InteractionPanel projectId={project.id} />

      {/* feedback */}
      <div className="card p-5 sm:p-6">
        <h2 className="text-base font-semibold text-ink">反馈校准</h2>
        <p className="mt-1 text-sm text-ink-muted">
          样本累计 ≥200 后可触发权重校准。你的每一次点击都在改进模型。
        </p>
        <div className="mt-4 flex flex-wrap gap-2">
          {SIGNALS.map((s) => (
            <button
              key={s.id}
              type="button"
              disabled={feedbackSending}
              onClick={() => sendFeedback(s.id)}
              className="btn-secondary"
            >
              {s.label}
            </button>
          ))}
        </div>
        <div className="mt-3 flex flex-col gap-2 sm:flex-row">
          <select className="select sm:w-48" value={outcome} onChange={(e) => setOutcome(e.target.value)}>
            {OUTCOMES.map((o) => (
              <option key={o.id || 'none'} value={o.id}>
                {o.label}
              </option>
            ))}
          </select>
          <input
            className="input sm:flex-1"
            placeholder="备注（可选；标签错误时可写：重点参与 / 观察 / 忽略）"
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
        </div>
      </div>
    </div>
  );
}
