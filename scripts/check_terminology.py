#!/usr/bin/env python
"""术语回退检查（pre-commit 钩子）。

防止「评分决策引擎」术语回退（约定见 CLAUDE.md §1 / CONVENTIONS.md §3.5 /
docs/GLOSSARY.md §2）：

  禁用写法                正确写法
  ---------------------   --------------------------
  评分引擎                评分决策引擎（指整个评分子系统时）
  评分大脑                评分决策引擎
  scoring engine          Scoring Decision Engine

注意：「评分决策引擎」不含子串「评分引擎」，故朴素匹配不会误伤正确写法。
「规则引擎」是合法术语（ADR-001 定义的默认打分路径），不在禁用列表。

用法：
  python scripts/check_terminology.py [file ...]   # pre-commit 传入暂存文件
  python scripts/check_terminology.py --all        # 全仓扫描（CI 可用）

退出码：0 = 通过；1 = 发现禁用术语。
"""

from __future__ import annotations

import os
import re
import subprocess
import sys

# (禁用模式, 正确写法提示)
FORBIDDEN: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"评分引擎"), "评分决策引擎"),
    (re.compile(r"评分大脑"), "评分决策引擎"),
    (re.compile(r"scoring engine", re.IGNORECASE), "Scoring Decision Engine"),
]

# 只检查这些扩展名的文本文件
SCAN_EXTS = {".md", ".py", ".html", ".js", ".ts", ".tsx", ".json", ".yaml", ".yml", ".txt"}

# 豁免：检查脚本自身（含禁用模式定义）
EXEMPT_BASENAMES = {"check_terminology.py"}


def iter_tracked_files() -> list[str]:
    """--all 模式：列出 git 跟踪的待检文件。"""
    out = subprocess.run(
        ["git", "ls-files"], capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    if out.returncode != 0:
        print("[check_terminology] git ls-files 失败，退回空列表", file=sys.stderr)
        return []
    return [line.strip() for line in out.stdout.splitlines() if line.strip()]


def should_scan(path: str) -> bool:
    if os.path.basename(path) in EXEMPT_BASENAMES:
        return False
    return os.path.splitext(path)[1].lower() in SCAN_EXTS


def check_file(path: str) -> list[str]:
    """返回违规信息列表（空 = 通过）。"""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
    except OSError as exc:
        return [f"{path}: 读取失败（{exc}）"]

    violations: list[str] = []
    for lineno, line in enumerate(lines, start=1):
        for pattern, suggestion in FORBIDDEN:
            if pattern.search(line):
                violations.append(
                    f"{path}:{lineno}: 发现禁用术语「{pattern.pattern}」，"
                    f"请改用「{suggestion}」（见 docs/GLOSSARY.md §2）"
                )
    return violations


def main(argv: list[str]) -> int:
    if "--all" in argv:
        files = [f for f in iter_tracked_files() if should_scan(f)]
    else:
        files = [f for f in argv[1:] if should_scan(f)]

    all_violations: list[str] = []
    for path in files:
        all_violations.extend(check_file(path))

    if all_violations:
        print("术语回退检查未通过：\n")
        for v in all_violations:
            print(f"  {v}")
        print(
            "\n约定：指代整个评分子系统用「评分决策引擎 / Scoring Decision Engine」；"
            "「规则引擎」仅指 LLM 关闭时的默认打分路径（CLAUDE.md §1 / CONVENTIONS.md §3.5）。"
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
