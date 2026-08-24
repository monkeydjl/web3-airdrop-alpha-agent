'use client';

import { apiFetch } from '@/lib/api';
import { useCallback, useEffect, useState } from 'react';

export interface AiBriefData {
  project_id: string;
  project_name?: string;
  mode: 'rule' | 'llm' | string;
  llm_available?: boolean;
  /**
   * 回退到规则引擎的原因。mode === 'llm' 时为 null。
   * 之所以需要它：只有 mode 时前端只能对所有降级说同一句话，
   * 而「没配密钥」和「今日预算用完了」的处置动作完全不同 ——
   * 说错会让人去查密钥，而问题在预算。
   */
  degraded_reason?: string | null;
  headline?: string;
  summary?: string;
  bullets?: string[];
  paragraphs?: string[];
  display_text?: string;
  label_zh?: string;
  score?: number;
  confidence?: number;
}

/** 把降级原因翻成一句「该怎么办」，而不是只说「降级了」。 */
function degradedNotice(data: AiBriefData): string {
  if (data.mode === 'llm') {
    return '以上由大模型根据系统评分因子生成，可能有误差；';
  }
  switch (data.degraded_reason) {
    case 'budget_exceeded':
      return '今日大模型预算已用完，以上为规则引擎生成的解读（UTC 零点自动恢复；要立即恢复请调大 LLM_DAILY_BUDGET_USD 并重启）；';
    case 'ledger_unavailable':
      return '预算账本暂时读不出来，为避免超支已暂停大模型调用，以上为规则引擎生成的解读；请检查数据库可写性；';
    case 'llm_error':
      return '大模型接口暂时不可用，以上为规则引擎生成的解读，稍后可重新生成；';
    case 'llm_disabled':
    default:
      return '当前未配置大模型密钥，以上为规则引擎根据评分因子自动拼装的解读；配置 OPENAI_API_KEY 后可获得更自然的文案。';
  }
}

export function AiBriefPanel({
  projectId,
  autoLoad = true,
}: {
  projectId: string;
  autoLoad?: boolean;
}) {
  const [data, setData] = useState<AiBriefData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    if (!projectId) return;
    setLoading(true);
    setError('');
    try {
      const res = await apiFetch<AiBriefData>(`/projects/${projectId}/ai-brief`, {
        method: 'POST',
        body: '{}',
      });
      setData(res);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '解读生成失败');
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    if (autoLoad && projectId) {
      load();
    }
  }, [autoLoad, projectId, load]);

  const paragraphs =
    data?.display_text
      ?.split(/\n\n+/)
      .map((p) => p.trim())
      .filter(Boolean) ||
    data?.paragraphs ||
    [];

  return (
    <section className="overflow-hidden border border-line bg-surface">
      <div className="border-b border-line px-4 py-3 sm:px-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold text-ink">智能解读</h3>
            <p className="mt-0.5 text-xs text-ink-muted">
              结合叙事 · 团队 · 风险 · 代币结构 · 系统理由
            </p>
          </div>
          <div className="flex items-center gap-2">
            {data ? (
              <span
                className={`badge ${
                  data.mode === 'llm'
                    ? 'bg-farm-soft text-farm dark:bg-farm/20 dark:text-farm'
                    : 'bg-surface-3 text-ink-muted'
                }`}
              >
                {data.mode === 'llm' ? '大模型增强' : '规则引擎'}
              </span>
            ) : null}
            <button type="button" className="btn-secondary !py-1.5 text-xs" onClick={load} disabled={loading}>
              {loading ? '生成中…' : data ? '重新生成' : '生成解读'}
            </button>
          </div>
        </div>
      </div>

      <div className="px-5 py-5 sm:px-6">
        {loading && !data ? (
          <div className="space-y-3">
            <div className="skeleton h-4 w-3/4" />
            <div className="skeleton h-4 w-full" />
            <div className="skeleton h-4 w-5/6" />
            <div className="skeleton h-20 w-full" />
          </div>
        ) : error ? (
          <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300">
            {error}
            <button type="button" className="ml-3 underline" onClick={load}>
              重试
            </button>
          </div>
        ) : data ? (
          <div className="space-y-4">
            {data.headline ? (
              <p className="text-base font-semibold leading-relaxed text-ink">{data.headline}</p>
            ) : null}

            {data.bullets && data.bullets.length > 0 ? (
              <ul className="grid gap-2 sm:grid-cols-2">
                {data.bullets.map((b) => (
                  <li
                    key={b}
                    className="flex gap-2 rounded-xl border border-line/80 bg-surface-2/60 px-3 py-2 text-sm text-ink-muted"
                  >
                    <span className="mt-0.5 text-farm">▸</span>
                    <span>{b}</span>
                  </li>
                ))}
              </ul>
            ) : null}

            <div className="space-y-3 border-t border-line pt-4">
              {paragraphs.map((p, i) => (
                <p key={i} className="text-sm leading-7 text-ink/90 whitespace-pre-wrap">
                  {p}
                </p>
              ))}
            </div>

            <p className="border-t border-line pt-3 text-[11px] text-ink-faint">
              {degradedNotice(data)}
              不构成投资建议。
            </p>
          </div>
        ) : (
          <div className="py-6 text-center">
            <p className="text-sm text-ink-muted">点击「生成解读」获取针对本项目的完整分析说明</p>
            <button type="button" className="btn-primary mt-4" onClick={load}>
              生成智能解读
            </button>
          </div>
        )}
      </div>
    </section>
  );
}
