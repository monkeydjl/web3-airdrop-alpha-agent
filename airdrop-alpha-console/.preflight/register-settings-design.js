// Register settings / settings-dark into the canvas and wire nav-settings edges
// into every pre-existing page.
const fs = require("fs");

const DESIGN = "d:\\Github\\Web3 Airdrop Alpha Agent System\\airdrop-alpha-console\\airdrop-alpha-console.design";
const doc = JSON.parse(fs.readFileSync(DESIGN, "utf8"));
const pages = doc.data;

const existingIds = new Set(pages.map((p) => p.id));
const now = Date.now();

function navEdge(domId, targetPageId) {
  return { domId, targetPageId, hideEdge: true, transitionLabel: "全局导航" };
}

const NAV_KEYS = ["index", "discoveries", "insights", "portfolio", "ops", "notifications", "archive", "collections", "settings"];
const darkSuffix = (id) => id.endsWith("-dark") || id.endsWith("-dark-btt");
const targetFor = (key, dark) => `page-${key}${dark ? "-dark" : ""}`;

function navEdgesFor(selfKey, dark) {
  return NAV_KEYS.filter((k) => k !== selfKey).map((k) => navEdge(`nav-${k}`, targetFor(k, dark)));
}

const newNodes = [
  {
    id: "page-settings",
    title: "系统设置",
    type: "page",
    version: 1,
    createdAt: now,
    canvasData: { x: 620, y: 856, group: 0 },
    devMetadata: { htmlSrc: "pages/settings.html", interactions: navEdgesFor("settings", false) },
  },
  {
    id: "page-settings-dark",
    title: "系统设置 — 暗色",
    type: "page",
    version: 1,
    createdAt: now + 1,
    canvasData: { x: 1240, y: 1676, group: 1 },
    devMetadata: { htmlSrc: "pages/settings-dark.html", interactions: navEdgesFor("settings", true) },
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

const injected = [];
for (const p of pages) {
  if (added.includes(p.id)) continue;
  if (!p.devMetadata) p.devMetadata = { htmlSrc: "", interactions: [] };
  if (!Array.isArray(p.devMetadata.interactions)) p.devMetadata.interactions = [];
  const dark = darkSuffix(p.id);
  const exists = p.devMetadata.interactions.some((i) => i.domId === "nav-settings");
  if (!exists) {
    p.devMetadata.interactions.push(navEdge("nav-settings", targetFor("settings", dark)));
    injected.push(p.id);
  }
}

fs.writeFileSync(DESIGN, JSON.stringify(doc, null, 2), "utf8");
console.log(JSON.stringify({ totalPages: pages.length, addedNodes: added, injectedEdges: injected.length }, null, 2));
