"""测试建库卫生守卫（conftest 会话级兜底的回归防线）。

背景：不少测试文件直连 DB_PATH（``get_connection()`` / ``ProjectRepository()``
等）却自身从不 ``init_db()``——历史上靠两条隐形路径侥幸通过：

1. 主仓库里历史残留的 ``data/test.db`` 带着旧 schema；
2. conftest.py 的 ``pytest_configure`` 会话级兜底 init_db。

全新 checkout / CI runner 上「单跑一个文件」时两条路径都不存在，
首个触碰 DB 的用例直接 ``no such table``。2026-09-28 已为 7 个此类
文件补了显式 autouse 建库 fixture；本守卫防止新的隐式依赖再混进来。

判定规则（对 ``tests/**/test_*.py``）：

**规则一（schema 来源）**

- **直连 DB 信号**（满足其一即视为依赖默认库）：
  ``from app.db import ...`` / ``import app.db`` /
  ``from app.repository import ...`` / 调用 ``sqlite3.connect(...)``
  指向 DB_PATH 变量 / 字符串常量 ``"DB_PATH"``
- **自救信号**（满足其一即豁免，说明 schema 有明确获取路径）：
  使用 ``init_db`` / 使用 ``create_app`` / ``from app.main import app``
  （模块级 app 实例已随 import 建库）/ 文件内自建表（``CREATE TABLE``
  字符串常量）/ 自建独立库（``sqlite3.connect(":memory:")`` 或
  ``tmp_path`` 下的文件）

**规则二（数据来源 / 残留行依赖）**

直连默认库的文件里出现 **SELECT 读取**、却没有任何写路径
（INSERT/UPDATE/REPLACE SQL 或 repository 导入）也没有自管库重定向
（``settings.db_path`` / ``:memory:``）→ 报违规：这类文件在全新空库上
要么读到空集失败，要么读到上一轮/其他文件残留的行而侥幸通过
（跨文件顺序耦合）。修复三选一：tmp_path 重定向自管库 / 同文件
INSERT 自播种后读回 / 核查后登记 READS_DEFAULT_DB_WHITELIST。

**规则三（替身目标漂移 / 2026-09-29 专项审计新增）**

tests 内 ``patch("app.db.get_connection", ...)`` → 报违规。§13.3 迁移后
消费路径走 ``connection_scope``，但其 own 分支经**模块全局名**调
``get_connection()``——patch 它经这条**活缝隙**看似生效，实则把测试钉死
在实现细节上：own 分支改为函数内 import / 直连工厂时 patch 静默失效，
测试开始碰真实默认库或测错路径。修复：patch 消费点（消费者模块的
``connection_scope`` 名字；函数内 import 时等价于
``app.db.connection_scope`` 本体）。被测对象就是 db.py 本体的可登记
PATCH_GET_CONNECTION_WHITELIST（须附理由）。

退出码：发现违规 → 1（CI 失败）；否则 0。纯标准库实现，与
check_connection_hygiene.py 同款 ``_force_utf8_stdio`` 防护（Windows
ANSI 代码页下 print 中文/emoji 不崩）。
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
TESTS_DIR = BACKEND_DIR / "tests"


def _force_utf8_stdio() -> None:
    """Windows 默认 ANSI 代码页编不了中文/✅，先重配 stdout/stderr 为 UTF-8。

    守卫的退出码才是契约，输出乱码不退出才是硬要求；getattr 守卫兼容
    pytest capsys 等替换流。
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def _string_constants(tree: ast.AST) -> set[str]:
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            out.add(node.value)
    return out


def _uses_name(tree: ast.AST, name: str) -> bool:
    """裸名或属性尾名都算（``init_db`` 与 ``db_module.init_db`` 等价）。"""
    return any(
        (isinstance(node, ast.Name) and node.id == name) or (isinstance(node, ast.Attribute) and node.attr == name)
        for node in ast.walk(tree)
    )


def _direct_db_signals(tree: ast.AST, strings: set[str]) -> list[str]:
    """文件依赖「默认库 schema」的信号清单。"""
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == "app.db" or module == "app.repository":
                names = {a.name for a in node.names}
                out.append(f"from {module} import {', '.join(sorted(names))}")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "app.db" or alias.name == "app.repository":
                    out.append(f"import {alias.name}")
        elif isinstance(node, ast.Call):
            func = node.func
            # sqlite3.connect(DB_PATH) —— 指向共享默认库；:memory:/tmp_path
            # 是自建库，由自救信号覆盖，不在此拦。
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "connect"
                and isinstance(func.value, ast.Name)
                and func.value.id == "sqlite3"
                and node.args
                and isinstance(node.args[0], ast.Name)
                and node.args[0].id == "DB_PATH"
            ):
                out.append("sqlite3.connect(DB_PATH)")
    if "DB_PATH" in strings and _uses_name(tree, "DB_PATH"):
        out.append("DB_PATH 引用")
    return out


# 文件级豁免（正当理由注明，与 check_connection_hygiene.py 同款风格）。
# 规则一（建库）：key 在 NEEDS_SCHEMA_WHITELIST 中则豁免缺 schema 判定。
# 规则二（残留数据）：key 在 READS_DEFAULT_DB_WHITELIST 中则豁免
# 「直读默认库且无自播种」判定。
WHITELIST = {
    # connection_scope 契约测试：只做 SELECT 1 / 异常路径，不触碰任何表——
    # sqlite3 对不存在的库文件自动建空文件即可满足，无 schema 需求。
    "tests/test_connection_scope.py",
}

# 规则二豁免：文件确实直读默认库，但读的是**本文件同轮自建的数据**
# （写路径经 repository 封装，静态规则不可见），或读到的结果与库内容
# 无关。逐个核查后登记，禁止无注释豁免。
READS_DEFAULT_DB_WHITELIST: dict[str, str] = {}

# 规则三（替身目标漂移）豁免：key 在 PATCH_GET_CONNECTION_WHITELIST 中
# 则豁免「tests 内 patch app.db.get_connection」判定。豁免必须附理由：
# - tests/test_db_init.py：被测对象就是 get_connection/init_db 本体
#   （db.py 的单测），patch 它是测试手段不是消费点误置；
# - tests/test_gdpr.py：db_conn fixture 双保险（已 patch 消费点
#   app.routers.v1.user_data.connection_scope，get_connection 是底座
#   兼容层，消费点 patch 惯例已遵守）。
PATCH_GET_CONNECTION_WHITELIST: dict[str, str] = {
    "tests/test_db_init.py": "被测对象就是 db.py 本体，patch 是测试手段",
    "tests/test_gdpr.py": "消费点 connection_scope 已 patch，get_connection 是双保险兼容层",
}


def _self_sufficiency_signals(tree: ast.AST, strings: set[str]) -> list[str]:
    """文件自带 schema 获取路径的信号清单。"""
    out: list[str] = []
    if _uses_name(tree, "init_db"):
        out.append("init_db")
    if _uses_name(tree, "create_app"):
        out.append("create_app")
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.ImportFrom)
            and (node.module or "") == "app.main"
            and any(a.name == "app" for a in node.names)
        ):
            out.append("from app.main import app")
    upper = {s.strip().upper() for s in strings}
    if any(s.startswith("CREATE TABLE") for s in upper):
        out.append("自建表 (CREATE TABLE)")
    if ":memory:" in strings:
        out.append("自建库 (:memory:)")
    # settings.db_path 被 monkeypatch/重定向到 tmp_path：自管库路径，
    # 不依赖默认库的 schema（如 test_verify_opportunity_shadow）。
    if "db_path" in strings:
        out.append("settings.db_path 重定向")
    return out


def _sql_statement_kinds(strings: set[str]) -> set[str]:
    """从字符串常量里识别 SQL 语句类别（SELECT/INSERT/UPDATE/REPLACE）。

    SELECT 只有带 ``FROM``（表读）才计数——``SELECT 1`` 这类连接探针
    不是数据读取，不应触发残留行判定。
    """
    kinds: set[str] = set()
    for s in strings:
        head = s.strip().lstrip("(\r\n \t").upper()
        for kw in ("SELECT", "INSERT", "UPDATE", "REPLACE"):
            if not head.startswith(kw):
                continue
            if kw == "SELECT" and " FROM " not in head:
                continue
            kinds.add(kw)
    return kinds


def _has_api_writes(tree: ast.AST) -> bool:
    """文件内是否有 TestClient 风格的 HTTP 写调用（client.post/put/...）。

    经 API 写入的数据属于本文件自播种，读回断言在全新空库上也成立。
    """
    write_verbs = {"post", "put", "patch", "delete"}
    return any(
        isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in write_verbs
        for node in ast.walk(tree)
    )


def check_file(path: Path) -> tuple[list[str], list[str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    strings = _string_constants(tree)
    return (
        _direct_db_signals(tree, strings),
        _self_sufficiency_signals(tree, strings),
    )


def check_residue_reads(path: Path) -> list[str] | None:
    """规则二：直读默认库且无自播种 → 疑似依赖残留行。

    判定（全部满足才报）：
    1. 直连默认库（规则一的直连信号非空）；
    2. 无自管库重定向（settings.db_path / :memory:）；
    3. 文件内有 SELECT 读取；
    4. 文件内没有任何写路径（INSERT/UPDATE/REPLACE SQL 或 repository
       导入——repo.add 等封装写入静态不可见，按可自播种对待）。

    全新空库上这类文件要么 no such table、要么读到空集断言失败，
    或更糟：读到上一轮/其他文件残留的行而侥幸通过（顺序耦合）。
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    strings = _string_constants(tree)
    needs = _direct_db_signals(tree, strings)
    if not needs:
        return None
    self_sufficiency = _self_sufficiency_signals(tree, strings)
    if ":memory:" in strings or "db_path" in strings:
        return None  # 自管库重定向
    kinds = _sql_statement_kinds(strings)
    if "SELECT" not in kinds:
        return None
    if kinds & {"INSERT", "UPDATE", "REPLACE"}:
        return None  # 同文件自播种后读回，合法
    if _has_api_writes(tree):
        return None  # 经 API client 写入自播种，读回合法
    if any("repository" in s for s in self_sufficiency) or any("repository" in n for n in needs):
        return None  # 经 repository 封装写入，视为可自播种
    return sorted(needs)


def check_stub_target_drift(path: Path) -> list[str] | None:
    """规则三：tests 内 patch ``app.db.get_connection`` → 替身目标漂移。

    背景（2026-09-29 专项审计）：§13.3 迁移后消费路径走 connection_scope，
    但 connection_scope 的 own 分支是 ``db = get_connection()``（模块全局
    运行时解析），patch app.db.get_connection 经这条**活缝隙**仍会生效——
    看似隔离，实则把测试钉死在一个实现细节上：own 分支一旦改为函数内
    import、直连工厂或连接池，patch 静默失效，测试开始碰真实默认库或
    测错路径。正确做法是 patch 消费点（消费者模块的 connection_scope
    名字；函数内 import 时等价于 app.db.connection_scope 本体）。

    判定（两种形态，覆盖裸 patch 与方法调用）：
    1. dotted 字符串目标：``patch("app.db.get_connection", ...)`` /
       ``monkeypatch.setattr("app.db.get_connection", ...)`` ——
       函数名是裸 Name（``from unittest.mock import patch``）或方法
       Attribute（``mock.patch`` / ``monkeypatch.setattr``）都要抓；
    2. 模块+名分离：``setattr(db_module, "get_connection", ...)``。
    已知盲区（docstring 记录）：``patch.object(db_module, ...)`` 形态
    不检测（罕见，出现时靠人工审查兜底）。
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    hits: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        # 裸名（from unittest.mock import patch / as mock_patch）与方法名都算
        if isinstance(func, ast.Name):
            call_name = func.id
        elif isinstance(func, ast.Attribute):
            call_name = func.attr
        else:
            continue
        is_patch_call = call_name == "setattr" or call_name.startswith("patch")
        if not is_patch_call or not node.args:
            continue
        # 形态一：dotted 字符串 "app.db.get_connection"
        target = node.args[0]
        if isinstance(target, ast.Constant) and target.value == "app.db.get_connection":
            hits.append(f"line {node.lineno}: {call_name}('app.db.get_connection', ...)")
            continue
        # 形态二：setattr(<db 模块名>, "get_connection", ...)
        if call_name == "setattr" and len(node.args) >= 2:
            base, name_arg = node.args[0], node.args[1]
            if isinstance(name_arg, ast.Constant) and name_arg.value == "get_connection":
                base_is_db = (isinstance(base, ast.Name) and base.id in {"db", "db_module", "db_mod", "dbm"}) or (
                    isinstance(base, ast.Attribute) and base.attr == "db"
                )
                if base_is_db:
                    hits.append(f"line {node.lineno}: setattr(<db 模块>, 'get_connection', ...)")
    return hits or None


def main() -> int:
    _force_utf8_stdio()

    violations: list[tuple[Path, list[str]]] = []
    residue: list[tuple[Path, list[str]]] = []
    stub_drift: list[tuple[Path, list[str]]] = []
    scanned = 0
    for path in sorted(TESTS_DIR.rglob("test_*.py")):
        scanned += 1
        rel = path.relative_to(BACKEND_DIR).as_posix()
        try:
            needs, has = check_file(path)
            if rel not in WHITELIST and needs and not has:
                violations.append((path, needs))
            if rel not in READS_DEFAULT_DB_WHITELIST:
                hit = check_residue_reads(path)
                if hit:
                    residue.append((path, hit))
            if rel not in PATCH_GET_CONNECTION_WHITELIST:
                hit = check_stub_target_drift(path)
                if hit:
                    stub_drift.append((path, hit))
        except SyntaxError as exc:  # pragma: no cover — tests/ 不应有语法错误
            print(f"::error::{path.relative_to(BACKEND_DIR)} 语法错误: {exc}")
            return 1

    failed = False
    if violations:
        failed = True
        print("❌ 测试建库守卫发现违规（测试直连 DB_PATH 但无任何自救建库路径）：\n")
        for path, needs in violations:
            rel = path.relative_to(BACKEND_DIR).as_posix()
            print(f"  {rel}")
            print(f"    直连信号: {'; '.join(sorted(set(needs)))}")
        print(
            "\n修复方式：在文件内加显式 autouse fixture 幂等建库（不删库）：\n"
            "    @pytest.fixture(autouse=True)\n"
            "    def _ensure_db_schema():\n"
            "        from app.db import init_db\n"
            "        init_db()\n"
            "  或改走 create_app/TestClient with 块 / 自建 :memory: 库。"
            "参考 tests/test_daily_briefing.py。"
        )
    if residue:
        failed = True
        print("\n❌ 残留数据依赖守卫发现违规（直读默认库且无自播种路径）：\n")
        for path, needs in residue:
            rel = path.relative_to(BACKEND_DIR).as_posix()
            print(f"  {rel}")
            print(f"    直连信号: {'; '.join(sorted(set(needs)))}")
        print(
            "\n修复方式（三选一）：\n"
            "  1. monkeypatch settings.db_path 到 tmp_path 并自建 schema + 种子数据；\n"
            "  2. 同文件内先 INSERT 自建数据再读回（全新空库上也要成立）；\n"
            "  3. 确认读的是本文件经 repository 写入的数据后，登记"
            " READS_DEFAULT_DB_WHITELIST（须附理由）。"
        )
    if stub_drift:
        failed = True
        print(
            "\n❌ 替身目标漂移守卫发现违规（tests 内 patch app.db.get_connection）：\n"
            "\n"
            "  connection_scope 的 own 分支经模块全局名调 get_connection()，\n"
            "  patch 它看似生效、实则把测试钉死在实现细节上（own 分支改为\n"
            "  函数内 import / 直连工厂时静默失效，测试开始碰真实默认库）。\n"
        )
        for path, hits in stub_drift:
            rel = path.relative_to(BACKEND_DIR).as_posix()
            print(f"  {rel}")
            for hit in hits:
                print(f"    {hit}")
        print(
            "\n修复方式：改为 patch 消费点——\n"
            "  - 消费者模块顶部 import connection_scope → patch\n"
            "    '<消费者模块>.connection_scope'；\n"
            "  - 消费者函数内 from app.db import connection_scope → patch\n"
            "    'app.db.connection_scope'（名字解析源）。\n"
            "  被测对象就是 db.py 本体的（如 test_db_init）可登记\n"
            "  PATCH_GET_CONNECTION_WHITELIST（须附理由）。"
        )
    if failed:
        return 1

    print(f"✅ 测试数据守卫通过：{scanned} 个测试文件均有明确 schema 与数据来源路径")
    return 0


if __name__ == "__main__":
    sys.exit(main())
