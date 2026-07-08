# Decision Log

> 记录项目中所有关键决策，包括技术选型、范围变更、风险应对等。
> 与 ADR 的区别：ADR 用于架构级决策；Decision Log 用于日常项目决策。

---

## 模板

### DEC-XXX — <决策标题>

- **日期**：YYYY-MM-DD
- **决策人**：
- **背景**：
- **决策**：
- **备选方案**：
- **影响**：
- **相关文档 / ADR**：
- **状态**：Proposed / Accepted / Rejected / Superseded

---

## 决策记录

### DEC-001 — 示例决策

- **日期**：2026-07-08
- **决策人**：Tech Lead
- **背景**：需要选择项目文档组织方式
- **决策**：采用 docs-as-code，所有设计文档放入 `docs/`，并通过编号索引管理
- **备选方案**：使用外部 Wiki（Notion / iWiki）
- **影响**：版本控制与代码同步，便于 AI Agent 读取
- **相关文档 / ADR**：`docs/00_index.md`
- **状态**：Accepted

---

_文档版本：v1.0 · 2026-07-08_
