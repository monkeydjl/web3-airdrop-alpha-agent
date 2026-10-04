"""双守卫共享盲区（间接触库）收口的回归钉子。

背景：`check_test_db_bootstrap.py`（静态守卫）与 `verify_test_db_isolation.py`
（动态酸测）都只认**直连信号**（`from app.db import ...` / `DB_PATH` /
`sqlite3.connect(DB_PATH)`）。经 service 层间接走 `connection_scope` 的测试文件
既无直连信号、因此既不进守卫、也不进酸测默认枚举——两类自动化共享同一盲区，
没有第二道防线。

2026-10-02 审计实证：`tests/test_roi_simulator.py` 直接调
`simulate_portfolio_allocation`（内部 `connection_scope`）却零直连信号，隐式
依赖默认库残留行；conftest 改为每轮删库后变红，而全量酸测**永远不会跑到它**。
本文件钉住 `verify_test_db_isolation.enumerate_indirect_db_files` 能把这类
文件枚举出来（该函数即收口修复），防止枚举逻辑退化导致盲区复发。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture
def vmod():
    """以 import 方式取酸测脚本（与 test_cleanliness_snapshot.py 同款路径处理）。"""
    scripts_dir = str(BACKEND_DIR / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import verify_test_db_isolation

    return verify_test_db_isolation


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


@pytest.fixture
def fake_tree(tmp_path):
    """造一棵迷你 app/ + tests/ 树，覆盖四种测试文件形态。

    - test_indirect.py：经 service 层间接触库（无直连信号）→ 应被枚举
    - test_indirect_main.py：经 app.main 间接（app.main 拉入触库模块）→ 应被枚举
    - test_direct.py：直连 app.db → 归灰区/探针，不算间接
    - test_plain.py：不 import 任何 app 模块 → 无关
    """
    app = tmp_path / "app"
    _write(app / "__init__.py", "")
    _write(
        app / "db.py",
        "def connection_scope():\n"
        "    return _Ctx()\n"
        "\n"
        "\n"
        "class _Ctx:\n"
        "    def __enter__(self):\n"
        "        return self\n"
        "\n"
        "    def __exit__(self, *exc):\n"
        "        return False\n",
    )
    _write(app / "services" / "__init__.py", "")
    _write(
        app / "services" / "roi.py",
        "from app.db import connection_scope\n\n\ndef sim():\n    with connection_scope():\n        return 1\n",
    )
    _write(
        app / "main.py",
        "from app.services.roi import sim\n\n\ndef app():\n    return sim()\n",
    )
    tests = tmp_path / "tests"
    _write(
        tests / "test_indirect.py",
        "from app.services.roi import sim\n\n\ndef test_x():\n    assert sim() == 1\n",
    )
    _write(
        tests / "test_indirect_main.py",
        "from app.main import app\n\n\ndef test_y():\n    assert app() == 1\n",
    )
    _write(
        tests / "test_direct.py",
        "from app.db import connection_scope\n\n\ndef test_z():\n    with connection_scope():\n        pass\n",
    )
    _write(tests / "test_plain.py", "def test_p():\n    assert True\n")
    return app, tests


class TestIndirectDbEnumeration:
    def test_transitive_db_modules(self, vmod, fake_tree):
        """触库模块集合靠 import 传播：app.db 是种子，service/app.main 经传播进入。"""
        app, _ = fake_tree
        db_modules, known = vmod._db_touching_app_modules(app)
        assert "app" in known and "app.db" in known
        assert "app.db" in db_modules
        assert "app.services.roi" in db_modules  # 经 import 传播
        assert "app.main" in db_modules  # 再传播一层

    def test_indirect_files_detected(self, vmod, fake_tree):
        app, tests = fake_tree
        found = {p.name for p in vmod.enumerate_indirect_db_files(tests_dir=tests, app_dir=app)}
        assert "test_indirect.py" in found  # 经 service 层
        assert "test_indirect_main.py" in found  # 经 app.main
        assert "test_direct.py" not in found  # 直连 → 归灰区/探针桶
        assert "test_plain.py" not in found  # 不触库

    def test_lazy_submodule_import_is_captured(self, vmod, tmp_path):
        """`from app.llm import budget` 必须被识别为 app.llm.budget 依赖。

        真实盲区：`app.llm.client` 在**函数内**惰性 `from app.llm import budget`
        （budget 才触库）。只登记 node.module（app.llm）会漏掉整个 app.llm.budget，
        让 tests/test_llm_failover.py 这类文件逃离撒网。
        """
        app = tmp_path / "app"
        _write(app / "__init__.py", "")
        _write(app / "llm" / "__init__.py", "")
        _write(
            app / "llm" / "budget.py",
            "from app.db import connection_scope\n\n\ndef spend():\n    with connection_scope():\n        return 0\n",
        )
        _write(
            app / "llm" / "client.py",
            "def call():\n    from app.llm import budget\n    return budget.spend()\n",
        )
        tests = tmp_path / "tests"
        _write(
            tests / "test_lazy.py",
            "from app.llm.client import call\n\n\ndef test_l():\n    assert call() == 0\n",
        )
        db_modules, _ = vmod._db_touching_app_modules(app)
        assert "app.llm.budget" in db_modules
        assert "app.llm.client" in db_modules
        found = {p.name for p in vmod.enumerate_indirect_db_files(tests_dir=tests, app_dir=app)}
        assert "test_lazy.py" in found

    def test_real_tree_covers_service_layer_files(self, vmod):
        """活体钉子：真实树上服务层间接文件必须进默认选集。

        以 `tests/test_action_queue.py`（import app.services.action_queue 但无
        直连信号）为代表；它若掉出选集，说明枚举逻辑退化、盲区复发。
        """
        names = {p.name for p in vmod.enumerate_indirect_db_files()}
        assert "test_action_queue.py" in names
        # test_roi_simulator.py 已改为显式建库（直连信号），不再靠残留行：
        # 若有人把它的 db_path 重定向删掉，它会掉回间接选集，这里立刻红。
        assert "test_roi_simulator.py" not in names
