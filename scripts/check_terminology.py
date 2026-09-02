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

## 行级豁免

有些行**必须**写出禁用术语才能表达意思，主要两类：

1. **定义规则本身的文档**（CLAUDE.md 里"拦截「评分引擎 / 评分大脑」"那句）
2. **引用历史记录**（会话记忆里引用的旧 git commit message，改了就是篡改记录）

这类行在行尾加 `terminology-ok` 标记即可豁免（Markdown 里用 HTML 注释、
代码里用普通注释）。**标记是逐行的、显式的、可 grep 审计的** ——
不做整文件豁免，否则真正的术语回退会藏在被豁免的文件里。

用法：
  python scripts/check_terminology.py [file ...]   # pre-commit 传入暂存文件
  python scripts/check_terminology.py --all        # 全仓扫描（CI 用）

退出码：0 = 通过；1 = 发现禁用术语。
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

# 本文件位于 <repo>/scripts/，故仓库根是上一级。
# 不用 `git rev-parse --show-toplevel`：那还得先起一个子进程，而这个路径
# 关系是仓库结构的一部分，挪动 scripts/ 目录本来就该改这里。
REPO_ROOT = Path(__file__).resolve().parent.parent

# (禁用模式, 正确写法提示)
FORBIDDEN: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"评分引擎"), "评分决策引擎"),
    (re.compile(r"评分大脑"), "评分决策引擎"),
    (re.compile(r"scoring engine", re.IGNORECASE), "Scoring Decision Engine"),
]

# 行级豁免标记（见模块文档字符串）
ALLOW_MARK = "terminology-ok"

# 只检查这些扩展名的文本文件
SCAN_EXTS = {".md", ".py", ".html", ".js", ".ts", ".tsx", ".json", ".yaml", ".yml", ".txt"}

# 豁免：检查脚本自身（含禁用模式定义）
EXEMPT_BASENAMES = {"check_terminology.py"}


def iter_tracked_files() -> list[str]:
    """--all 模式：列出 git 跟踪的待检文件，路径一律相对**仓库根**。

    用 shutil.which 解析 git 全路径，避免依赖 PATH 查找顺序（ruff S607）。

    `--full-name` 与 `cwd=REPO_ROOT` 两个都要，缺一不可：

    - 裸 `git ls-files` 返回的是相对 **cwd** 的路径，且**只列 cwd 子树**。
      CI 里 pytest 的 `working-directory` 是 `backend/`（ci.yml §31），
      于是这道闸门在 CI 上只扫到 314 个 backend 文件，而 `docs/` 的 69 个
      文档、根目录 CHANGELOG.md、frontend-next/ 全部 223 个待检文件从未被扫过
      —— 而术语约定主要就是给文档用的，等于锁错了地方
      （2026-09-02 实测发现：本机 `--all` 报 4 处回退，同样的内容在 CI 上全绿）。
    - `--full-name` 让输出始终相对仓库根，`cwd` 让 git 从根开始枚举。
      只加 `--full-name` 仍然只列 cwd 子树，只改 `cwd` 则调用方拿到的
      相对路径会与自己的 cwd 不一致。

    调用方需自行把返回的相对路径拼到 REPO_ROOT 上（`check_file` 收绝对路径）。
    """
    git = shutil.which("git")
    if git is None:
        print("[check_terminology] 找不到 git，退回空列表", file=sys.stderr)
        return []
    out = subprocess.run(
        [git, "ls-files", "--full-name"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        cwd=REPO_ROOT,
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
        if ALLOW_MARK in line:
            continue  # 行级显式豁免（见模块文档字符串）
        for pattern, suggestion in FORBIDDEN:
            if pattern.search(line):
                violations.append(
                    f"{path}:{lineno}: 发现禁用术语「{pattern.pattern}」，"
                    f"请改用「{suggestion}」（见 docs/GLOSSARY.md §2）"
                )
    return violations


def main(argv: list[str]) -> int:
    if "--all" in argv:
        # iter_tracked_files 返回相对仓库根的路径，必须拼成绝对路径 ——
        # 否则从 backend/ 调用时会去 backend/docs/... 找文件，全部读取失败。
        files = [str(REPO_ROOT / f) for f in iter_tracked_files() if should_scan(f)]
    else:
        # pre-commit 传入的路径相对 cwd（钩子在仓库根执行），原样使用。
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
        print(f"若该行确实必须写出禁用术语（定义规则本身、引用历史记录），在行尾加 {ALLOW_MARK} 标记。")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
