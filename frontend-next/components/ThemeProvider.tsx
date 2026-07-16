'use client';

import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';

type Theme = 'light' | 'dark';

const ThemeCtx = createContext<{ theme: Theme; toggle: () => void }>({
  theme: 'light',
  toggle: () => {},
});

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<Theme>('light');
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const stored = (localStorage.getItem('aa-theme') as Theme | null) || null;
    const preferred =
      stored ||
      (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    setTheme(preferred);
    document.documentElement.classList.toggle('dark', preferred === 'dark');
    setReady(true);
  }, []);

  const toggle = () => {
    setTheme((t) => {
      const next = t === 'dark' ? 'light' : 'dark';
      localStorage.setItem('aa-theme', next);
      document.documentElement.classList.toggle('dark', next === 'dark');
      return next;
    });
  };

  if (!ready) {
    return <div className="min-h-screen bg-canvas">{children}</div>;
  }

  return <ThemeCtx.Provider value={{ theme, toggle }}>{children}</ThemeCtx.Provider>;
}

export function useTheme() {
  return useContext(ThemeCtx);
}
