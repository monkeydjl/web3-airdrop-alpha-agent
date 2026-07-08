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
- 操作：添加 `mypy . --strict`（V2）与 `pytest -q --cov` 步骤；覆盖率门禁 ≥ 80%
- 验证：关键模块（agents/scorer/orchestrator/db）覆盖率 ≥ 90%

### Step 3: 安全门禁
- 操作：触发 `security.yml`（gitleaks + bandit `S` 规则），设为 required check
- 验证：密钥扫描失败阻断合并

### Step 4: 构建校验
- 操作：添加 `docker build` 冒烟（可选 matrix 含前端 V2）
- 验证：镜像构建成功，非 root 运行

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
