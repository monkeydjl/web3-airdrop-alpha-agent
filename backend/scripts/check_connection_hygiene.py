"""连接卫生守卫（CONVENTIONS.md §13.3 的机器可执行版本）。

背景：2026-09-26 的 17.1.26 事故里，`LeaderElector` 对 db_override **借用**连接
执行了 `with self.conn_factory() as conn:`，`DbConnection.__exit__` 一律 close，
把 lifespan 的共享连接关掉了。事后所有权判定已统一到 `app.db.connection_scope`
（own/borrow 唯一权威实现），全仓短作用域建连也已全部迁移完毕。

本守卫防止两种危险形态再次出现在 `app/` 下：

1. **裸 with**：``with get_connection() as conn:`` —— 与 connection_scope()
   语义相同但绕过了统一入口；更糟的是它对「可能是借用的连接」零防御
   （``with conn:`` 一律 close）。
2. **手写 finally close**：``conn = get_connection()`` 后跟 ``finally: conn.close()``
   —— rollback/commit 顺序极易出错（17.1.26 同源），一律走 connection_scope()。

白名单（合法豁免，都有注释说明）：
- ``app/db.py``：connection_scope 自身的实现与 docstring。
- ``app/main.py``：lifespan 是 app 连接的**所有权持有方**（own/borrow 判定的
  来源），作用域横跨整个 yield，用 try/finally 直接实现。

退出码：发现违规 → 1（CI 失败）；否则 0。设计为纯标准库、无第三方依赖，
lint job 里一条 ``python scripts/check_connection_hygiene.py`` 即可运行，
本地同样可跑。
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1] / "app"

# 相对 app/ 的白名单文件（POSIX 风格斜杠）。
WHITELIST = {
    "db.py",  # connection_scope 实现本体
    "main.py",  # lifespan：所有权持有方，跨 yield 的 try/finally
}

# 触发守卫的建连入口（当前唯一合法入口是 connection_scope）。
_ENTRY_NAMES = {"get_connection"}


def _is_get_connection_call(node: ast.AST) -> bool:
    """get_connection(...) 调用（含 from app.db import get_connection 形态）。"""
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _ENTRY_NAMES


def _violations_in_with(tree: ast.AST) -> list[tuple[int, str]]:
    """with get_connection() as X: —— 裸 with 建连。"""
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.With, ast.AsyncWith)):
            continue
        for item in node.items:
            if _is_get_connection_call(item.context_expr):
                out.append((node.lineno, "with get_connection() as ... （应改用 connection_scope()）"))
    return out


def _violations_in_finally_close(tree: ast.AST) -> list[tuple[int, str]]:
    """conn = get_connection() ... finally: conn.close() —— 手写作用域。"""
    out: list[tuple[int, str]] = []

    # 收集 try/finally 块里被 close 的名字（X.close()）
    finally_closes: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        for handler in node.finalbody:
            for sub in ast.walk(handler):
                if (
                    isinstance(sub, ast.Call)
                    and isinstance(sub.func, ast.Attribute)
                    and sub.func.attr == "close"
                    and isinstance(sub.func.value, ast.Name)
                ):
                    finally_closes.add(sub.func.value.id)

    if not finally_closes:
        return out

    # 找 X = get_connection() 赋值
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not _is_get_connection_call(node.value):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id in finally_closes:
                out.append(
                    (
                        node.lineno,
                        f"conn = get_connection() + finally close（变量 {target.id}）应改用 connection_scope()",
                    )
                )
    return out


def _force_utf8_stdio() -> None:
    """Windows 默认 ANSI 代码页（如 GBK）编不了 ✅/❌，print 直接 UnicodeEncodeError，
    让守卫在「发现违规与否」之前就非零退出——假阳性比漏报更糟。

    守卫的退出码才是契约，输出乱码不退出才是硬要求：stdout/stderr 若是文本流
    则重配为 UTF-8（极端环境编不了的字符降级为 ? 而非崩溃）；CI（Linux）
    本就是 UTF-8，重配为等值 no-op。getattr 守卫兼容 pytest capsys 等替换流。
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def check_file(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return _violations_in_with(tree) + _violations_in_finally_close(tree)


def main() -> int:
    _force_utf8_stdio()

    violations: list[tuple[Path, int, str]] = []
    for path in sorted(APP_DIR.rglob("*.py")):
        rel = path.relative_to(APP_DIR).as_posix()
        # 白名单在遍历层判断：白名单文件（db.py / main.py）即使内容含模式也整体跳过，
        # 不做单点豁免——它们的豁免理由是文件级的（实现本体 / 所有权持有方）。
        if rel in WHITELIST or path.name in WHITELIST:
            continue
        try:
            for lineno, message in check_file(path):
                violations.append((path, lineno, message))
        except SyntaxError as exc:  # pragma: no cover — app/ 不应有语法错误
            print(f"::error::{rel} 语法错误，守卫无法解析: {exc}")
            return 1

    if violations:
        print("❌ 连接卫生守卫发现违规（CONVENTIONS.md §13.3：建连统一走 app.db.connection_scope）：\n")
        for path, lineno, message in violations:
            print(f"  {path.relative_to(APP_DIR.parent)}:{lineno}  {message}")
        print(
            "\n修复方式：短作用域用 `with connection_scope() as conn:`；"
            "注入共享连接用 `connection_scope(conn)`（borrow，永不 close）；"
            "factory 消费者用 `connection_scope(factory=..., owns=...)`。"
        )
        return 1

    print("✅ 连接卫生守卫通过：app/ 下无裸 with get_connection() / 手写 finally close 模式")
    return 0


if __name__ == "__main__":
    sys.exit(main())
