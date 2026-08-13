// Polish the collapsed (64px) icon sidebar:
// - uniform 40x40 icon slots with 4px gaps
// - left edge accent bar on the active item
// - hover/focus flyout label tooltip (reuses .app-nav-label)
// - centered brand mark + larger status dot
const fs = require("fs");
const path = require("path");

const PAGES_DIR = path.join(__dirname, "..", "pages");

const blockOld = `  @media (max-width: 959px) {
    .app-sidebar { width: 64px; padding: 16px 8px; align-items: center; }
    .app-main { margin-left: 64px; }
    .app-brand { padding: 8px 0 20px; }
    .app-brand-text { display: none; }
    .app-nav { width: 100%; align-items: center; }
    .app-nav-item { width: 40px; padding: 0; justify-content: center; gap: 0; }
    .app-nav-label,
    .app-nav-badge { display: none; }
    .app-sidebar-footer { width: 100%; padding: 12px 0 0; }
    .app-api-health { justify-content: center; }
    .app-api-label,
    .app-api-version { display: none; }
    .app-engine-badges { display: none; }
  }`;

const blockNew = `  @media (max-width: 959px) {
    .app-sidebar { width: 64px; padding: 14px 10px; align-items: center; }
    .app-main { margin-left: 64px; }
    .app-brand { padding: 4px 0 18px; justify-content: center; }
    .app-brand-text { display: none; }
    .app-nav { width: 100%; align-items: center; gap: 4px; }
    .app-nav-item {
      position: relative;
      width: 40px;
      height: 40px;
      padding: 0;
      justify-content: center;
      gap: 0;
      border-radius: var(--radius-md);
    }
    .app-nav-item[data-active="true"]::before {
      content: "";
      position: absolute;
      left: -10px;
      top: 10px;
      bottom: 10px;
      width: 3px;
      border-radius: 0 3px 3px 0;
      background: var(--primary);
    }
    .app-nav-badge { display: none; }
    .app-nav-label {
      display: none;
      position: absolute;
      left: calc(100% + 14px);
      top: 50%;
      transform: translateY(-50%);
      padding: 6px 10px;
      background: var(--popover, var(--card));
      color: var(--popover-foreground, var(--foreground));
      border: 1px solid var(--border);
      border-radius: var(--radius-md);
      box-shadow: var(--shadow-md);
      font-size: 12.5px;
      line-height: 1;
      white-space: nowrap;
      z-index: 60;
      pointer-events: none;
    }
    .app-nav-item:hover .app-nav-label,
    .app-nav-item:focus-visible .app-nav-label { display: block; }
    .app-sidebar-footer { width: 100%; padding: 12px 0 2px; }
    .app-api-health { justify-content: center; }
    .app-api-dot { width: 10px; height: 10px; }
    .app-api-label,
    .app-api-version { display: none; }
    .app-engine-badges { display: none; }
  }`;

const files = fs.readdirSync(PAGES_DIR).filter((f) => f.endsWith(".html"));
const results = [];
for (const file of files) {
  const p = path.join(PAGES_DIR, file);
  const s = fs.readFileSync(p, "utf8");
  if (!s.includes(blockOld)) {
    results.push({ file, changed: false });
    continue;
  }
  fs.writeFileSync(p, s.replace(blockOld, blockNew), "utf8");
  results.push({ file, changed: true });
}
console.log(JSON.stringify({
  total: files.length,
  changed: results.filter((r) => r.changed).length,
  issues: results.filter((r) => !r.changed),
}, null, 2));
