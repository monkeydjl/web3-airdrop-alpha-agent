# Skill：CI 流水线配置

## 目标
配置/维护 GitHub Actions CI 流水线，覆盖 lint、type-check、测试、安全扫描与构建，遵循 CONVENTIONS.md §16。

## 适用场景
- 修改 `.github/workflows/ci.yml`
- 新增测试/覆盖率门禁
- 接入部署前校验

## 输入要求
- 文件：`.github/workflows/ci.yml`
- 文件：`.github/workflows/security.yml`
- 文件：`pyproject.toml`（ruff/mypy/pytest 配置）
- 文件：`CONVENTIONS.md §16 代码审查清单`

## 执行步骤

### Step 1: Lint 与格式
- 操作：在 `ci.yml` 添加 `ruff check .` 与 `ruff format --check .` 步骤
- 验证：使用 `pyproject.toml` 中 `line-length=120` 配置

### Step 2: 类型与测试
- 操作：添加 `mypy app --config-file pyproject.toml` 与 `pytest -q --cov` 步骤；覆盖率门禁 ≥ 80%
- 验证：关键模块（agents/scorer/orchestrator/db）覆盖率 ≥ 90%
- ⚠️ 不是 `mypy . --strict`：CI 的 `working-directory` 是 `backend`，扫的是 `app`（132 文件）。
  写 `mypy .` 会连 `scripts/` 一起扫出上百个既有错误，与 CI 结果不一致

### Step 3: 安全门禁
- 操作：触发 `security.yml`（gitleaks + bandit `S` 规则），设为 required check
- 验证：密钥扫描失败阻断合并

### Step 4: 构建校验
- 操作：添加 `docker build` 冒烟（可选 matrix 含前端 V2）
- 验证：镜像构建成功，非 root 运行

## 本地按 CI 口径复核（提交前必做）

CI 的 lint/type 两个 job 都以 **`backend/` 为工作目录**。本地必须复现这个 cwd，
否则配置解析与扫描范围都会偏，出现「本地绿 CI 红」。

```bash
cd backend
./venv/Scripts/python.exe -m ruff check .            # 期望 All checks passed
./venv/Scripts/python.exe -m ruff format --check .   # 期望 N files already formatted
./venv/Scripts/python.exe -m mypy app                # 期望 Success: no issues found
```

三个反直觉点（都是实测踩过的）：

1. **不要用 `git diff --name-only <base>` 挑文件跑 lint**。在栈式分支
   （`master ← fix/x ← docs/y ← feat/m1 ← feat/m2`）上，下层分支引入的 lint 债
   不在当前 diff 里，会连漏几轮。实例：`0005/0006` 的 E402+F401 是 M1 分支引入的，
   以 `feat/action-loop-m1` 为 base 的 diff 完全看不到，而 CI 扫 backend 全目录照旧红。
   **省时的增量检查只适合快速自查，提交前必须全目录跑一遍。**
2. **`backend/pyproject.toml` 有独立的 `[tool.mypy]`**（含 apscheduler/structlog 等
   `ignore_missing_imports` overrides），但**没有** `[tool.ruff]`。所以从 `backend/`
   跑时：mypy 用 backend 的配置，ruff 向上找到**根** `pyproject.toml`。
   显式传 `--config-file ../pyproject.toml` 给 mypy 会丢掉 overrides，报出 22 个
   假错（全是第三方库缺 stub）。
3. **ruff 的 per-file-ignores 按「配置文件所在目录」解析相对路径**，不是按 cwd。
   所以根配置里的 `backend/app/config.py = ["S104"]` 从 `backend/` 跑时依然生效 ——
   看到报错先当真错查，不要先怀疑路径错配。

另：仓库根的 `evaluation/` 与 `scripts/`（非 `backend/scripts/`）有 22 个既有
ruff 错，最后提交在 2026-07-08。CI 扫不到它们，**不要顺手"修"** —— 那是范围外改动。

## 输出
- 文件：`.github/workflows/ci.yml`（更新）
- 文件：`.github/workflows/security.yml`（更新）

## 检查清单
- [ ] `ruff check` + `ruff format --check` 通过
- [ ] `pytest --cov` 覆盖率 ≥ 80%（关键模块 ≥ 90%）
- [ ] 安全扫描为 required check
- [ ] Docker 构建冒烟通过
- [ ] 步骤失败阻断 PR 合并

## 参考
- `CONVENTIONS.md §16 代码审查清单`
- `.github/workflows/ci.yml`
- `.github/workflows/security.yml`
