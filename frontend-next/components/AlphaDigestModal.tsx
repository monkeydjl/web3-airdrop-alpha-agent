'use client';

import { apiFetch } from '@/lib/api';
import { useCallback, useEffect, useState } from 'react';
import { X, Copy, Download, RefreshCw, Check, BookOpen } from 'lucide-react';

interface DigestSummary {
  generated_at: string;
  date_str: string;
  window_days: number;
  total_scanned: number;
  total_farm: number;
  total_zero_cost: number;
  avg_top_score: number;
  top_picks_count: number;
  top_sectors: [string, number][];
  pua_warning_count: number;
}

interface DigestData {
  ok: boolean;
  markdown: string;
  summary: DigestSummary;
}

interface AlphaDigestModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export function AlphaDigestModal({ isOpen, onClose }: AlphaDigestModalProps) {
  const [windowDays, setWindowDays] = useState<number>(7);
  const [minScore, setMinScore] = useState<number>(70.0);
  const [data, setData] = useState<DigestData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [copied, setCopied] = useState(false);

  const fetchDigest = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const res = await apiFetch<DigestData>(
        `/projects/digest?window_days=${windowDays}&min_score=${minScore}&limit=15`,
      );
      setData(res);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '获取 Alpha 周报失败');
    } finally {
      setLoading(false);
    }
  }, [windowDays, minScore]);

  useEffect(() => {
    if (isOpen) {
      fetchDigest();
    }
  }, [isOpen, fetchDigest]);

  if (!isOpen) return null;

  const copyMarkdown = () => {
    if (!data?.markdown) return;
    navigator.clipboard.writeText(data.markdown);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const downloadMarkdown = () => {
    if (!data?.markdown) return;
    const blob = new Blob([data.markdown], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `Alpha_Digest_${data.summary?.date_str || 'latest'}_${windowDays}d.md`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-6 bg-black/60 backdrop-blur-xs animate-in fade-in duration-200">
      <div className="relative w-full max-w-4xl max-h-[90vh] flex flex-col rounded-2xl bg-surface border border-line shadow-2xl overflow-hidden">
        {/* Modal Header */}
        <div className="flex items-center justify-between border-b border-line px-5 py-4 bg-surface-2/40">
          <div className="flex items-center gap-2.5">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-brand-500/10 text-brand-600 dark:text-brand-400">
              <BookOpen className="h-5 w-5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h3 className="text-base font-semibold text-ink">🦅 Web3 Alpha 深度投研周报</h3>
                <span className="rounded-md bg-farm-soft px-2 py-0.5 text-[10px] font-semibold text-farm">
                  纯规则 0 成本
                </span>
              </div>
              <p className="text-xs text-ink-muted">
                批量聚合精选 FARM 项目、零成本测试网机会、VC 跑道存活率硬门禁与多钱包防女巫指南
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1.5 text-ink-faint hover:bg-surface-3 hover:text-ink transition-colors"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Filter and KPI Toolbar */}
        <div className="border-b border-line px-5 py-3 bg-surface flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className="text-ink-muted">时间跨度:</span>
            <div className="flex rounded-lg bg-surface-2 p-0.5">
              {[
                { label: '7 天 (周报)', val: 7 },
                { label: '14 天 (双周报)', val: 14 },
                { label: '30 天 (月报)', val: 30 },
              ].map((opt) => (
                <button
                  key={opt.val}
                  type="button"
                  onClick={() => setWindowDays(opt.val)}
                  className={`rounded px-2.5 py-1 transition ${
                    windowDays === opt.val
                      ? 'bg-surface font-semibold text-ink shadow-xs'
                      : 'text-ink-muted hover:text-ink'
                  }`}
                >
                  {opt.label}
                </button>
              ))}
            </div>

            <span className="ml-2 text-ink-muted">最低分:</span>
            <select
              value={minScore}
              onChange={(e) => setMinScore(Number(e.target.value))}
              className="rounded-lg border border-line bg-surface px-2 py-1 text-xs text-ink focus:outline-hidden"
            >
              <option value={60}>≥ 60 分</option>
              <option value={70}>≥ 70 分 (推荐)</option>
              <option value={80}>≥ 80 分 (严格)</option>
            </select>

            <button
              type="button"
              onClick={fetchDigest}
              disabled={loading}
              className="p-1 text-ink-muted hover:text-ink transition"
              title="刷新周报"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
            </button>
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={copyMarkdown}
              disabled={!data || loading}
              className="flex items-center gap-1.5 rounded-lg border border-line bg-surface px-3 py-1.5 text-xs font-medium text-ink hover:bg-surface-2 transition disabled:opacity-50"
            >
              {copied ? <Check className="h-3.5 w-3.5 text-farm" /> : <Copy className="h-3.5 w-3.5" />}
              <span>{copied ? '已复制 Markdown' : '复制 Markdown'}</span>
            </button>
            <button
              type="button"
              onClick={downloadMarkdown}
              disabled={!data || loading}
              className="flex items-center gap-1.5 rounded-lg bg-brand-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-brand-500 transition disabled:opacity-50"
            >
              <Download className="h-3.5 w-3.5" />
              <span>下载 .md</span>
            </button>
          </div>
        </div>

        {/* Quick KPI Cards */}
        {data?.summary ? (
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 border-b border-line px-5 py-2.5 bg-surface-2/20 text-xs">
            <div className="flex items-center justify-between px-2 py-1 rounded bg-surface border border-line/60">
              <span className="text-ink-muted">重点 FARM:</span>
              <span className="font-semibold text-farm">{data.summary.total_farm} 个</span>
            </div>
            <div className="flex items-center justify-between px-2 py-1 rounded bg-surface border border-line/60">
              <span className="text-ink-muted">零成本机会:</span>
              <span className="font-semibold text-brand-600 dark:text-brand-400">
                {data.summary.total_zero_cost} 个
              </span>
            </div>
            <div className="flex items-center justify-between px-2 py-1 rounded bg-surface border border-line/60">
              <span className="text-ink-muted">精选平均分:</span>
              <span className="font-semibold text-ink">{data.summary.avg_top_score} 分</span>
            </div>
            <div className="flex items-center justify-between px-2 py-1 rounded bg-surface border border-line/60">
              <span className="text-ink-muted">扫描总数:</span>
              <span className="font-semibold text-ink-muted">{data.summary.total_scanned} 个</span>
            </div>
          </div>
        ) : null}

        {/* Markdown Content Area */}
        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-4">
          {loading ? (
            <div className="space-y-4 py-8">
              <div className="skeleton h-8 w-1/2" />
              <div className="skeleton h-4 w-3/4" />
              <div className="skeleton h-24 w-full" />
              <div className="skeleton h-48 w-full" />
            </div>
          ) : error ? (
            <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700 dark:bg-red-500/10 dark:text-red-300">
              {error}
              <button type="button" onClick={fetchDigest} className="ml-3 underline font-semibold">
                重试
              </button>
            </div>
          ) : data ? (
            <div className="prose prose-sm dark:prose-invert max-w-none text-ink leading-relaxed">
              <pre className="p-4 rounded-xl bg-surface-2 border border-line text-xs font-mono whitespace-pre-wrap overflow-x-auto text-ink">
                {data.markdown}
              </pre>
            </div>
          ) : null}
        </div>

        {/* Modal Footer */}
        <div className="border-t border-line px-5 py-3 bg-surface-2/40 flex items-center justify-between text-xs text-ink-muted">
          <span>💡 提示：本周报支持导出为标准 Markdown，可直接导入 Notion、飞书、Obsidian 或投研文档库。</span>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg bg-surface border border-line px-4 py-1.5 text-xs font-medium text-ink hover:bg-surface-2 transition"
          >
            关闭
          </button>
        </div>
      </div>
    </div>
  );
}
