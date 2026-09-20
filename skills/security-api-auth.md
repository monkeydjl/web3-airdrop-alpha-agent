# Skill：API 鉴权实现（V2）

## 目标
维护 V2 API 的双令牌鉴权（管理员 API Key + 匿名 HMAC token），遵循 CONVENTIONS.md §12 配置管理与 docs/SECURITY.md。

> 路径注意：鉴权**全部在 `backend/app/auth.py` 一个文件里**（含中间件类）。
> 仓库里不存在 `backend/app/middleware/` 目录，不要新建。

## 适用场景
- 把某个路由/方法加入或移出管理员白名单
- 调整匿名 token 的签发、有效期、权限
- 接入用户系统（ADR-008）

## 输入要求
- 文件：`backend/app/auth.py`（鉴权逻辑 + `APIKeyMiddleware`）
- 文件：`backend/app/routers/v1/auth.py`（`/api/v1/auth/anonymous` 签发端点）
- 文件：`backend/app/main.py`（第 286 行附近 `app.add_middleware(APIKeyMiddleware)`）
- 文件：`docs/adr/ADR-008-user-system.md`、`docs/SECURITY.md`

## 现状速览（改之前先读懂）
| 机制 | 实现 |
| --- | --- |
| 管理员凭据 | `settings.api_key`，`X-API-Key` 或 `Authorization: Bearer` 传入 |
| 匿名 token | 纯 HMAC-SHA256，**无 JWT 依赖**：`base64url(payload) + "." + base64url(sig)` |
| 签名密钥 | `settings.auth_token_secret`；为空时进程内随机（仅本地/测试，生产必填） |
| 放行清单 | `PUBLIC_PREFIXES`（`/health`、`/metrics`、`/docs`、`/api/v1/auth/anonymous` 等） |
| 管理员锁 | `ADMIN_ONLY_PREFIXES`（整前缀，不分方法）+ `ADMIN_ONLY_METHOD_RULES`（按方法） |
| 判定入口 | `requires_admin(method, path) -> bool`（刻意抽成函数，便于测试直接断言） |

## 执行步骤

### Step 1: 确认配置项
- 操作：需要新配置时在 `backend/app/config.py` 的 `Settings` 增加字段，pydantic-settings 从 `.env` 读取
- 验证：密钥**不入库、不打印、不记日志**（CONVENTIONS §12）；生产必填项要补进
  `config.py` 的 `_validate_production`

### Step 2: 调整权限规则
- 操作：改 `ADMIN_ONLY_PREFIXES` 或 `ADMIN_ONLY_METHOD_RULES`，不要在中间件里内联 `any(...)`
- 验证：
  - 「同路径读开放、写受限」用 `ADMIN_ONLY_METHOD_RULES`（既有例子：
    `/api/v1/collections/*` 的写操作会真跑采集并消耗第三方配额，
    `PATCH /api/v1/projects/{id}/funding` 会改数据并触发重算，但两者 GET 都是普通只读）
  - 新规则必须有 `requires_admin()` 层面的断言，而不是只靠发请求间接观察

### Step 3: token 签发与校验
- 操作：签发走 `issue_anonymous_token()`，校验走 `verify_token()`，管理员判定走 `is_admin_token()`；
  路由内取当前用户用 `get_current_user(request)`
- 验证：
  - MVP 模式 `api_key=""` 时跳过校验（向后兼容），改动不能破坏这条
  - 鉴权失败返回 `401 { "ok": false, "error": { "code": ... } }` 统一包络
  - 签名比较用 `hmac.compare_digest`，不要用 `==`

### Step 4: 更新文档与测试
- 操作：同步 `docs/API_SPEC.md` 鉴权章节；测试写在
  `backend/tests/test_auth_anonymous.py`（签发/校验/过期/权限矩阵）与
  `backend/tests/test_auth_quarantine.py`（隔离区相关鉴权）
- 验证：测试不硬编码真实密钥，用 fixture 或 monkeypatch 注入；
  跑 `./venv/Scripts/python.exe -m pytest tests/test_auth_anonymous.py tests/test_auth_quarantine.py --no-cov -p no:cacheprovider -q`

## 输出
- 文件：`backend/app/auth.py`（更新）
- 文件：`backend/app/routers/v1/auth.py`（如涉及签发端点）
- 文件：`backend/app/config.py`（如新增配置）
- 文件：`backend/tests/test_auth_anonymous.py` / `test_auth_quarantine.py`
- 文件：`docs/API_SPEC.md`（更新）

## 检查清单
- [ ] 改动落在 `backend/app/auth.py`，未新建 `middleware/` 目录
- [ ] 密钥来自 `Settings`，无硬编码，日志无泄露
- [ ] 权限规则有 `requires_admin()` 级别的直接断言
- [ ] 401 使用统一错误包络
- [ ] MVP 空密钥兼容未被破坏
- [ ] API_SPEC.md 已同步

## 参考
- `docs/adr/ADR-008-user-system.md`
- `docs/SECURITY.md`
- `CONVENTIONS.md §12 配置管理`
- `backend/app/auth.py` 文件头注释（双令牌格式与受保护端点清单）
