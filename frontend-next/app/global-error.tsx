'use client';

/**
 * 全局错误兜底（2026-11-13 审查 P1-1）。
 *
 * global-error 只在**根布局本身**渲染失败时接管（error.tsx 之上的最后一层），
 * 此时 Nav/Footer 也不可用，所以这里必须自带 <html>/<body>。
 * 日常段级错误由 app/error.tsx 处理，不会走到这里。
 */

import { useEffect } from 'react';

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error('[global-error-boundary]', error);
  }, [error]);

  return (
    <html lang="zh-CN">
      <body className="min-h-screen flex items-center justify-center bg-canvas">
        <div className="max-w-md w-full mx-4 p-8 text-center rounded-lg border border-line bg-surface">
          <div className="text-4xl mb-4" aria-hidden>
            🛑
          </div>
          <h1 className="text-xl font-semibold mb-2 text-ink">应用暂时不可用</h1>
          <p className="text-sm mb-6 text-ink-muted">
            应用发生严重错误。请刷新页面；若持续出现，请稍后再试。
            {error.digest ? (
              <span className="block mt-2 text-xs text-ink-faint">
                错误标识：{error.digest}
              </span>
            ) : null}
          </p>
          <button type="button" className="btn-primary" onClick={reset}>
            刷新重试
          </button>
        </div>
      </body>
    </html>
  );
}
