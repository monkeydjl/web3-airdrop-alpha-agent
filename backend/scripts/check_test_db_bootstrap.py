"""测试建库卫生守卫（conftest 会话级兜底的回归防线）。

背景：不少测试文件直连 DB_PATH（``get_connection()`` / ``ProjectRepository()``
等）却自身从不 ``init_db()``——历史上靠两条隐形路径侥幸通过：

1. 主仓库里历史残留的 ``data/test.db`` 带着旧 schema；
2. conftest.py 的 ``pytest_configure`` 会话级兜底 init_db。

全新 checkout / CI runner 上「单跑一个文件」时两条路径都不存在，
首个触碰 DB 的用例直接 ``no such table``。2026-09-28 已为 7 个此类
文件补了显式 autouse 建库 fixture；本守卫防止新的隐式依赖再混进来。

判定规则（对 ``tests/**/test_*.py``）：

- **直连 DB 信号**（满足其一即视为依赖默认库）：
  ``from app.db import ...`` / ``import app.db`` /
  ``from app.repository import ...`` / 调用 ``sqlite3.connect(...)``
  指向 DB_PATH 变量 / 字符串常量 ``"DB_PATH"``
- **自救信号**（满足其一即豁免，说明 schema 有明确获取路径）：
  使用 ``init_db`` / 使用 ``create_app`` / ``from app.main import app``
  （模块级 app 实例已随 import 建库）/ 文件内自建表（``CREATE TABLE``
  字符串常量）/ 自建独立库（``sqlite3.connect(":memory:")`` 或
  ``tmp_path`` 下的文件）

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
WHITELIST = {
    # connection_scope 契约测试：只做 SELECT 1 / 异常路径，不触碰任何表——
    # sqlite3 对不存在的库文件自动建空文件即可满足，无 schema 需求。
    "tests/test_connection_scope.py",
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


def check_file(path: Path) -> tuple[list[str], list[str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    strings = _string_constants(tree)
    return (
        _direct_db_signals(tree, strings),
        _self_sufficiency_signals(tree, strings),
    )


def main() -> int:
    _force_utf8_stdio()

    violations: list[tuple[Path, list[str]]] = []
    scanned = 0
    for path in sorted(TESTS_DIR.rglob("test_*.py")):
        scanned += 1
        if path.relative_to(BACKEND_DIR).as_posix() in WHITELIST:
            continue
        try:
            needs, has = check_file(path)
        except SyntaxError as exc:  # pragma: no cover — tests/ 不应有语法错误
            print(f"::error::{path.relative_to(BACKEND_DIR)} 语法错误: {exc}")
            return 1
        if needs and not has:
            rel = path.relative_to(BACKEND_DIR).as_posix()
            violations.append((path, needs))

    if violations:
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
        return 1

    print(f"✅ 测试建库守卫通过：{scanned} 个测试文件均有明确 schema 获取路径")
    return 0


if __name__ == "__main__":
    sys.exit(main())
