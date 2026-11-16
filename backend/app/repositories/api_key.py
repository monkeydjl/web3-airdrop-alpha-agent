"""ApiKey Repository Layer (V3, ADR-008 & ROADMAP §25.3.3, §25.4).

提供 api_keys 表的数据访问与安全验证：
- ApiKeyRepository: API Key CRUD、安全校验与吊销
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import structlog

from app.auth import verify_password
from app.db import DbConnection, dict_from_row

logger = structlog.get_logger(__name__)


class ApiKeyRepository:
    """api_keys 表数据访问。"""

    def __init__(self, conn: DbConnection) -> None:
        self.conn = conn

    def create_key(
        self,
        *,
        key_id: str,
        user_id: str,
        name: str,
        key_hash: str,
        role: str,
        expires_at: datetime | None = None,
    ) -> dict[str, Any]:
        """创建新 API Key 记录（仅保存哈希）。"""
        self.conn.execute(
            """
            INSERT INTO api_keys (id, user_id, name, key_hash, role, expires_at, is_revoked)
            VALUES (?, ?, ?, ?, ?, ?, 0)
            """,
            (key_id, user_id, name.strip(), key_hash, role, expires_at),
        )
        self.conn.commit()
        record = self.get_by_id(key_id)
        assert record is not None
        return record

    def get_by_id(self, key_id: str) -> dict[str, Any] | None:
        """根据 Key ID 查询。"""
        row = self.conn.execute(
            "SELECT * FROM api_keys WHERE id = ?",
            (key_id,),
        ).fetchone()
        return dict_from_row(row) if row else None

    def list_by_user(self, user_id: str, include_revoked: bool = False) -> list[dict[str, Any]]:
        """列出指定用户的 API Key。"""
        if include_revoked:
            rows = self.conn.execute(
                "SELECT * FROM api_keys WHERE user_id = ? ORDER BY created_at DESC",
                (user_id,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM api_keys WHERE user_id = ? AND is_revoked = 0 ORDER BY created_at DESC",
                (user_id,),
            ).fetchall()
        return [dict_from_row(r) for r in rows if r]

    def list_all(self, include_revoked: bool = False) -> list[dict[str, Any]]:
        """列出系统中所有 API Key（仅管理员）。"""
        if include_revoked:
            rows = self.conn.execute(
                "SELECT * FROM api_keys ORDER BY created_at DESC",
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM api_keys WHERE is_revoked = 0 ORDER BY created_at DESC",
            ).fetchall()
        return [dict_from_row(r) for r in rows if r]

    def revoke_key(self, key_id: str, user_id: str | None = None) -> bool:
        """撤销指定 API Key。若指定了 user_id，则必须归属于该用户。"""
        if user_id:
            cursor = self.conn.execute(
                "UPDATE api_keys SET is_revoked = 1 WHERE id = ? AND user_id = ? AND is_revoked = 0",
                (key_id, user_id),
            )
        else:
            cursor = self.conn.execute(
                "UPDATE api_keys SET is_revoked = 1 WHERE id = ? AND is_revoked = 0",
                (key_id,),
            )
        self.conn.commit()
        return bool(cursor.rowcount and cursor.rowcount > 0)

    def update_last_used(self, key_id: str, last_used_at: datetime | None = None) -> None:
        """更新最后使用时间。"""
        dt = last_used_at or datetime.now(UTC)
        self.conn.execute(
            "UPDATE api_keys SET last_used_at = ? WHERE id = ?",
            (dt, key_id),
        )
        self.conn.commit()

    def find_active_key_by_raw(self, raw_key: str) -> dict[str, Any] | None:
        """根据明文 raw_key 验证并查找有效未撤销的 API Key 记录。

        优先通过 ak_{key_id_hex}_{secret} 格式在 O(1) 内检索主键行，避免全表扫描。

        安全语义（2026-11-13）：`ak_` 格式**解析成功后快速路径即权威判定** ——
        key_hash 是按整个 raw key 算的，未命中 / 已吊销 / 已过期 / 密文不匹配时，
        全表扫描不可能"救回"结果，只会把每个请求变成 N 次逐行 bcrypt（格式合法
        但不存在的 key 就能持续吃满 CPU，放大 DoS）。全表扫描只保留给历史格式的
        兼容查找。
        """
        raw = raw_key.strip()
        now = datetime.now(UTC)

        # 1. ak_{key_id_hex}_{secret}：主键检索，命中与否都到此为止
        if raw.startswith("ak_"):
            parts = raw.split("_", 2)
            if len(parts) == 3 and len(parts[1]) == 16:
                record = self.get_by_id(f"key_{parts[1]}")
                if not record or record.get("is_revoked") or self._expired(record.get("expires_at"), now):
                    return None
                if verify_password(raw, str(record["key_hash"])):
                    return record
                return None

        # 2. 历史格式兼容：扫描当前所有未撤销的 API Key 并校验 bcrypt
        rows = self.conn.execute(
            "SELECT * FROM api_keys WHERE is_revoked = 0",
        ).fetchall()
        for r in rows:
            record = dict_from_row(r)
            if not record:
                continue
            if self._expired(record.get("expires_at"), now):
                continue
            if verify_password(raw, str(record["key_hash"])):
                return record

        return None

    @staticmethod
    def _expired(expires_at: Any, now: datetime) -> bool:
        """expires_at 是否已过（容忍 str / datetime / None 三种存态）。

        解析失败按未过期处理 —— 与历史行为一致：坏数据不该把有效 key 锁死。
        """
        if not expires_at:
            return False
        if isinstance(expires_at, str):
            try:
                exp_dt = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            except Exception:
                return False
        elif isinstance(expires_at, datetime):
            exp_dt = expires_at if expires_at.tzinfo else expires_at.replace(tzinfo=UTC)
        else:
            return False
        return bool(exp_dt and exp_dt < now)
