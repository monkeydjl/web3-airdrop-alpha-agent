'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useEffect, useState } from 'react';
import { Radar, Sun, Moon, LineChart, ServerCog } from 'lucide-react';
import { fetchHealth } from '@/lib/api';
import type { HealthData } from '@/lib/types';
import { useTheme } from './ThemeProvider';

/** 导航项：icon 对齐设计稿 data-lucide 属性 */
const links = [
  { href: '/', label: '工作台', icon: Radar },
  { href: '/insights', label: '洞察', icon: LineChart },
  { href: '/ops', label: '运维', icon: ServerCog },
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
            <span className="flex h-8 w-8 items-center justify-center rounded-md bg-farm text-white">
              <Radar className="h-[18px] w-[18px]" strokeWidth={2.2} />
            </span>
            <div className="leading-tight">
              <div className="text-sm font-semibold tracking-tight text-ink group-hover:text-farm dark:group-hover:text-farm">
                空投阿尔法
              </div>
              <div className="hidden font-mono text-[10px] tracking-wide text-ink-faint sm:block">
                早期项目雷达
              </div>
            </div>
          </Link>

          <nav className="hidden items-center gap-1 sm:flex">
            {links.map((l) => {
              const active = pathname === l.href || (l.href !== '/' && pathname.startsWith(l.href));
              const Icon = l.icon;
              return (
                <Link
                  key={l.href}
                  href={l.href}
                  className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition ${
                    active
                      ? 'bg-farm-soft text-farm dark:bg-farm/15 dark:text-farm'
                      : 'text-ink-muted hover:bg-surface-2 hover:text-ink'
                  }`}
                >
                  <Icon className="h-4 w-4" strokeWidth={2} />
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
                ? 'border-farm/30 bg-farm-soft/60 text-farm dark:bg-farm/10 dark:text-farm'
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
            {theme === 'dark' ? <Sun className="h-[18px] w-[18px]" /> : <Moon className="h-[18px] w-[18px]" />}
          </button>
        </div>
      </div>

      <div className="flex gap-1 overflow-x-auto border-t border-line/60 px-3 py-1.5 sm:hidden">
        {links.map((l) => {
          const active = pathname === l.href || (l.href !== '/' && pathname.startsWith(l.href));
          const Icon = l.icon;
          return (
            <Link
              key={l.href}
              href={l.href}
              className={`flex items-center gap-1 whitespace-nowrap rounded-md px-3 py-1 text-xs font-medium ${
                active ? 'bg-farm-soft text-farm dark:bg-farm/15 dark:text-farm' : 'text-ink-muted'
              }`}
            >
              <Icon className="h-3.5 w-3.5" strokeWidth={2} />
              {l.label}
            </Link>
          );
        })}
      </div>
    </header>
  );
}
