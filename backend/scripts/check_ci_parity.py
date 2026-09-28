"""CI lint job 同款本地自检——防「只验 format 不验 check」再次发生。

事故背景（2026-09-29 整体回归抓出）：cf7a392 给 7 个测试文件补显式建库
fixture 时，验证只跑了 `ruff format`（改过的文件），没跑全仓
`ruff check .`——注释插进 import 块中间留下 E402 ×7 + I001 ×4，
CI lint job 必红，25 个提交之后才被整体回归发现。

本脚本把 ci.yml lint job 的每一步按**同命令、同顺序、同 cwd** 复刻成
一键自检，并在尾部加码两项 CI lint 没有的快速腿：

  1. python -m ruff check .            （CI 同款）
  2. python -m ruff format --check .   （CI 同款）
  3. scripts/check_connection_hygiene.py（CI 同款，§13.3）
  4. scripts/check_test_db_bootstrap.py （CI 同款，§13.4）
  5. 酸测枚举自检（加码）：verify_test_db_isolation 的灰区/探针桶枚举
     可跑、清单非空——不跑 pytest，秒级确认酸测脚本本身没坏

用法（backend/ 下）::

    venv/Scripts/python.exe scripts/check_ci_parity.py

每次提交守卫/测试基础设施相关改动前跑一次；配套
`tests/test_ci_parity.py` 把它钉进全量套件——就算人又偷懒只验 format，
全量 pytest 也会抓住。

退出码：任一腿失败 → 1；全绿 → 0。纯标准库实现，无第三方依赖
（ruff 经 `python -m` 调用，与 CI 同款）。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _force_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def _run_leg(cmd: list[str]) -> tuple[bool, str]:
    """跑一条腿，返回 (ok, 输出尾部)。失败时尾部含 ruff/守卫的错误明细。"""
    result = subprocess.run(
        cmd,
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, "PYTHONUTF8": "1"},
        timeout=300,
    )
    tail_lines = [line for line in (result.stdout + result.stderr).splitlines() if line.strip()]
    return result.returncode == 0, "\n".join(tail_lines[-15:])


def main() -> int:
    _force_utf8_stdio()

    legs: list[tuple[str, list[str]]] = [
        ("ruff check .", [sys.executable, "-m", "ruff", "check", "."]),
        ("ruff format --check .", [sys.executable, "-m", "ruff", "format", "--check", "."]),
        ("连接卫生守卫 (§13.3)", [sys.executable, "scripts/check_connection_hygiene.py"]),
        ("测试建库守卫 (§13.4)", [sys.executable, "scripts/check_test_db_bootstrap.py"]),
    ]

    # 加码腿：酸测枚举（不跑 pytest，只确认脚本能导入且清单非空）
    enum_check = (
        "import sys\n"
        "sys.path.insert(0, 'scripts')\n"
        "import verify_test_db_isolation as v\n"
        "gray = v.enumerate_gray_files()\n"
        "probes = v.enumerate_probe_candidates()\n"
        "assert gray, '灰区清单为空——酸测脚本或守卫函数坏了'\n"
        "assert probes, '探针桶清单为空——酸测脚本或守卫函数坏了'\n"
        "print(f'灰区 {len(gray)} + 探针桶 {len(probes)}')\n"
    )
    legs.append(("酸测枚举自检（加码）", [sys.executable, "-c", enum_check]))

    failed: list[str] = []
    for name, cmd in legs:
        ok, tail = _run_leg(cmd)
        print(f"{'✅' if ok else '❌'} {name}")
        if not ok:
            failed.append(name)
            for line in tail.splitlines():
                print(f"    {line}")

    if failed:
        print(f"\n❌ CI lint 同款自检：{len(failed)} 腿失败：{'、'.join(failed)}")
        print("   修完再提交；这也是 CI lint job 会抓的内容（+酸测枚举加码）。")
        return 1
    print(f"\n✅ CI lint 同款自检全绿：{len(legs)} 腿（4 同款 + 1 加码）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
