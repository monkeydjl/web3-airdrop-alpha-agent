import type { Metadata } from 'next';
import './globals.css';
import { Nav } from '@/components/Nav';
import { ThemeProvider } from '@/components/ThemeProvider';

export const metadata: Metadata = {
  title: '空投阿尔法 · 早期项目雷达',
  description: 'Web3 早期项目自动发现、多维评分与空投决策系统',
};

// 首帧前同步应用主题，消除 dark 模式用户的白屏闪烁（FOUC）。
const themeInitScript = `(function(){try{var t=localStorage.getItem('aa-theme');if(!t){t=window.matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light';}if(t==='dark'){document.documentElement.classList.add('dark');}}catch(e){}})();`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeInitScript }} />
      </head>
      <body className="min-h-screen">
        <ThemeProvider>
          <Nav />
          <div className="app-main">
            <main className="mx-auto max-w-7xl px-4 py-6 sm:px-6 sm:py-8">{children}</main>
            <footer className="mx-auto max-w-7xl px-4 pb-10 pt-2 text-center text-[11px] text-ink-faint sm:px-6">
              空投阿尔法 · 输出仅供研究参考，不构成投资建议
            </footer>
          </div>
        </ThemeProvider>
      </body>
    </html>
  );
}
