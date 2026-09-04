# Skill：密钥扫描配置

## 目标
维护仓库的密钥/敏感信息扫描，防止 API Key、私钥、token 入库，对齐 docs/SECURITY.md §8.1 与 CONVENTIONS.md §10.3。

> **工具注意**：本仓用的是 **detect-secrets**，配置是 `.secrets.baseline`。
> **没有 gitleaks，也没有 `.gitleaks.toml`** —— 不要照旧文档去建那个文件。

## 适用场景
- 处理 detect-secrets 的误报/漏报（更新 baseline）
- 调整 CI 安全扫描（`.github/workflows/security.yml`）
- 接入或调整 pre-commit 本地拦截

## 输入要求
- 文件：`.github/workflows/security.yml`（扫描命令的真相源）
- 文件：`.secrets.baseline`（detect-secrets 基线，已在仓库根目录）
- 文件：`.pre-commit-config.yaml`（本地 hook）
- 文件：`docs/SECURITY.md §8.1`
- 文件：`.env.example`（唯一允许出现在仓库里的密钥模板）

## security.yml 实际有四个 job
| Job | 工具 | 说明 |
| --- | --- | --- |
| `dependency-audit` | pip-audit | 审 `backend/requirements.txt` + `requirements-dev.txt`（`--strict`）。`requirements-otel.txt` 单独审但**不阻断**（未锁版本）。`requirements.lock.txt` 分支是**有意保留的条件判断**（将来若改用 pip-compile 产出全量锁文件则优先审它），不是 bug |
| `secret-detection` | detect-secrets | `detect-secrets scan --baseline .secrets.baseline --exclude-files '<regex>'` |
| Trivy | Trivy | 镜像/文件系统漏洞扫描 |
| dependency review | GitHub 原生 | PR 上的依赖变更审查 |

触发器：push（master/main，含对 `security.yml` 自身的改动）、PR、每周一 06:00 UTC、
`workflow_dispatch`（手动，用来验证修复而不必凑一个符合路径过滤的提交）。

## 执行步骤

### Step 1: 复现扫描
- 操作：
  ```bash
  pip install detect-secrets
  detect-secrets scan --baseline .secrets.baseline
  ```
- 验证：本地结果与 CI 一致。CI 额外带 `--exclude-files`，排除项为
  `.env$`、`.env..*`、`package-lock.json`、`*.db`、`*.db.bak-*`、`.git/`、
  `venv/`、`.venv/`、`node_modules/`、`.next/`、`.worktrees/`、`.pytest_tmp/`、`htmlcov/`

### Step 2: 处理误报
- 操作：确认是占位值后更新基线：
  ```bash
  detect-secrets scan --baseline .secrets.baseline
  # 交互式逐条标注
  detect-secrets audit .secrets.baseline
  ```
- 验证：
  - **只为占位/示例值更新基线**，真实密钥必须先轮换再谈基线
  - 新增排除路径要改 `security.yml` 里的 `--exclude-files` 正则，
    改完确认该 workflow 的 `paths` 过滤能触发它自己

### Step 3: pre-commit 本地拦截
- 操作：`.pre-commit-config.yaml` 已存在，装钩子：
  ```bash
  pip install pre-commit && pre-commit install
  ```
- 验证：`pre-commit run --all-files` 通过

### Step 4: 文档与流程
- 操作：扫描流程与例外记录在 `docs/SECURITY.md §8.1`
- 验证：
  - `backend/tests/test_security_doc_parity.py` 会拿文档与代码对账 ——
    改了安全实现必须同步文档，否则那份测试变红
  - CI `security.yml` 应为 required check

## 出现真实泄漏时（顺序不能颠倒）
1. **先轮换密钥**（改 baseline 不等于止损，历史提交里的值仍然有效）
2. 从代码中移除，改走 `Settings` + `.env`
3. 评估是否需要重写历史（谨慎，会影响所有协作者）
4. 更新基线，补一条能拦住同类问题的规则

## 输出
- 文件：`.secrets.baseline`（更新）
- 文件：`.github/workflows/security.yml`（如调整排除项）
- 文件：`.pre-commit-config.yaml`（如调整 hook）
- 文件：`docs/SECURITY.md`（更新）

## 检查清单
- [ ] 用的是 detect-secrets，未新建 `.gitleaks.toml`
- [ ] `.env` / `.env.*` 未被提交（`.gitignore` 覆盖 `.env`、`.env.*`、`.env copy/backup/_bak/-old`，同时保留 `.env.example` 可见）
- [ ] 基线更新仅针对占位值，真实泄漏已先轮换
- [ ] 新增排除路径同时改了 workflow 正则
- [ ] `pre-commit run --all-files` 通过
- [ ] SECURITY.md 已同步，doc parity 测试通过

## 参考
- `docs/SECURITY.md §8.1`
- `.github/workflows/security.yml`（每段注释都记着当初为什么这么写）
- `CONVENTIONS.md §10.3 敏感数据`
- `AGENTS.md`（禁止读取 `.env` 的红线）
