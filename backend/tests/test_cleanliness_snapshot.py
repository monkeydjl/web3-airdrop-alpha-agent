"""洁净度快照机制的回归钉子（tests/test_cleanliness_snapshot.py）。

把 `docs/testing-default-db-cleanliness.md` 后记的哨兵探针固化成可重放
用例。2026-09-29 的实证链：v3 快照在 xdist 下有缺陷 A（8 worker
last-writer-wins 覆盖基线）与缺陷 B（worker teardown print 被 xdist 捕获，
diff 提示不可达）；修复后又差点被一个探针盲区放行——同模式 diff 分支漏了
`parts = []` 初始化，此前所有手工探针都没踩中（全走异模式分支或零差异
路径），直到全量酸测在真实足迹变化路径上才引爆。
`test_serial_full_diff_outputs_full_table_diff` 就是那个盲区的直接回归。

## 三个继承污染盲区（2026-09-30 固化过程中实测发现）

被测路径要靠 in-pytest 子进程重放「会话结束」时序，而子进程会继承外层的
全部环境变量——本文件会被三种外层语境运行（开发者直跑 / 串行全量 /
酸测 acid 会话），断言在所有语境下都必须成立：

1. `CLEANLINESS_MODE`：acid 外层不钉住，会把 serial-full 路径用例静默
   变成 acid 会话，断言全部错位（酸测单跑实测 3 failed）。
2. `PYTEST_XDIST_WORKER`：不剥掉，串行子进程会被 conftest 误判成
   worker，teardown 直接跳过快照——用例失效且无任何报错。
3. `DB_PATH`：内层 `pytest_configure` 会删库重建。不钉住的话，删的就是
   外层正在用的库（串行全量的 test.db / worker 的 test_gwN.db）。
   因此每个用例把 DB_PATH 指向 `tmp_path` 里的**私有探针库**，快照文件
   随之落在私有目录（conftest 的 `db_file.parent` 规则），与真实基线
   `data/test.db.cleanliness.json` 彻底解耦——外层 xdist 多 worker 并发
   跑本文件时也不再共享任何介质（盲区三：共享快照文件互相踩踏，正是
   本文所防缺陷 A 的微型重演）。

## _run_one 的环境变量钉住（第四组契约）

`verify_test_db_isolation._run_one` 给酸测子进程钉 DB_PATH / 注入
CLEANLINESS_MODE=acid / 剥 PYTEST_XDIST_WORKER，其中 DB_PATH 必须与
`_delete_default_db()` 的删除目标同库。它曾硬编码
`BACKEND_DIR.parent / "data" / "test.db"`，而删除目标走
`_default_db_files()`——两处分叉正是 DB_PATH 分家盲区的复发路径，已
重构为单一真相源 `_default_db_files()[0]`。`TestRunOneEnvPinning` 用
**进程内**调用钉死三者：子进程调真脚本会让 `_delete_default_db()` 删掉
外层活动库，进程内 monkeypatch `_default_db_files` → tmp 三件套后脚本
代码原样执行；探针文件生成在 `backend/data/_probe/` 下的用例私有目录
（gitignore 运行时忽略区、tests/ 树外），三种外层语境（直跑 / 酸测 /
xdist）都可跑。

探针**不能放系统 TEMP**：pytest 9 的 win32 收集路径匹配会对不匹配的
兄弟收集节点逐个 `lstat` 兜底（`samefile_nofollow`），探针在 $TEMP 根
下时内层会话的收集链涵盖 $TEMP，而外层 xdist worker 正在并发删除
彼此的 `test_*` per-test 目录 → lstat 撞上刚被删的目录 → collection
error。`backend/data/_probe/` 下收集链祖先（backend/）的兄弟节点全程
稳定，无此竞争。

## 嵌套 xdist 的边界

`test_xdist_workers_never_touch_baseline` 需要真实的内层 `-n 2`。内层
worker 会按 conftest 的 worker 分支把 DB_PATH **强制**重定向回仓库
`data/test_gwN.db` 并删库重建——在外层 xdist 全量里，那正是外层 worker
活动中的库。因此该用例在 xdist 外层显式 skip（其余用例全部语境可跑）；
串行/acid 外层下内层删掉的只是上一轮 xdist 的残留 gw 库，无害。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _write_baseline(snapshot_path: Path, tables: dict[str, int], mode: str) -> None:
    """预埋一份基线快照（模拟上一轮运行留下的 JSON）。"""
    payload = dict(tables)
    payload["_mode"] = mode
    snapshot_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True),
        encoding="utf-8",
    )


def _read_snapshot(snapshot_path: Path) -> dict:
    return json.loads(snapshot_path.read_text(encoding="utf-8"))


def _run_pytest(
    args: list[str],
    db_path: Path,
    cleanliness_mode: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """跑一个隔离的 in-pytest 子进程，返回完整结果。

    `-s`：让 conftest teardown 的 print 直达 stdout（人工验收口径）。
    `--no-cov`：隔离子进程不做覆盖率统计（外层全量已统计），省一半时间。
    三个环境变量的钉住理由见模块 docstring「三个继承污染盲区」。
    """
    env = {
        **os.environ,
        "PYTHONUTF8": "1",
        "DB_PATH": str(db_path),
        "CLEANLINESS_MODE": "acid" if cleanliness_mode == "acid" else "",
    }
    env.pop("PYTEST_XDIST_WORKER", None)
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_anomaly_detection.py",
            *args,
            "-s",
            "-q",
            "--no-cov",
            "-p",
            "no:cacheprovider",
        ],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
        env=env,
    )


class TestCleanlinessSnapshotRegression:
    """四条快照路径各一个用例 + 模式标注契约，全部走真实子进程时序。

    每个用例的 DB_PATH 与快照文件都在 `tmp_path` 私有目录里（见模块
    docstring 盲区三），被跑的 `tests/test_anomaly_detection.py` 文件小
    （7 用例秒级）、有确定的最小默认库足迹、在守卫体系里已知自播种合规。
    """

    def test_serial_warning_channel_still_works(self, tmp_path):
        """串行（非 worker）路径：警告可达、哨兵被清、新格式带 _mode。

        缺陷 B 的反面钉子：修复前 xdist 失聪，修复后必须保证串行验收轮
        的提示通道一直活着——这是「diff + 人工核查进基线」的前提。
        """
        snapshot = tmp_path / "test.db.cleanliness.json"
        _write_baseline(snapshot, {"__sentinel__": 42}, mode="serial-full")
        result = _run_pytest([], tmp_path / "probe.db")
        assert result.returncode == 0, result.stdout[-2000:]
        assert "洁净度快照与上一轮不同" in result.stdout, result.stdout[-2000:]
        assert "清空: {'__sentinel__': 42}" in result.stdout
        payload = _read_snapshot(snapshot)
        assert payload["_mode"] == "serial-full"
        assert "__sentinel__" not in payload

    def test_xdist_workers_never_touch_baseline(self, tmp_path):
        """xdist worker 零写入：跑完基线逐键不变（缺陷 A 的直接回归）。

        修复前 8 个 worker last-writer-wins，基线被某个子集足迹覆盖；
        修复后 worker teardown 显式跳过。哨兵基线在这里就是探测器：
        任何一个 worker 写过快照，`__sentinel__` 都会消失。

        嵌套 xdist 边界见模块 docstring：外层 xdist 下 skip。
        """
        if os.environ.get("PYTEST_XDIST_WORKER"):
            pytest.skip("嵌套 xdist：内层 worker 会被强制重定向 DB_PATH 到仓库 data/ 并删库，外层全量下不安全")
        snapshot = tmp_path / "test.db.cleanliness.json"
        _write_baseline(snapshot, {"__sentinel__": 777}, mode="serial-full")
        result = _run_pytest(["-n", "2"], tmp_path / "probe.db")
        assert result.returncode == 0, result.stdout[-2000:]
        assert _read_snapshot(snapshot) == {"__sentinel__": 777, "_mode": "serial-full"}

    def test_cross_mode_baseline_gets_one_line_note(self, tmp_path):
        """异模式基线：只出单行模式注记，不做逐表 diff（预期差异不是污染）。"""
        snapshot = tmp_path / "test.db.cleanliness.json"
        _write_baseline(snapshot, {"projects": 9}, mode="serial-acid")
        result = _run_pytest([], tmp_path / "probe.db")
        assert result.returncode == 0, result.stdout[-2000:]
        assert "基线模式: 上轮由 'serial-acid' 写入，本次 'serial-full'" in result.stdout, result.stdout[-2000:]
        # 逐表列举是异模式下的噪声，分流后不应再出现
        assert "新出现:" not in result.stdout and "增长:" not in result.stdout
        assert _read_snapshot(snapshot)["_mode"] == "serial-full"

    def test_serial_full_diff_outputs_full_table_diff(self, tmp_path):
        """同模式 diff 路径：完整逐表 diff 正常输出（2026-09-29 盲区的直接回归）。

        回归史：基线分流重构把 `parts = []` 挪进 else 分支时漏了初始化，
        本路径在「同模式 + 足迹有差异」时抛 UnboundLocalError——用例全过、
        会话 teardown 报 error。此前所有探针都没踩中它：全走异模式分支
        （探针 A）或零差异路径（串行 R2）。哨兵键保证「清空」项必然存在，
        与真实足迹无关，本用例从此钉死这条路径。
        """
        snapshot = tmp_path / "test.db.cleanliness.json"
        _write_baseline(snapshot, {"__sentinel__": 42}, mode="serial-full")
        result = _run_pytest([], tmp_path / "probe.db")
        assert result.returncode == 0, result.stdout[-2000:]
        assert "洁净度快照与上一轮不同" in result.stdout, result.stdout[-2000:]
        assert "清空: {'__sentinel__': 42}" in result.stdout, result.stdout[-2000:]

    def test_acid_env_var_labels_the_baseline(self, tmp_path):
        """`CLEANLINESS_MODE=acid` 环境变量 → 基线标注 serial-acid。

        钉住 verify_test_db_isolation 注入与 conftest 消费之间的契约：
        酸测脚本改名或 conftest 改键名，这里立刻红。
        """
        result = _run_pytest([], tmp_path / "probe.db", cleanliness_mode="acid")
        assert result.returncode == 0, result.stdout[-2000:]
        assert _read_snapshot(tmp_path / "test.db.cleanliness.json")["_mode"] == "serial-acid"


# ── 第四盲区：_run_one 的环境变量钉住（2026-09-30 继承面审计）──────────
# 酸测脚本 verify_test_db_isolation._run_one 给子进程钉三个变量，其中
# DB_PATH 必须与 _delete_default_db() 的删除目标同库。它曾硬编码
# `BACKEND_DIR.parent / "data" / "test.db"`——而删除目标走
# `_default_db_files()`，单一真相源是 `_default_db_files()[0]`，硬编码
# 分叉后两处改一个就会悄悄分家（正是 DB_PATH 分家盲区的复发路径）。

_PROBE_NAME = "test_inner_probe"

_PROBE_BODY = '''\
"""_run_one 的环境变量探针（TestRunOneEnvPinning 生成于 tmp，仓库树外）。

经 verify_test_db_isolation._run_one 串行执行。本目录无 conftest，
子进程看到的环境变量全部来自 _run_one 的显式注入——这正是被断言的
东西。失败 traceback 只存在于子进程捕获输出里，外层仅得 exit code
与摘要行。
"""

import os


def test_inner_probe():
    delete_target = os.environ["_PROBE_DELETE_TARGET"]
    assert os.environ["DB_PATH"] == delete_target, (
        f"DB_PATH={os.environ['DB_PATH']!r} 与删除目标 {delete_target!r} 分家"
    )
    assert os.environ["CLEANLINESS_MODE"] == "acid", os.environ["CLEANLINESS_MODE"]
    assert "PYTEST_XDIST_WORKER" not in os.environ, os.environ["PYTEST_XDIST_WORKER"]
'''


def _run_one_env_snapshot(tmp_path: Path, env_overrides: dict[str, str]) -> tuple[bool, str, str]:
    """进程内调真 `_run_one`，返回 (ok, 摘要行, 内层输出尾部)，全程不触碰外层介质。

    不能子进程调真脚本：`_run_one` 无条件 `_delete_default_db()`，真脚本
    删的是外层活动库（串行全量的 data/test.db / xdist worker 的
    test_gwN.db）。改为进程内把 `_default_db_files` monkeypatch 成探针
    目录里的三件套——删除目标与 DB_PATH pin 一起落到探针目录，脚本代码
    原样执行。探针文件生成在 `backend/data/_probe/<tmp_path.name>/`（仓库
    树外、gitignore 运行时忽略区、tests/ 树外）：子进程不加载任何
    conftest，其环境变量全部来自 `_run_one` 的显式注入；收集链祖先
    （backend/）里的兄弟节点全程稳定，不会撞上外层 xdist worker 并发
    删除的 tmp 目录（系统 TEMP 下会，见模块 docstring）。三种外层语境
    （直跑 / 酸测 / xdist worker）都可跑，无需 skip。

    `_run_one` 本身丢弃子进程捕获输出，探针红时只有一行摘要无从诊断
    （「1 error」连 traceback 都没有），所以包装 `vmod.subprocess.run`
    把 CompletedProcess 留档——精确复用 `_run_one` 的 env/cwd 构造，
    零逻辑复制。同步窗口内本进程无其他 subprocess 消费方，包装安全。
    """
    scripts_dir = str(BACKEND_DIR / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import verify_test_db_isolation as vmod

    real_default_db_files = vmod._default_db_files
    real_run = vmod.subprocess.run
    captured: list[subprocess.CompletedProcess[str]] = []

    def _recording_run(*args, **kwargs):
        result = real_run(*args, **kwargs)
        captured.append(result)
        return result

    probe_dir = BACKEND_DIR / "data" / "_probe" / tmp_path.name
    probe_dir.mkdir(parents=True, exist_ok=True)
    probe_db = probe_dir / "probe.db"

    def _tmp_default_db_files() -> list[Path]:
        # 与脚本同款三件套命名（后缀 "" / "-wal" / "-shm"）。
        return [probe_db.with_name(probe_db.name + suffix) for suffix in ("", "-wal", "-shm")]

    vmod._default_db_files = _tmp_default_db_files
    vmod.subprocess.run = _recording_run
    probe_file = probe_dir / "_run_one_env_probe.py"
    probe_file.write_text(_PROBE_BODY, encoding="utf-8", newline="\n")

    saved = dict(os.environ)
    try:
        # 模拟最恶劣的操作员 shell：三个高危变量全部在场（污染值）。
        os.environ["DB_PATH"] = str(real_default_db_files()[0])
        os.environ["PYTEST_XDIST_WORKER"] = "gw0"
        os.environ["CLEANLINESS_MODE"] = ""
        # 删除目标标记取自 patch 后的模块属性：= _delete_default_db 将删的文件。
        os.environ["_PROBE_DELETE_TARGET"] = str(vmod._default_db_files()[0])
        os.environ.update(env_overrides)
        ok, summary = vmod._run_one(f"{probe_file.relative_to(BACKEND_DIR).as_posix()}::{_PROBE_NAME}")
        inner = captured[-1] if captured else None
        detail = (inner.stdout + inner.stderr)[-3000:] if inner is not None else "(无子进程被捕获)"
        return ok, summary, detail
    finally:
        # 只还原动过的键：先删新增键，再恢复被改写的原值。
        for key in set(os.environ) - set(saved):
            del os.environ[key]
        for key, value in saved.items():
            if os.environ.get(key) != value:
                os.environ[key] = value
        vmod._default_db_files = real_default_db_files
        vmod.subprocess.run = real_run
        # 探针目录即用即弃：库文件、快照 JSON 都在 gitignore 忽略区，
        # 但留着会跨轮累积，best-effort 清掉。
        shutil.rmtree(probe_dir, ignore_errors=True)


class TestRunOneEnvPinning:
    """污染 shell 下经真 `_run_one` 断言子进程环境钉住（2026-09-30 审计）。

    盲区：`_run_one` 曾只注入 CLEANLINESS_MODE 而 DB_PATH 未 pin——操作员
    shell 导出 DB_PATH 时，酸测写的库与 `_delete_default_db()` 固定删的
    库分家。修复：pin 改为 `_default_db_files()[0]`（与删除目标单一真相
    源）；本类经进程内调用 + tmp 重定向（见 `_run_one_env_snapshot`）钉死：

    - 子进程 DB_PATH == 删除目标（分家直接回归；任何一处再硬编码都会让
      标记与子进程 DB_PATH 不一致而红）；
    - CLEANLINESS_MODE 强制 acid（外层值不得穿透）；
    - PYTEST_XDIST_WORKER 必须剥除（worker 身份不得进入酸测子进程）。

    探针在仓库树外运行、无 conftest 参与，全部观测只依赖 _run_one 的注入。
    """

    def test_poisoned_shell_db_path_is_pinned_to_delete_target(self, tmp_path):
        """操作员 shell 导出 DB_PATH → 子进程仍被 pin 回删除目标（本轮盲区的直接回归）。"""
        ok, summary, detail = _run_one_env_snapshot(tmp_path, {"DB_PATH": "D:/tmp/some_operator_db.db"})
        assert ok, (
            f"探针失败：{summary}。修复后 _run_one 的 DB_PATH pin 应与删除目标同库"
            f"（单一真相源 _default_db_files()[0]）。内层输出：\n{detail}"
        )
        # summary 含 "passed" 排除 exit 5（no tests collected）被记 pass 的假绿。
        assert "passed" in summary, summary + "\n" + detail

    def test_poisoned_worker_identity_is_stripped(self, tmp_path):
        """外层冒充 xdist worker → `_run_one` 必须剥掉，不能传给酸测子进程。"""
        ok, summary, detail = _run_one_env_snapshot(tmp_path, {})
        assert ok, f"探针失败：{summary}。PYTEST_XDIST_WORKER 未被剥除。内层输出：\n{detail}"
        assert "passed" in summary, summary + "\n" + detail

    def test_cleanliness_mode_is_injected_as_acid(self, tmp_path):
        """CLEANLINESS_MODE 必须强制 acid，外层串行语境的值不得穿透。"""
        ok, summary, detail = _run_one_env_snapshot(tmp_path, {"CLEANLINESS_MODE": "serial-full"})
        assert ok, f"探针失败：{summary}。CLEANLINESS_MODE 注入缺失或被外层覆盖。内层输出：\n{detail}"
        assert "passed" in summary, summary + "\n" + detail
