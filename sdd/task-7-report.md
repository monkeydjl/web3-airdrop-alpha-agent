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

## Docker workflow build failure regression

Commands were run from the repository root unless noted.

### RED: deployment tests before Dockerfile fix

## `python -m pytest tests/test_deployment.py --no-cov -q` from `backend`

```text
........F.........s..........                                            [100%]
FAILED tests/test_deployment.py::TestDockerConfiguration::test_dockerfile_does_not_copy_ignored_data_directory
E       assert 'COPY data/' not in '# ...'
1 failed, 27 passed, 1 skipped in 0.44s
```

### GREEN: deployment tests after Dockerfile fix

## `python -m pytest tests/test_deployment.py --no-cov -q` from `backend`

```text
..................s..........                                            [100%]
28 passed, 1 skipped in 0.19s
```

### Docker build after Dockerfile fix

## `docker build -f docker/Dockerfile -t airdrop-alpha:shadow-rollout .`

```text
#13 [production 5/7] COPY backend/ ./backend/
#14 [production 6/7] COPY frontend/ ./frontend/
#15 [production 7/7] RUN mkdir -p /app/data/cache /app/backups &&     chown -R appuser:appuser /app
#16 naming to docker.io/library/airdrop-alpha:shadow-rollout done
#16 DONE 19.8s
```

## Fresh strict full-suite verified baseline

Commands were run from `backend`.

This section records fresh branch-head verification updates for current-reference docs only. Historical implementation plan text remains unchanged because those files document the baseline that was current when the plans were written.

### Strict backend full suite

## `python -m pytest --strict-markers --strict-config --cov=app --cov-report=term-missing`

```text
1524 passed, 1 skipped in 106.37s
TOTAL coverage: 84.44%
```

### Documentation updates

- Updated `README.md` verified test baseline to `1,524 passed, 1 skipped`; retained rounded README coverage as `84%` because `84.44%` rounds to `84%` at whole-percent badge/stat precision.
- Updated `docs/IMPLEMENTATION_STATUS.md` exact verified baseline to `1,524 passed / 1 skipped` and `84.44%` coverage.
- Updated `docs/superpowers/specs/2026-07-16-shadow-rollout-observability-design.md` because it states current verified facts rather than historical execution notes.
- Left `docs/superpowers/plans/2026-07-16-shadow-rollout-observability.md` unchanged because it is historical plan text documenting the baseline that was current when that plan was written.

## Docker smoke runtime entrypoint fix

Commands were run from the repository root unless noted.

### RED: deployment test before Dockerfile fix

## `python -m pytest tests/test_deployment.py --no-cov -q` from `backend`

```text
.........F.........s..........                                           [100%]
FAILED tests/test_deployment.py::TestDockerConfiguration::test_dockerfile_cmd_uses_valid_fastapi_module_entrypoint
E       AssertionError: assert '/app' == '/app/backend'
1 failed, 28 passed, 1 skipped in 0.47s
```

### GREEN: deployment tests and Ruff after Dockerfile fix

## `python -m ruff format tests/test_deployment.py; python -m ruff check tests/test_deployment.py; python -m ruff format --check tests/test_deployment.py; python -m pytest tests/test_deployment.py --no-cov -q` from `backend`

```text
1 file reformatted
All checks passed!
1 file already formatted
29 passed, 1 skipped in 0.24s
```

### Docker build

## `docker build -f docker/Dockerfile -t airdrop-alpha:shadow-rollout .`

```text
#16 [production 8/8] WORKDIR /app/backend
#17 naming to docker.io/library/airdrop-alpha:shadow-rollout done
#17 DONE 1.8s
```

### Docker runtime smoke

## `docker run -d --name airdrop-alpha-shadow-smoke -p 8002:8002 airdrop-alpha:shadow-rollout` then poll `http://localhost:8002/health`

```text
SMOKE_OK attempt=4 payload={"ok":true,"status":"healthy","version":"0.1.0","db":"ok","db_backend":"sqlite","quarantined_raw":0,"auth_required":false,"feedback_enabled":true,"opportunity_model_version":"opportunity-v2.0","opportunity_shadow_enabled":false,"opportunity_shadow_sample_rate":0.0}
```
