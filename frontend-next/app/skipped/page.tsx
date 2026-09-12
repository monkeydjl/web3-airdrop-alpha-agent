'use client';

import { Ban, Undo2 } from 'lucide-react';
import Link from 'next/link';
import { useCallback, useState } from 'react';
import { TopBar } from '@/components/TopBar';
import { EmptyState } from '@/components/ui';
import { apiFetch } from '@/lib/api';
import { sourceZh, stageZh } from '@/lib/format';
import { fetchAllProjects } from '@/lib/projects';
import type { Project } from '@/lib/types';
import { useAsyncData } from '@/lib/useAsyncData';

/**
 * 「不参与」清单页：用户主动跳过的项目都在这里。
 *
 * 与系统标签刻意分开（veto=already_launched 是模型判断，skip 是用户决定），
 * 所以恢复动作只有一个语义：从跳过列表移除 → 项目自动回到工作台。
 */
export default function SkippedPage() {
  const [removingId, setRemovingId] = useState<string | null>(null);
  const [err, setErr] = useState('');

  const loader = useCallback(async (signal: AbortSignal) => {
    const all = await fetchAllProjects(signal);
    return all.projects.filter((p) => p.skipped);
  }, []);

  const { data: items, loading, error, reload } = useAsyncData(loader, []);

  const restore = useCallback(
    async (projectId: string) => {
      if (removingId) return;
      setRemovingId(projectId);
      setErr('');
      try {
        await apiFetch(`/projects/${projectId}/skip`, { method: 'DELETE', body: '{}' });
        await reload();
      } catch (e: unknown) {
        setErr(e instanceof Error ? e.message : '恢复失败');
      } finally {
        setRemovingId(null);
      }
    },
    [removingId, reload],
  );

  const count = (items || []).length;

  return (
    <>
      <TopBar title="不参与" subtitle="你主动跳过的项目都沉在这里，随时恢复" />
      <div className="app-content animate-fade-in space-y-5">
        <p className="text-sm text-ink-muted">
          系统评出的 label/veto 是模型的结论，这个清单纯粹是你自己的决定。
          点「恢复」项目会重新出现在工作台。
        </p>

        {loading ? (
          <p className="text-xs text-ink-muted">加载中…</p>
        ) : error ? (
          <EmptyState
            title="加载失败"
            description={String(error)}
            action={
              <button type="button" className="btn-primary" onClick={reload}>
                重试
              </button>
            }
          />
        ) : count === 0 ? (
          <div className="border border-dashed border-line rounded-xl p-10 text-center space-y-3">
            <Ban className="mx-auto h-5 w-5 text-ink-faint" strokeWidth={1.5} />
            <p className="text-sm text-ink-muted">还没有「不参与」的项目</p>
            <p className="text-xs text-ink-faint">
              在详情页点「不参与」，项目就会汇到这里；工作台默认看不到它们。
            </p>
            <Link href="/" className="btn-primary inline-flex">去工作台</Link>
          </div>
        ) : (
          <div className="space-y-2">
            {err ? <p className="text-xs text-watch">{err}</p> : null}
            {items!.map((p) => (
              <SkippedRow key={p.id} project={p} busy={removingId === p.id} onRestore={restore} />
            ))}
          </div>
        )}
      </div>
    </>
  );
}

function SkippedRow({
  project,
  busy,
  onRestore,
}: {
  project: Project;
  busy: boolean;
  onRestore: (id: string) => void;
}) {
  return (
    <div className="flex items-center gap-3 rounded-xl border border-line bg-surface px-4 py-3">
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <Link href={`/project/${project.id}`} className="truncate text-sm font-medium text-ink hover:text-farm dark:hover:text-farm">
            {project.name}
          </Link>
          <span className="badge bg-surface-3 text-ink-faint">{stageZh(project.stage)}</span>
          {project.source ? (
            <span className="badge bg-surface-3 text-ink-faint">{sourceZh(project.source)}</span>
          ) : null}
        </div>
        <p className="mt-0.5 font-mono text-[11px] tracking-wide text-ink-faint">
          评分 {project.score ?? '—'} · {project.label ?? '—'}
        </p>
      </div>
      <button
        type="button"
        className="btn-secondary px-3 py-1.5 text-xs"
        disabled={busy}
        onClick={() => onRestore(project.id)}
        title="恢复后项目会重新出现在工作台"
      >
        <Undo2 className="mr-1 inline h-3.5 w-3.5" strokeWidth={2} />
        {busy ? '恢复中…' : '恢复'}
      </button>
    </div>
  );
}
