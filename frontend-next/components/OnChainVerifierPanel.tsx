'use client';

import { useState, useEffect, useCallback } from 'react';
import { apiFetch } from '@/lib/api';
import type { SupportedChain, OnChainVerificationResult } from '@/lib/types';
import {
  Activity,
  CheckCircle2,
  XCircle,
  Search,
  Copy,
  Check,
  Zap,
  Globe,
  Code2,
} from 'lucide-react';

export interface OnChainVerifierPanelProps {
  initialAddress?: string;
  defaultChain?: string;
  title?: string;
  subtitle?: string;
}

const SAMPLE_ADDRESSES = [
  {
    name: 'Sepolia Uniswap V3 Router',
    chain: 'sepolia',
    address: '0x3bFA4769FB09eefC5a80d6E87c3B9C650f7Ae48E',
  },
  {
    name: 'Sepolia WETH9',
    chain: 'sepolia',
    address: '0x7b79995e5f793A07Bc00c21412e50Ecae098E7f9',
  },
];

export function OnChainVerifierPanel({
  initialAddress = '',
  defaultChain = 'sepolia',
  title = '链上合约存活性探测器 (On-Chain Verifier)',
  subtitle = '100% 免 Key 公共 RPC 节点实时校验合约字节码与链上交互活跃度',
}: OnChainVerifierPanelProps) {
  const [chains, setChains] = useState<SupportedChain[]>([]);
  const [selectedChain, setSelectedChain] = useState<string>(defaultChain);
  const [address, setAddress] = useState<string>(initialAddress);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<OnChainVerificationResult | null>(null);
  const [copied, setCopied] = useState<boolean>(false);

  // 加载支持的公共 RPC 链列表
  useEffect(() => {
    let cancelled = false;
    apiFetch<{ ok: boolean; data: SupportedChain[] }>('/onchain/chains')
      .then((res) => {
        if (!cancelled && res.ok && Array.isArray(res.data)) {
          setChains(res.data);
          if (res.data.length > 0 && !res.data.some((c) => c.key === defaultChain)) {
            setSelectedChain(res.data[0].key);
          }
        }
      })
      .catch((err) => {
        if (!cancelled) {
          console.error('Failed to load onchain chains:', err);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [defaultChain]);

  const handleVerify = useCallback(async () => {
    const trimmed = address.trim();
    if (!trimmed) {
      setError('请输入待探测的 EVM 地址');
      return;
    }

    if (!/^0x[0-9a-fA-F]{40}$/.test(trimmed)) {
      setError('地址格式不正确，必须为 0x 开头的 40 位十六进制字符');
      return;
    }

    setError(null);
    setLoading(true);

    try {
      const res = await apiFetch<{ ok: boolean; data: OnChainVerificationResult }>('/onchain/verify', {
        method: 'POST',
        body: JSON.stringify({
          address: trimmed,
          chain: selectedChain,
        }),
      });

      if (res.ok && res.data) {
        setResult(res.data);
      } else {
        setError('探测失败，公共 RPC 节点无有效响应');
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '请求探测出错，请稍后重试');
    } finally {
      setLoading(false);
    }
  }, [address, selectedChain]);

  const handleCopy = useCallback((text: string) => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }, []);

  return (
    <div className="card p-4 sm:p-5 space-y-4">
      {/* 头部标题与免 Key 徽标 */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line pb-3">
        <div className="space-y-0.5">
          <div className="flex items-center gap-2">
            <Activity className="h-4 w-4 text-cyan-400" />
            <h3 className="text-sm font-semibold text-ink">{title}</h3>
            <span className="badge bg-cyan-500/15 text-cyan-400 border border-cyan-500/30 text-[10px]">
              免 Key 公共 RPC
            </span>
          </div>
          <p className="text-xs text-ink-muted">{subtitle}</p>
        </div>
        <div className="flex items-center gap-1.5 text-[11px] text-ink-faint">
          <Globe className="h-3.5 w-3.5" />
          <span>{chains.length} 条已配置免费网络</span>
        </div>
      </div>

      {/* 控制表单：网络选择 + 地址输入 + 探测按钮 */}
      <div className="space-y-3">
        <div className="grid gap-2.5 sm:grid-cols-[14rem_1fr_auto]">
          {/* 网络选择下拉 */}
          <div>
            <label className="block text-[11px] font-medium text-ink-muted mb-1">
              目标网络
            </label>
            <select
              className="select w-full text-xs"
              value={selectedChain}
              onChange={(e) => setSelectedChain(e.target.value)}
              disabled={loading}
            >
              {chains.map((c) => (
                <option key={c.key} value={c.key}>
                  {c.name} ({c.type === 'testnet' ? '测试网' : '主网'})
                </option>
              ))}
              {chains.length === 0 && (
                <option value="sepolia">Ethereum Sepolia (测试网)</option>
              )}
            </select>
          </div>

          {/* 地址输入框 */}
          <div>
            <label className="block text-[11px] font-medium text-ink-muted mb-1">
              合约或账户地址 (0x...)
            </label>
            <div className="relative">
              <input
                type="text"
                className="input w-full font-mono text-xs pr-8"
                placeholder="0x..."
                value={address}
                onChange={(e) => {
                  setAddress(e.target.value);
                  if (error) setError(null);
                }}
                disabled={loading}
              />
              {address && (
                <button
                  type="button"
                  onClick={() => setAddress('')}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-ink-faint hover:text-ink text-xs"
                  title="清空"
                >
                  ✕
                </button>
              )}
            </div>
          </div>

          {/* 探测动作按钮 */}
          <div className="flex items-end">
            <button
              type="button"
              className="btn-primary min-h-[34px] w-full sm:w-auto inline-flex items-center justify-center gap-1.5 text-xs font-medium"
              onClick={handleVerify}
              disabled={loading || !address.trim()}
            >
              {loading ? (
                <>
                  <span className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-slate-950 border-t-transparent" />
                  <span>探测中…</span>
                </>
              ) : (
                <>
                  <Search className="h-3.5 w-3.5" />
                  <span>探测存活性</span>
                </>
              )}
            </button>
          </div>
        </div>

        {/* 快速填入样本地址 */}
        <div className="flex flex-wrap items-center gap-2 pt-0.5 text-[11px] text-ink-muted">
          <span className="text-ink-faint">快速体验样本:</span>
          {SAMPLE_ADDRESSES.map((sample) => (
            <button
              key={sample.name}
              type="button"
              className="rounded border border-line bg-surface-2 px-2 py-0.5 font-mono text-[10px] text-ink-muted hover:border-ink-muted hover:text-ink transition-colors"
              onClick={() => {
                setAddress(sample.address);
                setSelectedChain(sample.chain);
                if (error) setError(null);
              }}
            >
              {sample.name}
            </button>
          ))}
        </div>

        {/* 错误提示 */}
        {error && (
          <div className="rounded-md border border-rose-500/30 bg-rose-500/10 p-2.5 text-xs text-rose-300 flex items-center gap-2">
            <XCircle className="h-4 w-4 shrink-0 text-rose-400" />
            <span>{error}</span>
          </div>
        )}
      </div>

      {/* 探测结果看板 */}
      {result && (
        <div className="mt-4 rounded-lg border border-line bg-surface-1 p-4 space-y-3 animate-fade-in">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line/60 pb-2.5">
            <div className="flex items-center gap-2">
              {result.is_contract ? (
                <span className="inline-flex items-center gap-1 rounded border border-emerald-500/30 bg-emerald-500/15 px-2.5 py-0.5 text-xs font-semibold text-emerald-400">
                  <CheckCircle2 className="h-3.5 w-3.5" />
                  智能合约 (Bytecode Active)
                </span>
              ) : (
                <span className="inline-flex items-center gap-1 rounded border border-slate-500/30 bg-slate-500/15 px-2.5 py-0.5 text-xs font-semibold text-slate-400">
                  <Code2 className="h-3.5 w-3.5" />
                  外部账户 / 未部署字节码 (EOA)
                </span>
              )}
              <span className="font-mono text-xs text-ink-muted uppercase">
                {result.chain}
              </span>
            </div>

            <div className="flex items-center gap-2 text-xs">
              <span className="text-ink-muted">RPC 响应延迟:</span>
              <span
                className={`font-mono text-xs font-semibold px-1.5 py-0.5 rounded ${
                  result.latency_ms < 300
                    ? 'bg-emerald-500/15 text-emerald-400'
                    : result.latency_ms < 800
                      ? 'bg-amber-500/15 text-amber-400'
                      : 'bg-rose-500/15 text-rose-400'
                }`}
              >
                {result.latency_ms} ms
              </span>
            </div>
          </div>

          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 text-xs">
            {/* 地址 */}
            <div className="sm:col-span-2 space-y-1">
              <span className="text-ink-muted">已探测地址</span>
              <div className="flex items-center gap-1.5 font-mono text-[11px] text-ink bg-surface-2 p-1.5 rounded border border-line break-all">
                <span>{result.address}</span>
                <button
                  type="button"
                  onClick={() => handleCopy(result.address)}
                  className="ml-auto shrink-0 p-1 text-ink-faint hover:text-ink"
                  title="复制地址"
                >
                  {copied ? (
                    <Check className="h-3 w-3 text-emerald-400" />
                  ) : (
                    <Copy className="h-3 w-3" />
                  )}
                </button>
              </div>
            </div>

            {/* 字节码大小 */}
            <div className="space-y-1">
              <span className="text-ink-muted">字节码大小</span>
              <div className="font-mono text-sm font-semibold text-ink bg-surface-2 p-1.5 rounded border border-line">
                {result.bytecode_length.toLocaleString()} <span className="text-[10px] text-ink-faint">字节</span>
              </div>
            </div>

            {/* Nonce / 交易计数 */}
            <div className="space-y-1">
              <span className="text-ink-muted">链上交易计数 (Nonce)</span>
              <div className="font-mono text-sm font-semibold text-ink bg-surface-2 p-1.5 rounded border border-line">
                {result.nonce.toLocaleString()} <span className="text-[10px] text-ink-faint">笔</span>
              </div>
            </div>
          </div>

          {/* 探测节点明细 */}
          <div className="flex flex-wrap items-center justify-between gap-2 pt-1 border-t border-line/40 text-[11px] text-ink-faint">
            <div className="flex items-center gap-1">
              <Zap className="h-3 w-3 text-cyan-400" />
              <span>响应节点:</span>
              <span className="font-mono">{result.rpc_endpoint || '公共免 Key 节点'}</span>
            </div>
            <div>
              <span>探测时间: {new Date(result.verified_at).toLocaleTimeString('zh-CN')}</span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
