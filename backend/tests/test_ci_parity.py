"""CI lint 同款自检脚本本身的回归防线（tests/test_ci_parity.py）。

把 `scripts/check_ci_parity.py` 钉进全量套件：就算有人改完守卫/测试
基础设施只验 `ruff format`，这里的子进程自检也会在 CI test 阶段抓住
「format 绿但 check 红」的树。见 check_ci_parity.py 文件头的事故背景。

注意：这里跑的是真实子进程（ruff + 两个守卫脚本 + 酸测枚举），全绿时
总耗时约 10-20 秒——可接受，因为换来的保证是「lint job 红不过夜」。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]

EXPECTED_LEGS = 5


def test_ci_parity_self_check_matches_ci_lint_job():
    """run_ci_parity 脚本全绿——CI lint job 的每一步在本树上都会过。"""
    result = subprocess.run(
        [sys.executable, "scripts/check_ci_parity.py"],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=240,
    )
    output = result.stdout + result.stderr
    assert result.returncode == 0, f"CI lint 同款自检红：\n{output}"
    assert f"{EXPECTED_LEGS} 腿" in output, f"自检腿数不对，输出：\n{output}"


def test_ci_parity_catches_check_only_violation(tmp_path, monkeypatch):
    """合成红树：format 过但 check 不过 → 自检必须 exit 1（负路径）。"""
    bad_tree = tmp_path / "backend"
    bad_tree.mkdir()
    # 裸树只有 ruff 两腿会真跑；守卫/枚举腿在无 app/ 的合成树上失败
    # 是预期的——本用例只断言「check 腿报错且整体 exit 1」。
    (bad_tree / "bad.py").write_text("import os,sys\n", encoding="utf-8")

    # 直接调 ruff check 指向合成文件，验证 check 腿能抓住 I001 类问题；
    # 完整脚本的子进程 cwd 固定在真实 backend/，合成树走不了全流程，
    # 所以这里只复刻 check 腿本身。
    result = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--select", "I001", str(bad_tree / "bad.py")],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    assert result.returncode == 1, "I001 红样例没被 ruff check 抓住"
    assert "I001" in result.stdout
