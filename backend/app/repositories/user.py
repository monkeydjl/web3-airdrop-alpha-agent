"""User and Auth Repository Layer (V3, ADR-008 & ROADMAP §25.4).

提供 users, sessions, blacklisted_jti 表的数据访问：
- UserRepository: 用户账户数据 CRUD
- SessionRepository: 刷新令牌（Refresh Token）会话管理
- BlacklistedJtiRepository: JWT 吊销黑名单管理
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import structlog

from app.db import DbConnection, dict_from_row

logger = structlog.get_logger(__name__)


class UserRepository:
    """users 表数据访问。"""

    def __init__(self, conn: DbConnection) -> None:
        self.conn = conn

    def create_user(
        self,
        *,
        user_id: str,
        email: str,
        password_hash: str,
        display_name: str | None = None,
        role: str = "viewer",
        preferences: str | None = None,
    ) -> dict[str, Any]:
        """创建新用户。"""
        self.conn.execute(
            """
            INSERT INTO users (id, email, password_hash, display_name, role, is_active, preferences)
            VALUES (?, ?, ?, ?, ?, 1, ?)
            """,
            (user_id, email.lower().strip(), password_hash, display_name, role, preferences),
        )
        self.conn.commit()
        created = self.get_by_id(user_id)
        assert created is not None
        return created

    def get_by_id(self, user_id: str) -> dict[str, Any] | None:
        """根据 ID 查询用户。"""
        row = self.conn.execute(
            "SELECT * FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        return dict_from_row(row) if row else None

    def get_by_email(self, email: str) -> dict[str, Any] | None:
        """根据 Email 查询用户（不区分大小写）。"""
        row = self.conn.execute(
            "SELECT * FROM users WHERE LOWER(email) = LOWER(?)",
            (email.strip(),),
        ).fetchone()
        return dict_from_row(row) if row else None

    def count_users(self) -> int:
        """获取总用户数（用于判断首个注册用户自举为 admin）。"""
        row = self.conn.execute("SELECT COUNT(*) FROM users").fetchone()
        return int(row[0]) if row and row[0] is not None else 0

    def update_last_login(self, user_id: str, last_login_at: datetime | None = None) -> None:
        """更新最后登录时间。"""
        dt = last_login_at or datetime.now(UTC)
        self.conn.execute(
            "UPDATE users SET last_login_at = ? WHERE id = ?",
            (dt, user_id),
        )
        self.conn.commit()

    def update_role(self, user_id: str, role: str) -> None:
        """更新用户角色。"""
        self.conn.execute(
            "UPDATE users SET role = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (role, user_id),
        )
        self.conn.commit()

    def update_preferences(self, user_id: str, preferences_json: str) -> None:
        """更新用户偏好 JSON。"""
        self.conn.execute(
            "UPDATE users SET preferences = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (preferences_json, user_id),
        )
        self.conn.commit()

    def delete_user(self, user_id: str) -> bool:
        """物理删除用户记录（GDPR §25.9）。"""
        cursor = self.conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        self.conn.commit()
        return bool(cursor.rowcount and cursor.rowcount > 0)


class SessionRepository:
    """sessions 表数据访问（Refresh Token 持久化与吊销）。"""

    def __init__(self, conn: DbConnection) -> None:
        self.conn = conn

    def create_session(
        self,
        *,
        session_id: str,
        user_id: str,
        refresh_token_hash: str,
        expires_at: datetime,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> dict[str, Any]:
        """记录新的 Refresh Token 会话。"""
        self.conn.execute(
            """
            INSERT INTO sessions (id, user_id, refresh_token_hash, ip, user_agent, expires_at, revoked)
            VALUES (?, ?, ?, ?, ?, ?, 0)
            """,
            (session_id, user_id, refresh_token_hash, ip, user_agent, expires_at),
        )
        self.conn.commit()
        session = self.get_by_id(session_id)
        assert session is not None
        return session

    def get_by_id(self, session_id: str) -> dict[str, Any] | None:
        """根据 Session ID 查询。"""
        row = self.conn.execute(
            "SELECT * FROM sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        return dict_from_row(row) if row else None

    def get_by_token_hash(self, refresh_token_hash: str) -> dict[str, Any] | None:
        """根据 Refresh Token 哈希查询。"""
        row = self.conn.execute(
            "SELECT * FROM sessions WHERE refresh_token_hash = ?",
            (refresh_token_hash,),
        ).fetchone()
        return dict_from_row(row) if row else None

    def revoke_session(self, session_id: str) -> bool:
        """撤销指定会话。"""
        cursor = self.conn.execute(
            "UPDATE sessions SET revoked = 1 WHERE id = ?",
            (session_id,),
        )
        self.conn.commit()
        return bool(cursor.rowcount and cursor.rowcount > 0)

    def revoke_by_token_hash(self, refresh_token_hash: str) -> bool:
        """根据 Refresh Token 哈希撤销会话。"""
        cursor = self.conn.execute(
            "UPDATE sessions SET revoked = 1 WHERE refresh_token_hash = ?",
            (refresh_token_hash,),
        )
        self.conn.commit()
        return bool(cursor.rowcount and cursor.rowcount > 0)

    def revoke_all_user_sessions(self, user_id: str) -> int:
        """撤销某用户的所有会话（全设备登出）。"""
        cursor = self.conn.execute(
            "UPDATE sessions SET revoked = 1 WHERE user_id = ? AND revoked = 0",
            (user_id,),
        )
        self.conn.commit()
        return int(cursor.rowcount or 0)

    def cleanup_expired(self) -> int:
        """清理已过期且已吊销的会话。"""
        now = datetime.now(UTC)
        cursor = self.conn.execute(
            "DELETE FROM sessions WHERE expires_at < ? OR revoked = 1",
            (now,),
        )
        self.conn.commit()
        return int(cursor.rowcount or 0)


class BlacklistedJtiRepository:
    """blacklisted_jti 表数据访问（JWT 吊销黑名单）。"""

    def __init__(self, conn: DbConnection) -> None:
        self.conn = conn

    def blacklist_jti(self, jti: str, expires_at: datetime) -> None:
        """将 JWT ID 记入黑名单。"""
        self.conn.execute(
            """
            INSERT OR REPLACE INTO blacklisted_jti (jti, expires_at)
            VALUES (?, ?)
            """,
            (jti, expires_at),
        )
        self.conn.commit()

    def is_blacklisted(self, jti: str) -> bool:
        """检查 JTI 是否在黑名单且尚未过期。"""
        row = self.conn.execute(
            "SELECT 1 FROM blacklisted_jti WHERE jti = ?",
            (jti,),
        ).fetchone()
        return bool(row)

    def cleanup_expired(self) -> int:
        """清理已过期的黑名单记录（已过期的 Token 本身无法通过 exp 校验）。"""
        now = datetime.now(UTC)
        cursor = self.conn.execute(
            "DELETE FROM blacklisted_jti WHERE expires_at < ?",
            (now,),
        )
        self.conn.commit()
        return int(cursor.rowcount or 0)
