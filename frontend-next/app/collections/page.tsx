'use client';

import { TopBar } from '@/components/TopBar';
import Link from 'next/link';
import { useCallback, useState } from 'react';
import { Star, RefreshCw } from 'lucide-react';
import { apiFetch } from '@/lib/api';
import { useAsyncData } from '@/lib/useAsyncData';
import { labelZh, labelStyles, relativeTime, stageZh } from '@/lib/format';

/** 后端 GET /api/v1/watchlist 的单条结构 */
interface WatchlistItem {
  project_id: string;
  name: string | null;
  sector: string | null;
  stage: string | null;
  score: number | null;
  label: string | null;
  confidence: number | null;
  url: string | null;
  note: string | null;
  watchlisted_at: string | null;
}

interface WatchlistData {
  items: WatchlistItem[];
  total: number;
  page: number;
  page_size: number;
}

type LabelFilter = 'all' | 'FARM' | 'WATCH' | 'IGNORE';

const LABEL_FILTERS: { key: LabelFilter; label: string }[] = [
  { key: 'all', label: '全部' },
  { key: 'FARM', label: labelZh('FARM') },
  { key: 'WATCH', label: labelZh('WATCH') },
  { key: 'IGNORE', label: labelZh('IGNORE') },
];

export default function CollectionsPage() {
  const [labelFilter, setLabelFilter] = useState<LabelFilter>('all');
  const [search, setSearch] = useState('');
  const [removing, setRemoving] = useState<string | null>(null);
  const [actionError, setActionError] = useState('');

  const loader = useCallback(
    (signal: AbortSignal) =>
      apiFetch<WatchlistData>('/watchlist?page=1&page_size=200', { signal }),
    [],
  );
  const { data, error, loading, reload } = useAsyncData(loader, []);

  const items = data?.items ?? [];

  /** 取消收藏：真实调用 DELETE /watchlist/{id}，成功后重新拉取 */
  const removeFromWatchlist = async (projectId: string) => {
    setActionError('');
    setRemoving(projectId);
    try {
      await apiFetch(`/watchlist/${encodeURIComponent(projectId)}`, { method: 'DELETE' });
      reload();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : '取消收藏失败');
    } finally {
      setRemoving(null);
    }
  };

  const counts = LABEL_FILTERS.map((f) => ({
    ...f,
    count:
      f.key === 'all'
        ? items.length
        : items.filter((i) => (i.label || '').toUpperCase() === f.key).length,
  }));

  const filtered = items.filter((item) => {
    if (labelFilter !== 'all' && (item.label || '').toUpperCase() !== labelFilter) return false;
    const q = search.trim().toLowerCase();
    if (!q) return true;
    return (
      (item.name || '').toLowerCase().includes(q) ||
      (item.project_id || '').toLowerCase().includes(q) ||
      (item.note || '').toLowerCase().includes(q) ||
      (item.sector || '').toLowerCase().includes(q)
    );
  });

  return (
    <>
      <TopBar title="收藏关注" subtitle="来自 watchlist · 关注的项目与评分">
        <button
          type="button"
          className="btn-secondary inline-flex items-center gap-1.5"
          onClick={reload}
          disabled={loading}
        >
          <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} strokeWidth={2} />
          <span className="hidden sm:inline">{loading ? '加载中…' : '刷新'}</span>
        </button>
      </TopBar>

      <div className="app-content space-y-4 animate-fade-in">
        {error && (
          <div className="col-card p-4 text-sm text-red-500">
            加载失败：{error}
            <button type="button" className="ml-3 underline" onClick={reload}>
              重试
            </button>
          </div>
        )}
        {actionError && <div className="col-card p-4 text-sm text-red-500">{actionError}</div>}

        {/* 筛选条 */}
        <div className="col-chips">
          {counts.map((c) => (
            <button
              key={c.key}
              type="button"
              className="col-chip"
              data-active={labelFilter === c.key}
              onClick={() => setLabelFilter(c.key)}
            >
              {c.label} <span className="col-chip-count">{c.count}</span>
            </button>
          ))}
          <input
            type="search"
            placeholder="搜索收藏项目…"
            aria-label="搜索收藏项目"
            className="select ml-auto w-48"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>

        {/* 收藏卡片网格 */}
        <div className="col-grid">
          {loading && items.length === 0 ? (
            <div className="col-card col-span-full p-8 text-center text-sm text-ink-faint">
              加载中…
            </div>
          ) : filtered.length === 0 ? (
            <div className="col-card col-span-full p-8 text-center text-sm text-ink-faint">
              {items.length === 0
                ? '还没有收藏任何项目。在项目详情页点「加入关注」即可出现在这里。'
                : '无匹配的收藏项目'}
            </div>
          ) : (
            filtered.map((item) => {
              const label = (item.label || '').toUpperCase();
              const styles = label ? labelStyles(label) : null;
              const busy = removing === item.project_id;
              return (
                <article className="col-card" key={item.project_id}>
                  <div className="col-card-head">
                    <div className="col-card-title-wrap">
                      <div className="col-card-name">{item.name || item.project_id}</div>
                      <div className="col-card-sub">
                        {[item.sector, item.stage ? stageZh(item.stage) : null]
                          .filter(Boolean)
                          .join(' · ') || item.project_id}
                      </div>
                    </div>
                    <button
                      type="button"
                      className="col-card-fav"
                      data-on={true}
                      disabled={busy}
                      aria-label={`取消收藏 ${item.name || item.project_id}`}
                      onClick={() => removeFromWatchlist(item.project_id)}
                    >
                      <Star className="h-3.5 w-3.5" fill="currentColor" strokeWidth={2} />
                    </button>
                  </div>
                  <div className="col-card-labels">
                    {styles && (
                      <span className={`badge ${styles.badge}`}>{labelZh(label)}</span>
                    )}
                  </div>
                  {item.note && <p className="col-card-note">{item.note}</p>}
                  <div className="col-card-meta">
                    <div className="col-meta-item">
                      <span className="col-meta-k">评分</span>
                      <span className="col-meta-v" style={styles ? { color: `rgb(var(--${label.toLowerCase()}))` } : undefined}>
                        {item.score == null ? '—' : item.score.toFixed(2)}
                      </span>
                    </div>
                    <div className="col-meta-item">
                      <span className="col-meta-k">置信度</span>
                      <span className="col-meta-v">
                        {item.confidence == null ? '—' : item.confidence.toFixed(2)}
                      </span>
                    </div>
                    <div className="col-meta-item">
                      <span className="col-meta-k">收藏时间</span>
                      <span className="col-meta-v">{relativeTime(item.watchlisted_at) || '—'}</span>
                    </div>
                  </div>
                  <div className="col-card-actions">
                    <Link
                      href={`/project/${encodeURIComponent(item.project_id)}`}
                      className="text-xs font-medium text-farm hover:underline"
                    >
                      查看详情 →
                    </Link>
                  </div>
                </article>
              );
            })
          )}
        </div>
      </div>
    </>
  );
}
