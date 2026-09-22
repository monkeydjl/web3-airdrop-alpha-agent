'use client';

import { useEffect, useMemo, useState } from 'react';
import { apiFetch } from '@/lib/api';
import { StatCard } from './ui';

export interface CalendarEvent {
  id: string;
  project_id: string;
  project_name: string;
  sector?: string;
  label?: string;
  score?: number;
  event_type: 'tge' | 'snapshot' | 'claim' | 'testnet';
  event_type_zh: string;
  title: string;
  description: string;
  deadline_iso: string;
  hours_remaining: number;
  days_remaining: number;
  urgency: 'urgent' | 'soon' | 'normal';
}

const TYPE_TAGS: Record<string, { bg: string; text: string; border: string }> = {
  snapshot: { bg: 'bg-rose-500/10', text: 'text-rose-400', border: 'border-rose-500/30' },
  tge: { bg: 'bg-brand-500/10', text: 'text-brand-400', border: 'border-brand-500/30' },
  claim: { bg: 'bg-emerald-500/10', text: 'text-emerald-400', border: 'border-emerald-500/30' },
  testnet: { bg: 'bg-cyan-500/10', text: 'text-cyan-400', border: 'border-cyan-500/30' },
};

export function AirdropCalendarPanel() {
  const [events, setEvents] = useState<CalendarEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [filterType, setFilterType] = useState<string>('all');

  const fetchEvents = async () => {
    setLoading(true);
    try {
      const res = await apiFetch<{ ok: boolean; data: { events: CalendarEvent[]; total: number } }>(
        '/calendar/events',
      );
      if (res?.data?.events) {
        setEvents(res.data.events);
      }
    } catch {
      // 捕获异常
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchEvents();
  }, []);

  const urgentCount = events.filter((e) => e.urgency === 'urgent').length;
  const soonCount = events.filter((e) => e.urgency === 'soon').length;

  const filtered = useMemo(() => {
    if (filterType === 'all') return events;
    return events.filter((e) => e.event_type === filterType);
  }, [events, filterType]);

  const handleExportIcs = () => {
    window.open('/api/v1/calendar/export.ics', '_blank');
  };

  return (
    <div className="space-y-6 animate-fade-in">
      {/* 顶部统计卡片 */}
      <div className="stat-grid">
        <StatCard label="总里程碑事件" value={events.length} accent="brand" hint="全库已收录时间节点" />
        <StatCard label="48h 紧急截止" value={urgentCount} accent="watch" hint="快照/认领倒计时中" />
        <StatCard label="7天内临近" value={soonCount} accent="farm" hint="即将结算重点项目" />
        <div className="dash-card p-4 flex flex-col justify-between items-start">
          <div>
            <span className="text-xs font-semibold text-ink-muted">手机/系统日历同步</span>
            <div className="text-sm font-bold text-ink mt-0.5">Google / Apple 日历</div>
          </div>
          <button
            type="button"
            onClick={handleExportIcs}
            className="btn-primary !py-1.5 !px-3 text-xs w-full mt-2 flex items-center justify-center gap-1.5 shadow-md shadow-brand-500/20"
          >
            <span>📅 导出/订阅 (.ics)</span>
          </button>
        </div>
      </div>

      {/* 过滤器与动作栏 */}
      <div className="dash-card p-4 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs font-semibold text-ink-muted mr-1">类型筛选:</span>
          {[
            { id: 'all', label: '全部事件' },
            { id: 'snapshot', label: '📸 快照截止' },
            { id: 'tge', label: '🚀 TGE 发币' },
            { id: 'testnet', label: '🧪 测试网结算' },
            { id: 'claim', label: '🎁 空投认领' },
          ].map((tab) => (
            <button
              key={tab.id}
              type="button"
              onClick={() => setFilterType(tab.id)}
              className={`px-3 py-1 rounded-xl text-xs font-medium transition ${
                filterType === tab.id
                  ? 'bg-brand-500 text-white shadow-sm'
                  : 'bg-surface-2 text-ink-muted hover:text-ink hover:bg-surface-2/80'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        <button
          type="button"
          onClick={fetchEvents}
          disabled={loading}
          className="text-xs text-brand-400 hover:text-brand-300 disabled:opacity-50"
        >
          {loading ? '加载中...' : '刷新日程 ⟳'}
        </button>
      </div>

      {/* 紧急提醒横幅（如果有 48h 紧急事件） */}
      {urgentCount > 0 && (
        <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 p-3.5 flex items-center gap-3 animate-pulse">
          <span className="text-xl">🚨</span>
          <div className="text-xs">
            <span className="font-bold text-rose-400">紧迫预警：</span>
            <span className="text-ink">
              共有 <strong>{urgentCount}</strong> 个关键快照/认领节点将在 48 小时内截止，请务必提前完成交互或防女巫申诉！
            </span>
          </div>
        </div>
      )}

      {/* 事件时间轴卡片列表 */}
      <div className="space-y-3">
        {filtered.map((item) => {
          const typeStyle = TYPE_TAGS[item.event_type] || TYPE_TAGS.tge;
          const isUrgent = item.urgency === 'urgent';
          return (
            <div
              key={item.id}
              className={`dash-card p-4 transition duration-200 flex flex-col md:flex-row md:items-center justify-between gap-4 ${
                isUrgent ? 'border-rose-500/40 shadow-[0_0_15px_rgba(244,63,94,0.1)]' : ''
              }`}
            >
              <div className="space-y-1.5 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span
                    className={`text-[10px] font-mono font-semibold px-2 py-0.5 rounded-full border ${typeStyle.border} ${typeStyle.bg} ${typeStyle.text}`}
                  >
                    {item.event_type_zh}
                  </span>
                  <span className="text-sm font-bold text-ink">{item.title}</span>
                  <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-surface-2 text-ink-muted border border-line">
                    {item.project_name} · {item.sector || 'Web3'}
                  </span>
                </div>
                <p className="text-xs text-ink-muted leading-relaxed">{item.description}</p>
              </div>

              <div className="flex items-center gap-4 shrink-0 self-end md:self-auto border-t md:border-t-0 border-line/60 pt-2 md:pt-0">
                <div className="text-right">
                  <div className="text-[10px] text-ink-faint">截止预计时间</div>
                  <div className="font-mono text-xs text-ink">
                    {new Date(item.deadline_iso).toLocaleDateString()}
                  </div>
                </div>

                <div
                  className={`px-3 py-1.5 rounded-xl border text-center min-w-[90px] ${
                    isUrgent
                      ? 'bg-rose-500/20 text-rose-300 border-rose-500/40 animate-pulse'
                      : item.urgency === 'soon'
                      ? 'bg-amber-500/10 text-amber-300 border-amber-500/30'
                      : 'bg-surface-2 text-ink border-line'
                  }`}
                >
                  <div className="font-mono text-sm font-bold">
                    {item.days_remaining > 1 ? `${item.days_remaining} 天` : `${item.hours_remaining} 小时`}
                  </div>
                  <div className="text-[9px] uppercase tracking-wider opacity-80">
                    {isUrgent ? '紧急倒计时' : '剩余时间'}
                  </div>
                </div>
              </div>
            </div>
          );
        })}

        {filtered.length === 0 && (
          <div className="dash-card p-12 text-center text-ink-faint text-xs">
            暂无该分类的里程碑事件
          </div>
        )}
      </div>
    </div>
  );
}
