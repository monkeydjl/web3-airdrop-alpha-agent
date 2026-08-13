'use client';

import {
  AlarmClock,
  Bell,
  CheckCheck,
  Inbox,
  Radio,
  Sparkles,
  TrendingUp,
  Wallet,
} from 'lucide-react';
import Link from 'next/link';
import { useMemo, useState } from 'react';
import { TopBar } from '@/components/TopBar';
import { EmptyState, Toast } from '@/components/ui';

type NtfType = 'all' | 'score' | 'deadline' | 'collector' | 'funding' | 'ai';
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
}

const NOTIFICATIONS: NotificationItem[] = [
  {
    id: 'ntf-1',
    type: 'score',
    dotTone: 'success',
    title: 'Nova Protocol 评分上升 0.12',
    tag: '评分变化',
    text: '大模型 v2.0 重新评估后，从 0.76 上调至 0.88。新增生态合作公告 + 测试网交互激励上线。',
    meta: [
      { label: '触发源', value: 'opportunity_engine' },
      { label: '项目', value: 'nova-protocol' },
    ],
    time: '12 分钟前',
    read: false,
    link: { label: '查看项目', href: '/project/nova-protocol' },
  },
  {
    id: 'ntf-2',
    type: 'deadline',
    dotTone: 'warning',
    title: 'Poly Oracle 快照还有 36 小时',
    tag: '截止提醒',
    text: 'Galxe 任务仍需 2 项才能完成资格；建议在明天 18:00 前补齐。',
    meta: [
      { label: '触发源', value: 'analysis_scheduler' },
      { label: '项目', value: 'poly-oracle' },
    ],
    time: '1 小时前',
    read: false,
    link: { label: '前往参与', href: '/project/poly-oracle' },
  },
  {
    id: 'ntf-3',
    type: 'collector',
    dotTone: 'error',
    title: 'twitter 采集器连续 3 次失败',
    tag: '采集器告警',
    text: '最近 1 小时失败率 100%（401 未授权）。可能是 token 过期，请前往运维台处理。',
    meta: [
      { label: '触发源', value: 'collectors' },
      { label: '来源', value: 'twitter' },
    ],
    time: '2 小时前',
    read: false,
    link: { label: '运维台', href: '/ops' },
  },
  {
    id: 'ntf-4',
    type: 'funding',
    dotTone: 'brand',
    title: 'Meridian Chain 完成 1,200 万美元 A 轮',
    tag: '资金与融资',
    text: '领投方为 Paradigm；项目 FDV 上调至 4.5 亿美元，空投预期由「观察」上调至「关注」。',
    meta: [
      { label: '触发源', value: 'funding_tracker' },
      { label: '项目', value: 'meridian-chain' },
    ],
    time: '昨天 22:14',
    read: true,
    link: { label: '查看项目', href: '/project/meridian-chain' },
  },
  {
    id: 'ntf-5',
    type: 'ai',
    dotTone: 'info',
    title: '今日 AI 简报已生成',
    tag: 'AI 摘要',
    text: '本期聚焦 DePIN 板块异动；新增 3 个高分机会，1 个项目被下调。',
    meta: [
      { label: '触发源', value: 'ai_brief' },
      { label: '共 1 节', value: '6 条要点' },
    ],
    time: '今天 07:30',
    read: true,
    link: { label: '查看简报', href: '/insights' },
  },
  {
    id: 'ntf-6',
    type: 'score',
    dotTone: 'success',
    title: '已将 3 个项目加入「重点追踪」',
    tag: '收藏同步',
    text: '来自发现队列：Nova Protocol、Tempo、Stable 已加入收藏，并默认进入每日简报。',
    meta: [{ label: '触发源', value: 'collections' }],
    time: '2 天前',
    read: true,
    link: { label: '查看收藏', href: '/collections' },
  },
  {
    id: 'ntf-7',
    type: 'score',
    dotTone: 'success',
    title: 'Tempo Network 评分上升 0.08',
    tag: '评分变化',
    text: '测试网活跃地址数突破 5 万，交互评分从 0.62 上调至 0.70。',
    meta: [
      { label: '触发源', value: 'opportunity_engine' },
      { label: '项目', value: 'tempo-network' },
    ],
    time: '3 天前',
    read: true,
    link: { label: '查看项目', href: '/project/tempo-network' },
  },
  {
    id: 'ntf-8',
    type: 'collector',
    dotTone: 'warning',
    title: 'coingecko 采集器速率受限',
    tag: '采集器告警',
    text: '过去 6 小时内触发 3 次 429 限流。建议配置 API Key 或降低采集频率。',
    meta: [
      { label: '触发源', value: 'collectors' },
      { label: '来源', value: 'coingecko' },
    ],
    time: '3 天前',
    read: true,
    link: { label: '运维台', href: '/ops' },
  },
];

const NAV_ITEMS: { key: NtfType; label: string; icon: typeof Inbox }[] = [
  { key: 'all', label: '全部', icon: Inbox },
  { key: 'score', label: '评分变化', icon: TrendingUp },
  { key: 'deadline', label: '截止提醒', icon: AlarmClock },
  { key: 'collector', label: '采集器', icon: Radio },
  { key: 'funding', label: '资金与融资', icon: Wallet },
  { key: 'ai', label: 'AI 摘要', icon: Sparkles },
];

export default function NotificationsPage() {
  const [activeType, setActiveType] = useState<NtfType>('all');
  const [items, setItems] = useState(NOTIFICATIONS);
  const [toast, setToast] = useState<{ message: string; type: 'success' | 'error' | 'info' } | null>(null);

  const typeCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const item of NOTIFICATIONS) {
      counts[item.type] = (counts[item.type] || 0) + 1;
      counts.all = (counts.all || 0) + 1;
    }
    return counts;
  }, []);

  const filtered = activeType === 'all' ? items : items.filter((n) => n.type === activeType);

  const unreadCount = items.filter((n) => !n.read).length;
  const scoreUpCount = items.filter((n) => n.type === 'score').length;
  const deadlineCount = items.filter((n) => n.type === 'deadline').length;
  const collectorAlertCount = items.filter((n) => n.type === 'collector' && !n.read).length;

  const handleMarkAllRead = () => {
    setItems((prev) => prev.map((n) => ({ ...n, read: true })));
    setToast({ message: '已全部标记为已读', type: 'success' });
  };

  const handleClickItem = (id: string) => {
    setItems((prev) => prev.map((n) => (n.id === id ? { ...n, read: true } : n)));
  };

  return (
    <>
      {toast && <Toast message={toast.message} type={toast.type} />}
      <TopBar title="通知中心" subtitle="interactions · 评分 · 截止 · 采集器告警">
        <button
          type="button"
          className="btn-secondary inline-flex items-center gap-1.5"
          onClick={handleMarkAllRead}
        >
          <CheckCheck className="h-4 w-4" strokeWidth={2} />
          <span className="hidden sm:inline">全部已读</span>
        </button>
        <Link href="/settings" className="btn-primary inline-flex items-center gap-1.5">
          <Bell className="h-4 w-4" strokeWidth={2} />
          <span>通知设置</span>
        </Link>
      </TopBar>

      <div className="app-content animate-fade-in">
        {/* 1. 概览统计 */}
        <section className="ntf-stats" aria-label="通知概览">
          <div className="ntf-stat">
            <span className="ntf-stat-k">未读</span>
            <span className="ntf-stat-v" data-tone="brand">{unreadCount}</span>
            <span className="ntf-stat-s">过去 24 小时</span>
          </div>
          <div className="ntf-stat">
            <span className="ntf-stat-k">评分上升</span>
            <span className="ntf-stat-v">{scoreUpCount}</span>
            <span className="ntf-stat-s">本周累计</span>
          </div>
          <div className="ntf-stat">
            <span className="ntf-stat-k">截止时间临近</span>
            <span className="ntf-stat-v" data-tone="warn">{deadlineCount}</span>
            <span className="ntf-stat-s">72 小时内</span>
          </div>
          <div className="ntf-stat">
            <span className="ntf-stat-k">采集器告警</span>
            <span className="ntf-stat-v" data-tone="err">{collectorAlertCount}</span>
            <span className="ntf-stat-s">需要处理</span>
          </div>
        </section>

        {/* 2. 侧栏筛选 + 通知列表 */}
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
                  onClick={handleMarkAllRead}
                >
                  <CheckCheck className="h-3.5 w-3.5" strokeWidth={2} />
                  <span>全部已读</span>
                </button>
              </div>
            </div>

            {filtered.length === 0 ? (
              <div className="p-8">
                <EmptyState title="暂无通知" description="当前筛选条件下没有通知" />
              </div>
            ) : (
              filtered.map((item) => (
                <div
                  key={item.id}
                  className="ntf-item"
                  data-read={item.read}
                  onClick={() => handleClickItem(item.id)}
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
