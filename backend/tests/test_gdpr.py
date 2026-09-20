"""GDPR 合规单元测试（ROADMAP §25.9 / ADR-008 §6 / W12-11）。

覆盖：
1. 数据导出：结构完整性、敏感字段（password_hash/key_hash）脱敏、多用户隔离。
2. 账户删除与去标识化：
   - feedback 样本去标识化（user_id 置 NULL，不物理删除样本以保持权重校准）。
   - events 及行为埋点硬删除。
   - watchlist / project_skips / interactions / api_keys / sessions 硬删除。
   - users 记录删除，邮箱释放可重新注册。
   - JWT JTI 记入黑名单。
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

import pytest
from starlette.requests import Request

from app.auth import (
    blacklist_token_jti,
    hash_password,
    is_jti_blacklisted,
)
from app.db import DbConnection, dict_from_row
from app.repositories.user import BlacklistedJtiRepository, SessionRepository, UserRepository
from app.routers.v1.user_data import delete_user_account, export_user_data


def _make_dummy_request(user_id: str, role: str = "viewer", jwt_jti: str | None = None) -> Request:
    """构造携带认证 state 的虚拟 Request 对象。"""
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/v1/user/data",
        "headers": [],
    }
    req = Request(scope)
    req.state.user_id = user_id
    req.state.user_role = role
    req.state.auth_method = "bearer"
    req.state.jwt_jti = jwt_jti
    return req


def _setup_test_db(conn: sqlite3.Connection) -> None:
    """初始化测试库并建表。"""
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            display_name TEXT,
            role TEXT NOT NULL DEFAULT 'viewer',
            is_active INTEGER DEFAULT 1,
            preferences TEXT,
            last_login_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            refresh_token_hash TEXT NOT NULL UNIQUE,
            ip TEXT,
            user_agent TEXT,
            expires_at TIMESTAMP NOT NULL,
            revoked INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS blacklisted_jti (
            jti TEXT PRIMARY KEY,
            expires_at TIMESTAMP NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS api_keys (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            name TEXT NOT NULL,
            key_hash TEXT NOT NULL UNIQUE,
            role TEXT NOT NULL,
            last_used_at TIMESTAMP,
            expires_at TIMESTAMP,
            is_revoked INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id TEXT NOT NULL,
            signal TEXT NOT NULL,
            score_before REAL,
            score_after REAL,
            notes TEXT,
            user_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            event_type TEXT NOT NULL,
            project_id TEXT,
            payload TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS watchlist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS project_skips (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id TEXT NOT NULL,
            user_id TEXT,
            reason TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS interactions (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            user_id TEXT,
            interaction_type TEXT NOT NULL,
            status TEXT NOT NULL,
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS notification_reads (
            user_id TEXT NOT NULL,
            notification_id TEXT NOT NULL,
            read_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, notification_id)
        );
        """
    )
    conn.commit()


@pytest.fixture
def db_conn(monkeypatch, tmp_path):
    """为每个测试创建独立 SQLite 数据库。"""
    db_file = tmp_path / "test_gdpr.db"

    def _get_conn() -> DbConnection:
        conn = sqlite3.connect(str(db_file), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return DbConnection(conn, kind="sqlite")

    with _get_conn() as init_conn:
        _setup_test_db(init_conn._raw)

    monkeypatch.setattr("app.routers.v1.user_data.get_connection", _get_conn)
    monkeypatch.setattr("app.db.get_connection", _get_conn)
    yield _get_conn


def test_export_user_data_completeness_and_sanitization(db_conn):
    """测试导出个人数据的完整性与敏感字段脱敏。"""
    with db_conn() as raw_conn:
        # 插入用户 A 与用户 B
        user_repo = UserRepository(raw_conn)
        user_repo.create_user(
            user_id="usr_alice",
            email="alice@example.com",
            password_hash=hash_password("Password123!"),
            display_name="Alice",
            role="viewer",
            preferences=json.dumps({"theme": "dark", "language": "zh"}),
        )
        user_repo.create_user(
            user_id="usr_bob",
            email="bob@example.com",
            password_hash=hash_password("Password123!"),
            display_name="Bob",
            role="viewer",
            preferences=json.dumps({"theme": "light"}),
        )

        # 插入 Alice 的数据
        raw_conn.execute(
            "INSERT INTO feedback (project_id, signal, score_before, score_after, notes, user_id) VALUES (?, ?, ?, ?, ?, ?)",
            ("p1", "positive", 80, 85, "Good", "usr_alice"),
        )
        raw_conn.execute(
            "INSERT INTO events (user_id, event_type, project_id, payload) VALUES (?, ?, ?, ?)",
            ("usr_alice", "click", "p1", json.dumps({"source": "search"})),
        )
        raw_conn.execute(
            "INSERT INTO watchlist (project_id, user_id, notes) VALUES (?, ?, ?)",
            ("p1", "usr_alice", "Follow up"),
        )
        raw_conn.execute(
            "INSERT INTO project_skips (project_id, user_id, reason) VALUES (?, ?, ?)",
            ("p2", "usr_alice", "Too risky"),
        )
        raw_conn.execute(
            "INSERT INTO interactions (id, project_id, user_id, interaction_type, status) VALUES (?, ?, ?, ?, ?)",
            ("int_1", "p1", "usr_alice", "testnet", "completed"),
        )
        raw_conn.execute(
            "INSERT INTO api_keys (id, user_id, name, key_hash, role) VALUES (?, ?, ?, ?, ?)",
            ("key_1", "usr_alice", "Dev Key", "hash_secret_key_123", "viewer"),
        )

        # 插入 Bob 的数据（确保不混入）
        raw_conn.execute(
            "INSERT INTO feedback (project_id, signal, score_before, score_after, notes, user_id) VALUES (?, ?, ?, ?, ?, ?)",
            ("p2", "negative", 70, 60, "Bad", "usr_bob"),
        )
        raw_conn.execute(
            "INSERT INTO events (user_id, event_type, project_id, payload) VALUES (?, ?, ?, ?)",
            ("usr_bob", "view", "p2", json.dumps({"source": "home"})),
        )
        raw_conn.commit()

    # 执行导出
    req = _make_dummy_request(user_id="usr_alice")
    resp = export_user_data(req)
    assert resp.ok is True
    data = resp.data

    # 验证 user 基本信息中不含 password_hash
    assert data.user["id"] == "usr_alice"
    assert data.user["email"] == "alice@example.com"
    assert "password_hash" not in data.user

    # 验证偏好
    assert data.preferences == {"theme": "dark", "language": "zh"}

    # 验证行为数据完整且仅包含 Alice
    assert len(data.feedback) == 1
    assert data.feedback[0]["project_id"] == "p1"

    assert len(data.events) == 1
    assert data.events[0]["event_type"] == "click"

    assert len(data.watchlist) == 1
    assert data.watchlist[0]["project_id"] == "p1"

    assert len(data.project_skips) == 1
    assert data.project_skips[0]["project_id"] == "p2"

    assert len(data.interactions) == 1
    assert data.interactions[0]["id"] == "int_1"

    # 验证 API Keys 不含 key_hash
    assert len(data.api_keys) == 1
    assert data.api_keys[0]["id"] == "key_1"
    assert "key_hash" not in data.api_keys[0]


def test_delete_user_account_deidentification_and_erasure(db_conn):
    """测试账户删除：feedback 去标识化保留样本、events 及私有数据硬删除、邮箱释放。"""
    with db_conn() as raw_conn:
        user_repo = UserRepository(raw_conn)
        user_repo.create_user(
            user_id="usr_alice",
            email="alice@example.com",
            password_hash=hash_password("Password123!"),
            display_name="Alice",
            role="viewer",
        )

        # 关联数据
        raw_conn.execute(
            "INSERT INTO feedback (project_id, signal, score_before, score_after, notes, user_id) VALUES (?, ?, ?, ?, ?, ?)",
            ("p1", "positive", 80, 85, "Good", "usr_alice"),
        )
        raw_conn.execute(
            "INSERT INTO events (user_id, event_type, project_id, payload) VALUES (?, ?, ?, ?)",
            ("usr_alice", "click", "p1", json.dumps({"source": "search"})),
        )
        raw_conn.execute(
            "INSERT INTO watchlist (project_id, user_id, notes) VALUES (?, ?, ?)",
            ("p1", "usr_alice", "Follow up"),
        )
        raw_conn.execute(
            "INSERT INTO project_skips (project_id, user_id, reason) VALUES (?, ?, ?)",
            ("p2", "usr_alice", "Too risky"),
        )
        raw_conn.execute(
            "INSERT INTO interactions (id, project_id, user_id, interaction_type, status) VALUES (?, ?, ?, ?, ?)",
            ("int_1", "p1", "usr_alice", "testnet", "completed"),
        )
        raw_conn.execute(
            "INSERT INTO api_keys (id, user_id, name, key_hash, role) VALUES (?, ?, ?, ?, ?)",
            ("key_1", "usr_alice", "Dev Key", "hash_secret_key_123", "viewer"),
        )
        raw_conn.execute(
            "INSERT INTO sessions (id, user_id, refresh_token_hash, expires_at) VALUES (?, ?, ?, datetime('now', '+7 days'))",
            ("sess_1", "usr_alice", "token_hash_123"),
        )
        raw_conn.commit()

    # 执行注销
    test_jti = "jti_alice_token_123"
    req = _make_dummy_request(user_id="usr_alice", jwt_jti=test_jti)
    resp = delete_user_account(req)

    assert resp.ok is True
    assert resp.data["status"] == "deleted"
    assert resp.data["deidentified_feedback_count"] == 1
    assert resp.data["deleted_events_count"] == 1

    with db_conn() as raw_conn:
        user_repo = UserRepository(raw_conn)

        # 1. 验证 feedback 未删除，但 user_id 被置为 NULL
        fb_row = raw_conn.execute("SELECT user_id, signal, project_id FROM feedback WHERE project_id = 'p1'").fetchone()
        assert fb_row is not None
        assert fb_row["user_id"] is None
        assert fb_row["signal"] == "positive"

        # 2. 验证 events 已被彻底物理删除
        events_count = raw_conn.execute("SELECT COUNT(*) FROM events WHERE user_id = 'usr_alice'").fetchone()[0]
        assert events_count == 0

        # 3. 验证 watchlist / skips / interactions / api_keys / sessions 均被清理
        assert raw_conn.execute("SELECT COUNT(*) FROM watchlist WHERE user_id = 'usr_alice'").fetchone()[0] == 0
        assert raw_conn.execute("SELECT COUNT(*) FROM project_skips WHERE user_id = 'usr_alice'").fetchone()[0] == 0
        assert raw_conn.execute("SELECT COUNT(*) FROM interactions WHERE user_id = 'usr_alice'").fetchone()[0] == 0
        assert raw_conn.execute("SELECT COUNT(*) FROM api_keys WHERE user_id = 'usr_alice'").fetchone()[0] == 0
        assert raw_conn.execute("SELECT COUNT(*) FROM sessions WHERE user_id = 'usr_alice'").fetchone()[0] == 0

        # 4. 验证 users 记录已删除
        assert user_repo.get_by_id("usr_alice") is None

        # 5. 验证 JTI 被吊销
        assert is_jti_blacklisted(test_jti) is True

        # 6. 验证同一邮箱可以重新注册新用户
        re_registered = user_repo.create_user(
            user_id="usr_alice_new",
            email="alice@example.com",
            password_hash=hash_password("NewPassword123!"),
            display_name="Alice Reborn",
        )
        assert re_registered["id"] == "usr_alice_new"
        assert re_registered["email"] == "alice@example.com"
