# 测试框架规范

> 配套文档：`CONVENTIONS.md §10`（测试规范）、`pyproject.toml`（pytest 配置）、`tests/README.md`、`evaluation/README.md`、`benchmark/README.md`、`docs/GOLDEN_TEST_CASES.md`
>
> 本文档统一定义项目的测试体系：单元 / 契约 / API / E2E / 回归 / 负载 / LLM 评估 / Prompt 基准 / Golden 数据集，以及自动化测试规范。

---

## 1. 测试金字塔

```
            ┌──────────┐
            │   E2E    │  少量，全链路验证（CI 夜间跑）
            ├──────────┤
            │   API    │  中等，端点契约（CI 每次跑）
            ├──────────┤
            │ Contract │  中等，Pydantic 模型 schema（CI 每次跑）
            ├──────────┤
            │  Golden  │  固定样本回归（CI 每次跑）
            ├──────────┤
            │   Unit   │  大量，纯函数 / 单 Agent（CI 每次跑）
            └──────────┘
```

| 层级 | 目录 | 频率 | 目标覆盖率 |
| --- | --- | --- | --- |
| Unit | `tests/unit/` | 每次 commit | ≥ 80%（关键模块 ≥ 90%） |
| Contract | `tests/contracts/` | 每次 commit | 100% Pydantic 模型 |
| Golden | `tests/golden/` | 每次 commit | 100% golden 样本通过 |
| API | `tests/api/` | 每次 commit | 100% 端点覆盖 |
| E2E | `tests/e2e/` | 夜间 / release | 全链路 smoke |
| Load | `tests/load/` | weekly / release | 满足性能 SLO |
| LLM Eval | `evaluation/llm/` | weekly | 结构遵从率 ≥ 95% |
| Prompt Benchmark | `benchmark/` | release | 满足性能目标 |

---

## 2. Unit Test

### 2.1 规范

- 文件命名：`test_<被测模块>.py`（如 `test_scorer.py`）
- 函数命名：`test_<行为>_<条件>_<预期>`（如 `test_score_returns_farm_when_total_above_70`）
- 一个测试只断言一件事。
- 使用 `pytest` fixture 复用 setup，禁止继承式测试基类。
- Mock 外部依赖（httpx / LLM / DB），单测不得触碰真实网络或磁盘。

### 2.2 Marker 使用

```python
import pytest

@pytest.mark.unit
def test_scorer_weights_sum_to_one():
    ...

@pytest.mark.slow
def test_full_pipeline_50_projects():
    ...
```

| marker | 用途 | CI 默认 |
| --- | --- | --- |
| `unit` | 单元测试 | 运行 |
| `integration` | 集成测试 | 运行 |
| `contract` | 契约测试 | 运行 |
| `golden` | Golden 回归 | 运行 |
| `api` | API 测试 | 运行 |
| `slow` | 慢测试（> 5s） | 跳过（release 时跑） |

### 2.3 运行

```bash
# 全部单元测试
pytest tests/unit -v -m unit

# 排除慢测试
pytest -v -m "not slow"

# 单文件
pytest tests/unit/test_scorer.py -v
```

---

## 3. Contract Test

### 3.1 目的

保证 Pydantic 模型的 schema 稳定性。模型字段变更（增删改类型）必须同步更新契约测试，否则 CI 失败。

### 3.2 规范

- 每个 Pydantic 模型对应一个契约测试文件。
- 断言字段名、类型、必填/可选、默认值、约束（`ge`/`le`/`regex`）。
- 断言 JSON 序列化/反序列化 round-trip 一致。

### 3.3 示例

```python
# tests/contracts/test_models_contract.py
from app.models import Project

def test_project_fields():
    fields = Project.model_fields
    assert "id" in fields
    assert "name" in fields
    assert "total_score" in fields
    assert fields["total_score"].annotation == float

def test_project_score_range():
    p = Project(id="...", name="test", total_score=150)
    # 期望被截断或抛错，取决于设计
```

---

## 4. Golden Test

### 4.1 目的

用固定输入样本验证评分 pipeline 输出不变（回归保护）。任何评分算法变更必须更新 golden 样本并在 PR 中说明。

### 4.2 数据集

- 样本文件：`tests/golden/projects.jsonl`（每行一个 RawProject JSON，含输入字段与期望的 score + label）
- 至少 20 个样本，覆盖 FARM / WATCH / IGNORE 三档。
- 期望输出内联在 `tests/golden/test_golden.py` 中（或 `projects.jsonl` 每行含 `expected_score` / `expected_label` 字段）。

### 4.3 规范

- 样本必须来源于真实项目（脱敏后）或精心构造的边界 case。
- 新增样本需在 `docs/GOLDEN_TEST_CASES.md` 记录设计意图。
- golden 失败时：先确认是 bug 还是预期变更；预期变更需更新 expected 文件 + PR 说明。

### 4.4 运行

```bash
pytest tests/golden -v -m golden
```

---

## 5. API Test

### 5.1 规范

- 使用 FastAPI `TestClient`（同步）或 `httpx.AsyncClient`（异步）。
- 每个端点至少覆盖：正常路径 + 4xx 错误路径 + 边界值。
- 不依赖真实 DB，用 fixture 注入内存 SQLite（`:memory:`）。

### 5.2 示例

```python
# tests/api/test_health.py
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_health_returns_200():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
```

---

## 6. E2E Test

### 6.1 目的

验证完整服务链路：Collector → Agents → Scorer → DB → API。需启动完整服务（Docker Compose）。

### 6.2 运行条件

- `docker compose -f docker-compose.prod.yml up -d` 已启动
- 访问 `http://localhost:8000`

### 6.3 运行

```bash
pytest tests/e2e -v -m "e2e"
```

### 6.4 测试范围

- 健康检查
- 触发 pipeline run 并验证响应结构
- 等待数据落库后验证项目列表非空
- API 版本头校验

---

## 7. Load Test

### 7.1 工具

`locust`（`tests/load/locustfile.py`）

### 7.2 运行

```bash
locust -f tests/load/locustfile.py --host http://localhost:8000
```

### 7.3 目标指标

| 指标 | MVP 目标 | V2 目标 |
| --- | --- | --- |
| P50 延迟 | < 200ms | < 100ms |
| P99 延迟 | < 1000ms | < 500ms |
| 错误率 | < 1% | < 0.1% |
| 并发用户 | 50 | 500 |

---

## 8. LLM Evaluation（AI 特有）

### 8.1 目的

评估 LLM 增强输出的质量，监控模型漂移与 prompt 效果。这是 AI First 项目区别于传统 CRUD 的核心测试类型。

### 8.2 评估维度

| 维度 | 衡量方式 | 目标 | 告警阈值 |
| --- | --- | --- | --- |
| **结构遵从率** | JSON schema 校验通过率 | ≥ 95% | < 95% |
| **数值合理性** | 修正值在 `output_schema` 范围内比例 | 100% | < 100% |
| **证据充分性** | `evidence` 字段条数 ≥ 1 | 100% | < 100% |
| **规则一致性** | LLM 结果与规则引擎结果偏差均值 | < 0.1 | > 0.2 |
| **延迟** | P95 响应时间 | < 15s | > 30s |
| **成本** | 单次评估 API 调用费用 | < $0.01 | > $0.05 |

### 8.3 评估流程

1. 从 `tests/golden/projects.jsonl` 抽取 100 个样本
2. 对每个样本运行 LLM Agent（Narrative/Team/Risk/Tokenomics）
3. 校验输出是否符合 `output_schema`
4. 对比 LLM 结果与规则引擎结果
5. 输出报告到 `evaluation/llm/YYYY-MM-DD_benchmark.md`
6. 更新 `evaluation/llm/metrics_history.json`（时间序列）

### 8.4 评估脚本

主脚本：`evaluation/llm/template_validation.py`

```bash
# 运行 LLM 评估（需 OPENAI_API_KEY）
python evaluation/llm/template_validation.py --samples 100 --agents narrative,team,risk,tokenomics

# 仅校验 prompt 模板结构（不需 API key）
python evaluation/llm/template_validation.py --validate-templates-only
```

### 8.5 触发频率

- **CI 不跑**（消耗 API 配额）
- **每周日 02:00 UTC** cron 自动跑（`prompts/evaluation/` 目录下）
- **Prompt 变更时**手动跑一次
- **Release 前**必跑

### 8.6 降级触发

- 结构遵从率 < 95% → 告警 + 该 Prompt 版本标记为 `testing`（不升 `stable`）
- 规则一致性 > 0.2 → 告警 + 评估是否回退 Prompt 版本
- 延迟 P95 > 30s → 告警 + 检查模型版本 / 并发配置

---

## 9. Prompt Benchmark

### 9.1 目的

测量 Prompt 模板的性能基线，对比不同版本 Prompt 的效果与成本。

### 9.2 Benchmark 维度

| 维度 | 衡量方式 |
| --- | --- |
| **Token 消耗** | input_tokens + output_tokens（均值 / P95） |
| **延迟** | 端到端耗时（均值 / P95） |
| **成本** | 单次调用 USD |
| **效果** | LLM 评估维度（§8.2） |

### 9.3 版本对比

| Prompt 版本 | 日期 | Token 均值 | 延迟 P95 | 成本/次 | 结构遵从率 | 规则一致性 |
| --- | --- | --- | --- | --- | --- | --- |
| `narrative/v1` | 2026-07-08 | TBD | TBD | TBD | TBD | TBD |
| `narrative/v2` | — | — | — | — | — | — |

新版本 Prompt 升级 `stable` 前，必须在相同样本集上跑 benchmark，且效果不得显著退化（任一维度退化 > 10% 需 ADR）。

### 9.4 运行

```bash
python evaluation/llm/template_validation.py --benchmark --prompt-versions narrative/v1,narrative/v2
```

---

## 10. Regression Test

### 10.1 目的

防止已修复的 Bug 再次出现。每个 Bug 修复 PR 必须附带回归测试。

### 10.2 规范

- 回归测试文件：`tests/unit/test_regression_<bug-id>.py` 或并入对应模块测试
- 测试名含 bug 编号：`test_regression_123_llm_timeout_does_not_crash`
- PR 模板要求：Bug 修复 PR 必须勾选"已添加回归测试"

### 10.3 示例

```python
# tests/unit/test_regression_123.py
"""Regression test for issue #123: LLM timeout crashes Narrative Agent."""
import pytest

@pytest.mark.unit
def test_regression_123_llm_timeout_does_not_crash(mock_llm_timeout):
    agent = NarrativeAgent(llm_client=mock_llm_timeout)
    result = agent.analyze(sector="L2", raw_signals={})
    # 应降级为规则引擎结果，不抛异常
    assert result.heat_score_adjustment == 0.0
```

---

## 11. 自动化测试规范

### 11.1 CI 测试阶段

> 完整定义见 `.github/workflows/ci.yml`。

| Phase | 内容 | 触发 | 失败动作 |
| --- | --- | --- | --- |
| 1. lint | `ruff check` + `ruff format --check` | 每次 push | 阻断 |
| 2. test-unit | `pytest tests/unit tests/contracts tests/golden` | 每次 push | 阻断 |
| 3. test-api | `pytest tests/api` | 每次 push | 阻断 |
| 4. docker-build | 构建 Docker 镜像 + smoke test | 每次 push | 阻断 |
| 5. type-check | `mypy backend/app`（暂 advisory） | 每次 push | 警告 |

### 11.2 本地测试命令

```bash
# 快速反馈（开发时）
make test-fast    # 并行快速测试

# 完整测试（PR 前）
make test-all     # unit + contract + golden + api + e2e

# 仅 LLM 评估（模板结构校验，不需 API key）
make test-llm     # 调用 evaluation/llm/template_validation.py

# 覆盖率报告
make test-cov     # 生成 htmlcov/ 覆盖率报告
```

### 11.3 覆盖率要求

> 注：当前 `backend/app/` 为扁平结构（config/db/main/models），下表为模块化拆分后的目标覆盖率。MVP 阶段以整体覆盖率 ≥ 80% 为准。

| 模块（计划拆分） | 最低覆盖率 | 说明 |
| --- | --- | --- |
| 评分逻辑（scorer） | 90% | 评分核心，零容忍 |
| Agent 逻辑（agents） | 85% | Agent 实现 |
| API 端点（api） | 80% | FastAPI 端点 |
| 数据访问（db） | 70% | 数据访问（部分难测） |
| 整体 | 80% | `pyproject.toml` `--cov-fail-under=80` |

### 11.4 测试数据管理

- 测试 fixture 放 `tests/conftest.py` 或 `tests/<type>/conftest.py`。
- 禁止在测试中硬编码真实 API key / 真实项目数据。
- 使用 `faker` 生成随机测试数据（`pyproject.toml` 已含依赖）。
- 外部 HTTP 调用用 `respx` mock（`pyproject.toml` 已含依赖）。

### 11.5 测试命名约定

| 类型 | 文件 | 函数 |
| --- | --- | --- |
| Unit | `test_<module>.py` | `test_<行为>_<条件>` |
| Contract | `test_<model>_contract.py` | `test_<model>_<aspect>` |
| Golden | `test_golden.py` | `test_golden_<case_id>` |
| API | `test_<endpoint>.py` | `test_<method>_<path>_<scenario>` |
| E2E | `test_e2e_<flow>.py` | `test_e2e_<flow>` |
| Regression | `test_regression_<bug_id>.py` | `test_regression_<bug_id>_<description>` |

---

## 12. 测试检查清单（PR 提交前）

- [ ] 新代码有对应单元测试
- [ ] Pydantic 模型变更同步更新契约测试
- [ ] 评分算法变更更新 golden 样本（如需）
- [ ] API 端点变更有 API 测试
- [ ] Bug 修复附回归测试
- [ ] 本地 `pytest -q --cov` 全绿，覆盖率不降
- [ ] `ruff check .` + `ruff format --check .` 通过
- [ ] 无 `print()` / 调试断点残留
- [ ] Prompt 变更时跑过 LLM 评估（手动或 cron）

---

_文档版本：v1.0 · 2026-07-08_
