'use client';

import { TopBar } from '@/components/TopBar';
import { useCallback } from 'react';
import { AlertTriangle, CheckCircle2, RefreshCw } from 'lucide-react';
import { apiFetch } from '@/lib/api';
import { useAsyncData } from '@/lib/useAsyncData';

/**
 * 归档策略页。
 *
 * 数字全部来自后端 `GET /archive/runs`：六档保留策略的真实行数与待清理量、
 * 归档调度配置、以及每次归档运行的历史（含失败）。
 *
 * 此页此前只有一句"暂无运行历史接口"的占位 —— 那个占位揭出的是真缺陷：
 * `app/archive.py` 的归档逻辑是真的，但没有任何调度会调用它。现在归档由
 * `UnifiedScheduler` 按 ARCHIVE_CRON 执行，每次运行都记入 archive_runs。
 */
interface ArchivePolicy {
  key: string;
  table: string;
  label: string;
  retention_days: number;
  action: 'archive' | 'delete';
  total: number;
  pending: number;
}

interface ArchiveRun {
  id: number;
  started_at: string;
  finished_at: string;
  duration_ms: number;
  trigger: string;
  dry_run: number;
  status: string;
  raw_archived: number;
  unprocessed_archived: number;
  signals_archived: number;
  logs_deleted: number;
  raw_archive_pruned: number;
  signals_archive_pruned: number;
  error_message: string | null;
}

interface ArchiveRunsPayload {
  runs: ArchiveRun[];
  summary: {
    total_runs: number;
    failed_runs: number;
    last_run_at: string | null;
    pending_total: number;
  };
  policies: ArchivePolicy[];
  schedule: { enabled: boolean; cron: string; timezone: string };
}

const TRIGGER_LABEL: Record<string, string> = {
  scheduler: '定时',
  manual: '手动',
  api: '接口',
};

function formatTs(value?: string | null): string {
  if (!value) return '—';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleString();
}

function formatDuration(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) return '—';
  if (ms < 1000) return `${ms} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
}

/** 一次运行总共动了多少行 —— 0 行是正常结果（没有数据到期），不是故障。 */
function totalAffected(run: ArchiveRun): number {
  return (
    run.raw_archived +
    run.unprocessed_archived +
    run.signals_archived +
    run.logs_deleted +
    run.raw_archive_pruned +
    run.signals_archive_pruned
  );
}

export default function ArchivePage() {
  const loader = useCallback(
    (signal: AbortSignal) => apiFetch<ArchiveRunsPayload>('/archive/runs?limit=20', { signal }),
    [],
  );
  const { data, error, loading, reload } = useAsyncData(loader, []);

  const policies = data?.policies ?? [];
  const runs = data?.runs ?? [];
  const summary = data?.summary;
  const schedule = data?.schedule;

  return (
    <div className="app-content space-y-5 animate-fade-in">
      <TopBar title="归档与保留策略" subtitle="保留期配置、待清理规模与归档运行历史">
        <button
          type="button"
          className="btn-secondary inline-flex items-center gap-1.5"
          onClick={reload}
          disabled={loading}
        >
          <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} strokeWidth={2} />
          <span className="hidden sm:inline">{loading ? '加载中…' : '刷新'}</span>
        </button>
      </TopBar>

      {error && (
        <div className="arc-policy-card p-4 text-sm text-red-500">
          加载失败：{error}
          <button type="button" className="ml-3 underline" onClick={reload}>
            重试
          </button>
        </div>
      )}

      {schedule && (
        <section className="arc-table-card">
          <div className="flex flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3 text-sm sm:px-5">
            <span className="inline-flex items-center gap-1.5">
              {schedule.enabled ? (
                <CheckCircle2 className="h-4 w-4 text-farm" strokeWidth={2} />
              ) : (
                <AlertTriangle className="h-4 w-4 text-amber-500" strokeWidth={2} />
              )}
              <span className="text-ink">
                定时归档{schedule.enabled ? '已启用' : '已关闭'}
              </span>
            </span>
            <span className="text-ink-muted">
              cron <code className="font-mono text-xs text-ink">{schedule.cron}</code>（
              {schedule.timezone}）
            </span>
            <span className="text-ink-muted">
              上次运行 <span className="text-ink">{formatTs(summary?.last_run_at)}</span>
            </span>
            <span className="text-ink-muted">
              累计 <span className="text-ink">{summary?.total_runs ?? 0}</span> 次
              {(summary?.failed_runs ?? 0) > 0 && (
                <span className="ml-1 text-red-500">（失败 {summary?.failed_runs}）</span>
              )}
            </span>
            <span className="text-ink-muted">
              当前待清理 <span className="text-ink">{summary?.pending_total ?? 0}</span> 行
            </span>
          </div>
        </section>
      )}

      <div className="arc-policy">
        {policies.map((p) => (
          <div className="arc-policy-card" key={p.key}>
            <div className="arc-policy-head">
              <span className="arc-policy-name">{p.label}</span>
              <span className="arc-policy-k">{p.action === 'archive' ? '归档' : '删除'}</span>
            </div>
            <div className="arc-policy-body">
              <div className="arc-policy-row">
                <span className="arc-policy-k">数据表</span>
                <span className="arc-policy-v font-mono text-xs">{p.table}</span>
              </div>
              <div className="arc-policy-row">
                <span className="arc-policy-k">保留期</span>
                <span className="arc-policy-v">{p.retention_days} 天</span>
              </div>
              <div className="arc-policy-row">
                <span className="arc-policy-k">当前行数</span>
                <span className="arc-policy-v">{p.total.toLocaleString()}</span>
              </div>
            </div>
            <div className="arc-policy-foot">
              <span className="arc-policy-k">待清理</span>
              <span className={p.pending > 0 ? 'arc-policy-v text-amber-500' : 'arc-policy-v'}>
                {p.pending.toLocaleString()} 行
              </span>
            </div>
          </div>
        ))}
        {!loading && policies.length === 0 && !error && (
          <div className="arc-policy-card p-4 text-sm text-ink-muted">暂无保留策略数据</div>
        )}
      </div>

      <section className="arc-table-card">
        <div className="arc-table-head">
          <div className="arc-table-title">归档运行历史</div>
          <span className="text-xs text-ink-faint">最近 20 次</span>
        </div>

        {runs.length === 0 ? (
          <div className="p-5 text-sm text-ink-muted">
            {/* 原文写的是"定时归档会在下一个 cron 时点写入第一条" ——
                那是个**承诺**，而它只在两个前提都成立时才为真：
                归档任务真的注册了，且进程活到那个时刻。
                实测本机 0 条记录的真正原因是后者（开发机不常驻，从没活到 03:00），
                而这句话会让人以为"等着就行"。改成把判断入口指出来。 */}
            {loading
              ? '加载中…'
              : '还没有运行记录。请到运维台的「调度器任务表」确认 archive_cleanup 是否已注册：已注册说明只是还没到过 cron 时点，没注册则需要检查 ARCHIVE_SCHEDULER_ENABLED。'}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="arc-table">
              <thead>
                <tr>
                  <th>开始时间</th>
                  <th>触发</th>
                  <th>结果</th>
                  <th>耗时</th>
                  <th>快照归档</th>
                  <th>低分归档</th>
                  <th>信号归档</th>
                  <th>日志删除</th>
                  <th>归档表清理</th>
                  <th>合计</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((run) => (
                  <tr key={run.id}>
                    <td className="whitespace-nowrap">{formatTs(run.started_at)}</td>
                    <td className="whitespace-nowrap">
                      {TRIGGER_LABEL[run.trigger] ?? run.trigger}
                      {run.dry_run === 1 && (
                        <span className="ml-1 text-xs text-ink-faint">(试跑)</span>
                      )}
                    </td>
                    <td className="whitespace-nowrap">
                      {run.status === 'success' ? (
                        <span className="text-farm">成功</span>
                      ) : (
                        <span className="text-red-500" title={run.error_message ?? undefined}>
                          失败
                        </span>
                      )}
                    </td>
                    <td className="whitespace-nowrap">{formatDuration(run.duration_ms)}</td>
                    <td>{run.raw_archived}</td>
                    <td>{run.unprocessed_archived}</td>
                    <td>{run.signals_archived}</td>
                    <td>{run.logs_deleted}</td>
                    <td>{run.raw_archive_pruned + run.signals_archive_pruned}</td>
                    <td className="font-medium">{totalAffected(run)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <div className="border-t border-line px-4 py-3 text-xs text-ink-faint sm:px-5">
          「低分归档」指未过分析阈值、永远不会被立项的采集记录 —— 它们此前不满足任何归档条件，
          会无限累积（实测占 raw_projects 的 73%）。保留期通过环境变量配置
          （<code className="font-mono">RAW_PROJECTS_RETENTION_DAYS</code>、
          <code className="font-mono">UNPROCESSED_RAW_RETENTION_DAYS</code> 等），修改需编辑
          <code className="font-mono">.env</code> 并重启服务。
        </div>
      </section>
    </div>
  );
}
