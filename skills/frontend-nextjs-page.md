# Skill：Next.js 页面创建（V2）

## 目标
在 `frontend-next/` 创建新的 Next.js App Router 页面，遵循 CONVENTIONS.md §3.2 TypeScript 规范与 docs/FRONTEND_SPEC.md。

> 目录名注意：前端实际目录是 **`frontend-next/`**。仓库里不存在 `frontend/`，
> 照着旧路径写会创建一个不被构建的孤立目录。

## 适用场景
- 新增业务页面（项目列表、评分详情、反馈页）
- 新增 dashboard 路由
- 修改页面路由结构

## 输入要求
- 文件：`docs/FRONTEND_SPEC.md`（前端规范）
- 文件：`CONVENTIONS.md §3.2 TypeScript 命名约定`
- 参照现有页面：`frontend-next/app/discoveries/page.tsx`（筛选+列表+Toast 的完整样例）
- 信息：路由路径、需要的数据、调用的后端端点

## 执行步骤

### Step 1: 创建路由文件
- 操作：在 `frontend-next/app/<route>/page.tsx` 创建页面组件
- 验证：路由目录名**全小写单词**（现有全部如此：`ops`、`portfolio`、`discoveries`），
  动态段用方括号（`app/project/[id]/page.tsx`）；默认导出 `PascalCase` 且以 `Page` 结尾
  的函数（`export default function DiscoveriesPage()`）

### Step 2: 调用后端 API
- 操作：用 `frontend-next/lib/api.ts` 的 `apiFetch<T>(path, init?)`，`path` 相对
  `API_BASE`（默认 `/api/v1`）书写，如 `apiFetch<DiscoveriesResponse>('/discoveries?status=pending')`
- 验证：
  - query 参数与返回字段保持 `snake_case`，**不转 camelCase**（CONVENTIONS §3.4）
  - 响应类型写进 `frontend-next/lib/types.ts`，页面 `import type` 引用
  - **不要读 `NEXT_PUBLIC_API_KEY`**：鉴权由服务端 `proxy.ts` 注入 `X-API-Key`，
    `NEXT_PUBLIC_*` 会被内联进浏览器 bundle，等于把管理员密钥公开
  - 后端拥有的枚举（采集器列表、sector 等）必须现拉，不要在前端写死清单 ——
    写死的后果是「筛选不到」而不是报错，几乎不可能被发现

### Step 3: 渲染与状态
- 操作：页面首行 `'use client'`，用 `@/lib/useAsyncData` 的 `useAsyncData(loader, deps)`
  管理 loading/error/data 三态；`loader` 收到 `AbortSignal` 必须透传给 `apiFetch`
- 验证：
  - 手写 `useState` + `useEffect` 拉数据时，必须自己处理取消与代次守卫，
    否则慢的旧响应会覆盖新响应（连点刷新即可复现）——优先直接用 `useAsyncData`
  - 取消错误用 `isAbortError(err)` 静默忽略，不要当故障弹 Toast
  - 错误态展示后端 `{ "ok": false, "error": { code, message } }` 包络里的 message
  - 空态用 `@/components/ui` 的 `EmptyState`，提示语用中文
- 说明：文案一律中文；中文文案**不要**套 `is-mono` / `font-mono`（等宽字体渲染中文会错位）。
  配色用 Tailwind 语义类（`text-ink`、`bg-surface-3`、`text-farm`），不要写死十六进制

### Step 4: 验证
- 操作：在 `frontend-next/` 下依次跑
  `npm run lint`、`npm run typecheck`、`npm run test`、`npm run build`
- 说明：前端测试入口是 `frontend-next/test.mjs`（在单进程内 `import` 各测试文件，
  刻意不用 `node --test`，因为沙箱下 spawn 子进程会 EPERM）。项目**没有安装
  React Testing Library、jest、vitest，也没有覆盖率工具** —— 不要引入这些依赖，
  也不要新建 `__tests__/` 目录写 `.test.tsx`。页面级组件当前没有渲染测试，
  可测逻辑请抽成纯函数放进 `lib/`，写同目录的 `*.test.ts`（参照 `lib/download.test.ts`），
  并在 `test.mjs` 的 `FILES` 数组里补一行（显式列表是有意的：漏注册会一眼看见）
- 验证：四条命令全绿。build 若报内存或参数异常，用 `NODE_OPTIONS="" npm run build`

## 输出
- 文件：`frontend-next/app/<route>/page.tsx`
- 文件：`frontend-next/lib/api.ts`（如新增封装）
- 文件：`frontend-next/lib/types.ts`（新增响应类型）
- 文件（可选）：`frontend-next/lib/<name>.test.ts` + 在 `test.mjs` 注册

## 检查清单
- [ ] 路径在 `frontend-next/` 下，不是 `frontend/`
- [ ] 路由目录全小写，组件为 `PascalCase` + `Page` 后缀
- [ ] API 调用走 `apiFetch`，参数/字段保持 `snake_case`
- [ ] 未引用 `NEXT_PUBLIC_API_KEY`，未在前端写死后端枚举
- [ ] loading / error / empty 三态齐全，取消错误被忽略
- [ ] 中文文案未套等宽字体类，配色走语义类
- [ ] lint / typecheck / test / build 四项全绿

## 参考
- `CONVENTIONS.md §3.2 TypeScript 命名约定`
- `docs/FRONTEND_SPEC.md`
- `frontend-next/lib/useAsyncData.ts`（取消 + 代次守卫的原因写在文件注释里）
- Next.js App Router 官方文档
