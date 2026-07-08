# Skill：架构决策分析

## 目标
针对重大架构问题做技术选型与权衡分析，产出决策建议并可落地为 ADR（参考 documentation-adr-create）。

## 适用场景
- 评估技术栈演进（如 V2 Postgres/Next.js）
- 并发模型/调度方案选型
- 是否引入新中间件/组件

## 输入要求
- 文件：`docs/ENGINEERING_ROADMAP.md`
- 文件：`docs/adr/`（既有决策）
- 文件：`docs/DESIGN_GAP_ANALYSIS.md`（如适用）
- 信息：待决策议题、约束（性能/成本/团队）

## 执行步骤

### Step 1: 明确问题
- 操作：用一句话定义决策议题与驱动因素（性能/可维护性/成本）
- 验证：与路线图阶段（MVP→V2→V3）对齐

### Step 2: 枚举选项
- 操作：列出 2-3 个候选方案，各自优缺点、兼容性（是否与既有 ADR 冲突）
- 验证：每个方案标注对 `airdrop_*` 指标（§14）与规范的影响

### Step 3: 推荐与权衡
- 操作：给出推荐方案，说明取舍与回滚预案
- 验证：引用相关 ADR（如 ADR-004/007/009）做交叉印证

### Step 4: 落地 ADR
- 操作：调用 documentation-adr-create 编写 `ADR-0XX`，更新 README 与 CROSS_REFERENCE
- 验证：状态明确（Proposed/Accepted/Superseded）

## 输出
- 文件：决策分析文档（issue / docs 片段）
- 文件：`docs/adr/ADR-0XX-<slug>.md`（如采纳）

## 检查清单
- [ ] 议题与驱动因素清晰
- [ ] 枚举 ≥2 方案并对比
- [ ] 推荐方案含权衡与回滚
- [ ] 交叉引用相关 ADR
- [ ] 落地 ADR 并登记索引

## 参考
- `docs/ENGINEERING_ROADMAP.md`
- `docs/adr/`
- `docs/DESIGN_GAP_ANALYSIS.md`
- `skills/documentation-adr-create.md`
