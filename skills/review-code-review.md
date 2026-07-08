# Skill：代码审查

## 目标
按项目规范对 PR 进行代码审查，确保合规、可测、安全，遵循 CONVENTIONS.md §16 审查清单。

## 适用场景
- Review 他人 PR
- 提交前自查
- 合并门禁把关

## 输入要求
- 文件：`.github/PULL_REQUEST_TEMPLATE.md`
- 文件：`CONVENTIONS.md §16 代码审查清单`
- 文件：PR diff 与对应测试
- 信息：PR 范围与意图

## 执行步骤

### Step 1: 范围核对
- 操作：确认 PR 单一职责（§11.3），未混入重构+功能
- 验证：PR 标题 `<type>(<scope>): <描述>` 格式正确

### Step 2: 规范核对
- 操作：检查命名（§3）、Pydantic `frozen/forbid`（§5.3）、`async def`（§8.1）、日志键名（§10.2）
- 验证：无 f-string SQL（§13.1）、无硬编码密钥（§12/§10.3）

### Step 3: 测试与质量
- 操作：确认 `pytest --cov` 覆盖率 ≥ 80%（关键模块 ≥ 90%），golden 通过
- 验证：Pydantic 变更有契约测试，API 变更有 API_SPEC 更新

### Step 4: 文档与配置
- 操作：检查 `.env.example`、ADR、DATABASE_DDL 是否同步
- 验证：新增依赖已更新 `requirements` + `.lock`

## 输出
- 文件：Review 意见（PR 评论）
- 文件：审批/请求修改决定

## 检查清单
- [ ] PR 单一职责，标题规范
- [ ] 命名/Pydantic/async/日志符合规范
- [ ] 无 SQL 注入与密钥硬编码
- [ ] 覆盖率达标，契约/golden 测试齐全
- [ ] 文档/配置已同步

## 参考
- `CONVENTIONS.md §16 代码审查清单`
- `.github/PULL_REQUEST_TEMPLATE.md`
- `docs/API_SPEC.md`
