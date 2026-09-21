'use client';

import { useState } from 'react';
import { X, Copy, Check, FileText, Sparkles } from 'lucide-react';
import { LabelBadge } from './ui';

export interface AlphaDossierData {
  project_id: string;
  project_name: string;
  generated_at: string;
  markdown: string;
  summary: {
    project_id: string;
    name: string;
    score: number;
    label: string;
    viability_tier?: string;
    fatigue_index?: number;
    friction_tier?: string;
    runway_months?: number;
    consensus_tier?: string;
    consensus_signals?: number;
    multi_wallet_tier?: string;
    recommended_wallets?: number;
    tasks_count?: number;
  };
}

export function AlphaDossierModal({
  dossier,
  onClose,
}: {
  dossier: AlphaDossierData;
  onClose: () => void;
}) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(dossier.markdown);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // fallback
    }
  };

  const { summary } = dossier;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm animate-fade-in">
      <div className="relative flex flex-col w-full max-w-4xl max-h-[90vh] bg-surface-1 border border-line rounded-xl shadow-2xl overflow-hidden">
        {/* Modal Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-line bg-surface-2/60">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-brand/10 border border-brand/20 rounded-lg text-brand">
              <FileText className="w-5 h-5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-lg font-bold text-ink">Alpha 深度投研研报</h2>
                <span className="text-xs px-2 py-0.5 rounded-full bg-surface-3 text-ink-muted border border-line">
                  {dossier.project_name}
                </span>
                <LabelBadge label={summary.label} />
              </div>
              <p className="text-xs text-ink-muted mt-0.5">
                零 Token 消耗 · 100% 规则确定性聚合 · 生成于 {dossier.generated_at}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={handleCopy}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-surface-3 hover:bg-surface-2 text-ink border border-line transition-colors"
              title="复制 Markdown 研报源码"
            >
              {copied ? (
                <>
                  <Check className="w-3.5 h-3.5 text-emerald-400" />
                  <span className="text-emerald-400">已复制到剪贴板</span>
                </>
              ) : (
                <>
                  <Copy className="w-3.5 h-3.5" />
                  <span>复制 Markdown</span>
                </>
              )}
            </button>
            <button
              type="button"
              onClick={onClose}
              className="p-1.5 text-ink-muted hover:text-ink rounded-lg hover:bg-surface-3 transition-colors"
              aria-label="关闭"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* Summary Quick Bar */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 px-6 py-3 border-b border-line bg-surface-1/50 text-xs">
          <div className="flex flex-col">
            <span className="text-ink-muted">综合评分</span>
            <span className="text-sm font-bold font-mono text-ink mt-0.5">{summary.score} 分</span>
          </div>
          <div className="flex flex-col">
            <span className="text-ink-muted">PUA 疲劳指数</span>
            <span className="text-sm font-bold font-mono text-ink mt-0.5">
              {summary.fatigue_index !== undefined ? `${summary.fatigue_index} / 1.0` : '—'}
            </span>
          </div>
          <div className="flex flex-col">
            <span className="text-ink-muted">资金摩擦</span>
            <span className="text-sm font-bold text-ink mt-0.5 capitalize">
              {summary.friction_tier ? summary.friction_tier.replace('_', ' ') : '—'}
            </span>
          </div>
          <div className="flex flex-col">
            <span className="text-ink-muted">建议多钱包</span>
            <span className="text-sm font-bold text-brand mt-0.5">
              {summary.recommended_wallets ? `${summary.recommended_wallets} 个隔离钱包` : '单钱包/不建议'}
            </span>
          </div>
        </div>

        {/* Markdown Content Area */}
        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-4">
          <pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed text-ink bg-surface-2/40 p-5 rounded-lg border border-line select-text">
            {dossier.markdown}
          </pre>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between px-6 py-3 border-t border-line bg-surface-2/40 text-xs text-ink-muted">
          <span className="flex items-center gap-1.5">
            <Sparkles className="w-3.5 h-3.5 text-brand" />
            6 大模块全要素自动交叉核验已完成
          </span>
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-1.5 text-xs font-medium rounded-lg bg-surface-3 hover:bg-surface-2 text-ink border border-line transition-colors"
          >
            关闭预览
          </button>
        </div>
      </div>
    </div>
  );
}
