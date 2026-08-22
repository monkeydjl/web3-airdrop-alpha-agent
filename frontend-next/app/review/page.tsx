'use client';

import { TopBar } from '@/components/TopBar';
import Link from 'next/link';
import { useCallback, useEffect, useRef, useState } from 'react';
import { RefreshCw } from 'lucide-react';
import { apiFetch } from '@/lib/api';
import { useAsyncData } from '@/lib/useAsyncData';
import { relativeTime, stageZh } from '@/lib/format';
import { LabelBadge, Toast } from '@/components/ui';

/** 后端 GET /api/v1/feedback/pending-review 的单条结构 */
interface PendingItem {
  project_id: string;
  name: string | null;
  sector: string | null;
  stage: string | null;
  score: number | null;
  label: string | null;
  confidence: number | null;
  url: string | null;
  updated_at: string | null;
  has_interaction: boolean;
  priority_reason: string | null;
}

interface PendingData {
  items: PendingItem[];
  total_pending: number;
  returned: number;
  already_marked: number;
}

interface CalibrationStatus {
  weight_version?: string;
  min_samples_gate?: number;
  total_feedback?: number;
  strong_samples?: number;
  calibration_ready?: boolean;
  samples_needed?: number;
}

/** 后端 outcome 枚举（WEIGHT_CALIBRATION §3.1） */
type Outcome = 'airdropped' | 'not_airdropped' | 'dumped';

/** 后端 POST /feedback/batch 的单请求条数上限。
 *  必须与后端保持一致：勾选超过该数量时分批发送，否则整个请求会被 422 拒绝。 */
const BATCH_LIMIT = 50;

const OUTCOMES: { key: Outcome; label: string; hint: string }[] = [
  { key: 'airdropped', label: '空投了', hint: '确认收到空投' },
  { key: 'not_airdropped', label: '没空投', hint: '已明确无空投或资格未达' },
  { key: 'dumped', label: '归零/跑路', hint: '代币归零或项目停摆' },
];

export default function ReviewPage() {
  const [picked, setPicked] = useState<Record<string, Outcome>>({});
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState<{ message: string; type: 'success' | 'error' | 'info' } | null>(null);

  // 用 ref 持有定时器并在卸载时清理：否则离开页面后定时器仍会 setState，
  // 触发 unmounted 组件更新告警（工作台页同样处理）。
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const showToast = (message: string, type: 'success' | 'error' | 'info' = 'info') => {
    if (toastTimer.current) clearTimeout(toastTimer.current);
    setToast({ message, type });
    toastTimer.current = setTimeout(() => setToast(null), 3600);
  };
  useEffect(() => () => {
    if (toastTimer.current) clearTimeout(toastTimer.current);
  }, []);

  const loader = useCallback(async (signal: AbortSignal) => {
    const [pending, calibration] = await Promise.all([
      apiFetch<PendingData>('/feedback/pending-review?limit=50', { signal }),
      apiFetch<CalibrationStatus>('/calibration/status', { signal }).catch(() => null),
    ]);
    return { pending, calibration };
  }, []);

  const { data, error, loading, reload } = useAsyncData(loader, []);
  const items = data?.pending?.items ?? [];
  const cal = data?.calibration ?? null;

  const gate = cal?.min_samples_gate ?? 200;
  const current = cal?.total_feedback ?? 0;
  const needed = cal?.samples_needed ?? Math.max(0, gate - current);
  const pct = gate > 0 ? Math.min(100, Math.round((current / gate) * 100)) : 0;

  const pickedCount = Object.keys(picked).length;

  const submitAll = async () => {
    if (pickedCount === 0) return;
    setSaving(true);
    try {
      const all = Object.entries(picked).map(([project_id, outcome]) => ({
        project_id,
        signal: 'correct_outcome' as const,
        outcome,
      }));
      // 分批发送：后端单请求上限 BATCH_LIMIT 条。
      // 记录已成功的批次——中途失败时必须把它们从 picked 里移除，
      // 否则用户重新提交会把成功过的项目重复写一遍。
      const sent: string[] = [];
      try {
        for (let i = 0; i < all.length; i += BATCH_LIMIT) {
          const chunk = all.slice(i, i + BATCH_LIMIT);
          await apiFetch('/feedback/batch', {
            method: 'POST',
            body: JSON.stringify({ items: chunk }),
          });
          sent.push(...chunk.map((c) => c.project_id));
        }
      } catch (err) {
        if (sent.length > 0) {
          setPicked((prev) => {
            const next = { ...prev };
            sent.forEach((id) => delete next[id]);
            return next;
          });
        }
        throw err;
      }
      showToast(`已提交 ${pickedCount} 条结果标记`, 'success');
      setPicked({});
      reload();
    } catch (e: unknown) {
      showToast(e instanceof Error ? e.message : '提交失败', 'error');
      reload(); // 失败后刷新，让列表反映真正已写入的部分
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      {toast && <Toast message={toast.message} type={toast.type} />}

      <TopBar title="结果复盘" subtitle="标记项目的实际结果，为评分权重校准积累样本">
        <button type="button" onClick={() => reload()} className="btn-secondary" disabled={loading || saving}>
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
          刷新
        </button>
        <button type="button" onClick={submitAll} className="btn-primary" disabled={pickedCount === 0 || saving}>
          {saving ? '提交中…' : `提交 ${pickedCount || ''} 条`}
        </button>
      </TopBar>

      <div className="app-content space-y-4 animate-fade-in">
        {/* 校准进度 */}
        <div className="dash-card p-5">
          <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
            <h2 className="text-sm font-semibold text-ink">权重校准进度</h2>
            <span className="text-xs text-ink-muted">
              权重版本 {cal?.weight_version ?? '—'} · 门禁 {gate} 条
            </span>
          </div>
          <div className="cal-bar" role="progressbar" aria-valuenow={current} aria-valuemin={0} aria-valuemax={gate} aria-label="权重校准样本进度">
            <div className="cal-bar-fill" style={{ width: `${pct}%` }} />
          </div>
          <p className="mt-2 text-xs text-ink-muted">
            已有 <strong className="text-ink">{current}</strong> 条样本
            {cal?.strong_samples != null ? `（强监督 ${cal.strong_samples} 条）` : ''}
            {cal?.calibration_ready
              ? ' · 已达门禁，可以运行权重校准'
              : ` · 还需 ${needed} 条才能启动校准`}
          </p>
          <p className="mt-1 text-[11px] leading-relaxed text-ink-faint">
            校准需要真实结果作监督信号。标得越多，评分决策引擎的权重越贴近你的实际收益。
            门禁阈值由 WEIGHT_CALIBRATION 规定，本页不修改它。
          </p>
        </div>

        {error && (
          <div className="dash-card flex flex-wrap items-center justify-between gap-3 border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300">
            <span>加载失败：{error}</span>
            <button type="button" className="btn-secondary !py-1" onClick={() => reload()}>
              重试
            </button>
          </div>
        )}

        {/* 待标记列表 */}
        <div className="dash-card p-5">
          <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
            <h2 className="text-sm font-semibold text-ink">待标记项目</h2>
            <span className="text-xs text-ink-muted">
              {data?.pending
                ? `共 ${data.pending.total_pending} 个待标记 · 已标记 ${data.pending.already_marked} 个`
                : ''}
            </span>
          </div>

          {loading && !data && (
            <div className="space-y-2">
              <div className="skeleton h-12 w-full" />
              <div className="skeleton h-12 w-full" />
              <div className="skeleton h-12 w-full" />
            </div>
          )}

          {!loading && !error && items.length === 0 && (
            <div className="rounded-lg border border-dashed border-line px-3 py-8 text-center text-sm text-ink-muted">
              没有待标记的项目。先在
              <Link href="/" className="mx-1 underline">
                工作台
              </Link>
              跑一次采集评分，或去参与几个项目。
            </div>
          )}

          <ul className="space-y-2">
            {items.map((item) => {
              const chosen = picked[item.project_id];
              return (
                <li key={item.project_id} className="rv-row" data-marked={chosen ? 'true' : 'false'}>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <Link href={`/project/${item.project_id}`} className="aq-project">
                        {item.name ?? item.project_id}
                      </Link>
                      {item.label && <LabelBadge label={item.label} />}
                      {typeof item.score === 'number' && <span className="aq-chip">{item.score} 分</span>}
                      {item.stage && <span className="aq-chip">{stageZh(item.stage)}</span>}
                      {item.has_interaction && <span className="aq-chip aq-chip-req">你有交互记录</span>}
                    </div>
                    <p className="mt-0.5 text-xs text-ink-faint">
                      {item.sector ?? '未分类'}
                      {item.updated_at ? ` · 更新于 ${relativeTime(item.updated_at)}` : ''}
                    </p>
                  </div>
                  <div className="rv-btns">
                    {OUTCOMES.map((o) => (
                      <button
                        key={o.key}
                        type="button"
                        className="rv-btn"
                        data-active={chosen === o.key ? 'true' : 'false'}
                        aria-pressed={chosen === o.key}
                        aria-label={`${item.name ?? item.project_id}：${o.label}（${o.hint}）`}
                        title={o.hint}
                        disabled={saving}
                        onClick={() =>
                          setPicked((prev) => {
                            // 再点一次取消选择
                            if (prev[item.project_id] === o.key) {
                              const next = { ...prev };
                              delete next[item.project_id];
                              return next;
                            }
                            return { ...prev, [item.project_id]: o.key };
                          })
                        }
                      >
                        {o.label}
                      </button>
                    ))}
                  </div>
                </li>
              );
            })}
          </ul>

          {items.length > 0 && (
            <p className="mt-3 text-[11px] leading-relaxed text-ink-muted">
              选好后点右上角「提交」写入。每 {BATCH_LIMIT} 条为一个批次、批次内保证全部成功或全部失败；
              勾选超过 {BATCH_LIMIT} 条会分多批发送，若中途失败请刷新后核对已提交的部分。
            </p>
          )}
        </div>
      </div>
    </>
  );
}
