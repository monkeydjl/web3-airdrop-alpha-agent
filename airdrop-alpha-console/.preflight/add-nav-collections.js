// Insert "收藏关注" nav item into all existing pages (except collections*.html).
// Active state is set only on collections pages themselves.
// For other pages the new item receives data-dom-id="nav-collections" so canvas nav edges bind correctly.
const fs = require("fs");
const path = require("path");

const PAGES = path.join(__dirname, "..", "pages");
const files = fs.readdirSync(PAGES).filter((f) => f.endsWith(".html"));

const anchorRe = /(\s*<a href="#" class="app-nav-item" data-nav-key="ops"(?:\s+data-active="true")?(?:\s+data-dom-id="[^"]+")?>\s*<i data-lucide="server-cog"><\/i>\s*<span class="app-nav-label">运维台<\/span>\s*<\/a>)/;

const navItem = (isCollections) => `
      <a href="#" class="app-nav-item" data-nav-key="collections"${isCollections ? ' data-active="true"' : ' data-dom-id="nav-collections"'}>
        <i data-lucide="bookmark"></i>
        <span class="app-nav-label">收藏关注</span>
      </a>`;

const results = [];
for (const file of files) {
  const p = path.join(PAGES, file);
  let s = fs.readFileSync(p, "utf8");
  const isCollections = file.startsWith("collections");
  const hasNav = s.includes('data-nav-key="collections"');
  if (hasNav) { results.push({ file, skipped: "already" }); continue; }
  const m = s.match(anchorRe);
  if (!m) { results.push({ file, error: "no ops nav item" }); continue; }
  s = s.replace(anchorRe, `${m[1]}${navItem(isCollections)}`);
  fs.writeFileSync(p, s, "utf8");
  results.push({ file, added: true, isCollections });
}

console.log(JSON.stringify({
  total: files.length,
  added: results.filter((r) => r.added).length,
  skipped: results.filter((r) => r.skipped).map((r) => r.file),
  issues: results.filter((r) => r.error),
}, null, 2));
