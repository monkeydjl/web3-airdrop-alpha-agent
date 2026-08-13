// Register notifications / notifications-dark / archive / archive-dark into the
// airdrop-alpha-console.design canvas and wire nav edges across all pages.
const fs = require("fs");

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

const NAV_KEYS = ["index", "discoveries", "insights", "portfolio", "ops", "notifications", "archive", "collections"];
const darkSuffix = (id) => id.endsWith("-dark") || id.endsWith("-dark-btt");
const targetFor = (key, dark) => `page-${key}${dark ? "-dark" : ""}`;

function navEdgesFor(selfKey, dark) {
  return NAV_KEYS.filter((k) => k !== selfKey).map((k) => navEdge(`nav-${k}`, targetFor(k, dark)));
}

const newNodes = [
  {
    id: "page-notifications",
    title: "通知中心",
    type: "page",
    version: 1,
    createdAt: now,
    canvasData: { x: 1860, y: 428, group: 0 },
    devMetadata: {
      htmlSrc: "pages/notifications.html",
      interactions: [
        interaction("ntf-item-1", "page-project-detail", "查看 Nova Protocol"),
        interaction("ntf-item-2", "page-project-detail", "前往参与 Poly Oracle"),
        interaction("ntf-item-3", "page-ops", "处理采集器告警"),
        ...navEdgesFor("notifications", false),
      ],
    },
  },
  {
    id: "page-notifications-dark",
    title: "通知中心 — 暗色",
    type: "page",
    version: 1,
    createdAt: now + 1,
    canvasData: { x: 1860, y: 1299, group: 1 },
    devMetadata: {
      htmlSrc: "pages/notifications-dark.html",
      interactions: [
        interaction("ntf-item-1", "page-project-detail-dark", "查看 Nova Protocol"),
        interaction("ntf-item-2", "page-project-detail-dark", "前往参与 Poly Oracle"),
        interaction("ntf-item-3", "page-ops-dark", "处理采集器告警"),
        ...navEdgesFor("notifications", true),
      ],
    },
  },
  {
    id: "page-archive",
    title: "归档历史",
    type: "page",
    version: 1,
    createdAt: now + 2,
    canvasData: { x: 0, y: 428, group: 0 },
    devMetadata: { htmlSrc: "pages/archive.html", interactions: navEdgesFor("archive", false) },
  },
  {
    id: "page-archive-dark",
    title: "归档历史 — 暗色",
    type: "page",
    version: 1,
    createdAt: now + 3,
    canvasData: { x: 0, y: 1299, group: 1 },
    devMetadata: { htmlSrc: "pages/archive-dark.html", interactions: navEdgesFor("archive", true) },
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

// Inject nav-notifications / nav-archive edges into every pre-existing page.
const injected = [];
for (const p of pages) {
  if (added.includes(p.id)) continue;
  if (!p.devMetadata) p.devMetadata = { htmlSrc: "", interactions: [] };
  if (!Array.isArray(p.devMetadata.interactions)) p.devMetadata.interactions = [];
  const dark = darkSuffix(p.id);
  for (const key of ["notifications", "archive"]) {
    const domId = `nav-${key}`;
    const exists = p.devMetadata.interactions.some((i) => i.domId === domId);
    if (!exists) {
      p.devMetadata.interactions.push(navEdge(domId, targetFor(key, dark)));
      injected.push(`${p.id} -> ${domId}`);
    }
  }
}

fs.writeFileSync(DESIGN, JSON.stringify(doc, null, 2), "utf8");

console.log(JSON.stringify({ totalPages: pages.length, addedNodes: added, injectedEdges: injected.length }, null, 2));
