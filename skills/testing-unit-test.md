# Skill：Pytest 单元测试编写

## 目标
为业务逻辑编写高质量的 pytest 单元测试，确保代码正确性和回归防护。

## 适用场景
- 新功能开发后编写测试
- Bug 修复时添加回归测试
- 重构前建立安全网

## 输入要求
- 文件：待测试的源代码文件
- 文件：`tests/conftest.py`（共享 Fixture）
- 信息：功能规格、边界条件

## 执行步骤

### Step 1: 分析待测函数
- 操作：读取源代码，识别输入/输出/副作用
- 验证：列出所有分支和边界条件

### Step 2: 编写测试用例
- 操作：按 `test_<功能>_<场景>_<预期>` 命名
- 验证：每个测试只测一个行为

### Step 3: 使用 Fixture
- 操作：复用 `conftest.py` 中的 db/sample_project/app_client
- 验证：测试间无状态泄漏

### Step 4: 运行并验证
- 操作：`pytest tests/unit/test_xxx.py -v --cov`
- 验证：全部通过，覆盖率达标

## 输出
- 文件：`tests/unit/test_<module>.py`
- 文件：`tests/conftest.py`（如需新增 Fixture）

## 检查清单
- [ ] 测试函数名清晰表达意图
- [ ] 使用 Arrange-Act-Assert 结构
- [ ] 边界条件已覆盖
- [ ] 异常路径已测试
- [ ] 无外部依赖（mock 外部调用）
- [ ] 测试运行时间 < 1s

## 参考
- `CONVENTIONS.md §9 测试规范`
- `tests/conftest.py`
- pytest 官方文档
