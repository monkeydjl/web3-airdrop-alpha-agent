import type { Project } from './types';

function formatFundingUsd(n?: number | null): string {
  if (n == null || Number.isNaN(n)) return '';
  if (n >= 1e9) return `${(n / 1e9).toFixed(1)}B`;
  if (n >= 1e6) return `${(n / 1e6).toFixed(1)}M`;
  if (n >= 1e3) return `${(n / 1e3).toFixed(1)}K`;
  return String(n);
}

function csvCell(value: unknown): string {
  const s = value == null ? '' : String(value);
  if (/[",\n]/.test(s)) return `"${s.replace(/"/g, '""')}"`;
  return s;
}

export function exportProjectsCsv(projects: Project[]): void {
  const headers = [
    'Name',
    'Sector',
    'Stage',
    'Score',
    'Label',
    'Confidence',
    'Funding Total USD',
    'Funding Tier',
    'Funding Quality',
    'Funding Rounds',
    'URL',
    'Source',
  ];
  const rows = projects.map((p) => {
    const quality = p.funding?.funding_quality;
    return [
      p.name,
      p.sector,
      p.stage,
      p.score,
      p.label,
      p.confidence,
      formatFundingUsd(p.funding?.funding_total_usd),
      p.funding?.funding_tier ?? '',
      quality != null ? `${(quality * 100).toFixed(0)}%` : '',
      p.funding?.funding_rounds ?? '',
      p.url ?? '',
      p.source ?? '',
    ]
      .map(csvCell)
      .join(',');
  });
  const csv = [headers.join(','), ...rows].join('\n');
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `airdrop-projects-${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}
