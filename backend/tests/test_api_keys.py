"""Unit tests for API Key repository and verification logic (W12-09)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.auth import hash_password, verify_password
from app.db import get_connection
from app.repositories.api_key import ApiKeyRepository
from app.repositories.user import UserRepository

# 显式建库：此文件的用例直连 DB_PATH 但自身不 init_db()，过去依赖
# conftest pytest_configure 的会话级兜底（主仓库 data/test.db 的历史残留
# schema）侥幸通过；全新 checkout / CI runner 上单跑必红（no such table）。
# 现改为模块内显式 autouse fixture 幂等建库，消除对兜底的隐式依赖。


@pytest.fixture(autouse=True)
def _ensure_db_schema():
    """显式幂等建库（不删库、不清数据）；详见文件头注释。"""
    from app.db import init_db

    init_db()


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


# ── bcrypt 扫描放大 DoS 回归（2026-11-13 审查）──────────────────
#
# find_active_key_by_raw 的 ak_ 快速路径未命中时（key_id 不存在 /
# 已吊销 / 密文不匹配），此前会**继续落进全表扫描**：每个请求对全部
# 未撤销 key 逐行 bcrypt（约 N×250ms 纯 CPU）。攻击者只要发一个格式
# 合法但不存在的 `ak_{16hex}_{x}`，就能以限流内的请求量持续吃满 CPU。
#
# 契约：`ak_` 格式解析成功后，快速路径就是**权威判定** —— 该 raw key
# 的哈希只可能存在于它声称的那一行，扫描不可能"救回"任何结果。
# 全表扫描只保留给历史格式（非 ak_ 前缀）的兼容查找。


def _seed_user_and_keys(n: int) -> list[str]:
    """建 1 个用户 + n 个有效 key，返回 n 个 raw key。"""
    from app.db import get_connection
    from app.repositories.api_key import ApiKeyRepository
    from app.repositories.user import UserRepository

    raws: list[str] = []
    with get_connection() as conn:
        UserRepository(conn).create_user(
            user_id="usr_dos",
            email="dos@test.com",
            password_hash="mock_hash",
            role="analyst",
        )
        repo = ApiKeyRepository(conn)
        for i in range(n):
            key_id_hex = f"{i:016x}"
            raw_key = f"ak_{key_id_hex}_super_secure_secret_{i}"
            repo.create_key(
                key_id=f"key_{key_id_hex}",
                user_id="usr_dos",
                name=f"k{i}",
                key_hash=hash_password(raw_key),
                role="analyst",
            )
            raws.append(raw_key)
    return raws


def _count_bcrypt_calls(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    """替换 api_key 命名空间里的 verify_password，统计 bcrypt 调用次数。"""
    import app.repositories.api_key as ak_mod

    counter = {"n": 0}
    real_verify = ak_mod.verify_password

    def counting_verify(raw: str, hashed: str) -> bool:
        counter["n"] += 1
        return real_verify(raw, hashed)

    monkeypatch.setattr(ak_mod, "verify_password", counting_verify)
    return counter


def test_unknown_key_id_does_not_trigger_bcrypt_scan(monkeypatch):
    """格式合法但 key_id 不存在 → 立即 None，0 次 bcrypt。"""
    _seed_user_and_keys(3)
    counter = _count_bcrypt_calls(monkeypatch)
    from app.db import get_connection
    from app.repositories.api_key import ApiKeyRepository

    with get_connection() as conn:
        result = ApiKeyRepository(conn).find_active_key_by_raw("ak_ffffffffffffffff_unknown")
    assert result is None
    assert counter["n"] == 0, f"key_id 未命中仍发生了 {counter['n']} 次 bcrypt —— 全表扫描放大 DoS 未修复"


def test_revoked_key_does_not_trigger_bcrypt_scan(monkeypatch):
    """key_id 命中但已吊销 → 立即 None，0 次 bcrypt（不扫其他行）。"""
    raws = _seed_user_and_keys(3)
    from app.db import get_connection
    from app.repositories.api_key import ApiKeyRepository

    with get_connection() as conn:
        ApiKeyRepository(conn).revoke_key("key_0000000000000000", user_id="usr_dos")

    counter = _count_bcrypt_calls(monkeypatch)
    with get_connection() as conn:
        result = ApiKeyRepository(conn).find_active_key_by_raw(raws[0])
    assert result is None
    assert counter["n"] == 0, f"已吊销 key 仍触发了 {counter['n']} 次 bcrypt 扫描"


def test_wrong_secret_verifies_only_against_claimed_row(monkeypatch):
    """key_id 命中但密文不匹配 → 恰好 1 次 bcrypt（对声称的那行），不是 1+N。"""
    raws = _seed_user_and_keys(3)
    from app.db import get_connection
    from app.repositories.api_key import ApiKeyRepository

    forged = raws[0].replace("_super_secure_secret_0", "_forged_secret_0")
    counter = _count_bcrypt_calls(monkeypatch)
    with get_connection() as conn:
        result = ApiKeyRepository(conn).find_active_key_by_raw(forged)
    assert result is None
    assert counter["n"] == 1, f"密文不匹配触发了 {counter['n']} 次 bcrypt（应为 1）"


def test_legacy_format_still_falls_back_to_scan():
    """非 ak_ 前缀的历史格式 key 仍走全表扫描兼容路径（能被找到）。"""
    _seed_user_and_keys(2)
    legacy_raw = "legacy_plain_token_2024"
    from app.auth import hash_password as _hp
    from app.db import get_connection
    from app.repositories.api_key import ApiKeyRepository

    with get_connection() as conn:
        ApiKeyRepository(conn).create_key(
            key_id="key_legacy00000000",
            user_id="usr_dos",
            name="legacy",
            key_hash=_hp(legacy_raw),
            role="analyst",
        )
        found = ApiKeyRepository(conn).find_active_key_by_raw(legacy_raw)
    assert found is not None
    assert found["id"] == "key_legacy00000000"
