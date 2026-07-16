'use client';

import {
  ArcElement,
  BarElement,
  CategoryScale,
  Chart as ChartJS,
  Legend,
  LinearScale,
  Tooltip,
} from 'chart.js';
import { Doughnut, Bar } from 'react-chartjs-2';
import type { Label } from '@/lib/types';
import { LABEL_ZH } from '@/lib/format';

ChartJS.register(ArcElement, BarElement, CategoryScale, LinearScale, Tooltip, Legend);

const LABEL_COLORS: Record<Label, string> = {
  FARM: '#10b981',
  WATCH: '#f59e0b',
  IGNORE: '#64748b',
};

export function LabelDoughnut({ counts }: { counts: Record<string, number> }) {
  const keys: Label[] = ['FARM', 'WATCH', 'IGNORE'];
  const labels = keys.map((l) => LABEL_ZH[l]);
  const data = keys.map((l) => counts[l] || 0);
  const total = data.reduce((a, b) => a + b, 0) || 1;

  return (
    <div className="relative mx-auto h-48 w-48">
      <Doughnut
        data={{
          labels,
          datasets: [
            {
              data,
              backgroundColor: keys.map((l) => LABEL_COLORS[l]),
              borderWidth: 0,
              hoverOffset: 6,
            },
          ],
        }}
        options={{
          cutout: '72%',
          plugins: {
            legend: { display: false },
            tooltip: {
              callbacks: {
                label: (ctx) => {
                  const v = Number(ctx.raw || 0);
                  return ` ${ctx.label}: ${v} (${Math.round((v / total) * 100)}%)`;
                },
              },
            },
          },
        }}
      />
      <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-2xl font-bold tabular-nums text-ink">{data.reduce((a, b) => a + b, 0)}</span>
        <span className="text-[10px] tracking-wide text-ink-faint">项目数</span>
      </div>
    </div>
  );
}

export function SectorBars({
  sectors,
}: {
  sectors: { name: string; count: number }[];
}) {
  const top = sectors.slice(0, 8);
  const labels = top.map((s) => s.name);
  const values = top.map((s) => s.count);

  if (!top.length) {
    return <p className="py-8 text-center text-sm text-ink-faint">暂无赛道数据</p>;
  }

  return (
    <div className="h-56">
      <Bar
        data={{
          labels,
          datasets: [
            {
              data: values,
              backgroundColor: 'rgba(99, 102, 241, 0.75)',
              borderRadius: 8,
              barThickness: 14,
            },
          ],
        }}
        options={{
          indexAxis: 'y',
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: { display: false },
          },
          scales: {
            x: {
              grid: { color: 'rgba(148,163,184,0.15)' },
              ticks: { precision: 0, color: '#94a3b8', font: { size: 10 } },
            },
            y: {
              grid: { display: false },
              ticks: { color: '#94a3b8', font: { size: 11 } },
            },
          },
        }}
      />
    </div>
  );
}
