"""灰区空库酸测（守卫规则二「静态不可见」边界的动态复验）。

背景：`check_test_db_bootstrap.py` 是纯静态 AST 守卫，只拦得住**有信号**
的违规；经 service 层间接使用默认库的文件静态不可见（§13.4 已知边界），
靠本酸测覆盖。方法学与 2026-09-28 全量审计一致：

- 复用守卫的 AST 函数**动态枚举**灰区：`_direct_db_signals` 非空
  （直连默认库）+ 含 SELECT 表读 + `check_residue_reads` 返回 None
  （走了规则二豁免路径）。守卫规则/白名单调整后清单自动跟随，零硬编码。
- 逐文件删除默认库三件套（test.db / -wal / -shm）→ 串行 pytest 单跑。
  串行是刻意的：xdist 每 worker 独立库文件，测不出「单文件空库」行为。
  conftest 的默认库在**仓库根** data/test.db（conftest 在 backend/tests/
  三层向上）——清库删仓库根 data/，不是 backend/data/（曾误删致假绿）。
- 探针抽样：「直连无表读」桶抽 5 个文件（无 SELECT 表读，静态上不依赖
  库中数据，酸测只验证空库上不因缺 schema 红）。抽样用确定性种子
  （--probe-seed 可覆盖），同树重跑结果稳定、diff 友好。

用法（backend/ 下）::

    venv/Scripts/python.exe scripts/verify_test_db_isolation.py
    venv/Scripts/python.exe scripts/verify_test_db_isolation.py \
        --probe-seed 7 --probe-count 8
    venv/Scripts/python.exe scripts/verify_test_db_isolation.py \
        --only tests/test_repository.py tests/api/test_feedback.py
    venv/Scripts/python.exe scripts/verify_test_db_isolation.py --changed
    venv/Scripts/python.exe scripts/verify_test_db_isolation.py --changed --base origin/master

``--changed`` 只酸测「本次改动」涉及的测试文件，三路并集：已提交未推送
（``git diff <base>``，基线默认 ``@{upstream}``，无 upstream 时须显式
``--base``）+ 工作区/暂存区改动（``git diff HEAD``）+ 未跟踪新文件
（``git ls-files --others``）。改动过的文件不问桶归属全部跑（守卫会拦
的也会标出）；没改动就跳过。适合 dispatch 前快速定向复验。

定向跑的已知盲区：只看改动的测试文件，经 service 层间接使用默认库的
部分不在选集里。因此 ``--changed`` 会额外扫 app/ diff 新增行的默认库
行为信号（启发式），命中时打印「建议跑全量」提示——不阻断，定向跑
照常执行。

退出码：任一文件 pytest 非零退出 → 1；否则 0。纯标准库实现，无
--timeout（仓库未装 pytest-timeout，传了会让 pytest exit=4）。Windows
GBK 控制台沿用守卫同款 _force_utf8_stdio 防护。

已知量级：约 34 灰区 + 5 探针 ≈ 39 文件全量 4-5 分钟（test_interactions
单文件 107s）。新增守卫规则 / 登记豁免前先跑一遍：红 = 登记理由不成立，
修测试而不是改酸测。
"""

from __future__ import annotations

import argparse
import ast
import os
import random
import re
import subprocess
import sys
from pathlib import Path

# 兼容两种运行方式：python scripts/verify_test_db_isolation.py（脚本目录
# 已在 sys.path）与从其他位置 import 复用枚举函数。
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_test_db_bootstrap import (
    BACKEND_DIR,
    TESTS_DIR,
    WHITELIST,
    _direct_db_signals,
    _sql_statement_kinds,
    _string_constants,
    check_residue_reads,
)


def _force_utf8_stdio() -> None:
    """Windows 默认 ANSI 代码页编不了中文/✅，先重配 stdout/stderr 为 UTF-8。

    与守卫同款：退出码才是契约，输出乱码不退出才是硬要求。
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def _default_db_files() -> list[Path]:
    """默认库三件套路径（仓库根 data/ 下，conftest 的 DB_PATH 默认值）。"""
    data_dir = BACKEND_DIR.parent / "data"
    return [data_dir / f"test.db{suffix}" for suffix in ("", "-wal", "-shm")]


def _delete_default_db() -> None:
    """删除默认库三件套，保证下个文件从全新空库开始。"""
    for db_file in _default_db_files():
        db_file.unlink(missing_ok=True)


def _enum_error(rel: str, exc: SyntaxError) -> None:
    print(f"::error::{rel} 枚举阶段语法错误: {exc}")
    raise SystemExit(1)


def _tree_and_strings(path: Path) -> tuple:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return tree, _string_constants(tree)


def enumerate_gray_files() -> list[Path]:
    """动态枚举灰区：直连 + SELECT 表读 + 走规则二豁免路径的测试文件。

    复用守卫函数而非硬编码清单：守卫规则一信号、SQL 识别或白名单调整后，
    本清单自动跟随，酸测覆盖面与守卫语义始终一致。
    """
    gray: list[Path] = []
    for path in sorted(TESTS_DIR.rglob("test_*.py")):
        rel = path.relative_to(BACKEND_DIR).as_posix()
        if rel in WHITELIST:
            continue
        try:
            tree, strings = _tree_and_strings(path)
        except SyntaxError as exc:
            _enum_error(rel, exc)
        needs = _direct_db_signals(tree, strings)
        if not needs:
            continue  # 不直连默认库
        if "SELECT" not in _sql_statement_kinds(strings):
            continue  # 无表读 → 探针桶
        if check_residue_reads(path) is not None:
            continue  # 守卫会拦的违规文件，不是灰区（应先修测试）
        gray.append(path)
    return gray


def enumerate_probe_candidates() -> list[Path]:
    """「直连无表读」桶：直连默认库但无 SELECT...FROM 表读的测试文件。

    静态上不依赖库中数据（规则二不适用），酸测只验证空库上不因缺
    schema 红。文件多，抽样跑（见 --probe-count / --probe-seed）。
    """
    probes: list[Path] = []
    for path in sorted(TESTS_DIR.rglob("test_*.py")):
        rel = path.relative_to(BACKEND_DIR).as_posix()
        if rel in WHITELIST:
            continue
        try:
            tree, strings = _tree_and_strings(path)
        except SyntaxError as exc:
            _enum_error(rel, exc)
        if not _direct_db_signals(tree, strings):
            continue
        if "SELECT" in _sql_statement_kinds(strings):
            continue  # 表读 → 灰区，全量跑
        probes.append(path)
    return probes


def _classify(rel: str) -> str:
    """单文件桶归属标注（--changed / --only 输出用；枚举函数的逐文件版）。

    返回值之一：whitelist / indirect（静态看不见默认库） /
    guard-would-flag（守卫规则二会拦的违规）/ gray（灰区）/ probe-bucket
    （直连无表读，探针桶成员）。与 enumerate_* 的判定共用同一批守卫函数，
    语义一致。
    """
    path = BACKEND_DIR / rel
    if rel in WHITELIST:
        return "whitelist"
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError:
        return "syntax-error"
    strings = _string_constants(tree)
    if not _direct_db_signals(tree, strings):
        return "indirect"
    if check_residue_reads(path) is not None:
        return "guard-would-flag"
    if "SELECT" in _sql_statement_kinds(strings):
        return "gray"
    return "probe-bucket"


_CLASSIFY_LABELS = {
    "whitelist": "白名单豁免",
    "indirect": "非直连",
    "guard-would-flag": "守卫会拦",
    "gray": "灰区",
    "probe-bucket": "探针桶",
    "syntax-error": "语法错误",
}


def _git(repo_root: Path, *args: str) -> str:
    result = subprocess.run(
        # S607：git 的安装路径因平台而异，必须交给 PATH 解析，不能硬编码。
        ["git", *args],  # noqa: S607
        cwd=repo_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"git {args[0]} 失败")
    return result.stdout


def _resolve_base(repo_root: Path, explicit: str | None) -> str:
    """--changed 的 diff 基线：显式 --base 优先，否则 @{upstream}。

    无 upstream（本地分支从未 push）时不猜分支名——猜错会让「本次改动」
    的口径完全不可信；直接报错并给出显式 --base 示例。
    """
    if explicit:
        return explicit
    try:
        return _git(repo_root, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}").strip()
    except RuntimeError as exc:
        print(
            f"❌ 无法确定 --changed 的 diff 基线：{exc}\n"
            "   本分支没有 upstream（或从未 push）时请显式指定，例如：\n"
            "     --base origin/master     与远端 master 比\n"
            "     --base HEAD~5            与最近 5 个提交前比\n"
            "     --base <sha>             与指定提交比"
        )
        raise SystemExit(2) from exc


def _changed_test_files(repo_root: Path, base: str) -> list[str]:
    """收集「本次改动」的测试文件（backend 相对路径，排序去重）。

    三路并集：vs 基线的已提交改动 + vs HEAD 的工作区/暂存改动 + 未跟踪
    新文件。diff-filter 排除 D（删除）——文件已不存在没法跑。只留
    backend/tests/ 下的 test_*.py。
    """
    changed: set[str] = set()
    changed.update(_git(repo_root, "diff", "--name-only", "--diff-filter=ACMR", base).splitlines())
    changed.update(_git(repo_root, "diff", "--name-only", "--diff-filter=ACMR", "HEAD").splitlines())
    changed.update(_git(repo_root, "ls-files", "--others", "--exclude-standard").splitlines())
    out: list[str] = []
    for name in changed:
        posix = Path(name).as_posix()
        if not posix.startswith("backend/tests/"):
            continue
        if Path(posix).name.startswith("test_") and posix.endswith(".py"):
            out.append(posix.removeprefix("backend/"))
    return sorted(set(out))


# app/ diff 新增行的默认库行为信号（启发式，--changed 提示用）。
# 已知误报：类型注解里的 get_connection/init_db 也会命中（mypy 批次会
# 误提示）——提示不阻断，宁可多提醒不漏提醒。刻意不含裸 "repository"
# （import 行就命中，纯噪音）。
_APP_DB_SIGNAL_RE = re.compile(
    r"sqlite3|DB_PATH|db_path|get_connection|connection_scope|init_db|"
    r"CREATE TABLE|INSERT INTO|DELETE FROM|UPDATE \w+ SET"
)


def _app_db_signal_files(repo_root: Path, base: str) -> list[tuple[str, set[str]]]:
    """扫描 vs 基线的 app/ diff 新增行里的默认库行为信号，返回 (文件, 信号)。"""
    diff = _git(repo_root, "diff", "--unified=0", base, "--", "backend/app/")
    current = ""
    hits: dict[str, set[str]] = {}
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            current = line[6:].removeprefix("backend/")
            continue
        if line.startswith("+") and not line.startswith("+++") and current:
            found = set(_APP_DB_SIGNAL_RE.findall(line))
            if found:
                hits.setdefault(current, set()).update(found)
    # 未跟踪新 app 文件不在 diff 里，整文件内容算新增行
    for name in _git(repo_root, "ls-files", "--others", "--exclude-standard").splitlines():
        posix = Path(name).as_posix()
        if posix.startswith("backend/app/") and posix.endswith(".py"):
            text = (repo_root / name).read_text(encoding="utf-8", errors="replace")
            found = set(_APP_DB_SIGNAL_RE.findall(text))
            if found:
                hits.setdefault(posix.removeprefix("backend/"), set()).update(found)
    return sorted(hits.items())


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--only",
        nargs="+",
        metavar="PATH",
        help="只跑指定测试文件（backend 相对路径，如 tests/test_repository.py）",
    )
    parser.add_argument(
        "--changed",
        action="store_true",
        help="只跑本次改动涉及的测试文件（与 --only 互斥；见模块 docstring）",
    )
    parser.add_argument(
        "--base",
        metavar="REF",
        default=None,
        help="--changed 的 diff 基线（默认 @{upstream}，无 upstream 时必填）",
    )
    parser.add_argument(
        "--probe-count",
        type=int,
        default=5,
        help="探针桶抽样数量（默认 5；0 = 跳过探针）",
    )
    parser.add_argument(
        "--probe-seed",
        type=int,
        default=20260928,
        help="探针抽样随机种子（默认固定值，同树重跑结果稳定；只影响默认全量模式）",
    )
    args = parser.parse_args(argv)
    if args.only and args.changed:
        parser.error("--only 与 --changed 互斥，选一个")
    return args


def _pick_probes(candidates: list[Path], count: int, seed: int) -> list[Path]:
    if count <= 0 or not candidates:
        return []
    # S311：抽样是确定性选样不是密码学用途，种子固定为了结果可复现。
    return random.Random(seed).sample(candidates, min(count, len(candidates)))  # noqa: S311


def _run_one(pytest_path: str) -> tuple[bool, str]:
    """删默认库后串行单跑一个测试文件，返回 (ok, 摘要行)。

    串行是刻意的：xdist 每 worker 独立库文件，测不出「单文件空库」行为。
    环境钉 PYTHONUTF8=1（Windows GBK 控制台下 pytest 输出中文不炸）。
    """
    _delete_default_db()
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        pytest_path,
        "-q",
        "--no-header",
        "-p",
        "no:cacheprovider",
        "--no-cov",
    ]
    result = subprocess.run(
        cmd,
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, "PYTHONUTF8": "1"},
    )
    # pytest exit 5 = EXIT_NOTESTSCOLLECTED：文件里没有任何用例。空文件没有
    # 行为可酸测，记 pass 而不是 FAIL（--changed 会抓到未跟踪的草稿文件，
    # 不该因它没有 test 函数就红）。收集错误（exit 2）仍算 FAIL。
    if result.returncode == 5:
        return True, "no tests collected (pytest exit 5)"
    summary = "?"
    for line in (result.stdout + result.stderr).splitlines():
        if "passed" in line or "failed" in line or "error" in line.lower():
            summary = line.strip()
    return result.returncode == 0, summary[:120]


def main(argv: list[str] | None = None) -> int:
    _force_utf8_stdio()
    args = _parse_args(argv)
    tags: dict[str, str] = {}  # rel -> 桶归属标注（--only/--changed 模式填）

    if args.only:
        missing = [rel for rel in args.only if not (BACKEND_DIR / rel).exists()]
        if missing:
            print(f"❌ --only 路径不存在: {', '.join(missing)}")
            return 2
        tags = {rel: _CLASSIFY_LABELS.get(_classify(rel), "") for rel in args.only}
        buckets = {"指定文件": list(args.only)}
    elif args.changed:
        repo_root = BACKEND_DIR.parent
        base = _resolve_base(repo_root, args.base)
        # 轻量提示（不强制）：app/ 改动含默认库行为信号 → 建议跑全量。
        # 反向选择器不完备（经 service 层间接用库的测试静态不可见），
        # 2026-09-29 审计结论：真实 DB 变更提交的反向选集≈全量，全量才是
        # 完备口径；定向跑的剩余风险由本提示显式暴露而非静默。
        hinted = _app_db_signal_files(repo_root, base)
        if hinted:
            print("💡 本次改动涉及 app/ 的默认库行为信号（启发式 diff 扫描）：")
            for rel, sig in hinted:
                print(f"   {rel}: {', '.join(sorted(sig))}")
            print("   建议跑全量酸测（去掉 --changed）：经 service 层间接使用")
            print("   默认库的测试静态不可见，定向选集不含它们。本提示不阻断。\n")
        rels = _changed_test_files(repo_root, base)
        if not rels:
            print(f"✅ 基线 {base} 以来没有改动的测试文件，无需酸测")
            return 0
        tags = {rel: _CLASSIFY_LABELS.get(_classify(rel), "") for rel in rels}
        buckets = {f"本次改动 (base={base})": rels}
    else:
        gray = enumerate_gray_files()
        probes = _pick_probes(enumerate_probe_candidates(), args.probe_count, args.probe_seed)
        buckets = {
            "灰区（直连+表读+豁免路径）": [p.relative_to(BACKEND_DIR).as_posix() for p in gray],
            f"探针抽样(seed={args.probe_seed})": [p.relative_to(BACKEND_DIR).as_posix() for p in probes],
        }

    total = sum(len(v) for v in buckets.values())
    if total == 0:
        print("✅ 没有需要酸测的文件（灰区为空且探针跳过）")
        return 0

    failures: list[tuple[str, str]] = []
    done = 0
    for bucket, rels in buckets.items():
        if not rels:
            continue
        print(f"\n── {bucket}: {len(rels)} 文件 ──")
        for rel in rels:
            done += 1
            ok, summary = _run_one(rel)
            tag = "pass" if ok else "FAIL"
            bucket = f" ({tags[rel]})" if tags.get(rel) else ""
            print(f"[{done}/{total}] {tag}  {rel}{bucket}  :: {summary}")
            if not ok:
                failures.append((rel, summary))

    print(f"\n=== 空库酸测完成：{total - len(failures)}/{total} 绿 ===")
    if failures:
        print("\n❌ 以下文件在全新空库上红（登记豁免前须先核实理由）：")
        for rel, summary in failures:
            print(f"  {rel}\n    {summary}")
        return 1
    print("✅ 全部通过：默认库数据来源在空库上无隐式依赖")
    return 0


if __name__ == "__main__":
    sys.exit(main())
