'use client';

import { useEffect, useState } from 'react';
import { apiFetch } from '@/lib/api';

interface StudioOperator {
  operator_id: string;
  name: string;
  role: string;
  assigned_wallets: number;
  assigned_projects: string[];
  today_completed_tx: number;
  today_target_tx: number;
  completion_rate: number;
  gas_spent_usd: number;
  status: string;
  ip_proxy_isolated: boolean;
  last_active: string;
}

interface AssignedTask {
  task_id: string;
  title: string;
  project: string;
  operator_id: string;
  target_wallet_count: number;
  status: string;
  priority: string;
  deadline: string;
}

interface StudioDashboardData {
  summary: {
    team_name: string;
    active_operators_count: number;
    total_managed_wallets: number;
    today_total_transactions: number;
    overall_completion_rate: number;
    today_gas_budget_usd: number;
    sybil_isolation_rating: string;
  };
  operators: StudioOperator[];
  assigned_tasks: AssignedTask[];
}

interface TeamStudioModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export default function TeamStudioModal({ isOpen, onClose }: TeamStudioModalProps) {
  const [data, setData] = useState<StudioDashboardData | null>(null);
  const [loading, setLoading] = useState(false);
  const [showAssignForm, setShowAssignForm] = useState(false);

  // New task form state
  const [taskTitle, setTaskTitle] = useState('');
  const [taskProject, setTaskProject] = useState('Scroll');
  const [taskOperator, setTaskOperator] = useState('op_alice');
  const [taskWallets, setTaskWallets] = useState(15);
  const [submitting, setSubmitting] = useState(false);

  const fetchDashboard = () => {
    setLoading(true);
    apiFetch<{ data: StudioDashboardData }>('/team-studio/dashboard')
      .then((res) => {
        if (res?.data) {
          setData(res.data);
        }
      })
      .catch((err) => console.error('Failed to load studio dashboard', err))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    if (!isOpen) return;
    fetchDashboard();
  }, [isOpen]);

  const handleAssignTask = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!taskTitle) return;
    setSubmitting(true);
    try {
      await apiFetch('/team-studio/assign-task', {
        method: 'POST',
        body: JSON.stringify({
          title: taskTitle,
          project: taskProject,
          operator_id: taskOperator,
          target_wallet_count: taskWallets,
          priority: 'high',
          deadline: '今日 24:00',
        }),
      });
      setTaskTitle('');
      setShowAssignForm(false);
      fetchDashboard();
    } catch (err) {
      console.error('Failed to assign task', err);
    } finally {
      setSubmitting(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm animate-fade-in">
      <div className="relative flex max-h-[92vh] w-full max-w-5xl flex-col rounded-2xl border border-line bg-surface p-6 shadow-2xl overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-line pb-4">
          <div className="flex items-center gap-2.5">
            <span className="text-2xl">👥</span>
            <div>
              <h3 className="text-lg font-bold text-ink">团队/工作室多操作员协同与任务看板</h3>
              <p className="text-xs text-ink-muted">
                钱包矩阵分配、跨协议任务派发、成员完成率跟踪与防交叉转账女巫隔离审计
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1.5 text-ink-muted hover:bg-surface-2 hover:text-ink transition"
          >
            ✕
          </button>
        </div>

        {/* Content */}
        <div className="my-4 flex-1 overflow-y-auto pr-1 space-y-5">
          {loading && !data ? (
            <div className="py-16 text-center text-sm text-ink-muted">正在同步团队工作室指标…</div>
          ) : data ? (
            <>
              {/* Studio Overview KPI Cards */}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                <div className="p-3.5 rounded-xl border border-line bg-surface-2/40 text-center">
                  <div className="text-[10px] text-ink-muted">团队操作员</div>
                  <div className="text-xl font-bold font-mono text-ink mt-0.5">
                    {data.summary.active_operators_count} 人
                  </div>
                </div>

                <div className="p-3.5 rounded-xl border border-line bg-surface-2/40 text-center">
                  <div className="text-[10px] text-ink-muted">矩阵托管钱包</div>
                  <div className="text-xl font-bold font-mono text-brand-400 mt-0.5">
                    {data.summary.total_managed_wallets} 个
                  </div>
                </div>

                <div className="p-3.5 rounded-xl border border-line bg-surface-2/40 text-center">
                  <div className="text-[10px] text-ink-muted">今日总交互笔数</div>
                  <div className="text-xl font-bold font-mono text-emerald-400 mt-0.5">
                    {data.summary.today_total_transactions} 笔
                  </div>
                </div>

                <div className="p-3.5 rounded-xl border border-line bg-surface-2/40 text-center">
                  <div className="text-[10px] text-ink-muted">综合达成率</div>
                  <div className="text-xl font-bold font-mono text-cyan-400 mt-0.5">
                    {(data.summary.overall_completion_rate * 100).toFixed(0)}%
                  </div>
                </div>
              </div>

              {/* Sybil Isolation Status Banner */}
              <div className="p-3 rounded-xl border border-emerald-500/30 bg-emerald-500/10 flex items-center justify-between text-xs text-emerald-400">
                <span className="flex items-center gap-2">
                  <span>🛡️</span>
                  <span><strong>隔离合规审计：</strong>{data.summary.sybil_isolation_rating}</span>
                </span>
                <span className="text-[11px] font-mono opacity-80">Zero Cross-Funding</span>
              </div>

              {/* Operators Workload Grid */}
              <div>
                <div className="flex items-center justify-between mb-2.5">
                  <h4 className="text-xs font-semibold text-ink-muted uppercase tracking-wider">
                    操作员档案与名下钱包配额 (Operators)
                  </h4>
                  <button
                    type="button"
                    onClick={() => setShowAssignForm(!showAssignForm)}
                    className="btn-primary !py-1 !px-2.5 text-xs"
                  >
                    {showAssignForm ? '收起派发' : '+ 派发新任务'}
                  </button>
                </div>

                {/* Assign Task Form Drawer */}
                {showAssignForm && (
                  <form onSubmit={handleAssignTask} className="mb-4 p-4 rounded-xl border border-brand-500/40 bg-surface-2/70 space-y-3">
                    <div className="text-xs font-bold text-ink">派发新交互任务</div>
                    <div className="grid grid-cols-1 sm:grid-cols-4 gap-2.5">
                      <div>
                        <label className="text-[11px] text-ink-muted">任务描述</label>
                        <input
                          type="text"
                          value={taskTitle}
                          placeholder="如: 批量完成Linea借贷"
                          onChange={(e) => setTaskTitle(e.target.value)}
                          className="mt-1 w-full rounded-lg border border-line bg-surface p-2 text-xs text-ink"
                          required
                        />
                      </div>
                      <div>
                        <label className="text-[11px] text-ink-muted">协议项目</label>
                        <input
                          type="text"
                          value={taskProject}
                          onChange={(e) => setTaskProject(e.target.value)}
                          className="mt-1 w-full rounded-lg border border-line bg-surface p-2 text-xs text-ink"
                          required
                        />
                      </div>
                      <div>
                        <label className="text-[11px] text-ink-muted">指派操作员</label>
                        <select
                          value={taskOperator}
                          onChange={(e) => setTaskOperator(e.target.value)}
                          className="mt-1 w-full rounded-lg border border-line bg-surface p-2 text-xs text-ink"
                        >
                          {data.operators.map((op) => (
                            <option key={op.operator_id} value={op.operator_id}>
                              {op.name}
                            </option>
                          ))}
                        </select>
                      </div>
                      <div>
                        <label className="text-[11px] text-ink-muted">目标钱包数</label>
                        <input
                          type="number"
                          value={taskWallets}
                          min={1}
                          max={200}
                          onChange={(e) => setTaskWallets(Number(e.target.value))}
                          className="mt-1 w-full rounded-lg border border-line bg-surface p-2 text-xs font-mono text-ink"
                        />
                      </div>
                    </div>
                    <div className="flex justify-end gap-2 pt-1">
                      <button
                        type="button"
                        onClick={() => setShowAssignForm(false)}
                        className="btn-secondary !py-1 !px-3 text-xs"
                      >
                        取消
                      </button>
                      <button
                        type="submit"
                        disabled={submitting}
                        className="btn-primary !py-1 !px-3 text-xs"
                      >
                        {submitting ? '派发中…' : '确认指派'}
                      </button>
                    </div>
                  </form>
                )}

                <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                  {data.operators.map((op) => (
                    <div
                      key={op.operator_id}
                      className="p-4 rounded-xl border border-line bg-surface-2/40 space-y-3"
                    >
                      <div className="flex items-start justify-between">
                        <div>
                          <div className="font-bold text-xs text-ink">{op.name}</div>
                          <div className="text-[10px] text-ink-muted">{op.role}</div>
                        </div>
                        <span
                          className={`px-2 py-0.5 rounded-full text-[10px] font-semibold ${
                            op.status === 'online'
                              ? 'bg-emerald-500/15 text-emerald-400'
                              : 'bg-surface-3 text-ink-muted'
                          }`}
                        >
                          {op.status === 'online' ? '● 在线' : '○ 空闲'}
                        </span>
                      </div>

                      <div className="space-y-1 text-xs">
                        <div className="flex justify-between">
                          <span className="text-ink-muted text-[11px]">托管钱包段:</span>
                          <span className="font-mono font-semibold text-ink">{op.assigned_wallets} 个</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-ink-muted text-[11px]">负责项目:</span>
                          <span className="text-[11px] text-brand-400 truncate max-w-[140px]">
                            {op.assigned_projects.join(', ')}
                          </span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-ink-muted text-[11px]">今日消耗 Gas:</span>
                          <span className="font-mono text-[11px] text-ink">${op.gas_spent_usd.toFixed(2)}</span>
                        </div>
                      </div>

                      {/* Progress Bar */}
                      <div>
                        <div className="flex justify-between text-[10px] text-ink-muted mb-1">
                          <span>今日进度 ({op.today_completed_tx}/{op.today_target_tx} 笔)</span>
                          <span className="font-mono font-bold text-ink">
                            {(op.completion_rate * 100).toFixed(0)}%
                          </span>
                        </div>
                        <div className="h-1.5 w-full bg-surface-3 rounded-full overflow-hidden">
                          <div
                            className="h-full bg-brand-500 rounded-full transition-all duration-300"
                            style={{ width: `${Math.min(100, op.completion_rate * 100)}%` }}
                          />
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Tasks Checklist */}
              <div>
                <h4 className="text-xs font-semibold text-ink-muted uppercase tracking-wider mb-2.5">
                  团队待办与履约进度 (Assigned Tasks)
                </h4>
                <div className="space-y-2">
                  {data.assigned_tasks.map((t) => (
                    <div
                      key={t.task_id}
                      className="flex items-center justify-between p-3 rounded-xl border border-line bg-surface-2/30 text-xs"
                    >
                      <div className="flex items-center gap-3">
                        <span
                          className={`h-2 w-2 rounded-full ${
                            t.status === 'completed'
                              ? 'bg-emerald-400'
                              : t.priority === 'high'
                              ? 'bg-red-400 animate-ping'
                              : 'bg-amber-400'
                          }`}
                        />
                        <div>
                          <div className="font-semibold text-ink">{t.title}</div>
                          <div className="text-[10px] text-ink-muted">
                            所属: {t.project} · 操作员: {t.operator_id} · 目标钱包: {t.target_wallet_count} 个
                          </div>
                        </div>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className="text-[10px] font-mono text-ink-muted">{t.deadline}</span>
                        <span
                          className={`px-2 py-0.5 rounded text-[10px] font-semibold ${
                            t.status === 'completed'
                              ? 'bg-emerald-500/15 text-emerald-400'
                              : 'bg-surface-3 text-ink-muted'
                          }`}
                        >
                          {t.status === 'completed' ? '已完成' : '进行中'}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </>
          ) : null}
        </div>

        {/* Footer */}
        <div className="border-t border-line pt-3 flex items-center justify-between text-xs text-ink-muted">
          <span>提示：工作室模式下请确保每位操作员配置独立的住宅静态代理 IP，严禁多人在同一公共 WiFi 环境下并发操作。</span>
          <button type="button" onClick={onClose} className="btn-secondary !py-1 !px-4">
            关闭
          </button>
        </div>
      </div>
    </div>
  );
}
