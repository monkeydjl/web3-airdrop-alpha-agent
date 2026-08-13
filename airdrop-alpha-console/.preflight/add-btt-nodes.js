// 注册 8 个回到顶部对比页节点（group=2，紧凑画布坐标）
const fs = require('fs');
const p = 'd:/Github/Web3 Airdrop Alpha Agent System/airdrop-alpha-console/airdrop-alpha-console.design';
const j = JSON.parse(fs.readFileSync(p, 'utf8'));

const ts = 1786361700000;
const mk = (id, title, htmlSrc, x, y) => ({
  id, title, type: 'page', version: 1, createdAt: ts,
  canvasData: { x, y, group: 2 },
  devMetadata: { htmlSrc, interactions: [] }
});

const nodes = [
  mk('page-index-btt', '工作台 · 项目雷达 — 回到顶部', 'pages/index-btt.html', 0, 2200),
  mk('page-project-detail-btt', '项目详情 — 回到顶部', 'pages/project-detail-btt.html', 620, 2200),
  mk('page-portfolio-btt', '参与复盘 — 回到顶部', 'pages/portfolio-btt.html', 1240, 2200),
  mk('page-insights-btt', '洞察 — 回到顶部', 'pages/insights-btt.html', 1860, 2200),
  mk('page-index-dark-btt', '工作台 · 项目雷达 暗色 — 回到顶部', 'pages/index-dark-btt.html', 0, 3300),
  mk('page-project-detail-dark-btt', '项目详情 暗色 — 回到顶部', 'pages/project-detail-dark-btt.html', 620, 3300),
  mk('page-portfolio-dark-btt', '参与复盘 暗色 — 回到顶部', 'pages/portfolio-dark-btt.html', 1240, 3300),
  mk('page-insights-dark-btt', '洞察 暗色 — 回到顶部', 'pages/insights-dark-btt.html', 1860, 3300),
];

// 防御：若已存在同 id 则先移除再追加（幂等）
j.data = j.data.filter(n => !nodes.some(m => m.id === n.id));
j.data.push(...nodes);
fs.writeFileSync(p, JSON.stringify(j, null, 2), 'utf8');
console.log('nodes total =', j.data.length);
