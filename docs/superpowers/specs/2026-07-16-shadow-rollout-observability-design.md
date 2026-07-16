# Opportunity Shadow Rollout and Observability Design

## Goal

Add a controlled rollout mechanism and low-cardinality observability for
Opportunity v2.0 Shadow evaluations while preserving the legacy `score-v1.4`
decision path. The work also aligns CI and release automation with the current
`master` branch, replaces fixed Docker smoke-test sleeps with bounded health
polling, and updates operator-facing documentation to match the verified
system state.

## Non-Goals

- Shadow assessments do not replace `projects.score` or `projects.label`.
- No project-specific rollout overrides or database-backed rollout table.
- No random, run-scoped, or process-local sampling.
- No high-cardinality Prometheus labels such as project IDs, assessment IDs,
  exception messages, or source URLs.
- No remote push or production deployment as part of this work.

## Configuration

Two settings govern automatic Shadow execution:

- `OPPORTUNITY_SHADOW_ENABLED`, default `false`.
- `OPPORTUNITY_SHADOW_SAMPLE_RATE`, a finite float in `[0.0, 1.0]`, default
  `0.0`.

The global switch is authoritative. A disabled switch prevents all automatic
Shadow evaluations regardless of sample rate. With the switch enabled, a rate
of `0.0` evaluates no projects and a rate of `1.0` evaluates every eligible
project.

Configuration validation rejects non-finite values and values outside the
closed interval. Explicit Opportunity API evaluation remains available and is
not sampled; sampling applies only to automatic post-persistence pipeline
Shadow execution.

## Deterministic Project Sampling

Sampling uses the persisted project ID as its only input:

1. Encode the non-empty project ID as UTF-8.
2. Calculate its SHA-256 digest.
3. Interpret the first eight digest bytes as an unsigned big-endian integer.
4. Map the integer to one of 10,000 buckets using modulo 10,000.
5. Convert the sample rate to an integer threshold using
   `floor(sample_rate * 10_000)`.
6. Select the project when its bucket is below the threshold.

Rows without a non-empty project ID are skipped. There is no random fallback.
The fixed bucket space gives these properties:

- The same project and rate produce the same result across processes,
  machines, and Python versions.
- Increasing the rate produces a monotonic superset of selected projects.
- Boundary behavior is explicit: `0.0` selects none and `1.0` selects all.

Sampling occurs after filtering for persisted rows with a non-null legacy
score and before constructing the Opportunity service context. If no rows are
selected, no Opportunity database connection or service context is opened.

## Pipeline Behavior

Automatic execution remains best-effort and isolated from the primary
pipeline:

- Only successfully persisted, scored rows are eligible.
- Sampling does not mutate pipeline state or persisted legacy decisions.
- Constructor, context entry, evaluation, context exit, and metrics failures
  cannot fail the primary pipeline.
- One project evaluation failure does not prevent later selected projects from
  running.

The Shadow result summary becomes:

- `eligible`: scored, persisted rows considered for sampling.
- `sampled`: eligible rows selected by deterministic sampling.
- `attempted`: selected rows whose evaluation was attempted.
- `saved`: evaluations completed and persisted.
- `failed`: attempted evaluations that raised an exception.
- `skipped`: eligible rows not selected, plus invalid-ID rows.

For backward clarity, `attempted`, `saved`, and `failed` retain their existing
meaning. New fields make rollout behavior observable without exposing project
identifiers.

## Prometheus Metrics

Metrics use bounded labels only:

- `airdrop_opportunity_shadow_projects_total{result}` where `result` is one of
  `eligible`, `sampled`, `attempted`, `saved`, `failed`, or `skipped`.
- `airdrop_opportunity_shadow_assessments_total{status,public_label,model_version,profile_version}`.
- `airdrop_opportunity_shadow_duration_seconds` for selected-batch execution.
- `airdrop_opportunity_shadow_enabled` gauge with value `0` or `1`.
- `airdrop_opportunity_shadow_sample_rate` gauge with the configured rate.

Assessment labels come from bounded model enums and fixed version constants.
Missing assessment values use the bounded literal `unknown`. Project IDs,
errors, and URLs remain in structured logs only and never become labels.

Metrics are updated only when metrics are enabled. Metrics collection remains
best-effort and cannot affect the pipeline result.

## Health Response

The existing health endpoint adds two inexpensive configuration fields:

- `opportunity_shadow_enabled`
- `opportunity_shadow_sample_rate`

The endpoint performs no Shadow table aggregation. Prometheus provides runtime
counts and durations; health only reports configured rollout state.

## CI and Release Automation

CI branch filters support both `master` and `main` during repository branch
transition. Existing feature, fix, and documentation branch filters remain.

Docker smoke checks replace fixed sleeps with a bounded polling loop:

- Poll `/health` once per second for up to 30 attempts.
- Exit immediately on success.
- On timeout, print container logs, stop the container, and fail the step.
- Cleanup runs even when the health probe fails.

Release remains tag-driven and therefore does not require a branch filter. Its
image build continues to use repository-root context and `docker/Dockerfile`.
The disabled demo deployment example uses the same bounded health polling
pattern instead of a fixed sleep.

## Documentation Updates

Operator and onboarding documentation must reflect verified facts:

- Next.js 16 and React 19 are the primary frontend.
- Local frontend and backend ports are 3002 and 8002.
- SQLite is the default database and PostgreSQL is supported through
  `DATABASE_URL`.
- The current full suite baseline is 1,486 passed, 1 skipped, with 84% coverage.
- The primary score remains the current eight-factor `score-v1.4` model with
  FARM at 65 or above.
- Opportunity v2.0 remains a non-authoritative Shadow model.
- Rollout enable, increase, observe, rollback, and verification steps are
  documented in `.env.example`, `README.md`, `docs/OBSERVABILITY.md`,
  `docs/OPERATIONS.md`, and `docs/IMPLEMENTATION_STATUS.md`.

## Testing

Focused tests cover:

- Settings defaults and validation boundaries.
- Stable bucket results for known project IDs.
- `0.0`, intermediate, and `1.0` sample rates.
- Monotonic selection as the rate increases.
- Disabled execution, sampled-out execution, invalid IDs, and all-in execution.
- Service construction only when at least one row is selected.
- Constructor, enter, evaluation, exit, and metrics failure isolation.
- Summary counts and low-cardinality assessment metric labels.
- Health response rollout fields.

Final validation includes Ruff check and format, the strict full pytest suite,
frontend TypeScript checking, SQLite and PostgreSQL Shadow verifiers,
PostgreSQL concurrent initialization, workflow structure checks, and
`git diff --check`.

## Rollout Procedure

1. Deploy with `OPPORTUNITY_SHADOW_ENABLED=false` and verify legacy behavior.
2. Set the switch to `true` with a low sample rate such as `0.05`.
3. Observe selected, attempted, saved, failed, assessment status, label, and
   duration metrics for at least one normal scheduling window.
4. Increase the rate gradually. Deterministic monotonic sampling keeps prior
   projects in the sample.
5. Roll back immediately by setting the global switch to `false`; no schema or
   data rollback is required because assessment storage is append-only and
   non-authoritative.

## Acceptance Criteria

- Automatic Shadow evaluation is disabled by default and deterministically
  sampled by project ID when enabled.
- Shadow failures cannot change primary pipeline success or legacy decisions.
- Metrics and health expose rollout state without high-cardinality labels or
  expensive health queries.
- CI triggers on `master` and `main`, and smoke checks use bounded polling.
- Documentation matches verified code, test, frontend, and database behavior.
- All final validation gates pass before implementation is committed.
