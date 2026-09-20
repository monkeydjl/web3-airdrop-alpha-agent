# Skill：Pytest 单元测试编写

## 目标
为业务逻辑编写高质量的 pytest 测试，确保正确性与回归防护。

> **目录注意**：测试根目录是 **`backend/tests/`**，全部平铺文件 + 少量子目录
> （`agents/`、`api/`、`collectors/`、`fixtures/`、`golden/`、`opportunity/`、
> `scripts/`、`utils/`）。仓库里**不存在 `tests/unit/`**，不要新建。

## 适用场景
- 新功能开发后编写测试
- Bug 修复时添加回归测试
- 重构前建立安全网

## 输入要求
- 文件：待测试的源代码文件
- 文件：`backend/tests/conftest.py`（唯一的 conftest，全仓只有这一个）
- 文件：`backend/pyproject.toml` `[tool.pytest.ini_options]`（addopts 真相源）
- 信息：功能规格、边界条件

## conftest 实际提供什么（别照抄不存在的 fixture）
`backend/tests/conftest.py` 做两类事，**没有** `db` / `sample_project` / `app_client` 这些 fixture：

| 内容 | 作用 |
| --- | --- |
| 模块顶层强制改 `os.environ` | `APP_ENV=test`、`API_KEY=""`、`HOST=127.0.0.1`，压过本地 `.env` 的生产配置，否则 `Settings()` 的生产自检会让 collection 阶段直接崩 |
| `DB_PATH` / `FETCHER_CACHE_DIR` 默认值 | 指向 `data/test.db` 与 `data/pytest_cache_dir`，避免写到 Docker 路径或生产缓存目录 |
| 覆写 `tmp_path` fixture | 沙箱会锁 pytest 内建 TempPathFactory 建的目录，改用 `data/pytest_tmp` |
| autouse `_isolate_fetcher_disk_cache` | fetcher 缓存是模块级单例，残留会让测试「缓存命中而不发请求」，症状是 `call_count == 0`，极难定位 |

需要 app client、样例数据时，在**测试文件内**自己构造（参照
`backend/tests/api/test_projects.py` 等既有写法）。

## 执行步骤

### Step 1: 分析待测函数
- 操作：读取源代码，识别输入/输出/副作用
- 验证：列出所有分支和边界条件

### Step 2: 选定文件位置
- 操作：API 端点测试放 `backend/tests/api/test_<name>.py`；agent 测试放
  `backend/tests/agents/`；其余放 `backend/tests/test_<module>.py`
- 验证：文件名 `test_*.py`，类名 `Test*`，函数名 `test_*`（`pyproject.toml` 里配死了）

### Step 3: 编写测试用例
- 操作：按 `test_<功能>_<场景>_<预期>` 命名，Arrange-Act-Assert 结构
- 验证：
  - 每个测试只测一个行为
  - `asyncio_mode = "auto"`，async 测试**不需要**加 `@pytest.mark.asyncio`
  - `--strict-markers` 生效，自定义 marker 必须先在配置里注册
  - 避免裸属性表达式（Ruff B018）；清理动作用 `contextlib.suppress`
  - 断言「某符号不存在」这类反向断言，必须先用一个**已知存在**的符号验证搜索器
    本身有效（见 `backend/tests/test_security_doc_parity.py` 文件头的踩坑记录）

### Step 4: 运行并验证
- 操作（本机，快速迭代）：
  ```bash
  cd backend && ./venv/Scripts/python.exe -m pytest tests/test_xxx.py \
    --no-cov -p no:cacheprovider -q
  ```
- 操作（复现 CI 严格度）：去掉 `--no-cov`，补上 CI 的三个 `-W`：
  ```bash
  ./venv/Scripts/python.exe -m pytest tests -q --cov=app --cov-fail-under=80 \
    -W error::DeprecationWarning -W error::ResourceWarning \
    -W error::pytest.PytestUnraisableExceptionWarning
  ```
- 验证：全部通过。覆盖率下限 **80%**（`backend/pyproject.toml` addopts 与 CI 都写着）
- 说明：**collection error + 秒级失败 + 无覆盖率产物 = 环境或依赖问题，不是业务代码**。
  这种情况先查 `requirements.txt` 的版本锁，别去改断言迁就

## 输出
- 文件：`backend/tests/[<subdir>/]test_<module>.py`
- 文件：`backend/tests/conftest.py`（仅在确实需要全局隔离时才动）

## 检查清单
- [ ] 文件落在 `backend/tests/` 下，未新建 `tests/unit/`
- [ ] 未引用 conftest 里不存在的 fixture
- [ ] 测试函数名清晰表达意图，Arrange-Act-Assert 结构
- [ ] 边界条件与异常路径已覆盖
- [ ] 无外部依赖（mock 掉网络/LLM 调用）
- [ ] 覆盖率不低于 80%
- [ ] 未把 `data/pytest_tmp`、`data/pytest_cache_dir` 之类测试产物提交进仓库

## 参考
- `CONVENTIONS.md §9 测试规范`
- `backend/tests/conftest.py`（每段隔离逻辑的原因都写在注释里）
- `backend/pyproject.toml` `[tool.pytest.ini_options]`
- `.github/workflows/ci.yml`（Run full backend test suite）
