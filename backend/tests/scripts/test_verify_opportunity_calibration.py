from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).parents[2] / "scripts" / "verify_opportunity_calibration.py"
SPEC = importlib.util.spec_from_file_location("verify_opportunity_calibration", SCRIPT)
assert SPEC and SPEC.loader
verifier = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verifier)


def test_network_free_fixture_report_is_stable_and_safe(tmp_path, monkeypatch):
    database = tmp_path / "calibration.sqlite3"
    monkeypatch.setattr(verifier.settings, "database_url", f"sqlite:///{database}")

    summary = verifier.run_verification(verifier.AS_OF)

    assert summary == {
        "backend": "sqlite",
        "json_stable": True,
        "markdown_stable": True,
        "privacy_safe": True,
        "production_select_only": True,
        "window_90d_samples": 3,
        "window_180d_samples": 3,
    }


def test_cli_is_sorted_bounded_and_has_pass_marker(tmp_path, monkeypatch, capsys):
    database = tmp_path / "calibration.sqlite3"
    monkeypatch.setattr(verifier.settings, "database_url", f"sqlite:///{database}")

    assert verifier.main(["--as-of", "2026-10-15T00:00:00Z"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[-1] == "RESULT: PASS"
    assert lines[:-1] == sorted(lines[:-1])
    assert all(len(line) <= verifier.MAX_OUTPUT_LINE for line in lines)
    assert not any("project-" in line or "assessment-" in line for line in lines)


def test_cli_failure_reveals_only_exception_type(monkeypatch, capsys):
    def fail(_as_of):
        raise RuntimeError("secret project id and database URL")

    monkeypatch.setattr(verifier, "run_verification", fail)
    assert verifier.main(["--as-of", "2026-10-15T00:00:00Z"]) == 1
    assert capsys.readouterr().out.splitlines() == ["failure_type=RuntimeError", "RESULT: FAIL"]
