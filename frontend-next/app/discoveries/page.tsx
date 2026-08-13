'use client';

import { Info, Play, ShieldOff } from 'lucide-react';
import Link from 'next/link';
import { useCallback, useEffect, useState } from 'react';
import { TopBar } from '@/components/TopBar';
import { EmptyState, Toast } from '@/components/ui';
import { apiFetch } from '@/lib/api';
import { relativeTime, sourceZh } from '@/lib/format';
import type { DiscoveryItem, DiscoveriesResponse } from '@/lib/types';

type StatusFilter = 'pending' | 'processed' | 'all';
type SortBy = 'score' | 'time' | 'name';

const SOURCE_OPTIONS = [
  'defillama', 'github', 'coingecko', 'cryptorank', 'rootdata',
  'twitter_kol', 'twitter_keyword', 'etherscan', 'galxe', 'layer3',
];

export default function DiscoveriesPage() {
  const [items, setItems] = useState<DiscoveryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<{ message: string; type: 'success' | 'error' | 'info' } | null>(null);

  // 统计
  const [pendingCount, setPendingCount] = useState(0);
  const [processedCount, setProcessedCount] = useState(0);
  const [totalCount, setTotalCount] = useState(0);
  const [quarantineCount, setQuarantineCount] = useState(0);
  const [todayNew, setTodayNew] = useState(0);

  // 筛选
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('pending');
  const [sourceFilter, setSourceFilter] = useState('');
  const [minScore, setMinScore] = useState(0.3);
  const [sortBy, setSortBy] = useState<SortBy>('score');

  // 隔离操作
  const [quarantining, setQuarantining] = useState<string | null>(null);

  const loadStats = useCallback(async () => {
    try {
      const [pendingRes, processedRes, allRes, qRes] = await Promise.all([
        apiFetch<DiscoveriesResponse>('/discoveries?page=1&page_size=1&processed=false&min_score=0.30'),
        apiFetch<DiscoveriesResponse>('/discoveries?page=1&page_size=1&processed=true&min_score=0.0'),
        apiFetch<DiscoveriesResponse>('/discoveries?page=1&page_size=1&min_score=0.0'),
        apiFetch<{ count: number; items: unknown[] }>('/quarantine?limit=1'),
      ]);
      setPendingCount(pendingRes.total);
      setProcessedCount(processedRes.total);
      setTotalCount(allRes.total);
      setQuarantineCount(qRes.count);
    } catch {
      // 统计加载失败不阻塞主表
    }
  }, []);

  const loadList = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({ page: '1', page_size: '200' });
      params.set('min_score', String(minScore));
      if (statusFilter === 'pending') params.set('processed', 'false');
      else if (statusFilter === 'processed') params.set('processed', 'true');

      const res = await apiFetch<DiscoveriesResponse>(`/discoveries?${params}`);
      let rows = res.items;

      // 来源筛选（客户端）
      if (sourceFilter) {
        rows = rows.filter((r) => r.source_id === sourceFilter);
      }

      // 排序（客户端）
      if (sortBy === 'time') {
        rows = [...rows].sort((a, b) =>
          new Date(b.discovered_at).getTime() - new Date(a.discovered_at).getTime(),
        );
      } else if (sortBy === 'name') {
        rows = [...rows].sort((a, b) => a.name.localeCompare(b.name));
      }

      setItems(rows);

      // 今日新增：统计 discovered_at 是今天的
      const todayStr = new Date().toISOString().slice(0, 10);
      setTodayNew(rows.filter((r) => r.discovered_at?.slice(0, 10) === todayStr).length);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载失败');
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, [minScore, statusFilter, sourceFilter, sortBy]);

  useEffect(() => {
    loadStats();
  }, [loadStats]);

  useEffect(() => {
    loadList();
  }, [loadList]);

  const handleQuarantine = async (rawId: string, name: string) => {
    const reason = window.prompt(`隔离「${name}」\n请输入隔离原因：`, '手动隔离');
    if (!reason) return;
    setQuarantining(rawId);
    try {
      await apiFetch('/quarantine', {
        method: 'POST',
        body: JSON.stringify({ raw_id: rawId, reason }),
      });
      setToast({ message: `已隔离 ${name}`, type: 'success' });
      setItems((prev) => prev.filter((r) => r.raw_id !== rawId));
      setPendingCount((c) => Math.max(0, c - 1));
      setQuarantineCount((c) => c + 1);
    } catch (err) {
      setToast({
        message: err instanceof Error ? err.message : '隔离失败',
        type: 'error',
      });
    } finally {
      setQuarantining(null);
    }
  };

  return (
    <>
      {toast && <Toast message={toast.message} type={toast.type} />}
      <TopBar title="发现队列" subtitle="采集器原始发现 · discovery_score ≥ 0.30 进入分析队列">
        <Link href="/ops" className="btn-secondary inline-flex items-center gap-1.5">
          <ShieldOff className="h-4 w-4" strokeWidth={2} />
          <span className="hidden sm:inline">查看隔离区</span>
        </Link>
        <button type="button" className="btn-primary inline-flex items-center gap-1.5">
          <Play className="h-4 w-4" strokeWidth={2} />
          <span>运行分析</span>
        </button>
      </TopBar>

      <div className="app-content animate-fade-in">
        {/* 1. 统计卡 */}
        <section className="disc-stats" aria-label="队列统计">
          <div className="disc-stat-card">
            <div className="disc-stat-head">
              <span className="disc-stat-dot" style={{ background: 'rgb(245 158 11)' }} />
              <span className="disc-stat-label">待处理</span>
            </div>
            <div className="disc-stat-value">{pendingCount}</div>
            <div className="disc-stat-caption">≥0.30 阈值过滤后</div>
          </div>
          <div className="disc-stat-card">
            <div className="disc-stat-head">
              <span className="disc-stat-dot" style={{ background: 'rgb(77 86 221)' }} />
              <span className="disc-stat-label">今日新增</span>
            </div>
            <div className="disc-stat-value">{todayNew}</div>
            <div className="disc-stat-caption">{SOURCE_OPTIONS.length} 个采集源</div>
          </div>
          <div className="disc-stat-card">
            <div className="disc-stat-head">
              <span className="disc-stat-dot" style={{ background: 'rgb(16 185 129)' }} />
              <span className="disc-stat-label">已入项目库</span>
            </div>
            <div className="disc-stat-value">{processedCount}</div>
            <div className="disc-stat-caption">累计 {totalCount} 条发现</div>
          </div>
          <div className="disc-stat-card">
            <div className="disc-stat-head">
              <span className="disc-stat-dot" style={{ background: 'rgb(224 72 63)' }} />
              <span className="disc-stat-label">隔离区</span>
            </div>
            <div className="disc-stat-value">{quarantineCount}</div>
            <div className="disc-stat-caption">手动隔离</div>
          </div>
        </section>

        {/* 2. 筛选行 */}
        <section className="disc-filters" aria-label="筛选工具">
          <div className="disc-filter-fields">
            <label className="disc-filter-field">
              <span className="disc-filter-label">状态</span>
              <select
                className="disc-filter-control"
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value as StatusFilter)}
              >
                <option value="pending">仅待处理</option>
                <option value="processed">已入库</option>
                <option value="all">全部状态</option>
              </select>
            </label>
            <label className="disc-filter-field">
              <span className="disc-filter-label">来源</span>
              <select
                className="disc-filter-control"
                value={sourceFilter}
                onChange={(e) => setSourceFilter(e.target.value)}
              >
                <option value="">全部来源</option>
                {SOURCE_OPTIONS.map((s) => (
                  <option key={s} value={s}>{sourceZh(s)}</option>
                ))}
              </select>
            </label>
            <label className="disc-filter-field">
              <span className="disc-filter-label">最低发现分</span>
              <select
                className="disc-filter-control"
                value={minScore}
                onChange={(e) => setMinScore(Number(e.target.value))}
              >
                <option value={0}>≥ 0.00</option>
                <option value={0.3}>≥ 0.30</option>
                <option value={0.5}>≥ 0.50</option>
                <option value={0.7}>≥ 0.70</option>
              </select>
            </label>
            <label className="disc-filter-field">
              <span className="disc-filter-label">排序</span>
              <select
                className="disc-filter-control"
                value={sortBy}
                onChange={(e) => setSortBy(e.target.value as SortBy)}
              >
                <option value="score">发现分优先</option>
                <option value="time">发现时间优先</option>
                <option value="name">项目名 A-Z</option>
              </select>
            </label>
          </div>
          <span className="disc-filter-count">
            {loading ? '加载中…' : `${items.length} / ${totalCount} 条`}
          </span>
        </section>

        {/* 3. 发现队列表 */}
        <section className="disc-table-card" aria-label="发现队列表">
          {error ? (
            <div className="p-8">
              <EmptyState title="加载失败" description={error} />
            </div>
          ) : items.length === 0 && !loading ? (
            <div className="p-8">
              <EmptyState title="暂无发现" description="当前筛选条件下没有数据" />
            </div>
          ) : loading ? (
            <div className="p-8 text-center text-sm text-ink-faint">加载中…</div>
          ) : (
            <table className="disc-table">
              <thead>
                <tr>
                  <th>项目名</th>
                  <th>来源</th>
                  <th>赛道</th>
                  <th>发现分</th>
                  <th>发现时间</th>
                  <th>状态</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr key={item.raw_id}>
                    <td>
                      <div className="disc-proj-name">{item.name || '未命名'}</div>
                      <div className="disc-proj-key">
                        {item.dedup_key}
                        {item.sector ? `::${item.sector}` : ''}
                      </div>
                    </td>
                    <td>
                      <span className="disc-source-chip">{item.source_id}</span>
                    </td>
                    <td>{item.sector || '—'}</td>
                    <td>
                      <div className="disc-score">
                        <span className="disc-score-bar">
                          <span
                            className="disc-score-fill"
                            style={{ width: `${Math.round(item.discovery_score * 100)}%` }}
                          />
                        </span>
                        <span className="disc-score-value">
                          {item.discovery_score.toFixed(2)}
                        </span>
                      </div>
                    </td>
                    <td>
                      <span className="text-xs text-ink-faint">
                        {relativeTime(item.discovered_at)}
                      </span>
                    </td>
                    <td>
                      {item.processed ? (
                        <span className="disc-badge disc-badge-success">已入库</span>
                      ) : (
                        <span className="disc-badge disc-badge-warning">待处理</span>
                      )}
                    </td>
                    <td>
                      <div className="disc-row-actions">
                        <button
                          type="button"
                          className="btn-secondary inline-flex items-center gap-1 px-2.5 py-1 text-xs"
                          disabled={quarantining === item.raw_id}
                          onClick={() => handleQuarantine(item.raw_id, item.name)}
                        >
                          <ShieldOff className="h-3.5 w-3.5" strokeWidth={2} />
                          <span>{quarantining === item.raw_id ? '…' : '隔离'}</span>
                        </button>
                        {item.project_id && (
                          <Link
                            href={`/project/${item.project_id}`}
                            className="disc-text-link"
                          >
                            查看项目
                          </Link>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>

        {/* 4. 隔离说明条 */}
        <section className="disc-quarantine-note" aria-label="关于隔离">
          <Info className="h-4 w-4 shrink-0 mt-0.5" style={{ color: 'rgb(180 100 10)' }} strokeWidth={2} />
          <div>
            <div className="disc-quarantine-title">关于隔离</div>
            <p className="disc-quarantine-text">
              隔离会将该发现移出分析队列（processed=1）并记录原因；在运维台可释放回队。误隔离不会影响已入库项目。
            </p>
          </div>
        </section>
      </div>
    </>
  );
}
