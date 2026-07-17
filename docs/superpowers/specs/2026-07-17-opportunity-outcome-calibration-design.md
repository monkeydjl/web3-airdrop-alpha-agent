# Opportunity Outcome Calibration Design

## Goal

Build a read-only, offline calibration workflow for `opportunity-v2.0` that
evaluates probability reliability, economic forecast error, and decision
quality from realized cohort outcomes. The workflow produces evidence-backed
adjustment suggestions for human review, but never changes assessments,
projects, profiles, thresholds, configuration, or model versions.

## Scope

The first release provides:

- A pure calibration and reporting module under `app.opportunity`.
- A read-only loader joining immutable Opportunity assessments to interaction
  outcomes through the explicit assessment ID and anonymous wallet cohort ID.
- A CLI that writes deterministic, versioned JSON and Markdown reports.
- A 90-day primary maturity window and a 180-day long-horizon slice.
- Cohort-weighted and project-equal views, with project-equal metrics governing
  recommendations.
- Sample gates that prevent small datasets from producing parameter advice.

The first release does not provide:

- Automatic model, profile, probability, or threshold updates.
- A calibration database table, runtime API, scheduler, or frontend page.
- Wallet-level records, project-level report rows, or sensitive free text.
- A replacement for the legacy `score-v1.4` decision path.
- Calibration across unsupported model or profile versions.

## Existing Data Contract

The workflow uses existing append-only `opportunity_assessments` snapshots and
existing `interactions` outcome fields. No schema migration is required.

An interaction is linked to a prediction only when all of these values match:

- `interactions.opportunity_assessment_id` identifies an existing assessment.
- The interaction and assessment have the same `project_id`.
- `opportunity_model_version` is `opportunity-v2.0`.
- `opportunity_profile_version` is
  `low-cost-curated-multiwallet-v1`.
- `wallet_cohort_id` is present and is already validated by the interaction
  API as a canonical anonymous cohort UUID.

The loader reads the raw nullable database columns. It must not use API
response convenience values such as `realized_net_usd` when those values turn
missing components into zero.

## Calibration Unit and Duplicate Policy

The base statistical unit is one unique
`(opportunity_assessment_id, wallet_cohort_id)` pair. One project may have
multiple cohorts, but repeated interactions for the same assessment and cohort
are not independent observations.

If more than one interaction row exists for the same assessment and cohort,
all rows for that pair are excluded. The report records the pair under
`duplicate_assessment_cohort`. The loader does not silently choose the latest
row or merge partial rows because either behavior could manufacture an outcome
that was never recorded atomically.

## Time and Maturity Rules

The CLI requires an explicit timezone-aware `--as-of` timestamp. Requiring the
timestamp makes repeated runs over the same database snapshot deterministic.

A linked interaction is eligible for a window when:

- `assessment.scored_at` and `interaction.outcome_observed_at` are valid,
  timezone-aware timestamps.
- `assessment.scored_at <= outcome_observed_at <= as_of`.
- The elapsed time from `scored_at` to `outcome_observed_at` is at least the
  window length.

The primary report uses 90 days. The long-horizon slice uses 180 days. A
180-day sample is also part of the 90-day population; the two sections are
nested views, not mutually exclusive datasets.

Records that are linked but not old enough remain in coverage and maturity
counts. They do not contribute to calibration scores. Records with future or
reversed timestamps are excluded as data quality errors.

## Dimension-Specific Outcome Mapping

Maturity determines whether a sample may be considered. Each metric dimension
then has its own completeness rules. Missing data in one dimension must not
remove valid evidence from another dimension.

### Event Outcome

Event probability is scored only from an explicit terminal event label:

- `outcome = airdropped` maps to `1`.
- `outcome = not_airdropped` maps to `0`.
- `pending`, `unknown`, `profit`, `loss`, `breakeven`, and null are unresolved
  for event probability.

Economic labels do not implicitly prove that a distribution event occurred.

### Eligibility Outcome

- `eligibility_result = eligible` maps to `1`.
- `eligibility_result = ineligible` maps to `0`.
- `unknown` and null are unresolved.

### Survival Outcome

- `survival_result = passed` maps to `1`.
- `survival_result = disqualified` maps to `0`.
- `unknown` and null are unresolved.

### Reward Outcome

Reward realization maps to `1` when `reward_received_usd > 0`.
It maps to `0` when at least one explicit no-reward condition exists:

- `reward_received_usd = 0`.
- `outcome = not_airdropped`.
- `eligibility_result = ineligible`.
- `survival_result = disqualified`.

If a positive reward conflicts with any explicit no-reward condition, reward
and decision metrics exclude the sample as `contradictory_outcome`.

### Economic Outcome

Net economic error requires all three raw values:

- `reward_received_usd`.
- `actual_hard_cost_usd`.
- `claim_cost_usd`.

The realized value is:

```text
realized_net_usd = reward_received_usd
                   - actual_hard_cost_usd
                   - claim_cost_usd
```

It is compared directly with `assessment.economics.net_reward`. The v1 report
does not rescale predictions by wallet count. It reports wallet count bands so
profile mismatch is visible instead of hidden by an unvalidated scaling rule.

Hard-cost error compares `actual_hard_cost_usd` with
`assessment.hard_cost_usd`. Claim cost remains part of realized net but is
reported separately because the current assessment has no claim-cost range.

Time error requires `actual_time_minutes` and compares
`actual_time_minutes / 60` with `assessment.total_time_hours`.

### Realized Decision Class

Decision quality uses only economically complete, non-contradictory samples:

- `POSITIVE`: eligible, passed, and `realized_net_usd > 0`.
- `NEGATIVE`: ineligible, disqualified, or `realized_net_usd < 0`.
- `NEUTRAL`: eligible, passed, and `realized_net_usd = 0`.

This class is an evaluation target, not a replacement public label. The report
compares predicted `FARM`, `WATCH`, and `IGNORE` with these three realized
classes and separately reports realized utility by predicted label.

## Probability Metrics

Each available probability dimension is scored independently using the base
probability from its stored range:

- `event_probability.base`.
- `eligibility_probability.base`.
- `survival_probability.base`.
- `reward_probability.base`.

For each dimension and aggregation view, the report provides:

- Sample count and unique project count.
- Observed positive rate and mean predicted probability.
- Brier score.
- Climatology Brier score using the observed base rate.
- Brier skill score when the climatology score is non-zero.
- Signed calibration bias: observed rate minus mean prediction.
- Ten fixed reliability bins: `[0.0, 0.1)`, ..., `[0.9, 1.0]`.
- Expected calibration error, weighted by sample weight.
- Sharpness as weighted population variance of predicted probabilities.
- Coverage relative to all mature linked samples in the window.

Empty dimensions return counts and `null` metrics; they never produce zero
scores that could be mistaken for perfect calibration.

## Economic Metrics

For net reward, hard cost, and total time, the report provides:

- Sample count and unique project count.
- Mean absolute error against the prediction base.
- Mean signed error `actual - predicted`.
- Median signed error.
- Root mean squared error.
- Prediction interval coverage using inclusive low/high boundaries.
- Mean prediction interval width.
- Mean and median realized values.

Net reward additionally reports downside rate (`realized_net_usd < 0`) and
positive-net rate. Claim cost reports descriptive actual values only.

## Decision Metrics

The decision section provides:

- A `FARM/WATCH/IGNORE` by `POSITIVE/NEUTRAL/NEGATIVE` confusion matrix.
- FARM precision and recall for `POSITIVE` outcomes.
- IGNORE precision and recall for `NEGATIVE` outcomes.
- Mean and median realized net by predicted public label.
- Positive, neutral, negative, ineligible, disqualified, and downside rates by
  predicted public label.
- Adjacent-label utility separation: FARM minus WATCH and WATCH minus IGNORE.

Decision metrics do not call WATCH a correct or incorrect label by definition.
They show whether the ordered policy separates realized utility.

## Aggregation and Correlation Control

Every metric section contains two views:

- `cohort_weighted`: every assessment-cohort sample has weight `1`.
- `project_equal`: every project has total weight `1`; each of its eligible
  cohorts receives weight `1 / eligible_cohort_count_for_project`.

Recommendation gates and recommendation evidence use `project_equal` metrics.
This prevents a single heavily tracked project from dominating calibration.

Fixed low-cardinality segments are:

- Predicted public label: FARM, WATCH, IGNORE.
- Decision status: ACTIONABLE, MONITOR, INSUFFICIENT_EVIDENCE, NOT_FIT,
  BLOCKED.
- Wallet count band: `1-2`, `3-10`, `11+`.

The report never groups by project ID, assessment ID, cohort ID, URL, note, or
disqualification text.

## Statistical Uncertainty

The report includes deterministic 95% confidence intervals generated by a
project-cluster bootstrap:

- Resample projects with replacement.
- Include all eligible cohorts belonging to each sampled project.
- Use 1,000 replicates.
- Use a fixed seed recorded in report metadata.
- Return percentile intervals.

Bootstrap intervals are produced for calibration bias, mean signed economic
error, label-level mean realized net, and adjacent-label utility separation.
When fewer than two projects are available, the interval is `null`.

## Sample Gates

Gates apply separately to each maturity window and metric dimension:

- Fewer than 30 valid samples: `data_quality_only`. Report coverage and
  exclusions, but suppress scored interpretation and suggestions.
- 30 to 99 valid samples: `descriptive`. Report metrics and uncertainty, but
  suppress global adjustment suggestions.
- At least 100 valid samples and at least 30 unique projects: `advisory`.
  Global suggestions may be emitted.

A segmented suggestion additionally requires at least 30 valid samples and at
least 10 unique projects in that segment. These gates do not imply statistical
significance; confidence intervals remain mandatory evidence.

## Suggestion Rules and Governance

Suggestions are deterministic candidate changes for human review. Each item
contains:

- `scope`: overall or a fixed segment.
- `target`: probability dimension, economic estimate, or decision threshold
  family.
- `direction`: increase, decrease, widen, narrow, tighten, loosen, or review.
- `observed_gap` and 95% confidence interval.
- Sample count, unique project count, maturity window, model version, and
  profile version.
- A bounded reason code and a plain-language explanation.
- `auto_apply: false`.

Probability suggestions are emitted only when calibration-bias confidence
intervals exclude zero. The observed bias is evidence for the direction; the
report does not mutate stored probability ranges.

Economic suggestions are emitted only when signed-error confidence intervals
exclude zero. Interval-width review is suggested when empirical interval
coverage is below the nominal interpretation of the stored low/high range;
the report describes observed coverage and does not invent a confidence level
that the model does not currently define.

Decision-threshold review is suggested when adjacent-label utility separation
is non-positive or its confidence interval includes zero. The suggestion names
the threshold family to review but does not generate a replacement threshold,
because acceptable false-positive and downside tolerances require a separate
governance decision.

Applying any suggestion requires a separately approved change that creates a
new model or profile version and reruns Shadow validation. Editing
`opportunity-v2.0` or `low-cost-curated-multiwallet-v1` in place is forbidden.

## Data Quality Report

The report exposes counts for at least:

- Total assessments.
- Total interactions.
- Linked assessment-cohort pairs.
- Missing assessment linkage.
- Assessment/project mismatch.
- Unsupported model or profile version.
- Missing or invalid cohort ID.
- Duplicate assessment-cohort pairs.
- Missing or invalid timestamps.
- Outcome before assessment.
- Outcome after `as_of`.
- Immature at 90 days.
- Immature at 180 days.
- Contradictory outcomes.
- Dimension-specific resolved and unresolved counts.

No excluded row content or identifier appears in the report.

## CLI Contract

The command is:

```text
python scripts/calibrate_opportunity.py \
  --as-of 2026-10-15T00:00:00Z \
  --output-dir reports/opportunity-calibration
```

The CLI uses the application's configured database backend. It accepts an
explicit `--database-url` override for verifier and operator use, but never
prints the URL. It does not inspect `.env` directly.

Required behavior:

- `--as-of` is mandatory and timezone-aware.
- `--output-dir` must not be an existing file.
- The command performs SELECT queries only.
- JSON and Markdown are written atomically using temporary files and replace.
- Existing output files for the same report ID are replaced only after both
  new representations render successfully.
- Exit code `0` means the reports were written, including data-quality-only
  reports.
- Invalid arguments, database errors, schema errors, and output errors return
  non-zero without partial final files.

The filenames contain a stable report ID derived from report schema version,
model version, profile version, `as_of`, and a canonical hash of the aggregate
report content. The same database snapshot and arguments produce identical
JSON bytes and Markdown content.

## JSON Report Schema

The top-level schema version is `opportunity-calibration-v1`. The report
contains:

- `metadata`: schema version, model/profile versions, `as_of`, windows,
  bootstrap seed/replicates, database backend, and report ID.
- `data_quality`: aggregate inclusion, exclusion, maturity, and coverage
  counts.
- `windows.90d` and `windows.180d`.
- Within each window: gate state, cohort-weighted metrics, project-equal
  metrics, fixed segments, and suggestions.

Numeric outputs are finite JSON numbers or `null`. NaN and infinity are
forbidden. Dictionary keys and list ordering are stable. JSON uses UTF-8,
sorted keys, and a final newline.

The Markdown report is a deterministic rendering of the JSON report and
contains no additional calculations.

## Privacy and Security

- Reports contain no project IDs, assessment IDs, cohort IDs, user IDs, URLs,
  notes, activities, or disqualification reasons.
- SQL values are parameterized.
- Database URLs and credentials are never logged or written to reports.
- The loader does not expose raw assessment snapshots outside the process.
- Output directories follow normal filesystem permissions; the CLI does not
  upload or transmit reports.

## Failure Handling

- Malformed individual rows are counted and excluded when the error is local
  to that row.
- Missing required tables or columns is a fatal schema error.
- Unsupported report schema, model version, or profile version is fatal.
- A metric with no valid data returns a structured empty result, not a fatal
  error.
- Suggestion generation failure is fatal because a partially trustworthy
  report must not be published.
- Temporary output files are removed on failure where possible.

## Testing

Pure unit tests use hand-calculated synthetic samples for:

- Event, eligibility, survival, and reward mappings.
- Contradiction and partial-dimension handling.
- Brier, climatology, skill, bias, reliability bins, ECE, and sharpness.
- Economic errors and inclusive interval coverage.
- Decision confusion matrix and utility separation.
- Cohort-weighted versus project-equal behavior.
- 90-day and 180-day maturity boundaries.
- 30/100 sample gates and segment gates.
- Deterministic project-cluster bootstrap intervals.
- Deterministic suggestion rules.

Loader and CLI tests cover:

- SQLite and PostgreSQL-equivalent query behavior.
- Read-only SQL behavior.
- Duplicate, missing-link, unsupported-version, and malformed-row exclusions.
- Stable JSON and Markdown snapshots.
- Atomic output and cleanup after rendering or filesystem failure.
- No identifier or credential leakage.

Final validation includes Ruff check and format, the strict backend suite,
SQLite calibration smoke, PostgreSQL calibration smoke run sequentially after
existing PostgreSQL verifiers, frontend TypeScript checking, and
`git diff --check`.

## Acceptance Criteria

- The same snapshot and arguments produce byte-identical JSON and Markdown.
- No command path writes to application database tables.
- Metrics use only explicitly linked, mature, dimension-complete data.
- 90-day and 180-day reports obey their fixed boundaries.
- Project-equal metrics prevent multi-cohort projects from dominating advice.
- Small samples cannot produce adjustment suggestions.
- Suggestions are evidence-backed, bounded, non-authoritative, and never
  automatically applied.
- Reports contain no row-level identifiers or sensitive text.
- SQLite and PostgreSQL produce equivalent aggregate reports.
- Existing Opportunity, legacy score, API, scheduler, and Shadow behavior
  remain unchanged.
