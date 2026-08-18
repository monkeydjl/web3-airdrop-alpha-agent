'use client';

import { TopBar } from '@/components/TopBar';
import { Switch } from '@/components/ui';
import { Download, Play } from 'lucide-react';

const POLICIES = [
  {
    name: '原始项目快照',
    enabled: true,
    source: 'raw_projects',
    retention: '90 天',
    destination: 'archive/raw_projects',
    lastRun: '今天 03:00',
    hitRate: '命中率 99.2%',
    activeLabel: '命中率 99.2%',
  },
  {
    name: '信号与指标',
    enabled: true,
    source: 'project_signals',
    retention: '180 天',
    destination: 'archive/signals',
    lastRun: '今天 03:00',
    hitRate: '命中率 100%',
    activeLabel: '命中率 100%',
  },
  {
    name: '采集日志',
    enabled: false,
    source: 'collection_logs',
    retention: '30 天',
    destination: 'archive/logs',
    lastRun: '从未运行',
    hitRate: '未启用',
    activeLabel: '未启用',
  },
];

const RECORDS = [
  { id: '#4821', name: 'arc-20250811-raw', scope: 'raw_projects · 90 天前', status: 'ok', statusText: '已完成', count: '2,314', size: '6.2 GB', startTime: '2025-08-11 03:00', duration: '4 分 12 秒' },
  { id: '#4822', name: 'arc-20250811-signals', scope: 'project_signals · 180 天前', status: 'ok', statusText: '已完成', count: '1,856', size: '12.4 GB', startTime: '2025-08-11 03:00', duration: '8 分 45 秒' },
  { id: '#4823', name: 'arc-20250810-raw', scope: 'raw_projects · 90 天前', status: 'ok', statusText: '已完成', count: '2,102', size: '5.8 GB', startTime: '2025-08-10 03:00', duration: '3 分 56 秒' },
  { id: '#4824', name: 'arc-20250810-signals', scope: 'project_signals · 180 天前', status: 'warn', statusText: '部分跳过', count: '1,743', size: '11.2 GB', startTime: '2025-08-10 03:00', duration: '7 分 23 秒' },
  { id: '#4825', name: 'arc-20250809-raw', scope: 'raw_projects · 90 天前', status: 'info', statusText: '增量', count: '651', size: '2.1 GB', startTime: '2025-08-09 03:00', duration: '1 分 34 秒' },
];

export default function ArchivePage() {
  return (
    <div className="app-content space-y-5 animate-fade-in">
      <TopBar title="归档历史" subtitle="数据归档 · 保留策略 · 记录查询">
        <button type="button" className="btn-secondary inline-flex items-center gap-1.5">
          <Download className="h-4 w-4" strokeWidth={2} />
          <span className="hidden sm:inline">导出清单</span>
        </button>
        <button type="button" className="btn-primary inline-flex items-center gap-1.5">
          <Play className="h-4 w-4" strokeWidth={2} />
          <span className="hidden sm:inline">立即归档</span>
        </button>
      </TopBar>

      <div className="arc-stats">
        <div className="arc-stat">
          <span className="arc-stat-k">本月已归档</span>
          <span className="arc-stat-v">4,821</span>
          <span className="arc-stat-s">raw_projects + signals</span>
        </div>
        <div className="arc-stat">
          <span className="arc-stat-k">归档体积</span>
          <span className="arc-stat-v">38.6 GB</span>
          <span className="arc-stat-s">较上月 +12%</span>
        </div>
        <div className="arc-stat">
          <span className="arc-stat-k">保留策略</span>
          <span className="arc-stat-v">90 天</span>
          <span className="arc-stat-s">原始数据默认</span>
        </div>
        <div className="arc-stat">
          <span className="arc-stat-k">待清理任务</span>
          <span className="arc-stat-v" style={{ color: 'rgb(var(--watch))' }}>2</span>
          <span className="arc-stat-s">待人工确认</span>
        </div>
      </div>

      <div className="arc-policy">
        {POLICIES.map((p) => (
          <div className="arc-policy-card" key={p.name}>
            <div className="arc-policy-head">
              <span className="arc-policy-name">{p.name}</span>
              <Switch
                checked={p.enabled}
                onChange={() => {}}
                label={`启用${p.name}归档`}
              />
            </div>
            <div className="arc-policy-body">
              <div className="arc-policy-row">
                <span className="arc-policy-k">数据源</span>
                <span className="arc-policy-v">{p.source}</span>
              </div>
              <div className="arc-policy-row">
                <span className="arc-policy-k">保留</span>
                <span className="arc-policy-v">{p.retention}</span>
              </div>
              <div className="arc-policy-row">
                <span className="arc-policy-k">归档目的地</span>
                <span className="arc-policy-v">{p.destination}</span>
              </div>
              <div className="arc-policy-row">
                <span className="arc-policy-k">上次执行</span>
                <span className="arc-policy-v">{p.lastRun}</span>
              </div>
            </div>
            <div className="arc-policy-foot">
              <span className="arc-policy-k">{p.activeLabel}</span>
              <button type="button" className="arc-policy-link">编辑策略</button>
            </div>
          </div>
        ))}
      </div>

      <section className="arc-table-card">
        <div className="arc-table-head">
          <div className="arc-table-title">归档记录</div>
          <div className="arc-table-actions">
            <button type="button" className="btn-secondary !min-h-8 !px-3 !text-xs inline-flex items-center gap-1.5">
              <Download className="h-3.5 w-3.5" strokeWidth={2} />
              <span>导出清单</span>
            </button>
            <button type="button" className="btn-primary !min-h-8 !px-3 !text-xs inline-flex items-center gap-1.5">
              <Play className="h-3.5 w-3.5" strokeWidth={2} />
              <span>立即归档</span>
            </button>
          </div>
        </div>
        <div className="overflow-x-auto">
          <table className="arc-table">
            <thead>
              <tr>
                <th>归档任务</th>
                <th>范围</th>
                <th>状态</th>
                <th>记录数</th>
                <th>大小</th>
                <th>开始时间</th>
                <th>耗时</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {RECORDS.map((r) => (
                <tr key={r.id}>
                  <td>
                    <div className="arc-name">{r.name}</div>
                    <div className="arc-id">{r.id}</div>
                  </td>
                  <td>
                    <div className="arc-scope">{r.scope}</div>
                  </td>
                  <td>
                    <span className="arc-pill" data-tone={r.status}>{r.statusText}</span>
                  </td>
                  <td className="font-mono text-xs tabular-nums">{r.count}</td>
                  <td className="arc-size">{r.size}</td>
                  <td className="font-mono text-xs text-ink-muted">{r.startTime}</td>
                  <td className="font-mono text-xs text-ink-muted">{r.duration}</td>
                  <td>
                    <button type="button" className="arc-text-btn">下载</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
