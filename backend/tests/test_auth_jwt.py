from __future__ import annotations

from app.auth import (
    blacklist_token_jti,
    decode_and_verify_jwt,
    hash_password,
    hash_refresh_token,
    is_jti_blacklisted,
    issue_access_token,
    issue_anonymous_token,
    issue_refresh_token,
    validate_password_strength,
    verify_password,
    verify_token,
)


def test_password_hashing_and_verification() -> None:
    """验证 bcrypt 密码哈希与匹配。"""
    raw = "StrongPassword123"
    hashed = hash_password(raw)

    assert hashed != raw
    assert hashed.startswith("$2b$12$")  # bcrypt cost factor 12
    assert verify_password(raw, hashed) is True
    assert verify_password("WrongPassword123", hashed) is False
    assert verify_password("", hashed) is False


def test_password_strength_validation() -> None:
    """验证密码复杂度规则（长度≥8，含大小写字母与数字）。"""
    # 合法密码
    ok, err = validate_password_strength("Pass1234")
    assert ok is True
    assert err == ""

    # 过短
    ok, err = validate_password_strength("P1a")
    assert ok is False
    assert "至少为 8" in err

    # 缺少大写字母
    ok, err = validate_password_strength("password123")
    assert ok is False
    assert "大写字母" in err

    # 缺少小写字母
    ok, err = validate_password_strength("PASSWORD123")
    assert ok is False
    assert "小写字母" in err

    # 缺少数字
    ok, err = validate_password_strength("PasswordOnly")
    assert ok is False
    assert "数字" in err


def test_jwt_access_token_lifecycle() -> None:
    """验证 JWT Access Token 签发与解析。"""
    user_id = "usr_test123"
    role = "analyst"

    token, jti, expires_in = issue_access_token(user_id, role, expires_minutes=15)
    assert token
    assert jti
    assert expires_in == 900

    payload = decode_and_verify_jwt(token, expected_type="access")
    assert payload is not None
    assert payload["sub"] == user_id
    assert payload["role"] == role
    assert payload["jti"] == jti
    assert payload["type"] == "access"

    # 期望 refresh 类型时解析应失败
    assert decode_and_verify_jwt(token, expected_type="refresh") is None


def test_jwt_refresh_token_lifecycle() -> None:
    """验证 JWT Refresh Token 签发与解析。"""
    user_id = "usr_test456"

    token, jti, expires_in = issue_refresh_token(user_id, expires_days=7)
    assert token
    assert jti
    assert expires_in == 7 * 86400

    payload = decode_and_verify_jwt(token, expected_type="refresh")
    assert payload is not None
    assert payload["sub"] == user_id
    assert payload["jti"] == jti
    assert payload["type"] == "refresh"

    # 验证 hash_refresh_token
    token_hash = hash_refresh_token(token)
    assert len(token_hash) == 64  # sha256 hex


def test_jwt_revocation_blacklist() -> None:
    """验证 JTI 吊销黑名单机制。"""
    user_id = "usr_revoked"
    token, jti, _ = issue_access_token(user_id, "viewer")

    # 未吊销前校验成功
    assert decode_and_verify_jwt(token) is not None
    assert is_jti_blacklisted(jti) is False

    # 吊销 JTI
    blacklist_token_jti(jti)

    # 吊销后校验失败
    assert is_jti_blacklisted(jti) is True
    assert decode_and_verify_jwt(token) is None


def test_jwt_expiration() -> None:
    """验证已过期的 JWT 无法通过校验。"""
    user_id = "usr_expired"
    # 签发立即过期的 token（负时间或 0）
    token, _, _ = issue_access_token(user_id, "viewer", expires_minutes=-1)

    assert decode_and_verify_jwt(token) is None


def test_anonymous_token_backward_compatibility() -> None:
    """验证既有 V2 HMAC 匿名 token 保持 100% 兼容。"""
    anon_token = issue_anonymous_token(user_id="anon-custom", ttl_hours=24)
    assert anon_token.count(".") == 1  # 2 parts HMAC

    payload = verify_token(anon_token)
    assert payload is not None
    assert payload["user_id"] == "anon-custom"
    assert payload["role"] == "anonymous"
