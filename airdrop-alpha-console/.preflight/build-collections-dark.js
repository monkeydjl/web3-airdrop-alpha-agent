// Build collections-dark.html from collections.html, copying theme class only.
const fs = require("fs");
const path = require("path");

const ROOT = path.join(__dirname, "..", "pages");
const SRC = path.join(ROOT, "collections.html");
const DST = path.join(ROOT, "collections-dark.html");

let s = fs.readFileSync(SRC, "utf8");
// switch html class
s = s.replace('<html lang="zh-CN" class="light">', '<html lang="zh-CN" class="dark">');
// title suffix to mirror dark page naming convention elsewhere
s = s.replace(/<title>([^<]+)<\/title>/, `<title>$1 — 暗色</title>`);

fs.writeFileSync(DST, s, "utf8");
const stat = {
  written: path.relative(path.join(__dirname, ".."), DST),
  bytes: fs.statSync(DST).size,
  dark: s.includes('class="dark"'),
  title: /<title>([^<]+)<\/title>/.exec(s)[1],
};
console.log(JSON.stringify(stat, null, 2));
