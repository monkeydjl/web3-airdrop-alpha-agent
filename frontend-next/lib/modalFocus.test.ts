/**
 * lib/modalFocus.ts 的单测。
 *
 * 焦点陷阱的失败方式很隐蔽：禁用项被算进去、`tabindex="-1"` 被误当成可聚焦、
 * 两端循环差一位、空集合时焦点逃到背景 —— 都不会报错，只会让键盘用起来「怪」。
 * 这里用最小的假 DOM（只实现被用到的三个方法）把每个分支钉死，因此不需要
 * jsdom，`npm test` 在 Node 里直接跑真实源文件。
 */

import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import { FOCUSABLE_SELECTOR, focusableWithin, nextFocusIndex } from './modalFocus.ts';
import type { FocusScope } from './modalFocus.ts';

/** 造一个只带测试关心能力的假元素。 */
function fakeEl(attrs: Record<string, string> = {}, rects = 1): HTMLElement {
  return {
    getAttribute(name: string) {
      return name in attrs ? attrs[name] : null;
    },
    hasAttribute(name: string) {
      return name in attrs;
    },
    getClientRects() {
      return { length: rects };
    },
  } as unknown as HTMLElement;
}

/** 收集查询选择器以便断言，同时返回预设的元素列表。 */
function fakeScope(els: HTMLElement[]): { scope: FocusScope; selector: () => string } {
  let last = '';
  return {
    scope: {
      querySelectorAll(selector: string) {
        last = selector;
        return els;
      },
    },
    selector: () => last,
  };
}

describe('focusableWithin', () => {
  it('用同一个可聚焦选择器查询作用域', () => {
    const { scope, selector } = fakeScope([]);
    focusableWithin(scope);
    assert.equal(selector(), FOCUSABLE_SELECTOR);
    assert.match(FOCUSABLE_SELECTOR, /button:not\(\[disabled\]\)/);
  });

  it('保留普通元素并保持文档顺序', () => {
    const a = fakeEl();
    const b = fakeEl();
    const { scope } = fakeScope([a, b]);
    assert.deepEqual(focusableWithin(scope), [a, b]);
  });

  it('过滤 aria-hidden / hidden / disabled / 零尺寸元素', () => {
    const keep = fakeEl();
    const hidden = fakeEl({ 'aria-hidden': 'true' });
    const hiddenAttr = fakeEl({ hidden: '' });
    const disabled = fakeEl({ disabled: '' });
    const zeroSize = fakeEl({}, 0);
    const { scope } = fakeScope([keep, hidden, hiddenAttr, disabled, zeroSize]);
    assert.deepEqual(focusableWithin(scope), [keep]);
  });

  it('没有可聚焦元素时返回空数组（调用方据此回落到容器）', () => {
    const { scope } = fakeScope([]);
    assert.deepEqual(focusableWithin(scope), []);
  });
});

describe('nextFocusIndex', () => {
  it('向前推进并在末尾回到开头（环形）', () => {
    assert.equal(nextFocusIndex(3, 0, false), 1);
    assert.equal(nextFocusIndex(3, 2, false), 0);
  });

  it('向后推进并在开头绕到末尾', () => {
    assert.equal(nextFocusIndex(3, 1, true), 0);
    assert.equal(nextFocusIndex(3, 0, true), 2);
  });

  it('焦点不在集合内时落到首/尾', () => {
    assert.equal(nextFocusIndex(3, -1, false), 0);
    assert.equal(nextFocusIndex(3, -1, true), 2);
    assert.equal(nextFocusIndex(3, 99, false), 0);
    assert.equal(nextFocusIndex(3, 99, true), 2);
  });

  it('空集合返回 -1', () => {
    assert.equal(nextFocusIndex(0, -1, false), -1);
    assert.equal(nextFocusIndex(0, 0, true), -1);
  });

  it('只有一个元素时原地循环', () => {
    assert.equal(nextFocusIndex(1, 0, false), 0);
    assert.equal(nextFocusIndex(1, 0, true), 0);
  });
});
