"""backfill_structured_signals.py 的门禁：存量行结构化 Anti-PUA 信号回填。

背景（2026-09-27）：opportunity evidence 的 fatigue/friction 输入从
description/sector 文本匹配切换为 meta.signals 三个结构化键后，存量行
全部缺失 → 回退保守默认档。本脚本从 description/sector 一次性提取候选值。

置信度分档（脚本的灵魂，测试逐条钉住）：
- is_perp：高置信（复用主评分 agents.risk.is_perp_dex）→ 自动写库；
- tge_clarity：中置信（confirmed + TGE/季度词共现）→ 自动写库；
  "模糊/未确认"没有可靠词形，一律不写（缺失与 unannounced 等价）；
- points_season_count：低置信（词形匹配误报面大）→ 只进审核清单 CSV，
  永不写库，人工核对后手工处理。

其余硬契约：
- 只补缺失键，已有 signals 值绝不覆盖；
- 季数候选只取 >=2（=1 与默认档等价，没有信息量）；
- 词边界匹配："s3x" / "perplexity" 不得命中；
- dry-run 不写库；--apply 先备份、只 UPDATE meta 列、产出 manifest。
"""

from __future__ import annotations

import csv
import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

from app.db import init_db

BACKEND_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = BACKEND_ROOT / "scripts" / "backfill_structured_signals.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("backfill_structured_signals", SCRIPT)
    assert spec and spec.loader, f"{SCRIPT} 不存在 —— 被测对象没了。"
    mod = importlib.util.module_from_spec(spec)
    sys.modules["backfill_structured_signals"] = mod
    spec.loader.exec_module(mod)
    return mod


mod = _load_script()


# ── 提取规则单测 ──────────────────────────────────────────────


def test_season_word_boundary_rejects_deceptive_substrings():
    """旧实现的灵魂问题："s3x" 命中 s3、"support 3" 类裸数字误伤——新词表必须拒绝。"""
    assert mod.extract_season_count("an s3x protocol with s3x marketing") is None
    assert mod.extract_season_count("the s3x standard") is None
    assert mod.extract_season_count("support 3 languages, version 2 rollout") is None
    assert mod.extract_season_count("the third season of our campaign") is None  # 文字数字不匹配
    assert mod.extract_season_count("") is None
    # 中文前后断言：相邻数字不允许,非数字相邻允许
    assert mod.extract_season_count("第13季") is None
    assert mod.extract_season_count("第 13 季") is None


def test_extract_uses_signals_description_storage():
    """描述存于 meta.signals.description（projects 表无 description 列）。"""
    project = {"id": "p", "name": "p", "sector": "DEX", "stage": "testnet"}
    signals = {"description": "perpetual futures dex, TGE confirmed for Q3 2026, season 3"}
    assert mod.extract_is_perp(project, signals) is True
    assert mod.derive_candidates(project, signals) == {"is_perp": True, "tge_clarity": "confirmed_quarter"}


def test_season_accepts_only_informative_values():
    # =1 与保守默认档等价，不写（无信息量）
    assert mod.extract_season_count("season 1 live now") is None
    assert mod.extract_season_count("points season is live") is None
    # 合法词形
    assert mod.extract_season_count("season 2 rewards") == (2, "season 2")
    assert mod.extract_season_count("Season 3-5 planned") == (5, "Season 3-5")
    assert mod.extract_season_count("第 3 季进行中") == (3, "第 3 季")
    assert mod.extract_season_count("join s2 before it ends") == (2, "s2")
    # 多段命中取最大；>10 钳制拒绝
    assert mod.extract_season_count("season 2 then season 4") == (4, "season 4")
    assert mod.extract_season_count("season 99") is None


def test_tge_clarity_requires_confirmed_and_time_anchor():
    assert mod.extract_tge_clarity("TGE confirmed for Q3 2026") == "confirmed_quarter"
    assert mod.extract_tge_clarity("token generation event confirmed by the team") == "confirmed_quarter"
    assert mod.extract_tge_clarity("Q2 2026 launch window announced") == "confirmed_quarter"
    # 模糊/未确认没有可靠词形——不写
    assert mod.extract_tge_clarity("TGE coming soon, stay tuned") is None
    assert mod.extract_tge_clarity("tge announced without a date") is None
    assert mod.extract_tge_clarity("airdrop confirmed") is None  # 确认词但无时间锚


def test_is_perp_reuses_scorer_judgement_and_ignores_name():
    """与主评分同一判定器；且不因项目名含 perp 词而误判（is_perp_dex 的既有契约）。"""
    perp = {"id": "p1", "name": "p1", "sector": "perp-dex", "description": "swap", "stage": "testnet"}
    clean = {"id": "p2", "name": "PerpX", "sector": "DEX", "description": "an amm", "stage": "testnet"}
    confusing = {
        "id": "p3",
        "name": "p3",
        "sector": "ai",
        "description": "perplexity search engine",
        "stage": "testnet",
    }

    assert mod.extract_is_perp(perp) is True
    assert mod.extract_is_perp(clean) is False
    assert mod.extract_is_perp(confusing) is False
    assert mod.derive_candidates(confusing) == {}


def test_tge_confirmed_only_when_genuine_anchor_present():
    assert (
        mod.derive_candidates(
            {"id": "p", "name": "p", "sector": "l2", "description": "TGE confirmed for Q3 2026", "stage": "testnet"}
        )["tge_clarity"]
        == "confirmed_quarter"
    )


# ── 端到端：内存库 dry-run / apply ────────────────────────────


def _seed_db(tmp_path: Path) -> Path:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    db_path = tmp_path / "seed.db"
    disk = sqlite3.connect(str(db_path))
    conn.backup(disk)
    disk.close()
    conn.close()
    return db_path


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _insert_project(conn: sqlite3.Connection, pid: str, *, description: str = "", meta: str | None = None) -> None:
    """模拟真实保存链路的行形态：描述存于 meta.signals.description（表无该列）。"""
    if meta is None:
        meta = json.dumps({"signals": {"description": description}}, ensure_ascii=False) if description else None
    conn.execute(
        "INSERT INTO projects (id, name, url, sector, stage, source, meta) VALUES (?,?,?,?,?,?,?)",
        (pid, pid, f"https://{pid}.example.com", "DEX", "testnet", "seed", meta),
    )
    conn.commit()


def test_dry_run_writes_nothing_and_emits_review_csv(tmp_path):
    db = _seed_db(tmp_path)
    conn = _connect(db)
    _insert_project(conn, "perp-proj", description="perpetual futures dex")
    _insert_project(conn, "season-proj", description="season 3 rewards are live")
    _insert_project(conn, "clean-proj")
    conn.close()

    rc = None  # noqa: F841 — dry-run 经 sys.argv 驱动 mod.main()
    sys.argv = ["backfill_structured_signals.py", "--db", str(db), "--dry-run"]
    assert mod.main() == 0

    conn = _connect(db)
    for pid in ("perp-proj", "season-proj", "clean-proj"):
        row = dict(conn.execute("SELECT meta FROM projects WHERE id = ?", (pid,)).fetchone())
        signals = json.loads(row["meta"]).get("signals", {}) if row["meta"] else {}
        assert "is_perp" not in signals, f"{pid} 在 dry-run 下不应被写入 is_perp"
        assert "tge_clarity" not in signals and "points_season_count" not in signals
    conn.close()

    reviews = list(db.parent.glob("*.review-*.csv"))
    assert len(reviews) == 1, "审核清单必须恰好产出一份"
    with reviews[0].open(encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))
    assert [r["project_id"] for r in rows] == ["season-proj"], "只有 season 候选进审核清单"
    assert rows[0]["candidate_season"] == "3"
    manifests = list(db.parent.glob("*.manifest-*.json"))
    assert len(manifests) == 1
    manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
    assert manifest["mode"] == "dry-run"


def test_apply_writes_auto_keys_only_and_never_touches_existing(tmp_path):
    db = _seed_db(tmp_path)
    conn = _connect(db)
    existing_meta = json.dumps({"signals": {"is_perp": False, "custom_keep": "v1", "description": "perpetual dex"}})
    _insert_project(conn, "perp-proj", description="perpetual futures dex")
    _insert_project(conn, "season-proj", description="season 2 rewards are live")
    _insert_project(conn, "has-existing", meta=existing_meta)
    conn.close()

    sys.argv = ["backfill_structured_signals.py", "--db", str(db), "--apply"]
    assert mod.main() == 0

    conn = _connect(db)
    perp = json.loads(dict(conn.execute("SELECT meta FROM projects WHERE id='perp-proj'").fetchone())["meta"])
    season = json.loads(dict(conn.execute("SELECT meta FROM projects WHERE id='season-proj'").fetchone())["meta"])
    existing = json.loads(dict(conn.execute("SELECT meta FROM projects WHERE id='has-existing'").fetchone())["meta"])
    conn.close()

    assert perp["signals"]["is_perp"] is True, "高置信 is_perp 必须写库"
    assert "points_season_count" not in perp["signals"]
    assert "points_season_count" not in season["signals"], "season 候选永不写库"
    assert existing["signals"]["is_perp"] is False, "已有值绝不覆盖"
    assert existing["signals"]["custom_keep"] == "v1", "signals 中已有键一律保留"

    # 备份与审计产物
    backups = list(db.parent.glob("*.bak-*"))
    assert len(backups) == 1
    manifest = json.loads(next(db.parent.glob("*.manifest-*.json")).read_text(encoding="utf-8"))
    assert manifest["mode"] == "apply"
    assert manifest["backup"] == str(backups[0])
    added = {u["project_id"]: u["added_keys"] for u in manifest["updates"]}
    assert added["perp-proj"] == "is_perp"
    # has-existing 的 is_perp 已存在且为 False(高置信路径也绝不覆盖已有值),
    # 描述里无 TGE 确认词 → 无新增,不进入 updates
    assert "has-existing" not in added


def test_apply_idempotent_second_run_changes_nothing(tmp_path):
    db = _seed_db(tmp_path)
    conn = _connect(db)
    _insert_project(conn, "perp-proj", description="perpetual futures dex")
    conn.close()

    sys.argv = ["backfill_structured_signals.py", "--db", str(db), "--apply"]
    assert mod.main() == 0
    conn = _connect(db)
    first = dict(conn.execute("SELECT meta FROM projects WHERE id='perp-proj'").fetchone())["meta"]
    conn.close()

    assert mod.main() == 0  # 二次运行
    conn = _connect(db)
    second = dict(conn.execute("SELECT meta FROM projects WHERE id='perp-proj'").fetchone())["meta"]
    conn.close()
    assert first == second, "幂等：已有键不覆盖,二次运行零写入"
