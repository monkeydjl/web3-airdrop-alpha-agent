'use client';

import Link from 'next/link';
import type { Project } from '@/lib/types';
import { ConfidenceBar, LabelBadge, ScoreRing } from './ui';
import { formatPct, sourceZh, stageZh, tierZh } from '@/lib/format';

export function ProjectCard({ project, rank }: { project: Project; rank?: number }) {
  return (
    <Link href={`/project/${project.id}`} className="card-hover group block p-4 animate-fade-in">
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
              <span className="badge bg-brand-50 text-brand-700 dark:bg-brand-900/30 dark:text-brand-300">
                {tierZh(project.funding.funding_tier)}
              </span>
            ) : null}
          </div>
          <h3 className="truncate text-base font-semibold text-ink group-hover:text-brand-600 dark:group-hover:text-brand-300">
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
        <p className="mt-3 line-clamp-2 text-xs leading-relaxed text-ink-faint">
          {project.reason.slice(0, 2).join(' · ')}
        </p>
      ) : (
        <p className="mt-3 text-xs text-ink-faint">置信度 {formatPct(project.confidence ?? 0)}</p>
      )}
    </Link>
  );
}
