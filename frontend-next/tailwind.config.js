/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: 'class',
  content: [
    './app/**/*.{js,ts,jsx,tsx,mdx}',
    './components/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      colors: {
        brand: {
          50: '#eef2ff',
          100: '#e0e7ff',
          200: '#c7d2fe',
          300: '#a5b4fc',
          400: '#818cf8',
          500: '#6366f1',
          600: '#4f46e5',
          700: '#4338ca',
          800: '#3730a3',
          900: '#312e81',
        },
        farm: { DEFAULT: '#10b981', soft: '#d1fae5', dark: '#059669' },
        watch: { DEFAULT: '#f59e0b', soft: '#fef3c7', dark: '#d97706' },
        ignore: { DEFAULT: '#64748b', soft: '#f1f5f9', dark: '#475569' },
        surface: {
          DEFAULT: 'rgb(var(--surface) / <alpha-value>)',
          2: 'rgb(var(--surface-2) / <alpha-value>)',
          3: 'rgb(var(--surface-3) / <alpha-value>)',
        },
        ink: {
          DEFAULT: 'rgb(var(--ink) / <alpha-value>)',
          muted: 'rgb(var(--ink-muted) / <alpha-value>)',
          faint: 'rgb(var(--ink-faint) / <alpha-value>)',
        },
        line: 'rgb(var(--line) / <alpha-value>)',
        canvas: 'rgb(var(--canvas) / <alpha-value>)',
      },
      fontFamily: {
        sans: [
          'var(--font-geist)',
          'ui-sans-serif',
          'system-ui',
          '-apple-system',
          'Segoe UI',
          'PingFang SC',
          'Microsoft YaHei',
          'sans-serif',
        ],
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'Consolas', 'monospace'],
      },
      boxShadow: {
        card: '0 1px 2px rgb(0 0 0 / 0.04), 0 4px 16px rgb(0 0 0 / 0.04)',
        lift: '0 8px 30px rgb(0 0 0 / 0.08)',
        glow: '0 0 0 1px rgb(99 102 241 / 0.15), 0 8px 24px rgb(99 102 241 / 0.12)',
      },
      borderRadius: {
        xl: '0.875rem',
        '2xl': '1.125rem',
      },
      animation: {
        'fade-in': 'fadeIn 0.35s ease-out',
        'slide-up': 'slideUp 0.4s ease-out',
        'pulse-soft': 'pulseSoft 2s ease-in-out infinite',
      },
      keyframes: {
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        slideUp: {
          '0%': { opacity: '0', transform: 'translateY(8px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        pulseSoft: {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.55' },
        },
      },
    },
  },
  plugins: [],
};
