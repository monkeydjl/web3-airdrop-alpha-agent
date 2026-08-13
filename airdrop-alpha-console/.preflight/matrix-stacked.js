// 校准矩阵 v4：标签行 + 横向堆叠条形（按结果分段） + 行末命中率环
// 设计语言与"洞察/工作台"页一致：信息层级用图表与列表说话，不做大数字堆砌
const fs = require('fs');
const path = require('path');
const pagesDir = 'd:/Github/Web3 Airdrop Alpha Agent System/airdrop-alpha-console/pages';
const targets = ['portfolio', 'portfolio-dark', 'portfolio-btt', 'portfolio-dark-btt'];

// 结果分段定义：key / 中文 / 颜色 token
const segs = [
  ['airdropped', '空投成功', 'var(--label-farm)'],
  ['not_airdropped', '未空投', 'var(--label-ignore)'],
  ['pumped', '上涨', 'var(--state-info)'],
  ['dumped', '下跌', 'var(--state-error)'],
  ['pending', '进行中', 'var(--muted)'],
];

const rows = [
  { badge: 'pf-badge-farm', label: 'FARM', color: 'var(--label-farm)', rate: 0.62, data: { airdropped: 8, not_airdropped: 2, pumped: 3, dumped: 0, pending: 10 } },
  { badge: 'pf-badge-watch', label: 'WATCH', color: 'var(--label-watch)', rate: 0.18, data: { airdropped: 2, not_airdropped: 6, pumped: 2, dumped: 1, pending: 7 } },
  { badge: 'pf-badge-ignore', label: 'IGNORE', color: 'var(--label-ignore)', rate: 0.08, data: { airdropped: 0, not_airdropped: 9, pumped: 0, dumped: 1, pending: 2 } },
];

const R = 21, C = +(2 * Math.PI * R).toFixed(2);
const ring = (rate, color, label) => {
  const filled = +(C * rate).toFixed(2), gap = +(C - filled).toFixed(2), pct = Math.round(rate * 100);
  return `<span class="pf-mx-ring" role="img" aria-label="${label} 命中率 ${pct}%">
                  <svg width="46" height="46" viewBox="0 0 46 46" aria-hidden="true">
                    <circle cx="23" cy="23" r="${R}" fill="none" style="stroke:var(--muted)" stroke-width="5"/>
                    <circle cx="23" cy="23" r="${R}" fill="none" style="stroke:${color}" stroke-width="5" stroke-linecap="round" stroke-dasharray="${filled} ${gap}" transform="rotate(-90 23 23)"/>
                    <text x="23" y="23" text-anchor="middle" dominant-baseline="central" class="pf-mx-ring-text">${pct}%</text>
                  </svg>
                </span>`;
};

const rowsHtml = rows.map(r => {
  const total = Object.values(r.data).reduce((a, b) => a + b, 0);
  const bars = segs.map(([k, zh, color]) => {
    const v = r.data[k];
    if (!v) return '';
    const w = +((v / total) * 100).toFixed(1);
    return `<span class="pf-mx-seg" style="width:${w}%;background:${color}" title="${zh} ${v}"></span>`;
  }).filter(Boolean).join('\n                    ');
  return `              <div class="pf-mx-row">
                <div class="pf-mx-head">
                  <span class="pf-badge ${r.badge}">${r.label}</span>
                  <span class="pf-mx-total">${total} 项</span>
                </div>
                <div class="pf-mx-track" role="img" aria-label="${r.label} 各结果分布">
${bars}
                </div>
                <div class="pf-mx-side">
                  ${ring(r.rate, r.color, r.label)}
                  <span class="pf-mx-rate-note">命中率</span>
                </div>
              </div>`;
}).join('\n\n');

const legend = segs.map(([k, zh, color]) =>
  `<span class="pf-mx-legend-item"><span class="pf-mx-dot" style="background:${color}"></span>${zh}</span>`
).join('\n                ');

const newBlock = `<div class="pf-mx">
${rowsHtml}

              <div class="pf-mx-legend">
                ${legend}
              </div>
            </div>`;

const newCss = `  /* ---------- 校准矩阵（v4：标签行 + 堆叠条形 + 命中率环） ---------- */
  .pf-mx { display: flex; flex-direction: column; gap: 14px; }
  .pf-mx-row {
    display: grid;
    grid-template-columns: 132px 1fr 92px;
    align-items: center;
    gap: 18px;
    padding: 12px 14px;
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    background: var(--card);
  }
  .pf-mx-head { display: flex; flex-direction: column; gap: 6px; align-items: flex-start; }
  .pf-mx-total {
    font-family: var(--font-mono);
    font-variant-numeric: tabular-nums;
    font-size: 12px;
    color: var(--muted-foreground);
  }
  .pf-mx-track {
    display: flex;
    height: 30px;
    border-radius: var(--radius-sm);
    overflow: hidden;
    background: var(--muted);
  }
  .pf-mx-seg { display: block; height: 100%; transition: opacity var(--duration-fast) var(--ease-default); }
  .pf-mx-row:hover .pf-mx-seg { opacity: 0.85; }
  .pf-mx-side { display: flex; flex-direction: column; align-items: center; gap: 3px; }
  .pf-mx-ring { display: inline-flex; }
  .pf-mx-ring svg { display: block; }
  .pf-mx-ring-text {
    font-family: var(--font-mono);
    font-variant-numeric: tabular-nums;
    font-size: 11px;
    font-weight: 700;
    fill: var(--foreground);
  }
  .pf-mx-rate-note { font-size: 11px; color: var(--muted-foreground); }
  .pf-mx-legend {
    display: flex;
    flex-wrap: wrap;
    gap: 8px 18px;
    padding-top: 2px;
  }
  .pf-mx-legend-item {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-size: 12px;
    color: var(--muted-foreground);
  }
  .pf-mx-dot { width: 10px; height: 10px; border-radius: 3px; flex-shrink: 0; }
  @media (max-width: 720px) {
    .pf-mx-row { grid-template-columns: 1fr; gap: 10px; }
    .pf-mx-side { flex-direction: row; }
  }`;

for (const slug of targets) {
  const f = path.join(pagesDir, slug + '.html');
  if (!fs.existsSync(f)) { console.log('MISS ' + slug); continue; }
  let html = fs.readFileSync(f, 'utf8');

  // 1) 替换 <table class="pf-matrix">…</table> 整块为 .pf-mx
  const tStart = html.indexOf('<table class="pf-matrix"');
  const tEnd = html.indexOf('</table>', tStart);
  if (tStart === -1 || tEnd === -1) { console.log('NO TABLE ' + slug); continue; }
  html = html.slice(0, tStart) + newBlock + html.slice(tEnd + '</table>'.length);

  // 2) 替换矩阵 CSS 块（校准矩阵注释 → .pf-matrix-foot strong 结束）
  const cStart = html.indexOf('  /* ---------- 校准矩阵');
  const footStrong = html.indexOf('.pf-matrix-foot strong', cStart);
  if (cStart === -1 || footStrong === -1) { console.log('NO CSS ' + slug); continue; }
  const blockEnd = html.indexOf('}', footStrong) + 1;
  html = html.slice(0, cStart) + newCss + '\n' + html.slice(blockEnd);

  // 3) footer 结论保留（已有 strong 包裹），无需改
  fs.writeFileSync(f, html, 'utf8');
  console.log('OK ' + slug);
}
console.log('done');
