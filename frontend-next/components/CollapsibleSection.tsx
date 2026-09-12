'use client';

import { useState } from 'react';

/**
 * 可折叠 section：头部整行可点（标题 + meta + 旋转箭头），内容默认不渲染。
 *
 * 用于详情页的明细参考区块（四路分析 / 8 维子分 / Opportunity / 融资）——
 * 折叠时子树不挂载，页面首屏只剩决策区与行动区；想看细节点一下展开。
 *
 * 头部样式对齐 page.tsx 的 SecHead（等宽小字号大写），保证展开与折叠
 * 区块在同一页里视觉一致。用受控 button + aria-expanded 而不是原生
 * <details>：React 对 details 的 open 属性是受控语义，重渲染会把用户
 * 手动点开的状态打回去。
 */
export function CollapsibleSection({
  id,
  title,
  meta,
  children,
  defaultOpen = false,
}: {
  id: string;
  title: string;
  meta?: string;
  children: React.ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <section id={id} className="scroll-mt-[4.5rem] border-t border-line py-5">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={`${id}-body`}
        onClick={() => setOpen((v) => !v)}
        className="-my-1 flex w-full items-center justify-between gap-3 py-1 text-left"
      >
        <span className="flex items-baseline gap-2.5">
          <span className="m-0 font-mono text-[11px] font-semibold uppercase tracking-[0.08em] text-ink-muted">
            {title}
          </span>
          {meta ? (
            <span className="font-mono text-[10px] tracking-wide text-ink-faint">{meta}</span>
          ) : null}
        </span>
        <span aria-hidden className={`text-xs text-ink-faint transition-transform ${open ? 'rotate-90' : ''}`}>
          ▸
        </span>
      </button>
      {open ? (
        <div id={`${id}-body`} className="pt-3.5">
          {children}
        </div>
      ) : null}
    </section>
  );
}
