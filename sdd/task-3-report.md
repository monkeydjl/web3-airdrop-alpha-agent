# Task 3 Recovery Report

Date: 2026-07-18
Worktree: `.worktrees/opportunity-outcome-calibration`
Branch: `feat/opportunity-outcome-calibration`
Starting HEAD: `61769bb8b78b005b332010ed5f49f983626bec51`

## Recovered State

The worktree initially contained exactly one modified file:

```text
 M backend/tests/opportunity/test_calibration_metrics.py
```

The inherited change was inspected with:

```text
git status --short --branch
git diff -- backend/tests/opportunity/test_calibration_metrics.py
git show HEAD:backend/tests/opportunity/test_calibration_metrics.py
```

It was preserved and used as the test-first specification. The committed Task 3 file at `HEAD` contained 9 test functions / 9 collected cases. Before this recovery run, the prior agent had:

- Updated 5 existing `probability_metrics` tests to pass an explicit `coverage_denominator`.
- Added coverage field assertions to the hand-calculated and empty-data tests.
- Corrected the expected project-equal bias sign.
- Added 5 new test functions / 10 collected cases: bias direction (1), same-bin project-equal reliability/ECE (1), zero-denominator coverage (1), invalid coverage denominators (2), and invalid binary predictions (5).

Therefore the preserved file collected 19 cases total: 9 cases committed before recovery and 10 inherited uncommitted cases that pre-existed this run.

No production file had uncommitted changes at recovery start.

## RED Evidence

Before any production change, the preserved test file was run from `backend`:

```text
python -m pytest tests/opportunity/test_calibration_metrics.py --no-cov -q
```

Exact result:

```text
10 failed, 9 passed in 0.60s
```

All 10 failures raised:

```text
TypeError: probability_metrics() got an unexpected keyword argument 'coverage_denominator'
```

This established RED for the incomplete required coverage contract. The 9 passing cases included all 5 invalid-prediction parameter cases, confirming that `BinaryObservation` finite/range validation already existed in production before this run. The existing implementation also showed the bias formula was reversed as `mean_prediction - observed_rate`.

## Production Changes

`backend/app/opportunity/calibration/metrics.py` now:

- Requires the keyword-only `coverage_denominator` argument.
- Reports `coverage_count` as the eligible observation count.
- Reports the supplied `coverage_denominator`.
- Reports `coverage_count / coverage_denominator` as `coverage`.
- Reports null coverage when the denominator is zero.
- Rejects a negative denominator.
- Rejects a denominator below the eligible observation count.
- Defines bias as `observed_rate - mean_prediction`.

The existing project-equal sample weights continue through reliability-bin means and ECE. The inherited same-bin regression verifies that projects, rather than rows, contribute equally.

Caller inventory with `probability_metrics\(` found no production callers beyond the function definition. All test callers were updated by the inherited test change to satisfy the now-required contract.

## GREEN Evidence

Focused Task 3 test after the production change:

```text
python -m pytest tests/opportunity/test_calibration_metrics.py --no-cov -q
19 passed in 0.30s
```

Complete Task 1-3 tests:

```text
python -m pytest tests/opportunity/test_calibration_outcomes.py tests/opportunity/test_calibration_loader.py tests/opportunity/test_calibration_metrics.py --no-cov -q
87 passed in 0.67s
```

Ruff check:

```text
python -m ruff check app/opportunity/calibration tests/opportunity/test_calibration_outcomes.py tests/opportunity/test_calibration_loader.py tests/opportunity/test_calibration_metrics.py
All checks passed!
```

Ruff format check:

```text
python -m ruff format --check app/opportunity/calibration tests/opportunity/test_calibration_outcomes.py tests/opportunity/test_calibration_loader.py tests/opportunity/test_calibration_metrics.py
8 files already formatted
```
