'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useEffect, useState } from 'react';
import {
  Radar, SatelliteDish, LineChart, ClipboardCheck, ServerCog,
  Bell, Archive, Bookmark, Settings, Sun, Moon, CheckCheck, Ban,
} from 'lucide-react';
import { fetchHealth } from '@/lib/api';
import type { HealthData } from '@/lib/types';
import { useTheme } from './ThemeProvider';

/** 导航项：icon 对齐设计稿 data-lucide 属性 */
const navItems = [
  { href: '/', label: '工作台', icon: Radar },
  { href: '/discoveries', label: '发现队列', icon: SatelliteDish },
  { href: '/insights', label: '洞察', icon: LineChart },
  { href: '/portfolio', label: '参与复盘', icon: ClipboardCheck },
  { href: '/review', label: '结果复盘', icon: CheckCheck },
  { href: '/ops', label: '运维台', icon: ServerCog },
  { href: '/notifications', label: '通知中心', icon: Bell },
  { href: '/archive', label: '归档历史', icon: Archive },
  { href: '/collections', label: '收藏关注', icon: Bookmark },
  { href: '/skipped', label: '不参与', icon: Ban },
  { href: '/settings', label: '系统设置', icon: Settings },
];

export function Nav() {
  const pathname = usePathname();
  const { theme, toggle } = useTheme();
  const [health, setHealth] = useState<HealthData | null>(null);

  useEffect(() => {
    let cancelled = false;
    // 探 /health 而不是 /collections/sources：后者是业务接口，探它既不准确
    // 又会平白占用限流配额。/health 自身返回 ok 字段，直接采信。
    fetchHealth()
      .then((data) => {
        if (!cancelled) setHealth(data as HealthData);
      })
      .catch(() => {
        if (!cancelled) setHealth({ ok: false, status: 'down' });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <aside className="app-sidebar">
      {/* ── 品牌 ── */}
      <Link href="/" className="app-sidebar-brand">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-gradient-to-tr from-emerald-500 to-cyan-400 text-slate-950 shadow-lg shadow-emerald-500/25">
          <Radar className="h-5 w-5" strokeWidth={2.4} />
        </span>
        <div className="app-sidebar-brand-text leading-tight">
          <div className="text-sm font-bold tracking-tight text-ink flex items-center gap-1.5">
            <span>空投阿尔法</span>
            <span className="h-1.5 w-1.5 rounded-full bg-farm animate-pulse" />
          </div>
          <div className="font-mono text-[10px] tracking-wider text-ink-faint uppercase">Alpha Terminal</div>
        </div>
      </Link>

      {/* ── 导航 ── */}
      <nav className="app-sidebar-nav" aria-label="主导航">
        {navItems.map((item) => {
          const active = pathname === item.href || (item.href !== '/' && pathname.startsWith(item.href));
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`app-sidebar-nav-item group relative ${active ? 'active font-semibold' : ''}`}
            >
              <Icon className="h-5 w-5 shrink-0 transition-transform group-hover:scale-110" strokeWidth={active ? 2.3 : 1.9} />
              <span className="app-sidebar-nav-label">{item.label}</span>
              {active && (
                <span className="ml-auto h-1.5 w-1.5 rounded-full bg-farm shadow-sm shadow-farm" />
              )}
            </Link>
          );
        })}
      </nav>

      {/* ── 主题切换 ── */}
      <button
        type="button"
        onClick={toggle}
        className="app-sidebar-nav-item"
        aria-label="切换主题"
        title="切换主题"
      >
        {theme === 'dark'
          ? <Sun className="h-5 w-5 shrink-0 text-amber-400" strokeWidth={2} />
          : <Moon className="h-5 w-5 shrink-0 text-slate-600" strokeWidth={2} />}
        <span className="app-sidebar-nav-label">{theme === 'dark' ? '浅色模式' : '深色模式'}</span>
      </button>

      {/* ── 弹性间隔 ── */}
      <div className="flex-1" />

      {/* ── 底部：接口状态 + 引擎徽章 ── */}
      <div className="app-sidebar-footer">
        <div className="app-sidebar-api">
          <span
            className={`h-2 w-2 shrink-0 rounded-full ${
              health === null ? 'bg-ink-faint' : health.ok ? 'bg-farm animate-pulse' : 'bg-red-500'
            }`}
          />
          <span className="app-sidebar-footer-text text-xs text-ink-muted">
            {health === null ? '检测中…' : health.ok ? '接口在线' : '接口异常'}
          </span>
          <span className="app-sidebar-footer-text ml-auto font-mono text-[11px] text-ink-faint">v1.4.2</span>
        </div>
        <div className="app-sidebar-engine-badges">
          <span className="app-sidebar-engine-chip font-mono text-[10px] border-emerald-500/30 text-emerald-400 dark:bg-emerald-500/10">score-v1.4 · 权威</span>
          <span className="app-sidebar-engine-chip font-mono text-[10px] border-cyan-500/30 text-cyan-400 dark:bg-cyan-500/10">opp-v2.0 · 影子</span>
        </div>
      </div>
    </aside>
  );
}
