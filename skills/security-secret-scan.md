# Skill：密钥扫描配置

## 目标
为仓库配置密钥/敏感信息扫描，防止 API Key、私钥、token 入库，对齐 docs/SECURITY.md §8.1 与 CONVENTIONS.md。

## 适用场景
- 接入 pre-commit 密钥检测
- 配置 CI 安全扫描（`.github/workflows/security.yml`）
- 处理误报/漏报

## 输入要求
- 文件：`.github/workflows/security.yml`
- 文件：`docs/SECURITY.md §8.1`
- 文件：`.env.example`（密钥模板，应被允许）

## 执行步骤

### Step 1: 选择扫描工具
- 操作：采用 `gitleaks`（或 `ruff` 的 `S` 安全规则）做静态密钥检测
- 验证：CI 中 `security.yml` 已集成该步骤

### Step 2: 配置忽略规则
- 操作：编写 `.gitleaks.toml`，将 `.env.example`、测试 fixture 中的占位密钥加入 `allowlist`
- 验证：占位值（如 `openai_api_key=""`）不被误报，真实格式密钥被拦截

### Step 3: 接入 pre-commit
- 操作：在 `.pre-commit-config.yaml` 增加 gitleaks hook，提交前本地拦截
- 验证：本地 `pre-commit run --all-files` 通过

### Step 4: 验证与文档
- 操作：在 `docs/SECURITY.md` 记录扫描流程；CI 失败时不合并
- 验证：CI `security.yml` 步骤为 required check

## 输出
- 文件：`.gitleaks.toml`（或等效配置）
- 文件：`.pre-commit-config.yaml`（更新）
- 文件：`.github/workflows/security.yml`（更新）
- 文件：`docs/SECURITY.md`（更新）

## 检查清单
- [ ] CI security.yml 已集成密钥扫描
- [ ] `.env.example` 占位密钥已 allowlist
- [ ] pre-commit hook 本地可用
- [ ] 真实格式密钥被拦截
- [ ] SECURITY.md 已记录流程

## 参考
- `docs/SECURITY.md §8.1`
- `.github/workflows/security.yml`
- `CONVENTIONS.md §10.3 敏感数据`
