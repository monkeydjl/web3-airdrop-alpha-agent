'use client';

import { useState } from 'react';
import { apiFetch } from '@/lib/api';

interface SybilDefenseModalProps {
  initialAddress?: string;
  onClose: () => void;
}

export function SybilDefenseModal({ initialAddress = '', onClose }: SybilDefenseModalProps) {
  const [address, setAddress] = useState(initialAddress);
  const [project, setProject] = useState('LayerZero');
  const [reason, setReason] = useState('误判女巫清洗名单，申请人工复核 (False-positive sybil flag)');
  const [customNotes, setCustomNotes] = useState('长期真实个人交互，多链分布与独立设备环境');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<any | null>(null);
  const [copied, setCopied] = useState(false);

  const handleGenerate = async () => {
    if (!address.trim()) return;
    setLoading(true);
    setResult(null);
    try {
      const res = await apiFetch<{ ok: boolean; data: any }>('/sybil/generate-dossier', {
        method: 'POST',
        body: JSON.stringify({
          wallet_address: address.trim(),
          project_name: project.trim(),
          appeal_reason: reason.trim(),
          custom_notes: customNotes.trim(),
        }),
      });
      if (res?.data) {
        setResult(res.data);
      }
    } catch {
      // 异常捕获
    } finally {
      setLoading(false);
    }
  };

  const copyMarkdown = () => {
    if (!result?.markdown_dossier) return;
    navigator.clipboard.writeText(result.markdown_dossier);
    setCopied(true);
    setTimeout(() => setCopied(false), 2500);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm animate-fade-in">
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
            <span>链上女巫清洗自证报告与申诉存证导出器</span>
          </h2>
          <p className="text-xs text-ink-muted mt-0.5">
            自动采集多链 Nonce 与离散度，生成符合项目方审核标准的非女巫独立参与者声明
          </p>
        </div>

        <div className="space-y-3.5 overflow-y-auto flex-1 pr-1">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div className="space-y-1">
              <label className="text-[11px] font-semibold text-ink-muted">申诉钱包地址 (EVM)</label>
              <input
                type="text"
                value={address}
                onChange={(e) => setAddress(e.target.value)}
                placeholder="0x..."
                className="input font-mono text-xs w-full"
              />
            </div>
            <div className="space-y-1">
              <label className="text-[11px] font-semibold text-ink-muted">申诉目标项目</label>
              <input
                type="text"
                value={project}
                onChange={(e) => setProject(e.target.value)}
                placeholder="如 LayerZero, Linea, ZKsync"
                className="input text-xs w-full"
              />
            </div>
          </div>

          <div className="space-y-1">
            <label className="text-[11px] font-semibold text-ink-muted">申诉核心理由</label>
            <input
              type="text"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              className="input text-xs w-full"
            />
          </div>

          <div className="space-y-1">
            <label className="text-[11px] font-semibold text-ink-muted">独立性补充自述与网络环境证据</label>
            <textarea
              rows={2}
              value={customNotes}
              onChange={(e) => setCustomNotes(e.target.value)}
              placeholder="说明交互习惯、多链活动背景、独立网络与设备环境等..."
              className="input text-xs w-full resize-none"
            />
          </div>

          <div className="flex justify-end">
            <button
              type="button"
              onClick={handleGenerate}
              disabled={loading || !address.trim()}
              className="btn-primary !py-2 text-xs flex items-center gap-1.5"
            >
              {loading ? (
                <>
                  <span className="h-3 w-3 animate-spin rounded-full border-2 border-white/30 border-t-white" />
                  <span>正在链上查证并生成...</span>
                </>
              ) : (
                <span>⚡ 一键生成防女巫申诉存证报告</span>
              )}
            </button>
          </div>

          {/* 生成结果展示 */}
          {result && (
            <div className="mt-4 pt-4 border-t border-line space-y-3 animate-fade-in">
              <div className="flex flex-wrap items-center justify-between gap-2 p-3 rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-emerald-400">
                <div className="text-xs">
                  <span className="font-bold">独立性审核评分：</span>
                  <span className="font-mono text-sm font-extrabold ml-1">{result.independence_score} / 100</span>
                  <span className="text-[11px] ml-2 text-ink-muted">({result.verdict})</span>
                </div>
                <button
                  type="button"
                  onClick={copyMarkdown}
                  className="btn-secondary !py-1 text-xs"
                >
                  {copied ? '✅ 已复制报告全文' : '📋 复制申诉 Markdown'}
                </button>
              </div>

              <div className="rounded-xl border border-line bg-surface-2 p-3.5 max-h-64 overflow-y-auto font-mono text-[11px] text-ink whitespace-pre-wrap leading-relaxed">
                {result.markdown_dossier}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
