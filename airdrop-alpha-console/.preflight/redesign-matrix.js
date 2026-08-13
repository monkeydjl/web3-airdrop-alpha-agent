// 重设计 portfolio 校准矩阵卡片：大数字 + 底部强度条 + 行命中率徽章
const fs = require('fs');
const path = require('path');
const pagesDir = 'd:/Github/Web3 Airdrop Alpha Agent System/airdrop-alpha-console/pages';
const targets = ['portfolio', 'portfolio-dark', 'portfolio-btt', 'portfolio-dark-btt'];

// 每行数据：label, badgeClass, cells(数值/强度), hitRate, hitRateNote
const rows = [
  { label: 'FARM', badge: 'pf-badge-farm', cells: [[8,'s3'],[2,'s1'],[3,'s1'],[0,'s0'],[10,'s3']], rate: '62%', note: '命中率' },
  { label: 'WATCH', badge: 'pf-badge-watch', cells: [[2,'s1'],[6,'s2'],[2,'s1'],[1,'s1'],[7,'s2']], rate: '18%', note: '命中率' },
  { label: 'IGNORE', badge: 'pf-badge-ignore', cells: [[0,'s0'],[9,'s3'],[0,'s0'],[1,'s1'],[2,'s1']], rate: '8%', note: '命中率' },
];

const cell = (v, s) => {
  const numCls = s === 's0' ? 'pf-cell-num is-zero' : 'pf-cell-num';
  return `<td class="pf-cell" data-strength="${s}"><span class="${numCls}">${v}</span><span class="pf-cell-bar" aria-hidden="true"></span></td>`;
};

const rowHtml = rows.map(r => {
  const tds = r.cells.map(([v, s]) => cell(v, s)).join('\n                  ');
  return `                <tr>
                  <th scope="row">
                    <span class="pf-badge ${r.badge}">${r.label}</span>
                    <span class="pf-rate"><span class="pf-rate-num">${r.rate}</span><span class="pf-rate-note">${r.note}</span></span>
                  </th>
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
${rowHtml}
              </tbody>
            </table>`;

const newCss = `  /* ---------- 校准矩阵（重设计：大数字 + 底部强度条 + 行命中率） ---------- */
  .pf-matrix {
    width: calc(100% + 8px);
    margin: -4px;
    border-collapse: separate;
    border-spacing: 4px;
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
    width: 168px;
    text-align: left;
    font-weight: 400;
    font-size: 11.5px;
  }
  .pf-matrix th[scope="row"] { text-align: left; padding: 0 6px; vertical-align: middle; }
  .pf-col-mono {
    font-family: var(--font-mono);
    font-variant-numeric: tabular-nums;
    font-size: 11.5px;
  }
  .pf-rate { display: inline-flex; align-items: baseline; gap: 5px; margin-top: 4px; }
  .pf-rate-num {
    font-family: var(--font-mono);
    font-variant-numeric: tabular-nums;
    font-size: 15px;
    font-weight: 700;
    color: var(--foreground);
    line-height: 1;
  }
  .pf-rate-note { font-size: 11px; color: var(--muted-foreground); }
  /* 单元格：边框为主，强度条在底部，避免浅色块+白字的对比度问题 */
  .pf-matrix td.pf-cell {
    height: 64px;
    padding: 0 0 10px;
    text-align: center;
    vertical-align: middle;
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    position: relative;
  }
  .pf-cell-num {
    display: block;
    font-family: var(--font-mono);
    font-variant-numeric: tabular-nums;
    font-size: 26px;
    font-weight: 700;
    line-height: 1.1;
    color: var(--foreground);
  }
  .pf-cell-num.is-zero { color: var(--muted-foreground); font-weight: 500; }
  .pf-cell-bar {
    position: absolute;
    left: 10px;
    right: 10px;
    bottom: 8px;
    height: 4px;
    border-radius: var(--radius-full);
    background: transparent;
  }
  .pf-cell[data-strength="s1"] .pf-cell-bar { background: var(--alpha-200); }
  .pf-cell[data-strength="s2"] .pf-cell-bar { background: var(--alpha-400); }
  .pf-cell[data-strength="s3"] .pf-cell-bar { background: var(--primary); }
  .pf-cell[data-strength="s3"] { border-color: var(--alpha-300); }
  .pf-cell[data-strength="s2"] { border-color: var(--alpha-200); }
  .pf-matrix-foot {
    margin: 14px 0 0;
    text-align: right;
    font-size: 12px;
    line-height: 1.5;
    color: var(--muted-foreground);
  }
  .pf-matrix-foot strong { color: var(--foreground); font-weight: 600; }`;

let replaced = 0;
for (const slug of targets) {
  const f = path.join(pagesDir, slug + '.html');
  if (!fs.existsSync(f)) { console.log('MISS ' + slug); continue; }
  let html = fs.readFileSync(f, 'utf8');

  // 1) 替换 <table class="pf-matrix">...</table>
  const tStart = html.indexOf('<table class="pf-matrix"');
  const tEnd = html.indexOf('</table>', tStart);
  if (tStart === -1 || tEnd === -1) { console.log('NO TABLE ' + slug); continue; }
  html = html.slice(0, tStart) + newMatrix + html.slice(tEnd + '</table>'.length);

  // 2) 替换旧的矩阵 CSS 块（从校准矩阵注释到 .pf-matrix-foot 结束）
  const cStart = html.indexOf('  /* ---------- 校准矩阵');
  const footEnd = html.indexOf('}', html.indexOf('.pf-matrix-foot', cStart));
  if (cStart === -1 || footEnd === -1) { console.log('NO CSS ' + slug); continue; }
  // 找到 .pf-matrix-foot 规则块的结尾（含 color 行的 }）
  const blockEnd = html.indexOf('\n', footEnd) + 1;
  html = html.slice(0, cStart) + newCss + '\n' + html.slice(blockEnd);

  // 3) 强化 footer 命中率数字
  html = html.replace(
    /FARM 命中率 62% · WATCH 18% · IGNORE 8% — 标签区分度健康/,
    '<strong>FARM 命中率 62%</strong> · WATCH 18% · IGNORE 8% — 标签区分度健康'
  );

  fs.writeFileSync(f, html, 'utf8');
  console.log('OK ' + slug);
  replaced++;
}
console.log('done, replaced=' + replaced);
