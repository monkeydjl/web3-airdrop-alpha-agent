"""拦截非法 UTF-8 文本文件，防止编码损坏再次进入仓库。

## 为什么需要这个检查

仓库里已有 3 个文档存在 UTF-8 损坏（`docs/OPERATIONS.md`、
`docs/OBSERVABILITY.md`、`docs/DATA_SOURCE_STRATEGY.md`，合计 1116 处）。
损坏形态：每个 3 字节中文字符的**第 3 字节被替换成 '?'**，前 2 字节完好 ——
典型的"以非 UTF-8 编码写回文件"造成的不可逆映射。

这类损坏的恶劣之处在于**静默**：文件还能打开、git 也照常提交，只是内容里多了
一堆 `?`。它在 git 历史里潜伏了 3 个提交才被发现，且其中一个文件的所有历史
版本都已损坏、无法恢复。

因此加这道机械检查：任何非法 UTF-8 的文本文件都拦下来，不让它进下一次提交。

## 用法

    python scripts/check_encoding.py            # 检查全仓（跳过已知损坏文件）
    python scripts/check_encoding.py --strict    # 连已知损坏文件也报错
    python scripts/check_encoding.py <路径...>   # 只检查指定文件（pre-commit 用）

退出码 0 = 全部合法；1 = 有非法文件。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# 需要检查的文本扩展名
TEXT_SUFFIXES = {
    ".md",
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".json",
    ".yml",
    ".yaml",
    ".txt",
    ".ps1",
    ".bat",
    ".css",
    ".sql",
    ".toml",
    ".cfg",
    ".ini",
}

SKIP_DIRS = {
    "node_modules",
    "venv",
    ".venv",
    ".git",
    "htmlcov",
    ".pytest_cache",
    ".pytest_tmp",
    ".next",
    "__pycache__",
    ".ruff_cache",
    ".mypy_cache",
}

# 已知的历史损坏文件：默认只警告不阻断，避免这道检查一上线就把所有提交卡死。
# 修复完成后请从这里删除对应条目 —— 清单为空是目标状态。
KNOWN_BROKEN = {
    "docs/OPERATIONS.md",
    "docs/OBSERVABILITY.md",
    "docs/DATA_SOURCE_STRATEGY.md",
}


def describe_first_error(data: bytes) -> str:
    try:
        data.decode("utf-8")
    except UnicodeDecodeError as e:
        line = data[: e.start].count(b"\n") + 1
        ctx = data[max(0, e.start - 24) : e.start + 12]
        return f"第 {line} 行 (offset {e.start}) 非法字节 {data[e.start : e.end]!r}；上下文 {ctx!r}"
    return ""


def count_errors(data: bytes) -> int:
    n = 0
    i = 0
    while i < len(data):
        try:
            data[i:].decode("utf-8")
            break
        except UnicodeDecodeError as e:
            n += 1
            i += e.start + max(1, e.end - e.start)
    return n


def iter_repo_files() -> list[Path]:
    out: list[Path] = []
    stack = [REPO_ROOT]
    while stack:
        cur = stack.pop()
        try:
            entries = list(cur.iterdir())
        except OSError:
            continue
        for p in entries:
            if p.is_dir():
                if p.name not in SKIP_DIRS:
                    stack.append(p)
            elif p.suffix.lower() in TEXT_SUFFIXES:
                out.append(p)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="*", help="要检查的文件（缺省=全仓扫描）")
    ap.add_argument("--strict", action="store_true", help="已知损坏文件也判为失败")
    args = ap.parse_args()

    files = [Path(p) for p in args.paths] if args.paths else iter_repo_files()

    failures: list[tuple[str, int, str]] = []
    known_hits: list[tuple[str, int]] = []

    for path in files:
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        try:
            data.decode("utf-8")
            continue
        except UnicodeDecodeError:
            pass

        try:
            rel = path.resolve().relative_to(REPO_ROOT).as_posix()
        except ValueError:
            rel = path.as_posix()
        n = count_errors(data)

        if rel in KNOWN_BROKEN and not args.strict:
            known_hits.append((rel, n))
        else:
            failures.append((rel, n, describe_first_error(data)))

    for rel, n in known_hits:
        print(f"[known] {rel}：{n} 处非法 UTF-8（已登记的历史损坏，待修复）")

    if failures:
        print()
        print(f"[FAIL] {len(failures)} 个文件不是合法 UTF-8：")
        for rel, n, detail in failures:
            print(f"  {rel}  （{n} 处）")
            print(f"    {detail}")
        print()
        print("修复提示：用 UTF-8 重新保存该文件。若是中文字符被替换成 '?'，")
        print("说明写入时用了非 UTF-8 编码，原字符已不可逆丢失 —— 参见")
        print("scripts/repair_utf8_docs.py 与 scripts/verify_utf8_repair.py。")
        return 1

    if known_hits:
        print()
        print(f"检查通过（{len(files)} 个文件），但仍有 {len(known_hits)} 个已登记的损坏文件待修复。")
    else:
        print(f"检查通过：{len(files)} 个文本文件全部是合法 UTF-8。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
