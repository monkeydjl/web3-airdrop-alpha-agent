// Register collections / collections-dark pages into airdrop-alpha-console.design
// and add nav-collections edge to every other page.
const fs = require("fs");
const path = require("path");

const DESIGN = "d:\\Github\\Web3 Airdrop Alpha Agent System\\airdrop-alpha-console\\airdrop-alpha-console.design";
const doc = JSON.parse(fs.readFileSync(DESIGN, "utf8"));
const pages = doc.data;

const existingIds = new Set(pages.map((p) => p.id));
const now = Date.now();

function navEdge(domId, targetPageId) {
  return { domId, targetPageId, hideEdge: true, transitionLabel: "全局导航" };
}

function interaction(domId, targetPageId, transitionLabel) {
  return { domId, targetPageId, transitionLabel };
}

const lightInter = [
  interaction("col-card-nova", "page-project-detail", "查看 Nova Protocol"),
  interaction("col-card-poly", "page-project-detail", "查看 Poly Oracle"),
  interaction("col-card-kite", "page-project-detail", "查看 Kite Network"),
  navEdge("nav-index", "page-index"),
  navEdge("nav-discoveries", "page-discoveries"),
  navEdge("nav-insights", "page-insights"),
  navEdge("nav-portfolio", "page-portfolio"),
  navEdge("nav-ops", "page-ops"),
];

const darkInter = [
  interaction("col-card-nova", "page-project-detail-dark", "查看 Nova Protocol"),
  interaction("col-card-poly", "page-project-detail-dark", "查看 Poly Oracle"),
  interaction("col-card-kite", "page-project-detail-dark", "查看 Kite Network"),
  navEdge("nav-index", "page-index-dark"),
  navEdge("nav-discoveries", "page-discoveries-dark"),
  navEdge("nav-insights", "page-insights-dark"),
  navEdge("nav-portfolio", "page-portfolio-dark"),
  navEdge("nav-ops", "page-ops-dark"),
];

const newNodes = [
  {
    id: "page-collections",
    title: "收藏关注",
    type: "page",
    version: 1,
    createdAt: now,
    canvasData: { x: 1240, y: 428, group: 0 },
    devMetadata: { htmlSrc: "pages/collections.html", interactions: lightInter },
  },
  {
    id: "page-collections-dark",
    title: "收藏关注 — 暗色",
    type: "page",
    version: 1,
    createdAt: now + 1,
    canvasData: { x: 1240, y: 1299, group: 1 },
    devMetadata: { htmlSrc: "pages/collections-dark.html", interactions: darkInter },
  },
];

const added = [];
for (const n of newNodes) {
  if (!existingIds.has(n.id)) {
    pages.push(n);
    existingIds.add(n.id);
    added.push(n.id);
  }
}

// Map: page id -> collections target for nav edge injection
const navTargetFor = (id) => {
  if (id.endsWith("-dark-btt")) return "page-collections-dark";
  if (id.endsWith("-btt")) return "page-collections";
  if (id.endsWith("-dark")) return "page-collections-dark";
  return "page-collections";
};

const skippedEdges = [];
for (const p of pages) {
  if (p.id === "page-collections" || p.id === "page-collections-dark") continue;
  if (!p.devMetadata) p.devMetadata = { htmlSrc: "", interactions: [] };
  if (!Array.isArray(p.devMetadata.interactions)) p.devMetadata.interactions = [];
  const exists = p.devMetadata.interactions.some((i) => i.domId === "nav-collections");
  if (exists) { skippedEdges.push(p.id); continue; }
  p.devMetadata.interactions.push(navEdge("nav-collections", navTargetFor(p.id)));
}

fs.writeFileSync(DESIGN, JSON.stringify(doc, null, 2), "utf8");

console.log(JSON.stringify({
  totalPages: pages.length,
  addedNodes: added,
  edgesInjected: pages.length - added.length - skippedEdges.length - 2 + skippedEdges.length,
  skippedEdges,
}, null, 2));
