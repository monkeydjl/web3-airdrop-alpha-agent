'use client';

import { apiFetch } from '@/lib/api';
import { relativeTime } from '@/lib/format';
import type { WatchedWallet, WatchedWalletsResponse } from '@/lib/types';
import {
  Check,
  Copy,
  Edit2,
  Lock,
  Plus,
  RefreshCw,
  Trash2,
  Wallet,
  X,
} from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { EmptyState, Switch, Toast } from './ui';

const SUPPORTED_CHAINS = [
  { id: 'ethereum', name: 'Ethereum', color: 'bg-indigo-500/15 text-indigo-400 border-indigo-500/30' },
  { id: 'arbitrum', name: 'Arbitrum', color: 'bg-blue-500/15 text-blue-400 border-blue-500/30' },
  { id: 'optimism', name: 'Optimism', color: 'bg-red-500/15 text-red-400 border-red-500/30' },
  { id: 'base', name: 'Base', color: 'bg-sky-500/15 text-sky-400 border-sky-500/30' },
  { id: 'polygon', name: 'Polygon', color: 'bg-purple-500/15 text-purple-400 border-purple-500/30' },
];

const ADDRESS_REGEX = /^0x[0-9a-fA-F]{40}$/;

export function WatchedWalletsPanel({ className = '' }: { className?: string }) {
  const [wallets, setWallets] = useState<WatchedWallet[]>([]);
  const [total, setTotal] = useState(0);
  const [activeCount, setActiveCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState('');
  const [isForbidden, setIsForbidden] = useState(false);
  const [toast, setToast] = useState<{ message: string; type: 'success' | 'error' | 'info' } | null>(null);

  // 添加弹窗状态
  const [isAddOpen, setIsAddOpen] = useState(false);
  const [newAddress, setNewAddress] = useState('');
  const [newLabel, setNewLabel] = useState('');
  const [newChain, setNewChain] = useState('ethereum');
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState('');

  // 编辑弹窗状态
  const [editingWallet, setEditingWallet] = useState<WatchedWallet | null>(null);
  const [editLabel, setEditLabel] = useState('');
  const [editChain, setEditChain] = useState('ethereum');
  const [editSubmitting, setEditSubmitting] = useState(false);
  const [editError, setEditError] = useState('');

  // 删除状态
  const [deletingId, setDeletingId] = useState<number | null>(null);

  // 复制反馈状态
  const [copiedAddress, setCopiedAddress] = useState<string | null>(null);

  const showToast = useCallback((message: string, type: 'success' | 'error' | 'info' = 'success') => {
    setToast({ message, type });
    setTimeout(() => setToast(null), 3000);
  }, []);

  const fetchWallets = useCallback(async (isRefresh = false) => {
    if (isRefresh) setRefreshing(true);
    else setLoading(true);
    setError('');
    setIsForbidden(false);

    try {
      const res = await apiFetch<WatchedWalletsResponse>('/watched-wallets');
      setWallets(res.wallets || []);
      setTotal(res.total || 0);
      setActiveCount(res.active_count || 0);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : '获取监控钱包列表失败';
      if (msg.includes('403') || msg.toLowerCase().includes('forbidden')) {
        setIsForbidden(true);
      } else {
        setError(msg);
      }
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    fetchWallets();
  }, [fetchWallets]);

  // 切换启用/禁用状态
  const handleToggleActive = async (wallet: WatchedWallet, newActive: boolean) => {
    const prevWallets = [...wallets];
    // 乐观更新
    setWallets((prev) =>
      prev.map((w) => (w.id === wallet.id ? { ...w, active: newActive } : w))
    );
    setActiveCount((c) => (newActive ? c + 1 : Math.max(0, c - 1)));

    try {
      await apiFetch<WatchedWallet>(`/watched-wallets/${wallet.id}`, {
        method: 'PATCH',
        body: JSON.stringify({ active: newActive }),
      });
      showToast(newActive ? `已启用监控：${wallet.label}` : `已停用监控：${wallet.label}`, 'info');
    } catch (err: unknown) {
      // 回滚
      setWallets(prevWallets);
      setActiveCount((c) => (newActive ? Math.max(0, c - 1) : c + 1));
      const msg = err instanceof Error ? err.message : '更新状态失败';
      showToast(msg, 'error');
    }
  };

  // 添加钱包
  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    setFormError('');

    const trimmedAddress = newAddress.trim();
    const trimmedLabel = newLabel.trim();

    if (!ADDRESS_REGEX.test(trimmedAddress)) {
      setFormError('地址格式不合法（必须为 0x 开头的 40 位十六进制字符）');
      return;
    }
    if (!trimmedLabel) {
      setFormError('请输入钱包备注名称');
      return;
    }

    setSubmitting(true);
    try {
      await apiFetch('/watched-wallets', {
        method: 'POST',
        body: JSON.stringify({
          address: trimmedAddress,
          label: trimmedLabel,
          chain: newChain,
        }),
      });
      showToast('监控钱包添加成功', 'success');
      setIsAddOpen(false);
      setNewAddress('');
      setNewLabel('');
      setNewChain('ethereum');
      fetchWallets(true);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : '添加失败';
      setFormError(msg);
    } finally {
      setSubmitting(false);
    }
  };

  // 保存编辑
  const handleSaveEdit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editingWallet) return;
    setEditError('');

    const trimmedLabel = editLabel.trim();
    if (!trimmedLabel) {
      setEditError('备注不能为空');
      return;
    }

    setEditSubmitting(true);
    try {
      const updated = await apiFetch<WatchedWallet>(`/watched-wallets/${editingWallet.id}`, {
        method: 'PATCH',
        body: JSON.stringify({
          label: trimmedLabel,
          chain: editChain,
        }),
      });
      setWallets((prev) => prev.map((w) => (w.id === editingWallet.id ? updated : w)));
      showToast('钱包信息修改成功', 'success');
      setEditingWallet(null);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : '修改失败';
      setEditError(msg);
    } finally {
      setEditSubmitting(false);
    }
  };

  // 删除钱包
  const handleDelete = async (id: number) => {
    setDeletingId(id);
    try {
      await apiFetch(`/watched-wallets/${id}`, { method: 'DELETE' });
      setWallets((prev) => prev.filter((w) => w.id !== id));
      setTotal((t) => Math.max(0, t - 1));
      showToast('监控钱包已删除', 'info');
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : '删除失败';
      showToast(msg, 'error');
    } finally {
      setDeletingId(null);
    }
  };

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text);
    setCopiedAddress(text);
    showToast('已复制完整地址到剪贴板', 'info');
    setTimeout(() => setCopiedAddress(null), 2000);
  };

  const formatAddress = (addr: string) => {
    if (addr.length <= 14) return addr;
    return `${addr.slice(0, 8)}...${addr.slice(-6)}`;
  };

  if (isForbidden) {
    return (
      <div className={`rounded-xl border border-line bg-surface p-6 ${className}`}>
        <div className="flex items-center gap-3 text-ink-muted">
          <Lock className="h-5 w-5 text-amber-400" />
          <div>
            <h3 className="text-sm font-semibold text-ink">监控钱包管理（受限）</h3>
            <p className="mt-1 text-xs text-ink-muted">
              监控钱包地址清单涉及敏感资金隐私，仅管理员具备读写权限。请以管理员身份登录后查看。
            </p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className={`rounded-xl border border-line bg-surface p-5 space-y-4 ${className}`}>
      {toast ? <Toast message={toast.message} type={toast.type} /> : null}

      {/* 头部标题与操作 */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line pb-4">
        <div className="flex items-center gap-2.5">
          <div className="rounded-lg bg-farm-soft p-2 text-farm">
            <Wallet className="h-5 w-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-base font-bold text-ink">自有监控钱包（Claim Watch）</h3>
              <span className="rounded-full bg-surface-3 px-2 py-0.5 text-xs font-medium text-ink-muted">
                {total} 个监控中 · {activeCount} 活跃
              </span>
            </div>
            <p className="mt-0.5 text-xs text-ink-muted">
              配置自有钱包地址。当 Alchemy Webhook 命中这些地址的代币转入时，将自动推送疑似到账提醒。
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => fetchWallets(true)}
            disabled={refreshing || loading}
            className="btn btn-secondary text-xs h-8 px-2.5"
            title="刷新钱包列表"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${refreshing ? 'animate-spin' : ''}`} />
            <span className="hidden sm:inline">刷新</span>
          </button>
          <button
            type="button"
            onClick={() => setIsAddOpen(true)}
            className="btn btn-primary text-xs h-8 px-3"
          >
            <Plus className="h-3.5 w-3.5 mr-1" />
            登记钱包
          </button>
        </div>
      </div>

      {/* 错误提示 */}
      {error ? (
        <div className="rounded-lg border border-red-500/20 bg-red-500/10 p-3 text-xs text-red-400 flex items-center justify-between">
          <span>{error}</span>
          <button type="button" onClick={() => fetchWallets(true)} className="underline hover:opacity-80">
            重试
          </button>
        </div>
      ) : null}

      {/* 列表加载骨架 */}
      {loading ? (
        <div className="space-y-2 py-2">
          <div className="skeleton h-12 w-full rounded-lg" />
          <div className="skeleton h-12 w-full rounded-lg" />
          <div className="skeleton h-12 w-full rounded-lg" />
        </div>
      ) : wallets.length === 0 ? (
        <EmptyState
          title="暂无登记的监控钱包"
          description="点击右上角「登记钱包」添加你的自有链上地址，开启空投到账主动感知。"
        />
      ) : (
        /* 钱包列表 */
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="border-b border-line text-ink-muted">
                <th className="py-2.5 px-3 font-semibold">备注 (Label)</th>
                <th className="py-2.5 px-3 font-semibold">钱包地址</th>
                <th className="py-2.5 px-3 font-semibold">监控链</th>
                <th className="py-2.5 px-3 font-semibold">添加时间</th>
                <th className="py-2.5 px-3 font-semibold">监控状态</th>
                <th className="py-2.5 px-3 font-semibold text-right">操作</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {wallets.map((w) => {
                const chainInfo = SUPPORTED_CHAINS.find((c) => c.id === w.chain) || {
                  id: w.chain,
                  name: w.chain,
                  color: 'bg-surface-3 text-ink-muted border-line',
                };
                const isCopied = copiedAddress === w.address;

                return (
                  <tr key={w.id} className="hover:bg-surface-2/50 transition">
                    <td className="py-3 px-3 font-medium text-ink">
                      <div className="flex items-center gap-1.5">
                        <span>{w.label}</span>
                      </div>
                    </td>
                    <td className="py-3 px-3 font-mono text-ink-muted">
                      <div className="flex items-center gap-1.5">
                        <span title={w.address}>{formatAddress(w.address)}</span>
                        <button
                          type="button"
                          onClick={() => copyToClipboard(w.address)}
                          className="text-ink-muted hover:text-ink transition p-0.5 rounded"
                          title="复制完整地址"
                        >
                          {isCopied ? <Check className="h-3.5 w-3.5 text-farm" /> : <Copy className="h-3.5 w-3.5" />}
                        </button>
                      </div>
                    </td>
                    <td className="py-3 px-3">
                      <span className={`inline-flex items-center rounded px-2 py-0.5 text-[11px] font-medium border ${chainInfo.color}`}>
                        {chainInfo.name}
                      </span>
                    </td>
                    <td className="py-3 px-3 text-ink-muted" title={w.created_at}>
                      {relativeTime(w.created_at)}
                    </td>
                    <td className="py-3 px-3">
                      <Switch
                        id={`switch-wallet-${w.id}`}
                        label={`切换 ${w.label} 监控状态`}
                        checked={w.active}
                        onChange={(checked) => handleToggleActive(w, checked)}
                      />
                    </td>
                    <td className="py-3 px-3 text-right">
                      <div className="inline-flex items-center gap-1">
                        <button
                          type="button"
                          onClick={() => {
                            setEditingWallet(w);
                            setEditLabel(w.label);
                            setEditChain(w.chain);
                            setEditError('');
                          }}
                          className="p-1 rounded text-ink-muted hover:text-ink hover:bg-surface-3 transition"
                          title="编辑备注与链"
                        >
                          <Edit2 className="h-3.5 w-3.5" />
                        </button>
                        <button
                          type="button"
                          disabled={deletingId === w.id}
                          onClick={() => {
                            if (window.confirm(`确认删除监控钱包「${w.label}」吗？历史命中记录仍将保留在通知日志中。`)) {
                              handleDelete(w.id);
                            }
                          }}
                          className="p-1 rounded text-ink-muted hover:text-red-400 hover:bg-red-500/10 transition"
                          title="删除"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* 底部小提示 */}
      <div className="rounded-lg bg-surface-2/60 p-3 text-xs text-ink-muted flex items-start gap-2 border border-line">
        <span className="text-farm font-bold">提示:</span>
        <span>
          地址一律小写归一存储；若只需临时停止提醒，建议使用「关」切换停用而非直接删除，避免频繁重复登记。
        </span>
      </div>

      {/* ── 添加钱包弹窗 ── */}
      {isAddOpen ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 animate-fade-in">
          <div className="w-full max-w-md rounded-xl border border-line bg-surface p-5 shadow-lift space-y-4">
            <div className="flex items-center justify-between border-b border-line pb-3">
              <h4 className="text-sm font-bold text-ink flex items-center gap-2">
                <Wallet className="h-4 w-4 text-farm" />
                登记监控钱包
              </h4>
              <button
                type="button"
                onClick={() => setIsAddOpen(false)}
                className="text-ink-muted hover:text-ink"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            {formError ? (
              <div className="rounded border border-red-500/30 bg-red-500/10 p-2 text-xs text-red-400">
                {formError}
              </div>
            ) : null}

            <form onSubmit={handleCreate} className="space-y-3.5 text-xs">
              <div>
                <label className="block font-medium text-ink mb-1">
                  钱包地址 <span className="text-red-400">*</span>
                </label>
                <input
                  type="text"
                  required
                  placeholder="0x..."
                  value={newAddress}
                  onChange={(e) => setNewAddress(e.target.value)}
                  className="w-full rounded-lg border border-line bg-surface-2 px-3 py-2 font-mono text-xs text-ink placeholder:text-ink-muted focus:border-farm focus:outline-none"
                />
                <p className="mt-1 text-[11px] text-ink-muted">
                  请输入 0x 开头的 40 位十六进制以太坊兼容地址（系统将自动转为小写）。
                </p>
              </div>

              <div>
                <label className="block font-medium text-ink mb-1">
                  钱包备注 (Label) <span className="text-red-400">*</span>
                </label>
                <input
                  type="text"
                  required
                  maxLength={64}
                  placeholder="如：主钱包 01、Arbitrum 交互号"
                  value={newLabel}
                  onChange={(e) => setNewLabel(e.target.value)}
                  className="w-full rounded-lg border border-line bg-surface-2 px-3 py-2 text-xs text-ink placeholder:text-ink-muted focus:border-farm focus:outline-none"
                />
              </div>

              <div>
                <label className="block font-medium text-ink mb-1">监控主链</label>
                <select
                  value={newChain}
                  onChange={(e) => setNewChain(e.target.value)}
                  className="w-full rounded-lg border border-line bg-surface-2 px-3 py-2 text-xs text-ink focus:border-farm focus:outline-none"
                >
                  {SUPPORTED_CHAINS.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </select>
              </div>

              <div className="flex items-center justify-end gap-2 pt-2 border-t border-line">
                <button
                  type="button"
                  onClick={() => setIsAddOpen(false)}
                  className="btn btn-secondary text-xs h-8 px-3"
                >
                  取消
                </button>
                <button
                  type="submit"
                  disabled={submitting}
                  className="btn btn-primary text-xs h-8 px-4"
                >
                  {submitting ? '提交中...' : '确认登记'}
                </button>
              </div>
            </form>
          </div>
        </div>
      ) : null}

      {/* ── 编辑钱包弹窗 ── */}
      {editingWallet ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 animate-fade-in">
          <div className="w-full max-w-md rounded-xl border border-line bg-surface p-5 shadow-lift space-y-4">
            <div className="flex items-center justify-between border-b border-line pb-3">
              <h4 className="text-sm font-bold text-ink flex items-center gap-2">
                <Edit2 className="h-4 w-4 text-farm" />
                修改监控钱包
              </h4>
              <button
                type="button"
                onClick={() => setEditingWallet(null)}
                className="text-ink-muted hover:text-ink"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            {editError ? (
              <div className="rounded border border-red-500/30 bg-red-500/10 p-2 text-xs text-red-400">
                {editError}
              </div>
            ) : null}

            <form onSubmit={handleSaveEdit} className="space-y-3.5 text-xs">
              <div>
                <label className="block font-medium text-ink-muted mb-1">钱包地址（不可修改）</label>
                <input
                  type="text"
                  disabled
                  value={editingWallet.address}
                  className="w-full rounded-lg border border-line bg-surface-3 px-3 py-2 font-mono text-xs text-ink-muted cursor-not-allowed opacity-75"
                />
                <p className="mt-1 text-[11px] text-ink-muted">
                  地址不可直接变更；如需更换钱包地址，请删除后重新登记。
                </p>
              </div>

              <div>
                <label className="block font-medium text-ink mb-1">
                  钱包备注 (Label) <span className="text-red-400">*</span>
                </label>
                <input
                  type="text"
                  required
                  maxLength={64}
                  value={editLabel}
                  onChange={(e) => setEditLabel(e.target.value)}
                  className="w-full rounded-lg border border-line bg-surface-2 px-3 py-2 text-xs text-ink focus:border-farm focus:outline-none"
                />
              </div>

              <div>
                <label className="block font-medium text-ink mb-1">监控主链</label>
                <select
                  value={editChain}
                  onChange={(e) => setEditChain(e.target.value)}
                  className="w-full rounded-lg border border-line bg-surface-2 px-3 py-2 text-xs text-ink focus:border-farm focus:outline-none"
                >
                  {SUPPORTED_CHAINS.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </select>
              </div>

              <div className="flex items-center justify-end gap-2 pt-2 border-t border-line">
                <button
                  type="button"
                  onClick={() => setEditingWallet(null)}
                  className="btn btn-secondary text-xs h-8 px-3"
                >
                  取消
                </button>
                <button
                  type="submit"
                  disabled={editSubmitting}
                  className="btn btn-primary text-xs h-8 px-4"
                >
                  {editSubmitting ? '保存中...' : '保存修改'}
                </button>
              </div>
            </form>
          </div>
        </div>
      ) : null}
    </div>
  );
}
