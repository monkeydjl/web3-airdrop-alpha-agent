import pytest

from app.config import settings
from app.db import DbConnection
from scripts import verify_opportunity_shadow


class _DictCountCursor:
    def __init__(self, cursor):
        self._cursor = cursor

    def fetchone(self):
        return {"assessment_count": self._cursor.fetchone()[0]}


class _DictCountConnection(DbConnection):
    def __init__(self, connection):
        self._connection = connection
        super().__init__(connection._raw, kind=connection.kind)

    def execute(self, query, parameters=()):
        cursor = self._connection.execute(query, parameters)
        if query.lstrip().upper().startswith("SELECT COUNT(*)"):
            return _DictCountCursor(cursor)
        return cursor

    def __getattr__(self, name):
        return getattr(self._connection, name)


@pytest.mark.parametrize("dict_count_row", [False, True])
def test_verify_shadow_smoke_creates_two_snapshots_without_changing_legacy(tmp_path, monkeypatch, dict_count_row):
    monkeypatch.setattr(settings, "database_url", None)
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "shadow.db"))
    if dict_count_row:
        get_connection = verify_opportunity_shadow.get_connection
        monkeypatch.setattr(
            verify_opportunity_shadow,
            "get_connection",
            lambda: _DictCountConnection(get_connection()),
        )

    result = verify_opportunity_shadow.run_verification()

    assert result == {
        "assessment_count": 2,
        "db_backend": "sqlite",
        "legacy_label_unchanged": True,
        "legacy_score_unchanged": True,
        "model_version": "opportunity-v2.0",
        "second_snapshot_complete": True,
        "sparse_label": "WATCH",
        "sparse_status": "INSUFFICIENT_EVIDENCE",
    }
