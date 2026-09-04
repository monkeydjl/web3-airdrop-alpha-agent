# Skill：代码审查

## 目标
按项目规范审查 PR / 自查，确保合规、可测、安全、文档同步。
基线是 `CONVENTIONS.md §16 代码审查清单` 与 `.github/PULL_REQUEST_TEMPLATE.md`，本文件补充「清单里写了但和现状不符」的地方，以及真正会拦下 PR 的自动化门禁。

## 适用场景
- Review 他人 PR
- 提交前自查
- 合并门禁把关

## 现状速览（清单与现状的差异，以这张表为准）

| 清单里写的 | 实际情况 |
|---|---|
| 新增依赖更新 `requirements.txt` + `.lock.txt` | **`.lock.txt` 全仓不存在**。真实门禁是 `backend/tests/test_requirements_pinning.py`：新增依赖必须 `==` 精确 pin 到 `backend/requirements.txt`（或 `-dev` / `-otel`），散装装包会让 CI 结果不可复现 |
| 覆盖率「行覆盖率 ≥ 80%（关键模块 ≥ 90%）」 | **只有 80% 一条线**，没有「关键模块」分级。`backend/pyproject.toml` 的 `addopts` 与 CI 都只写 `--cov-fail-under=80` |
| `mypy . --strict`（V2 启用） | 实际跑的是 `mypy app --config-file pyproject.toml`（CI 同名 job）——**只检查 `app`，不检查 `tests`**，也不是 `--strict` |
| Pydantic 变更 → 契约测试 | 没有 `tests/contracts/` 目录。Pydantic 变更的兜底是 `test_frontend_field_parity.py` / `test_frontend_enum_parity.py` / `test_frontend_flag_parity.py` 三条前后端一致性测试 |
| 「（单元/契约/golden/API）」 | 真实目录是 `backend/tests/` 下的 `agents/` `api/` `collectors/` `opportunity/` `scripts/` `utils/` `golden/`；golden 唯一入口是 `backend/tests/golden/test_golden_cases.py` |

> **PR 模板自身也有漂移。** `.github/PULL_REQUEST_TEMPLATE.md` 里仍写着 `.lock.txt` 与
> 「关键模块 ≥ 90%」。审查时按上表判定，别照模板打勾。要修模板是另一件事，别混进业务 PR。

## 输入要求
- 文件：`.github/PULL_REQUEST_TEMPLATE.md`
- 文件：`CONVENTIONS.md §16 代码审查清单`（§3 命名 / §5.3 Pydantic / §7 错误处理 / §10 日志 / §11.3 提交 / §12 配置 / §13 数据库）
- 文件：PR diff 与对应测试
- 信息：PR 范围与意图

## 执行步骤

### Step 1: 范围核对
- 操作：确认 PR 单一职责（§11.3），未把重构和功能混在一起
- 验证：标题 `<type>(<scope>): <描述>`，type 取 `feat` / `fix` / `docs` / `refactor` / `test` / `chore` / `perf`
- 说明：涉及架构决策的应带 ADR；`backend/tests/test_adr_index_parity.py` 会校验 ADR 索引与文件是否对得上

### Step 2: 规范核对
- 操作：检查命名（§3）、Pydantic `frozen/forbid`（§5.3）、`async def`（§8.1）、日志事件名（§10.2）、指标前缀 `airdrop_`（§14）
- 验证：无 f-string SQL（§13.1，一律 `?` 占位符）、无硬编码密钥、无 `print()` / 调试断点残留
- 说明：`except` 里的清理动作要套 `contextlib.suppress`；异步锁惰性创建（否则事件循环绑定在不同 loop 上会炸）

### Step 3: 数据库变更专项
- 操作：新增列/表必须**四处同落** —— `backend/app/db.py` 的 `_sqlite_ddl()` 与 `_postgres_ddl()`、Alembic 新版本、`docs/DATABASE_DDL.md`
- 验证：补列走 `_add_column_if_not_exists()`；PostgreSQL 侧多语句要过 `_split_sql_statements()`；会有测试扫到的两处是
  `backend/tests/test_db_init.py`（扫 `_sqlite_ddl()`）与
  `backend/tests/opportunity/test_repository.py::test_postgres_ddl_defines_equivalent_opportunity_schema_without_foreign_keys`
  （断言 PG DDL 里 `"foreign key" not in ddl` 且 `" references " not in ddl`）
- 说明：schema 刻意不写 `REFERENCES`，级联删除在路由层显式做。漏掉 PostgreSQL 那份 DDL 在本地 SQLite 下完全测不出来
- 说明：`docs/DATABASE_DDL.md` 的同步**没有自动化门禁**（只在 `test_v2_tables.py` 的 docstring 里被引用），全靠人工，这一项最常漏

### Step 4: 跑真正的门禁
- 操作（后端）：
  ```bash
  cd backend
  ./venv/Scripts/python.exe -m ruff check .
  ./venv/Scripts/python.exe -m ruff format --check .
  ./venv/Scripts/python.exe -m mypy app --config-file pyproject.toml
  ./venv/Scripts/python.exe -m pytest tests -q --no-cov -p no:cacheprovider
  ```
- 操作（前端）：`cd frontend-next && npm run lint && npm run typecheck && npm run build && npm audit --audit-level=high`
- 验证：CI 的 pytest 还带三个 `-W error::`（`DeprecationWarning` / `ResourceWarning` / `PytestUnraisableExceptionWarning`），本地没带会在 CI 上才暴露
- 说明：**别把 `.txt` 传给 ruff**，它只接受 `.py`；也别放宽 `-W error` 来绕过依赖警告 —— 2026-09-04 的 anyio 事故（32 个文件 collection error）正确修法是 pin 版本

### Step 5: 文档一致性门禁（本仓最容易漏的一类）
- 操作：改动涉及下列契约时，跑对应的 parity 测试
  ```bash
  cd backend && ./venv/Scripts/python.exe -m pytest \
    tests/test_check_terminology.py tests/test_encoding_mojibake.py \
    tests/test_api_spec_parity.py tests/test_observability_doc_parity.py \
    tests/test_security_doc_parity.py tests/test_operations_doc_parity.py \
    tests/test_env_example_parity.py tests/test_requirements_pinning.py \
    tests/test_adr_index_parity.py \
    tests/test_frontend_field_parity.py tests/test_frontend_enum_parity.py \
    tests/test_frontend_flag_parity.py \
    --no-cov -p no:cacheprovider -q
  ```
- 验证：改了 API 同步 `docs/API_SPEC.md`；改了事件名同步 `docs/OBSERVABILITY.md` 的计数；改了环境变量同步 `.env.example`
- 说明：`test_security_doc_parity.py` 有一条**反向断言** —— `system_prompt` / `output_schema` 等 6 个符号在 `backend/app` 里必须一处都没有。把「待实现」变成「已实现」时，必须同步改这个测试，否则它会在你做对之后报错

### Step 6: 出结论
- 操作：给 approve / request changes，意见指到具体文件行
- 验证：request changes 必须带可执行的修改建议，不只是「这里不好」

## 输出
- 文件：Review 意见（PR 评论）
- 文件：审批 / 请求修改决定

## 检查清单
- [ ] PR 单一职责，标题 `<type>(<scope>): <描述>`
- [ ] 命名 / Pydantic / async / 日志 / 指标符合规范
- [ ] 无 f-string SQL、无密钥硬编码、无调试残留
- [ ] DB 变更四处同落（sqlite DDL / pg DDL / alembic / DATABASE_DDL.md），级联删除显式写
- [ ] ruff + mypy + pytest 全绿，覆盖率按 80% 判定（**不是 90%**）
- [ ] 新增依赖 `==` pin 到 requirements，无 `.lock` 文件要更新
- [ ] 前端 lint / typecheck / build / `npm audit --audit-level=high` 通过
- [ ] 涉及的 parity 测试已跑（术语、编码、API、可观测性、安全、运维、env、ADR 索引、前端一致性）
- [ ] 若把某个「待实现」符号落地，同步 `test_security_doc_parity.py` 的反向断言

## 参考
- `CONVENTIONS.md §16 代码审查清单`（及 §3 / §5.3 / §7 / §10 / §11.3 / §12 / §13 / §14）
- `.github/PULL_REQUEST_TEMPLATE.md`
- `docs/API_SPEC.md`、`docs/DATABASE_DDL.md`、`docs/OBSERVABILITY.md`
- `.github/workflows/ci.yml`（6 个 job）、`.github/workflows/security.yml`（pip-audit / detect-secrets / Trivy / dependency review）
- `backend/tests/` 下的 `test_*_parity.py` 系列
