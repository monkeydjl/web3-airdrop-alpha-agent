# Skill：ADR 编写

## 目标
按项目模板编写新的架构决策记录（ADR），记录重要技术决策的背景、选项与后果，遵循 docs/adr/TEMPLATE.md。

## 适用场景
- 引入新技术/库（如 ORM、队列）
- 改变架构边界或并发模型
- 推翻/补充既有 ADR

## 输入要求
- 文件：`docs/adr/TEMPLATE.md`（模板）
- 文件：`docs/adr/README.md`（索引）
- 文件：`docs/adr/ADR_CROSS_REFERENCE.md`
- 信息：决策议题、候选方案、已选方案

## 执行步骤

### Step 1: 编号与命名
- 操作：取下一个编号，文件名 `docs/adr/ADR-0XX-<kebab-slug>.md`
- 验证：现有编号连续到 **ADR-016**（`ADR-016-llm-provider-round-robin.md`），
  新 ADR 应为 `ADR-017`；slug 简述决策主题，与既有编号不冲突

### Step 2: 套用模板
- 操作：复制 `docs/adr/TEMPLATE.md` 结构：状态 / 背景 / 决策驱动因素 / 选项 / 决策 / 后果 / 参考
- 验证：背景说明"为什么现在决策"，后果含正反两面

### Step 3: 交叉引用
- 操作：在文中引用相关 ADR（如 ADR-004、ADR-007），并在
  `docs/adr/ADR_CROSS_REFERENCE.md` 登记关系
- 验证：被取代的 ADR 标记为 `Superseded by ADR-0XX`

### Step 4: 登记索引
- 操作：在 `docs/adr/README.md` 增加条目，摘要一句话
- 验证：索引与文件一致。文档里的枚举值/事件标识**不要用反引号包裹**（本仓文档约定），
  链接要能过 Docs Link Check workflow

## 输出
- 文件：`docs/adr/ADR-0XX-<slug>.md`
- 文件：`docs/adr/README.md`（更新）
- 文件：`docs/adr/ADR_CROSS_REFERENCE.md`（更新）

## 检查清单
- [ ] 编号连续、文件名 kebab-case
- [ ] 含状态/背景/选项/决策/后果
- [ ] 引用了相关 ADR
- [ ] README 索引已登记
- [ ] 被取代 ADR 已标记

## 参考
- `docs/adr/TEMPLATE.md`
- `docs/adr/README.md`
- `docs/adr/ADR_CROSS_REFERENCE.md`
