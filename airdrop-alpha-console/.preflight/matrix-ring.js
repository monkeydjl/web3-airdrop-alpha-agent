// 把校准矩阵行命中率从纯数字换成环形小图（SVG donut）
const fs = require('fs');
const path = require('path');
const pagesDir = 'd:/Github/Web3 Airdrop Alpha Agent System/airdrop-alpha-console/pages';
const targets = ['portfolio', 'portfolio-dark', 'portfolio-btt', 'portfolio-dark-btt'];

// 每行：标签徽章类、命中率、环形颜色 token、旧数字字符串（用于替换）
const rows = [
  { badge: 'pf-badge-farm', label: 'FARM', rate: 0.62, color: 'var(--label-farm)', old: '<span class="pf-rate-num">62%</span>' },
  { badge: 'pf-badge-watch', label: 'WATCH', rate: 0.18, color: 'var(--label-watch)', old: '<span class="pf-rate-num">18%</span>' },
  { badge: 'pf-badge-ignore', label: 'IGNORE', rate: 0.08, color: 'var(--label-ignore)', old: '<span class="pf-rate-num">8%</span>' },
];

const R = 18;         // 半径
const C = +(2 * Math.PI * R).toFixed(2); // 周长

function ring(rate, color, label) {
  const filled = +(C * rate).toFixed(2);
  const gap = +(C - filled).toFixed(2);
  const pct = Math.round(rate * 100);
  return `<span class="pf-rate-ring" role="img" aria-label="${label} 命中率 ${pct}%">
                      <svg width="44" height="44" viewBox="0 0 44 44" aria-hidden="true">
                        <circle cx="22" cy="22" r="${R}" fill="none" style="stroke:var(--muted)" stroke-width="5"/>
                        <circle cx="22" cy="22" r="${R}" fill="none" style="stroke:${color}" stroke-width="5" stroke-linecap="round" stroke-dasharray="${filled} ${gap}" transform="rotate(-90 22 22)"/>
                        <text x="22" y="22" text-anchor="middle" dominant-baseline="central" class="pf-rate-ring-text">${pct}%</text>
                      </svg>
                    </span>`;
}

// 环形图相关 CSS（追加到矩阵样式块末尾）
const ringCss = `
  /* 命中率环形小图 */
  .pf-rate { display: inline-flex; align-items: center; gap: 8px; margin-top: 6px; }
  .pf-rate-ring { display: inline-flex; align-items: center; justify-content: center; flex-shrink: 0; }
  .pf-rate-ring svg { display: block; }
  .pf-rate-ring-text {
    font-family: var(--font-mono);
    font-variant-numeric: tabular-nums;
    font-size: 10px;
    font-weight: 700;
    fill: var(--foreground);
  }
  .pf-rate-note { font-size: 11px; color: var(--muted-foreground); }`;

for (const slug of targets) {
  const f = path.join(pagesDir, slug + '.html');
  if (!fs.existsSync(f)) { console.log('MISS ' + slug); continue; }
  let html = fs.readFileSync(f, 'utf8');

  // 1) 替换每个 <th scope="row"> 里的徽章+命中率结构
  for (const r of rows) {
    const oldRow = `<span class="pf-badge ${r.badge}">${r.label}</span>
                    <span class="pf-rate"><span class="pf-rate-num">${Math.round(r.rate * 100)}%</span><span class="pf-rate-note">命中率</span></span>`;
    const newRow = `<span class="pf-badge ${r.badge}">${r.label}</span>
                    ${ring(r.rate, r.color, r.label)}`;
    if (!html.includes(oldRow)) { console.log(`ROW MISS ${slug} ${r.label}`); continue; }
    html = html.replace(oldRow, newRow);
  }

  // 2) 替换 .pf-rate 样式块为环形图版本（找到 .pf-rate { 到 .pf-rate-note 的 }）
  const rateStart = html.indexOf('  .pf-rate {');
  const noteEnd = html.indexOf('}', html.indexOf('.pf-rate-note', rateStart));
  if (rateStart !== -1 && noteEnd !== -1) {
    html = html.slice(0, rateStart) + ringCss.trimStart() + '\n' + html.slice(noteEnd + 1);
  } else {
    // 若找不到（比如 btt 页结构不同），在 </style> 前兜底追加
    html = html.replace('</style>', ringCss + '\n</style>');
  }

  fs.writeFileSync(f, html, 'utf8');
  console.log('OK ' + slug);
}
console.log('done');
