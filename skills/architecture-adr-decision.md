# Skill：架构决策分析

## 目标
针对重大架构问题做技术选型与权衡分析，产出决策建议并可落地为 ADR（参考 documentation-adr-create）。

## 适用场景
- 评估技术栈演进（如 V2 Postgres/Next.js）
- 并发模型/调度方案选型
- 是否引入新中间件/组件

## 输入要求
- 文件：`docs/ENGINEERING_ROADMAP.md`（阶段与既定方向）
- 目录：`docs/adr/`（既有决策）
- 文件：`docs/decision_log.md`（决策流水，不是 `DESIGN_GAP_ANALYSIS.md` —— 那个文件不存在）
- 文件：`docs/SYSTEM_DIRECTION_CHANGE.md`（如议题涉及方向调整）
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
- 操作：调用 documentation-adr-create 编写 `docs/adr/ADR-0XX-<slug>.md`，
  同步 `docs/adr/README.md` 与 `docs/adr/ADR_CROSS_REFERENCE.md`
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
- [ ] 若决策把某个"尚未实现"变成"已实现"，同步检查
      `backend/tests/test_security_doc_parity.py` 的反向断言是否需要更新

## 参考
- `docs/ENGINEERING_ROADMAP.md`
- `docs/adr/`（含 `README.md` 与 `ADR_CROSS_REFERENCE.md`）
- `docs/decision_log.md`
- `skills/documentation-adr-create.md`
