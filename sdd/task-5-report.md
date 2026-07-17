# Task 5 Review Fix Report

## RED

Command:

`python -m pytest tests/opportunity/test_calibration_advice.py -q`

Result: `29 failed, 26 passed in 4.31s`.

The failures demonstrated that segment generation did not use the canonical scope syntax, caller-provided gates were trusted, arbitrary dimensions entered targets/explanations, and unknown or privacy-sensitive scopes produced advice.

## GREEN

Focused command:

`python -m pytest tests/opportunity/test_calibration_advice.py -q`

Result: `55 passed in 3.55s`.

Full Task 1-5 calibration command:

`python -m pytest tests/opportunity/test_calibration_outcomes.py tests/opportunity/test_calibration_loader.py tests/opportunity/test_calibration_metrics.py tests/opportunity/test_calibration_economics.py tests/opportunity/test_calibration_decisions.py tests/opportunity/test_calibration_advice.py -q`

Result: `174 passed in 4.23s`.

Ruff commands:

`python -m ruff check app/opportunity/calibration tests/opportunity/test_calibration_outcomes.py tests/opportunity/test_calibration_loader.py tests/opportunity/test_calibration_metrics.py tests/opportunity/test_calibration_economics.py tests/opportunity/test_calibration_decisions.py tests/opportunity/test_calibration_advice.py`

Result: `All checks passed!`

`python -m ruff format --check app/opportunity/calibration tests/opportunity/test_calibration_outcomes.py tests/opportunity/test_calibration_loader.py tests/opportunity/test_calibration_metrics.py tests/opportunity/test_calibration_economics.py tests/opportunity/test_calibration_decisions.py tests/opportunity/test_calibration_advice.py`

Result: `12 files already formatted`.
