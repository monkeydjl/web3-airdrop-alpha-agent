# Opportunity Outcome Calibration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic, read-only CLI that evaluates mature `opportunity-v2.0` assessment outcomes and produces privacy-safe JSON and Markdown reports with human-review-only calibration suggestions.

**Architecture:** Add a focused `app.opportunity.calibration` package. A read-only loader converts assessment and interaction rows into immutable assessment-cohort samples; pure modules handle outcome mapping, metrics, cluster bootstrap, gates, suggestions, and report rendering. The CLI orchestrates these modules and atomically writes reports without changing application tables or runtime decisions.

**Tech Stack:** Python 3.11+, standard library statistics/random/json, Pydantic v2 models already in the project, SQLite/PostgreSQL through `DbConnection`, pytest, Ruff.

## Global Constraints

- Never read or modify `.env`; `.env.example` does not need changes for this feature.
- Preserve the existing local `.workbuddy/memory/MEMORY.md` modification and never stage it with feature commits.
- Calibration is read-only: production code may issue only `SELECT` statements against application databases.
- Supported inputs are exactly `opportunity-v2.0` and `low-cost-curated-multiwallet-v1`.
- The base unit is one unique `(opportunity_assessment_id, wallet_cohort_id)` pair.
- Duplicate assessment-cohort pairs are all excluded; never select the latest row or merge rows.
- `--as-of` is mandatory and timezone-aware.
- Maturity windows are fixed at 90 and 180 days; the 180-day population is nested inside the 90-day population.
- Dimension completeness is independent: missing economics must not suppress a valid eligibility observation.
- Recommendation evidence always uses project-equal metrics.
- Fewer than 30 valid samples yields data-quality-only output; 30-99 yields descriptive output; advisory output requires at least 100 samples and 30 projects.
- Segment advice requires at least 30 samples and 10 projects.
- Bootstrap uses project-cluster resampling, 1,000 replicates, and a fixed seed recorded in the report.
- Reports contain no project, assessment, cohort, user, URL, note, activity, or disqualification identifiers/text.
- Suggestions always contain `auto_apply: false` and never update models, profiles, thresholds, settings, projects, or assessments.
- Applying a suggestion later requires a separately approved new model or profile version.
- JSON must contain only finite numbers or null, use sorted keys and UTF-8, and end with a newline.
- The same database snapshot and CLI arguments must produce byte-identical JSON and Markdown.
- PostgreSQL smoke commands run sequentially, never in parallel.
- Do not push to a remote unless separately requested.

## File Map

- `backend/app/opportunity/calibration/__init__.py`: exports the stable calibration API.
- `backend/app/opportunity/calibration/models.py`: immutable internal samples, observations, ranges, gates, suggestions, and dataset models.
- `backend/app/opportunity/calibration/outcomes.py`: maturity and dimension-specific outcome mapping.
- `backend/app/opportunity/calibration/loader.py`: SELECT-only assessment/interaction loading, linkage validation, duplicate exclusion, and quality counts.
- `backend/app/opportunity/calibration/metrics.py`: weighted probability, economic, and decision metrics.
- `backend/app/opportunity/calibration/advice.py`: cluster bootstrap, sample gates, fixed segments, and deterministic suggestions.
- `backend/app/opportunity/calibration/report.py`: two-window report assembly, canonical report ID, JSON, Markdown, and atomic output.
- `backend/scripts/calibrate_opportunity.py`: operator CLI.
- `backend/scripts/verify_opportunity_calibration.py`: network-free SQLite/PostgreSQL smoke verifier.
- `backend/tests/opportunity/test_calibration_outcomes.py`: outcome and maturity unit tests.
- `backend/tests/opportunity/test_calibration_loader.py`: loader, quality, duplicate, privacy, and read-only tests.
- `backend/tests/opportunity/test_calibration_metrics.py`: hand-calculated probability/economic/decision metrics.
- `backend/tests/opportunity/test_calibration_advice.py`: project weighting, bootstrap, gates, segments, and suggestions.
- `backend/tests/opportunity/test_calibration_report.py`: deterministic report schema/render/output tests.
- `backend/tests/scripts/test_calibrate_opportunity.py`: CLI behavior and errors.
- `backend/tests/scripts/test_verify_opportunity_calibration.py`: verifier regression test.
- `docs/OPERATIONS.md`: calibration command, interpretation, approval, and sequential verifier procedure.
- `docs/IMPLEMENTATION_STATUS.md`: records calibration as an offline advisory capability.

---

### Task 1: Immutable Samples, Maturity, and Outcome Mapping

**Files:**
- Create: `backend/app/opportunity/calibration/__init__.py`
- Create: `backend/app/opportunity/calibration/models.py`
- Create: `backend/app/opportunity/calibration/outcomes.py`
- Create: `backend/tests/opportunity/test_calibration_outcomes.py`

**Interfaces:**
- Produces: `RangeValue(low: float, base: float, high: float)`.
- Produces: `CalibrationSample` with internal IDs, prediction snapshot, outcome fields, and timestamps.
- Produces: `OutcomeValues(event, eligibility, survival, reward, realized_net_usd, realized_class, actual_hard_cost_usd, actual_time_hours, claim_cost_usd)`.
- Produces: `maturity_state(sample, as_of, window_days) -> str`.
- Produces: `map_outcomes(sample) -> tuple[OutcomeValues, tuple[str, ...]]`.

- [ ] **Step 1: Write failing model and maturity tests**

Create tests that import the desired interfaces and use this fixture shape:

```python
def sample(**updates):
    values = {
        "project_id": "project-1",
        "assessment_id": "assessment-1",
        "cohort_id": "cohort-550e8400-e29b-41d4-a716-446655440000",
        "scored_at": datetime(2026, 1, 1, tzinfo=UTC),
        "outcome_observed_at": datetime(2026, 4, 1, tzinfo=UTC),
        "model_version": "opportunity-v2.0",
        "profile_version": "low-cost-curated-multiwallet-v1",
        "status": "ACTIONABLE",
        "public_label": "FARM",
        "wallet_count": 3,
        "event_probability": RangeValue(0.6, 0.7, 0.8),
        "eligibility_probability": RangeValue(0.5, 0.6, 0.7),
        "survival_probability": RangeValue(0.7, 0.8, 0.9),
        "reward_probability": RangeValue(0.3, 0.4, 0.5),
        "net_reward": RangeValue(10, 30, 50),
        "hard_cost": RangeValue(2, 4, 6),
        "total_time_hours": RangeValue(1, 2, 3),
        "outcome": "airdropped",
        "eligibility_result": "eligible",
        "survival_result": "passed",
        "reward_received_usd": 40.0,
        "actual_hard_cost_usd": 5.0,
        "claim_cost_usd": 1.0,
        "actual_time_minutes": 150,
    }
    return CalibrationSample(**(values | updates))
```

Assert exact maturity boundaries: 89 days is `immature`, 90 days is `mature`, a future outcome is `outcome_after_as_of`, and an outcome before scoring is `outcome_before_assessment`.

- [ ] **Step 2: Run maturity tests to verify import failure**

Run from `backend`:

```powershell
python -m pytest tests/opportunity/test_calibration_outcomes.py -k "maturity or range" -v
```

Expected: collection error because `app.opportunity.calibration` does not exist.

- [ ] **Step 3: Implement immutable models and maturity**

Use frozen dataclasses with explicit nullable fields. `RangeValue.__post_init__`
must reject non-finite values and require `low <= base <= high`.

Implement exact maturity return values:

```python
def maturity_state(sample, *, as_of, window_days):
    if sample.scored_at > sample.outcome_observed_at:
        return "outcome_before_assessment"
    if sample.outcome_observed_at > as_of:
        return "outcome_after_as_of"
    if sample.outcome_observed_at - sample.scored_at < timedelta(days=window_days):
        return "immature"
    return "mature"
```

- [ ] **Step 4: Write failing dimension mapping tests**

Cover all exact mappings from the design:

```python
assert map_outcomes(sample(outcome="airdropped"))[0].event == 1
assert map_outcomes(sample(outcome="not_airdropped"))[0].event == 0
assert map_outcomes(sample(outcome="profit"))[0].event is None
assert map_outcomes(sample(eligibility_result="ineligible"))[0].eligibility == 0
assert map_outcomes(sample(survival_result="disqualified"))[0].survival == 0
assert map_outcomes(sample(reward_received_usd=0))[0].reward == 0
```

Also assert that a positive reward plus `ineligible`, `disqualified`, or
`not_airdropped` returns `contradictory_outcome` and suppresses reward,
realized net, and realized class. Economic completeness must require reward,
actual hard cost, and claim cost. Realized classes must be POSITIVE, NEGATIVE,
and NEUTRAL exactly as specified.

- [ ] **Step 5: Run mapping tests to verify failure**

Run: `python -m pytest tests/opportunity/test_calibration_outcomes.py -v`

Expected: failures because `map_outcomes` is absent.

- [ ] **Step 6: Implement mapping and exports**

Keep mapping pure and never use API-computed `realized_net_usd`. Export public
interfaces from `calibration/__init__.py`.

- [ ] **Step 7: Run tests, Ruff, and commit**

Run:

```powershell
python -m pytest tests/opportunity/test_calibration_outcomes.py -v
python -m ruff check app/opportunity/calibration tests/opportunity/test_calibration_outcomes.py
python -m ruff format --check app/opportunity/calibration tests/opportunity/test_calibration_outcomes.py
```

Expected: all tests and Ruff gates pass.

Commit:

```bash
git add backend/app/opportunity/calibration backend/tests/opportunity/test_calibration_outcomes.py
git commit -m "feat: add opportunity calibration outcomes"
```

---

### Task 2: Read-Only Loader and Data Quality Accounting

**Files:**
- Create: `backend/app/opportunity/calibration/loader.py`
- Modify: `backend/app/opportunity/calibration/models.py`
- Modify: `backend/app/opportunity/calibration/__init__.py`
- Create: `backend/tests/opportunity/test_calibration_loader.py`

**Interfaces:**
- Consumes: `CalibrationSample`, `RangeValue`.
- Produces: `CalibrationDataset(samples: tuple[CalibrationSample, ...], quality: Mapping[str, int], backend: str)`.
- Produces: `load_calibration_dataset(conn, *, model_version, profile_version) -> CalibrationDataset`.

- [ ] **Step 1: Write failing successful-linkage test**

Build an in-memory SQLite database through `init_db(conn)`, insert one complete
assessment JSON and one interaction explicitly linked to it, then assert the
loader returns one sample with parsed ranges and raw nullable outcome values.
Use `OpportunityAssessment.model_dump_json()` for valid fixture JSON rather
than hand-writing production snapshots.

- [ ] **Step 2: Run loader test to verify failure**

Run: `python -m pytest tests/opportunity/test_calibration_loader.py::test_loader_builds_explicit_assessment_cohort_sample -v`

Expected: import failure for `load_calibration_dataset`.

- [ ] **Step 3: Implement SELECT-only loading**

Issue exactly these categories of query:

```text
SELECT assessment_id, project_id, model_version, profile_version,
       assessment_json, scored_at
FROM opportunity_assessments

SELECT id, project_id, wallet_cohort_id, wallet_count,
       actual_hard_cost_usd, actual_time_minutes, eligibility_result,
       survival_result, reward_received_usd, claim_cost_usd,
       opportunity_assessment_id, opportunity_model_version,
       opportunity_profile_version, outcome_observed_at, outcome
FROM interactions
```

Join in Python so missing and mismatched links can be counted. Parse assessment
JSON with `OpportunityAssessment.model_validate_json`. Do not return raw rows.

- [ ] **Step 4: Write failing quality and duplicate tests**

Create independent rows for each required quality reason. Assert exact counts
for missing linkage, mismatched project, unsupported version, missing/invalid
cohort, malformed assessment JSON, invalid timestamp, and duplicate pair.
For a duplicate pair, assert neither row appears in `samples`.

Add a recording connection wrapper that captures SQL and assert every executed
statement begins with `SELECT` after leading whitespace.

- [ ] **Step 5: Run quality tests to verify failure**

Run: `python -m pytest tests/opportunity/test_calibration_loader.py -v`

Expected: failures for missing exclusion counters and read-only guarantees.

- [ ] **Step 6: Implement deterministic exclusions**

Sort valid samples by `(project_id, assessment_id, cohort_id)` before returning.
Quality dictionaries must contain all documented keys even when values are
zero. Never store excluded IDs in quality output.

- [ ] **Step 7: Verify and commit**

Run:

```powershell
python -m pytest tests/opportunity/test_calibration_loader.py tests/opportunity/test_calibration_outcomes.py -v
python -m ruff check app/opportunity/calibration tests/opportunity/test_calibration_loader.py
python -m ruff format --check app/opportunity/calibration tests/opportunity/test_calibration_loader.py
```

Commit:

```bash
git add backend/app/opportunity/calibration backend/tests/opportunity/test_calibration_loader.py
git commit -m "feat: load calibration samples read only"
```

---

### Task 3: Weighted Probability Metrics

**Files:**
- Create: `backend/app/opportunity/calibration/metrics.py`
- Modify: `backend/app/opportunity/calibration/models.py`
- Modify: `backend/app/opportunity/calibration/__init__.py`
- Create: `backend/tests/opportunity/test_calibration_metrics.py`

**Interfaces:**
- Produces: `BinaryObservation(project_id, predicted, actual)`.
- Produces: `sample_weights(observations, view) -> tuple[float, ...]` for `cohort_weighted` and `project_equal`.
- Produces: `probability_metrics(observations, *, view) -> Mapping[str, Any]`.

- [ ] **Step 1: Write failing hand-calculated probability tests**

Use observations `(0.1, 0)`, `(0.7, 1)`, `(0.8, 1)`, `(0.4, 0)` and assert:

```python
expected_brier = (0.01 + 0.09 + 0.04 + 0.16) / 4
expected_rate = 0.5
expected_mean_prediction = 0.5
```

Assert fixed bin boundaries, especially `0.1` entering the second bin and
`1.0` entering the last bin. Assert empty observations return null scores.

- [ ] **Step 2: Run tests to verify failure**

Run: `python -m pytest tests/opportunity/test_calibration_metrics.py -k probability -v`

Expected: import failure for `probability_metrics`.

- [ ] **Step 3: Implement weighted probability formulas**

Use weighted means for Brier, observed rate, prediction mean, ECE, and
sharpness. Climatology Brier uses the weighted observed rate as every
prediction. Skill is `1 - model_brier / climatology_brier`, or null when the
climatology score is zero.

- [ ] **Step 4: Write failing project-equal test**

Give project A nine identical cohorts and project B one cohort. Assert cohort
weighting is 9:1 while project-equal total weight is 1:1 and each A cohort has
weight `1/9`.

- [ ] **Step 5: Implement weights and observation builders**

Add pure builders that read only the base probability and mapped binary outcome
for each dimension. Missing prediction or outcome excludes only that dimension.

- [ ] **Step 6: Verify and commit**

Run: `python -m pytest tests/opportunity/test_calibration_metrics.py tests/opportunity/test_calibration_outcomes.py -v`

Then Ruff check/format the changed paths and commit:

```bash
git add backend/app/opportunity/calibration backend/tests/opportunity/test_calibration_metrics.py
git commit -m "feat: calculate probability calibration metrics"
```

---

### Task 4: Economic and Decision Metrics

**Files:**
- Modify: `backend/app/opportunity/calibration/metrics.py`
- Modify: `backend/app/opportunity/calibration/models.py`
- Create: `backend/tests/opportunity/test_calibration_economics.py`
- Create: `backend/tests/opportunity/test_calibration_decisions.py`

**Interfaces:**
- Produces: `NumericObservation(project_id, low, base, high, actual)`.
- Produces: `economic_metrics(observations, *, view) -> Mapping[str, Any]`.
- Produces: `decision_metrics(samples, outcomes, *, view) -> Mapping[str, Any]`.

- [ ] **Step 1: Write failing economic tests**

Use predictions `[10, 20, 30]` and `[0, 10, 20]` against actuals `25` and `-5`.
Assert MAE `10`, signed errors `5` and `-15`, RMSE
`sqrt((25 + 225) / 2)`, interval coverage `0.5`, and mean width `20`.
Assert inclusive boundaries count as covered.

- [ ] **Step 2: Implement weighted economic metrics**

Median uses deterministic sorted values; weighted views expand no samples.
Implement a weighted median helper. Reject non-finite inputs before metrics.

- [ ] **Step 3: Write failing decision tests**

Build one sample for each predicted label and realized class. Assert the full
3x3 matrix always contains all cells. Add FARM precision/recall, IGNORE
precision/recall, utility by label, downside rates, and adjacent mean-net
separation tests. A missing denominator returns null, not zero.

- [ ] **Step 4: Implement decision metrics without redefining WATCH**

Use only economically complete, non-contradictory samples. Do not emit a single
accuracy score. Keep confusion matrix ordering FARM/WATCH/IGNORE and
POSITIVE/NEUTRAL/NEGATIVE.

- [ ] **Step 5: Run all metric tests and commit**

Run all `test_calibration_*` metric/outcome files, then Ruff gates.

Commit:

```bash
git add backend/app/opportunity/calibration backend/tests/opportunity/test_calibration_economics.py backend/tests/opportunity/test_calibration_decisions.py
git commit -m "feat: measure opportunity economics and decisions"
```

---

### Task 5: Bootstrap, Gates, Segments, and Suggestions

**Files:**
- Create: `backend/app/opportunity/calibration/advice.py`
- Modify: `backend/app/opportunity/calibration/models.py`
- Modify: `backend/app/opportunity/calibration/__init__.py`
- Create: `backend/tests/opportunity/test_calibration_advice.py`

**Interfaces:**
- Produces: `cluster_bootstrap_interval(records, statistic, *, seed, replicates=1000) -> tuple[float, float] | None`.
- Produces: `gate_state(sample_count, project_count, *, segmented=False) -> str`.
- Produces: `segment_key(sample, segment_type) -> str`.
- Produces: `build_suggestions(window_report) -> tuple[Mapping[str, Any], ...]`.

- [ ] **Step 1: Write failing deterministic bootstrap tests**

Use three projects with multiple cohorts. Run the bootstrap twice with seed
`20260717` and assert identical intervals. Assert all cohorts from a selected
project move together by using a statistic that exposes split clusters.
Fewer than two projects returns null.

- [ ] **Step 2: Implement project-cluster bootstrap**

Use `random.Random(seed)`. Resample the sorted unique project list with
replacement and concatenate every record belonging to each selected project.
Use nearest-rank percentile indices for 2.5% and 97.5%, documented in code by
clear function names rather than prose comments.

- [ ] **Step 3: Write failing gate and segment tests**

Assert exact overall gates:

```python
assert gate_state(29, 30) == "data_quality_only"
assert gate_state(30, 30) == "descriptive"
assert gate_state(99, 30) == "descriptive"
assert gate_state(100, 29) == "descriptive"
assert gate_state(100, 30) == "advisory"
```

For segmented gates, require 30 samples and 10 projects. Assert wallet bands
`1-2`, `3-10`, `11+` and fixed status/label values.

- [ ] **Step 4: Implement gates and fixed segments**

Unknown status or label is a data-quality exclusion, not a dynamic segment.
Never segment by an identifier or free-text value.

- [ ] **Step 5: Write failing suggestion tests**

Create advisory reports where:

- Probability bias CI is wholly positive, yielding `direction=increase`.
- Probability bias CI crosses zero, yielding no suggestion.
- Economic signed-error CI is wholly negative, yielding `direction=decrease`.
- FARM-WATCH separation CI crosses zero, yielding `direction=review` for the
  decision threshold family.

Assert every suggestion includes bounded reason code, counts, versions,
window, evidence, and `auto_apply is False`. Assert descriptive and
data-quality gates produce no suggestions.

- [ ] **Step 6: Implement deterministic suggestions**

Suggestions describe observed gap and direction. Do not generate replacement
decision thresholds. Sort by `(scope, target, reason_code)`.

- [ ] **Step 7: Verify and commit**

Run advice tests plus all calibration unit tests and Ruff gates.

Commit:

```bash
git add backend/app/opportunity/calibration backend/tests/opportunity/test_calibration_advice.py
git commit -m "feat: generate guarded calibration advice"
```

---

### Task 6: Two-Window Report, Stable Rendering, and Atomic Output

**Files:**
- Create: `backend/app/opportunity/calibration/report.py`
- Modify: `backend/app/opportunity/calibration/__init__.py`
- Create: `backend/tests/opportunity/test_calibration_report.py`

**Interfaces:**
- Produces: `build_calibration_report(dataset, *, as_of, seed=20260717) -> Mapping[str, Any]`.
- Produces: `canonical_report_json(report) -> bytes`.
- Produces: `render_markdown(report) -> str`.
- Produces: `write_report_pair(report, output_dir) -> tuple[Path, Path]`.

- [ ] **Step 1: Write failing 90/180 window report test**

Use samples exactly 89, 90, 179, and 180 days old. Assert 90-day counts include
90/179/180 and 180-day counts include only 180. Assert maturity and unresolved
counts are present even when no dimension reaches a scoring gate.

- [ ] **Step 2: Implement window assembly**

For each window, map outcomes once, build all metrics in both views, build fixed
segments, calculate intervals, apply gates, then generate suggestions.
Report metadata uses schema `opportunity-calibration-v1`, fixed windows
`[90, 180]`, seed `20260717`, and replicates `1000`.

- [ ] **Step 3: Write failing determinism and privacy tests**

Build the report twice from reversed sample input order. Assert byte-identical
JSON and Markdown. Recursively inspect keys and values and assert none contains
known project, assessment, cohort, user, URL, note, or reason text fixture
values. Assert no NaN or Infinity appears.

- [ ] **Step 4: Implement canonical report ID and renderers**

Compute the hash from canonical JSON with `report_id` omitted, then insert
`report_id` and serialize the final report with sorted keys and a newline.
Markdown consumes only the finalized report dictionary and performs no metric
calculations.

- [ ] **Step 5: Write failing atomic output tests**

Assert successful output writes matching `.json` and `.md` names. Monkeypatch
Markdown rendering and `Path.replace` failures separately; assert no partial
final pair and no leaked temporary files.

- [ ] **Step 6: Implement atomic pair output**

Render both representations before creating final files. Write temporary files
in the destination directory, flush and close, then replace final paths. If the
second replace fails, restore or remove the first new final so a mixed pair is
not published.

- [ ] **Step 7: Verify and commit**

Run report tests plus all calibration unit tests and Ruff gates.

Commit:

```bash
git add backend/app/opportunity/calibration backend/tests/opportunity/test_calibration_report.py
git commit -m "feat: render opportunity calibration reports"
```

---

### Task 7: Operator CLI and Error Contract

**Files:**
- Create: `backend/scripts/calibrate_opportunity.py`
- Create: `backend/tests/scripts/test_calibrate_opportunity.py`

**Interfaces:**
- Consumes: loader and report APIs from Tasks 2 and 6.
- Produces: `parse_as_of(value: str) -> datetime`.
- Produces: `run_calibration(*, as_of, output_dir, database_url=None) -> tuple[Path, Path]`.
- Produces: `main(argv: Sequence[str] | None = None) -> int`.

- [ ] **Step 1: Write failing argument tests**

Assert missing `--as-of`, naive timestamps, invalid timestamps, and an output
path that is a file return non-zero. Assert `Z` and explicit offsets normalize
to UTC. Ensure captured output never contains a supplied database URL.

- [ ] **Step 2: Implement CLI parsing**

Use `argparse`. Required invocation:

```powershell
python scripts/calibrate_opportunity.py --as-of 2026-10-15T00:00:00Z --output-dir reports/opportunity-calibration
```

Optional `--database-url` temporarily overrides `settings.database_url` only
for the current process call and is restored in `finally`.

- [ ] **Step 3: Write failing successful CLI test**

Populate a temporary SQLite DB, invoke `main([...])`, assert exit `0`, exactly
two final files, stable rerun bytes, and output containing report paths plus
gate/sample summary but no database URL or row identifier.

- [ ] **Step 4: Implement orchestration and bounded errors**

Initialize existing schema, open one connection, load, close in `finally`,
build report, and write pair. Print only exception type and a bounded public
message on failure; do not print SQL parameters, URL, traceback, or row data.

- [ ] **Step 5: Verify and commit**

Run CLI tests, all calibration tests, and Ruff gates.

Commit:

```bash
git add backend/scripts/calibrate_opportunity.py backend/tests/scripts/test_calibrate_opportunity.py
git commit -m "feat: add opportunity calibration CLI"
```

---

### Task 8: SQLite/PostgreSQL Smoke Verifier and Operations Docs

**Files:**
- Create: `backend/scripts/verify_opportunity_calibration.py`
- Create: `backend/tests/scripts/test_verify_opportunity_calibration.py`
- Modify: `docs/OPERATIONS.md`
- Modify: `docs/IMPLEMENTATION_STATUS.md`

**Interfaces:**
- Produces: `run_verification(as_of: datetime) -> Mapping[str, Any]`.
- Preserves: no writes outside deterministic verifier fixture setup/cleanup; calibration production functions remain SELECT-only.

- [ ] **Step 1: Write failing verifier test**

Point settings to a temporary SQLite DB. The verifier creates synthetic
projects, assessments, and interactions covering mature probability, economics,
decision, duplicate, immature, and contradictory cases. Assert summary:

```python
{
    "backend": "sqlite",
    "json_stable": True,
    "markdown_stable": True,
    "privacy_safe": True,
    "production_select_only": True,
    "window_90d_samples": expected_90,
    "window_180d_samples": expected_180,
}
```

- [ ] **Step 2: Implement network-free verifier**

Use fixed IDs and fixed UTC timestamps. Fixture writes occur only in the
verifier; call the same production loader/report functions used by the CLI.
Clean fixture rows in `finally`.

- [ ] **Step 3: Add verifier CLI output test**

Assert sorted `key=value` output and final `RESULT: PASS`. On failure print only
`failure_type=<ClassName>` and `RESULT: FAIL`.

- [ ] **Step 4: Update operations documentation**

Document:

```powershell
cd backend
python scripts/calibrate_opportunity.py --as-of 2026-10-15T00:00:00Z --output-dir reports/opportunity-calibration
python scripts/verify_opportunity_calibration.py --as-of 2026-10-15T00:00:00Z
```

Document gate meanings, nested windows, project-equal recommendation basis,
privacy exclusions, no-auto-apply rule, and manual approval requiring a new
model/profile version.

Add PostgreSQL order after existing verifiers:

```powershell
$env:DATABASE_URL='postgresql://airdrop:airdrop_test@127.0.0.1:5433/airdrop_test'
python scripts/verify_postgres.py
python scripts/verify_opportunity_shadow.py
python scripts/verify_init_db_concurrency.py --database-url 'postgresql://airdrop:airdrop_test@127.0.0.1:5433/airdrop_test' --workers 4 --rounds 2
python scripts/verify_opportunity_calibration.py --as-of 2026-10-15T00:00:00Z
```

- [ ] **Step 5: Verify and commit**

Run verifier tests, SQLite verifier, docs diff check, and all calibration tests.

Commit:

```bash
git add backend/scripts/verify_opportunity_calibration.py backend/tests/scripts/test_verify_opportunity_calibration.py docs/OPERATIONS.md docs/IMPLEMENTATION_STATUS.md
git commit -m "docs: operationalize opportunity calibration"
```

---

### Task 9: Complete Verification and Delivery Review

**Files:**
- Verify only; fix only failures caused by Tasks 1-8 in their owning files.

**Interfaces:**
- Consumes all prior deliverables.
- Produces fresh evidence for correctness, determinism, privacy, both database backends, and unchanged application behavior.

- [ ] **Step 1: Run focused calibration suite**

Run from `backend`:

```powershell
python -m pytest tests/opportunity/test_calibration_outcomes.py tests/opportunity/test_calibration_loader.py tests/opportunity/test_calibration_metrics.py tests/opportunity/test_calibration_economics.py tests/opportunity/test_calibration_decisions.py tests/opportunity/test_calibration_advice.py tests/opportunity/test_calibration_report.py tests/scripts/test_calibrate_opportunity.py tests/scripts/test_verify_opportunity_calibration.py -v
```

Expected: all tests pass without warnings.

- [ ] **Step 2: Run unchanged Opportunity and interaction regressions**

Run:

```powershell
python -m pytest tests/opportunity tests/test_interactions.py tests/api/test_opportunity.py tests/test_pipeline_run.py -q
```

Expected: all pass; no assessment, interaction, or Shadow regression.

- [ ] **Step 3: Run Ruff and strict full backend suite**

Run:

```powershell
python -m ruff check .
python -m ruff format --check .
python -m pytest tests -q --cov=app --cov-report=term-missing --cov-fail-under=80 -W error::DeprecationWarning -W error::ResourceWarning -W error::pytest.PytestUnraisableExceptionWarning
```

Expected: Ruff passes, all files are formatted, all tests pass, and coverage is
at least 80%.

- [ ] **Step 4: Run frontend type checking**

Run `npx tsc --noEmit` from `frontend-next`.

Expected: exit code `0` with no errors.

- [ ] **Step 5: Run SQLite calibration smoke twice**

Run from `backend` with `DATABASE_URL` explicitly removed from the child
environment:

```powershell
python scripts/verify_opportunity_calibration.py --as-of 2026-10-15T00:00:00Z
python scripts/verify_opportunity_calibration.py --as-of 2026-10-15T00:00:00Z
```

Expected: both report `backend=sqlite`, identical report IDs, and
`RESULT: PASS`.

- [ ] **Step 6: Run PostgreSQL verifiers sequentially**

Run the four commands documented in Task 8 one at a time. Expected results in
order: `RESULT: OK`, Shadow `RESULT: PASS`, concurrency `RESULT: PASS`, and
calibration `backend=postgres` plus `RESULT: PASS`.

- [ ] **Step 7: Inspect privacy, writes, and final diff**

Run targeted searches proving report serializers do not emit internal IDs and
loader production SQL contains no INSERT/UPDATE/DELETE. Then run:

```powershell
git diff --check
git status --short
git log --oneline -15
```

Expected: only intended files, no generated reports, no secrets, and the
pre-existing local memory modification remains unstaged.

- [ ] **Step 8: Request whole-branch review**

Review sampling linkage, outcome mappings, maturity boundaries, project-equal
weights, formulas, bootstrap clustering, gates, suggestion governance,
determinism, privacy, read-only behavior, SQLite/PostgreSQL equivalence, and
operator docs. Fix every Critical or Important finding with a regression test
and a new commit; do not amend reviewed commits.
