'use client';

import { apiFetch } from '@/lib/api';
import { useRouter } from 'next/navigation';
import { useCallback, useEffect, useMemo, useState } from 'react';

/**
 * 详情页项目切换栏：‹ 上一个 / 项目下拉跳选 / 下一个 ›,外加 ←/→ 快捷键。
 *
 * 排序与工作台同口径：score 降序（同分时这些页面邻居与工作台的次序可能略有
 * 出入，属正常——工作台的并列部分本身没有确定性 tiebreak）。
 *
 * 邻接关系在前端算：列表接口 page_size≤500，全量项目两页放不完才翻页；
 * 不为「上一个/下一个」单开一个后端端点 —— 同样的数据端点一次拉齐，
 * 前端取前后邻即可，少一个端点少一份鉴权/文档成本。
 */

interface ProjectLite {
  id: string;
  name?: string;
  score?: number;
  label?: string;
}

interface ProjectsPage {
  projects?: ProjectLite[];
  total?: number;
}

const PAGE_SIZE = 500;

export function ProjectSwitcher({ projectId }: { projectId: string }) {
  const router = useRouter();
  const [items, setItems] = useState<ProjectLite[]>([]);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const all: ProjectLite[] = [];
        let page = 1;
        for (;;) {
          const res = await apiFetch<ProjectsPage>(
            `/projects?page=${page}&page_size=${PAGE_SIZE}&sort_by=score&sort_order=desc`,
          );
          const batch = res.projects || [];
          all.push(...batch);
          if (batch.length < PAGE_SIZE || all.length >= (res.total || all.length)) break;
          page += 1;
        }
        if (!cancelled) setItems(all);
      } catch {
        if (!cancelled) setFailed(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const { index, prev, next } = useMemo(() => {
    const idx = items.findIndex((p) => p.id === projectId);
    return {
      index: idx,
      prev: idx > 0 ? items[idx - 1] : null,
      next: idx >= 0 && idx < items.length - 1 ? items[idx + 1] : null,
    };
  }, [items, projectId]);

  const jump = useCallback(
    (id: string) => {
      if (id && id !== projectId) router.push(`/project/${id}`);
    },
    [projectId, router],
  );

  // 键盘 ←/→ 切换：输入控件聚焦时不抢键
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (
        t &&
        (t.tagName === 'INPUT' ||
          t.tagName === 'TEXTAREA' ||
          t.tagName === 'SELECT' ||
          t.isContentEditable)
      ) {
        return;
      }
      if (e.key === 'ArrowLeft' && prev) jump(prev.id);
      else if (e.key === 'ArrowRight' && next) jump(next.id);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [prev, next, jump]);

  // 拉取失败时静默收起，不挡详情页本体
  if (failed) return null;

  return (
    <div className="mb-5 flex items-center gap-2">
      <button
        type="button"
        className="btn-secondary min-h-8 max-w-[16rem] px-2.5 py-1.5 text-xs"
        disabled={!prev}
        onClick={() => prev && jump(prev.id)}
        title={prev ? `上一个：${prev.name ?? prev.id}` : '已到第一个'}
        aria-label="上一个项目"
      >
        <span aria-hidden>‹ </span>
        <span className="truncate">{prev?.name ?? '没有了'}</span>
      </button>

      <select
        className="select min-w-0 flex-1 !py-1.5 text-xs"
        value={projectId}
        onChange={(e) => jump(e.target.value)}
        aria-label="切换项目"
      >
        {index < 0 ? (
          <option value={projectId}>当前项目</option>
        ) : null}
        {items.map((p) => (
          <option key={p.id} value={p.id}>
            {p.score ?? '—'} · {p.name ?? p.id}
          </option>
        ))}
      </select>

      <button
        type="button"
        className="btn-secondary min-h-8 max-w-[16rem] px-2.5 py-1.5 text-xs"
        disabled={!next}
        onClick={() => next && jump(next.id)}
        title={next ? `下一个：${next.name ?? next.id}` : '已到最后一个'}
        aria-label="下一个项目"
      >
        <span className="truncate">{next?.name ?? '没有了'}</span>
        <span aria-hidden> ›</span>
      </button>
    </div>
  );
}
