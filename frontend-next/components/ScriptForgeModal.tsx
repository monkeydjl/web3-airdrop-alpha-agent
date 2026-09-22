'use client';

import { useEffect, useState } from 'react';
import { apiFetch } from '@/lib/api';

interface ScriptForgeModalProps {
  initialProjectName?: string;
  onClose: () => void;
}

export function ScriptForgeModal({
  initialProjectName = 'Story Protocol',
  onClose,
}: ScriptForgeModalProps) {
  const [projectName, setProjectName] = useState(initialProjectName);
  const [contractAddress, setContractAddress] = useState('0x7777777254eeb25477b68fb85ed929f73a960582');
  const [rpcUrl, setRpcUrl] = useState('https://odyssey.storyrpc.io');
  const [jitterMin, setJitterMin] = useState(15);
  const [jitterMax, setJitterMax] = useState(60);

  const [activeTab, setActiveTab] = useState<'foundry_cast' | 'web3_py' | 'viem_ts'>('web3_py');
  const [scripts, setScripts] = useState<Record<string, string> | null>(null);
  const [loading, setLoading] = useState(false);
  const [copied, setCopied] = useState(false);

  const handleGenerate = async () => {
    setLoading(true);
    try {
      const res = await apiFetch<{ ok: boolean; scripts: Record<string, string> }>('/scripts/generate', {
        method: 'POST',
        body: JSON.stringify({
          project_name: projectName,
          contract_address: contractAddress,
          rpc_url: rpcUrl,
          jitter_min: Number(jitterMin),
          jitter_max: Number(jitterMax),
        }),
      });
      if (res?.scripts) {
        setScripts(res.scripts);
      }
    } catch {
      // 捕获异常
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    handleGenerate();
  }, []);

  const copyCurrentScript = () => {
    if (!scripts || !scripts[activeTab]) return;
    navigator.clipboard.writeText(scripts[activeTab]);
    setCopied(true);
    setTimeout(() => setCopied(false), 2500);
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
            <span>⚡</span>
            <span>自动化交互 CLI 脚本与防女巫模板工坊</span>
          </h2>
          <p className="text-xs text-ink-muted mt-0.5">
            一键生成内置随机时间离散度 (Jitter) 与微量 Gas 扰动的开源安全执行脚本
          </p>
        </div>

        <div className="space-y-3.5 overflow-y-auto flex-1 pr-1">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div className="space-y-1">
              <label className="text-[11px] font-semibold text-ink-muted">项目名称</label>
              <input
                type="text"
                value={projectName}
                onChange={(e) => setProjectName(e.target.value)}
                className="input text-xs w-full"
              />
            </div>
            <div className="space-y-1">
              <label className="text-[11px] font-semibold text-ink-muted">RPC 节点 URL</label>
              <input
                type="text"
                value={rpcUrl}
                onChange={(e) => setRpcUrl(e.target.value)}
                className="input font-mono text-xs w-full"
              />
            </div>
          </div>

          <div className="space-y-1">
            <label className="text-[11px] font-semibold text-ink-muted">目标交互智能合约地址</label>
            <input
              type="text"
              value={contractAddress}
              onChange={(e) => setContractAddress(e.target.value)}
              className="input font-mono text-xs w-full"
            />
          </div>

          <div className="grid grid-cols-2 gap-3 p-3 rounded-xl bg-surface-2 border border-line">
            <div>
              <label className="text-[11px] font-semibold text-ink">防女巫时间抖动下限 (秒)</label>
              <input
                type="number"
                value={jitterMin}
                onChange={(e) => setJitterMin(Number(e.target.value))}
                className="input font-mono text-xs w-full mt-1"
              />
            </div>
            <div>
              <label className="text-[11px] font-semibold text-ink">防女巫时间抖动上限 (秒)</label>
              <input
                type="number"
                value={jitterMax}
                onChange={(e) => setJitterMax(Number(e.target.value))}
                className="input font-mono text-xs w-full mt-1"
              />
            </div>
          </div>

          <div className="flex justify-between items-center pt-1">
            <div className="flex items-center gap-1.5">
              {[
                { id: 'web3_py', label: '🐍 Python (Web3.py)' },
                { id: 'foundry_cast', label: '🔨 Foundry Cast' },
                { id: 'viem_ts', label: '🔷 TypeScript (Viem)' },
              ].map((t) => (
                <button
                  key={t.id}
                  type="button"
                  onClick={() => setActiveTab(t.id as any)}
                  className={`px-3 py-1 rounded-xl text-xs font-semibold transition ${
                    activeTab === t.id
                      ? 'bg-brand-500 text-white shadow-sm'
                      : 'bg-surface-2 text-ink-muted hover:text-ink'
                  }`}
                >
                  {t.label}
                </button>
              ))}
            </div>

            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={handleGenerate}
                disabled={loading}
                className="btn-secondary !py-1 text-xs"
              >
                {loading ? '生成中...' : '重新生成 ⟳'}
              </button>
              <button
                type="button"
                onClick={copyCurrentScript}
                className="btn-primary !py-1 text-xs flex items-center gap-1"
              >
                <span>{copied ? '✅ 已复制代码' : '📋 复制脚本'}</span>
              </button>
            </div>
          </div>

          {/* 脚本展示区 */}
          {scripts && (
            <div className="rounded-xl border border-line bg-surface-2 p-3.5 max-h-72 overflow-y-auto font-mono text-[11px] text-ink whitespace-pre-wrap leading-relaxed">
              {scripts[activeTab]}
            </div>
          )}

          <div className="text-[10px] text-ink-faint">
            🔒 安全说明：脚本直接调用标准 Web3 库并在您的本地终端运行，私钥保留在本地，绝无第三方服务器收集。
          </div>
        </div>
      </div>
    </div>
  );
}
