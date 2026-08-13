// Fixed sidebar: sticky -> fixed, add margin-left to .app-main
const fs = require("fs");
const path = require("path");

const PAGES_DIR = path.join(__dirname, "..", "pages");

const files = fs.readdirSync(PAGES_DIR).filter((f) => f.endsWith(".html"));

const sidebarOld = `  .app-sidebar {
    width: 240px;
    flex-shrink: 0;
    position: sticky;
    top: 0;
    height: 100vh;
    display: flex;
    flex-direction: column;
    padding: 16px 12px;
    background: var(--sidebar);
    border-right: 1px solid var(--sidebar-border);
  }`;
const sidebarNew = `  .app-sidebar {
    width: 240px;
    flex-shrink: 0;
    position: fixed;
    top: 0;
    left: 0;
    z-index: 50;
    height: 100vh;
    display: flex;
    flex-direction: column;
    padding: 16px 12px;
    background: var(--sidebar);
    border-right: 1px solid var(--sidebar-border);
  }`;

const mainOld = `  .app-main {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
  }`;
const mainNew = `  .app-main {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    margin-left: 240px;
  }`;

const narrowOld = `    .app-sidebar { width: 64px; padding: 16px 8px; align-items: center; }`;
const narrowNew = `    .app-sidebar { width: 64px; padding: 16px 8px; align-items: center; }
    .app-main { margin-left: 64px; }`;

const commentOld = `  /* ---------- 侧边栏（240px · 吸顶） ---------- */`;
const commentNew = `  /* ---------- 侧边栏（240px · 固定） ---------- */`;

const results = [];
for (const file of files) {
  const p = path.join(PAGES_DIR, file);
  let s = fs.readFileSync(p, "utf8");
  const orig = s;
  const applied = { sidebar: false, main: false, narrow: false };

  if (s.includes(sidebarOld)) {
    s = s.replace(sidebarOld, sidebarNew);
    applied.sidebar = true;
  }
  if (s.includes(mainOld)) {
    s = s.replace(mainOld, mainNew);
    applied.main = true;
  }
  if (s.includes(narrowOld)) {
    s = s.replace(narrowOld, narrowNew);
    applied.narrow = true;
  }
  if (s.includes(commentOld)) {
    s = s.replace(commentOld, commentNew);
  }

  if (s !== orig) {
    fs.writeFileSync(p, s, "utf8");
    results.push({ file, applied });
  } else {
    results.push({ file, applied, skipped: true });
  }
}

const pass = results.filter((r) => r.applied.sidebar && r.applied.main && r.applied.narrow);
const fail = results.filter((r) => !(r.applied.sidebar && r.applied.main && r.applied.narrow));
console.log(JSON.stringify({ total: files.length, changed: pass.length, issues: fail }, null, 2));
