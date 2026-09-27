'use client';

/**
 * 模拟数据角标（Simulated Data Badge）。
 *
 * 契约：后端扩展端点（见 docs/EXPANSION_AUDIT_REPORT.md）在响应体顶层返回
 * `data_quality: { quality: "simulated", note: "..." }` 时，前端所有消费该
 * 数据的面板/模态框必须渲染此角标，与 seed 项目的「种子数据」标记同一原则：
 * **用户可分辨真实计算与占位演示**。
 *
 * 用法：
 *   <SimulatedDataBadge dataQuality={res.data_quality} />
 * 或在无响应元数据、但已知该面板数据为演示时直接传 note：
 *   <SimulatedDataBadge note="本地演示数据" />
 */

export interface DataQualityMeta {
  quality?: string;
  note?: string;
}

export function isSimulated(dq?: DataQualityMeta | null): boolean {
  return dq?.quality === 'simulated';
}

export function SimulatedDataBadge({
  dataQuality,
  note,
  className = '',
}: {
  dataQuality?: DataQualityMeta | null;
  note?: string;
  className?: string;
}) {
  if (!isSimulated(dataQuality) && !note) return null;

  const tip = note || dataQuality?.note || '本数据为演示/启发式生成，非实时数据。';

  return (
    <span
      title={tip}
      className={`inline-flex items-center gap-1 rounded-full border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-[10px] font-semibold text-amber-400 ${className}`}
    >
      <span aria-hidden>⚠️</span>
      <span>模拟数据</span>
    </span>
  );
}
