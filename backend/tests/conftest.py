# ──────────────────────────────────────────────
# pytest 全局配置 — 测试环境隔离
# ──────────────────────────────────────────────
# 为什么需要这个文件：
# config.py 在模块导入时就执行 `settings = Settings()`，它会读取仓库根目录
# 的 .env。本地开发者若把 .env 配成生产参数（APP_ENV=production / HOST=0.0.0.0
# / API_KEY 空），Settings() 的“生产环境安全自检”会在实例化时抛错，导致 pytest
# 在 collection 阶段直接崩溃（不是断言失败，而是 import 就炸）。
#
# 解决办法：在任何 app 模块被导入之前（即本文件顶层、其它 import 之前）强制把
# 进程环境变量改成安全的测试值。pydantic-settings 的优先级是 环境变量 > .env
# 文件，因此这里的强制覆盖能压过操作员本地的生产 .env。
#
# 用强制赋值而非 setdefault：目的就是要盖掉 .env 里可能存在的生产配置。
# 注意：这不会削弱安全自检本身——test_review_regressions.py 里用
# `Settings(_env_file=None, app_env="production", ...)` 显式构造的用例走的是
# init kwargs，优先级高于环境变量，仍会正常触发拒绝逻辑。
import os
import pathlib
import uuid

os.environ["APP_ENV"] = "test"
os.environ["API_KEY"] = ""
os.environ["HOST"] = "127.0.0.1"

# Override DB_PATH to a workspace-writable location for tests.
# .env may set DB_PATH=/app/data/app.db (Docker path) which doesn't exist on
# the host. Tests that don't use tmp_path will fall through to this default.
os.environ.setdefault("DB_PATH", str(
    pathlib.Path(__file__).resolve().parent.parent.parent / "data" / "test.db"
))

# ── Override tmp_path to avoid sandbox-locked dirs ──────────────────
# DSH sandbox locks directories created by pytest's internal TempPathFactory.
# We override tmp_path and tmp_path_factory to use workspace-writable dirs
# that we create ourselves (which are NOT locked).
import pytest

_WORKSPACE_TMP = pathlib.Path(__file__).resolve().parent.parent.parent / "data" / "pytest_tmp"


@pytest.fixture
def tmp_path(request):
    """Override tmp_path to use a workspace-writable directory.

    DSH sandbox may lock pytest's default temp dirs. This fixture creates
    per-test dirs under data/pytest_tmp/ which are writable.
    """
    _WORKSPACE_TMP.mkdir(parents=True, exist_ok=True)
    # Use test name + uuid for uniqueness
    test_name = request.node.name.replace("/", "_").replace("::", "_").replace("[", "_").replace("]", "")
    # Sanitize characters that are illegal in Windows directory names
    test_name = test_name.replace(":", "_").replace("*", "_").replace("?", "_").replace('"', "_").replace("<", "_").replace(">", "_").replace("|", "_")
    # Truncate to avoid path length issues on Windows
    test_name = test_name[:80]
    d = _WORKSPACE_TMP / f"{test_name}_{uuid.uuid4().hex[:8]}"
    d.mkdir(parents=True, exist_ok=True)
    yield d
    # Cleanup (best-effort)
    import shutil

    try:
        shutil.rmtree(d, ignore_errors=True)
    except Exception:
        pass
