'use client';

/**
 * 路由段错误边界（2026-11-13 审查 P1-1）。
 *
 * 此前 app/ 下没有任何 error.tsx —— 任一页面渲染期抛出未捕获异常会整站
 * 白屏。各页面对**请求失败**已有各自的降级处理（partialError 分区提示等），
 * 这里只兜"页面本身崩了"这一层。
 *
 * 注意：error.tsx 只包 app-main 内的内容（Nav/Footer 在 layout 里，不受
 * 段级错误影响），用户仍可导航离开。
 */

import { useEffect } from 'react';

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // 生产环境堆栈不会进响应体，只在这里留给控制台排障。
    console.error('[error-boundary]', error);
  }, [error]);

  return (
    <section
      role="alert"
      className="flex-1 flex items-center justify-center px-4 py-16"
    >
      <div className="card max-w-md w-full p-8 text-center">
        <div className="text-4xl mb-4" aria-hidden>
          ⚠️
        </div>
        <h1 className="text-xl font-semibold mb-2 text-ink">页面出错了</h1>
        <p className="text-sm mb-6 text-ink-muted">
          页面渲染时发生意外错误，数据本身不受影响。可以重试，或返回工作台。
          {error.digest ? (
            <span className="block mt-2 text-xs text-ink-faint">
              错误标识：{error.digest}
            </span>
          ) : null}
        </p>
        <div className="flex gap-3 justify-center">
          <button type="button" className="btn-primary" onClick={reset}>
            重试
          </button>
          <a className="btn-secondary" href="/">
            返回工作台
          </a>
        </div>
      </div>
    </section>
  );
}
