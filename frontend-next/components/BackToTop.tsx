'use client';

import { ArrowUp } from 'lucide-react';
import { useEffect, useState } from 'react';

/** 滚动超过该阈值（px）后显示「回到顶部」按钮 */
const SHOW_AFTER_PX = 600;

/**
 * 全局「回到顶部」悬浮按钮（挂在根 layout）。
 *
 * 长页面（项目详情页约 10 个 section）滚到底部后没有回到页头的捷径，
 * 只能拖滚动条。按钮固定在右下角，平滑回顶（html 已带 scroll-smooth）。
 */
export function BackToTop() {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const onScroll = () => setVisible(window.scrollY > SHOW_AFTER_PX);
    onScroll();
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, []);

  return (
    <button
      type="button"
      aria-label="回到顶部"
      onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })}
      // 不 unmount 只做显隐过渡：避免滚动到阈值附近时按钮反复挂载/卸载闪烁
      className={`fixed bottom-6 right-6 z-40 flex h-9 w-9 items-center justify-center rounded-full border border-line bg-surface text-ink-muted shadow-sm transition-opacity duration-200 hover:text-ink ${
        visible ? 'opacity-100' : 'pointer-events-none opacity-0'
      }`}
    >
      <ArrowUp size={16} aria-hidden />
    </button>
  );
}
