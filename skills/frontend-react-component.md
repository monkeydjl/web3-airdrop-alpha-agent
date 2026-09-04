# Skill：React 组件创建

## 目标
在 `frontend-next/components/` 下创建可复用的 React 组件（卡片、图表、面板），遵循 CONVENTIONS.md §3.2 与 docs/DESIGN_TOKENS.md。

## 适用场景
- 新增展示组件（ProjectCard、FundingPanel）
- 新增数据可视化组件（见 ADR-011 图表库选型，实际用 Chart.js + react-chartjs-2）
- 新增表单/输入组件（InteractionPanel、RoiLedger）

## 输入要求
- 文件：`docs/DESIGN_TOKENS.md`（设计令牌）
- 文件：`docs/FRONTEND_SPEC.md`
- 文件：`frontend-next/lib/types.ts`（后端数据模型的前端类型）
- 信息：组件需要哪些数据、数据来源是哪个端点

## 执行步骤

### Step 1: 标注 props 类型
- 操作：在 `frontend-next/components/<Name>.tsx` 内联标注 props，数据模型从 `@/lib/types` 导入
- 说明：本项目**不写独立的 Props 接口**。现有组件一律内联解构，例如
  `export function ProjectCard({ project, rank }: { project: Project; rank?: number })`
- 验证：后端返回的字段**保持 snake_case 原样**（funding_tier、funding_total_usd），
  不要改写成 camelCase —— 前后端字段名一致是 CONVENTIONS §3.4 的硬要求，
  而且有后端 parity 门禁钉住

### Step 2: 实现组件
- 操作：函数组件 + 解构 props。用到 hooks、事件或浏览器 API 时首行加 `'use client'`
- 样式：只用 Tailwind 语义类（text-ink、text-ink-muted、bg-surface-3、text-farm 等），
  不要写死十六进制颜色。中文文案**不要套 is-mono / font-mono**，那是给英文与数字标识用的
- 验证：纯展示组件无副作用；取数下沉到页面层

### Step 3: 引用与复用
- 操作：跨目录用路径别名 `@/components/<Name>`，同目录用相对路径（`./ui`）
- 说明：**没有 components/index.ts 桶文件，也不要新建**。现有组件都是具名导出、按需直接引入
- 验证：改动后 typecheck 能解析全部 import

### Step 4: 验证
- 操作：在 `frontend-next/` 下依次跑
  `npm run lint`、`npm run typecheck`、`npm run test`、`npm run build`
- 说明：前端测试入口是 `frontend-next/test.mjs`（Node 原生 test runner）。
  项目**没有安装 React Testing Library、jest、vitest，也没有覆盖率工具** ——
  不要引入这些依赖，也不要新建 `__tests__/` 目录写 .test.tsx
- 验证：四条命令全绿。build 若报内存或参数异常，用 `NODE_OPTIONS="" npm run build`
