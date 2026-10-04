/**
 * 弹窗定位与统一外壳的静态守卫。
 *
 * 背景：`position: fixed` 的遮罩一旦渲染在某个带 transform / backdrop-filter /
 * filter / perspective / contain 的祖先里，该祖先就成了它的**包含块**，弹窗会被
 * 关进那张卡片/顶栏并被 `overflow-hidden` 裁掉。项目卡片暗色下的
 * `.card-hover:hover { transform: translateY(-2px) }` 与顶栏
 * `.app-topbar { backdrop-filter: blur(12px) }` 都命中过这条规则，直接导致
 * 「弹窗太靠上、显示不全 / 渲染在项目小卡片里 / 页面闪烁」。
 *
 * 修法是把所有遮罩统一交给 `Modal`（内部 createPortal 到 document.body）。这个
 * 测试是那条规则的静态守卫，钉住三件事：
 *   1. 遮罩数量足够多（守卫自身不空转，正则/路径失效会立刻暴露）；
 *   2. 没有人再手写 `<div … fixed inset-0 …>` 遮罩；
 *   3. 没有人绕过 `Modal` 直接用 `ModalPortal` —— 否则焦点陷阱 / Esc / aria-modal /
 *      滚动锁定又会缺一块。
 *
 * 跑法：`npm test`（等价于同一进程内 import 本文件）。
 */

import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { describe, it } from 'node:test';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const ROOT = dirname(fileURLToPath(import.meta.url));
const SCAN_DIRS = ['../components', '../app'];

/** 收集待扫描的 .tsx 源码（递归）。 */
function collectTsx(): string[] {
  const files: string[] = [];
  for (const d of SCAN_DIRS) {
    const dir = join(ROOT, d);
    const walk = (cur: string) => {
      for (const entry of readdirSync(cur, { withFileTypes: true })) {
        const full = join(cur, entry.name);
        if (entry.isDirectory()) walk(full);
        else if (entry.name.endsWith('.tsx')) files.push(full);
      }
    };
    walk(dir);
  }
  return files;
}

/**
 * 找出所有承载 `fixed inset-0` 的 JSX 开标签，返回 `{file, tag}`。
 *
 * 只认 `<Tag ... fixed inset-0 ...>` 这种开标签，因此 Modal.tsx 文档注释与
 * className 模板串里出现的 `fixed inset-0` 片段不会被误判。
 */
function findFixedOverlays(): Array<{ file: string; tag: string }> {
  const out: Array<{ file: string; tag: string }> = [];
  for (const file of collectTsx()) {
    const src = readFileSync(file, 'utf8');
    const re = /<(\w+)[^>]*\bfixed inset-0/g;
    for (const m of src.matchAll(re)) out.push({ file, tag: m[1] });
  }
  return out;
}

/** 统计 `<Modal ` 开标签的出现次数（排除 Modal.tsx 自身）。 */
function countModalUsages(): number {
  let n = 0;
  for (const file of collectTsx()) {
    if (file.endsWith(join('components', 'Modal.tsx'))) continue;
    n += (readFileSync(file, 'utf8').match(/<Modal\s/g) ?? []).length;
  }
  return n;
}

describe('弹窗遮罩必须走统一 Modal 外壳', () => {
  it('仓库里仍有足量 <Modal> 弹窗（守卫自身不空转）', () => {
    const usages = countModalUsages();
    assert.ok(usages >= 20, `只找到 ${usages} 处 <Modal>，扫描可能失效`);
  });

  it('没有人手写 `fixed inset-0` 遮罩', () => {
    assert.deepEqual(
      findFixedOverlays().map((o) => `${o.file.replace(ROOT, '')}: <${o.tag}>`),
      [],
      '请改用 <Modal title="…">（内置传送门/焦点陷阱/Esc/aria/滚动锁定）',
    );
  });

  it('Modal 通过 createPortal 传送到 document.body', () => {
    const src = readFileSync(join(ROOT, '../components/Modal.tsx'), 'utf8');
    assert.match(src, /createPortal\(/, 'Modal 必须使用 createPortal');
    assert.match(src, /document\.body/, 'Modal 必须传送到 document.body');
  });

  it('Modal 内置焦点陷阱 / Esc 关闭 / aria-modal / 滚动锁定', () => {
    const src = readFileSync(join(ROOT, '../components/Modal.tsx'), 'utf8');
    assert.match(src, /aria-modal="true"/, '必须声明 aria-modal');
    assert.match(src, /role=\{role\}/, '必须有 dialog 语义');
    assert.match(src, /'Escape'/, '必须响应 Esc');
    assert.match(src, /focusableWithin/, '必须实现焦点陷阱');
    assert.match(src, /overflow = 'hidden'/, '必须锁定背景滚动');
  });

  it('没有组件绕过 Modal 直接用 ModalPortal', () => {
    const offenders: string[] = [];
    for (const file of collectTsx()) {
      if (file.endsWith(join('components', 'Modal.tsx'))) continue;
      if (readFileSync(file, 'utf8').includes('<ModalPortal')) offenders.push(file.replace(ROOT, ''));
    }
    assert.deepEqual(offenders, [], '请直接用 <Modal>；ModalPortal 只是它的内部实现细节');
  });
});
