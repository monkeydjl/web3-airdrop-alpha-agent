"""Unit tests for API Key repository and verification logic (W12-09)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.auth import hash_password, verify_password
from app.db import get_connection
from app.repositories.api_key import ApiKeyRepository
from app.repositories.user import UserRepository


@pytest.fixture(autouse=True)
def clean_db():
    with get_connection() as conn:
        conn.execute("DELETE FROM api_keys")
        conn.execute("DELETE FROM users")
        conn.commit()
    yield
    with get_connection() as conn:
        conn.execute("DELETE FROM api_keys")
        conn.execute("DELETE FROM users")
        conn.commit()


def test_api_key_bcrypt_verification():
    """验证 API Key 原始值与 bcrypt 哈希验证的一致性。"""
    raw_key = "ak_1234567890abcdef_secret_high_entropy_token_sample"
    key_hash = hash_password(raw_key)

    assert key_hash.startswith("$2b$")
    assert verify_password(raw_key, key_hash) is True
    assert verify_password(raw_key + "_wrong", key_hash) is False


def test_api_key_repo_crud_and_fast_lookup():
    """验证 ApiKeyRepository CRUD 操作与 O(1) 快速检索。"""
    key_id_hex = "1234567890abcdef"
    key_id = f"key_{key_id_hex}"
    raw_key = f"ak_{key_id_hex}_super_secure_random_bytes_abc"
    key_hash = hash_password(raw_key)

    with get_connection() as conn:
        user_repo = UserRepository(conn)
        user_repo.create_user(
            user_id="usr_alice",
            email="alice@test.com",
            password_hash="mock_hash",
            role="analyst",
        )

        repo = ApiKeyRepository(conn)

        # 1. 创建 Key
        record = repo.create_key(
            key_id=key_id,
            user_id="usr_alice",
            name="Alice Key 1",
            key_hash=key_hash,
            role="analyst",
        )
        assert record["id"] == key_id
        assert record["name"] == "Alice Key 1"
        assert record["role"] == "analyst"
        assert record["is_revoked"] == 0

        # 2. O(1) 快速查找
        found = repo.find_active_key_by_raw(raw_key)
        assert found is not None
        assert found["id"] == key_id
        assert found["user_id"] == "usr_alice"

        # 3. 错误密钥查找返回 None
        assert repo.find_active_key_by_raw(raw_key + "tampered") is None

        # 4. 列表查询
        alice_keys = repo.list_by_user("usr_alice")
        assert len(alice_keys) == 1
        assert alice_keys[0]["id"] == key_id

        # 5. 更新最后使用时间
        now = datetime.now(UTC)
        repo.update_last_used(key_id, now)
        updated = repo.get_by_id(key_id)
        assert updated is not None
        assert updated["last_used_at"] is not None

        # 6. 撤销 Key
        revoked = repo.revoke_key(key_id, user_id="usr_alice")
        assert revoked is True

        # 撤销后再查返回 None
        assert repo.find_active_key_by_raw(raw_key) is None
        assert len(repo.list_by_user("usr_alice", include_revoked=False)) == 0
        assert len(repo.list_by_user("usr_alice", include_revoked=True)) == 1


def test_api_key_expiration():
    """验证已过期的 API Key 不可通过验证。"""
    key_id_hex = "fedcba0987654321"
    key_id = f"key_{key_id_hex}"
    raw_key = f"ak_{key_id_hex}_super_secure_random_bytes_def"
    key_hash = hash_password(raw_key)

    # 创建一个已过期的 Key（昨日到期）
    yesterday = datetime.now(UTC) - timedelta(days=1)

    with get_connection() as conn:
        user_repo = UserRepository(conn)
        user_repo.create_user(
            user_id="usr_bob",
            email="bob@test.com",
            password_hash="mock_hash",
            role="viewer",
        )

        repo = ApiKeyRepository(conn)
        repo.create_key(
            key_id=key_id,
            user_id="usr_bob",
            name="Expired Key",
            key_hash=key_hash,
            role="viewer",
            expires_at=yesterday,
        )

        found = repo.find_active_key_by_raw(raw_key)
        assert found is None
