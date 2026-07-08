# Skill：FastAPI API 端点创建

## 目标
为项目创建新的 FastAPI REST API 端点，遵循项目编码规范和 API_SPEC.md 契约。

## 适用场景
- 添加新的 REST 端点
- 修改现有端点行为
- 添加请求/响应模型

## 输入要求
- 文件：`docs/API_SPEC.md`（API 契约）
- 文件：`CONVENTIONS.md`（编码规范）
- 信息：端点路径、HTTP 方法、请求/响应格式

## 执行步骤

### Step 1: 定义 Pydantic 模型
- 操作：在 `backend/app/models.py` 中添加请求/响应模型
- 验证：模型包含 `model_config = ConfigDict(frozen=True, extra="forbid")`

### Step 2: 实现路由处理函数
- 操作：在 `backend/app/routers/v1/` 中创建或修改路由文件
- 验证：函数签名包含类型注解，返回 `ApiResponse` 包络

### Step 3: 添加单元测试
- 操作：在 `tests/unit/` 中添加对应测试文件
- 验证：测试覆盖正常路径和错误路径

### Step 4: 更新 API 文档
- 操作：同步更新 `docs/API_SPEC.md`
- 验证：文档与代码一致

## 输出
- 文件：`backend/app/routers/v1/<name>.py`
- 文件：`backend/app/models.py`（新增模型）
- 文件：`tests/unit/test_<name>.py`
- 文件：`docs/API_SPEC.md`（更新）

## 检查清单
- [ ] 请求模型有 Field 描述
- [ ] 响应使用 ApiResponse 包络
- [ ] 错误处理使用 HTTPException
- [ ] 单元测试覆盖率 ≥ 90%
- [ ] API_SPEC.md 已同步更新
- [ ] 遵循 CONVENTIONS.md §8 异步规范

## 参考
- `docs/API_SPEC.md`
- `CONVENTIONS.md §8 异步与并发`
- FastAPI 官方文档
