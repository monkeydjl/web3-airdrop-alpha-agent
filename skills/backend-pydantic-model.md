# Skill：Pydantic 数据模型定义

## 目标
为项目定义新的 Pydantic 数据模型，遵循 frozen + extra="forbid" 严格模式与 CONVENTIONS.md §5.3 规范。

## 适用场景
- 新增 agent 输出结构
- 新增 API 请求/响应模型
- 新增数据库行映射模型

## 输入要求
- 文件：`backend/app/models.py`（模型集中存放）
- 文件：`CONVENTIONS.md §5.3 Pydantic 模型严格模式`
- 信息：字段名、类型、取值范围、来源（agent/db/api）

## 执行步骤

### Step 1: 选择模型类别
- 操作：在 `backend/app/models.py` 中新增 `class XxxResult(BaseModel)`（agent 输出）或 `class XxxRow(BaseModel)`（DB 行）
- 验证：模型名使用 `PascalCase`，后缀 `Result`/`Row`/`Request`/`Response` 表意

### Step 2: 声明 model_config
- 操作：设置 `model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True, validate_default=True)`
- 验证：`frozen=True` 防运行时篡改，`extra="forbid"` 拒绝多余字段

### Step 3: 声明字段与校验
- 操作：每个字段标注类型并使用 `Field(..., description=..., ge/le/pattern=...)`
- 验证：枚举/范围字段加 `pattern` 或 `Literal`；浮点分数加 `ge=0.0, le=1.0`

### Step 4: 补充契约测试
- 操作：把序列化/非法字段拒绝的断言写进对应模块的测试文件
  （API 模型 → `backend/tests/api/test_<name>.py`；opportunity 域模型 →
  `backend/tests/opportunity/test_models.py`）
- 验证：`extra="forbid"` 对未知字段抛 `ValidationError`
- 说明：**不存在 `tests/contracts/` 目录**，不要新建；契约断言与所属模块的测试同处一文件

## 输出
- 文件：`backend/app/models.py`（新增模型）
- 文件：对应模块的测试文件（新增契约断言）

## 检查清单
- [ ] 含 `model_config = ConfigDict(frozen=True, extra="forbid", ...)`
- [ ] 所有字段有类型注解
- [ ] 所有字段有 `Field(description=...)`
- [ ] 范围/枚举字段有 `ge`/`le`/`pattern`/`Literal` 约束
- [ ] 字段名保持 `snake_case`，**不转 camelCase**（前端直接消费原样字段）
- [ ] 契约断言覆盖正常 + 非法输入，且未新建 `tests/contracts/`
- [ ] 模型变更同步更新 API_SPEC.md（如为 API 模型）

## 参考
- `CONVENTIONS.md §5.3 Pydantic 模型严格模式`
- `backend/app/models.py`
- `backend/tests/opportunity/test_models.py`
- Pydantic v2 官方文档
