"""`.env.example` 与代码真相的双向门禁。

**为什么需要这道门禁**：`.env.example` 是新人和部署脚本唯一的配置起点，
但它不被任何代码读取 —— 所以它写错了不会有任何报错，只会静默误导人。
实测这一份此前有 47 个键的值与 `app/config.py` 的默认值不一致、2 个键
全仓无人读取、还有一处**自相矛盾**（写着 `DB_BACKEND=sqlite`，
同时把 `DATABASE_URL` 设成 Postgres —— 后者会反向把 backend 改成 postgres，
于是照模板复制出来的 `.env` 实际连的是 PG，而不是它自己声明的 SQLite）。

门禁的两条断言：

1. **每个键都必须真的有人读**：是 `Settings` 字段，或带 `env-external`
   标记说明谁读它（OTel SDK / docker compose 这类不经 Settings 的变量）。
2. **每个值都必须等于代码默认值**，或带 `env-differs` 标记写出为什么故意不同。

标记写在键的**上一行注释**里，逐键显式、可 `grep` 审计。
**刻意不做整文件豁免** —— 那正是 `API_SPEC.md` / `OPERATIONS.md`
烂掉的机制：一旦整份被豁免，就没人再逐行读它，错的内容会跟错的字节一起躺着。

解析器自身也必须能失败：三条 parser self-check 断言它在文件结构变化时
会大声报错，而不是安静地少读几个键然后一路全绿。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_EXAMPLE = REPO_ROOT / ".env.example"

# 逐键豁免标记，必须出现在该键上方的注释块里。
_MARK_EXTERNAL = "env-external"  # 这个键不是 Settings 字段，由外部组件直接读
_MARK_DIFFERS = "env-differs"  # 这个键的值故意与代码默认值不同

_KEY_LINE = re.compile(r"^([A-Z][A-Z0-9_]*)=(.*)$")


def _read_example() -> str:
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    assert len(text) > 2000, f"{ENV_EXAMPLE.name} 短得不正常（{len(text)} 字符），解析器可能读错了文件"
    return text


def _parse_example(text: str) -> dict[str, tuple[str, set[str]]]:
    """解析出 `键 -> (值, 该键上方注释块里出现的豁免标记集合)`。

    注释块 = 紧贴该键上方的连续 `#` 行（空行会截断，所以标记不会跨节泄漏到
    下一个键上）。这一点很重要：如果标记能跨越空行生效，一个豁免就会顺着
    整节蔓延，退化成整文件豁免。
    """
    result: dict[str, tuple[str, set[str]]] = {}
    pending: list[str] = []
    for raw in text.split("\n"):
        line = raw.strip()
        if line.startswith("#"):
            pending.append(line)
            continue
        m = _KEY_LINE.match(line)
        if m:
            marks = set()
            block = "\n".join(pending)
            if _MARK_EXTERNAL in block:
                marks.add(_MARK_EXTERNAL)
            if _MARK_DIFFERS in block:
                marks.add(_MARK_DIFFERS)
            result[m.group(1)] = (m.group(2).strip(), marks)
        pending = []
    assert len(result) > 100, f"只解析出 {len(result)} 个键，明显偏少 —— 解析器和文件格式对不上了"
    return result


def _code_default(name: str) -> str:
    """把 Settings 字段**声明的**默认值渲染成 `.env` 里该写的字面量。

    刻意读 `model_fields[...].default` 而不是 `Settings(...)` 实例属性：
    实例会被环境变量覆盖（`conftest.py` 就设了 `APP_ENV=test`、`DB_PATH`、
    `HOST`，而环境变量的优先级高于 dotenv）。拿实例值当"代码默认值"的话，
    这道门禁在 pytest 里、在裸机上、在 CI 里的判定各不相同 ——
    **一个随环境改变结论的断言不是断言。**
    """
    value = Settings.model_fields[name].default
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    return str(value)


def _values_agree(name: str, documented: str, expected: str) -> bool:
    """比对模板值与代码默认值，数值字段按数值比（`0.10` 等于 `0.1`）。"""
    if documented == expected:
        return True
    annotation = Settings.model_fields[name].annotation
    if annotation in (float, int):
        try:
            return float(documented) == float(expected)
        except ValueError:
            return False
    return False


def _load_from_example(parsed: dict[str, tuple[str, set[str]]]) -> Settings:
    """按模板的键值构造 Settings，绕过环境变量干扰。

    用 init kwargs（优先级最高）而不是 `_env_file=`：后者会被 `conftest.py`
    设的环境变量压住，测出来的就不是"照这份模板会得到什么"。
    """
    fields = set(Settings.model_fields)
    kwargs = {key.lower(): value for key, (value, _m) in parsed.items() if key.lower() in fields}
    return Settings(_env_file=None, **kwargs)  # type: ignore[call-arg]


@pytest.fixture(scope="module")
def parsed() -> dict[str, tuple[str, set[str]]]:
    return _parse_example(_read_example())


class TestEveryKeyIsActuallyRead:
    """每个键都必须真的有人读 —— 否则就是让人白填的假配置。"""

    def test_keys_are_settings_fields_or_marked_external(self, parsed):
        fields = set(Settings.model_fields)
        orphans = sorted(
            key for key, (_value, marks) in parsed.items() if key.lower() not in fields and _MARK_EXTERNAL not in marks
        )
        assert not orphans, (
            f".env.example 里这些键既不是 Settings 字段、也没标 {_MARK_EXTERNAL}：{orphans}。"
            "要么删掉（没人读的配置比缺配置更坏 —— 填了以为生效了），"
            f"要么在键上方注释里加 {_MARK_EXTERNAL} 并写清谁读它。"
        )

    def test_external_marks_are_not_used_on_real_settings_fields(self, parsed):
        """`env-external` 只能用在真的不是 Settings 字段的键上。

        否则这个标记会变成绕过值比对的后门：标上它，值写错也不会被抓。
        """
        fields = set(Settings.model_fields)
        misused = sorted(
            key for key, (_value, marks) in parsed.items() if _MARK_EXTERNAL in marks and key.lower() in fields
        )
        assert not misused, f"这些键是真的 Settings 字段，不该标 {_MARK_EXTERNAL}：{misused}"

    def test_every_setting_that_matters_appears(self, parsed):
        """反向：`Settings` 里的字段不该在模板里整片缺席。

        不要求 100% 覆盖（有些字段是内部推导值），但覆盖率塌下来说明模板
        已经跟不上代码了。
        """
        fields = {n for n in Settings.model_fields}
        documented = {k.lower() for k in parsed}
        covered = fields & documented
        ratio = len(covered) / len(fields)
        assert ratio > 0.75, (
            f"Settings 有 {len(fields)} 个字段，.env.example 只写了 {len(covered)} 个（{ratio:.0%}）。"
            f"缺的示例：{sorted(fields - documented)[:12]}"
        )


class TestValuesMatchCodeDefaults:
    """值必须等于代码默认值，或显式说明为什么不同。"""

    def test_unmarked_values_equal_code_defaults(self, parsed):
        fields = set(Settings.model_fields)
        mismatches: list[str] = []
        for key, (value, marks) in sorted(parsed.items()):
            name = key.lower()
            if name not in fields or _MARK_DIFFERS in marks:
                continue
            expected = _code_default(name)
            if not _values_agree(name, value, expected):
                mismatches.append(f"{key}: 模板={value!r} 代码默认={expected!r}")
        assert not mismatches, (
            "这些键的值和 app/config.py 的默认值不一致，且没有标 "
            f"{_MARK_DIFFERS}：\n  " + "\n  ".join(mismatches) + "\n"
            f"要么改成一致，要么在键上方注释里加 {_MARK_DIFFERS} 并写出理由。"
        )

    def test_differs_marks_are_not_stale(self, parsed):
        """标了"故意不同"的键，值必须真的不同。

        值改回一致之后标记若留着，就成了一个永久后门：下次真写错也不会被抓。
        """
        fields = set(Settings.model_fields)
        stale: list[str] = []
        for key, (value, marks) in sorted(parsed.items()):
            name = key.lower()
            if name not in fields or _MARK_DIFFERS not in marks:
                continue
            if _values_agree(name, value, _code_default(name)):
                stale.append(key)
        assert not stale, f"这些键标了 {_MARK_DIFFERS} 但值其实和代码默认值一样，标记已过期，请删掉：{stale}"

    def test_weights_sum_to_one(self, parsed):
        """8 个权重之和必须是 1.0（ADR-006 启动断言）。

        模板里凑不齐 1.0 的话，照它填出来的 .env 会让应用**启动即崩**。
        """
        weights = {k: float(v) for k, (v, _m) in parsed.items() if k.startswith("WEIGHT_") and k != "WEIGHT_VERSION"}
        assert len(weights) == 8, f"应有 8 个权重键，解析到 {len(weights)} 个：{sorted(weights)}"
        total = sum(weights.values())
        assert abs(total - 1.0) < 1e-9, f"模板里的权重之和是 {total}，不是 1.0，照它填会启动失败"


class TestExampleIsSelfConsistent:
    """模板自身不能自相矛盾 —— 它比值写错更难被发现。"""

    def test_loading_example_does_not_flip_db_backend(self, parsed):
        """按模板加载出来的 backend，必须就是模板自己声明的那个。

        这条是实测踩到的坑：模板写 `DB_BACKEND=sqlite`，又打开了
        `DATABASE_URL=postgresql://…`，而 `_resolve_db_backend()` 会**反向**
        把 `db_backend` 改成 postgres。于是照模板复制出的 `.env` 连的是 PG,
        跟它自己写的那行完全相反 —— 不读代码的人无从察觉。
        """
        declared = parsed["DB_BACKEND"][0]
        loaded = _load_from_example(parsed)
        assert loaded.db_backend == declared, (
            f"模板声明 DB_BACKEND={declared}，但按模板加载出来实际是 "
            f"{loaded.db_backend} —— 模板自相矛盾。"
            "通常是因为 DATABASE_URL 那行没注释掉（它会反向改写 db_backend）。"
        )

    def test_example_loads_without_validation_error(self, parsed):
        """模板必须能被 `Settings` 成功加载。

        级联校验（evidence_emit⇒snapshot、resolver⇒evidence）写错顺序会
        直接抛异常 —— 那种模板等于教人把应用配崩。
        """
        loaded = _load_from_example(parsed)
        assert loaded.app_env == "development", "模板的 APP_ENV 应保持 development（生产值由部署时覆盖）"
        assert not loaded.is_production, "模板不该默认落到生产模式"

    def test_referenced_paths_exist(self, parsed):
        """模板里指向**随仓库提交的文件**的路径必须真的存在。

        此前 `SEED_DATA_PATH=data/seed_projects.json` 指向一个不存在的文件。

        这条**只查随仓库提交的文件**，不查运行时目录。第一版把
        `FETCHER_CACHE_DIR` 也放进来了，CI 立刻挂 —— `cache/` 是
        `_FileCache.__init__` 里 `mkdir(parents=True, exist_ok=True)`
        按需建出来的，本机因为跑过应用才有，全新 checkout 上并不存在。
        **又是同一个错：一个只在"已经运行过的机器"上为真的断言不是断言。**
        运行时目录改由下一条按"是否会被安全地自动创建"来验。
        """
        rel = parsed["SEED_DATA_PATH"][0]
        assert rel, "SEED_DATA_PATH 不该留空"
        assert (REPO_ROOT / rel).exists(), f"SEED_DATA_PATH={rel} 在仓库里不存在（真实默认是 scripts/seed.py）"

    def test_runtime_dirs_are_relative_and_inside_repo(self, parsed):
        """运行时按需创建的目录必须是仓库内的相对路径。

        不断言它存在（它由代码 `mkdir` 出来），但要挡住绝对路径 / `..` 逃逸 ——
        那会让缓存写到仓库外，跟 `DB_PATH` 解析到 `D:\\app\\data` 是同一个坑。
        """
        rel = parsed["FETCHER_CACHE_DIR"][0]
        assert rel, "FETCHER_CACHE_DIR 不该留空"
        parts = Path(rel).parts
        assert not Path(rel).is_absolute(), f"FETCHER_CACHE_DIR={rel} 不该是绝对路径"
        assert ".." not in parts, f"FETCHER_CACHE_DIR={rel} 不该用 .. 逃出仓库"


class TestParserSelfChecks:
    """解析器自己必须会失败 —— 一个读不到东西却依然全绿的解析器不是门禁。"""

    def test_parser_rejects_a_file_with_too_few_keys(self):
        with pytest.raises(AssertionError, match="明显偏少"):
            _parse_example("# only a comment\nFOO=bar\n")

    def test_marker_does_not_leak_across_a_blank_line(self):
        """空行截断注释块 —— 否则一个标记会顺着整节蔓延成整文件豁免。"""
        text = "\n".join([f"# {_MARK_DIFFERS}: 只该作用于 A", "A=1", "", "B=2"] + [f"K{i}=v" for i in range(120)])
        parsed = _parse_example(text)
        assert _MARK_DIFFERS in parsed["A"][1], "紧贴上方的标记应当生效"
        assert _MARK_DIFFERS not in parsed["B"][1], "隔了空行的键不该继承上一个键的豁免标记"

    def test_parser_reads_both_key_and_value(self):
        text = "\n".join(["FOO=0 8 * * *", "BAR="] + [f"K{i}=v" for i in range(120)])
        parsed = _parse_example(text)
        assert parsed["FOO"][0] == "0 8 * * *", "含空格的值（cron）必须完整读出，不能被截断"
        assert parsed["BAR"][0] == "", "留空的键应解析成空串，而不是被丢掉"

    def test_real_file_parses_to_a_plausible_size(self, parsed):
        assert len(parsed) > 140, f"真实 .env.example 只解析出 {len(parsed)} 个键，解析器可能漏读了"
