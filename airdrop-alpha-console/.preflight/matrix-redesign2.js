// 重设计校准矩阵 v2：行首 48px 环形徽章一体，单元格只留干净大数字
const fs = require('fs');
const path = require('path');
const pagesDir = 'd:/Github/Web3 Airdrop Alpha Agent System/airdrop-alpha-console/pages';
const targets = ['portfolio', 'portfolio-dark', 'portfolio-btt', 'portfolio-dark-btt'];

const rows = [
  { badge: 'pf-badge-farm', label: 'FARM', rate: 0.62, color: 'var(--label-farm)', cells: [[8,'s3'],[2,'s1'],[3,'s1'],[0,'s0'],[10,'s3']] },
  { badge: 'pf-badge-watch', label: 'WATCH', rate: 0.18, color: 'var(--label-watch)', cells: [[2,'s1'],[6,'s2'],[2,'s1'],[1,'s1'],[7,'s2']] },
  { badge: 'pf-badge-ignore', label: 'IGNORE', rate: 0.08, color: 'var(--label-ignore)', cells: [[0,'s0'],[9,'s3'],[0,'s0'],[1,'s1'],[2,'s1']] },
];

const R = 21;
const C = +(2 * Math.PI * R).toFixed(2);

function ringCell(rate, color, label, badge) {
  const filled = +(C * rate).toFixed(2);
  const gap = +(C - filled).toFixed(2);
  const pct = Math.round(rate * 100);
  return `<th scope="row">
                    <div class="pf-lead">
                      <span class="pf-ring" role="img" aria-label="${label} 命中率 ${pct}%">
                        <svg width="48" height="48" viewBox="0 0 48 48" aria-hidden="true">
                          <circle cx="24" cy="24" r="${R}" fill="none" style="stroke:var(--muted)" stroke-width="5"/>
                          <circle cx="24" cy="24" r="${R}" fill="none" style="stroke:${color}" stroke-width="5" stroke-linecap="round" stroke-dasharray="${filled} ${gap}" transform="rotate(-90 24 24)"/>
                          <text x="24" y="24" text-anchor="middle" dominant-baseline="central" class="pf-ring-text">${pct}%</text>
                        </svg>
                      </span>
                      <span class="pf-lead-meta">
                        <span class="pf-badge ${badge}">${label}</span>
                        <span class="pf-lead-note">命中率</span>
                      </span>
                    </div>
                  </th>`;
}

const cell = (v, s) => {
  const numCls = s === 's0' ? 'pf-cell-num is-zero' : 'pf-cell-num';
  return `<td class="pf-cell" data-strength="${s}"><span class="${numCls}">${v}</span></td>`;
};

const bodyRows = rows.map(r => {
  const tds = r.cells.map(([v, s]) => cell(v, s)).join('\n                  ');
  return `                <tr>
                  ${ringCell(r.rate, r.color, r.label, r.badge)}
                  ${tds}
                </tr>`;
}).join('\n');

const newMatrix = `<table class="pf-matrix" aria-label="标签与结果计数矩阵">
              <thead>
                <tr>
                  <th class="pf-matrix-corner" scope="col">标签 × 结果</th>
                  <th scope="col"><span class="pf-col-mono">airdropped</span></th>
                  <th scope="col"><span class="pf-col-mono">not_airdropped</span></th>
                  <th scope="col"><span class="pf-col-mono">pumped</span></th>
                  <th scope="col"><span class="pf-col-mono">dumped</span></th>
                  <th scope="col">进行中 <span class="pf-col-mono">pending</span></th>
                </tr>
              </thead>
              <tbody>
${bodyRows}
              </tbody>
            </table>`;

const newCss = `  /* ---------- 校准矩阵（v3：行首环形徽章一体 + 干净大数字单元格） ---------- */
  .pf-matrix {
    width: calc(100% + 8px);
    margin: -4px;
    border-collapse: separate;
    border-spacing: 6px;
    table-layout: fixed;
  }
  .pf-matrix th {
    font-size: 12px;
    font-weight: 500;
    color: var(--muted-foreground);
    text-align: center;
    padding: 6px 8px;
    line-height: 1.4;
  }
  .pf-matrix .pf-matrix-corner {
    width: 176px;
    text-align: left;
    font-weight: 400;
    font-size: 11.5px;
    vertical-align: middle;
  }
  .pf-matrix th[scope="row"] { text-align: left; padding: 0 6px; vertical-align: middle; }
  .pf-col-mono {
    font-family: var(--font-mono);
    font-variant-numeric: tabular-nums;
    font-size: 11.5px;
  }
  /* 行首：环形 + 徽章 + 文字 横排一体 */
  .pf-lead { display: flex; align-items: center; gap: 12px; }
  .pf-ring { display: inline-flex; flex-shrink: 0; }
  .pf-ring svg { display: block; }
  .pf-ring-text {
    font-family: var(--font-mono);
    font-variant-numeric: tabular-nums;
    font-size: 11px;
    font-weight: 700;
    fill: var(--foreground);
  }
  .pf-lead-meta { display: flex; flex-direction: column; gap: 5px; align-items: flex-start; }
  .pf-lead-note { font-size: 11px; color: var(--muted-foreground); }
  /* 单元格：只留大数字，强度用边框色深浅表达，不要底部色条 */
  .pf-matrix td.pf-cell {
    height: 68px;
    text-align: center;
    vertical-align: middle;
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
  }
  .pf-cell-num {
    font-family: var(--font-mono);
    font-variant-numeric: tabular-nums;
    font-size: 30px;
    font-weight: 700;
    line-height: 1;
    color: var(--foreground);
  }
  .pf-cell-num.is-zero { color: var(--muted-foreground); font-weight: 500; }
  .pf-cell[data-strength="s3"] { border-color: var(--alpha-300); background: var(--alpha-50); }
  .pf-cell[data-strength="s2"] { border-color: var(--alpha-200); }
  .pf-cell[data-strength="s3"] .pf-cell-num { color: var(--primary); }
  .pf-matrix-foot {
    margin: 14px 0 0;
    text-align: right;
    font-size: 12px;
    line-height: 1.5;
    color: var(--muted-foreground);
  }
  .pf-matrix-foot strong { color: var(--foreground); font-weight: 600; }`;

for (const slug of targets) {
  const f = path.join(pagesDir, slug + '.html');
  if (!fs.existsSync(f)) { console.log('MISS ' + slug); continue; }
  let html = fs.readFileSync(f, 'utf8');

  // 替换整个 <tbody>…</tbody>
  const bStart = html.indexOf('<tbody>');
  const bEnd = html.indexOf('</tbody>');
  if (bStart === -1 || bEnd === -1) { console.log('NO TBODY ' + slug); continue; }
  html = html.slice(0, bStart) + '<tbody>\n' + bodyRows + '\n              </tbody>' + html.slice(bEnd + '</tbody>'.length);

  // 替换矩阵 CSS 块（从校准矩阵注释到 .pf-matrix-foot strong 结束）
  const cStart = html.indexOf('  /* ---------- 校准矩阵');
  const footStrong = html.indexOf('.pf-matrix-foot strong', cStart);
  if (cStart === -1 || footStrong === -1) { console.log('NO CSS ' + slug); continue; }
  const blockEnd = html.indexOf('}', footStrong) + 1;
  html = html.slice(0, cStart) + newCss + '\n' + html.slice(blockEnd);

  fs.writeFileSync(f, html, 'utf8');
  console.log('OK ' + slug);
}
console.log('done');
