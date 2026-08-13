// 为长页面生成「回到顶部」对比版：复制源页 + 注入锚点与浮动控件
const fs = require('fs');
const path = require('path');
const pagesDir = 'd:/Github/Web3 Airdrop Alpha Agent System/airdrop-alpha-console/pages';

const targets = [
  'project-detail', 'project-detail-dark',
  'index', 'index-dark',
  'portfolio', 'portfolio-dark',
  'insights', 'insights-dark',
];

const css = `
/* 回到顶部 · 可用性增强 */
.btt-fab {
  position: fixed;
  right: 28px;
  bottom: 28px;
  z-index: 60;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  height: 44px;
  padding: 0 16px;
  border-radius: var(--radius-full);
  background: var(--primary);
  color: var(--primary-foreground);
  font-family: var(--font-sans);
  font-size: 13px;
  font-weight: 500;
  text-decoration: none;
  border: 0;
  cursor: pointer;
  box-shadow: var(--shadow-md);
  transition: transform var(--duration-fast) var(--ease-default), background-color var(--duration-fast) var(--ease-default);
}
.btt-fab:hover { transform: translateY(-3px); }
.btt-fab:active { transform: translateY(0); }
.btt-fab:focus-visible { outline: 2px solid var(--ring); outline-offset: 2px; }
.btt-fab [data-lucide] { width: 16px; height: 16px; }
@media (prefers-reduced-motion: reduce) { .btt-fab { transition: none; } }
@media (max-width: 959px) { .btt-fab { right: 20px; bottom: 20px; height: 40px; padding: 0 14px; } }
`;

const fab = `<a href="#page-top" class="btt-fab" aria-label="回到顶部"><i data-lucide="arrow-up"></i><span>回到顶部</span></a>`;

for (const slug of targets) {
  const src = path.join(pagesDir, slug + '.html');
  const dst = path.join(pagesDir, slug + '-btt.html');
  let html = fs.readFileSync(src, 'utf8');

  // 1) 在 <main class="app-content"> 起始处注入锚点
  if (!/<main class="app-content"/.test(html)) { console.log('MISS main: ' + slug); continue; }
  html = html.replace(/(<main class="app-content"[^>]*>)/, '$1\n      <span id="page-top" style="position:absolute;top:0;left:0;width:1px;height:1px;overflow:hidden;" aria-hidden="true"></span>');

  // 2) 在 </main> 前注入 CSS + FAB
  if (!/<\/main>/.test(html)) { console.log('MISS /main: ' + slug); continue; }
  html = html.replace('</main>', '      <style>' + css + '</style>\n      ' + fab + '\n    </main>');

  fs.writeFileSync(dst, html, 'utf8');
  console.log('OK ' + slug + '-btt.html');
}
