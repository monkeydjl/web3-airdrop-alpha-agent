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
os.environ.setdefault("DB_PATH", str(pathlib.Path(__file__).resolve().parent.parent.parent / "data" / "test.db"))

# ── 把 fetcher 磁盘缓存隔离到测试专用目录 ─────────────────────────
# `settings.fetcher_cache_dir` 默认是相对路径 `"cache"`，即 `backend/cache/` ——
# 那是**生产会用的真实缓存目录**。测试直接往里写有两个后果：
#
# 1. 残留文件跨运行存活，让后续测试**缓存命中而不发请求**。实测症状是
#    `call_count == 0`、mock 的 request 从未被调用，断言以「请求没发出」失败，
#    而报错信息完全看不出是缓存导致的 —— 极难定位。
# 2. 本机沙箱的 safe-delete 让 `unlink()` 抛 OSError，`clear_cache()` 清不掉这些
#    残留，于是污染永久存在，且只在特定执行顺序下暴露（单跑该文件时看不到）。
#
# 用固定的测试专用目录而不是 per-test 目录：fetcher 的缓存是模块级单例，
# 在 import 期就绑定了目录，无法按测试切换。隔离到这里至少保证污染不会
# 落到生产缓存目录，也不会跨 checkout 泄漏。
os.environ.setdefault(
    "FETCHER_CACHE_DIR",
    str(pathlib.Path(__file__).resolve().parent.parent.parent / "data" / "pytest_cache_dir"),
)

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
    test_name = (
        test_name.replace(":", "_")
        .replace("*", "_")
        .replace("?", "_")
        .replace('"', "_")
        .replace("<", "_")
        .replace(">", "_")
        .replace("|", "_")
    )
    # Truncate to avoid path length issues on Windows
    test_name = test_name[:80]
    d = _WORKSPACE_TMP / f"{test_name}_{uuid.uuid4().hex[:8]}"
    d.mkdir(parents=True, exist_ok=True)
    yield d
    # Cleanup (best-effort)
    import contextlib
    import shutil

    with contextlib.suppress(Exception):
        shutil.rmtree(d, ignore_errors=True)


# ── fetcher 磁盘缓存必须每个测试前清空 ──────────────────────────
# fetcher 的缓存目录是**模块级单例**（import 期绑定），所有测试共享同一个目录。
# 只把目录换个位置（见上面的 FETCHER_CACHE_DIR）不解决问题：只要有测试写入过，
# 残留就会让**后续测试缓存命中而不发请求**，mock 的 request 从未被调用，
# 断言以「请求没发出」失败。
#
# 这个失效模式的隐蔽之处：
# - 单跑一个文件看不到（没有前序测试留下残留）；
# - 只在特定执行顺序下暴露，表现为「加上某个不相关的目录一起跑就红」；
# - 报错信息（`call_count == 0`）完全指不到缓存上。
#
# 清理**不能用 unlink**：本机沙箱的 safe-delete 依赖回收站，回收站不可用时
# `unlink()` 直接抛 OSError，清理静默失败、污染永久留存。改为把文件**截断成
# 空内容** —— 空文件会让 `json.load()` 抛 JSONDecodeError，走 fetcher 的
# "corrupt cache → 视为 miss 回源" 分支，效果等价于删除且不依赖删除权限。
@pytest.fixture(autouse=True)
def _isolate_fetcher_disk_cache():
    import contextlib

    def _purge() -> None:
        try:
            from app.config import settings
        except Exception:
            return
        cache_dir = pathlib.Path(settings.fetcher_cache_dir)
        if not cache_dir.is_absolute():
            cache_dir = pathlib.Path.cwd() / cache_dir
        if not cache_dir.exists():
            return
        for f in cache_dir.glob("*.json"):
            # 先试删；删不掉（沙箱 safe-delete 抛 OSError）就退化为截断成空文件。
            try:
                f.unlink()
            except OSError:
                with contextlib.suppress(OSError):
                    f.write_bytes(b"")

    _purge()
    # 内存层也要清，否则同进程内的上一个测试留下的条目照样命中
    with contextlib.suppress(Exception):
        from app.utils.fetcher import clear_cache

        clear_cache()
    yield
    _purge()
