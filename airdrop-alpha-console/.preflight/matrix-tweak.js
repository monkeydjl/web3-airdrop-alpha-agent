// 校准矩阵微调：条形加粗 / 环改细 / 图例移到标题旁
const fs = require('fs');
const path = require('path');
const pagesDir = 'd:/Github/Web3 Airdrop Alpha Agent System/airdrop-alpha-console/pages';
const targets = ['portfolio', 'portfolio-dark', 'portfolio-btt', 'portfolio-dark-btt'];

for (const slug of targets) {
  const f = path.join(pagesDir, slug + '.html');
  if (!fs.existsSync(f)) { console.log('MISS ' + slug); continue; }
  let html = fs.readFileSync(f, 'utf8');

  // 1) 条形加粗：30px → 40px
  html = html.replace(/\.pf-mx-track \{\s*\n\s*display: flex;\s*\n\s*height: 30px;/, '.pf-mx-track {\n    display: flex;\n    height: 40px;');

  // 2) 环改细：SVG stroke-width 5 → 3.5（轨道+进度两个 circle）
  html = html.replace(/(pf-mx-ring[\s\S]*?stroke-width=")5(")/g, '$13.5$2');
  // 环形 SVG 尺寸 46→44，配合细环更精致
  html = html.replace(/(<svg width=")46(" height=")46(" viewBox="0 0 46 46")/g, '$144$244$3'.replace('44 44','44 44'));

  // 3) 图例移到标题旁：把 .pf-mx-legend 块从矩阵底部挪到卡片标题行
  const legendStart = html.indexOf('<div class="pf-mx-legend">');
  const legendEnd = html.indexOf('</div>', html.indexOf('</span>', legendStart));
  if (legendStart !== -1) {
    // 找到 legend 块完整结尾（最后一个 </div> 后）
    const blockEnd = html.indexOf('</div>', legendStart) ; // first inner close
    // 精确：legend 块结构是 <div class="pf-mx-legend"> 若干 <span>...</span> </div>
    const legendClose = html.indexOf('</div>', html.lastIndexOf('</span>', html.indexOf('</div>\n            </div>', legendStart)));
    // 简化：截取从 legendStart 到 "pf-mx-legend" 块结束（找 "</div>" 紧跟 "</div>" 之前）
    const afterLegend = html.indexOf('\n              </div>\n            </div>', legendStart);
    if (afterLegend !== -1) {
      const legendBlock = html.slice(legendStart, html.indexOf('</div>', legendStart) + 6);
      // 实际 legend 块结尾：找 "\n              </div>" (legend 的闭合)
      const realEnd = html.indexOf('\n              </div>', legendStart);
      const legendHtml = html.slice(legendStart, realEnd);
      // 从原位置删除
      html = html.slice(0, legendStart) + html.slice(realEnd);
      // 插入到卡片标题行 caption 后面
      const captionStr = '<p class="pf-card-caption">score-v1.4 标签在实际结果上的命中率 · 权重校准核心输入</p>';
      html = html.replace(captionStr, captionStr + '\n            ' + legendHtml.replace(/class="pf-mx-legend"/, 'class="pf-mx-legend pf-mx-legend--head"'));
    }
  }

  // 4) 追加微调样式：标题旁图例样式
  const tweakCss = `
  /* 微调：标题旁图例 */
  .pf-mx-legend--head { padding-top: 0; margin-left: auto; gap: 6px 14px; }
  .pf-card-head { display: flex; flex-wrap: wrap; align-items: center; gap: 4px 16px; }
  .pf-card-head .pf-card-title { margin-right: 0; }
  .pf-card-head .pf-card-caption { order: 3; width: 100%; }
  `;
  html = html.replace('</style>', tweakCss + '\n</style>');

  fs.writeFileSync(f, html, 'utf8');
  console.log('OK ' + slug);
}
console.log('done');
