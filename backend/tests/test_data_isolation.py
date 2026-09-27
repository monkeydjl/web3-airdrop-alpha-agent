"""Unit tests for row-level data isolation logic (W12-10)."""

from app.services.user_scope import (
    _ALLOWED_TABLES,
    DEFAULT_USER,
    build_user_scope_filter,
)


class TestUserScopeFilterBuilder:
    def test_admin_without_filter_returns_empty(self) -> None:
        clause, params = build_user_scope_filter(user_id="admin", role="admin")
        assert clause == ""
        assert params == []

    def test_admin_with_filter_returns_equality(self) -> None:
        clause, params = build_user_scope_filter(
            user_id="admin",
            role="admin",
            admin_filter_user_id="usr_alice",
        )
        assert clause == "user_id = ?"
        assert params == ["usr_alice"]

    def test_default_user_includes_null(self) -> None:
        clause, params = build_user_scope_filter(user_id=DEFAULT_USER, role="viewer")
        # 1b4b76f 起 default/anonymous 查询额外纳入 default 用户的记录：
        # (user_id = 当前身份 OR user_id = 'default' OR user_id IS NULL)。
        assert clause == "(user_id = ? OR user_id = ? OR user_id IS NULL)"
        assert params == [DEFAULT_USER, DEFAULT_USER]

    def test_anonymous_user_includes_null(self) -> None:
        clause, params = build_user_scope_filter(user_id="anonymous", role="anonymous")
        assert clause == "(user_id = ? OR user_id = ? OR user_id IS NULL)"
        assert params == ["anonymous", DEFAULT_USER]

    def test_named_user_strictly_isolated(self) -> None:
        clause, params = build_user_scope_filter(user_id="usr_alice", role="analyst")
        assert clause == "user_id = ?"
        assert params == ["usr_alice"]

    def test_custom_column_name(self) -> None:
        clause, params = build_user_scope_filter(
            user_id="usr_alice",
            role="analyst",
            col_name="f.user_id",
        )
        assert clause == "f.user_id = ?"
        assert params == ["usr_alice"]


class TestAllowedTables:
    def test_events_and_skips_in_allowed_tables(self) -> None:
        assert "events" in _ALLOWED_TABLES
        assert "feedback" in _ALLOWED_TABLES
        assert "watchlist" in _ALLOWED_TABLES
        assert "interactions" in _ALLOWED_TABLES
        assert "project_skips" in _ALLOWED_TABLES
