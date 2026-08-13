// 微调后暗色令牌对比度复验
function lum(hex) {
  const c = hex.replace('#', '');
  const rgb = [0, 2, 4].map(i => {
    let v = parseInt(c.slice(i, i + 2), 16) / 255;
    return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
  });
  return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2];
}
function ratio(a, b) {
  const [l1, l2] = [lum(a), lum(b)].sort((x, y) => y - x);
  return ((l1 + 0.05) / (l2 + 0.05)).toFixed(2);
}
const pairs = [
  ['正文 fg / 卡片', '#eceffa', '#161a2e'],
  ['次级文字 / 卡片', '#a3aacc', '#161a2e'],
  ['次级文字 / 背景', '#a3aacc', '#0e1120'],
  ['品牌 primary / 卡片', '#8b93f5', '#161a2e'],
  ['品牌按钮文字 / primary', '#10122a', '#8b93f5'],
  ['success 文字 / subtle', '#6fe0b6', '#14382b'],
  ['warning 文字 / subtle', '#f7c66f', '#3f3014'],
  ['error 文字 / subtle', '#f79b95', '#421d1b'],
  ['info 文字 / subtle', '#b2b8f8', '#272c52'],
  ['ignore 徽章文字 / bg', '#c3c9d8', '#282e42'],
  ['边框 / 卡片(分界可见度)', '#303759', '#161a2e'],
  ['输入边框 / 卡片', '#3a4166', '#161a2e'],
  ['导航激活文字 / accent', '#b2b8f8', '#232850'],
  ['图表 chart-3 / 卡片', '#5f68d4', '#161a2e'],
  ['brand-strong / subtle(徽标文字)', '#b2b8f8', '#272c52'],
];
for (const [name, a, b] of pairs) {
  const r = ratio(a, b);
  const tag = parseFloat(r) >= 4.5 ? 'PASS' : parseFloat(r) >= 3.0 ? 'LARGE/UI' : 'LOW ';
  console.log(`${tag}  ${r}:1  ${name}`);
}
