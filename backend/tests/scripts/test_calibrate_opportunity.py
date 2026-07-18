from __future__ import annotations

from datetime import UTC

import pytest

from app.config import settings
from scripts import calibrate_opportunity
from scripts.calibrate_opportunity import main, parse_as_of


@pytest.mark.parametrize("value", ["2026-10-15T00:00:00", "not-a-timestamp"])
def test_parse_as_of_rejects_invalid_or_naive_values(value):
    with pytest.raises(ValueError):
        parse_as_of(value)


def test_parse_as_of_normalizes_z_and_offsets_to_utc():
    assert parse_as_of("2026-10-15T00:00:00Z").tzinfo is UTC
    assert parse_as_of("2026-10-15T08:00:00+08:00").isoformat() == "2026-10-15T00:00:00+00:00"


def test_main_requires_as_of(capsys, tmp_path):
    assert main(["--output-dir", str(tmp_path)]) != 0
    assert "--as-of" in capsys.readouterr().err


def test_main_rejects_output_file(capsys, tmp_path):
    output = tmp_path / "not-a-directory"
    output.write_text("file", encoding="utf-8")
    assert main(["--as-of", "2026-10-15T00:00:00Z", "--output-dir", str(output)]) != 0
    assert "not a directory" in capsys.readouterr().err


def test_main_restores_database_url_after_failure(monkeypatch, capsys, tmp_path):
    original = settings.database_url
    supplied = "sqlite:///private-do-not-print.db"
    monkeypatch.setattr(settings, "database_url", original)
    def fail_connection():
        raise RuntimeError(f"cannot connect to {supplied}")

    monkeypatch.setattr(calibrate_opportunity, "get_connection", fail_connection)
    assert main(
        [
            "--as-of",
            "2026-10-15T00:00:00Z",
            "--output-dir",
            str(tmp_path),
            "--database-url",
            supplied,
        ]
    ) != 0
    captured = capsys.readouterr()
    assert settings.database_url == original
    assert supplied not in captured.out + captured.err
    assert "Traceback" not in captured.out + captured.err


def test_main_publishes_stable_json_markdown_pair(monkeypatch, capsys, tmp_path):
    database = tmp_path / "calibration.db"
    output = tmp_path / "reports"
    monkeypatch.setattr(settings, "database_url", None)
    monkeypatch.setattr(settings, "db_path", str(database))
    arguments = ["--as-of", "2026-10-15T00:00:00Z", "--output-dir", str(output)]

    assert main(arguments) == 0
    first_bytes = {path.name: path.read_bytes() for path in output.iterdir()}
    captured = capsys.readouterr().out
    assert len(first_bytes) == 2
    assert all(name.endswith((".json", ".md")) for name in first_bytes)
    assert "report" in captured.lower()
    assert "gate" in captured.lower()
    assert "mature samples" in captured.lower()
    assert "calibration.db" not in captured

    assert main(arguments) == 0
    second_bytes = {path.name: path.read_bytes() for path in output.iterdir()}
    assert first_bytes == second_bytes
