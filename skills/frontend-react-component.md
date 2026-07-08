# Skill：React 组件创建（V2）

## 目标
为 V2 前端创建可复用的 React 组件（卡片、图表、表格），遵循 CONVENTIONS.md §3.2 与 docs/DESIGN_TOKENS.md。

## 适用场景
- 新增展示组件（ProjectCard、StatCard）
- 新增数据可视化组件（评分图，参考 ADR-011 图表库）
- 新增表单/输入组件

## 输入要求
- 文件：`docs/DESIGN_TOKENS.md`（设计令牌）
- 文件：`docs/FRONTEND_SPEC.md`
- 信息：组件 props 结构、数据来源

## 执行步骤

### Step 1: 定义 Props 接口
- 操作：在 `frontend/components/<Name>.tsx` 定义 `interface <Name>Props`
- 验证：接口 `PascalCase`，字段 `camelCase`，可选字段加 `?`

### Step 2: 实现组件
- 操作：使用函数组件 + 解构 props；样式引用 `docs/DESIGN_TOKENS.md` 令牌（颜色/间距）
- 验证：纯展示组件无副作用；数据获取下沉到页面层

### Step 3: 导出与复用
- 操作：在 `frontend/components/index.ts` 统一导出
- 验证：组件可被多页面 import 复用

### Step 4: 添加测试
- 操作：在 `frontend/__tests__/components/<Name>.test.tsx` 用 RTL 测试渲染与交互
- 验证：覆盖率 ≥ 80%，边界 props 已测

## 输出
- 文件：`frontend/components/<Name>.tsx`
- 文件：`frontend/components/index.ts`（更新）
- 文件：`frontend/__tests__/components/<Name>.test.tsx`

## 检查清单
- [ ] 组件函数 `PascalCase`，Props 接口 `PascalCase`
- [ ] 字段 `camelCase`，可选字段显式 `?`
- [ ] 使用 DESIGN_TOKENS.md 设计令牌
- [ ] 无内联硬编码魔数样式
- [ ] 测试覆盖率 ≥ 80%

## 参考
- `CONVENTIONS.md §3.2 TypeScript 命名约定`
- `docs/DESIGN_TOKENS.md`
- `docs/adr/ADR-011-mvp-chart-library.md`
