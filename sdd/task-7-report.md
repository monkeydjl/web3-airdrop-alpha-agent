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
