# Opportunity Shadow Rollout and Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add deterministic project-ID rollout and low-cardinality observability to automatic Opportunity v2.0 Shadow evaluation, harden Docker smoke checks, and align operator documentation with the verified system.

**Architecture:** Keep the legacy `score-v1.4` pipeline authoritative and perform sampling only on its successfully persisted, scored row snapshots. Put the pure SHA-256 bucket decision in `pipeline_run.py`, keep Prometheus instruments and best-effort recording in `metrics.py`, and expose only configured rollout state from `/health`. CI and the disabled release demo use bounded health polling with unconditional cleanup.

**Tech Stack:** Python 3.13, FastAPI, Pydantic Settings, Prometheus client, pytest, GitHub Actions, Docker, Next.js 16, React 19.

## Global Constraints

- Never read or modify `.env`; only `.env.example` may be changed.
- `OPPORTUNITY_SHADOW_ENABLED` defaults to `false` and remains the authoritative automatic-execution switch.
- `OPPORTUNITY_SHADOW_SAMPLE_RATE` defaults to `0.0` and must be a finite float in `[0.0, 1.0]`.
- Sampling uses the first eight SHA-256 digest bytes, unsigned big-endian, modulo 10,000, with `floor(sample_rate * 10_000)` as the exclusive threshold.
- Sampling applies only to automatic post-persistence Shadow execution; explicit Opportunity API evaluation is not sampled.
- Rows must be persisted, have a non-null legacy score, and have a non-empty project ID to be selected.
- Shadow remains non-authoritative: do not change `projects.score`, `projects.label`, `score-v1.4`, `opportunity-v2.0`, or `low-cost-curated-multiwallet-v1`.
- Prometheus labels must never contain project IDs, assessment IDs, URLs, exception text, or other unbounded values.
- Shadow service and metrics failures must never fail or alter the primary pipeline result.
- Do not add compatibility aliases, rollout databases, per-project overrides, or random fallbacks.
- Run PostgreSQL verifier commands sequentially to avoid concurrent DDL/DML deadlocks.
- Do not push to a remote.

## File Map

- `backend/app/config.py`: defines and validates the automatic Shadow sample rate.
- `backend/app/pipeline_run.py`: performs pure deterministic selection and runs the sampled Shadow batch.
- `backend/app/metrics.py`: owns bounded Shadow counters, histogram, rollout gauges, and failure-isolated recording helpers.
- `backend/app/main.py`: reports configured Shadow rollout state in health responses.
- `backend/tests/test_pipeline_run.py`: verifies settings, bucket stability, monotonic rollout, summaries, service lifecycle, and metrics isolation.
- `backend/tests/api/test_metrics.py`: verifies exported Shadow metric names and bounded labels.
- `backend/tests/api/test_opportunity.py`: verifies health rollout fields without database aggregation.
- `backend/tests/test_deployment.py`: verifies branch filters and bounded workflow polling structure.
- `.github/workflows/ci.yml`: listens to `master` and `main` and performs bounded Docker health polling with cleanup.
- `.github/workflows/release.yml`: keeps tag release behavior and updates the disabled demo health probe.
- `.env.example`: documents supported PostgreSQL configuration and Shadow rollout defaults.
- `README.md`: updates primary architecture, scoring, database, test, and frontend facts.
- `docs/OBSERVABILITY.md`: documents Shadow metrics and low-cardinality alerting.
- `docs/OPERATIONS.md`: documents rollout, observation, rollback, and verifier order.
- `docs/IMPLEMENTATION_STATUS.md`: records the verified implementation and test baseline.

---

## Completion Record

- Completed and locally merged to master on 2026-07-17.
- Final strict backend suite: 1,524 passed, 1 skipped, 84.44% coverage.
- Ruff check/format, frontend TypeScript, SQLite Shadow verifier, sequential PostgreSQL verifiers, Docker build/health smoke, and final branch review passed.
- No remote push was performed because no remote is configured.

### Task 1: Validated Sample-Rate Configuration and Pure Sampling

**Files:**
- Modify: `backend/app/config.py:170-177,220-237`
- Modify: `backend/app/pipeline_run.py:1-47`
- Test: `backend/tests/test_pipeline_run.py:1-73`

**Interfaces:**
- Produces: `Settings.opportunity_shadow_sample_rate: float` with default `0.0`.
- Produces: `opportunity_shadow_bucket(project_id: str) -> int` returning an integer in `[0, 9999]`.
- Produces: `is_opportunity_shadow_sampled(project_id: object, sample_rate: float) -> bool`.
- Consumes: no interfaces introduced by later tasks.

- [x] **Step 1: Write failing settings tests**

Add `ValidationError` and parameterized boundary tests to `backend/tests/test_pipeline_run.py`:

```python
from pydantic import ValidationError


def test_opportunity_shadow_defaults_disabled_and_unsampled(monkeypatch):
    monkeypatch.delenv("OPPORTUNITY_SHADOW_ENABLED", raising=False)
    monkeypatch.delenv("OPPORTUNITY_SHADOW_SAMPLE_RATE", raising=False)

    configured = Settings(_env_file=None)

    assert configured.opportunity_shadow_enabled is False
    assert configured.opportunity_shadow_sample_rate == 0.0


@pytest.mark.parametrize("sample_rate", [0.0, 0.05, 1.0])
def test_opportunity_shadow_sample_rate_accepts_closed_interval(sample_rate):
    assert Settings(_env_file=None, opportunity_shadow_sample_rate=sample_rate).opportunity_shadow_sample_rate == sample_rate


@pytest.mark.parametrize("sample_rate", [-0.01, 1.01, float("inf"), float("-inf"), float("nan")])
def test_opportunity_shadow_sample_rate_rejects_invalid_values(sample_rate):
    with pytest.raises(ValidationError, match="sample rate must be finite and between 0 and 1"):
        Settings(_env_file=None, opportunity_shadow_sample_rate=sample_rate)
```

Replace the existing defaults-only test rather than retaining duplicate coverage.

- [x] **Step 2: Run settings tests to verify failure**

Run: `python -m pytest tests/test_pipeline_run.py -k "sample_rate or defaults_disabled_and_unsampled" -v`

Working directory: `backend`

Expected: FAIL because `Settings` has no `opportunity_shadow_sample_rate` field and currently ignores that extra input.

- [x] **Step 3: Implement the setting and finite-range validator**

Add the setting beside `opportunity_shadow_enabled` in `backend/app/config.py`:

```python
    opportunity_shadow_enabled: bool = False
    opportunity_shadow_sample_rate: float = 0.0
```

Import `isfinite` from `math`, then add a dedicated validator before `model_post_init`:

```python
    @field_validator("opportunity_shadow_sample_rate")
    @classmethod
    def validate_opportunity_shadow_sample_rate(cls, value: float) -> float:
        if not isfinite(value) or not 0.0 <= value <= 1.0:
            raise ValueError("sample rate must be finite and between 0 and 1")
        return value
```

- [x] **Step 4: Run settings tests to verify pass**

Run: `python -m pytest tests/test_pipeline_run.py -k "sample_rate or defaults_disabled_and_unsampled" -v`

Expected: all selected tests PASS.

- [x] **Step 5: Write failing deterministic sampling tests**

Import the two new functions from `app.pipeline_run` and add:

```python
@pytest.mark.parametrize(
    ("project_id", "expected_bucket"),
    [
        ("project-1", 3389),
        ("alpha", 2974),
    ],
)
def test_opportunity_shadow_bucket_is_stable(project_id, expected_bucket):
    assert opportunity_shadow_bucket(project_id) == expected_bucket


@pytest.mark.parametrize("project_id", [None, "", "   "])
def test_opportunity_shadow_sampling_rejects_empty_ids(project_id):
    assert is_opportunity_shadow_sampled(project_id, 1.0) is False


def test_opportunity_shadow_sampling_has_explicit_boundaries():
    assert is_opportunity_shadow_sampled("project-1", 0.0) is False
    assert is_opportunity_shadow_sampled("project-1", 1.0) is True


def test_opportunity_shadow_sampling_is_monotonic():
    project_ids = [f"project-{index}" for index in range(500)]
    low = {project_id for project_id in project_ids if is_opportunity_shadow_sampled(project_id, 0.05)}
    high = {project_id for project_id in project_ids if is_opportunity_shadow_sampled(project_id, 0.25)}

    assert low
    assert low < high
```

The literal expected buckets are fixed compatibility vectors; do not calculate expected values with the production implementation in the test.

- [x] **Step 6: Run sampling tests to verify failure**

Run: `python -m pytest tests/test_pipeline_run.py -k "bucket or sampling" -v`

Expected: test collection FAILS because the sampling functions do not exist.

- [x] **Step 7: Implement pure deterministic sampling**

Add imports and pure helpers to `backend/app/pipeline_run.py`:

```python
import hashlib
from math import floor

OPPORTUNITY_SHADOW_BUCKETS = 10_000


def opportunity_shadow_bucket(project_id: str) -> int:
    digest = hashlib.sha256(project_id.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big", signed=False) % OPPORTUNITY_SHADOW_BUCKETS


def is_opportunity_shadow_sampled(project_id: object, sample_rate: float) -> bool:
    if not isinstance(project_id, str) or not project_id.strip():
        return False
    threshold = floor(sample_rate * OPPORTUNITY_SHADOW_BUCKETS)
    return opportunity_shadow_bucket(project_id) < threshold
```

Do not normalize case or whitespace for non-empty IDs: the persisted ID's exact UTF-8 representation is the sampling key.

- [x] **Step 8: Run Task 1 tests and commit**

Run: `python -m pytest tests/test_pipeline_run.py -k "sample_rate or bucket or sampling or defaults_disabled_and_unsampled" -v`

Expected: all selected tests PASS.

Then:

```bash
git add backend/app/config.py backend/app/pipeline_run.py backend/tests/test_pipeline_run.py
git commit -m "feat: add deterministic shadow sampling"
```

---

### Task 2: Sampled Shadow Batch Summary and Pipeline Wiring

**Files:**
- Modify: `backend/app/pipeline_run.py:32-80,122-230`
- Modify: `backend/tests/test_pipeline_run.py:62-334`

**Interfaces:**
- Consumes: `is_opportunity_shadow_sampled(project_id: object, sample_rate: float) -> bool` from Task 1.
- Produces: `OPPORTUNITY_SHADOW_EMPTY_STATS` with keys `eligible`, `sampled`, `attempted`, `saved`, `failed`, and `skipped`.
- Produces: `run_opportunity_shadow(..., enabled: bool, sample_rate: float, service_factory=None) -> dict[str, int]`.
- Produces: `execute_analysis_pipeline()` passes both configured rollout values and returns the six-field summary.

- [x] **Step 1: Update existing expectations and write failing rollout tests**

Define this test helper near the Shadow tests:

```python
EMPTY_SHADOW_STATS = {
    "eligible": 0,
    "sampled": 0,
    "attempted": 0,
    "saved": 0,
    "failed": 0,
    "skipped": 0,
}
```

Replace existing three-field expected dictionaries with the six-field summary. Pass `sample_rate=1.0` to tests that expect evaluation and `sample_rate=0.0` to the disabled test. Add:

```python
def test_sampled_out_rows_do_not_construct_service():
    service_factory = Mock()

    stats = run_opportunity_shadow(
        [{"id": "project-1", "score": 80}],
        enabled=True,
        sample_rate=0.0,
        service_factory=service_factory,
    )

    assert stats == {**EMPTY_SHADOW_STATS, "eligible": 1, "skipped": 1}
    service_factory.assert_not_called()


def test_invalid_ids_are_eligible_but_skipped_without_service():
    service_factory = Mock()
    rows = [{"id": None, "score": 80}, {"id": "", "score": 70}, {"score": 60}]

    stats = run_opportunity_shadow(rows, enabled=True, sample_rate=1.0, service_factory=service_factory)

    assert stats == {**EMPTY_SHADOW_STATS, "eligible": 3, "skipped": 3}
    service_factory.assert_not_called()


def test_all_in_summary_counts_unscored_rows_as_ineligible():
    rows = [{"id": "one", "score": 80}, {"id": "two", "score": 70}, {"id": "three", "score": None}]
    service = MagicMock()
    service.__enter__.return_value = service

    stats = run_opportunity_shadow(rows, enabled=True, sample_rate=1.0, service_factory=Mock(return_value=service))

    assert stats == {"eligible": 2, "sampled": 2, "attempted": 2, "saved": 2, "failed": 0, "skipped": 0}
```

- [x] **Step 2: Run batch tests to verify failure**

Run: `python -m pytest tests/test_pipeline_run.py -k "RunOpportunityShadow or sampled_out or invalid_ids or all_in_summary" -v`

Expected: FAIL because `sample_rate` is not accepted and the new summary fields are absent.

- [x] **Step 3: Implement selection before service construction**

Change the constant and function in `backend/app/pipeline_run.py`:

```python
OPPORTUNITY_SHADOW_EMPTY_STATS = {
    "eligible": 0,
    "sampled": 0,
    "attempted": 0,
    "saved": 0,
    "failed": 0,
    "skipped": 0,
}


def run_opportunity_shadow(
    persisted_project_rows: list[dict[str, Any]],
    *,
    enabled: bool,
    sample_rate: float,
    service_factory=None,
) -> dict[str, int]:
    stats = OPPORTUNITY_SHADOW_EMPTY_STATS.copy()
    if not enabled:
        return stats

    eligible_rows = [row for row in persisted_project_rows if row.get("score") is not None]
    stats["eligible"] = len(eligible_rows)
    sampled_rows = [
        row for row in eligible_rows if is_opportunity_shadow_sampled(row.get("id"), sample_rate)
    ]
    stats["sampled"] = len(sampled_rows)
    stats["skipped"] = stats["eligible"] - stats["sampled"]
    if not sampled_rows:
        return stats

    service_factory = service_factory or OpportunityService
    # Preserve the existing constructor, enter, per-row evaluation, and exit
    # failure isolation, but iterate over sampled_rows.
```

Keep lifecycle-start failures truthful: `eligible`, `sampled`, and `skipped` remain populated while `attempted`, `saved`, and `failed` remain zero.

- [x] **Step 4: Wire the configured rate through automatic execution**

Change the pipeline call to:

```python
    if save_to_db and settings.opportunity_shadow_enabled:
        opportunity_shadow = await asyncio.to_thread(
            run_opportunity_shadow,
            response.persisted_project_rows,
            enabled=True,
            sample_rate=settings.opportunity_shadow_sample_rate,
        )
```

Update `fake_shadow` in `test_opportunity_shadow_runs_after_orchestrator` to accept `sample_rate`, set the monkeypatched rate to `1.0`, and assert that the fake received it. Keep `save_to_db=False` proving no thread or service runs.

- [x] **Step 5: Run focused pipeline tests**

Run: `python -m pytest tests/test_pipeline_run.py -v`

Expected: all tests in the file PASS.

- [x] **Step 6: Commit sampled batch behavior**

```bash
git add backend/app/pipeline_run.py backend/tests/test_pipeline_run.py
git commit -m "feat: apply shadow rollout to pipeline"
```

---

### Task 3: Low-Cardinality Shadow Metrics and Failure Isolation

**Files:**
- Modify: `backend/app/metrics.py:20-149`
- Modify: `backend/app/pipeline_run.py:1-230`
- Modify: `backend/tests/test_pipeline_run.py:62-334`
- Modify: `backend/tests/api/test_metrics.py:17-81`

**Interfaces:**
- Consumes: six-field Shadow summary from Task 2.
- Consumes: `OpportunityService.evaluate_row(...) -> OpportunityAssessment`.
- Produces: `set_opportunity_shadow_rollout(enabled: bool, sample_rate: float) -> None`.
- Produces: `record_opportunity_shadow_projects(stats: Mapping[str, int]) -> None`.
- Produces: `record_opportunity_shadow_assessment(assessment: object) -> None`.
- Produces: `observe_opportunity_shadow_duration(duration_seconds: float) -> None`.
- All four helpers return `None`, no-op when metrics are disabled, and swallow/log metric exceptions.

- [x] **Step 1: Write failing exported-metric tests**

Extend `test_metrics_contains_airdrop_metrics` in `backend/tests/api/test_metrics.py`:

```python
        for metric_name in (
            "airdrop_opportunity_shadow_projects_total",
            "airdrop_opportunity_shadow_assessments_total",
            "airdrop_opportunity_shadow_duration_seconds",
            "airdrop_opportunity_shadow_enabled",
            "airdrop_opportunity_shadow_sample_rate",
        ):
            assert metric_name in content
```

Add a focused bounded-label test that imports `record_opportunity_shadow_assessment`, passes a `SimpleNamespace` with `status`, `public_label`, `model_version`, and `profile_version`, renders metrics, and asserts those four label names are present while `project_id`, `assessment_id`, `source_url`, and `error` are absent from the assessment metric line.

- [x] **Step 2: Run endpoint metric tests to verify failure**

Run: `python -m pytest tests/api/test_metrics.py -k "airdrop_metrics or bounded" -v`

Expected: FAIL because no Shadow metric instruments or recording helper exist.

- [x] **Step 3: Define instruments and best-effort helpers**

Add `Mapping` import and these instruments to `backend/app/metrics.py`:

```python
OPPORTUNITY_SHADOW_PROJECTS = Counter(
    "airdrop_opportunity_shadow_projects_total",
    "Automatic Opportunity Shadow projects by batch result.",
    ["result"],
)
OPPORTUNITY_SHADOW_ASSESSMENTS = Counter(
    "airdrop_opportunity_shadow_assessments_total",
    "Persisted Opportunity Shadow assessments by bounded model outcome.",
    ["status", "public_label", "model_version", "profile_version"],
)
OPPORTUNITY_SHADOW_DURATION = Histogram(
    "airdrop_opportunity_shadow_duration_seconds",
    "Automatic Opportunity Shadow selected-batch duration.",
    buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0],
)
OPPORTUNITY_SHADOW_ENABLED = Gauge(
    "airdrop_opportunity_shadow_enabled",
    "Whether automatic Opportunity Shadow evaluation is enabled.",
)
OPPORTUNITY_SHADOW_SAMPLE_RATE = Gauge(
    "airdrop_opportunity_shadow_sample_rate",
    "Configured deterministic Opportunity Shadow sample rate.",
)
```

Use the fixed project result tuple `("eligible", "sampled", "attempted", "saved", "failed", "skipped")`. Each helper first checks `MetricsExporter.is_enabled()`, wraps all Prometheus operations in `try/except Exception`, and logs `metrics.opportunity_shadow_update_failed` without re-raising. Assessment values use `str(value.value)` for enum-like values, `str(value)` otherwise, and `"unknown"` only when a value is absent.

- [x] **Step 4: Run endpoint metric tests to verify pass**

Run: `python -m pytest tests/api/test_metrics.py -k "airdrop_metrics or bounded" -v`

Expected: all selected tests PASS.

- [x] **Step 5: Write failing pipeline metric-isolation tests**

Add tests in `backend/tests/test_pipeline_run.py` that monkeypatch the imported recording helpers:

```python
def test_shadow_records_saved_assessment_and_batch_summary(monkeypatch):
    assessment = SimpleNamespace(
        status="MONITOR",
        public_label="WATCH",
        model_version="opportunity-v2.0",
        profile_version="low-cost-curated-multiwallet-v1",
    )
    service = MagicMock()
    service.__enter__.return_value = service
    service.evaluate_row.return_value = assessment
    recorded = []
    monkeypatch.setattr("app.pipeline_run.record_opportunity_shadow_assessment", recorded.append)
    monkeypatch.setattr("app.pipeline_run.record_opportunity_shadow_projects", lambda stats: recorded.append(stats.copy()))

    stats = run_opportunity_shadow(
        [{"id": "project-1", "score": 80}],
        enabled=True,
        sample_rate=1.0,
        service_factory=Mock(return_value=service),
    )

    assert recorded == [assessment, stats]


def test_metrics_failure_cannot_change_shadow_or_primary_result(monkeypatch):
    service = MagicMock()
    service.__enter__.return_value = service
    monkeypatch.setattr(
        "app.pipeline_run.record_opportunity_shadow_assessment",
        Mock(side_effect=RuntimeError("metrics failed")),
    )
    monkeypatch.setattr(
        "app.pipeline_run.record_opportunity_shadow_projects",
        Mock(side_effect=RuntimeError("metrics failed")),
    )

    stats = run_opportunity_shadow(
        [{"id": "project-1", "score": 80}],
        enabled=True,
        sample_rate=1.0,
        service_factory=Mock(return_value=service),
    )

    assert stats["saved"] == 1
    assert stats["failed"] == 0
```

Also verify a duration observer failure does not escape by injecting or monkeypatching it around the selected-batch timer.

- [x] **Step 6: Integrate best-effort recording into the Shadow batch**

Import `time` and the four helpers in `pipeline_run.py`. At pipeline start, call `set_opportunity_shadow_rollout(...)` inside an additional local `try/except` so even a monkeypatched helper that violates its own contract cannot escape. For selected rows, start `time.perf_counter()` immediately before service construction, record each returned assessment after `saved` increments, record the six summary counters once at every return path, and observe duration only when at least one row was sampled.

Use a local wrapper such as:

```python
def _record_shadow_metric(callback, *args) -> None:
    try:
        callback(*args)
    except Exception as error:
        logger.warning("pipeline.opportunity_shadow_metrics_failed", error=str(error))
```

Do not count metric failures as assessment failures.

- [x] **Step 7: Run all Shadow and metric tests**

Run: `python -m pytest tests/test_pipeline_run.py tests/api/test_metrics.py -v`

Expected: all tests PASS.

- [x] **Step 8: Commit metrics**

```bash
git add backend/app/metrics.py backend/app/pipeline_run.py backend/tests/test_pipeline_run.py backend/tests/api/test_metrics.py
git commit -m "feat: observe shadow rollout metrics"
```

---

### Task 4: Health Rollout State

**Files:**
- Modify: `backend/app/main.py:280-317`
- Modify: `backend/tests/api/test_opportunity.py:467-474`

**Interfaces:**
- Consumes: `settings.opportunity_shadow_enabled` and `settings.opportunity_shadow_sample_rate`.
- Produces: `/health` JSON fields `opportunity_shadow_enabled: bool` and `opportunity_shadow_sample_rate: float`.

- [x] **Step 1: Write the failing health assertion**

Update the existing Opportunity health test:

```python
def test_health_registers_shadow_capability_without_claiming_replacement(client):
    response = client.get(settings.health_check_path)

    assert response.status_code == 200
    body = response.json()
    assert body["opportunity_model_version"] == "opportunity-v2.0"
    assert body["opportunity_shadow_enabled"] is settings.opportunity_shadow_enabled
    assert body["opportunity_shadow_sample_rate"] == settings.opportunity_shadow_sample_rate
    assert "replace" not in str(body).lower()
```

- [x] **Step 2: Run health test to verify failure**

Run: `python -m pytest tests/api/test_opportunity.py::test_health_registers_shadow_capability_without_claiming_replacement -v`

Expected: FAIL with missing `opportunity_shadow_sample_rate`.

- [x] **Step 3: Add inexpensive configured state to health**

Change the two health fields in `backend/app/main.py` to direct settings access:

```python
            "opportunity_shadow_enabled": settings.opportunity_shadow_enabled,
            "opportunity_shadow_sample_rate": settings.opportunity_shadow_sample_rate,
```

Do not query Opportunity tables or Prometheus from the health endpoint.

- [x] **Step 4: Run health and metrics endpoint tests**

Run: `python -m pytest tests/api/test_opportunity.py::test_health_registers_shadow_capability_without_claiming_replacement tests/api/test_metrics.py -v`

Expected: all tests PASS.

- [x] **Step 5: Commit health state**

```bash
git add backend/app/main.py backend/tests/api/test_opportunity.py
git commit -m "feat: expose shadow rollout health"
```

---

### Task 5: CI and Release Smoke Hardening

**Files:**
- Modify: `.github/workflows/ci.yml:1-15,129-135`
- Modify: `.github/workflows/release.yml:76-89`
- Modify: `backend/tests/test_deployment.py:1-225`

**Interfaces:**
- Produces: CI push and pull-request filters containing both `master` and `main`.
- Produces: a 30-attempt, one-second health loop that prints logs on timeout and always removes the smoke container.
- Preserves: tag-only release trigger, repository-root Docker context, and `docker/Dockerfile`.

- [x] **Step 1: Write failing workflow structure tests**

Import `Path` and `yaml`, add a loader that prevents PyYAML from coercing the key `on` by reading the workflow as text for branch assertions, and add:

```python
def test_ci_supports_master_and_main_branches():
    content = Path(PROJECT_ROOT, ".github", "workflows", "ci.yml").read_text(encoding="utf-8")
    assert "branches: [master, main" in content


def test_ci_health_smoke_is_bounded_and_has_cleanup():
    content = Path(PROJECT_ROOT, ".github", "workflows", "ci.yml").read_text(encoding="utf-8")
    assert "seq 1 30" in content
    assert "sleep 1" in content
    assert "/health" in content
    assert "docker logs" in content
    assert "docker rm -f" in content


def test_release_demo_health_probe_is_bounded_and_diagnostic():
    content = Path(PROJECT_ROOT, ".github", "workflows", "release.yml").read_text(encoding="utf-8")
    assert "seq 1 30" in content
    assert "sleep 1" in content
    assert "/health" in content
    assert "docker compose logs backend" in content


def test_release_remains_tag_driven_with_root_docker_context():
    content = Path(PROJECT_ROOT, ".github", "workflows", "release.yml").read_text(encoding="utf-8")
    assert 'tags:' in content and '"v*"' in content
    assert "context: ." in content
    assert "file: docker/Dockerfile" in content
```

The release test may match the disabled demo script; it is a structural guard, not a claim that demo deployment runs in CI.

- [x] **Step 2: Run workflow tests to verify failure**

Run: `python -m pytest tests/test_deployment.py -k "workflow or ci_supports or release_remains" -v`

Expected: FAIL because `master`, bounded polling, logs, and unconditional cleanup are absent.

- [x] **Step 3: Update CI branch filters and smoke script**

Set both branch filters to include `master` and `main` while preserving current patterns:

```yaml
  push:
    branches: [master, main, 'feat/**', 'fix/**', 'docs/**']
  pull_request:
    branches: [master, main]
```

Replace the fixed sleep with:

```yaml
      - name: Smoke test - health check
        run: |
          set -euo pipefail
          container=airdrop-smoke
          cleanup() { docker rm -f "$container" >/dev/null 2>&1 || true; }
          trap cleanup EXIT
          docker run -d --name "$container" -p 8002:8002 airdrop-alpha:ci-${{ github.sha }}
          for attempt in $(seq 1 30); do
            if curl --fail --silent --show-error http://localhost:8002/health; then
              exit 0
            fi
            sleep 1
          done
          docker logs "$container"
          exit 1
```

The `trap` guarantees cleanup after success, timeout, curl failure, or shell interruption.

- [x] **Step 4: Update the disabled release demo probe**

Keep `if: false`, but replace its fixed sleep with a remote shell command that runs `for attempt in $(seq 1 30)`, checks `/health`, sleeps one second, and on timeout runs `docker compose logs backend` before returning non-zero. Do not stop the demo compose stack after a successful deployment; unlike the disposable CI smoke container, it is the deployed service.

Prefer a self-contained remote script using `ssh ... 'bash -se' <<'EOF'` so loop quoting is readable and deterministic.

- [x] **Step 5: Run deployment structure tests**

Run: `python -m pytest tests/test_deployment.py -v`

Expected: all tests PASS.

- [x] **Step 6: Inspect workflow diffs and commit**

Run: `git diff --check -- .github/workflows/ci.yml .github/workflows/release.yml backend/tests/test_deployment.py`

Expected: no whitespace errors.

Then:

```bash
git add .github/workflows/ci.yml .github/workflows/release.yml backend/tests/test_deployment.py
git commit -m "fix(ci): harden docker health smoke"
```

---

### Task 6: Operator and Onboarding Documentation

**Files:**
- Modify: `.env.example:32-43,71-78,171-179`
- Modify: `README.md:1-432`
- Modify: `docs/OBSERVABILITY.md`
- Modify: `docs/OPERATIONS.md`
- Modify: `docs/IMPLEMENTATION_STATUS.md`

**Interfaces:**
- Consumes: rollout environment names, metric names, health fields, and verifier commands from Tasks 1-5.
- Produces: one consistent operator narrative for enablement, increase, observation, rollback, and verification.

- [x] **Step 1: Correct `.env.example` database, scoring, and rollout settings**

Replace the stale PostgreSQL comments with:

```dotenv
# SQLite is the default when DATABASE_URL is unset.
DB_PATH=data/airdrop.db
# PostgreSQL is fully supported; the local test compose maps it to port 5433.
# DATABASE_URL=postgresql://airdrop:airdrop_test@127.0.0.1:5433/airdrop_test
```

Replace the six stale weight values with all eight defaults from `Settings`: `0.18`, `0.15`, `0.12`, `0.12`, `0.10`, `0.10`, `0.13`, and `0.10`, including `WEIGHT_EXECUTION` and `WEIGHT_TRANSPARENCY`.

Document rollout defaults together:

```dotenv
# Automatic Opportunity v2.0 Shadow evaluation is non-authoritative.
OPPORTUNITY_SHADOW_ENABLED=false
# Deterministic fraction of persisted, scored projects selected by project ID.
OPPORTUNITY_SHADOW_SAMPLE_RATE=0.0
```

- [x] **Step 2: Update README verified facts**

Make these exact corrections without rewriting unrelated sections:

- Badge and test sections: `1,486 passed, 1 skipped`, `84% coverage`.
- Primary frontend: `frontend-next`, Next.js 16, React 19, port 3002; describe `frontend` as the retained HTML prototype.
- Backend: FastAPI on port 8002.
- Database: SQLite default plus PostgreSQL through `DATABASE_URL`.
- Primary model: eight-factor `score-v1.4`, FARM at 65 or above.
- Opportunity: `opportunity-v2.0` with profile `low-cost-curated-multiwallet-v1`, append-only and non-authoritative.
- Quick start: use the actual `frontend-next` package scripts from its `package.json`; do not retain `python -m http.server 3002` as the primary route.

- [x] **Step 3: Document metrics and bounded labels**

Add a dedicated Opportunity Shadow section to `docs/OBSERVABILITY.md` listing the five metric families exactly:

```text
airdrop_opportunity_shadow_projects_total{result}
airdrop_opportunity_shadow_assessments_total{status,public_label,model_version,profile_version}
airdrop_opportunity_shadow_duration_seconds
airdrop_opportunity_shadow_enabled
airdrop_opportunity_shadow_sample_rate
```

Document the six allowed `result` values and explicitly prohibit project ID, assessment ID, URL, and error text labels. Include practical alert examples based on failure ratio and absence of saved assessments after sampled/attempted increases, without presenting a universal production threshold as verified fact.

- [x] **Step 4: Document rollout and sequential verification operations**

Add to `docs/OPERATIONS.md`:

1. Start with `OPPORTUNITY_SHADOW_ENABLED=false` and rate `0.0`.
2. Enable at `0.05` after baseline health verification.
3. Observe health fields and Shadow counters, assessment statuses/labels, and duration for a normal scheduling window.
4. Increase gradually; explain that deterministic bucket thresholds create monotonic supersets.
5. Roll back by setting enabled to `false`; no schema or legacy-score rollback is needed.

Include these PostgreSQL commands in this exact sequential order:

```powershell
$env:DATABASE_URL='postgresql://airdrop:airdrop_test@127.0.0.1:5433/airdrop_test'
python scripts/verify_postgres.py
python scripts/verify_opportunity_shadow.py
python scripts/verify_init_db_concurrency.py --database-url 'postgresql://airdrop:airdrop_test@127.0.0.1:5433/airdrop_test' --workers 4 --rounds 2
```

State that they run from `backend` and must not be parallelized.

- [x] **Step 5: Update implementation status**

Record deterministic rollout, six-field summaries, low-cardinality metrics, health configuration, CI branch support, and bounded Docker health polling as implemented. Record the verified baseline as `1,486 passed, 1 skipped` and `84.26%` coverage, while README may use rounded `84%`.

- [x] **Step 6: Scan documentation for specifically superseded claims**

Run from repository root:

```powershell
rg -n "417|FARM.*75|纯 HTML|SQLite-only|未完全接线|当前代码未完全接线|python -m http.server 3002" README.md .env.example docs/OBSERVABILITY.md docs/OPERATIONS.md docs/IMPLEMENTATION_STATUS.md
```

Expected: no matches that describe the current system. Historical context must be explicitly labeled historical if retained.

- [x] **Step 7: Check documentation diff and commit**

Run: `git diff --check -- .env.example README.md docs/OBSERVABILITY.md docs/OPERATIONS.md docs/IMPLEMENTATION_STATUS.md`

Expected: no whitespace errors.

Then:

```bash
git add .env.example README.md docs/OBSERVABILITY.md docs/OPERATIONS.md docs/IMPLEMENTATION_STATUS.md
git commit -m "docs: document shadow rollout operations"
```

---

### Task 7: Complete Verification and Delivery Review

**Files:**
- Verify only; fix only failures caused by Tasks 1-6 in their owning files.

**Interfaces:**
- Consumes: all prior deliverables.
- Produces: evidence that lint, format, tests, frontend types, both database backends, workflows, and whitespace gates pass.

- [x] **Step 1: Run focused backend regression tests**

Run from `backend`:

```powershell
python -m pytest tests/test_pipeline_run.py tests/api/test_metrics.py tests/api/test_opportunity.py tests/test_deployment.py -v
```

Expected: all selected tests PASS.

- [x] **Step 2: Run Ruff gates**

Run from `backend`:

```powershell
python -m ruff check .
python -m ruff format --check .
```

Expected: `All checks passed!` and all files already formatted. If format check fails, run `python -m ruff format <only-the-files-changed-by-this-plan>` and rerun both gates.

- [x] **Step 3: Run strict full backend suite**

Run from `backend`:

```powershell
python -m pytest tests -q --cov=app --cov-report=term-missing --cov-fail-under=80 -W error::DeprecationWarning -W error::ResourceWarning -W error::pytest.PytestUnraisableExceptionWarning
```

Expected: all tests pass, at least 80% coverage, and no strict warning failure. Record the new exact pass/skip count in `docs/IMPLEMENTATION_STATUS.md`; update README only if the baseline intentionally tracks the post-change exact count.

- [x] **Step 4: Run frontend type checking**

Run: `npx tsc --noEmit`

Working directory: `frontend-next`

Expected: exit code 0 with no TypeScript errors.

- [x] **Step 5: Run SQLite Shadow verifier**

Run: `python scripts/verify_opportunity_shadow.py`

Working directory: `backend`

Expected: output contains `RESULT: PASS` and reports SQLite backend. Launch this command with `DATABASE_URL` explicitly removed from the child process environment; do not inspect `.env` to establish backend selection.

- [x] **Step 6: Run PostgreSQL verifiers sequentially**

Ensure the existing `airdrop-alpha-postgres-test` container is healthy, then run each command separately from `backend` with an explicit URL:

```powershell
$env:DATABASE_URL='postgresql://airdrop:airdrop_test@127.0.0.1:5433/airdrop_test'
python scripts/verify_postgres.py
python scripts/verify_opportunity_shadow.py
python scripts/verify_init_db_concurrency.py --database-url 'postgresql://airdrop:airdrop_test@127.0.0.1:5433/airdrop_test' --workers 4 --rounds 2
```

Expected in order: `RESULT: OK`, `db_backend=postgres` plus `RESULT: PASS`, then `RESULT: PASS`. Never launch these three commands in parallel.

- [x] **Step 7: Build and smoke-test the Docker image locally**

Run from repository root:

```powershell
docker build -f docker/Dockerfile -t airdrop-alpha:shadow-rollout .
docker run --rm -d --name airdrop-shadow-smoke -p 8002:8002 airdrop-alpha:shadow-rollout
```

Poll `http://localhost:8002/health` once per second for at most 30 attempts. Confirm HTTP 200 and both Shadow rollout fields. On failure inspect `docker logs airdrop-shadow-smoke`; always run `docker rm -f airdrop-shadow-smoke` afterward.

- [x] **Step 8: Inspect repository state and final diff**

Run from repository root:

```powershell
git status --short
git diff --check
git log --oneline -10
```

Expected: no whitespace errors, only intended files changed, and no secrets or generated artifacts. Do not modify unrelated concurrent work.

- [x] **Step 9: Request code review and address only concrete findings**

Use `superpowers:requesting-code-review` against the commits created by this plan. Review for sampling formula correctness, summary invariants, failure isolation, metric cardinality, workflow cleanup, and documentation accuracy. If a finding requires a code change, add or adjust a failing regression test first, implement the minimum fix, rerun the relevant focused gate, and create a new commit rather than amending prior commits.
