#  Contributing Guide

> 感谢你对 Web3 Airdrop Alpha Agent System 的兴趣！
> 本文档说明如何参与项目贡献。

---

## 开发流程

### 1. 环境准备

```bash
# 克隆仓库
git clone https://github.com/web3-airdrop-alpha/web3-airdrop-alpha-agent.git
cd web3-airdrop-alpha-agent

# 创建虚拟环境
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 安装依赖
pip install -e ".[dev]"

# 安装 pre-commit hooks
pre-commit install

# 复制环境变量
cp .env.example .env
```

### 2. 创建分支

```bash
# 从 main 创建功能分支
git checkout -b feat/your-feature-name

# 分支命名规范：
# feat/*  - 新功能
# fix/*   - Bug 修复
# docs/*  - 文档更新
# perf/*  - 性能优化
```

### 3. 开发

```bash
# 启动开发服务器
make dev

# 运行测试
make test

# 代码检查
make lint
make format-check
make typecheck
```

### 4. 提交

```bash
# Commit 格式（Conventional Commits）
git commit -m "feat(scorer): add competition cache"

# type: feat | fix | docs | refactor | test | chore | perf
# scope: 模块名（scorer, api, db, agent 等）
```

### 5. 创建 PR

- 使用 PR 模板填写变更说明
- 确保 CI 全绿
- 至少 1 个 Reviewer 批准

---

## 代码规范

详见 [`CONVENTIONS.md`](./CONVENTIONS.md)。

关键要点：
- Python 3.11+，所有函数必须有类型注解
- 使用 ruff 格式化（行宽 120）
- Google-style docstring
- 测试覆盖率 ≥ 80%，关键模块 ≥ 90%

---

## 测试

```bash
# 全部测试
make test

# 仅单元测试
make test-unit

# 仅 golden 回归
make test-golden

# 覆盖率报告
make test-cov
```

---

## 文档

- 代码变更需同步更新相关文档
- API 变更需更新 `docs/API_SPEC.md`
- 架构变更需创建 ADR

---

## 行为准则

- 尊重所有贡献者
- 接受建设性批评
- 关注社区共同目标

---

## 问题反馈

- Bug 报告：使用 [Bug Report Template](.github/ISSUE_TEMPLATE/bug_report.md)
- 功能请求：使用 [Feature Request Template](.github/ISSUE_TEMPLATE/feature_request.md)

---

_文档版本：v1.0 · 2026-07-08_
