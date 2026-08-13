// Normalize the sidebar nav across all 26 pages to the canonical 8 items.
// Order: index, discoveries, insights, portfolio, ops, notifications, archive, collections
// - Active page keeps data-active="true" and drops its data-dom-id (detected from current markup)
// - project-detail* pages have no active item
const fs = require("fs");
const path = require("path");

const PAGES_DIR = "d:\\Github\\Web3 Airdrop Alpha Agent System\\airdrop-alpha-console\\pages";

const ITEMS = [
  { key: "index", icon: "radar", label: "工作台" },
  { key: "discoveries", icon: "satellite-dish", label: "发现队列", badge: "12" },
  { key: "insights", icon: "chart-line", label: "洞察" },
  { key: "portfolio", icon: "clipboard-check", label: "参与复盘" },
  { key: "ops", icon: "server-cog", label: "运维台" },
  { key: "notifications", icon: "bell", label: "通知中心" },
  { key: "archive", icon: "archive", label: "归档历史" },
  { key: "collections", icon: "bookmark", label: "收藏关注" },
];

function navItemHtml(item, activeKey) {
  const isActive = item.key === activeKey;
  const attrs = isActive
    ? `data-nav-key="${item.key}" data-active="true"`
    : `data-nav-key="${item.key}" data-dom-id="nav-${item.key}"`;
  const badge = item.badge ? `\n        <span class="app-nav-badge">${item.badge}</span>` : "";
  return [
    `      <a href="#" class="app-nav-item" ${attrs}>`,
    `        <i data-lucide="${item.icon}"></i>`,
    `        <span class="app-nav-label">${item.label}</span>${badge}`,
    `      </a>`,
  ].join("\n");
}

const files = fs.readdirSync(PAGES_DIR).filter((f) => f.endsWith(".html"));
const report = [];

for (const f of files) {
  const fp = path.join(PAGES_DIR, f);
  let html = fs.readFileSync(fp, "utf8");

  const navRe = /<nav class="app-nav" aria-label="主导航">[\s\S]*?<\/nav>/;
  const m = html.match(navRe);
  if (!m) {
    report.push({ f, ok: false, reason: "nav block not found" });
    continue;
  }

  const activeM = m[0].match(/data-nav-key="([a-z-]+)"\s+data-active="true"/);
  const activeKey = activeM ? activeM[1] : null;

  const newNav = [
    `<nav class="app-nav" aria-label="主导航">`,
    ...ITEMS.map((it) => navItemHtml(it, activeKey)),
    `    </nav>`,
  ].join("\n");

  html = html.replace(navRe, newNav);
  fs.writeFileSync(fp, html, "utf8");
  report.push({ f, ok: true, active: activeKey });
}

console.log(JSON.stringify(report, null, 2));
