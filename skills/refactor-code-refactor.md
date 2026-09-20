# Skill：代码重构

## 目标
在不改变外部行为的前提下重构代码，提升可读性与可维护性，遵循 CONVENTIONS.md 与单 PR 单一职责（§11.3）。

## 适用场景
- 消除重复逻辑
- 拆分过长函数/模块
- 改善命名与结构

## 输入要求
- 目录：`backend/app/`（待重构模块）
- 文件：`CONVENTIONS.md §3 命名 / §6 代码风格 / §11.3 变更原则`
- 目录：`backend/tests/`（测试；**不是**仓库根的 `tests/`，那个目录不存在）
- 信息：重构范围与动机

## 执行步骤

### Step 1: 锁定行为基线
- 操作：先跑通全套测试并记下覆盖率
  ```bash
  cd backend && ./venv/Scripts/python.exe -m pytest tests -q -p no:cacheprovider
  ```
- 验证：`backend/tests/golden/test_golden_cases.py` 通过 —— golden 是行为契约，
  它一变就说明不是重构而是改行为
- 说明：**collection error + 秒级失败 + 无覆盖率产物 = 环境或依赖问题**，
  这种情况先查依赖版本锁，不要以为是自己的改动

### Step 2: 小步重构
- 操作：按 CONVENTIONS 重命名（`snake_case` / `PascalCase`）、提取函数、消除重复
- 验证：
  - 每步跑一次测试再继续
  - 不改 Pydantic 模型字段语义；字段名保持 `snake_case`（前端直接消费原样字段，
    改名会静默打断前端）
  - 日志/事件名不要顺手改（`§10.2`）：事件名是可观测性契约，且有文档对账测试盯着；
    调用点必须保留字面量，不要抽成变量拼接，否则搜索器与门禁都会失效

### Step 3: 保持规范（按 CI 的口径）
- 操作：在 `backend/` 目录下跑
  ```bash
  ./venv/Scripts/python.exe -m ruff check .
  ./venv/Scripts/python.exe -m ruff format --check .
  ./venv/Scripts/python.exe -m mypy app --config-file pyproject.toml
  ```
- 验证：
  - **ruff 跑全目录**，不是只跑改动文件（CI 就是 `ruff check .`）
  - **mypy 只跑 `app`，不跑 `tests`**（CI 第 223 行如此），所以测试里的类型问题
    不会被 CI 拦住 —— 别因此在测试里放宽真实代码的类型
  - `ruff check` 不要把 `.txt` 之类非 Python 文件传进去（会被当 Python 解析而报一堆错）
  - 无 `print()` / 调试残留；清理动作套 `contextlib.suppress`；避免裸属性表达式（B018）

### Step 4: 验证等价
- 操作：重跑 `backend/tests/golden/` 与 `backend/tests/api/`，比对覆盖率
- 验证：覆盖率不低于 80%（CI `--cov-fail-under=80`）；下降 >3% 触发告警（§9.5）

## 输出
- 文件：`backend/app/<module>.py`（重构）
- 文件：`backend/tests/**`（如有调整）

## 检查清单
- [ ] 重构前测试全绿且 golden 通过
- [ ] 单 PR 仅含重构（无功能变更）
- [ ] `ruff check .` / `ruff format --check .` 全目录通过
- [ ] `mypy app --config-file pyproject.toml` 通过
- [ ] 覆盖率不下降，仍 ≥80%
- [ ] 日志/事件名与 Pydantic 字段语义未变

## 参考
- `CONVENTIONS.md §3 命名 / §6 风格 / §11.3 变更原则`
- `backend/tests/golden/test_golden_cases.py`
- `.github/workflows/ci.yml`（lint 与 mypy 的准确命令）
- `skills/deployment-ci-pipeline.md`
