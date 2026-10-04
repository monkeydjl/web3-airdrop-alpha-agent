'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import type { KeyboardEvent as ReactKeyboardEvent, MouseEvent as ReactMouseEvent, ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { focusableWithin, nextFocusIndex } from '@/lib/modalFocus';

/**
 * 遮罩外壳的基础类名，刻意放在模块顶层常量里而非直接写进 JSX。
 *
 * 原因不只是复用：`lib/modalShell.test.ts` 有一条静态守卫，会扫描所有 `.tsx`
 * 里手写的 `fixed inset-0` 遮罩开标签，确保没有组件绕过本组件自己造外壳。
 * 把定位类收敛到常量后，全仓库唯一的遮罩定义点就是这里。
 *
 * 注意：这里不含 padding —— 它由 `paddingClassName` 单独传入。原因：Tailwind
 * 冲突类（`p-3` vs `p-4`）谁生效由样式表里的生成顺序决定、而非 className 的
 * 书写顺序，因此「默认 padding 写进常量、调用方再用 backdropClassName 覆盖」
 * 不可靠；拆成独立 prop 后同一时刻只有一个 padding 类存在。
 */
const OVERLAY_CLASS =
  'fixed inset-0 z-50 flex items-center justify-center animate-fade-in';

export interface ModalProps {
  children: ReactNode;
  /** 无障碍名称（映射到 aria-label），必填：缺了它 dialog 对屏幕阅读器匿名。 */
  title: string;
  /** 传入后启用 Esc 关闭、点击遮罩关闭与关闭时的焦点归还。 */
  onClose?: () => void;
  /** 对话框语义，默认普通 `dialog`，破坏性确认可用 `alertdialog`。 */
  role?: 'dialog' | 'alertdialog';
  /** 遮罩层额外类名（背景透明度 / 模糊），各弹窗原有的视觉差异走这里。 */
  backdropClassName?: string;
  /** 遮罩内边距，默认 `p-4`；个别弹窗（如响应式 `p-3 sm:p-6`）在这里覆盖。 */
  paddingClassName?: string;
  /** 是否允许点击遮罩空白处关闭，默认开启（仅在提供了 onClose 时生效）。 */
  closeOnBackdrop?: boolean;
}

/**
 * 统一的弹窗遮罩外壳。
 *
 * 原先 24 处弹窗各自手写一份 `fixed inset-0` 遮罩，导致三类问题反复出现：
 * 遮罩渲染进带 `transform` / `backdrop-filter` 的祖先里被当成包含块而裁剪、
 * 焦点停留在背景页面、Esc 与滚动锁定各写各的还经常漏。这里一次性收口：
 *
 *   - `createPortal` 到 `document.body`，彻底摆脱祖先包含块的影响；
 *   - 焦点陷阱（Tab / Shift+Tab 在弹窗内循环，打开时移入、关闭时归还）；
 *   - Esc 关闭与点击遮罩关闭；
 *   - `role` + `aria-modal="true"` 的对话框语义；
 *   - 挂载期间锁定 `body` 滚动，卸载时还原。
 */
export function Modal({
  children,
  title,
  onClose,
  role = 'dialog',
  backdropClassName = '',
  paddingClassName = 'p-4',
  closeOnBackdrop = true,
}: ModalProps) {
  const panelRef = useRef<HTMLDivElement>(null);
  // 遮罩点击的「同起点同终点」校验位：mousedown 落在遮罩上、click 也落在
  // 遮罩上才算点空白关闭 —— 避免从遮罩起按拖选文本、在内容区松开时误关。
  const backdropDownRef = useRef(false);
  const [mounted, setMounted] = useState(false);

  // 仅在客户端挂载后再传送，避免服务端渲染阶段访问 document。
  useEffect(() => {
    setMounted(true);
  }, []);

  // 打开时把焦点移入弹窗并把原焦点记下，关闭时归还 —— 否则焦点会掉回 <body>，
  // 键盘用户得重新 Tab 一长串才能回到触发按钮。
  useEffect(() => {
    if (!mounted) return;
    const previous = document.activeElement as HTMLElement | null;
    const panel = panelRef.current;
    const first = panel ? focusableWithin(panel)[0] ?? panel : null;
    first?.focus();
    return () => {
      previous?.focus?.();
    };
  }, [mounted]);

  // 滚动锁定：记录原值后隐藏 body 溢出，卸载时恢复（不覆盖调用方原本的样式）。
  useEffect(() => {
    if (!mounted) return;
    const { body } = document;
    const previous = body.style.overflow;
    body.style.overflow = 'hidden';
    return () => {
      body.style.overflow = previous;
    };
  }, [mounted]);

  const handleKeyDown = useCallback(
    (event: ReactKeyboardEvent<HTMLDivElement>) => {
      if (event.key === 'Escape') {
        if (!onClose) return;
        event.stopPropagation();
        onClose();
        return;
      }
      if (event.key !== 'Tab') return;

      const panel = panelRef.current;
      if (!panel) return;
      const focusables = focusableWithin(panel);
      if (focusables.length === 0) {
        // 没有任何可聚焦元素时，把 Tab 收敛到容器本身，避免焦点逃到背景。
        event.preventDefault();
        panel.focus();
        return;
      }
      const active = document.activeElement as HTMLElement | null;
      const target = nextFocusIndex(
        focusables.length,
        active ? focusables.indexOf(active) : -1,
        event.shiftKey,
      );
      if (target < 0) return;
      event.preventDefault();
      focusables[target]?.focus();
    },
    [onClose],
  );

  const handleBackdropMouseDown = useCallback((event: ReactMouseEvent<HTMLDivElement>) => {
    // 只记录「按下是否在遮罩本身」，关闭决策留给 click（见上）。
    backdropDownRef.current = event.target === event.currentTarget;
  }, []);

  const handleBackdropClick = useCallback(
    (event: ReactMouseEvent<HTMLDivElement>) => {
      const startedOnBackdrop = backdropDownRef.current;
      backdropDownRef.current = false;
      if (!onClose || !closeOnBackdrop || !startedOnBackdrop) return;
      // 按下与松开都在遮罩本身（空白区）才关闭，点内容区不冒泡成关闭。
      if (event.target !== event.currentTarget) return;
      onClose();
    },
    [onClose, closeOnBackdrop],
  );

  if (!mounted) return null;

  return createPortal(
    <div
      ref={panelRef}
      role={role}
      aria-modal="true"
      aria-label={title}
      tabIndex={-1}
      onKeyDown={handleKeyDown}
      onMouseDown={handleBackdropMouseDown}
      onClick={handleBackdropClick}
      className={`${OVERLAY_CLASS} ${paddingClassName}${backdropClassName ? ` ${backdropClassName}` : ''}`}
    >
      {children}
    </div>,
    document.body,
  );
}

export default Modal;
