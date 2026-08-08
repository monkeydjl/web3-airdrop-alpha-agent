import { apiFetch } from './api';
import type { ProjectsResponse } from './types';

/** 单页上限与后端 `Query(20, ge=1, le=500)` 对齐 */
const PAGE_SIZE = 500;
/** 防御性上限，避免异常大的数据集把浏览器拖垮 */
const MAX_PROJECTS = 5000;

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
export async function fetchAllProjects(signal?: AbortSignal): Promise<AllProjects> {
  const first = await apiFetch<ProjectsResponse>(`/projects?page=1&page_size=${PAGE_SIZE}`, {
    signal,
  });
  const total = Number(first.total ?? first.projects?.length ?? 0);
  const projects = [...(first.projects || [])];

  const cap = Math.min(total, MAX_PROJECTS);
  let page = 2;
  while (projects.length < cap) {
    const next = await apiFetch<ProjectsResponse>(`/projects?page=${page}&page_size=${PAGE_SIZE}`, {
      signal,
    });
    const batch = next.projects || [];
    if (batch.length === 0) break;
    projects.push(...batch);
    page += 1;
  }

  return { projects, total, truncated: projects.length < total };
}
