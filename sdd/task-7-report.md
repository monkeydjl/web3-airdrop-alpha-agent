# Task 7 final verification

Commands were run from `backend`.

## `python -m ruff check .`

```text
All checks passed!
```

## `python -m ruff format --check .`

```text
148 files already formatted
```

## `python -m pytest tests/api/test_metrics.py tests/api/test_opportunity.py tests/test_deployment.py tests/test_pipeline_run.py --no-cov -q`

```text
........................................................................ [ 50%]
................s.....................................................   [100%]
141 passed, 1 skipped in 7.99s
```

## Fresh full-suite failure fix verification

Commands were run from `backend`.

### Four focused tests before the fix

```text
tests\api\test_run.py FFFF                                               [100%]
FAILED tests/api/test_run.py::TestRunEndpoint::test_run_reports_disabled_opportunity_shadow
FAILED tests/api/test_run.py::TestRunEndpoint::test_run_reports_enabled_opportunity_shadow
FAILED tests/api/test_run.py::TestRunEndpoint::test_shadow_failure_preserves_legacy_response
FAILED tests/api/test_run.py::TestRunEndpoint::test_run_empty_projects_triggers_auto_collection
============================= 4 failed in 10.07s ==============================
```

### Four focused tests after the fix

## `pytest tests/api/test_run.py::TestRunEndpoint::test_run_reports_disabled_opportunity_shadow tests/api/test_run.py::TestRunEndpoint::test_run_reports_enabled_opportunity_shadow tests/api/test_run.py::TestRunEndpoint::test_shadow_failure_preserves_legacy_response tests/api/test_run.py::TestRunEndpoint::test_run_empty_projects_triggers_auto_collection --no-cov -q`

```text
....                                                                     [100%]
4 passed in 3.51s
```

### Entire run API test file

## `pytest tests/api/test_run.py --no-cov -q`

```text
......................                                                   [100%]
22 passed in 6.69s
```

### Prior four focused files

## `pytest tests/api/test_metrics.py tests/api/test_opportunity.py tests/test_deployment.py tests/test_pipeline_run.py --no-cov -q`

```text
........................................................................ [ 50%]
................s.....................................................   [100%]
141 passed, 1 skipped in 7.86s
```

### Ruff changed-file checks

## `python -m ruff check tests/api/test_run.py`

```text
All checks passed!
```

## `python -m ruff format --check tests/api/test_run.py`

```text
1 file already formatted
```
