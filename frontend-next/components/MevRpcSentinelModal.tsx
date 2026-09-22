'use client';

import { useEffect, useState } from 'react';
import { apiFetch } from '@/lib/api';

interface MevRpcNode {
  id: string;
  name: string;
  chain_id: number;
  chain_name: string;
  rpc_url: string;
  fast_rpc_url: string;
  website: string;
  anti_sandwich: boolean;
  anti_frontrunning: boolean;
  mev_refund: boolean;
  mev_refund_pct: number;
  zero_gas_on_failure: boolean;
  trust_score: number;
  latency_ms: number;
  features: string[];
  setup_guide: string;
  network_config: {
    chainId: string;
    chainName: string;
    rpcUrls: string[];
    nativeCurrency: { name: string; symbol: string; decimals: number };
    blockExplorerUrls: string[];
  };
}

interface BenchmarkResult {
  status: string;
  node_info: MevRpcNode;
  latency_ms: number;
  safety_rating: string;
  rating_description: string;
  recommended_for: string[];
}

interface MevRpcSentinelModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export default function MevRpcSentinelModal({ isOpen, onClose }: MevRpcSentinelModalProps) {
  const [nodes, setNodes] = useState<MevRpcNode[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedNode, setSelectedNode] = useState<MevRpcNode | null>(null);
  const [benchmark, setBenchmark] = useState<BenchmarkResult | null>(null);
  const [benchmarking, setBenchmarking] = useState(false);
  const [copiedKey, setCopiedKey] = useState<string | null>(null);

  useEffect(() => {
    if (!isOpen) return;
    setLoading(true);
    apiFetch<{ data: { nodes: MevRpcNode[] } }>('/mev-rpc/nodes')
      .then((res) => {
        if (res?.data?.nodes) {
          setNodes(res.data.nodes);
          if (res.data.nodes.length > 0 && !selectedNode) {
            setSelectedNode(res.data.nodes[0]);
          }
        }
      })
      .catch((err) => console.error('Failed to load MEV nodes', err))
      .finally(() => setLoading(false));
  }, [isOpen]);

  const handleBenchmark = async (node: MevRpcNode) => {
    setSelectedNode(node);
    setBenchmarking(true);
    try {
      const res = await apiFetch<{ data: BenchmarkResult }>('/mev-rpc/benchmark', {
        method: 'POST',
        body: JSON.stringify({ node_id: node.id }),
      });
      if (res?.data) {
        setBenchmark(res.data);
      }
    } catch (e) {
      console.error('Benchmark failed', e);
    } finally {
      setBenchmarking(false);
    }
  };

  const copyToClipboard = (text: string, key: string) => {
    navigator.clipboard.writeText(text);
    setCopiedKey(key);
    setTimeout(() => setCopiedKey(null), 2000);
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm animate-fade-in">
      <div className="relative flex max-h-[92vh] w-full max-w-4xl flex-col rounded-2xl border border-line bg-surface p-6 shadow-2xl overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-line pb-4">
          <div className="flex items-center gap-2.5">
            <span className="text-2xl">🛡️</span>
            <div>
              <h3 className="text-lg font-bold text-ink">智能防夹 (MEV) 与私有 RPC 路由哨兵</h3>
              <p className="text-xs text-ink-muted">
                直通验证者 Builder 专用通道，防御三明治夹子与抢跑套利，支持最高 90% 利润现金回退
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
          {loading ? (
            <div className="py-12 text-center text-sm text-ink-muted">正在检索受信防夹节点…</div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-12 gap-5">
              {/* Nodes List */}
              <div className="md:col-span-5 space-y-2.5">
                <h4 className="text-xs font-semibold text-ink-muted uppercase tracking-wider">推荐受信节点</h4>
                {nodes.map((node) => {
                  const isSelected = selectedNode?.id === node.id;
                  return (
                    <div
                      key={node.id}
                      onClick={() => handleBenchmark(node)}
                      className={`cursor-pointer rounded-xl border p-3.5 transition ${
                        isSelected
                          ? 'border-brand-500 bg-brand-500/10 shadow-sm ring-1 ring-brand-500'
                          : 'border-line/70 bg-surface-2/40 hover:bg-surface-2/80'
                      }`}
                    >
                      <div className="flex items-center justify-between">
                        <div className="font-semibold text-xs text-ink">{node.name}</div>
                        <span className="font-mono text-[10px] px-1.5 py-0.5 rounded bg-surface-3 text-ink-muted">
                          {node.chain_name}
                        </span>
                      </div>
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        {node.anti_sandwich && (
                          <span className="rounded bg-emerald-500/15 px-1.5 py-0.5 text-[10px] font-medium text-emerald-400">
                            ✓ 防三明治夹子
                          </span>
                        )}
                        {node.mev_refund && (
                          <span className="rounded bg-amber-500/15 px-1.5 py-0.5 text-[10px] font-medium text-amber-400">
                            💰 {node.mev_refund_pct}% 利润返还
                          </span>
                        )}
                        {node.zero_gas_on_failure && (
                          <span className="rounded bg-blue-500/15 px-1.5 py-0.5 text-[10px] font-medium text-blue-400">
                            失败免Gas
                          </span>
                        )}
                      </div>
                      <div className="mt-2 text-[11px] font-mono text-ink-faint truncate">{node.rpc_url}</div>
                    </div>
                  );
                })}
              </div>

              {/* Node Details & Benchmark */}
              <div className="md:col-span-7 space-y-4">
                {selectedNode && (
                  <div className="rounded-xl border border-line bg-surface-2/30 p-4 space-y-4">
                    <div className="flex items-start justify-between">
                      <div>
                        <div className="flex items-center gap-2">
                          <h4 className="font-bold text-sm text-ink">{selectedNode.name}</h4>
                          <span className="px-2 py-0.5 rounded-full bg-brand-500/20 text-brand-400 font-mono text-xs font-bold">
                            信任评分 {selectedNode.trust_score}/100
                          </span>
                        </div>
                        <p className="mt-1 text-xs text-ink-muted">{selectedNode.setup_guide}</p>
                      </div>
                    </div>

                    {/* Features Badges */}
                    <div className="flex flex-wrap gap-1.5">
                      {selectedNode.features.map((f, i) => (
                        <span key={i} className="px-2 py-0.5 rounded-md bg-surface-3 text-xs text-ink-muted">
                          ⚡ {f}
                        </span>
                      ))}
                    </div>

                    {/* Benchmark Card */}
                    <div className="rounded-lg border border-line/80 bg-surface p-3 space-y-2">
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-semibold text-ink">连通性与实测评分</span>
                        <button
                          type="button"
                          onClick={() => handleBenchmark(selectedNode)}
                          disabled={benchmarking}
                          className="px-2.5 py-1 text-xs font-semibold rounded bg-brand-500/20 text-brand-400 hover:bg-brand-500/30 transition disabled:opacity-50"
                        >
                          {benchmarking ? '测试中…' : '🔄 测速与诊断'}
                        </button>
                      </div>
                      <div className="grid grid-cols-2 gap-2 pt-1">
                        <div className="p-2 rounded bg-surface-2 text-center">
                          <div className="text-[10px] text-ink-muted">响应延迟</div>
                          <div className="text-base font-bold text-emerald-400 font-mono">
                            {benchmark ? `${benchmark.latency_ms} ms` : `${selectedNode.latency_ms} ms`}
                          </div>
                        </div>
                        <div className="p-2 rounded bg-surface-2 text-center">
                          <div className="text-[10px] text-ink-muted">安全防护评级</div>
                          <div className="text-base font-bold text-brand-400 font-mono">
                            {benchmark ? benchmark.safety_rating : 'A+'}
                          </div>
                        </div>
                      </div>
                    </div>

                    {/* Wallet Config Parameters */}
                    <div className="rounded-lg border border-line/80 bg-surface p-3 space-y-2">
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-semibold text-ink">MetaMask / Rabby 导入参数</span>
                        <button
                          type="button"
                          onClick={() => copyToClipboard(selectedNode.rpc_url, 'rpc')}
                          className="text-[11px] font-semibold text-brand-400 hover:underline"
                        >
                          {copiedKey === 'rpc' ? '✓ 已复制 RPC URL' : '复制 RPC URL'}
                        </button>
                      </div>
                      <div className="space-y-1.5 text-xs font-mono">
                        <div className="flex justify-between p-1.5 rounded bg-surface-2">
                          <span className="text-ink-muted">Network Name:</span>
                          <span className="text-ink">{selectedNode.network_config.chainName}</span>
                        </div>
                        <div className="flex justify-between p-1.5 rounded bg-surface-2">
                          <span className="text-ink-muted">RPC URL:</span>
                          <span className="text-ink truncate max-w-[200px]">{selectedNode.rpc_url}</span>
                        </div>
                        <div className="flex justify-between p-1.5 rounded bg-surface-2">
                          <span className="text-ink-muted">Chain ID:</span>
                          <span className="text-ink">{selectedNode.network_config.chainId} ({selectedNode.chain_id})</span>
                        </div>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="border-t border-line pt-3 flex items-center justify-between text-xs text-ink-muted">
          <span>提示：在领取大额空投或进行 $5,000+ DEX Swap 前，请切换为防夹 RPC 以免被 Sandwich Bot 抽走滑点。</span>
          <button type="button" onClick={onClose} className="btn-secondary !py-1 !px-4">
            关闭
          </button>
        </div>
      </div>
    </div>
  );
}
