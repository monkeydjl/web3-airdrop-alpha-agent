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
            <main className="flex-1">{children}</main>
            <footer className="app-footer">
              <span>空投阿尔法 · Web3 空投 Alpha 识别与决策支持</span>
              <span>数据不构成投资建议 · score-v1.4</span>
            </footer>
          </div>
        </ThemeProvider>
      </body>
    </html>
  );
}
