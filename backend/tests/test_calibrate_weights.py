"""Unit tests for calibration helpers."""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.agents.scorer import LABEL_THRESHOLDS  # noqa: E402
from app.calibration import (  # noqa: E402
    CalibrationSample,
    compute_j,
    recompute_score,
)


def _score_to_label(score: int) -> str:
    """Map a 0-100 score to its label using the v1.1 thresholds."""
    for threshold, label in LABEL_THRESHOLDS:
        if score >= threshold:
            return label
    return "IGNORE"


def test_score_to_label_v11():
    assert _score_to_label(70) == "FARM"
    assert _score_to_label(65) == "FARM"
    assert _score_to_label(64) == "WATCH"
    assert _score_to_label(50) == "WATCH"
    assert _score_to_label(49) == "IGNORE"


def test_total_from_subscores_v1_weights():
    subs = {
        "airdrop_signal": 100,
        "narrative_timing": 100,
        "team_reputation": 100,
        "risk": 100,
        "tokenomics": 100,
        "competition": 100,
    }
    weights = {
        "airdrop_signal": 0.2,
        "narrative_timing": 0.2,
        "team_reputation": 0.15,
        "risk": 0.15,
        "tokenomics": 0.15,
        "competition": 0.15,
    }
    assert recompute_score(subs, weights) == 100


def test_metric_j_perfect_farm():
    farm_subs = {k: 100.0 for k in (
        "airdrop_signal", "narrative_timing", "team_reputation",
        "risk", "tokenomics", "competition",
    )}
    ignore_subs = {k: 0.0 for k in (
        "airdrop_signal", "narrative_timing", "team_reputation",
        "risk", "tokenomics", "competition",
    )}
    weights = {
        "airdrop_signal": 0.2,
        "narrative_timing": 0.2,
        "team_reputation": 0.15,
        "risk": 0.15,
        "tokenomics": 0.15,
        "competition": 0.15,
    }
    samples = [
        CalibrationSample(
            project_id="a",
            subscores=farm_subs,
            true_label="FARM",
            current_label="FARM",
            signal="wrong_label",
            outcome=None,
        ),
        CalibrationSample(
            project_id="b",
            subscores=ignore_subs,
            true_label="WATCH",
            current_label="WATCH",
            signal="wrong_label",
            outcome=None,
        ),
    ]
    m = compute_j(samples, weights)
    assert m["recall_farm"] == 1.0
    assert m["fpr_farm"] == 0.0
    assert m["j"] == 1.0
