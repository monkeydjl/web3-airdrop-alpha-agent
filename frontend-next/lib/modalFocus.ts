/**
 * 弹窗焦点管理的纯逻辑。
 *
 * 刻意与 React / 真实 DOM 渲染解耦：`Modal` 负责挂载、事件与滚动锁定，这里只
 * 回答两个最容易出错、又完全不需要浏览器就能验证的问题 ——
 *   1. 作用域里「哪些元素此刻能被 Tab 到」；
 *   2. 按 Tab / Shift+Tab 之后焦点该落到第几个（含两端循环）。
 *
 * 抽出成独立模块是为了能放进 `lib/*.test.ts` 做单测：禁用项、`tabindex="-1"`、
 * 隐藏元素、空集合与环形边界这些分支，靠人工点弹窗很难覆盖，而它们一旦错了
 * 表现是「焦点跑出弹窗」——用户只会觉得键盘坏了。
 */

/**
 * 可聚焦元素选择器，与浏览器默认 Tab 顺序覆盖的元素集对齐。
 * 已排除 `disabled`、`type="hidden"` 与 `tabindex="-1"`。
 */
export const FOCUSABLE_SELECTOR = [
  'a[href]',
  'area[href]',
  'button:not([disabled])',
  'input:not([disabled]):not([type="hidden"])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  'iframe',
  'audio[controls]',
  'video[controls]',
  '[contenteditable]:not([contenteditable="false"])',
  '[tabindex]:not([tabindex="-1"])',
].join(', ');

/**
 * 只要能 `querySelectorAll` 即可。真实的 DOM 节点满足，测试替身也能满足，
 * 因此焦点逻辑不必依赖 jsdom。
 */
export interface FocusScope {
  querySelectorAll(selector: string): ArrayLike<Element>;
}

/** 选中后仍不应参与 Tab 的少数情况：显式隐藏或零尺寸。 */
function isFocusable(el: HTMLElement): boolean {
  if (el.getAttribute('aria-hidden') === 'true') return false;
  if (el.hasAttribute('hidden')) return false;
  if (el.hasAttribute('disabled')) return false;
  const rects = (el as { getClientRects?: () => { length: number } }).getClientRects?.();
  if (rects && rects.length === 0) return false;
  return true;
}

/** 收集作用域内当前可聚焦的元素，保持文档顺序。 */
export function focusableWithin(scope: FocusScope): HTMLElement[] {
  const out: HTMLElement[] = [];
  const nodes = scope.querySelectorAll(FOCUSABLE_SELECTOR);
  for (let i = 0; i < nodes.length; i += 1) {
    const el = nodes[i] as HTMLElement;
    if (isFocusable(el)) out.push(el);
  }
  return out;
}

/**
 * 计算 Tab（`shift=false`）或 Shift+Tab（`shift=true`）后应聚焦的下标。
 *
 * 支持两端环形循环；`current` 不在集合内（例如焦点还在容器上）时回到集合的
 * 首/尾。集合为空返回 `-1`，调用方据此决定是否回落到容器本身。
 */
export function nextFocusIndex(length: number, current: number, shift: boolean): number {
  if (length <= 0) return -1;
  if (current < 0 || current >= length) return shift ? length - 1 : 0;
  return (current + (shift ? -1 : 1) + length) % length;
}
