'use client';

import {
  Bell,
  CheckCheck,
  Inbox,
  Radio,
  Sparkles,
  TrendingUp,
} from 'lucide-react';
import Link from 'next/link';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { TopBar } from '@/components/TopBar';
import { EmptyState, Toast } from '@/components/ui';
import { apiFetch } from '@/lib/api';
import { relativeTime } from '@/lib/format';

/**
 * 通知类型。
 *
 * **只列后端真的会产出的类型**：`app/routers/v1/notifications.py` 聚合三类——
 * `new_project`（今日新建且 FARM/WATCH）、`score`（最新两条评分有变化）、
 * `collector`（今日采集失败）。
 *
 * 此前这里还有 `deadline` / `funding` / `ai` 三种，后端从不产出，于是侧栏
 * 常驻三个永远显示 0 的分类入口——点进去永远是空列表。一个永远为空的入口
 * 不是"暂时没数据"，而是在承诺一个不存在的功能。
 */
type NtfType = 'all' | 'new_project' | 'score' | 'collector';
type DotTone = 'info' | 'success' | 'warning' | 'error' | 'brand';

interface NotificationItem {
  id: string;
  type: Exclude<NtfType, 'all'>;
  dotTone: DotTone;
  title: string;
  tag: string;
  text: string;
  meta: { label: string; value: string }[];
  time: string;
  read: boolean;
  link?: { label: string; href: string };
  createdAt?: string;
}

interface ApiNotification {
  id: string;
  type: string;
  title: string;
  tag?: string;
  text?: string;
  project_id?: string;
  created_at?: string;
  read?: boolean;
  link?: { label: string; href: string };
}

/** apiFetch 已解包后端 data 字段 */
interface NotificationsData {
  unread_count?: number;
  items?: ApiNotification[];
}

interface MarkReadData {
  marked?: number;
  ids?: string[];
}

const TYPE_DOT: Record<string, DotTone> = {
  new_project: 'success',
  score: 'success',
  collector: 'error',
};

const TYPE_TAG: Record<string, string> = {
  new_project: '新机会',
  score: '评分变化',
  collector: '采集器告警',
};

function mapApiItem(item: ApiNotification): NotificationItem {
  const type = (item.type || 'score') as Exclude<NtfType, 'all'>;
  return {
    id: item.id,
    type,
    dotTone: TYPE_DOT[type] || 'info',
    title: item.title,
    tag: item.tag || TYPE_TAG[type] || type,
    text: item.text || '',
    meta: item.project_id
      ? [
          { label: '类型', value: type },
          { label: '项目', value: item.project_id.slice(0, 8) },
        ]
      : [{ label: '类型', value: type }],
    time: item.created_at ? relativeTime(item.created_at) : '刚刚',
    read: Boolean(item.read),
    link: item.link,
    createdAt: item.created_at,
  };
}

const NAV_ITEMS: { key: NtfType; label: string; icon: typeof Inbox }[] = [
  { key: 'all', label: '全部', icon: Inbox },
  { key: 'new_project', label: '新机会', icon: Sparkles },
  { key: 'score', label: '评分变化', icon: TrendingUp },
  { key: 'collector', label: '采集器', icon: Radio },
];

export default function NotificationsPage() {
  const [activeType, setActiveType] = useState<NtfType>('all');
  const [items, setItems] = useState<NotificationItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<{ message: string; type: 'success' | 'error' | 'info' } | null>(
    null,
  );

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await apiFetch<NotificationsData>('/notifications');
      const raw = res?.items ?? [];
      setItems(raw.map(mapApiItem));
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载通知失败');
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const typeCounts = useMemo(() => {
    const counts: Record<string, number> = { all: items.length };
    for (const item of items) {
      counts[item.type] = (counts[item.type] || 0) + 1;
    }
    return counts;
  }, [items]);

  const filtered = activeType === 'all' ? items : items.filter((n) => n.type === activeType);

  const unreadCount = items.filter((n) => !n.read).length;
  const newOpportunityCount = items.filter((n) => n.type === 'new_project').length;
  const scoreChangeCount = items.filter((n) => n.type === 'score').length;
  const collectorAlertCount = items.filter((n) => n.type === 'collector' && !n.read).length;

  const handleMarkAllRead = async () => {
    const prev = items;
    setItems((cur) => cur.map((n) => ({ ...n, read: true })));
    try {
      await apiFetch<MarkReadData>('/notifications/read', {
        method: 'POST',
        body: JSON.stringify({ all: true }),
      });
      setToast({ message: '已全部标记为已读', type: 'success' });
    } catch (err) {
      setItems(prev);
      setToast({
        message: err instanceof Error ? err.message : '标记已读失败',
        type: 'error',
      });
    }
  };

  const handleClickItem = async (id: string) => {
    const target = items.find((n) => n.id === id);
    if (!target || target.read) return;
    const prev = items;
    setItems((cur) => cur.map((n) => (n.id === id ? { ...n, read: true } : n)));
    try {
      await apiFetch<MarkReadData>('/notifications/read', {
        method: 'POST',
        body: JSON.stringify({ ids: [id] }),
      });
    } catch {
      setItems(prev);
    }
  };

  return (
    <>
      {toast && <Toast message={toast.message} type={toast.type} />}
      <TopBar title="通知中心" subtitle="真实数据 · 新机会 · 评分变化 · 采集告警">
        <button
          type="button"
          className="btn-secondary inline-flex items-center gap-1.5"
          onClick={() => void handleMarkAllRead()}
          disabled={items.length === 0 || unreadCount === 0}
        >
          <CheckCheck className="h-4 w-4" strokeWidth={2} />
          <span className="hidden sm:inline">全部已读</span>
        </button>
        <button type="button" className="btn-secondary inline-flex items-center gap-1.5" onClick={() => void load()}>
          <Bell className="h-4 w-4" strokeWidth={2} />
          <span>刷新</span>
        </button>
        <Link href="/settings" className="btn-primary inline-flex items-center gap-1.5">
          <Bell className="h-4 w-4" strokeWidth={2} />
          <span>通知设置</span>
        </Link>
      </TopBar>

      <div className="app-content animate-fade-in">
        <section className="ntf-stats" aria-label="通知概览">
          <div className="ntf-stat">
            <span className="ntf-stat-k">未读</span>
            <span className="ntf-stat-v" data-tone="brand">
              {unreadCount}
            </span>
            <span className="ntf-stat-s">当前列表</span>
          </div>
          <div className="ntf-stat">
            <span className="ntf-stat-k">新机会</span>
            <span className="ntf-stat-v">{newOpportunityCount}</span>
            <span className="ntf-stat-s">今日新建 FARM / WATCH</span>
          </div>
          {/* 原先这里是「截止时间临近」，副标题写着「有数据时显示」——
              但后端从不产出 deadline 类通知，所以它永远是 0。
              换成后端真的会产出的「评分变化」。 */}
          <div className="ntf-stat">
            <span className="ntf-stat-k">评分变化</span>
            <span className="ntf-stat-v" data-tone="warn">
              {scoreChangeCount}
            </span>
            <span className="ntf-stat-s">最新两次打分有变动</span>
          </div>
          <div className="ntf-stat">
            <span className="ntf-stat-k">采集器告警</span>
            <span className="ntf-stat-v" data-tone="err">
              {collectorAlertCount}
            </span>
            <span className="ntf-stat-s">需要处理</span>
          </div>
        </section>

        <div className="ntf-layout">
          <nav className="ntf-side" aria-label="通知分组">
            <div className="ntf-side-title">通知类型</div>
            {NAV_ITEMS.map((item) => {
              const Icon = item.icon;
              const count = typeCounts[item.key] || 0;
              return (
                <button
                  key={item.key}
                  type="button"
                  className="ntf-side-item"
                  data-active={activeType === item.key}
                  onClick={() => setActiveType(item.key)}
                >
                  <Icon className="h-3.5 w-3.5" strokeWidth={2} />
                  <span>{item.label}</span>
                  <span className="ntf-side-count">{count}</span>
                </button>
              );
            })}
          </nav>

          <section className="ntf-list" aria-label="通知列表">
            <div className="ntf-list-head">
              <div className="ntf-list-title">最新动态</div>
              <div className="ntf-list-actions">
                <button
                  type="button"
                  className="btn-secondary px-2.5 py-1 text-xs"
                  onClick={() => void handleMarkAllRead()}
                  disabled={items.length === 0 || unreadCount === 0}
                >
                  <CheckCheck className="h-3.5 w-3.5" strokeWidth={2} />
                  <span>全部已读</span>
                </button>
              </div>
            </div>

            {loading ? (
              <div className="p-8 text-center text-sm text-ink-faint">加载中…</div>
            ) : error ? (
              <div className="p-8">
                <EmptyState
                  title="加载失败"
                  description={error}
                  action={
                    <button type="button" className="btn-primary" onClick={() => void load()}>
                      重试
                    </button>
                  }
                />
              </div>
            ) : filtered.length === 0 ? (
              <div className="p-8">
                <EmptyState
                  title="暂无通知"
                  description="今日暂无新 FARM/WATCH 机会或采集器告警。跑一次采集评分后这里会出现真实条目。"
                />
              </div>
            ) : (
              filtered.map((item) => (
                <div
                  key={item.id}
                  className="ntf-item"
                  data-read={item.read}
                  onClick={() => void handleClickItem(item.id)}
                >
                  <span className={`ntf-dot ntf-dot-${item.dotTone}`} />
                  <div className="ntf-body">
                    <div className="ntf-head">
                      <span className="ntf-title">{item.title}</span>
                      <span className="ntf-tag">{item.tag}</span>
                    </div>
                    <p className="ntf-text">{item.text}</p>
                    <div className="ntf-meta">
                      {item.meta.map((m) => (
                        <span key={m.label}>
                          {m.label} · {m.value}
                        </span>
                      ))}
                    </div>
                  </div>
                  <div className="ntf-side-actions">
                    <span className="ntf-time">{item.time}</span>
                    {item.link && (
                      <Link href={item.link.href} className="ntf-link">
                        {item.link.label}
                      </Link>
                    )}
                  </div>
                </div>
              ))
            )}
          </section>
        </div>
      </div>
    </>
  );
}
