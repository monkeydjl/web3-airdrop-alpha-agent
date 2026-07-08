# Skill：REST 端点设计与实现

## 目标
设计并实现符合 docs/API_SPEC.md 契约的 REST 端点，遵循 CONVENTIONS.md §3.4 与 backend-fastapi-api 规范。

## 适用场景
- 新增 REST 资源端点
- 调整请求/响应结构
- 版本化端点（ADR-009）

## 输入要求
- 文件：`docs/API_SPEC.md`（契约）
- 文件：`CONVENTIONS.md §3.4 API 命名`
- 文件：`backend/app/routers/v1/`（路由目录）
- 信息：资源、方法、字段

## 执行步骤

### Step 1: 设计契约
- 操作：在 `docs/API_SPEC.md` 定义路径（`/api/v1/<resources>`）、方法、请求/响应 JSON（`snake_case`）
- 验证：路径名词复数，query 参数 `snake_case`（§3.4）

### Step 2: 定义模型
- 操作：在 `backend/app/models.py` 加请求/响应模型（`frozen=True, extra="forbid"`）
- 验证：字段含 `Field(description=...)`

### Step 3: 实现路由
- 操作：在 `backend/app/routers/v1/<resources>.py` 写 `async def`，返回 `ApiResponse` 包络
- 验证：统一 `async def`（§8.1）；错误用 `HTTPException` + 语义状态码

### Step 4: 测试与版本
- 操作：`tests/api/test_<resources>.py` 覆盖 2xx/4xx/422；如弃用旧版更新 `middleware/version_check.py`（ADR-009）
- 验证：覆盖率 ≥ 90%，API_SPEC 与代码一致

## 输出
- 文件：`backend/app/routers/v1/<resources>.py`
- 文件：`backend/app/models.py`（更新）
- 文件：`tests/api/test_<resources>.py`
- 文件：`docs/API_SPEC.md`（更新）

## 检查清单
- [ ] 路径 `snake_case` 复数，query `snake_case`
- [ ] 响应用 ApiResponse 包络
- [ ] 路由 `async def`，错误用 HTTPException
- [ ] 测试覆盖正常/错误/校验路径
- [ ] API_SPEC.md 已同步

## 参考
- `docs/API_SPEC.md`
- `CONVENTIONS.md §3.4 API 命名 / §8.1 异步`
- `docs/adr/ADR-009-api-versioning.md`
