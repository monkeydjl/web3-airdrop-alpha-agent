'use client';

import { useState } from 'react';
import { apiFetch } from '@/lib/api';

interface SecuritySentinelModalProps {
  initialAddress?: string;
  initialUrl?: string;
  onClose: () => void;
}

export function SecuritySentinelModal({
  initialAddress = '',
  initialUrl = '',
  onClose,
}: SecuritySentinelModalProps) {
  const [tab, setTab] = useState<'approvals' | 'domain'>('approvals');
  const [address, setAddress] = useState(initialAddress);
  const [url, setUrl] = useState(initialUrl);

  const [approvalResult, setApprovalResult] = useState<any | null>(null);
  const [domainResult, setDomainResult] = useState<any | null>(null);
  const [loading, setLoading] = useState(false);

  const handleScanApprovals = async () => {
    if (!address.trim()) return;
    setLoading(true);
    setApprovalResult(null);
    try {
      const res = await apiFetch<{ ok: boolean; data: any }>('/security/approvals', {
        method: 'POST',
        body: JSON.stringify({ wallet_address: address.trim() }),
      });
      if (res?.data) {
        setApprovalResult(res.data);
      }
    } catch {
      // 异常捕获
    } finally {
      setLoading(false);
    }
  };

  const handleCheckDomain = async () => {
    if (!url.trim()) return;
    setLoading(true);
    setDomainResult(null);
    try {
      const res = await apiFetch<{ ok: boolean; data: any }>('/security/domain-check', {
        method: 'POST',
        body: JSON.stringify({ url: url.trim() }),
      });
      if (res?.data) {
        setDomainResult(res.data);
      }
    } catch {
      // 异常捕获
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/75 backdrop-blur-sm animate-fade-in">
      <div className="dash-card w-full max-w-2xl max-h-[90vh] flex flex-col p-6 shadow-2xl border-line bg-surface relative">
        <button
          type="button"
          onClick={onClose}
          className="absolute top-4 right-4 text-ink-muted hover:text-ink text-sm"
        >
          ✕
        </button>

        <div className="border-b border-line pb-3 mb-4">
          <h2 className="text-sm font-bold text-ink flex items-center gap-2">
            <span>🛡️</span>
            <span>智能合约授权与防钓鱼安全风控雷达</span>
          </h2>
          <p className="text-xs text-ink-muted mt-0.5">
            排查代币无限额授权 (Unlimited Allowance) 暴露风险与防范仿冒山寨钓鱼站
          </p>
        </div>

        {/* 选项卡 */}
        <div className="flex items-center gap-2 border-b border-line pb-2 mb-3">
          <button
            type="button"
            onClick={() => setTab('approvals')}
            className={`px-3 py-1 rounded-xl text-xs font-semibold transition ${
              tab === 'approvals'
                ? 'bg-brand-500 text-white shadow-sm'
                : 'bg-surface-2 text-ink-muted hover:text-ink'
            }`}
          >
            🔑 钱包代币授权体检
          </button>
          <button
            type="button"
            onClick={() => setTab('domain')}
            className={`px-3 py-1 rounded-xl text-xs font-semibold transition ${
              tab === 'domain'
                ? 'bg-brand-500 text-white shadow-sm'
                : 'bg-surface-2 text-ink-muted hover:text-ink'
            }`}
          >
            🌐 官网防钓鱼与同形异义词检测
          </button>
        </div>

        <div className="overflow-y-auto flex-1 space-y-4 pr-1">
          {tab === 'approvals' ? (
            <div className="space-y-3">
              <div className="flex gap-2">
                <input
                  type="text"
                  value={address}
                  onChange={(e) => setAddress(e.target.value)}
                  placeholder="输入要体检的钱包 EVM 地址 0x..."
                  className="input font-mono text-xs flex-1"
                />
                <button
                  type="button"
                  onClick={handleScanApprovals}
                  disabled={loading || !address.trim()}
                  className="btn-primary !py-1.5 text-xs shrink-0"
                >
                  {loading ? '正在体检中...' : '开始安全扫描 🔍'}
                </button>
              </div>

              {approvalResult && (
                <div className="space-y-3 animate-fade-in pt-2">
                  <div className="flex items-center justify-between p-3.5 rounded-xl border border-line bg-surface-2">
                    <div>
                      <div className="text-xs font-semibold text-ink-muted">授权安全健康度</div>
                      <div className="flex items-center gap-2 mt-1">
                        <span className="font-mono text-xl font-black text-brand-400">
                          {approvalResult.security_score} / 100
                        </span>
                        <span className="text-xs font-bold text-ink">
                          {approvalResult.risk_status_zh}
                        </span>
                      </div>
                    </div>

                    <a
                      href={approvalResult.revoke_url}
                      target="_blank"
                      rel="noreferrer"
                      className="btn-secondary !py-1.5 text-xs text-rose-400 border-rose-500/30 hover:bg-rose-500/10 flex items-center gap-1"
                    >
                      <span>一键前往 Revoke.cash 撤销 ↗</span>
                    </a>
                  </div>

                  <div className="p-3 rounded-lg bg-amber-500/10 border border-amber-500/20 text-xs text-amber-300 leading-relaxed">
                    💡 <strong>防坑建议：</strong> {approvalResult.recommendation}
                  </div>

                  {/* 授权列表 */}
                  <div className="space-y-1.5">
                    <span className="text-xs font-semibold text-ink">已发现的典型授权清单：</span>
                    <div className="divide-y divide-line/60 rounded-xl border border-line bg-surface-2 overflow-hidden text-xs">
                      {approvalResult.approvals.map((item: any, idx: number) => (
                        <div key={idx} className="p-2.5 flex items-center justify-between">
                          <div className="space-y-0.5">
                            <div className="flex items-center gap-1.5 font-bold text-ink">
                              <span>{item.network}</span>
                              <span>·</span>
                              <span className="text-brand-400">{item.token}</span>
                            </div>
                            <div className="font-mono text-[11px] text-ink-muted">
                              {item.spender_name} ({item.spender_address.slice(0, 8)}...{item.spender_address.slice(-6)})
                            </div>
                          </div>

                          <div className="text-right">
                            <span
                              className={`text-[10px] font-mono font-bold px-1.5 py-0.5 rounded ${
                                item.is_unlimited ? 'bg-rose-500/20 text-rose-300' : 'bg-surface-3 text-ink-muted'
                              }`}
                            >
                              {item.allowance}
                            </span>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div className="space-y-3">
              <div className="flex gap-2">
                <input
                  type="text"
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                  placeholder="输入空投官网链接，如 https://story.foundation"
                  className="input font-mono text-xs flex-1"
                />
                <button
                  type="button"
                  onClick={handleCheckDomain}
                  disabled={loading || !url.trim()}
                  className="btn-primary !py-1.5 text-xs shrink-0"
                >
                  {loading ? '检测中...' : '检测链接安全 🌐'}
                </button>
              </div>

              {domainResult && (
                <div className="space-y-3 animate-fade-in pt-2">
                  <div
                    className={`p-3.5 rounded-xl border flex items-center justify-between ${
                      domainResult.is_safe
                        ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
                        : 'border-rose-500/30 bg-rose-500/10 text-rose-300'
                    }`}
                  >
                    <div>
                      <div className="text-xs font-semibold">域名安全性评定</div>
                      <div className="text-base font-bold mt-0.5">
                        {domainResult.is_safe ? '✅ 官方正品正规站点' : `⚠️ ${domainResult.risk_level_zh}`}
                      </div>
                    </div>
                  </div>

                  <div className="rounded-xl border border-line bg-surface-2 p-3 text-xs space-y-1">
                    <span className="font-bold text-ink">逐项安全指标分析：</span>
                    <ul className="list-disc list-inside space-y-1 text-ink-muted mt-1">
                      {domainResult.reasons.map((r: string, i: number) => (
                        <li key={i}>{r}</li>
                      ))}
                    </ul>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
