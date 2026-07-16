"""Unit tests for calibrate_weights helpers."""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from scripts.calibrate_weights import (  # noqa: E402
    FeedbackSample,
    metric_j,
    score_to_label,
    total_from_subscores,
)


def test_score_to_label_v11():
    assert score_to_label(70) == "FARM"
    assert score_to_label(65) == "FARM"
    assert score_to_label(64) == "WATCH"
    assert score_to_label(50) == "WATCH"
    assert score_to_label(49) == "IGNORE"


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
    assert total_from_subscores(subs, weights) == 100


def test_metric_j_perfect_farm():
    samples = [
        FeedbackSample("a", "wrong_label", None, "FARM", "FARM", 1.0),
        FeedbackSample("b", "wrong_label", None, "WATCH", "WATCH", 1.0),
    ]
    m = metric_j(samples)
    assert m["recall_farm"] == 1.0
    assert m["fpr_farm"] == 0.0
    assert m["J"] == 1.0
