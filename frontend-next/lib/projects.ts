import { apiFetch } from './api';
import type { ProjectsResponse } from './types';

/** 单页上限与后端 `Query(20, ge=1, le=500)` 对齐 */
const PAGE_SIZE = 500;
/** 防御性上限，避免异常大的数据集把浏览器拖垮 */
const MAX_PROJECTS = 5000;
/** 分页并发上限：兼顾加载速度与后端按 IP 限流 */
const PAGE_CONCURRENCY = 3;

export interface AllProjects {
  projects: ProjectsResponse['projects'];
  /** 后端报告的总数（可能大于实际取回数量） */
  total: number;
  /** 因达到上限而未取回全部时为 true */
  truncated: boolean;
}

/**
 * 按分页取回项目，直到覆盖后端报告的 total（或触及上限）。
 *
 * 此前各页面硬编码 `?page_size=500` 且从不读取 `total`：一旦项目数超过 500，
 * 列表、统计卡、赛道分布与筛选下拉全部基于被截断的切片计算，且界面上没有
 * 任何提示。
 */
export async function fetchAllProjects(
  signal?: AbortSignal,
  options?: { curated?: boolean; persona?: string; includeHidden?: boolean },
): Promise<AllProjects> {
  const curated = options?.curated ?? false;
  // include_hidden 拼进 curatedQuery 一起带到每一页：分页时漏掉它会让第 2 页起
  // 的 total 口径和第 1 页不一致
  const curatedQuery = (curated ? '&curated=true' : '') + (options?.includeHidden ? '&include_hidden=true' : '');
  const personaQuery = options?.persona && options.persona !== 'balanced' ? `&persona=${encodeURIComponent(options.persona)}` : '';
  const first = await apiFetch<ProjectsResponse>(
    `/projects?page=1&page_size=${PAGE_SIZE}${curatedQuery}${personaQuery}`,
    {
      signal,
    },
  );
  const total = Number(first.total ?? first.projects?.length ?? 0);
  const projects = [...(first.projects || [])];

  const cap = Math.min(total, MAX_PROJECTS);
  const totalPages = Math.ceil(cap / PAGE_SIZE);
  if (totalPages > 1) {
    const pageNumbers = Array.from({ length: totalPages - 1 }, (_, i) => i + 2);
    // 按批并发（而非一次性 Promise.all 全发）：后端按 IP 限流（默认 100 次/60s），
    // 一次打 9 页 + Dashboard 其它请求，多标签页/同 NAT 下很容易 429。
    // 某页失败时停止并保留已取回的页（truncated 会如实标记），不让整个列表变空白。
    let failed = false;
    for (let i = 0; i < pageNumbers.length && !failed; i += PAGE_CONCURRENCY) {
      const batch = pageNumbers.slice(i, i + PAGE_CONCURRENCY);
      const settled = await Promise.allSettled(
        batch.map((page) =>
          apiFetch<ProjectsResponse>(
            `/projects?page=${page}&page_size=${PAGE_SIZE}${curatedQuery}${personaQuery}`,
            { signal },
          ),
        ),
      );
      // 按页序合并；遇到第一页失败即停，避免中间缺页造成顺序错乱
      for (const r of settled) {
        if (r.status === 'rejected') {
          if (signal?.aborted) throw r.reason;
          failed = true;
          break;
        }
        if (r.value?.projects?.length) {
          projects.push(...r.value.projects);
        }
      }
    }
  }

  return { projects, total, truncated: projects.length < total };
}
