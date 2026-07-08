# FAQ — 常见问题

> 引用键：`KN:faq`
> 更新：2026-07-08

## 产品相关

### Q: 如何判断一个项目是否值得 FARM？
A: 见 `docs/DATA_SCORING_DICT.md` §4 评分算法。系统从 6 个维度评估：空投信号、赛道时机、团队信誉、风险、代币经济、竞争度。

### Q: 系统如何处理缺失数据？
A: 见 `docs/ENGINEERING_ROADMAP.md` §7.6 缺失降级策略。缺失字段 ≥ 3 时 confidence < 0.5，label 强制降一档。

### Q: LLM 集成如何工作？
A: 见 `docs/ENGINEERING_ROADMAP.md` §19。MVP 默认关闭 LLM（ADR-001），设置 `OPENAI_API_KEY` 后自动启用，失败自动回退规则引擎。

## 开发相关

### Q: 如何添加新数据源？
A: 见 `docs/ENGINEERING_ROADMAP.md` §10，实现 fetcher + 容错矩阵。

### Q: 如何贡献代码？
A: 见 `CONTRIBUTING.md` 和 `CONVENTIONS.md §11` Git 规范。

### Q: 遇到 Bug 怎么办？
A: 使用 `.github/ISSUE_TEMPLATE/bug_report.md` 提交 Issue。

### Q: 如何部署到生产？
A: 见 `docs/DEPLOYMENT.md`。

## 技术相关

### Q: 为什么选择 SQLite 而不是 PostgreSQL？
A: MVP 阶段零运维启动（ADR-004）。满足 4 个触发条件后迁移到 PostgreSQL。

### Q: 评分权重可以调整吗？
A: MVP 阶段权重冻结（ADR-006），V2 通过灰度 + 用户反馈校准。

### Q: 系统如何保证并发安全？
A: 三级并发模型（ADR-007）：项目级 Semaphore、Agent 级 gather、子调用独立 Semaphore。

---

_文档版本：v1.0 · 2026-07-08_
