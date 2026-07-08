# Pull Request 模板

> Web3 Airdrop Alpha Agent System

## 描述

请简要描述本次 PR 的内容：

- **类型**：`feat` / `fix` / `docs` / `refactor` / `test` / `chore` / `perf`
- **关联 Issue**：Closes #
- **对应 ADR**：（如有）ADR-0xx

## 变更清单

- [ ] 新增功能 / 修复 / 文档变更列表

## 自查清单

提交前请确认：

### 代码质量
- [ ] 所有新代码有对应的测试（单元/契约/golden/API）
- [ ] 本地测试通过：`pytest -q --cov` 全绿
- [ ] lint 通过：`ruff check .` + `ruff format --check .`
- [ ] 无 `print()` / `input()` / 调试断点残留
- [ ] 行覆盖率 ≥ 80%（关键模块 ≥ 90%）

### 文档与配置
- [ ] Pydantic 模型变更时同步更新了契约测试
- [ ] API 变更时同步更新了 `API_SPEC.md`
- [ ] 环境变量变更时同步更新了 `.env.example`
- [ ] 新增外部依赖时同步更新 `requirements.txt` + `.lock.txt`
- [ ] `AgentError.kind` 新增枚举时同步更新了文档

### 架构与兼容
- [ ] 本变更向后兼容（同一 API 版本内）
- [ ] 如需 breaking change，已更新 API 版本或走弃用流程
- [ ] 日志事件名遵循 `层级.动词过去式` 格式
- [ ] 指标命名遵循 `airdrop_*` 前缀规范

### 安全
- [ ] 无密钥/Token 硬编码或泄漏风险
- [ ] SQL 查询使用参数化（`?` 占位符）
- [ ] 输入校验通过 Pydantic 模型

## 关联文档

- [ ] 已更新 `ENGINEERING_ROADMAP.md` 对应章节
- [ ] 已更新 `CHANGELOG.md` / `DESIGN_REVIEW_CHANGELOG.md`
- [ ] （如涉及架构决策）已创建或更新 ADR

## 截图 / 日志 / 性能数据

<!-- 如有 UI 变更请附截图；性能优化请附 benchmark 数据 -->

## 测试说明

<!-- 描述如何验证本变更：手动操作、curl 命令、pytest 运行等 -->

---

_提交 PR 即代表您已阅读并同意 [CONVENTIONS.md](../CONVENTIONS.md) 中的编码规范。_
