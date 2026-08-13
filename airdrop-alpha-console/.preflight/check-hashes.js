const fs = require("fs");
const path = require("path");
const crypto = require("crypto");

const root = "d:\\Github\\Web3 Airdrop Alpha Agent System\\airdrop-alpha-console";
const reportPath = path.join(root, "validation-report.json");
const report = JSON.parse(fs.readFileSync(reportPath, "utf8"));
const baseline = report.projectFileHashes || {};

function sha1(p) {
  const buf = fs.readFileSync(p);
  return crypto.createHash("sha1").update(buf).digest("hex");
}

const diffs = [];
for (const rel of Object.keys(baseline)) {
  const full = path.join(root, rel);
  if (!fs.existsSync(full)) {
    diffs.push({ rel, reason: "missing" });
    continue;
  }
  const now = sha1(full);
  if (now !== baseline[rel]) diffs.push({ rel, reason: "diff" });
}

console.log(JSON.stringify({ reportMtime: fs.statSync(reportPath).mtime, baselineCount: Object.keys(baseline).length, diffCount: diffs.length, diffs: diffs.slice(0, 5) }, null, 2));
