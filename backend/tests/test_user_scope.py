"""用户归属过滤口径测试。

背景：两张表写 user_id 的方式不一致（实测确认）——
`POST /interactions` 不传 user_id 时落 NULL，`POST /watchlist/{id}` 落 'default'。
user_scope 把这个差异收敛到一处，本文件锁死其语义。
"""

import pytest

from app.services.user_scope import (
    DEFAULT_USER,
    owned_project_ids,
    owned_project_ids_where,
)


@pytest.fixture
def conn(tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "db_path", str(tmp_path / "scope.db"))
    from app.db import get_connection, init_db

    init_db()
    with get_connection() as c:
        yield c


def _seed_interactions(c, rows: list[tuple[str, str | None]]) -> None:
    for pid, uid in rows:
        c.execute(
            "INSERT INTO interactions (project_id, user_id, status) VALUES (?, ?, 'active')",
            (pid, uid),
        )
    c.commit()


class TestDefaultUserIncludesNull:
    def test_null_user_rows_belong_to_default_user(self, conn):
        """关键：interactions 写 NULL，默认用户必须能读到。

        若严格用 user_id = 'default'，用户刚标记「已做」的项目读不出来，
        今日行动会把它反复推给用户。
        """
        _seed_interactions(conn, [("p-null", None), ("p-default", DEFAULT_USER)])
        got = owned_project_ids(conn, "interactions", DEFAULT_USER)
        assert got == {"p-null", "p-default"}

    def test_watchlist_default_rows_are_found(self, conn):
        conn.execute("INSERT INTO watchlist (project_id, user_id) VALUES ('p-w', ?)", (DEFAULT_USER,))
        conn.commit()
        assert owned_project_ids(conn, "watchlist", DEFAULT_USER) == {"p-w"}


class TestNamedUserIsIsolated:
    def test_named_user_does_not_see_null_or_other_users(self, conn):
        """多用户启用后的边界：具名用户不得读到 NULL 或他人记录。"""
        _seed_interactions(
            conn,
            [("p-null", None), ("p-alice", "alice"), ("p-bob", "bob")],
        )
        assert owned_project_ids(conn, "interactions", "alice") == {"p-alice"}
        assert owned_project_ids(conn, "interactions", "bob") == {"p-bob"}

    def test_default_user_query_does_not_leak_named_users(self, conn):
        _seed_interactions(conn, [("p-null", None), ("p-alice", "alice")])
        assert owned_project_ids(conn, "interactions", DEFAULT_USER) == {"p-null"}


class TestExtraCondition:
    def test_extra_condition_is_applied(self, conn):
        conn.execute(
            "INSERT INTO feedback (project_id, user_id, signal, outcome) VALUES ('p-done', NULL, 'correct_outcome', 'airdropped')"
        )
        conn.execute("INSERT INTO feedback (project_id, user_id, signal) VALUES ('p-open', NULL, 'useful')")
        conn.commit()

        marked = owned_project_ids_where(conn, "feedback", DEFAULT_USER, "outcome IS NOT NULL")
        assert marked == {"p-done"}

        all_rows = owned_project_ids(conn, "feedback", DEFAULT_USER)
        assert all_rows == {"p-done", "p-open"}

    def test_extra_condition_still_respects_user_isolation(self, conn):
        conn.execute(
            "INSERT INTO feedback (project_id, user_id, signal, outcome) VALUES ('p-a', 'alice', 'correct_outcome', 'airdropped')"
        )
        conn.execute(
            "INSERT INTO feedback (project_id, user_id, signal, outcome) VALUES ('p-b', 'bob', 'correct_outcome', 'dumped')"
        )
        conn.commit()
        assert owned_project_ids_where(conn, "feedback", "alice", "outcome IS NOT NULL") == {"p-a"}


class TestTableWhitelist:
    def test_unknown_table_is_rejected(self, conn):
        """表名会拼进 SQL，必须限定取值。"""
        with pytest.raises(ValueError, match="unsupported table"):
            owned_project_ids(conn, "projects", DEFAULT_USER)
        with pytest.raises(ValueError, match="unsupported table"):
            owned_project_ids(conn, "interactions; DROP TABLE projects", DEFAULT_USER)

    def test_empty_table_returns_empty_set(self, conn):
        assert owned_project_ids(conn, "interactions", DEFAULT_USER) == set()
