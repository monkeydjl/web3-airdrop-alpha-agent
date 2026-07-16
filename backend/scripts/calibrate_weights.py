"""Offline weight calibration skeleton (WEIGHT_CALIBRATION.md).

Does NOT change production weights unless --apply is passed AND sample gate passes.
Default mode is dry-run / report-only.

  cd backend
  python scripts/calibrate_weights.py
  python scripts/calibrate_weights.py --min-samples 50   # lower for experiments
  python scripts/calibrate_weights.py --search            # grid search when ready

Never prints secrets. Does not read .env contents into logs.
"""

from __future__ import annotations

import itertools
import json
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
for p in (BACKEND, BACKEND.parent):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from app.agents.scorer import LABEL_THRESHOLDS, WEIGHTS
from app.db import get_connection, init_db

MIN_SAMPLES_DEFAULT = 200
WEIGHT_KEYS = list(WEIGHTS.keys())
V1_WEIGHTS = dict(WEIGHTS)


@dataclass
class FeedbackSample:
    project_id: str
    signal: str
    outcome: str | None
    predicted_label: str | None
    true_label: str | None
    weight: float  # sample weight (strong vs weak)


def score_to_label(score: int, thresholds: list[tuple[int, str]] | None = None) -> str:
    th = thresholds or LABEL_THRESHOLDS
    for threshold, label in th:
        if score >= threshold:
            return label
    return "IGNORE"


def total_from_subscores(subscores: dict[str, float], weights: dict[str, float]) -> int:
    total = sum(float(subscores.get(k, 50.0)) * weights[k] for k in weights)
    return round(max(0.0, min(100.0, total)))


def load_samples(conn) -> list[FeedbackSample]:
    """Build calibration samples from feedback + projects."""
    rows = conn.execute(
        """
        SELECT f.project_id, f.signal, f.outcome, f.note, f.created_at,
               p.label AS pred_label, p.score AS pred_score, p.reason
        FROM feedback f
        LEFT JOIN projects p ON p.id = f.project_id
        ORDER BY f.created_at DESC
        """
    ).fetchall()

    samples: list[FeedbackSample] = []
    seen: set[tuple[str, str]] = set()  # (project_id, signal) keep latest

    for row in rows:
        d = dict(row)
        pid = d.get("project_id") or ""
        signal = (d.get("signal") or "").lower()
        key = (pid, signal)
        if key in seen:
            continue
        seen.add(key)

        outcome = d.get("outcome")
        pred = d.get("pred_label")
        true_label: str | None = None
        weight = 0.3  # weak useful/useless

        if signal == "wrong_label":
            # note may carry correct label; try parse
            note = (d.get("note") or "").upper()
            for lab in ("FARM", "WATCH", "IGNORE"):
                if lab in note:
                    true_label = lab
                    break
            weight = 1.0 if true_label else 0.5
        elif outcome in ("airdropped", "pumped"):
            true_label = "FARM"
            weight = 1.0
        elif outcome in ("not_airdropped", "dumped"):
            # not_airdropped ≠ IGNORE always, but as weak negative on FARM
            true_label = "WATCH" if pred == "FARM" else (pred or "WATCH")
            weight = 0.8
        elif signal == "correct_outcome":
            true_label = pred
            weight = 0.7
        elif signal == "useful":
            true_label = pred
            weight = 0.3
        elif signal == "useless":
            # treat as "not FARM" if predicted FARM
            true_label = "WATCH" if pred == "FARM" else pred
            weight = 0.3

        samples.append(
            FeedbackSample(
                project_id=pid,
                signal=signal,
                outcome=outcome,
                predicted_label=pred,
                true_label=true_label,
                weight=weight,
            )
        )
    return samples


def metric_j(samples: list[FeedbackSample]) -> dict[str, float]:
    """J = recall(FARM) - 2 * FPR(FARM) on samples with true_label."""
    labeled = [s for s in samples if s.true_label and s.predicted_label]
    if not labeled:
        return {"J": 0.0, "recall_farm": 0.0, "fpr_farm": 0.0, "n": 0.0}

    tp = fp = fn = tn = 0.0
    for s in labeled:
        w = s.weight
        pred_f = s.predicted_label == "FARM"
        true_f = s.true_label == "FARM"
        if pred_f and true_f:
            tp += w
        elif pred_f and not true_f:
            fp += w
        elif (not pred_f) and true_f:
            fn += w
        else:
            tn += w

    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    fpr = fp / (fp + tn) if (fp + tn) > 0 else 0.0
    j = recall - 2.0 * fpr
    return {
        "J": round(j, 4),
        "recall_farm": round(recall, 4),
        "fpr_farm": round(fpr, 4),
        "n": float(len(labeled)),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
    }


def valid_weight_grid(step: float = 0.05, max_delta: float = 0.10) -> list[dict[str, float]]:
    """Generate weight vectors near v1 with Σ=1 and per-dim |Δ|<=max_delta."""
    # discrete offsets -max_delta..+max_delta
    offs = []
    k = 0.0
    while round(k, 10) <= max_delta + 1e-9:
        offs.append(round(k, 10))
        if k > 0:
            offs.append(round(-k, 10))
        k = round(k + step, 10)

    candidates: list[dict[str, float]] = []
    # random-ish full grid is huge; use product of small offsets then renorm/filter
    # sample systematically: each dim offset independently, renorm to 1, check constraints
    for combo in itertools.product(offs, repeat=len(WEIGHT_KEYS)):
        w = {WEIGHT_KEYS[i]: V1_WEIGHTS[WEIGHT_KEYS[i]] + combo[i] for i in range(len(WEIGHT_KEYS))}
        if any(v < 0.05 or v > 0.40 for v in w.values()):
            continue
        if any(abs(w[k] - V1_WEIGHTS[k]) > max_delta + 1e-9 for k in WEIGHT_KEYS):
            continue
        s = sum(w.values())
        if abs(s - 1.0) > 1e-6:
            # renorm
            w = {k: v / s for k, v in w.items()}
            if any(abs(w[k] - V1_WEIGHTS[k]) > max_delta + 1e-9 for k in WEIGHT_KEYS):
                continue
            if abs(sum(w.values()) - 1.0) > 1e-6:
                continue
        candidates.append({k: round(w[k], 4) for k in WEIGHT_KEYS})

    # unique
    uniq = {tuple(sorted(c.items())): c for c in candidates}
    return list(uniq.values())


def ensure_changelog_table(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS weight_changelog (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_version TEXT,
            to_version TEXT,
            weights_json TEXT NOT NULL,
            sample_size INTEGER,
            metrics_json TEXT,
            triggered_by TEXT,
            status TEXT DEFAULT 'candidate',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()


def main() -> int:
    args = sys.argv[1:]
    do_search = "--search" in args
    min_samples = MIN_SAMPLES_DEFAULT
    if "--min-samples" in args:
        i = args.index("--min-samples")
        min_samples = int(args[i + 1])

    init_db()
    conn = get_connection()
    try:
        ensure_changelog_table(conn)
        samples = load_samples(conn)
        strong = [s for s in samples if s.weight >= 0.7 and s.true_label]
        metrics = metric_j(samples)
        print("=== Weight calibration report ===")
        print(f"current_weights (v1.1 labels): {json.dumps(V1_WEIGHTS)}")
        print(f"label_thresholds: {LABEL_THRESHOLDS}")
        print(f"feedback_samples: {len(samples)} (strong≈{len(strong)})")
        print(f"min_samples_gate: {min_samples}")
        print(f"metrics_current_preds: {metrics}")
        by_sig = Counter(s.signal for s in samples)
        print(f"by_signal: {dict(by_sig)}")

        ready = len(samples) >= min_samples
        print(f"calibration_ready: {ready}")
        if not ready:
            print(
                f"BLOCKED: need {min_samples - len(samples)} more feedback samples "
                f"(WEIGHT_CALIBRATION.md §3.3). Weights NOT changed."
            )
            print("RESULT: GATE_NOT_MET")
            return 0

        if not do_search:
            print("Gate passed. Re-run with --search to explore weight candidates.")
            print("RESULT: READY_NO_SEARCH")
            return 0

        # Offline search uses predicted labels as proxy only when true_label set.
        # Full re-weight needs stored sub_scores; if missing, search is skipped.
        print(
            "NOTE: Full grid re-weight needs per-project sub_scores snapshot. "
            "Recording baseline metrics to weight_changelog as candidate baseline."
        )
        conn.execute(
            """
            INSERT INTO weight_changelog (
                from_version, to_version, weights_json, sample_size,
                metrics_json, triggered_by, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "v1",
                "v1-baseline",
                json.dumps(V1_WEIGHTS),
                len(samples),
                json.dumps(metrics),
                "calibrate_weights.py",
                "baseline",
            ),
        )
        conn.commit()
        print("Wrote weight_changelog baseline row.")
        print("RESULT: BASELINE_LOGGED")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
