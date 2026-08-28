# 2026-08-28

> mypy strict 这条 long-running 目标今天收口：立项时 **374 个 strict 错误 / 81 文件**，
> 全部分支 `fix/mypy-strict` 上 21 个提交清到 **0 错误 / 120 文件**，
> mypy + ruff 全绿。还差 push、开 PR、CI 门禁走完，然后写当日验证、合并。

---

## 一、这个目标在干什么（给接手的人）

`backend/pyproject.toml` 的 `[tool.mypy]` 此前只是一组 false/true 混排的"宽松口径"，
CI 的 Type Check 绿着却什么都拦不住。owner 拍板把 backend 提到 `strict = true`
（对齐根 pyproject 那份从没被读过的严格配置），修完 374 个错误、落地成真门禁。

配置最终形态（`backend/pyproject.toml`）：

- `strict = true` + `warn_unreachable = true` + `warn_redundant_casts = true`
- `[[tool.mypy.overrides]]` 只豁免 5 个没配 stub 的第三方库：
  `apscheduler.*` / `structlog.*` / `pandas` / `openpyxl.*` / `opentelemetry.*`，
  项目内 `app/` 一条都不豁免
- `python_version = "3.11"`（= `requires-python` 下限，见 08-24 第十四节）

验证命令（cwd=backend）：
`& ".\venv\Scripts\python.exe" -m mypy app --config-file pyproject.toml --no-incremental`

---

## 二、三批方法论（可复用）

374 个错误不是硬啃，是按三批清掉的，顺序很重要：

1. **先消配置噪音**：第三方缺 stub 的 import 检查会淹没项目内错误，
   先 override 豁免掉，剩下的才是真问题。
2. **再补机械注解**：`-> None`、`dict[str, Any]`、`cast(...)`、删多余
   `# type: ignore`（strict 下 `warn_unused_ignores` 会把多余的 ignore 标成错误）。
   占大头，一次几十个，纯机械，适合批量。
3. **最后啃真实类型问题**：`X | None` 的窄化、循环变量重赋值、
   `all()` / 列表推导 filter 不窄化元素、structlog processor 签名、
   pydantic validator 返回 `Self`。这些才是 strict 真正要逼出来的。

---

## 三、mypy strict 的可复用坑（以后直接绕开）

- **`all(x is not None for ...)` 不 narrow 元素**；helper 布尔函数
  `_ok(item)` 也不 narrow 它的参数。要显式 `is None` 检查，或 `cast`。
- **列表推导的 `if dt is not None` 在推导体里 narrow 了 `dt`，但结果列表的
  元素类型不跟着 narrow**（`parsed` 元素仍是 `X | None`）——要么显式循环 +
  `list[tuple[Any, datetime]]` 注解，要么 `cast(...)` 包裹（cast 反而会报
  redundant-cast，因为它只 narrow 了局部）。直接重写成显式 for 循环最干净。
- **模块级 `_x = None` 是 partial type**；若在别的函数里重新赋值后再判
  `is None`，mypy 会把重赋值路径判成 `unreachable`。补 `_x: Any | None = None`。
- **`if x is not None:` 窄化会把循环里"用 None 终止"的写法判成死代码**：
  前面窄化成 `str`，循环里 `current_id = ... or None` 就报 assignment。
  修法：给变量显式声明 `str | None`，循环改 `while True:` + 开头 `if x is None: break`。
- **structlog processor 签名**：`(logger, method_name, event_dict)` 的
  `event_dict` 是 `MutableMapping[str, Any]`，返回 `Mapping[str, Any]`
  （不是 `dict[str, Any]`，否则 list-item 不匹配）。
- **pydantic**：`@model_validator(mode="after")` 返回 `-> Self`；
  `mode="before"` 是 `(cls, data: Any) -> Any`；`model_post_init(self, __context: Any) -> None`。
- **starlette 1.3.x 的 `RequestResponseEndpoint` 在 `starlette.middleware.base`**，
  不在 `starlette.types`。
- **`Any` 的 `==` / `>` 比较结果是 `Any`**，声明返回 `bool` 时 `return left == right`
  报 no-any-return → 包 `bool(...)`。
- **删多余 `# type: ignore` 时看错误码**：`# type: ignore[misc]` 盖不住
  `assignment` 错误，会同时报"unused ignore"和"assignment 未被覆盖"。
  精确改 `# type: ignore[assignment]`。

---

## 四、今天收尾这一轮（round 42，从 177 一路清到 0）

按文件的几个真实问题（不是注解、是代码边界）：

- `opportunity/repository.py` supersession 环检测：`stored.supersedes_evidence_id`
  在前面 `is not None` 窄化成 `str`，循环"用 None 终止"被判死代码 → 显式
  `str | None` + `while True / break` 还原语义。
- `utils/redact.py` `_open_log_file = None` 缺注解被当"恒 None 部分类型"，
  `is None` 分支后的重赋值判 unreachable → 补 `Any | None` 消灭假阳性。
- `collectors/cryptorank.py` 的 `usd` 经 `or` 链可能返回非 dict，却先注解
  `dict[str, Any]`，把"非 dict 就置空"的防御分支变死代码 → 改 `Any`。
- `opportunity/economic_integration.py`：`writer.process()` 已声明非 None，
  删掉恒 False 的 `if summary is None` 防御分支出（死代码）。
- `openapi.py`：给 `app` 补 `FastAPI` 注解后，`openapi_schema` 有了真实 stub
  类型，之前为压 no-any-return 加的 `cast` 变成 redundant → 去掉。

---

## 五、验证记录（实际跑过的命令）

| 检查 | 结果 |
|---|---|
| `mypy app --config-file pyproject.toml --no-incremental` | **Success: no issues found in 120 source files** |
| `ruff check app tests` | All checks passed |
| `ruff format --check app tests` | 247 files already formatted |
| 完整后端套件 `pytest`（--cov-fail-under=80） | **待补**（本轮进行中，约 40 分钟） |

---

## 六、下一步 & 遗留

1. **补 pytest 结果**（跑完后把上表"待补"换成真实 passed/skipped/cov）。
2. **push `fix/mypy-strict` → 开 PR #26**（target master），CI 5 个 required
   context 全绿后合并：Coverage Gate / Type Check / Frontend Lint & Build /
   Lint & Format Check / Full Backend Test Suite。
3. **合并后**：确认 master 的 Type Check job 跑的就是 strict 口径（本次核心收益）。

遗留（非本次范围）：根目录 `pyproject.toml` 里的死配置 `[tool.mypy]`（08-24
第十四节记过）—— 现在 backend 已是 strict，根那份要不要删/对齐，另议。