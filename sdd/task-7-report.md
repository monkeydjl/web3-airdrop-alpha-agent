# Task 7 Final Finding Report

## RED

Focused regression command before the fix:

`python -m pytest tests/scripts/test_calibrate_opportunity.py -q`

Result: `4 failed, 7 passed`; argparse emitted 204–503 character usage/raw-argument output, output-directory validation returned operational code 1, and a `connection.close()` exception prevented restoration of `settings.database_url`.

## GREEN

Focused calibration CLI tests:

`python -m pytest tests/scripts/test_calibrate_opportunity.py -q`

Result: `11 passed in 5.40s`.

All calibration tests:

`python -m pytest tests/opportunity -k calibration -q`

Result: `191 passed, 610 deselected in 15.66s`.

Ruff:

`python -m ruff check scripts/calibrate_opportunity.py tests/scripts/test_calibrate_opportunity.py app/opportunity/calibration tests/opportunity`

Result: `All checks passed!`

`python -m ruff format --check scripts/calibrate_opportunity.py tests/scripts/test_calibrate_opportunity.py app/opportunity/calibration tests/opportunity`

Result: `25 files already formatted` after formatting the two changed files.

Diff check:

`git diff --check`

Result: clean.

## Findings fixed

- Restored `settings.database_url` in the outer `finally`, independent of connection cleanup failures; added a close-failure regression test.
- Added bounded, sanitized argparse handling: public argument/validation errors exit 2, are capped at 160 characters, and do not expose URLs or tracebacks.
- Preserved operational failures as exit 1 and successful reports as exit 0.
- Added tests proving the supplied database URL is used and public errors are capped/redacted.
