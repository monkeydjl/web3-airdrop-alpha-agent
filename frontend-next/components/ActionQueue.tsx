'use client';

import { useCallback, useState } from 'react';
import Link from 'next/link';
import { Check, ExternalLink, RefreshCw } from 'lucide-react';
import { apiFetch } from '@/lib/api';
import { safeExternalUrl } from '@/lib/format';
import { useAsyncData } from '@/lib/useAsyncData';

export interface ActionQueueItem {
  project_id: string;
  project_name?: string | null;
  project_score?: number | null;
  label?: string | null;
  sector?: string | null;
  stage?: string | null;
  url?: string | null;
  task_id: string;
  title: string;
  description?: string | null;
  category?: string | null;
  category_zh?: string | null;
  priority?: number | null;
  effort_zh?: string | null;
  why?: string | null;
  action_hint?: string | null;
  link?: string | null;
  required?: boolean;
  already_engaged?: boolean;
  watchlisted?: boolean;
  rank_score?: number | null;
}

interface ActionQueueData {
  items?: ActionQueueItem[];
  summary?: {
    returned?: number;
    candidates?: number;
    projects_considered?: number;
    projects_skipped_engaged?: number;
    required_count?: number;
    projects_in_queue?: number;
  };
  notes?: string[];
}

interface Props {
  limit?: number;
  onDone?: (message: string, type: 'success' | 'error') => void;
}

export function ActionQueue({ limit = 5, onDone }: Props) {
  const [marking, setMarking] = useState<string | null>(null);
  // onDone 是可选的：若调用方没传，标记失败就会无声无息。这里兜一个本地
  // 错误态，保证「点了没反应」永远不会发生。
  const [markError, setMarkError] = useState('');

  const loader = useCallback(
    (signal: AbortSignal) => apiFetch<ActionQueueData>(`/action-queue?limit=${limit}`, { signal }),
    [limit],
  );
  const { data, error, loading, reload } = useAsyncData(loader, [limit]);

  const items = data?.items ?? [];
  const summary = data?.summary ?? {};

  /** 标记「已做」= 写一条真实的交互记录（复用 interactions，不引入第二套状态） */
  const markDone = async (item: ActionQueueItem) => {
    const key = `${item.project_id}:${item.task_id}`;
    setMarking(key);
    setMarkError('');
    try {
      await apiFetch('/interactions', {
        method: 'POST',
        body: JSON.stringify({
          project_id: item.project_id,
          status: 'active',
          activities: item.title,
          note: `来自今日行动：${item.title}`,
          outcome: 'pending',
        }),
      });
      onDone?.(`已记录：${item.project_name ?? item.project_id} · ${item.title}`, 'success');
      // 重新拉取补位：该项目已有交互记录，后端会把它整体排除并让出名额，
      // 于是列表长度保持稳定、新候选顶上来。
      // 刻意不用「本地隐藏」表达已完成——那样清单会随着标记逐条变短直到空掉，
      // 用户以为没活儿了，实际后端还有上百个候选没露出来。
      reload();
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : '标记失败';
      setMarkError(msg);
      onDone?.(msg, 'error');
    } finally {
      setMarking(null);
    }
  };

  return (
    <div className="dash-card p-5">
      <div className="mb-1 flex items-center justify-between gap-3">
        <h2 className="text-sm font-semibold text-ink">今日行动</h2>
        <button
          type="button"
          onClick={() => reload()}
          className="btn-secondary !px-2 !py-1"
          disabled={loading}
          aria-label="刷新今日行动"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
        </button>
      </div>
      <p className="mb-4 text-xs text-ink-muted">
        从重点参与 / 观察项目里挑出最该先做的几步
        {typeof summary.candidates === 'number' && summary.candidates > 0
          ? ` · 候选 ${summary.candidates} 条`
          : ''}
        {summary.projects_skipped_engaged ? ` · 已跳过 ${summary.projects_skipped_engaged} 个已参与项目` : ''}
      </p>

      {(error || markError) && (
        <div
          role="alert"
          className="mb-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300"
        >
          {error ? `加载失败：${error}` : `标记失败：${markError}`}
        </div>
      )}

      {loading && !data && (
        <div className="space-y-2">
          <div className="skeleton h-14 w-full" />
          <div className="skeleton h-14 w-full" />
          <div className="skeleton h-14 w-full" />
        </div>
      )}

      {!loading && !error && items.length === 0 && (
        <div className="rounded-lg border border-dashed border-line px-3 py-6 text-center text-xs text-ink-muted">
          {summary.projects_skipped_engaged
            ? `重点参与项目都已有交互记录（跳过 ${summary.projects_skipped_engaged} 个），暂无新行动。`
            : '暂无待办行动。跑一次「采集并评分」后会自动生成。'}
        </div>
      )}

      <ul className="space-y-2">
        {items.map((item) => {
          const key = `${item.project_id}:${item.task_id}`;
          const href = safeExternalUrl(item.link || item.url || '');
          return (
            <li key={key} className="aq-row">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-1.5">
                  <Link href={`/project/${item.project_id}`} className="aq-project">
                    {item.project_name ?? item.project_id}
                  </Link>
                  {typeof item.project_score === 'number' && (
                    <span className="aq-chip">{Math.round(item.project_score)} 分</span>
                  )}
                  {item.category_zh && <span className="aq-chip">{item.category_zh}</span>}
                  {item.required && <span className="aq-chip aq-chip-req">必做</span>}
                  {item.watchlisted && <span className="aq-chip">已收藏</span>}
                </div>
                <p className="mt-1 truncate text-sm font-medium text-ink" title={item.title}>
                  {item.title}
                </p>
                {item.why && <p className="mt-0.5 line-clamp-2 text-xs text-ink-muted">{item.why}</p>}
              </div>
              <div className="flex shrink-0 items-center gap-1.5">
                {href && (
                  <a
                    href={href}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="btn-secondary !px-2 !py-1"
                    aria-label={`打开 ${item.project_name ?? item.project_id} 官网`}
                  >
                    <ExternalLink className="h-3.5 w-3.5" />
                  </a>
                )}
                <button
                  type="button"
                  onClick={() => markDone(item)}
                  disabled={marking === key}
                  className="btn-primary !px-2 !py-1"
                  aria-label={`标记已做：${item.title}`}
                >
                  {marking === key ? (
                    <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-white/30 border-t-white" />
                  ) : (
                    <Check className="h-3.5 w-3.5" />
                  )}
                </button>
              </div>
            </li>
          );
        })}
      </ul>

      {items.length > 0 && (
        <p className="mt-3 text-[11px] leading-relaxed text-ink-muted">
          标记「已做」会写入你的交互记录，可在
          <Link href="/portfolio" className="mx-1 underline">
            参与复盘
          </Link>
          补充成本与收益。清单由规则生成，非官方承诺。
        </p>
      )}
    </div>
  );
}
