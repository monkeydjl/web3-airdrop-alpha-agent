# Skill：API 鉴权实现（V2）

## 目标
为 V2 API 实现请求鉴权（API Key / Token），遵循 CONVENTIONS.md §12 配置管理与 docs/SECURITY.md。

## 适用场景
- 为路由添加鉴权中间件
- 接入用户系统（ADR-008）
- 强化现有鉴权逻辑

## 输入要求
- 文件：`backend/app/auth.py`（鉴权逻辑）
- 文件：`backend/app/middleware/auth.py`（中间件）
- 文件：`docs/adr/ADR-008-user-system.md`
- 文件：`docs/SECURITY.md`

## 执行步骤

### Step 1: 读取密钥配置
- 操作：在 `backend/app/config.py` 的 `Settings` 增加 `api_key`/`jwt_secret`（pydantic-settings 从 `.env` 读取）
- 验证：密钥**不入库、不打印、不记日志**（CONVENTIONS §12）

### Step 2: 实现鉴权逻辑
- 操作：在 `backend/app/auth.py` 实现 `verify_request(req) -> bool`，校验 Header `X-API-Key` 或 Bearer Token
- 验证：MVP 模式 `api_key=""` 时空字符串跳过校验（向后兼容）

### Step 3: 挂载中间件
- 操作：在 `backend/app/middleware/auth.py` 注册 `BaseHTTPMiddleware`，对受保护路由调用 `verify_request`
- 验证：鉴权失败时返回 `401 { "ok": false, "error": { "code": "unauthorized" } }`

### Step 4: 更新文档与测试
- 操作：更新 `docs/API_SPEC.md` 鉴权章节，在 `tests/api/test_auth.py` 测 200/401 路径
- 验证：测试不硬编码真实密钥，使用 fixtures 注入

## 输出
- 文件：`backend/app/auth.py`（更新）
- 文件：`backend/app/middleware/auth.py`（更新）
- 文件：`backend/app/config.py`（更新）
- 文件：`tests/api/test_auth.py`
- 文件：`docs/API_SPEC.md`（更新）

## 检查清单
- [ ] 密钥来自 `Settings`，无硬编码
- [ ] 日志中无密钥泄露
- [ ] 401 使用统一错误包络
- [ ] MVP 空密钥兼容
- [ ] API_SPEC.md 已同步
- [ ] 测试覆盖 200/401

## 参考
- `docs/adr/ADR-008-user-system.md`
- `docs/SECURITY.md`
- `CONVENTIONS.md §12 配置管理`
