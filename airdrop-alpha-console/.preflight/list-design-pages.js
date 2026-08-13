const fs = require("fs");
const d = JSON.parse(fs.readFileSync("d:\\Github\\Web3 Airdrop Alpha Agent System\\airdrop-alpha-console\\airdrop-alpha-console.design", "utf8"));
const out = d.data.map((p) => ({
  id: p.id, title: p.title, x: p.canvasData && p.canvasData.x, y: p.canvasData && p.canvasData.y,
  group: p.canvasData && p.canvasData.group,
  src: p.devMetadata && p.devMetadata.htmlSrc,
}));
console.log(JSON.stringify(out, null, 2));
