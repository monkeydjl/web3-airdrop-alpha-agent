'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useEffect, useState } from 'react';
import { fetchHealth } from '@/lib/api';
import type { HealthData } from '@/lib/types';
import { useTheme } from './ThemeProvider';

const links = [
  { href: '/', label: '工作台', icon: '◈' },
  { href: '/insights', label: '洞察', icon: '◎' },
  { href: '/ops', label: '运维', icon: '⬡' },
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
    <header className="sticky top-0 z-50 border-b border-line/80 bg-surface/80 backdrop-blur-xl">
      <div className="mx-auto flex h-14 max-w-7xl items-center justify-between gap-4 px-4 sm:px-6">
        <div className="flex items-center gap-6">
          <Link href="/" className="group flex items-center gap-2.5">
            <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-gradient-to-br from-brand-500 to-brand-700 text-sm font-bold text-white shadow-glow">
              α
            </span>
            <div className="leading-tight">
              <div className="text-sm font-bold tracking-tight text-ink group-hover:text-brand-600 dark:group-hover:text-brand-300">
                空投阿尔法
              </div>
              <div className="hidden text-[10px] text-ink-faint sm:block">Web3 早期项目雷达</div>
            </div>
          </Link>

          <nav className="hidden items-center gap-1 sm:flex">
            {links.map((l) => {
              const active = pathname === l.href || (l.href !== '/' && pathname.startsWith(l.href));
              return (
                <Link
                  key={l.href}
                  href={l.href}
                  className={`rounded-lg px-3 py-1.5 text-sm font-medium transition ${
                    active
                      ? 'bg-brand-50 text-brand-700 dark:bg-brand-500/15 dark:text-brand-300'
                      : 'text-ink-muted hover:bg-surface-2 hover:text-ink'
                  }`}
                >
                  <span className="mr-1.5 opacity-60">{l.icon}</span>
                  {l.label}
                </Link>
              );
            })}
          </nav>
        </div>

        <div className="flex items-center gap-2">
          <div
            className={`hidden items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-medium sm:flex ${
              health?.ok
                ? 'border-farm/30 bg-farm-soft/60 text-farm-dark dark:bg-farm/10 dark:text-farm'
                : 'border-line bg-surface-2 text-ink-faint'
            }`}
            title="接口状态"
          >
            <span
              className={`h-1.5 w-1.5 rounded-full ${
                health === null ? 'bg-ink-faint' : health.ok ? 'bg-farm' : 'bg-red-500'
              }`}
            />
            {health === null ? '接口检测中…' : health.ok ? '接口在线' : '接口异常'}
          </div>

          <button
            type="button"
            onClick={toggle}
            className="btn-ghost h-9 w-9 !p-0"
            aria-label="切换主题"
            title="切换主题"
          >
            {theme === 'dark' ? '☀' : '☾'}
          </button>
        </div>
      </div>

      <div className="flex gap-1 overflow-x-auto border-t border-line/60 px-3 py-1.5 sm:hidden">
        {links.map((l) => {
          const active = pathname === l.href || (l.href !== '/' && pathname.startsWith(l.href));
          return (
            <Link
              key={l.href}
              href={l.href}
              className={`whitespace-nowrap rounded-lg px-3 py-1 text-xs font-medium ${
                active ? 'bg-brand-50 text-brand-700 dark:bg-brand-500/15' : 'text-ink-muted'
              }`}
            >
              {l.label}
            </Link>
          );
        })}
      </div>
    </header>
  );
}
