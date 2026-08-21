'use client';

import { TopBar } from '@/components/TopBar';
import { useCallback } from 'react';
import { Info, RefreshCw } from 'lucide-react';
import { apiFetch } from '@/lib/api';
import { useAsyncData } from '@/lib/useAsyncData';

/**
 * 归档策略页。
 *
 * 只展示后端**真实**暴露的保留策略配置（GET /settings/config 的 automation 块）。
 * 归档运行历史（记录数/体积/耗时/命中率）后端目前没有对应接口——`app/archive.py`
 * 的 RawDataArchiver 有真实逻辑但未挂路由，所以这里不编造数字，而是明确标注
 * "暂无运行历史接口"。补上后端接口后再接。
 */
interface SettingsConfig {
  automation?: {
    RAW_PROJECTS_RETENTION_DAYS?: number;
    PROJECT_SIGNALS_RETENTION_DAYS?: number;
    COLLECTION_LOGS_RETENTION_DAYS?: number;
  };
}

interface PolicyRow {
  name: string;
  table: string;
  retentionDays?: number;
  desc: string;
}

export default function ArchivePage() {
  const loader = useCallback(
    (signal: AbortSignal) => apiFetch<SettingsConfig>('/settings/config', { signal }),
    [],
  );
  const { data, error, loading, reload } = useAsyncData(loader, []);

  const automation = data?.automation;

  const policies: PolicyRow[] = [
    {
      name: '原始项目快照',
      table: 'raw_projects',
      retentionDays: automation?.RAW_PROJECTS_RETENTION_DAYS,
      desc: '采集器写入的原始项目记录，超过保留期后归档清理',
    },
    {
      name: '信号与指标',
      table: 'project_signals',
      retentionDays: automation?.PROJECT_SIGNALS_RETENTION_DAYS,
      desc: '各来源的热度 / 资金 / 开发活跃度信号明细',
    },
    {
      name: '采集日志',
      table: 'collection_logs',
      retentionDays: automation?.COLLECTION_LOGS_RETENTION_DAYS,
      desc: '每次采集运行的执行日志，超期直接删除',
    },
  ];

  return (
    <div className="app-content space-y-5 animate-fade-in">
      <TopBar title="归档与保留策略" subtitle="数据保留期配置（只读）">
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

      <div className="arc-policy">
        {policies.map((p) => (
          <div className="arc-policy-card" key={p.table}>
            <div className="arc-policy-head">
              <span className="arc-policy-name">{p.name}</span>
            </div>
            <div className="arc-policy-body">
              <div className="arc-policy-row">
                <span className="arc-policy-k">数据表</span>
                <span className="arc-policy-v">{p.table}</span>
              </div>
              <div className="arc-policy-row">
                <span className="arc-policy-k">保留期</span>
                <span className="arc-policy-v">
                  {loading
                    ? '…'
                    : p.retentionDays != null
                      ? `${p.retentionDays} 天`
                      : '—'}
                </span>
              </div>
            </div>
            <div className="arc-policy-foot">
              <span className="arc-policy-k">{p.desc}</span>
            </div>
          </div>
        ))}
      </div>

      <section className="arc-table-card">
        <div className="arc-table-head">
          <div className="arc-table-title">归档运行历史</div>
        </div>
        <div className="flex items-start gap-2.5 p-5 text-sm text-ink-muted">
          <Info className="mt-0.5 h-4 w-4 shrink-0 text-ink-faint" strokeWidth={2} />
          <div className="space-y-1">
            <p className="text-ink">暂无运行历史接口</p>
            <p className="text-xs text-ink-faint">
              归档逻辑由后端 <code className="font-mono">app/archive.py</code> 按上述保留期执行，
              但尚未提供查询运行记录的 API。补上接口后此处会展示真实的归档批次、记录数与耗时。
            </p>
            <p className="text-xs text-ink-faint">
              保留期通过环境变量配置（<code className="font-mono">RAW_PROJECTS_RETENTION_DAYS</code> 等），
              修改需编辑 <code className="font-mono">.env</code> 并重启服务。
            </p>
          </div>
        </div>
      </section>
    </div>
  );
}
