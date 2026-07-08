# 前端设计令牌（Design Tokens）

> 配套文档：FRONTEND_SPEC.md §3、§11。本文档定义 Dashboard 的视觉设计令牌，供前端实现统一引用，确保视觉一致性。
>
> 适用阶段：V2（Next.js Dashboard 品牌色板）。**MVP 单页 HTML 使用 [FRONTEND_SPEC.md](FRONTEND_SPEC.md) §2 的色值**（主色 `#2563eb`、FARM `#16a34a`、WATCH `#d97706`、IGNORE `#6b7280`），与本文件语义一致、具体色值不同，MVP 不引用本文件。

---

## 1. 设计原则

1. **语义化命名**：令牌名表达用途，而非颜色值（如 `color-farm` 而非 `color-green-500`）。
2. **单一来源**：所有视觉属性从令牌派生，禁止硬编码色值/间距。
3. **主题支持**：MVP 仅亮色主题；V2 支持亮/暗双主题。
4. **无障碍**：所有颜色组合满足 WCAG AA 对比度（4.5:1 正文/3:1 大文本）。

---

## 2. 颜色系统

### 2.1 品牌色（Brand）

| 令牌 | 亮色值 | 暗色值（V2） | 用途 |
|---|---|---|---|
| `color-brand-primary` | `#6366F1` | `#818CF8` | 主色：按钮、链接、重点强调 |
| `color-brand-secondary` | `#8B5CF6` | `#A78BFA` | 辅助色：渐变、图表 |
| `color-brand-accent` | `#06B6D4` | `#22D3EE` | 强调色：高亮、提示 |

### 2.2 语义色（Semantic）

| 令牌 | 亮色值 | 暗色值（V2） | 用途 |
|---|---|---|---|
| `color-farm` | `#10B981` | `#34D399` | FARM label、正面信号 |
| `color-watch` | `#F59E0B` | `#FBBF24` | WATCH label、中性信号 |
| `color-ignore` | `#EF4444` | `#F87171` | IGNORE label、负面信号 |
| `color-success` | `#22C55E` | `#4ADE80` | 成功状态、健康指示 |
| `color-warning` | `#F59E0B` | `#FBBF24` | 警告状态、注意提示 |
| `color-error` | `#EF4444` | `#F87171` | 错误状态、危险操作 |
| `color-info` | `#3B82F6` | `#60A5FA` | 信息提示、帮助文本 |

### 2.3 中性色（Neutral）

| 令牌 | 亮色值 | 暗色值（V2） | 用途 |
|---|---|---|---|
| `color-bg-primary` | `#FFFFFF` | `#0F172A` | 主背景 |
| `color-bg-secondary` | `#F8FAFC` | `#1E293B` | 次背景：卡片、侧边栏 |
| `color-bg-tertiary` | `#F1F5F9` | `#334155` | 第三背景：输入框、分隔区 |
| `color-text-primary` | `#0F172A` | `#F8FAFC` | 主文本：标题、正文 |
| `color-text-secondary` | `#475569` | `#CBD5E1` | 次文本：描述、标签 |
| `color-text-tertiary` | `#94A3B8` | `#64748B` | 第三文本：占位符、禁用 |
| `color-border` | `#E2E8F0` | `#334155` | 边框、分隔线 |
| `color-border-strong` | `#CBD5E1` | `#475569` | 强调边框 |

### 2.4 数据可视化色（Data Viz）

| 令牌 | 值 | 用途 |
|---|---|---|
| `color-viz-1` | `#6366F1` | 图表主色 |
| `color-viz-2` | `#10B981` | 图表辅色 |
| `color-viz-3` | `#F59E0B` | 图表强调 |
| `color-viz-4` | `#EF4444` | 图表警示 |
| `color-viz-5` | `#8B5CF6` | 图表第五色 |
| `color-viz-6` | `#06B6D4` | 图表第六色 |
| `color-viz-7` | `#EC4899` | 图表第七色 |
| `color-viz-8` | `#14B8A6` | 图表第八色 |

---

## 3. 间距系统（Spacing）

### 3.1 基础单位
```
基础单位：4px
```

### 3.2 间距令牌

| 令牌 | 值 | 用途 |
|---|---|---|
| `space-1` | `4px` | 图标与文字间距、紧凑内边距 |
| `space-2` | `8px` | 表单项间距、按钮内边距 |
| `space-3` | `12px` | 卡片内边距、列表项间距 |
| `space-4` | `16px` | 默认内边距、段落间距 |
| `space-5` | `20px` | 区块间距、表单分组 |
| `space-6` | `24px` | 卡片间距、区块分隔 |
| `space-8` | `32px` | 大区块间距、页面分区 |
| `space-10` | `40px` | 页面级间距 |
| `space-12` | `48px` | 大分区间距 |
| `space-16` | `64px` | 页面顶部/底部留白 |

### 3.3 布局间距

| 令牌 | 值 | 用途 |
|---|---|---|
| `layout-page-padding` | `24px` | 页面水平内边距（桌面） |
| `layout-page-padding-mobile` | `16px` | 页面水平内边距（移动） |
| `layout-section-gap` | `32px` | 页面区块间距 |
| `layout-card-gap` | `16px` | 卡片网格间距 |
| `layout-sidebar-width` | `240px` | 侧边栏宽度 |
| `layout-header-height` | `64px` | 顶部导航高度 |

---

## 4. 字体系统（Typography）

### 4.1 字体族

| 令牌 | 值 | 用途 |
|---|---|---|
| `font-family-sans` | `'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif` | 主字体 |
| `font-family-mono` | `'JetBrains Mono', 'Fira Code', monospace` | 代码、数据 |

### 4.2 字号

| 令牌 | 值 | 行高 | 用途 |
|---|---|---|---|
| `font-size-xs` | `12px` | `16px` | 辅助文本、标签 |
| `font-size-sm` | `14px` | `20px` | 次文本、描述 |
| `font-size-base` | `16px` | `24px` | 正文、输入 |
| `font-size-lg` | `18px` | `28px` | 大文本、副标题 |
| `font-size-xl` | `20px` | `28px` | 标题 H4 |
| `font-size-2xl` | `24px` | `32px` | 标题 H3 |
| `font-size-3xl` | `30px` | `36px` | 标题 H2 |
| `font-size-4xl` | `36px` | `40px` | 标题 H1 |
| `font-size-5xl` | `48px` | `1` | 展示数字（score） |

### 4.3 字重

| 令牌 | 值 | 用途 |
|---|---|---|
| `font-weight-normal` | `400` | 正文 |
| `font-weight-medium` | `500` | 强调、按钮 |
| `font-weight-semibold` | `600` | 副标题、label |
| `font-weight-bold` | `700` | 标题、重点 |

---

## 5. 圆角系统（Border Radius）

| 令牌 | 值 | 用途 |
|---|---|---|
| `radius-none` | `0px` | 无圆角 |
| `radius-sm` | `4px` | 小元素：标签、徽章 |
| `radius-md` | `6px` | 按钮、输入框 |
| `radius-lg` | `8px` | 卡片、模态框 |
| `radius-xl` | `12px` | 大卡片、浮层 |
| `radius-2xl` | `16px` | 特大容器 |
| `radius-full` | `9999px` | 圆形：头像、按钮 |

---

## 6. 阴影系统（Shadow）

| 令牌 | 值 | 用途 |
|---|---|---|
| `shadow-sm` | `0 1px 2px rgba(0,0,0,0.05)` | 微阴影：输入框聚焦 |
| `shadow-md` | `0 4px 6px -1px rgba(0,0,0,0.1)` | 默认阴影：卡片 |
| `shadow-lg` | `0 10px 15px -3px rgba(0,0,0,0.1)` | 悬浮阴影：下拉菜单 |
| `shadow-xl` | `0 20px 25px -5px rgba(0,0,0,0.1)` | 大阴影：模态框 |
| `shadow-2xl` | `0 25px 50px -12px rgba(0,0,0,0.25)` | 最深阴影：抽屉 |

---

## 7. 动效系统（Motion）

### 7.1 时长

| 令牌 | 值 | 用途 |
|---|---|---|
| `duration-fast` | `150ms` | 微交互：按钮 hover、颜色变化 |
| `duration-normal` | `250ms` | 常规过渡：展开、折叠 |
| `duration-slow` | `350ms` | 复杂动画：模态框、抽屉 |

### 7.2 缓动函数

| 令牌 | 值 | 用途 |
|---|---|---|
| `ease-default` | `cubic-bezier(0.4, 0, 0.2, 1)` | 默认缓动 |
| `ease-in` | `cubic-bezier(0.4, 0, 1, 1)` | 进入动画 |
| `ease-out` | `cubic-bezier(0, 0, 0.2, 1)` | 退出动画 |
| `ease-in-out` | `cubic-bezier(0.4, 0, 0.2, 1)` | 双向动画 |

---

## 8. 断点系统（Breakpoints）

| 令牌 | 值 | 用途 |
|---|---|---|
| `breakpoint-sm` | `640px` | 大屏手机 |
| `breakpoint-md` | `768px` | 平板 |
| `breakpoint-lg` | `1024px` | 小桌面 |
| `breakpoint-xl` | `1280px` | 桌面 |
| `breakpoint-2xl` | `1536px` | 大桌面 |

---

## 9. Z-Index 系统

| 令牌 | 值 | 用途 |
|---|---|---|
| `z-base` | `0` | 基础层 |
| `z-dropdown` | `1000` | 下拉菜单、选择器 |
| `z-sticky` | `1100` | 粘性头部 |
| `z-fixed` | `1200` | 固定元素 |
| `z-modal-backdrop` | `1300` | 模态框背景 |
| `z-modal` | `1400` | 模态框内容 |
| `z-popover` | `1500` | 弹出层、工具提示 |
| `z-toast` | `1600` | 通知提示 |
| `z-tooltip` | `1700` | 工具提示 |

---

## 10. 组件令牌映射

### 10.1 按钮（Button）

| 属性 | 令牌 |
|---|---|
| 主按钮背景 | `color-brand-primary` |
| 主按钮文字 | `#FFFFFF` |
| 次按钮背景 | `color-bg-primary` |
| 次按钮边框 | `color-border` |
| 危险按钮背景 | `color-error` |
| 按钮圆角 | `radius-md` |
| 按钮内边距 | `space-2 space-4` |
| 按钮字重 | `font-weight-medium` |
| 按钮过渡 | `duration-fast ease-default` |

### 10.2 卡片（Card）

| 属性 | 令牌 |
|---|---|
| 背景 | `color-bg-primary` |
| 边框 | `1px solid color-border` |
| 圆角 | `radius-lg` |
| 阴影 | `shadow-md` |
| 内边距 | `space-6` |
| 悬停阴影 | `shadow-lg` |

### 10.3 输入框（Input）

| 属性 | 令牌 |
|---|---|
| 背景 | `color-bg-primary` |
| 边框 | `1px solid color-border` |
| 聚焦边框 | `2px solid color-brand-primary` |
| 圆角 | `radius-md` |
| 内边距 | `space-2 space-3` |
| 占位符颜色 | `color-text-tertiary` |
| 错误边框 | `2px solid color-error` |

### 10.4 Badge（标签）

| 属性 | FARM | WATCH | IGNORE |
|---|---|---|---|
| 背景 | `color-farm/10%` | `color-watch/10%` | `color-ignore/10%` |
| 文字 | `color-farm` | `color-watch` | `color-ignore` |
| 圆角 | `radius-full` | `radius-full` | `radius-full` |
| 内边距 | `space-1 space-2` | `space-1 space-2` | `space-1 space-2` |
| 字重 | `font-weight-semibold` | `font-weight-semibold` | `font-weight-semibold` |

---

## 11. Tailwind 配置示例

```javascript
// tailwind.config.js
module.exports = {
  theme: {
    extend: {
      colors: {
        brand: {
          primary: '#6366F1',
          secondary: '#8B5CF6',
          accent: '#06B6D4',
        },
        farm: {
          DEFAULT: '#10B981',
          light: '#D1FAE5',
        },
        watch: {
          DEFAULT: '#F59E0B',
          light: '#FEF3C7',
        },
        ignore: {
          DEFAULT: '#EF4444',
          light: '#FEE2E2',
        },
      },
      fontFamily: {
        sans: ['Inter', '-apple-system', 'sans-serif'],
        mono: ['JetBrains Mono', 'monospace'],
      },
      spacing: {
        // 使用默认 4px 基准，无需自定义
      },
      borderRadius: {
        sm: '4px',
        md: '6px',
        lg: '8px',
        xl: '12px',
        '2xl': '16px',
      },
      boxShadow: {
        sm: '0 1px 2px rgba(0,0,0,0.05)',
        md: '0 4px 6px -1px rgba(0,0,0,0.1)',
        lg: '0 10px 15px -3px rgba(0,0,0,0.1)',
        xl: '0 20px 25px -5px rgba(0,0,0,0.1)',
      },
    },
  },
};
```

---

## 12. CSS 变量示例（V2 暗色主题）

```css
:root {
  /* 亮色主题（默认） */
  --color-bg-primary: #FFFFFF;
  --color-bg-secondary: #F8FAFC;
  --color-text-primary: #0F172A;
  --color-text-secondary: #475569;
  --color-border: #E2E8F0;
  --color-farm: #10B981;
  --color-watch: #F59E0B;
  --color-ignore: #EF4444;
}

[data-theme="dark"] {
  --color-bg-primary: #0F172A;
  --color-bg-secondary: #1E293B;
  --color-text-primary: #F8FAFC;
  --color-text-secondary: #CBD5E1;
  --color-border: #334155;
  --color-farm: #34D399;
  --color-watch: #FBBF24;
  --color-ignore: #F87171;
}
```

---

_文档版本：v1.0 · 配套 FRONTEND_SPEC.md · 实现阶段 Tailwind/CSS 直接引用。_
