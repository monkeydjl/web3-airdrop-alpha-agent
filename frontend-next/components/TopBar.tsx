'use client';

import { Search, X, CornerDownLeft } from 'lucide-react';
import { useRouter } from 'next/navigation';
import type { ReactNode } from 'react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { fetchAllProjects } from '@/lib/projects';
import { LABEL_ZH, labelStyles } from '@/lib/format';
import type { Label, Project } from '@/lib/types';
import { isAbortError } from '@/lib/api';

interface TopBarProps {
  title: string;
  subtitle?: ReactNode;
  /** 右侧操作区（按钮等） */
  children?: ReactNode;
}

/** 搜索结果最大显示条数 */
const MAX_RESULTS = 8;
/** 防抖延迟（ms） */
const DEBOUNCE_MS = 200;

/** 全局项目缓存：多个 TopBar 实例共享，避免每页重复拉取 */
let projectCache: Project[] | null = null;
let cachePromise: Promise<Project[]> | null = null;

async function loadProjects(): Promise<Project[]> {
  if (projectCache) return projectCache;
  if (cachePromise) return cachePromise;
  cachePromise = fetchAllProjects()
    .then((res) => {
      projectCache = res.projects;
      return res.projects;
    })
    .catch((err) => {
      cachePromise = null;
      // 无论何种失败原因都缓存空数组，使后续搜索能展示
      // "无匹配项目" 而非一直不发下拉面板
      projectCache = [];
      if (isAbortError(err)) return [];
      // 静默失败：搜索是辅助功能，不应阻断页面
      return [];
    });
  return cachePromise;
}

interface SearchResult {
  project: Project;
  /** 匹配字段 */
  matchedOn: 'name' | 'sector' | 'label';
}

function searchProjects(projects: Project[], query: string): SearchResult[] {
  const q = query.toLowerCase().trim();
  if (!q) return [];

  const labelMatch = (Object.entries(LABEL_ZH) as [Label, string][])
    .filter(([, zh]) => zh.toLowerCase().includes(q))
    .map(([label]) => label);

  const results: SearchResult[] = [];

  for (const p of projects) {
    // 名称匹配（优先级最高）
    if (p.name?.toLowerCase().includes(q)) {
      results.push({ project: p, matchedOn: 'name' });
      continue;
    }
    // 赛道匹配
    if (p.sector?.toLowerCase().includes(q)) {
      results.push({ project: p, matchedOn: 'sector' });
      continue;
    }
    // 标签匹配（中文 / 英文）
    if (labelMatch.includes(p.label)) {
      results.push({ project: p, matchedOn: 'label' });
      continue;
    }
  }

  // 按分数降序排列
  results.sort((a, b) => (b.project.score ?? 0) - (a.project.score ?? 0));
  return results.slice(0, MAX_RESULTS);
}

/**
 * 统一顶栏 — 对齐设计稿 .app-topbar
 * sticky 64px，左侧标题+副标题，右侧全局搜索 + 页面操作 slot
 *
 * 搜索框支持：
 * - 输入时实时展示匹配项目（名称/赛道/标签）
 * - 键盘 ↑↓ 导航、Enter 跳转详情、Esc 关闭
 * - 点击结果跳转 /project/[id]
 * - 空输入隐藏面板
 */
export function TopBar({ title, subtitle, children }: TopBarProps) {
  const router = useRouter();
  const [q, setQ] = useState('');
  const [open, setOpen] = useState(false);
  const [results, setResults] = useState<SearchResult[]>([]);
  const [activeIndex, setActiveIndex] = useState(-1);
  const [loading, setLoading] = useState(false);

  const containerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const debounceTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // 首次聚焦时加载项目数据
  const ensureProjects = useCallback(async () => {
    if (projectCache) return;
    setLoading(true);
    await loadProjects();
    setLoading(false);
  }, []);

  // 防抖搜索
  useEffect(() => {
    if (debounceTimer.current) clearTimeout(debounceTimer.current);

    const query = q.trim();
    if (!query) {
      setResults([]);
      setOpen(false);
      setActiveIndex(-1);
      return;
    }

    debounceTimer.current = setTimeout(async () => {
      await ensureProjects();
      if (projectCache) {
        setResults(searchProjects(projectCache, query));
        setOpen(true);
        setActiveIndex(-1);
      }
    }, DEBOUNCE_MS);

    return () => {
      if (debounceTimer.current) clearTimeout(debounceTimer.current);
    };
  }, [q, ensureProjects]);

  // 点击外部关闭
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  // 键盘导航
  const onKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (!open || results.length === 0) {
        if (e.key === 'Enter') {
          const keyword = q.trim();
          if (keyword) router.push(`/?keyword=${encodeURIComponent(keyword)}`);
        }
        return;
      }

      if (e.key === 'ArrowDown') {
        e.preventDefault();
        setActiveIndex((i) => (i + 1) % results.length);
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        setActiveIndex((i) => (i <= 0 ? results.length - 1 : i - 1));
      } else if (e.key === 'Enter') {
        e.preventDefault();
        const idx = activeIndex >= 0 ? activeIndex : 0;
        const project = results[idx]?.project;
        if (project) {
          router.push(`/project/${project.id}`);
          setOpen(false);
          setQ('');
        }
      } else if (e.key === 'Escape') {
        e.preventDefault();
        setOpen(false);
        inputRef.current?.blur();
      }
    },
    [open, results, activeIndex, q, router],
  );

  const selectProject = useCallback(
    (project: Project) => {
      router.push(`/project/${project.id}`);
      setOpen(false);
      setQ('');
    },
    [router],
  );

  const clearSearch = useCallback(() => {
    setQ('');
    setResults([]);
    setOpen(false);
    inputRef.current?.focus();
  }, []);

  const hasQuery = q.trim().length > 0;

  return (
    <header className="app-topbar">
      <div className="app-topbar-titles">
        <h1 className="app-page-title">{title}</h1>
        {subtitle ? <p className="app-page-subtitle">{subtitle}</p> : null}
      </div>
      <div className="app-topbar-right">
        <div className="app-search-wrapper" ref={containerRef}>
          <div className="app-search" role="search">
            <Search className="h-4 w-4 shrink-0 text-ink-faint" strokeWidth={2} />
            <input
              ref={inputRef}
              type="text"
              placeholder="搜索项目 / 赛道 / 标签…"
              aria-label="全局搜索"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              onFocus={ensureProjects}
              onKeyDown={onKeyDown}
              role="combobox"
              aria-expanded={open}
              aria-controls="search-results"
              aria-autocomplete="list"
            />
            {hasQuery && (
              <button
                type="button"
                onClick={clearSearch}
                className="app-search-clear"
                aria-label="清除搜索"
              >
                <X className="h-3.5 w-3.5" strokeWidth={2} />
              </button>
            )}
          </div>

          {open && (
            <div className="app-search-dropdown" id="search-results" role="listbox">
              {loading && results.length === 0 && (
                <div className="app-search-empty">加载中…</div>
              )}
              {!loading && results.length === 0 && (
                <div className="app-search-empty">无匹配项目</div>
              )}
              {results.map((r, i) => {
                const ls = labelStyles(r.project.label);
                return (
                  <button
                    key={r.project.id}
                    type="button"
                    className={`app-search-result ${i === activeIndex ? 'active' : ''}`}
                    onClick={() => selectProject(r.project)}
                    onMouseEnter={() => setActiveIndex(i)}
                    role="option"
                    aria-selected={i === activeIndex}
                  >
                    <div className="app-search-result-main">
                      <span className="app-search-result-name">{r.project.name}</span>
                      {r.project.sector && (
                        <span className="app-search-result-sector">{r.project.sector}</span>
                      )}
                    </div>
                    <div className="app-search-result-meta">
                      <span className={`app-search-result-label ${ls.badge}`}>
                        {LABEL_ZH[r.project.label] ?? r.project.label}
                      </span>
                      <span className="app-search-result-score">
                        {r.project.score != null ? r.project.score.toFixed(2) : '—'}
                      </span>
                    </div>
                  </button>
                );
              })}
              {results.length > 0 && (
                <div className="app-search-hint">
                  <CornerDownLeft className="h-3 w-3" strokeWidth={2} />
                  <span>跳转到项目详情</span>
                </div>
              )}
            </div>
          )}
        </div>
        {children}
      </div>
    </header>
  );
}
