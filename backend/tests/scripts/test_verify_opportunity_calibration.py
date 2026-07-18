from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from uuid import uuid4

import pytest

SCRIPT = Path(__file__).parents[2] / "scripts" / "verify_opportunity_calibration.py"
SPEC = importlib.util.spec_from_file_location("verify_opportunity_calibration", SCRIPT)
assert SPEC and SPEC.loader
verifier = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verifier)


def _configure_database(tmp_path, monkeypatch):
    database = tmp_path / "calibration.sqlite3"
    monkeypatch.setattr(verifier.settings, "database_url", None)
    monkeypatch.setattr(verifier.settings, "db_path", str(database))
    verifier.init_db()
    return database


def _insert_sentinels():
    conn = verifier.get_connection()
    assessment_id = f"preexisting-assessment-sentinel-{uuid4()}"
    interaction_note = "preexisting-interaction-sentinel"
    assessment = verifier._assessment(assessment_id, verifier.PROJECT_ID_PREFIX + "1", verifier.AS_OF)
    conn.execute(
        """INSERT INTO opportunity_assessments
           (assessment_id, project_id, model_version, profile_version, assessment_json,
            decision_status, public_label, overall_confidence, scored_at, expires_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            assessment_id,
            verifier.PROJECT_ID_PREFIX + "1",
            "unrelated-model",
            "unrelated-profile",
            json.dumps(assessment),
            "ACTIONABLE",
            "FARM",
            0.8,
            verifier.AS_OF.isoformat(),
            (verifier.AS_OF + verifier.timedelta(days=30)).isoformat(),
        ),
    )
    cursor = conn.execute(
        "INSERT INTO interactions (project_id, note) VALUES (?, ?)",
        (verifier.PROJECT_ID_PREFIX + "1", interaction_note),
    )
    interaction_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return assessment_id, interaction_id, interaction_note


def _assert_sentinels_survive(assessment_id, interaction_id, interaction_note):
    conn = verifier.get_connection()
    try:
        assessment = conn.execute(
            "SELECT assessment_id FROM opportunity_assessments WHERE assessment_id = ?", (assessment_id,)
        ).fetchone()
        interaction = conn.execute("SELECT note FROM interactions WHERE id = ?", (interaction_id,)).fetchone()
        assert assessment["assessment_id"] == assessment_id
        assert interaction["note"] == interaction_note
    finally:
        conn.close()


def _insert_preexisting_duplicate_pair():
    conn = verifier.get_connection()
    assessment_id = f"preexisting-supported-assessment-{uuid4()}"
    project_id = f"preexisting-supported-project-{uuid4()}"
    cohort_id = f"cohort-{uuid4()}"
    assessment = verifier._assessment(assessment_id, project_id, verifier.AS_OF - verifier.timedelta(days=200))
    conn.execute(
        """INSERT INTO opportunity_assessments
           (assessment_id, project_id, model_version, profile_version, assessment_json,
            decision_status, public_label, overall_confidence, scored_at, expires_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            assessment_id,
            project_id,
            verifier.MODEL_VERSION,
            verifier.PROFILE_VERSION,
            json.dumps(assessment),
            "ACTIONABLE",
            "FARM",
            0.8,
            assessment["scored_at"],
            assessment["expires_at"],
        ),
    )
    for outcome in ("airdropped", "not_airdropped"):
        conn.execute(
            """INSERT INTO interactions
               (project_id, wallet_cohort_id, wallet_count, opportunity_assessment_id,
                opportunity_model_version, opportunity_profile_version, outcome_observed_at, outcome)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                project_id,
                cohort_id,
                1,
                assessment_id,
                verifier.MODEL_VERSION,
                verifier.PROFILE_VERSION,
                verifier.AS_OF.isoformat(),
                outcome,
            ),
        )
    conn.commit()
    conn.close()
    return assessment_id, project_id, cohort_id


def test_network_free_fixture_report_is_stable_and_safe(tmp_path, monkeypatch):
    _configure_database(tmp_path, monkeypatch)

    summary = verifier.run_verification(verifier.AS_OF)

    assert summary == verifier.EXPECTED_SUMMARY


def test_fixture_quality_is_measured_as_an_exact_delta_from_production_baseline(tmp_path, monkeypatch):
    _configure_database(tmp_path, monkeypatch)
    identifiers = _insert_preexisting_duplicate_pair()

    assert verifier.run_verification(verifier.AS_OF) == verifier.EXPECTED_SUMMARY

    conn = verifier.get_connection()
    try:
        assert (
            conn.execute(
                "SELECT COUNT(*) AS count FROM opportunity_assessments WHERE assessment_id = ?", (identifiers[0],)
            ).fetchone()["count"]
            == 1
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) AS count FROM interactions WHERE project_id = ? AND wallet_cohort_id = ?",
                identifiers[1:],
            ).fetchone()["count"]
            == 2
        )
    finally:
        conn.close()


def test_fixture_transaction_preserves_preexisting_rows_on_success(tmp_path, monkeypatch):
    _configure_database(tmp_path, monkeypatch)
    sentinel = _insert_sentinels()

    assert verifier.run_verification(verifier.AS_OF) == verifier.EXPECTED_SUMMARY

    _assert_sentinels_survive(*sentinel)


def test_preexisting_legacy_fixed_fixture_id_does_not_collide(tmp_path, monkeypatch):
    _configure_database(tmp_path, monkeypatch)
    conn = verifier.get_connection()
    assessment = verifier._assessment(verifier.ASSESSMENT_IDS[0], verifier.PROJECT_IDS[0], verifier.AS_OF)
    conn.execute(
        """INSERT INTO opportunity_assessments
           (assessment_id, project_id, model_version, profile_version, assessment_json,
            decision_status, public_label, overall_confidence, scored_at, expires_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            verifier.ASSESSMENT_IDS[0],
            verifier.PROJECT_IDS[0],
            "unrelated-model",
            "unrelated-profile",
            json.dumps(assessment),
            "ACTIONABLE",
            "FARM",
            0.8,
            verifier.AS_OF.isoformat(),
            (verifier.AS_OF + verifier.timedelta(days=30)).isoformat(),
        ),
    )
    conn.commit()
    conn.close()

    assert verifier.run_verification(verifier.AS_OF) == verifier.EXPECTED_SUMMARY

    conn = verifier.get_connection()
    try:
        assert (
            conn.execute(
                "SELECT assessment_id FROM opportunity_assessments WHERE assessment_id = ?",
                (verifier.ASSESSMENT_IDS[0],),
            ).fetchone()["assessment_id"]
            == verifier.ASSESSMENT_IDS[0]
        )
    finally:
        conn.close()


def test_fixture_transaction_preserves_preexisting_rows_on_failure(tmp_path, monkeypatch):
    _configure_database(tmp_path, monkeypatch)
    sentinel = _insert_sentinels()

    def fail_report(*_args, **_kwargs):
        raise RuntimeError("forced report failure")

    monkeypatch.setattr(verifier, "build_calibration_report", fail_report)
    with pytest.raises(RuntimeError, match="forced report failure"):
        verifier.run_verification(verifier.AS_OF)

    _assert_sentinels_survive(*sentinel)


def test_injected_writing_loader_is_rejected_and_rolled_back(tmp_path, monkeypatch):
    _configure_database(tmp_path, monkeypatch)
    sentinel = _insert_sentinels()

    def writing_loader(conn, **_kwargs):
        conn.execute("DELETE FROM interactions")

    with pytest.raises(verifier.NonReadOnlyStatementError):
        verifier.run_verification(verifier.AS_OF, loader=writing_loader)

    _assert_sentinels_survive(*sentinel)


def test_recording_connection_rejects_empty_sql():
    class Connection:
        kind = "sqlite"

        def execute(self, _sql, _params=None):
            raise AssertionError("empty SQL reached the wrapped connection")

    recording = verifier._RecordingConnection(Connection())

    with pytest.raises(verifier.NonReadOnlyStatementError):
        recording.execute(" ; ")
    assert recording.statements == []


def test_cli_is_sorted_bounded_and_has_pass_marker(tmp_path, monkeypatch, capsys):
    _configure_database(tmp_path, monkeypatch)

    assert verifier.main(["--as-of", "2026-10-15T00:00:00Z"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[-1] == "RESULT: PASS"
    assert lines[:-1] == sorted(lines[:-1])
    assert all(len(line) <= verifier.MAX_OUTPUT_LINE for line in lines)
    assert not any("project-" in line or "assessment-" in line for line in lines)


@pytest.mark.parametrize(
    "failed_key",
    ("json_stable", "markdown_stable", "privacy_safe", "production_select_only"),
)
def test_cli_fails_when_any_required_boolean_is_false(monkeypatch, capsys, failed_key):
    summary = dict(verifier.EXPECTED_SUMMARY)
    summary[failed_key] = False
    monkeypatch.setattr(verifier, "run_verification", lambda _as_of: summary)

    assert verifier.main([]) == 1
    assert capsys.readouterr().out.splitlines() == ["failure_type=VerificationMismatch", "RESULT: FAIL"]


@pytest.mark.parametrize("count_key", ("window_90d_samples", "window_180d_samples"))
def test_cli_fails_when_an_expected_count_differs(monkeypatch, capsys, count_key):
    summary = dict(verifier.EXPECTED_SUMMARY)
    summary[count_key] += 1
    monkeypatch.setattr(verifier, "run_verification", lambda _as_of: summary)

    assert verifier.main([]) == 1
    assert capsys.readouterr().out.splitlines() == ["failure_type=VerificationMismatch", "RESULT: FAIL"]


@pytest.mark.parametrize(
    ("metadata_key", "wrong_value"),
    (
        ("schema", "wrong-schema"),
        ("model_version", "wrong-model"),
        ("profile_version", "wrong-profile"),
        ("as_of", "2026-10-14T00:00:00Z"),
        ("windows", [90]),
        ("bootstrap_seed", 1),
        ("bootstrap_replicates", 999),
    ),
)
def test_verifier_rejects_report_metadata_mismatch(tmp_path, monkeypatch, metadata_key, wrong_value):
    _configure_database(tmp_path, monkeypatch)
    original = verifier.build_calibration_report

    def mismatched_report(*args, **kwargs):
        report = original(*args, **kwargs)
        report["metadata"][metadata_key] = wrong_value
        return report

    monkeypatch.setattr(verifier, "build_calibration_report", mismatched_report)

    with pytest.raises(AssertionError):
        verifier.run_verification(verifier.AS_OF)


def test_cli_failure_reveals_only_exception_type(monkeypatch, capsys):
    def fail(_as_of):
        raise RuntimeError("secret project id and database URL")

    monkeypatch.setattr(verifier, "run_verification", fail)
    assert verifier.main(["--as-of", "2026-10-15T00:00:00Z"]) == 1
    assert capsys.readouterr().out.splitlines() == ["failure_type=RuntimeError", "RESULT: FAIL"]


def test_cli_failure_type_is_bounded(monkeypatch, capsys):
    long_exception = type("X" * 500, (RuntimeError,), {})

    def fail(_as_of):
        raise long_exception("private failure details")

    monkeypatch.setattr(verifier, "run_verification", fail)
    assert verifier.main([]) == 1
    lines = capsys.readouterr().out.splitlines()
    assert lines[-1] == "RESULT: FAIL"
    assert all(len(line) <= verifier.MAX_OUTPUT_LINE for line in lines)


@pytest.mark.parametrize("argv", (["--as-of"], ["--as-of", "private-raw-as-of-value"]))
def test_argparse_failures_are_bounded_and_do_not_echo_input(argv, capsys):
    assert verifier.main(argv) == 1
    captured = capsys.readouterr()
    lines = captured.out.splitlines()
    assert captured.err == ""
    assert lines == ["failure_type=ArgumentError", "RESULT: FAIL"]
    assert "private-raw-as-of-value" not in captured.out
    assert all(len(line) <= verifier.MAX_OUTPUT_LINE for line in lines)
