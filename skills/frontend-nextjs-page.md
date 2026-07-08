# Skill：Next.js 页面创建（V2）

## 目标
为 V2 前端创建新的 Next.js App Router 页面，遵循 CONVENTIONS.md §3.2 TypeScript 规范与 docs/FRONTEND_SPEC.md。

## 适用场景
- 新增业务页面（项目列表、评分详情、反馈页）
- 新增 dashboard 路由
- 修改页面路由结构

## 输入要求
- 文件：`docs/FRONTEND_SPEC.md`（前端规范）
- 文件：`CONVENTIONS.md §3.2 TypeScript 命名约定`
- 信息：路由路径、需要的数据、调用的后端端点

## 执行步骤

### Step 1: 创建路由文件
- 操作：在 `frontend/app/<route>/page.tsx` 创建页面组件
- 验证：目录名 `snake_case`，页面默认导出 `PascalCase` 函数组件

### Step 2: 调用后端 API
- 操作：在 `frontend/lib/api.ts` 封装 `fetch`（指向 `/api/v1/...`），页面内 `await` 调用
- 验证：使用 `snake_case` query 参数，JSON 字段不转换 camelCase（见 CONVENTIONS §3.4）

### Step 3: 渲染与状态
- 操作：使用 React Server Component 或 `"use client"` 组件管理加载/错误态
- 验证：错误态展示后端 `{ "ok": false, "error": ... }` 包络信息

### Step 4: 添加组件测试
- 操作：在 `frontend/__tests__/page.test.tsx` 用 React Testing Library 测试渲染
- 验证：mock `fetch`，覆盖 loading / data / error 三态

## 输出
- 文件：`frontend/app/<route>/page.tsx`
- 文件：`frontend/lib/api.ts`（如新增封装）
- 文件：`frontend/__tests__/page.test.tsx`

## 检查清单
- [ ] 文件名为 `PascalCase`/`snake_case` 目录
- [ ] 组件函数 `PascalCase`，含 docstring
- [ ] API 调用使用 `snake_case` 参数
- [ ] 处理了 loading / error 状态
- [ ] 测试覆盖三态，无未使用变量

## 参考
- `CONVENTIONS.md §3.2 TypeScript 命名约定`
- `docs/FRONTEND_SPEC.md`
- Next.js App Router 官方文档
