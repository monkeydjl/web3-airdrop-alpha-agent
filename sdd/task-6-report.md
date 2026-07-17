# Task 6 Final Finding Report

## RED

Command:

`python -m pytest tests/opportunity/test_calibration_report.py -k project_equal_decision_median_uses_project_label_means -q`

Result: `1 failed, 16 deselected in 4.93s`; expected project-equal median `7.0`, received `None`.

## GREEN

Focused report command:

`python -m pytest tests/opportunity/test_calibration_report.py -q`

Result: `17 passed in 13.38s`.

All calibration tests:

`python -m pytest tests/opportunity -k calibration -q`

Result: `191 passed, 610 deselected in 14.34s`.

Ruff commands:

`python -m ruff check app/opportunity/calibration tests/opportunity/test_calibration_outcomes.py tests/opportunity/test_calibration_loader.py tests/opportunity/test_calibration_metrics.py tests/opportunity/test_calibration_economics.py tests/opportunity/test_calibration_decisions.py tests/opportunity/test_calibration_advice.py tests/opportunity/test_calibration_report.py`

Result: `All checks passed!`

`python -m ruff format --check app/opportunity/calibration tests/opportunity/test_calibration_outcomes.py tests/opportunity/test_calibration_loader.py tests/opportunity/test_calibration_metrics.py tests/opportunity/test_calibration_economics.py tests/opportunity/test_calibration_decisions.py tests/opportunity/test_calibration_advice.py tests/opportunity/test_calibration_report.py`

Result: `14 files already formatted`.
