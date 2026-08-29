"""Tests for weight calibration engine (C2, §7.9).

Covers:
- Sample extraction from feedback + projects
- Gate check (≥ 200 samples, ≥ 30 FARM)
- Objective function J = recall(FARM) - 2*FPR(FARM)
- Grid search: finds better weights, Σ=1.0 invariant, constraint ≤ 0.10
- Changelog recording (status='candidate')
- Full run_calibration flow (gate not met → no search)
- Format report output

Reference:
- V2_TASKS.md C2
- WEIGHT_CALIBRATION.md §3-§7
- ADR-006 权重校准
"""

from __future__ import annotations

import json
import sqlite3

import pytest

import app.calibration as cal_module
from app.calibration import (
    WEIGHT_KEYS,
    CalibrationSample,
    check_gate,
    compute_j,
    extract_samples,
    format_report,
    grid_search,
    recompute_label,
    recompute_score,
    record_candidate,
    run_calibration,
)
from app.db import init_db

# ── Fixtures ────────────────────────────────────


def _make_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


def _insert_project(conn, project_id, sub_scores, label="WATCH", score=55):
    conn.execute(
        """
        INSERT INTO projects (id, name, url, sector, stage, score, label,
                              confidence, weight_version, sub_scores, source)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            project_id,
            project_id.replace("-", " "),
            f"https://{project_id}.example.com",
            "DeFi",
            "testnet",
            score,
            label,
            0.8,
            "v1.2",
            json.dumps(sub_scores) if sub_scores else None,
            "test",
        ),
    )


def _insert_feedback(conn, project_id, signal, outcome=None, note=None, user_id="tester"):
    conn.execute(
        """
        INSERT INTO feedback (project_id, user_id, signal, outcome, note)
        VALUES (?, ?, ?, ?, ?)
        """,
        (project_id, user_id, signal, outcome, note),
    )


def _make_subscores(**overrides):
    """Create subscores dict with all 8 dimensions, default 50 each."""
    base = {k: 50.0 for k in WEIGHT_KEYS}
    base.update(overrides)
    return base


@pytest.fixture
def conn():
    c = _make_conn()
    try:
        yield c
    finally:
        c.close()


# ── Sample extraction tests ────────────────────


def test_extract_samples_wrong_label(conn):
    """wrong_label feedback with correct_label in note → sample extracted."""
    subscores = _make_subscores()
    _insert_project(conn, "proj-1", subscores, label="WATCH")
    _insert_feedback(conn, "proj-1", signal="wrong_label", note="should be FARM")

    samples = extract_samples(conn)
    assert len(samples) == 1
    assert samples[0].true_label == "FARM"
    assert samples[0].project_id == "proj-1"


def test_extract_samples_outcome(conn):
    """outcome feedback → sample extracted with mapped label."""
    subscores = _make_subscores()
    _insert_project(conn, "proj-2", subscores, label="IGNORE")
    _insert_feedback(conn, "proj-2", signal="correct_outcome", outcome="airdropped")

    samples = extract_samples(conn)
    assert len(samples) == 1
    assert samples[0].true_label == "FARM"
    assert samples[0].outcome == "airdropped"


def test_extract_samples_dedup(conn):
    """Multiple feedback for same project → only latest kept."""
    subscores = _make_subscores()
    _insert_project(conn, "proj-3", subscores)
    _insert_feedback(conn, "proj-3", signal="useless", outcome="dumped")
    _insert_feedback(conn, "proj-3", signal="wrong_label", note="should be WATCH")

    samples = extract_samples(conn)
    assert len(samples) == 1
    # Latest (wrong_label) is kept, note says WATCH
    assert samples[0].true_label == "WATCH"


def test_extract_samples_skips_missing_subscores(conn):
    """Project without sub_scores JSON → skipped."""
    _insert_project(conn, "proj-4", {}, label="WATCH")
    _insert_feedback(conn, "proj-4", signal="wrong_label", note="FARM")

    samples = extract_samples(conn)
    assert len(samples) == 0


def test_extract_samples_skips_no_supervision(conn):
    """Feedback with only 'useful' signal and no outcome → skipped."""
    subscores = _make_subscores()
    _insert_project(conn, "proj-5", subscores)
    _insert_feedback(conn, "proj-5", signal="useful")

    samples = extract_samples(conn)
    assert len(samples) == 0


# ── Gate check tests ───────────────────────────


def test_gate_fails_below_min_samples():
    """< 200 samples → gate not met."""
    samples = [
        CalibrationSample(
            project_id=f"p-{i}",
            subscores=_make_subscores(),
            true_label="FARM" if i < 10 else "IGNORE",
            current_label="WATCH",
            signal="wrong_label",
            outcome=None,
        )
        for i in range(50)
    ]
    gate = check_gate(samples)
    assert not gate.passed
    assert "GATE_NOT_MET" in gate.reason
    assert "200" in gate.reason


def test_gate_fails_below_farm_samples():
    """≥ 200 samples but < 30 FARM → gate not met."""
    samples = [
        CalibrationSample(
            project_id=f"p-{i}",
            subscores=_make_subscores(),
            true_label="FARM" if i < 10 else "IGNORE",
            current_label="WATCH",
            signal="wrong_label",
            outcome=None,
        )
        for i in range(250)
    ]
    gate = check_gate(samples)
    assert not gate.passed
    assert "FARM" in gate.reason
    assert "30" in gate.reason


def test_gate_passes_with_enough_samples():
    """≥ 200 samples and ≥ 30 FARM → gate met."""
    samples = [
        CalibrationSample(
            project_id=f"p-{i}",
            subscores=_make_subscores(),
            true_label="FARM" if i < 50 else "IGNORE",
            current_label="WATCH",
            signal="wrong_label",
            outcome=None,
        )
        for i in range(200)
    ]
    gate = check_gate(samples)
    assert gate.passed
    assert "GATE_MET" in gate.reason


def test_gate_constants_not_lowered():
    """门槛常量必须钉在协议值（WEIGHT_CALIBRATION.md §3.3）。

    这是防"调低门槛让校准更快达标"的护栏：把 200 → 50 或 30 → 5
    会直接红掉这条测试。协议说「未达标禁止切换默认 weight_version」，
    门槛是协议的一部分，不随样本稀缺而下调。
    """
    assert cal_module.MIN_VALID_SAMPLES == 200
    assert cal_module.MIN_FARM_SAMPLES == 30


# ── Objective function tests ────────────────────


def test_compute_j_perfect_classifier():
    """Perfect FARM classifier → J = 1.0 (recall=1, fpr=0)."""
    samples = [
        CalibrationSample(
            project_id=f"p-{i}",
            subscores=_make_subscores(airdrop_signal=90 if i < 10 else 10),
            true_label="FARM" if i < 10 else "IGNORE",
            current_label="FARM",
            signal="wrong_label",
            outcome=None,
        )
        for i in range(20)
    ]
    # Use weights that perfectly separate
    weights = {k: 0.0 for k in WEIGHT_KEYS}
    weights["airdrop_signal"] = 1.0

    metrics = compute_j(samples, weights)
    assert metrics["j"] == 1.0
    assert metrics["recall_farm"] == 1.0
    assert metrics["fpr_farm"] == 0.0
    assert metrics["tp"] == 10
    assert metrics["fp"] == 0


def test_compute_j_all_wrong():
    """All predictions wrong → J = -2 (recall=0, fpr=1)."""
    samples = [
        CalibrationSample(
            project_id=f"p-{i}",
            subscores=_make_subscores(airdrop_signal=90),
            true_label="IGNORE",  # All are actually IGNORE
            current_label="FARM",
            signal="wrong_label",
            outcome=None,
        )
        for i in range(20)
    ]
    weights = {k: 0.0 for k in WEIGHT_KEYS}
    weights["airdrop_signal"] = 1.0

    metrics = compute_j(samples, weights)
    assert metrics["recall_farm"] == 0.0
    assert metrics["fpr_farm"] == 1.0
    assert metrics["j"] == -2.0


def test_recompute_score_uses_weights():
    """recompute_score correctly applies given weights."""
    subscores = _make_subscores(airdrop_signal=100, narrative_timing=0)
    weights = {k: 0.0 for k in WEIGHT_KEYS}
    weights["airdrop_signal"] = 1.0

    score = recompute_score(subscores, weights)
    assert score == 100


def test_recompute_label_thresholds():
    """recompute_label respects FARM/WATCH/IGNORE thresholds."""
    subscores = _make_subscores(airdrop_signal=70)
    weights = {k: 0.0 for k in WEIGHT_KEYS}
    weights["airdrop_signal"] = 1.0

    assert recompute_label(subscores, weights) == "FARM"

    subscores_low = _make_subscores(airdrop_signal=55)
    assert recompute_label(subscores_low, weights) == "WATCH"

    subscores_very_low = _make_subscores(airdrop_signal=30)
    assert recompute_label(subscores_very_low, weights) == "IGNORE"


# ── Grid search tests ───────────────────────────


def test_grid_search_finds_better_weights():
    """Grid search finds weights that improve J over baseline."""
    # Create samples where airdrop_signal is highly predictive
    samples = [
        CalibrationSample(
            project_id=f"p-{i}",
            subscores=_make_subscores(
                airdrop_signal=80 if i < 50 else 20,
                narrative_timing=50,
            ),
            true_label="FARM" if i < 50 else "IGNORE",
            current_label="WATCH",
            signal="wrong_label",
            outcome=None,
        )
        for i in range(200)
    ]

    # Baseline weights (uniform, not optimized)
    current = {k: 0.125 for k in WEIGHT_KEYS}
    baseline_j = compute_j(samples, current)["j"]

    best_weights, best_j, _ = grid_search(samples, current, n_random=500)

    assert best_j >= baseline_j
    # Σ=1.0 invariant
    assert abs(sum(best_weights.values()) - 1.0) < 0.01


def test_grid_search_respects_constraint():
    """No dimension changes more than 0.10 from baseline."""
    samples = [
        CalibrationSample(
            project_id=f"p-{i}",
            subscores=_make_subscores(),
            true_label="FARM" if i < 50 else "IGNORE",
            current_label="WATCH",
            signal="wrong_label",
            outcome=None,
        )
        for i in range(200)
    ]

    current = {k: 0.125 for k in WEIGHT_KEYS}
    best_weights, _, _ = grid_search(samples, current, n_random=500)

    for k in WEIGHT_KEYS:
        assert abs(best_weights[k] - current[k]) <= 0.10 + 1e-6, (
            f"{k} changed by {abs(best_weights[k] - current[k]):.4f}, max allowed 0.10"
        )


def test_grid_search_sum_is_one():
    """Best weights always sum to 1.0."""
    samples = [
        CalibrationSample(
            project_id=f"p-{i}",
            subscores=_make_subscores(),
            true_label="FARM" if i < 50 else "IGNORE",
            current_label="WATCH",
            signal="wrong_label",
            outcome=None,
        )
        for i in range(200)
    ]

    current = {
        "airdrop_signal": 0.18,
        "narrative_timing": 0.15,
        "team_reputation": 0.12,
        "risk": 0.12,
        "tokenomics": 0.10,
        "competition": 0.10,
        "execution": 0.13,
        "transparency": 0.10,
    }

    best_weights, _, _ = grid_search(samples, current, n_random=200)

    total = sum(best_weights.values())
    assert abs(total - 1.0) < 0.01, f"Σ={total}, expected 1.0"


# ── Changelog recording tests ───────────────────


def test_record_candidate_inserts_row(conn):
    """record_candidate inserts a row with status='candidate'."""
    weights = {k: 0.125 for k in WEIGHT_KEYS}
    metrics = {"j": 0.75, "recall_farm": 0.8, "fpr_farm": 0.025}

    changelog_id = record_candidate(
        conn,
        from_version="v1.2",
        to_version="v1.3",
        weights=weights,
        sample_size=250,
        metrics=metrics,
        triggered_by="human",
    )

    assert changelog_id > 0

    row = conn.execute(
        "SELECT * FROM weight_changelog WHERE id = ?",
        (changelog_id,),
    ).fetchone()

    assert row is not None
    assert row["from_version"] == "v1.2"
    assert row["to_version"] == "v1.3"
    assert row["sample_size"] == 250
    assert row["triggered_by"] == "human"
    assert row["status"] == "candidate"

    stored_weights = json.loads(row["weights_json"])
    assert stored_weights == weights

    stored_metrics = json.loads(row["metrics_json"])
    assert stored_metrics["j"] == 0.75


def test_record_candidate_default_status(conn):
    """New candidate always gets status='candidate'."""
    weights = {k: 0.125 for k in WEIGHT_KEYS}
    changelog_id = record_candidate(
        conn,
        from_version="v1.2",
        to_version="v1.3",
        weights=weights,
        sample_size=200,
        metrics={"j": 0.5},
    )

    row = conn.execute(
        "SELECT status FROM weight_changelog WHERE id = ?",
        (changelog_id,),
    ).fetchone()

    assert row["status"] == "candidate"


# ── Full run_calibration flow tests ─────────────


def test_run_calibration_gate_not_met_no_search(conn):
    """When gate not met, no search performed, no changelog written."""
    # Insert only a few samples
    for i in range(10):
        _insert_project(conn, f"proj-{i}", _make_subscores())
        _insert_feedback(conn, f"proj-{i}", signal="wrong_label", note="FARM")

    report = run_calibration(conn, search=True)

    assert not report.gate.passed
    assert report.best_weights is None
    assert report.changelog_id is None

    # No changelog written
    count = conn.execute("SELECT COUNT(*) FROM weight_changelog").fetchone()[0]
    assert count == 0


def test_run_calibration_gate_met_no_search_flag(conn):
    """When gate met but search=False, no search performed."""
    for i in range(200):
        _insert_project(conn, f"proj-{i}", _make_subscores())
        _insert_feedback(
            conn,
            f"proj-{i}",
            signal="wrong_label",
            note="FARM" if i < 50 else "IGNORE",
        )

    report = run_calibration(conn, search=False)

    assert report.gate.passed
    assert report.best_weights is None
    assert report.changelog_id is None


def test_run_calibration_gate_met_with_search(conn):
    """When gate met and search=True, search runs and candidate recorded."""
    for i in range(200):
        subscores = _make_subscores(airdrop_signal=80 if i < 50 else 20)
        _insert_project(conn, f"proj-{i}", subscores)
        _insert_feedback(
            conn,
            f"proj-{i}",
            signal="wrong_label",
            note="FARM" if i < 50 else "IGNORE",
        )

    report = run_calibration(conn, search=True)

    assert report.gate.passed
    assert report.best_weights is not None
    assert report.changelog_id is not None

    # Changelog written
    row = conn.execute(
        "SELECT * FROM weight_changelog WHERE id = ?",
        (report.changelog_id,),
    ).fetchone()
    assert row is not None
    assert row["status"] == "candidate"

    # Σ=1.0 invariant on best weights
    assert abs(sum(report.best_weights.values()) - 1.0) < 0.01


def test_run_calibration_improvement_non_negative(conn):
    """Best J is >= baseline J (search never makes things worse)."""
    for i in range(200):
        subscores = _make_subscores(airdrop_signal=80 if i < 50 else 20)
        _insert_project(conn, f"proj-{i}", subscores)
        _insert_feedback(
            conn,
            f"proj-{i}",
            signal="wrong_label",
            note="FARM" if i < 50 else "IGNORE",
        )

    report = run_calibration(conn, search=True)

    assert report.best_j >= report.baseline_j - 1e-9


# ── Format report tests ─────────────────────────


def test_format_report_gate_not_met():
    """Report contains GATE_NOT_MET when gate fails."""
    from app.calibration import GateResult

    report = cal_module.CalibrationReport(
        gate=GateResult(
            passed=False,
            reason="GATE_NOT_MET: 有效样本 50 < 200",
            total_samples=50,
            strong_samples=50,
            farm_samples=10,
        ),
        baseline_j=0.5,
        best_j=0.5,
        best_weights=None,
        current_weights={k: 0.125 for k in WEIGHT_KEYS},
        improvement=0.0,
    )

    text = format_report(report)
    assert "GATE_NOT_MET" in text
    assert "未执行搜索" in text


def test_format_report_with_candidate():
    """Report contains candidate weights and metrics when search ran."""
    from app.calibration import GateResult

    weights = {
        "airdrop_signal": 0.20,
        "narrative_timing": 0.15,
        "team_reputation": 0.12,
        "risk": 0.12,
        "tokenomics": 0.10,
        "competition": 0.10,
        "execution": 0.13,
        "transparency": 0.08,
    }
    report = cal_module.CalibrationReport(
        gate=GateResult(
            passed=True,
            reason="GATE_MET: 250 samples (50 FARM)",
            total_samples=250,
            strong_samples=250,
            farm_samples=50,
        ),
        baseline_j=0.65,
        best_j=0.78,
        best_weights=weights,
        current_weights={k: 0.125 for k in WEIGHT_KEYS},
        improvement=0.13,
        changelog_id=42,
        metrics={
            "j": 0.78,
            "recall_farm": 0.85,
            "fpr_farm": 0.035,
            "tp": 42,
            "fp": 5,
            "fn": 8,
            "tn": 195,
            "precision_farm": 0.89,
        },
    )

    text = format_report(report)
    assert "GATE_MET" in text
    assert "Candidate Weights" in text or "候选权重" in text
    assert "0.78" in text
    assert "0.13" in text
    assert "candidate" in text
    assert "42" in text  # changelog id
