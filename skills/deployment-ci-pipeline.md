# Skill：CI 流水线配置

## 目标
配置/维护 GitHub Actions CI 流水线，覆盖 lint、type-check、测试、安全扫描与构建，遵循 CONVENTIONS.md §16。

## 适用场景
- 修改 `.github/workflows/ci.yml`
- 新增测试/覆盖率门禁
- 接入部署前校验

## 输入要求
- 文件：`.github/workflows/ci.yml`（6 个 job：Lint & Format Check → Full Backend Test Suite → Coverage Gate / Docker Build Check / Type Check (mypy) / Frontend Lint & Build）
- 文件：`.github/workflows/security.yml`（pip-audit / detect-secrets / Trivy / dependency review）
- 文件：`.github/workflows/docs.yml`（文档链接检查）、`.github/workflows/release.yml`
- 文件：根 `pyproject.toml`（ruff 配置）与 `backend/pyproject.toml`（mypy / pytest 配置）
- 文件：`CONVENTIONS.md §16 代码审查清单`

## 执行步骤

### Step 1: Lint 与格式
- 操作：在 `ci.yml` 添加 `python -m ruff check .` 与 `python -m ruff format --check .` 步骤
- 验证：使用根 `pyproject.toml` 的 `line-length=120` 配置

### Step 2: 类型与测试
- 操作：添加 `mypy app --config-file pyproject.toml` 与 `pytest tests -q --cov=app` 步骤；
  覆盖率门禁 `--cov-fail-under=80`
- 验证：关键模块（agents/scorer/orchestrator/db）覆盖率 ≥ 90%
- ⚠️ 不是 `mypy . --strict`：CI 的 `working-directory` 是 `backend`，扫的是 `app`。
  写 `mypy .` 会连 `scripts/` 一起扫出上百个既有错误，与 CI 结果不一致
- ⚠️ 后端测试 job 还带三个 `-W error::`（`DeprecationWarning`、`ResourceWarning`、
  `pytest.PytestUnraisableExceptionWarning`）。这意味着**第三方库的弃用警告会让
  收集阶段整批崩掉**。2026-09-04 实际事故：`anyio` 升到 4.15.0 后
  `starlette.testclient` 触发 `anyio.abc.BlockingPortal` 弃用警告，
  32 个导入 `TestClient` 的文件全部 collection error、exit code 2。
  **正确修法是把传递依赖写进 `requirements.txt` 并 pin 版本，不是放宽 `-W error`** ——
  放宽等于把这道门禁废掉。已有门禁 `backend/tests/test_requirements_pinning.py` 守着这条

### Step 3: 安全门禁
- 操作：`security.yml` 已有四个环节：pip-audit（CVE）、**detect-secrets**（密钥，
  基线为 `.secrets.baseline`）、Trivy、dependency review；设为 required check
- 验证：密钥扫描失败阻断合并
- ⚠️ **不是 gitleaks，也没有 bandit**：旧文档写错过。改这一步先读
  `.github/workflows/security.yml` 实际命令

### Step 4: 构建校验
- 操作：`Docker Build Check` job 做镜像冒烟；后端 `docker/Dockerfile`（`python:3.12-slim`），
  前端 `frontend-next/Dockerfile`（`node:22-alpine`）
- 验证：镜像构建成功，非 root 运行（`appuser` / `nextjs`）

### Step 5: 核对 run 结果
- 操作：同一个 sha 会同时触发 **push 与 pull_request 两个 CI run**，要分别核对
- 验证：用 `gh run list` / `gh run view <id>` 看具体 job；
  「秒级失败 + 无 `coverage.xml` 产物」通常是环境/依赖问题，不是业务代码

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
- [ ] `ruff check` + `ruff format --check` 全目录通过（cwd = `backend/`）
- [ ] `mypy app --config-file pyproject.toml` 通过
- [ ] `pytest --cov` 覆盖率 ≥ 80%（关键模块 ≥ 90%）
- [ ] 新增/升级依赖已在 `requirements.txt` 里 pin，未放宽 `-W error`
- [ ] 安全扫描（detect-secrets / pip-audit）为 required check
- [ ] Docker 构建冒烟通过
- [ ] push 与 pull_request 两个 run 都核对过
- [ ] 步骤失败阻断 PR 合并

## 参考
- `CONVENTIONS.md §16 代码审查清单`
- `.github/workflows/ci.yml`、`security.yml`、`docs.yml`、`release.yml`
- `backend/requirements.txt` 头部（依赖锁定原则与事故记录）
- `backend/tests/test_requirements_pinning.py`
