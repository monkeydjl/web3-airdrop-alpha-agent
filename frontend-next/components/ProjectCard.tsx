'use client';

import Link from 'next/link';
import { useCallback, useState } from 'react';
import { apiFetch } from '@/lib/api';
import type { Project } from '@/lib/types';
import { ConfidenceBar, LabelBadge, ScoreRing } from './ui';
import { formatPct, reasonTone, sourceZh, stageZh, tierZh } from '@/lib/format';

export function ProjectCard({ project, rank }: { project: Project; rank?: number }) {
  const needsVerify = project.veto === 'no_participation_path';
  const [verdict, setVerdict] = useState<'FARM' | 'WATCH' | null>(null);
  const [sending, setSending] = useState(false);
  const [verifyErr, setVerifyErr] = useState('');

  // 人工核验 → 反馈样本。校准门禁只认 wrong_label + note(正确标签)两类
  // 样本（见 calibration.extract_samples），按钮直接产出这种样本。
  // 「没路径」记 WATCH：系统原本就给了 WATCH，核验与它一致 —— 这也是有效样本
  // （agreement），不是只有分歧才算数。
  const mark = useCallback(
    async (v: 'FARM' | 'WATCH') => {
      if (sending) return;
      setSending(true);
      setVerifyErr('');
      try {
        await apiFetch('/feedback', {
          method: 'POST',
          body: JSON.stringify({ project_id: project.id, signal: 'wrong_label', note: v }),
        });
        setVerdict(v);
      } catch (e) {
        setVerifyErr(e instanceof Error ? e.message : '提交失败');
      } finally {
        setSending(false);
      }
    },
    [project.id, sending],
  );

  return (
    <div className="card-hover group p-4 animate-fade-in">
      <Link href={`/project/${project.id}`} className="block">
        <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="mb-2 flex flex-wrap items-center gap-2">
            {rank != null ? (
              <span className="font-mono text-[10px] text-ink-faint">#{rank}</span>
            ) : null}
            <LabelBadge label={project.label} />
            {project.stage ? (
              <span className="badge bg-surface-3 text-ink-muted">{stageZh(project.stage)}</span>
            ) : null}
            {project.funding?.funding_tier && project.funding.funding_tier !== 'none' ? (
              <span className="badge bg-farm-soft text-farm dark:bg-brand-900/30 dark:text-farm">
                {tierZh(project.funding.funding_tier)}
              </span>
            ) : null}
            {project.veto === 'no_participation_path' ? (
              <span
                className="badge bg-watch-soft text-watch-dark dark:bg-watch/20 dark:text-watch"
                title="分数已达 FARM 线，但未发现测试网/积分/任务入口 —— 需要你到官网或 Twitter 人工验证一次"
              >
                待验证路径
              </span>
            ) : null}
            {project.signals?.site_alive === false ? (
              <span
                className="badge bg-ignore-soft text-ignore-dark dark:bg-ignore/20 dark:text-ignore"
                title="官网连接失败（探测记录里有）—— 这个项目可能已经停服，介入前先看看"
              >
                官网不可达
              </span>
            ) : null}
            {project.skipped ? (
              <span
                className="badge bg-surface-3 text-ink-faint line-through"
                title="你已标记「不参与」—— 工作台默认隐藏这类项目，详情页可恢复"
              >
                不参与
              </span>
            ) : null}
          </div>
          <h3 className="truncate text-base font-semibold text-ink group-hover:text-farm dark:group-hover:text-farm">
            {project.name}
          </h3>
          <p className="mt-0.5 truncate text-xs text-ink-muted">
            {project.sector || '未知赛道'}
            {project.source ? ` · ${sourceZh(project.source)}` : ''}
          </p>
        </div>
        <ScoreRing score={project.score ?? 0} size={64} label={project.label} />
      </div>

      <div className="mt-4">
        <ConfidenceBar value={project.confidence ?? 0} />
      </div>

      {project.reason?.length ? (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {project.reason.slice(0, 2).map((r, i) => {
            const tone = reasonTone(r);
            const sign = tone === 'pos' ? '+' : tone === 'neg' ? '−' : tone === 'warn' ? '!' : '·';
            return (
              <span key={i} className="reason-chip">
                <span className={`reason-sign reason-${tone}`}>{sign}</span>
                <span className="truncate min-w-0">{r}</span>
              </span>
            );
          })}
        </div>
      ) : (
        <p className="mt-3 text-xs text-ink-faint">置信度 {formatPct(project.confidence ?? 0)}</p>
      )}
      </Link>

      {needsVerify ? (
        <div className="mt-3 border-t border-line/70 pt-3">
          {verdict ? (
            <p className="text-xs text-farm" role="status">
              {verdict === 'FARM'
                ? '✓ 已核验：该升 FARM · 计入校准样本'
                : '✓ 已核验：维持观察 · 计入校准样本'}
            </p>
          ) : (
            <div className="flex items-center gap-2">
              <span className="text-[11px] text-ink-faint">人工核验：</span>
              <button
                type="button"
                disabled={sending}
                onClick={() => void mark('FARM')}
                className="btn-secondary !min-h-0 px-2 py-1 text-[11px]"
                title="我去官网/Twitter 看过了，确实有测试网/积分/任务入口 —— 这项目该升级到 FARM"
              >
                有路径 → 升 FARM
              </button>
              <button
                type="button"
                disabled={sending}
                onClick={() => void mark('WATCH')}
                className="btn-secondary !min-h-0 px-2 py-1 text-[11px]"
                title="看过了，确实没有参与入口 —— 系统维持观察是对的"
              >
                没路径 → 维持观察
              </button>
            </div>
          )}
          {verifyErr ? <p className="mt-1 text-[11px] text-watch">{verifyErr}</p> : null}
        </div>
      ) : null}
    </div>
  );
}
