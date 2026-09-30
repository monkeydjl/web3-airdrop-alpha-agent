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
import tempfile
import uuid

os.environ["APP_ENV"] = "test"
os.environ["API_KEY"] = ""
os.environ["HOST"] = "127.0.0.1"

# Override DB_PATH to a workspace-writable location for tests.
# .env may set DB_PATH=/app/data/app.db (Docker path) which doesn't exist on
# the host. Tests that don't use tmp_path will fall through to this default.
# xdist 安全：每 worker 用独立文件名，避免并发 worker 争写同一个 data/test.db。
# （写同一 SQLite 文件虽有 WAL + busy_timeout，但 schema/seed 互相踩踏会让
#  用例随机红——文件级隔离是唯一可靠口径。）
_XDIST_WORKER = os.environ.get("PYTEST_XDIST_WORKER", "")
_DB_SUFFIX = f"test_{_XDIST_WORKER}.db" if _XDIST_WORKER else "test.db"
_DB_DEFAULT = str(pathlib.Path(__file__).resolve().parent.parent.parent / "data" / _DB_SUFFIX)
if _XDIST_WORKER:
    # worker：强制覆盖。xdist controller 先加载一次 conftest（此时 worker
    # 尚未设置，suffix 为空），worker 继承 controller 环境后再 setdefault
    # 早已失效——8 个 worker 会全部写同一个 data/test.db（实测残留 86MB），
    # 文件级隔离形同虚设，且跨轮次残留固定 ID 数据撞 UNIQUE。
    os.environ["DB_PATH"] = _DB_DEFAULT
else:
    # 串行：保留原 setdefault 语义，尊重显式指定的 DB_PATH。
    os.environ.setdefault("DB_PATH", _DB_DEFAULT)

# ── 把 SEED_FALLBACK_ENABLED 钉在测试值上 ────────────────────────
# `seed_fallback_enabled` 的类默认值是 True，但 pydantic-settings 会读仓库根
# 目录的 .env。本地开发者按生产加固清单把 SEED_FALLBACK_ENABLED 写成 false
# （GO_LIVE 要求生产关闭，且生产自检还会再强制关一次）后，pytest 会继承这个
# 值 —— 后果是 §10.2 的 seed fallback 在本机测试里永远不触发，
# test_seed_fallback.py 的两条流水线用例在 CI（无 .env）全绿、本机稳定红，
# 且报错（project_count == 0）完全看不出与本地配置有关。
#
# 与上面 APP_ENV 同理用强制赋值而不是 setdefault：目的就是盖掉操作员本地的
# 生产配置，测试环境要的是与本地 .env 无关的确定性。
#
# 生产侧断言不受影响：test_production_hardening.py 用 init kwargs 显式构造
# Settings（优先级高于环境变量），且生产自检本身会无条件覆盖该字段；
# test_pipeline_run / api/test_collections 里需要的「关」都是在 settings
# 对象上显式 monkeypatch 的，同样与这里的进程环境变量无关。
os.environ["SEED_FALLBACK_ENABLED"] = "true"

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
    str(
        pathlib.Path(__file__).resolve().parent.parent.parent
        / "data"
        / (f"pytest_cache_dir_{_XDIST_WORKER}" if _XDIST_WORKER else "pytest_cache_dir")
    ),
)

# ── Override tmp_path to avoid sandbox-locked dirs ──────────────────
# DSH sandbox locks directories created by pytest's internal TempPathFactory.
# We override tmp_path and tmp_path_factory to use workspace-writable dirs
# that we create ourselves (which are NOT locked).
import pytest  # noqa: E402  # 必须在环境变量设置之后导入（conftest 的时序要求）

_WORKSPACE_TMP = pathlib.Path(__file__).resolve().parent.parent.parent / "data" / "pytest_tmp"
_SYSTEM_TMP = pathlib.Path(os.environ.get("TEMP") or tempfile.gettempdir())

# 本机实测（2026-09-23）：同一份 ~30KB SQLite DDL，落在仓库目录（data/pytest_tmp）
# 每个 API 用例要 ~4s，落在系统临时目录只要 ~0.3s（~12 倍差）。慢的不是 fixture
# 也不是 TestClient，而是仓库目录上的 SQLite 文件 IO——典型的实时杀毒/索引服务
# 对仓库路径的实时扫描放大了每条 DDL 的提交成本。
# 策略：优先用系统临时目录（快）；仅在探测到系统临时目录不可写时回退仓库目录
# （保留当年 DSH 沙箱锁定 pytest 默认临时目录时的兼容性）。


def _pick_tmp_base() -> pathlib.Path:
    """选择 per-test 临时目录的根：系统 TEMP 可写则优先，否则回退仓库内目录。"""
    probe = _SYSTEM_TMP / f"pytest_probe_{uuid.uuid4().hex[:8]}"
    try:
        probe.mkdir(parents=True, exist_ok=True)
        probe.rmdir()
        return _SYSTEM_TMP
    except OSError:
        return _WORKSPACE_TMP


_TMP_BASE = _pick_tmp_base()


@pytest.fixture
def tmp_path(request):
    """Override tmp_path to use a workspace-writable directory.

    DSH sandbox may lock pytest's default temp dirs. This fixture creates
    per-test dirs under a writable base (system TEMP preferred for speed;
    falls back to data/pytest_tmp/ inside the workspace).
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
    d = _TMP_BASE / f"{test_name}_{uuid.uuid4().hex[:8]}"
    d.mkdir(parents=True, exist_ok=True)
    yield d
    # Cleanup (best-effort)
    import contextlib
    import shutil

    with contextlib.suppress(Exception):
        shutil.rmtree(d, ignore_errors=True)


# ── xdist worker 启动时重置本 worker 独立库并建好 schema ──────
# 每个 worker 的 DB_PATH 是独立文件（见上方 DB_PATH 强制赋值）。但文件
# 跨运行持久：上一轮残留的 usr_alice/key_1234 等固定 ID 行会让本轮
# 的 INSERT 撞 UNIQUE（串行模式靠其他文件的清理 fixture 顺序性擦库
# 侥幸避开，并行下顺序不定必炸）。worker 会话开始时直接删库文件再
# init_db()，等价于 CI 每次都是全新库，跨轮次确定性。串行单进程
# （master）不删除，保持既有行为。
# xdist worker 会话开始时直接删库文件再 init_db()，等价于 CI 每次都是
# 全新库，跨轮次确定性。
#
# 串行（master）进程也要保证 schema 存在：不少用例（如 test_daily_briefing）
# 直连 DB_PATH 却从不 init_db()，过去靠仓库里历史残留的 data/test.db 带着
# 旧 schema 侥幸通过——全新 checkout / CI runner 上首个串行用例必红
# （no such table）。串行路径不删库（保留既有行为与跨运行残留数据），
# 只做幂等 init_db() 补齐缺失表。
def pytest_configure(config):
    import contextlib

    # 删库重建统一适用于串行与 xdist worker：洁净度快照（见下方
    # _default_db_cleanliness_snapshot）要从已知空库开始累积，否则本机
    # 历史残留会让快照无意义。规则一/二守卫 + 空库酸测已把所有隐式依赖
    # 清干净（2026-09-28/29），「串行保留残留」的旧行为不再有存在价值。
    db_file = pathlib.Path(os.environ["DB_PATH"])
    for suffix in ("", "-wal", "-shm"):
        with contextlib.suppress(OSError):
            db_file.with_name(db_file.name + suffix).unlink()

    from app.db import init_db

    init_db()


# ── 会话级默认库洁净度快照（守卫体系的动态验收基线）────────────
# 历史教训（2026-09-29 两次重设计）：
#
# 首版「会话结束默认库必须零业务行」在 xdist 下不可用：worker 跑互不
# 相交的测试子集，teardown 时库里的行多来自其它测试经 own-library
# fixture（tmp_path 重定向后撒种子）留下的——但 xdist 下 8 个 worker
# 共用同一个 data/test.db？不，worker 各有独立文件。真正的问题：
# own-library fixture 写的是 settings.db_path **重定向后的 tmp 库**，
# 不落默认库。但审计发现 2693 个 per-test 误报的根因：**大量用例合法
# 地写默认库**——规则一/二要求的是「有自救建库+自播种」，即默认库
# 写了行后同文件或后续文件会读回清理；这不是污染，而是既定隔离模式。
#
# 「任何行即红」的绝对口径与现有测试体系不兼容；能机器化的口径是：
# **每轮全量跑完，把默认库的实际内容快照到 data/test.db.cleanliness.json，
# 与上一轮 diff** ——意外的新增表/暴增行数（污染信号）在 diff 中现形，
# 人工核查后才进入基线。这把「洁净度」从二值断言降为**可审阅的漂移
# 追踪**，诚实反映「默认库是共享介质」的现实，不制造虚假红。
# 完整实证数据与分析：docs/testing-default-db-cleanliness.md
#
# 量级信息在快照顶部：非零表清单即当前体系的真实足迹（2026-09-28
# 酸测审计确认的 39 个灰区/探针文件的播种产物）。
#
# xdist 下的两个实测缺陷（2026-09-29 后记实证，docs 同文）：
# A. 快照路径是 db_file.parent / "test.db.cleanliness.json"（文件名硬编码，
#    不随库名变），8 个 worker teardown 各写同一个文件 → last-writer-wins，
#    实测基线被盖成 gw3 的 44 表子集足迹；串行/xdist 两种介质足迹本来就
#    不同，模式混用时基线被轮流覆盖，diff 参照系每轮都在漂。
# B. worker 的 teardown print 被 xdist 捕获（-s 也不改变 worker 内捕获），
#    diff 提示在主要验收形态下不可达 → 哨兵探针实证：串行 -s 有警告，
#    -n 2 -s 零警告。覆盖发生时无人看见。
# 最小修复：只有非 worker 进程写快照（controller 不跑用例、fixture 不激活，
# 天然不写）；快照内容带 _mode 标注，读到异模式基线时在 diff 提示里注明。
# 语义：xdist 全量验收 = 不碰基线；基线由串行验收轮维护。
# 基线分流（消除串行全量 ↔ 串行酸测交替时的预期内大 diff）：
# 两者都是单进程、足迹却截然不同（全量 projects=118 vs 酸测残留 projects=9），
# 共用一份基线时每次交替都会出一条千行级「增长/清空」警告——预期差异不是
# 污染信号，不该以大 diff 形式出现。故 _mode 细分为：
#   serial-full  直跑 pytest（默认，环境变量未设时）
#   serial-acid  酸测脚本注入 CLEANLINESS_MODE=acid（verify_test_db_isolation）
# 同模式比对走完整 diff；异模式基线只出**单行模式注记**（数字不可比，
# 逐表列举只会是噪声），基线随本轮覆盖更新。
_CLEANLINESS_WHITELISTED_TABLES = frozenset({"alembic_version"})
# 快照里的保留键：记录写入时的运行模式。表名来自 sqlite_master（已排除
# sqlite_%），不可能以下划线开头，与保留键无冲突风险。
_CLEANLINESS_MODE_KEY = "_mode"
# 酸测脚本（verify_test_db_isolation）会设 CLEANLINESS_MODE=acid；直跑
# pytest（串行全量/单文件）落到默认 serial-full。


@pytest.fixture(scope="session", autouse=True)
def _default_db_cleanliness_snapshot():
    """会话结束时把默认库各业务表行数快照到 data/，与上轮 diff 报告。

    仅非 worker 进程写入：xdist worker 各自是独立介质（test_gwN.db），
    子集足迹既不等于全量足迹，diff 提示也不可达（见上方缺陷 A/B）。
    """
    yield

    # xdist worker 显式跳过：缺陷 A（8 进程 last-writer-wins 覆盖基线）
    # + 缺陷 B（teardown print 不可达，覆盖无人看见）。
    if os.environ.get("PYTEST_XDIST_WORKER"):
        return

    # 本次运行的模式标签（见上方分流说明）。
    cleanliness_mode = "serial-acid" if os.environ.get("CLEANLINESS_MODE") == "acid" else "serial-full"

    import contextlib
    import json
    import sqlite3

    from app.config import settings

    db_file = pathlib.Path(settings.db_path)
    if not db_file.is_absolute():
        db_file = pathlib.Path.cwd().parent / db_file
    if not db_file.exists():
        return

    snapshot: dict[str, int] = {}
    conn = sqlite3.connect(db_file)
    try:
        tables = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        ]
        for table in tables:
            if table in _CLEANLINESS_WHITELISTED_TABLES:
                continue
            # 表名来自 sqlite_master 白名单枚举而非用户输入，f-string 拼接安全（S608）
            snapshot[table] = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]  # noqa: S608
    finally:
        conn.close()

    snapshot_path = db_file.parent / "test.db.cleanliness.json"
    prev_raw = None
    if snapshot_path.exists():
        try:
            prev_raw = json.loads(snapshot_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            prev_raw = None

    # 取出基线里的模式标注，剩下的键才是表行数。
    prev: dict[str, int] | None = None
    prev_mode: str | None = None
    if isinstance(prev_raw, dict):
        prev_raw = dict(prev_raw)
        prev_mode = prev_raw.pop(_CLEANLINESS_MODE_KEY, None)
        prev = prev_raw

    if prev is not None and prev != snapshot:
        if prev_mode is not None and prev_mode != cleanliness_mode:
            # 异模式基线：逐表列举只会是噪声（两模式足迹本来就不同），
            # 单行注记说明切换即可，基线随本轮覆盖更新。
            parts = [
                f"基线模式: 上轮由 {prev_mode!r} 写入，本次 {cleanliness_mode!r}"
                " —— 两模式足迹不可比，基线随本轮覆盖更新"
            ]
        else:
            parts = []
            added = {t: n for t, n in snapshot.items() if t not in prev and n}
            grown = {t: (prev[t], n) for t, n in snapshot.items() if t in prev and n > prev[t]}
            removed = {t: prev[t] for t in prev if t not in snapshot or not snapshot.get(t)}
            if added:
                parts.append(f"新出现: {added}")
            if grown:
                parts.append(f"增长: {grown}")
            if removed:
                parts.append(f"清空: {removed}")
        print(
            "\n⚠ 默认库洁净度快照与上一轮不同（非阻断，供审阅）：\n  "
            + "; ".join(parts)
            + f"\n  快照: {snapshot_path}（确认无害后它会随本轮覆盖更新）"
        )

    with contextlib.suppress(OSError):
        # 只读环境下快照写不进去就跳过（diff 提示自然消失）
        payload = dict(snapshot)
        payload[_CLEANLINESS_MODE_KEY] = cleanliness_mode
        snapshot_path.write_text(json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")


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
