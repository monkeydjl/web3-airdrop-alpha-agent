"""项目身份解析：别名映射层。

背景：此前项目身份完全由 `(normalize_name(name), normalize_sector(sector))`
经 UUID v5 决定。项目一旦改名、赛道写法变化、或不同数据源给出不同名称，
就会生成第二个 `project_id`，`projects` 出现重复行，`project_history`、
评分与反馈被劈成两条互不相干的记录。

这里引入别名表（复用既有空表 `dedup_keys`）作为解析入口，优先级从高到低：

1. 手工精确键 `name::Sector`
2. 手工名称级键 `name::*`（仅手工可配置）
3. 回填精确键（`backfill`，来自既有 projects 行）
4. 自动精确键（`auto`，同源归并后学习）
5. 历史自动名称级键 `name::*`
6. 兜底：旧的 `uuid5("name::sector")`

未命中任何别名时结果与旧逻辑**逐字节一致**，保证既有项目 ID 不漂移。
`raw_projects.dedup_key` 的语义（源内唯一 / 已处理标记）不受影响。
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog

from app.db import DbConnection, connection_scope, dict_from_row
from app.utils.normalize import (
    DedupKey,
    generate_deterministic_id,
    normalize_name,
    normalize_sector,
)

logger = structlog.get_logger(__name__)

# 别名来源。数值越小优先级越高；只有 manual 可以写名称级（name::*）键。
ALIAS_SOURCE_MANUAL = "manual"
ALIAS_SOURCE_BACKFILL = "backfill"
ALIAS_SOURCE_AUTO = "auto"

_SOURCE_RANK = {
    ALIAS_SOURCE_MANUAL: 0,
    ALIAS_SOURCE_BACKFILL: 1,
    ALIAS_SOURCE_AUTO: 2,
}

_DEFAULT_CONFIDENCE = {
    ALIAS_SOURCE_MANUAL: 1.0,
    ALIAS_SOURCE_BACKFILL: 0.9,
    ALIAS_SOURCE_AUTO: 0.5,
}

# 名称级别名的赛道段。`name::*` 表示「这个名字下所有赛道都归到同一项目」。
NAME_WIDE_SECTOR = "*"


def make_alias_key(name: str, sector: str | None = None, *, name_wide: bool = False) -> str:
    """构造规范别名键。

    `name_wide=True` 时返回 `name::*`；否则返回 `name::Sector`，
    sector 为空按 "Unknown" 处理（与 `create_dedup_key` 口径一致）。
    """
    name_key = normalize_name(name or "")
    sector_key = NAME_WIDE_SECTOR if name_wide else normalize_sector(sector or "Unknown")
    return f"{name_key}::{sector_key}"


def split_alias_key(alias_key: str, *, allow_empty_name: bool = False) -> tuple[str, str]:
    """把任意写法的别名键拆成 (规范化 name_key, 规范化 sector_key)。

    `allow_empty_name=True` 仅供解析路径使用：名称缺失的畸形记录没有别名意义，
    但仍需回落到旧 uuid5（写路径必须保持严格）。
    """
    raw = (alias_key or "").strip()
    name_part, sep, sector_part = raw.partition("::")
    if not sep or (not name_part.strip() and not allow_empty_name):
        raise ValueError(f"非法别名键（应为 name::Sector 或 name::*）：{alias_key!r}")
    name_key = normalize_name(name_part)
    if not name_key and not allow_empty_name:
        raise ValueError(f"别名键的项目名为空：{alias_key!r}")
    sector_part = sector_part.strip()
    sector_key = NAME_WIDE_SECTOR if sector_part == NAME_WIDE_SECTOR else normalize_sector(sector_part or "Unknown")
    return name_key, sector_key


def normalize_alias_key(alias_key: str) -> str:
    """把别名键统一成「规范化 name::规范化 sector」。"""
    name_key, sector_key = split_alias_key(alias_key)
    return f"{name_key}::{sector_key}"


@dataclass(frozen=True)
class ResolvedIdentity:
    """一次身份解析的结果。"""

    project_id: str
    name_key: str
    sector_key: str
    alias_key: str
    # None = 未命中别名，走了旧 uuid5 兜底
    source: str | None
    confidence: float
    # manual_exact / manual_name / backfill_exact / auto_exact / auto_name / legacy
    matched: str

    @property
    def is_legacy(self) -> bool:
        return self.source is None


class ProjectIdentityResolver:
    """别名表解析器。

    实例持有别名索引的内存副本，首次解析时从库里加载一次；写操作后自动失效。
    连接来源：
    - 构造时注入 `conn` → 借用该连接，不负责关闭（便于测试/app 级共享连接）；
    - 未注入 → 每次操作在 `connection_scope()` 内自建并关闭。

    索引加载失败（表还没建、库不可用）时退化为空索引并打 warning，
    解析结果回落到旧 uuid5 —— 身份层不可用不应阻断采集流水线。
    """

    def __init__(self, conn: DbConnection | None = None) -> None:
        self._conn = conn
        self._lock = threading.RLock()
        self._exact: dict[str, tuple[str, str, float]] = {}
        self._namewide: dict[str, tuple[str, str, float]] = {}
        self._loaded = False

    # ── 索引 ────────────────────────────────────

    def _scope(self) -> Any:
        return connection_scope(self._conn)

    def _load(self) -> None:
        with self._lock:
            if self._loaded:
                return
            exact: dict[str, tuple[str, str, float]] = {}
            namewide: dict[str, tuple[str, str, float]] = {}
            try:
                with self._scope() as conn:
                    rows = conn.execute(
                        """
                        SELECT dedup_key, project_id, source, confidence
                        FROM dedup_keys
                        WHERE source IN ('manual', 'backfill', 'auto')
                        """
                    ).fetchall()
                for raw_row in rows:
                    row = dict_from_row(raw_row)
                    source = str(row.get("source") or "")
                    project_id = str(row.get("project_id") or "").strip()
                    if source not in _SOURCE_RANK or not project_id:
                        continue
                    try:
                        key = normalize_alias_key(str(row.get("dedup_key") or ""))
                    except ValueError:
                        continue
                    _, sector_key = split_alias_key(key)
                    confidence = row.get("confidence")
                    conf = _DEFAULT_CONFIDENCE[source] if confidence is None else float(confidence)
                    target = namewide if sector_key == NAME_WIDE_SECTOR else exact
                    target[key] = (project_id, source, conf)
            except Exception as exc:  # 身份层不可用不阻断流水线
                logger.warning(
                    "identity.alias_index_load_failed",
                    error_type=type(exc).__name__,
                    error=str(exc)[:200],
                )
            self._exact, self._namewide, self._loaded = exact, namewide, True

    def invalidate(self) -> None:
        """丢弃内存索引，下次解析重新加载。"""
        with self._lock:
            self._loaded = False

    def reload(self) -> None:
        self.invalidate()
        self._load()

    # ── 解析 ────────────────────────────────────

    def resolve(self, name: str, sector: str | None = None) -> ResolvedIdentity:
        """按名称 + 赛道解析项目身份。"""
        return self._resolve_keys(normalize_name(name or ""), normalize_sector(sector or "Unknown"))

    def resolve_key(self, alias_key: str) -> ResolvedIdentity:
        """按别名键解析项目身份（键可以是任意写法，内部会归一化）。"""
        name_key, sector_key = split_alias_key(alias_key, allow_empty_name=True)
        return self._resolve_keys(name_key, sector_key)

    def _resolve_keys(self, name_key: str, sector_key: str) -> ResolvedIdentity:
        if not name_key:
            # 名称缺失的畸形记录：别名对它没意义，保持旧 uuid5 行为而不是抛错。
            # 采集侧以前能容忍这种行，身份层不能让整批采集因此中断。
            return self._legacy_identity(name_key, sector_key)

        self._load()
        exact_key = f"{name_key}::{sector_key}"
        wide_key = f"{name_key}::{NAME_WIDE_SECTOR}"

        # 顺序即优先级：手工精确 → 手工名称级 → 回填精确 → 自动精确 → 自动名称级
        for source, matched, table, key in (
            (ALIAS_SOURCE_MANUAL, "manual_exact", self._exact, exact_key),
            (ALIAS_SOURCE_MANUAL, "manual_name", self._namewide, wide_key),
            (ALIAS_SOURCE_BACKFILL, "backfill_exact", self._exact, exact_key),
            (ALIAS_SOURCE_AUTO, "auto_exact", self._exact, exact_key),
            (ALIAS_SOURCE_AUTO, "auto_name", self._namewide, wide_key),
        ):
            hit = table.get(key)
            if hit is not None and hit[1] == source:
                return ResolvedIdentity(
                    project_id=hit[0],
                    name_key=name_key,
                    sector_key=sector_key,
                    alias_key=key,
                    source=source,
                    confidence=hit[2],
                    matched=matched,
                )

        # 兜底：与改造前的确定性 ID 完全一致
        return self._legacy_identity(name_key, sector_key)

    def _legacy_identity(self, name_key: str, sector_key: str) -> ResolvedIdentity:
        legacy_key = DedupKey(name_key=name_key, sector_key=sector_key)
        return ResolvedIdentity(
            project_id=generate_deterministic_id(legacy_key),
            name_key=name_key,
            sector_key=sector_key,
            alias_key=legacy_key.to_string(),
            source=None,
            confidence=0.0,
            matched="legacy",
        )

    # ── 写入 ────────────────────────────────────

    def upsert_alias(
        self,
        dedup_key: str,
        project_id: str,
        *,
        source: str = ALIAS_SOURCE_MANUAL,
        confidence: float | None = None,
        notes: str | None = None,
        name_raw: str | None = None,
        sector_raw: str | None = None,
    ) -> dict[str, Any]:
        """写入一条别名，并返回是否真的生效。

        降级保护：
        - `auto` / `backfill` 不得覆盖 `manual`；
        - `auto` 不得覆盖 `backfill`。
        同源重复写入（例如手工纠正手工）允许覆盖 `project_id`。
        """
        if source not in _SOURCE_RANK:
            raise ValueError(f"未知别名来源：{source!r}")
        key = normalize_alias_key(dedup_key)
        name_key, sector_key = split_alias_key(key)
        if sector_key == NAME_WIDE_SECTOR and source != ALIAS_SOURCE_MANUAL:
            raise ValueError("只有手工别名可以配置名称级（name::*）键")
        if not str(project_id or "").strip():
            raise ValueError("project_id 不能为空")

        conf = _DEFAULT_CONFIDENCE[source] if confidence is None else float(confidence)
        with self._scope() as conn:
            existing = conn.execute(
                "SELECT source FROM dedup_keys WHERE dedup_key = ?",
                (key,),
            ).fetchone()
            current_source = str(dict_from_row(existing).get("source") or "") if existing is not None else ""
            if _SOURCE_RANK.get(current_source, 99) < _SOURCE_RANK[source]:
                logger.info(
                    "identity.alias_upsert_rejected",
                    alias_key=key,
                    existing_source=current_source,
                    attempted_source=source,
                )
                return {
                    "applied": False,
                    "reason": f"{current_source}_alias_protected",
                    "alias_key": key,
                }
            conn.execute(
                """
                INSERT INTO dedup_keys
                    (dedup_key, project_id, name_raw, sector_raw, source, confidence, notes, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(dedup_key) DO UPDATE SET
                    project_id = excluded.project_id,
                    name_raw = excluded.name_raw,
                    sector_raw = excluded.sector_raw,
                    source = excluded.source,
                    confidence = excluded.confidence,
                    notes = excluded.notes,
                    updated_at = datetime('now')
                """,
                (
                    key,
                    project_id,
                    name_raw if name_raw is not None else name_key,
                    sector_raw if sector_raw is not None else sector_key,
                    source,
                    conf,
                    notes,
                ),
            )
            conn.commit()
        self.invalidate()
        return {"applied": True, "alias_key": key, "project_id": project_id, "source": source}

    def learn_auto_aliases(self, entries: Iterable[tuple[str, str]]) -> int:
        """从同源归并结果中学习自动别名（best-effort）。

        `entries` 为 `(别名键, project_id)`。只写精确键，不写名称级；
        已有 manual / backfill 条目不会被覆盖（由 SQL 的 WHERE 保证）。
        返回实际写入/更新的行数。
        """
        applied = 0
        try:
            with self._scope() as conn:
                for alias_key, project_id in entries:
                    try:
                        key = normalize_alias_key(alias_key)
                    except ValueError:
                        continue
                    name_key, sector_key = split_alias_key(key)
                    if sector_key == NAME_WIDE_SECTOR:
                        continue
                    cursor = conn.execute(
                        """
                        INSERT INTO dedup_keys
                            (dedup_key, project_id, name_raw, sector_raw, source, confidence, notes, updated_at)
                        VALUES (?, ?, ?, ?, 'auto', ?, ?, datetime('now'))
                        ON CONFLICT(dedup_key) DO UPDATE SET
                            project_id = excluded.project_id,
                            confidence = excluded.confidence,
                            updated_at = datetime('now')
                        WHERE dedup_keys.source = 'auto'
                        """,
                        (
                            key,
                            project_id,
                            name_key,
                            sector_key,
                            _DEFAULT_CONFIDENCE[ALIAS_SOURCE_AUTO],
                            "learned: 同源归并",
                        ),
                    )
                    applied += max(int(getattr(cursor, "rowcount", 0) or 0), 0)
                conn.commit()
        except Exception as exc:
            logger.warning(
                "identity.auto_alias_learn_failed",
                error_type=type(exc).__name__,
                error=str(exc)[:200],
            )
            return applied
        if applied:
            self.invalidate()
        return applied

    # ── 查询 / 删除 ──────────────────────────────

    def list_aliases(
        self,
        *,
        project_id: str | None = None,
        source: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        sql = (
            "SELECT id, dedup_key, project_id, name_raw, sector_raw, source, confidence, notes, "
            "created_at, updated_at FROM dedup_keys WHERE source IS NOT NULL"
        )
        params: list[Any] = []
        if project_id:
            sql += " AND project_id = ?"
            params.append(project_id)
        if source:
            sql += " AND source = ?"
            params.append(source)
        sql += " ORDER BY project_id, dedup_key LIMIT ?"
        params.append(max(1, min(int(limit), 5000)))
        with self._scope() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict_from_row(row) for row in rows]

    def delete_alias(self, alias_id: int) -> bool:
        with self._scope() as conn:
            cursor = conn.execute(
                "DELETE FROM dedup_keys WHERE id = ? AND source IS NOT NULL",
                (alias_id,),
            )
            conn.commit()
            deleted = int(getattr(cursor, "rowcount", 0) or 0) > 0
        if deleted:
            self.invalidate()
        return deleted

    def load_manual_aliases(self, payload: dict[str, Any]) -> dict[str, int]:
        """按 JSON 载荷批量写入手工别名。

        支持两种条目写法：
        - `{"dedup_key": "foo::DeFi", "project_id": "..."}`
        - `{"name": "Foo", "sector": "DeFi", "project_id": "...", "name_wide": false}`
        """
        entries = payload.get("aliases") if isinstance(payload, dict) else None
        if not isinstance(entries, list):
            return {"applied": 0, "skipped": 0}
        applied = skipped = 0
        for entry in entries:
            if not isinstance(entry, dict):
                skipped += 1
                continue
            project_id = str(entry.get("project_id") or "").strip()
            if not project_id:
                skipped += 1
                continue
            if entry.get("dedup_key"):
                dedup_key = str(entry["dedup_key"])
            elif entry.get("name"):
                dedup_key = make_alias_key(
                    str(entry["name"]),
                    entry.get("sector"),
                    name_wide=bool(entry.get("name_wide")),
                )
            else:
                skipped += 1
                continue
            try:
                result = self.upsert_alias(
                    dedup_key,
                    project_id,
                    source=ALIAS_SOURCE_MANUAL,
                    confidence=entry.get("confidence"),
                    notes=str(entry.get("notes") or "manual file"),
                )
            except ValueError:
                skipped += 1
                continue
            if result.get("applied"):
                applied += 1
            else:
                skipped += 1
        return {"applied": applied, "skipped": skipped}


def load_manual_aliases_file(path: str, *, conn: DbConnection | None = None) -> dict[str, Any]:
    """读取 JSON 别名文件并同步为 manual 别名。文件不存在时返回 skipped。"""
    file_path = Path(path)
    if not file_path.is_file():
        logger.warning("identity.alias_file_missing", path=str(file_path))
        return {"applied": 0, "skipped": 0, "error": "file_not_found"}
    payload = json.loads(file_path.read_text(encoding="utf-8"))
    resolver = ProjectIdentityResolver(conn)
    stats = resolver.load_manual_aliases(payload)
    return {**stats, "path": str(file_path)}


@dataclass(frozen=True)
class BackfillReport:
    """别名回填报告（dry-run 与 --apply 共用）。"""

    apply: bool
    scanned: int
    already_pinned: int
    creatable: list[dict[str, Any]]
    conflicts: list[dict[str, Any]]
    applied: int

    def to_dict(self, *, sample: int = 20) -> dict[str, Any]:
        return {
            "apply": self.apply,
            "scanned": self.scanned,
            "already_pinned": self.already_pinned,
            "candidate_count": len(self.creatable),
            "conflict_count": len(self.conflicts),
            "applied": self.applied,
            "candidates": self.creatable[:sample],
            "conflicts": self.conflicts[:sample],
        }


def backfill_project_aliases(
    *,
    apply: bool = False,
    conn: DbConnection | None = None,
    limit: int | None = None,
) -> BackfillReport:
    """把既有 `projects` 行的 ID 钉成 backfill 别名。

    只读模式（默认）不写库。冲突键（同一别名键对应多个 project_id，
    或已被指向别的项目）**只报告不合并**：合并重复项目是另一件事，
    不在身份解析层里做。
    """
    resolver = ProjectIdentityResolver(conn)
    sql = "SELECT id, name, sector FROM projects ORDER BY id"
    params: list[Any] = []
    if limit:
        sql += " LIMIT ?"
        params.append(int(limit))
    with connection_scope(conn) as db:
        rows = db.execute(sql, params).fetchall()

    scanned = 0
    already_pinned = 0
    candidates: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    for raw_row in rows:
        row = dict_from_row(raw_row)
        project_id = str(row.get("id") or "").strip()
        name = str(row.get("name") or "")
        if not project_id or not name:
            continue
        scanned += 1
        alias_key = make_alias_key(name, row.get("sector"))
        identity = resolver.resolve_key(alias_key)
        if not identity.is_legacy:
            if identity.project_id == project_id:
                already_pinned += 1
            else:
                conflicts.append(
                    {
                        "dedup_key": alias_key,
                        "reason": "alias_points_elsewhere",
                        "alias_project_id": identity.project_id,
                        "project_id": project_id,
                        "name": name,
                        "sector": row.get("sector"),
                    }
                )
            continue
        candidates.append(
            {
                "dedup_key": alias_key,
                "project_id": project_id,
                "name": name,
                "sector": row.get("sector"),
            }
        )

    # 同一别名键命中多个 projects 行 → 存量重复，不能随便选一个
    by_key: dict[str, list[str]] = {}
    for item in candidates:
        by_key.setdefault(item["dedup_key"], []).append(item["project_id"])
    duplicated = {key: pids for key, pids in by_key.items() if len(set(pids)) > 1}
    for key, pids in duplicated.items():
        conflicts.append(
            {
                "dedup_key": key,
                "reason": "multiple_projects_share_key",
                "project_ids": sorted(set(pids)),
            }
        )

    creatable = [item for item in candidates if item["dedup_key"] not in duplicated]
    applied = 0
    if apply:
        for item in creatable:
            try:
                result = resolver.upsert_alias(
                    item["dedup_key"],
                    item["project_id"],
                    source=ALIAS_SOURCE_BACKFILL,
                    confidence=_DEFAULT_CONFIDENCE[ALIAS_SOURCE_BACKFILL],
                    notes="backfill: 既有 projects 行",
                    sector_raw=str(item.get("sector") or ""),
                )
            except Exception as exc:
                logger.warning(
                    "identity.backfill_write_failed",
                    alias_key=item["dedup_key"],
                    error_type=type(exc).__name__,
                    error=str(exc)[:200],
                )
                continue
            if result.get("applied"):
                applied += 1

    report = BackfillReport(
        apply=apply,
        scanned=scanned,
        already_pinned=already_pinned,
        creatable=creatable,
        conflicts=conflicts,
        applied=applied,
    )
    logger.info(
        "identity.backfill_completed",
        apply=apply,
        scanned=scanned,
        already_pinned=already_pinned,
        candidate_count=len(creatable),
        conflict_count=len(conflicts),
        applied=applied,
    )
    return report
