# Skill：代码重构

## 目标
在不改变外部行为的前提下重构代码，提升可读性与可维护性，遵循 CONVENTIONS.md 与单 PR 单一职责（§11.3）。

## 适用场景
- 消除重复逻辑
- 拆分过长函数/模块
- 改善命名与结构

## 输入要求
- 文件：`backend/app/`（待重构模块）
- 文件：`CONVENTIONS.md §3 命名 / §6 代码风格`
- 文件：对应测试（`tests/` 镜像结构）
- 信息：重构范围与动机

## 执行步骤

### Step 1: 锁定行为基线
- 操作：先确保 `pytest -q --cov` 全绿，记录当前覆盖率
- 验证：golden 测试 `tests/golden/test_golden.py` 通过，作为行为契约

### Step 2: 小步重构
- 操作：按 CONVENTIONS 重命名（snake_case/PascalCase）、提取函数、消除重复
- 验证：每步提交后跑测试；不改 Pydantic 模型字段语义（否则同步契约测试）

### Step 3: 保持规范
- 操作：`ruff check .` + `ruff format --check .` + `mypy . --strict` 全过
- 验证：无 `print()`/调试残留；日志键名不变（§10.2）

### Step 4: 验证等价
- 操作：重跑 `tests/golden` 与 `tests/api`，覆盖率不下降
- 验证：覆盖率下降 >3% 触发告警（§9.5）

## 输出
- 文件：`backend/app/<module>.py`（重构）
- 文件：对应 `tests/` 测试（如有调整）

## 检查清单
- [ ] 重构前测试全绿且 golden 通过
- [ ] 单 PR 仅含重构（无功能变更）
- [ ] ruff + mypy 全过
- [ ] 覆盖率不下降
- [ ] 日志键名/模型语义未变

## 参考
- `CONVENTIONS.md §3 命名 / §6 风格 / §11.3 变更原则`
- `tests/golden/`
- `tests/`
