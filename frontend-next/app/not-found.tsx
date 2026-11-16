/**
 * 全局 404 页（2026-11-13 审查 P1-1）。
 *
 * 此前深链到不存在的路径会走 Next 默认英文 404，与全站 zh-CN 不一致。
 */

import Link from 'next/link';

export default function NotFound() {
  return (
    <main className="flex-1 flex items-center justify-center px-4 py-16">
      <div className="card max-w-md w-full p-8 text-center">
        <div className="text-4xl mb-4" aria-hidden>
          🧭
        </div>
        <h1 className="text-xl font-semibold mb-2 text-ink">页面不存在</h1>
        <p className="text-sm mb-6 text-ink-muted">
          你访问的地址不存在或已被移动。项目可能已进入归档 —— 去归档页找找？
        </p>
        <div className="flex gap-3 justify-center">
          <Link className="btn-primary" href="/">
            返回工作台
          </Link>
          <Link className="btn-secondary" href="/archive">
            查看归档
          </Link>
        </div>
      </div>
    </main>
  );
}
