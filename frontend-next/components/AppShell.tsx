'use client';

import { useState, useEffect, useCallback } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { Radar, Sun, Moon, LineChart, ServerCog } from 'lucide-react';
import { fetchHealth } from '@/lib/api';

const NAV_ITEMS = [
  { href: '/', label: '工作台', icon: Radar },
  { href: '/insights', label: '洞察', icon: LineChart },
  { href: '/ops', label: '运维', icon: ServerCog },
];

export default function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [theme, setTheme] = useState<'light' | 'dark'>('light');
  const [health, setHealth] = useState<{ ok: boolean; status: string }>({ ok: false, status: 'loading' });

  // Theme init
  useEffect(() => {
    const saved = localStorage.getItem('aa-theme-v2');
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    const initial = saved === 'dark' || (!saved && prefersDark) ? 'dark' : 'light';
    setTheme(initial);
    document.documentElement.classList.toggle('dark', initial === 'dark');
  }, []);

  // Health check
  useEffect(() => {
    const check = async () => {
      try {
        const h = await fetchHealth();
        setHealth({ ok: h.ok, status: h.status });
      } catch {
        setHealth({ ok: false, status: 'down' });
      }
    };
    check();
    const timer = setInterval(check, 30_000);
    return () => clearInterval(timer);
  }, []);

  const toggleTheme = useCallback(() => {
    const next = theme === 'light' ? 'dark' : 'light';
    setTheme(next);
    localStorage.setItem('aa-theme-v2', next);
    document.documentElement.classList.toggle('dark', next === 'dark');
  }, [theme]);

  const healthClass = health.ok ? 'ok' : health.status === 'degraded' ? 'degraded' : 'down';
  const healthLabel = health.ok ? 'API 正常' : health.status === 'degraded' ? 'API 降级' : 'API 离线';

  return (
    <div className="min-h-screen bg-canvas">
      {/* ── Top Nav ── */}
      <nav className="sticky top-0 z-40 h-14 border-b border-line bg-surface/80 backdrop-blur-md">
        <div className="mx-auto flex h-full max-w-[1280px] items-center justify-between px-4">
          {/* Logo */}
          <Link href="/" className="flex items-center gap-2 text-lg font-semibold text-ink">
            <span className="flex h-8 w-8 items-center justify-center rounded-md bg-farm text-white">
              <Radar className="h-[18px] w-[18px]" strokeWidth={2.2} />
            </span>
            <span className="hidden sm:inline">空投阿尔法</span>
          </Link>

          {/* Desktop Nav */}
          <div className="hidden items-center gap-1 sm:flex">
            {NAV_ITEMS.map((item) => {
              const active = pathname === item.href || (item.href !== '/' && pathname.startsWith(item.href));
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={`rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
                    active
                      ? 'bg-surface-3 text-ink'
                      : 'text-ink-muted hover:bg-surface-2 hover:text-ink'
                  }`}
                >
                  {item.label}
                </Link>
              );
            })}
          </div>

          {/* Right side */}
          <div className="flex items-center gap-3">
            {/* Health pill */}
            <span className={`health-pill ${healthClass}`}>
              <span className={`h-1.5 w-1.5 rounded-full ${
                health.ok ? 'bg-farm' : health.status === 'degraded' ? 'bg-watch' : 'bg-red-500'
              }`} />
              {healthLabel}
            </span>

            {/* Theme toggle */}
            <button
              onClick={toggleTheme}
              className="btn-ghost btn-sm"
              aria-label={theme === 'light' ? '切换到深色模式' : '切换到浅色模式'}
            >
              {theme === 'light' ? <Moon className="h-[18px] w-[18px]" /> : <Sun className="h-[18px] w-[18px]" />}
            </button>
          </div>
        </div>
      </nav>

      {/* ── Mobile Bottom Nav ── */}
      <div className="fixed bottom-0 left-0 right-0 z-40 border-t border-line bg-surface sm:hidden">
        <div className="flex items-center justify-around py-2">
          {NAV_ITEMS.map((item) => {
            const active = pathname === item.href || (item.href !== '/' && pathname.startsWith(item.href));
            const Icon = item.icon;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`flex flex-col items-center gap-0.5 px-3 py-1 text-xs ${
                  active ? 'text-farm' : 'text-ink-muted'
                }`}
              >
                <Icon className="h-5 w-5" strokeWidth={2} />
                {item.label}
              </Link>
            );
          })}
        </div>
      </div>

      {/* ── Main Content ── */}
      <main className="mx-auto max-w-[1280px] px-4 py-6 pb-20 sm:pb-6">
        {children}
      </main>
    </div>
  );
}
