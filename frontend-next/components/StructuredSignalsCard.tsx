import { structuredSignalRows } from '@/lib/format';

/**
 * 结构化 Anti-PUA 信号卡片（项目详情页 ·「多源共识与可核验信号」区内）。
 *
 * 展示 `meta.signals` 里登记在 SIGNAL_KEYS 的三个结构化键：
 * `points_season_count` / `tge_clarity` / `is_perp` —— opportunity-v2.0
 * Shadow 旁路 fatigue/friction 的直接输入，取代旧的 description 文本启发式。
 *
 * 「未观测」与「未公布」刻意分开：后者是后端的观测结论（默认档），
 * 前者表示这个键在 meta.signals 里没有类型合法的值。判断逻辑集中在
 * `lib/format.ts::structuredSignalRows`，本组件只负责布局。
 */
export function StructuredSignalsCard({ signals }: { signals?: Record<string, unknown> | null }) {
  const rows = structuredSignalRows(signals);
  const observedCount = rows.filter((r) => r.observed).length;

  const toneClass: Record<string, string> = {
    pos: 'text-farm dark:text-farm',
    watch: 'text-watch dark:text-watch',
    muted: 'text-ink-muted',
  };

  return (
    <div className="mb-5 rounded-lg border border-line bg-surface-1 p-4 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line/60 pb-3">
        <h3 className="m-0 text-xs font-semibold text-ink">结构化 Anti-PUA 信号</h3>
        <span className="font-mono text-[11px] text-ink-faint">
          {observedCount ? `已观测 ${observedCount}/${rows.length}` : '三项均未观测'}
        </span>
      </div>

      <div className="mt-3 grid gap-x-6 sm:grid-cols-3">
        {rows.map((row) => (
          <div key={row.key} className="border-b border-line py-2 text-[13px] last:border-b-0 sm:border-b-0">
            <div className="flex items-baseline justify-between gap-3">
              <span className="text-ink-muted" title={row.hint}>
                {row.label}
              </span>
              <span
                className={`font-mono text-[11px] font-semibold tracking-wide ${toneClass[row.tone] ?? 'text-ink-muted'}`}
                title={row.hint}
              >
                {row.display}
              </span>
            </div>
          </div>
        ))}
      </div>

      <p className="mb-0 mt-2.5 font-mono text-[10px] leading-relaxed tracking-wide text-ink-faint">
        数据来源：采集侧公开文案（赛道/描述）的结构化推断，登记于 meta.signals，由 opportunity-v2.0 旁路消费。
        「未观测」≠ 观测为否；详情悬浮可见各信号口径。
      </p>
    </div>
  );
}
