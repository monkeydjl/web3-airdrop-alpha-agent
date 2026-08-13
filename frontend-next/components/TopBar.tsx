'use client';

import { Search } from 'lucide-react';
import { useRouter } from 'next/navigation';
import type { ReactNode } from 'react';
import { useState } from 'react';

interface TopBarProps {
  title: string;
  subtitle?: ReactNode;
  /** 右侧操作区（按钮等） */
  children?: ReactNode;
}

/**
 * 统一顶栏 — 对齐设计稿 .app-topbar
 * sticky 64px，左侧标题+副标题，右侧全局搜索 + 页面操作 slot
 */
export function TopBar({ title, subtitle, children }: TopBarProps) {
  const router = useRouter();
  const [q, setQ] = useState('');

  const onSearch = (e: React.FormEvent) => {
    e.preventDefault();
    const keyword = q.trim();
    router.push(keyword ? `/?keyword=${encodeURIComponent(keyword)}` : '/');
  };

  return (
    <header className="app-topbar">
      <div className="app-topbar-titles">
        <h1 className="app-page-title">{title}</h1>
        {subtitle ? <p className="app-page-subtitle">{subtitle}</p> : null}
      </div>
      <div className="app-topbar-right">
        <form onSubmit={onSearch} className="app-search" role="search">
          <Search className="h-4 w-4 shrink-0 text-ink-faint" strokeWidth={2} />
          <input
            type="text"
            placeholder="搜索项目 / 赛道…"
            aria-label="全局搜索"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
        </form>
        {children}
      </div>
    </header>
  );
}
