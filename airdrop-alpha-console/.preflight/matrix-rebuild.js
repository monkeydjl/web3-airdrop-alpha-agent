// 重建校准矩阵 section：自包含、条形清晰（进行中用更明显的色，分段带间隔）
const fs = require('fs');
const path = require('path');
const pagesDir = 'd:/Github/Web3 Airdrop Alpha Agent System/airdrop-alpha-console/pages';
const targets = ['portfolio', 'portfolio-dark', 'portfolio-btt', 'portfolio-dark-btt'];

const rows = [
  { badge: 'pf-badge-farm', label: 'FARM', color: 'var(--label-farm)', rate: 62, segs: [[34.8,'var(--state-success)','空投成功 8'],[8.7,'var(--label-ignore)','未空投 2'],[13,'var(--state-info)','上涨 3'],[43.5,'var(--alpha-300)','进行中 10']] },
  { badge: 'pf-badge-watch', label: 'WATCH', color: 'var(--label-watch)', rate: 18, segs: [[11.1,'var(--state-success)','空投成功 2'],[33.3,'var(--label-ignore)','未空投 6'],[11.1,'var(--state-info)','上涨 2'],[5.6,'var(--state-error)','下跌 1'],[38.9,'var(--alpha-300)','进行中 7']] },
  { badge: 'pf-badge-ignore', label: 'IGNORE', color: 'var(--label-ignore)', rate: 8, segs: [[75,'var(--label-ignore)','未空投 9'],[8.3,'var(--state-error)','下跌 1'],[16.7,'var(--alpha-300)','进行中 2']] },
];

const R = 17, CIRC = +(2 * Math.PI * R).toFixed(1);
const ring = (rate, color, label) => {
  const f = +(CIRC * rate / 100).toFixed(1), g = +(CIRC - f).toFixed(1);
  return `<span class="pf-mx-ring" role="img" aria-label="${label} 命中率 ${rate}%">
                  <svg width="46" height="46" viewBox="0 0 46 46" aria-hidden="true">
                    <circle cx="23" cy="23" r="${R}" fill="none" style="stroke:var(--border)" stroke-width="4"/>
                    <circle cx="23" cy="23" r="${R}" fill="none" style="stroke:${color}" stroke-width="4" stroke-linecap="round" stroke-dasharray="${f} ${g}" transform="rotate(-90 23 23)"/>
                    <text x="23" y="23" text-anchor="middle" dominant-baseline="central" class="pf-mx-ring-text">${rate}%</text>
                  </svg>
                </span>`;
};

const rowHtml = rows.map(r => {
  const bars = r.segs.map(([w, color, title]) =>
    `<span class="pf-mx-seg" style="width:${w}%;background:${color}" title="${title}"></span>`
  ).join('');
  const total = r.segs.reduce((a, s) => a + parseInt(s[2].match(/\d+$/)[0]), 0);
  return `              <div class="pf-mx-row">
                <div class="pf-mx-head">
                  <span class="pf-badge ${r.badge}">${r.label}</span>
                  <span class="pf-mx-total">${total} 项</span>
                </div>
                <div class="pf-mx-track" role="img" aria-label="${r.label} 各结果分布">${bars}</div>
                <div class="pf-mx-side">
                  ${ring(r.rate, r.color, r.label)}
                  <span class="pf-mx-rate-note">命中率</span>
                </div>
              </div>`;
}).join('\n');

const legend = [['空投成功','var(--state-success)'],['未空投','var(--label-ignore)'],['上涨','var(--state-info)'],['下跌','var(--state-error)'],['进行中','var(--alpha-300)']]
  .map(([t, c]) => `<span class="pf-mx-legend-item"><span class="pf-mx-dot" style="background:${c}"></span>${t}</span>`).join('\n                ');

const newSection = `<section class="pf-card" aria-label="标签 × 结果校准矩阵">
          <div class="pf-card-head">
            <h2 class="pf-card-title">标签 × 结果校准矩阵</h2>
            <div class="pf-mx-legend pf-mx-legend--head">
                ${legend}
            </div>
            <p class="pf-card-caption">score-v1.4 标签在实际结果上的命中率 · 权重校准核心输入</p>
          </div>
          <div class="pf-card-body">
            <div class="pf-mx">
${rowHtml}
            </div>
            <p class="pf-matrix-foot"><strong>FARM 命中率 62%</strong> · WATCH 18% · IGNORE 8% — 标签区分度健康</p>
          </div>
        </section>`;

const newCss = `  /* ---------- 校准矩阵（标签行 + 堆叠条形 + 命中率环） ---------- */
  .pf-mx { display: flex; flex-direction: column; gap: 12px; }
  .pf-mx-row {
    display: grid;
    grid-template-columns: 120px minmax(0, 1fr) 96px;
    align-items: center;
    gap: 16px;
    padding: 12px 14px;
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    background: var(--card);
  }
  .pf-mx-head { display: flex; flex-direction: column; gap: 6px; align-items: flex-start; }
  .pf-mx-total { font-family: var(--font-mono); font-variant-numeric: tabular-nums; font-size: 12px; color: var(--muted-foreground); }
  .pf-mx-track {
    display: flex;
    height: 34px;
    border-radius: var(--radius-sm);
    overflow: hidden;
    background: var(--muted);
  }
  .pf-mx-seg { display: block; height: 100%; transition: opacity var(--duration-fast) var(--ease-default); }
  .pf-mx-row:hover .pf-mx-seg { opacity: 0.88; }
  .pf-mx-side { display: flex; flex-direction: column; align-items: center; gap: 3px; }
  .pf-mx-ring { display: inline-flex; }
  .pf-mx-ring svg { display: block; }
  .pf-mx-ring-text { font-family: var(--font-mono); font-variant-numeric: tabular-nums; font-size: 11px; font-weight: 700; fill: var(--foreground); }
  .pf-mx-rate-note { font-size: 11px; color: var(--muted-foreground); }
  .pf-mx-legend { display: flex; flex-wrap: wrap; gap: 6px 16px; }
  .pf-mx-legend--head { margin-left: auto; }
  .pf-mx-legend-item { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; color: var(--muted-foreground); }
  .pf-mx-dot { width: 10px; height: 10px; border-radius: 3px; flex-shrink: 0; }
  .pf-matrix-foot { margin: 14px 0 0; text-align: right; font-size: 12px; line-height: 1.5; color: var(--muted-foreground); }
  .pf-matrix-foot strong { color: var(--foreground); font-weight: 600; }
  @media (max-width: 720px) { .pf-mx-row { grid-template-columns: 1fr; } .pf-mx-side { flex-direction: row; } }`;

for (const slug of targets) {
  const f = path.join(pagesDir, slug + '.html');
  if (!fs.existsSync(f)) { console.log('MISS ' + slug); continue; }
  let html = fs.readFileSync(f, 'utf8');

  // 1) 替换整个校准矩阵 <section>（从注释到 </section>）
  const sStart = html.indexOf('<!-- 2. 标签 × 结果校准矩阵 -->');
  const secStart = html.indexOf('<section class="pf-card" aria-label="标签 × 结果校准矩阵">', sStart);
  const secEnd = html.indexOf('</section>', secStart);
  if (secStart === -1 || secEnd === -1) { console.log('NO SECTION ' + slug); continue; }
  html = html.slice(0, secStart) + newSection + html.slice(secEnd + '</section>'.length);

  // 2) 替换矩阵 CSS 块（校准矩阵注释 → 双栏分布注释之前）
  const cStart = html.indexOf('  /* ---------- 校准矩阵');
  const nextComment = html.indexOf('  /* ---------- 双栏分布', cStart);
  if (cStart === -1 || nextComment === -1) { console.log('NO CSS ' + slug); continue; }
  html = html.slice(0, cStart) + newCss + '\n\n\n' + html.slice(nextComment);

  fs.writeFileSync(f, html, 'utf8');
  console.log('OK ' + slug);
}
console.log('done');
