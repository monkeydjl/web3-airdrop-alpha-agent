# Opportunity Action Workflow Design

## Goal

Turn the existing Opportunity v2 assessment into a deterministic, read-only
action workflow on the project detail page. The workflow must tell the user
what to do next, why that action is appropriate, what evidence supports it,
and how a small validation cohort can be recorded for later calibration.

Opportunity v2 remains an experimental Shadow path. The existing
`score-v1.4` label and decision remain the authoritative user-facing decision.
This release adds an action surface beside the legacy decision; it does not
replace, rewrite, or silently reinterpret the legacy score.

## Scope

The first release provides:

- A backend Action Workflow Projection assembled from the project, latest
  Opportunity assessment, evidence, participation tasks, and interactions.
- A read-only endpoint:
  `GET /api/v1/projects/{project_id}/opportunity/workflow`.
- A project-detail `OpportunityWorkflowPanel` placed before the existing
  `ParticipationTasks` section.
- A single prominent next action and a stable, expandable full action plan.
- Read-only evidence presentation with source, grade, freshness, verification
  state, and missing factor keys.
- Validation controls that reuse the existing `interactions` API and its
  `planned -> active -> done/abandoned` lifecycle.
- Assessment snapshot linkage on every validation interaction and automatic
  server-side generation of an anonymous `cohort-UUID4` identifier.
- Outcome fields that are already consumed by the calibration loader.

The first release does not provide:

- A new action, workflow, or wallet table.
- A separate Opportunity workbench or dashboard.
- Wallet connection, signing, transaction submission, automated farming, or
  wallet-address storage.
- Manual evidence entry, invalidation, superseding, or editing from the UI.
- LLM calls while building the projection.
- Automatic changes to scores, thresholds, profiles, model versions, or
  legacy labels.

## Existing Authority and Data Contracts

### Legacy decision

The project response remains the source of truth for the legacy decision:

- `project.score` and `project.label` are displayed as `score-v1.4`.
- The legacy label is always rendered, even when Opportunity data is missing,
  stale, blocked, or contradictory.
- The projection marks the legacy decision as `authoritative: true` and the
  Opportunity result as `shadow: true`.

### Opportunity assessment

The projection reads the latest persisted assessment for the default profile
(`low-cost-curated-multiwallet-v1`) using the existing repository ordering:
`scored_at DESC, created_at DESC, assessment_id DESC`.

The supported Opportunity model/profile pair is fixed to:

- model: `opportunity-v2.0`
- profile: `low-cost-curated-multiwallet-v1`

The assessment status values are the existing
`ACTIONABLE`, `MONITOR`, `INSUFFICIENT_EVIDENCE`, `BLOCKED`, and `NOT_FIT`.
The projection exposes the assessment ID, status, public label, recommended
action, reason-code arrays, confidence, score timestamps, and relevant
economic ranges without recalculating the assessment.

### Interactions

The workflow uses the existing interaction contract. No new persistence model
is introduced.

- Status: `planned`, `active`, `done`, `abandoned`.
- Eligibility: `unknown`, `eligible`, `ineligible`.
- Survival: `unknown`, `passed`, `disqualified`.
- Outcome: `pending`, `airdropped`, `not_airdropped`, `profit`, `loss`,
  `breakeven`, `unknown`.
- Validation linkage: `opportunity_assessment_id`,
  `opportunity_model_version`, and `opportunity_profile_version`.
- Outcome fields: `actual_hard_cost_usd`, `actual_time_minutes`,
  `eligibility_result`, `survival_result`, `reward_received_usd`,
  `claim_cost_usd`, and `outcome_observed_at`.

When the user starts validation, the client creates a `planned` interaction
with the current assessment ID. The server continues to generate the
anonymous `wallet_cohort_id` when it is omitted and validates the assessment
project/model/profile linkage. The client never asks for, sends, or displays a
wallet address, private key, seed phrase, or other sensitive identity.

## Architecture

### Projection service

Add a small deterministic projection service under `backend/app/opportunity`
with one public operation, conceptually:

```text
build_workflow(project_id, now) -> OpportunityWorkflowProjection
```

The service composes existing repositories/services only:

1. Load the project and legacy fields.
2. Load the latest persisted Opportunity assessment for the default profile.
3. Load evidence, including invalidated records for transparent read-only
   status display.
4. Load participation tasks from the existing deterministic generator.
5. Load the project interactions and select validation history linked to the
   current assessment.
6. Derive the workflow state, next action, action plan, blockers, upgrade
   conditions, evidence summary, and validation summary.

The service is pure with respect to application state: it performs no writes,
does not invoke an LLM, and does not create an assessment. Repeated calls with
the same database contents and `now` value return the same JSON ordering and
values.

### API endpoint

Add:

```text
GET /api/v1/projects/{project_id}/opportunity/workflow
```

Successful responses use the existing envelope. The `data` object contains:

```text
workflow_version: opportunity-action-workflow-v1
project_id
legacy: { model_version, score, label, authoritative }
opportunity: assessment summary or null
workflow: { state, next_action, action_plan, blockers, upgrade_conditions }
evidence: { items, missing_factor_keys, counts_by_grade }
validation: { current, history_summary, allowed_transitions }
review_at
expires_at
```

The `legacy` object reads `project.score`, `project.label`, and the existing
legacy reason fields without changing their meaning. The `opportunity` object
includes `shadow: true`, the assessment/profile/model IDs, status, public label,
recommended action, reason-code arrays, confidence, and score timestamps. It
may include the existing probability/economic ranges needed by the summary,
but it must not calculate a new assessment.

If the project does not exist, return the existing project-not-found 404
shape. If no Opportunity assessment exists, return 200 with `opportunity:
null`, `workflow.state: NEEDS_EVALUATION`, empty blockers/upgrade conditions,
and the legacy decision still populated.

## Workflow State Matrix

The state is derived in this exact order:

1. No latest assessment: `NEEDS_EVALUATION`.
2. `now >= review_at` or `now >= expires_at`: `REVIEW_REQUIRED`.
3. Otherwise, copy the assessment decision status:
   `ACTIONABLE`, `MONITOR`, `INSUFFICIENT_EVIDENCE`, `BLOCKED`, or `NOT_FIT`.

`REVIEW_REQUIRED` always wins over the assessment status. A stale assessment is
not silently treated as actionable.

CTA policy is deterministic:

- `NEEDS_EVALUATION`: show “运行 Opportunity 评估”; it invokes the existing
  evaluate flow, not the projection endpoint.
- `REVIEW_REQUIRED`: show “重新评估”; no validation CTA is offered.
- `ACTIONABLE`: show exactly one validation CTA. If an open linked
  interaction exists, the CTA is “继续验证”; otherwise it is “开始验证”.
- `MONITOR`: show monitoring/recheck guidance and upgrade conditions; do not
  offer validation start.
- `INSUFFICIENT_EVIDENCE`: show evidence-gap guidance and missing factor keys;
  do not offer validation start.
- `BLOCKED`: show the blocker and remediation condition; never provide an
  execution CTA.
- `NOT_FIT`: show the profile mismatch/negative-economics explanation; never
  provide an execution CTA.

The `next_action` object is always present and unique. An empty action plan is
allowed only when the state has no assessment or no generated participation
tasks; it must not create a second competing CTA.

## Action Plan Rules

The full plan is an ordered list of semantic actions. The backend does not
reorder it per request or locale. Sort by:

1. workflow phase (`review`, `evidence`, `validation`, `maintenance`,
   `outcome`),
2. numeric task priority when sourced from `participation-tasks`,
3. required before optional,
4. stable task/action ID.

The plan may include:

- review or re-evaluation,
- evidence verification,
- official participation tasks,
- one-to-two-wallet validation,
- recording actual cost/time and eventual outcome,
- reassessment before expanding the cohort.

Each item has `id`, `sequence`, `kind`, `title`, `description`, `required`,
`source`, and optional `task_id`/`external_url`. External URLs are included
only when they are absolute `http`/`https` URLs; the client renders them as
safe external links. The plan must not embed wallet addresses or arbitrary
free-form identifiers.

`blockers` are normalized objects containing a stable `code`, `severity`, and
human-readable `message`, sourced from assessment blocker/reason codes. They
are sorted by code. `upgrade_conditions` are similarly stable objects sourced
from watch reasons, critical unknowns, or missing factors; they describe what
new evidence or passage of time would change the state and never imply that a
blocked project is safe to execute.

## Evidence Projection

Evidence is display-only in this release. The panel may show:

- `evidence_id`, `factor_key`, normalized `value`, `value_type`, and
  `observation_type`,
- `source_url`, `source_type`, `source_grade`, and `verification_status`,
- `observed_at`, optional `effective_at`/`expires_at`, and deterministic
  freshness fields.

Items are sorted by `observed_at DESC`, then `evidence_id DESC`. Freshness is:

- `EXPIRED` when `expires_at` exists and `now >= expires_at`;
- `CURRENT` otherwise.

The projection also returns `age_days` as a non-negative integer derived from
`now - observed_at`, and always returns all five grade counters (`A`, `B`, `C`,
`D`, `U`). `missing_factor_keys` is the sorted `critical_unknowns` tuple stored
in the assessment's `factor_snapshot`; the projection does not infer new
unknowns or re-run the decision.

The UI has no create, invalidate, supersede, or edit evidence controls. Source
URLs remain subject to the existing source URL validator; the projection must
not expose raw snapshot references or other internal storage metadata.

## Validation Workflow and Calibration

The validation panel is a thin client over the existing interactions API.

### Start

When the state is `ACTIONABLE` and no open linked interaction exists, “开始验证”
creates:

- `status: planned`,
- `project_id`,
- `wallet_count: 1` or `2` (default 1),
- `opportunity_assessment_id` equal to the displayed assessment ID,
- matching model/profile versions.

The API generates `wallet_cohort_id` server-side. The UI displays only the
wallet count and the assessment timestamp, not the cohort ID.

### Record outcome

The panel can update the existing interaction with:

- `actual_hard_cost_usd`,
- `actual_time_minutes`,
- `eligibility_result`,
- `survival_result`,
- `reward_received_usd`,
- `claim_cost_usd`, and
- timezone-aware `outcome_observed_at`.

`disqualified` survival continues to require a non-empty reason at the API
boundary. The UI must never accept wallet addresses, private keys, seed
phrases, or sensitive identity in these fields.

After any create/update, the client refetches the projection. It does not
optimistically invent workflow state or assessment linkage.

### Selection and transitions

For the current assessment, `validation.current` selects the newest open
interaction (`planned` or `active`) by `created_at DESC, id DESC`; if none is
open, it selects the newest terminal interaction using the same order. The
history summary counts all linked interactions, while duplicate cohorts are
left to the existing calibration loader's duplicate policy.

The projection advertises the allowed lifecycle transitions:

- `planned -> active` or `abandoned`;
- `active -> done` or `abandoned`;
- `done` and `abandoned` are terminal.

The first release uses these transitions in the UI and does not introduce a
second state machine or a new interaction table.

## Frontend Structure

Add `OpportunityWorkflowPanel` to the project detail page before the existing
`ParticipationTasks` component. Its stable child structure is:

```text
OpportunityWorkflowPanel
├─ LegacyDecisionBadge
├─ OpportunityAssessmentSummary
├─ NextActionCard
├─ ActionPlanAccordion
├─ BlockerAndUpgradeConditions
├─ EvidenceSummary
└─ ValidationPanel
```

The legacy badge and Opportunity summary are rendered side by side where the
layout permits, but the legacy badge remains visually authoritative and the
Opportunity summary carries an explicit “Shadow / 实验性” label.

The component loads the projection once on mount and refetches after any
interaction mutation. Loading, 404, no-assessment, and projection-error
states each have explicit UI. On narrow screens the cards stack vertically;
the next action remains the first actionable element.

No existing `InteractionPanel` fields are removed in this release. The new
validation panel is a focused workflow surface and the legacy interaction
panel remains available for detailed historical editing.

## Error Handling and Compatibility

- Project not found: existing 404 envelope.
- No assessment: 200 with `NEEDS_EVALUATION`; never a 500 or an empty screen.
- Malformed persisted assessment/evidence: return a structured 500 with a
  stable workflow error code and log the project/assessment identifiers only;
  do not include raw evidence values in logs.
- Interaction create/update validation errors: surface the existing 4xx detail
  and leave the projection unchanged until the next successful refetch.
- SQLite and PostgreSQL must produce the same field names, ordering, null
  semantics, and transition matrix.

The endpoint is additive. Existing opportunity, evidence, participation-task,
interaction, and project endpoints remain backward compatible. No migration is
required because all persisted values already exist.

## Privacy and Safety Requirements

The implementation must preserve the existing interaction screening and add
workflow-level tests proving that:

- no wallet address, private key, seed phrase, or sensitive identity is stored
  or returned by the workflow endpoint;
- `wallet_cohort_id` is generated as an anonymous canonical `cohort-UUID4` and
  is not shown in the UI;
- source URLs are validated and never include userinfo, fragments, or sensitive
  query keys;
- raw snapshot references and arbitrary free-text notes are excluded from the
  evidence projection;
- links from participation tasks are limited to absolute `http`/`https` URLs.

## Testing and Acceptance Gates

### Backend

Add tests for:

- endpoint envelope and project-not-found behavior;
- no-assessment `NEEDS_EVALUATION` response;
- every state in the state matrix, including review/expiry precedence;
- deterministic next-action uniqueness and action-plan ordering;
- blocker and upgrade-condition mapping;
- evidence sorting, freshness, grade counts, missing factors, and safe source
  fields;
- interaction selection, assessment snapshot linkage, and allowed transitions;
- SQLite/PostgreSQL contract parity;
- privacy and sensitive-token rejection;
- calibration loader visibility of completed outcome fields.

### Frontend

Verify:

- TypeScript typecheck passes;
- the panel renders each backend state with a deterministic CTA policy;
- start/continue validation refreshes the projection;
- outcome fields round-trip without exposing a wallet address or cohort ID;
- the action accordion is stable and usable on desktop and mobile widths.

### Repository gates

The implementation is accepted only when the full pytest suite, Ruff, frontend
typecheck/build, and the existing Opportunity shadow/calibration verifiers
pass. Git changes are committed locally only; no remote push is part of this
work.

## Rollout and Observability

The endpoint and panel are additive and may be enabled with the existing
frontend deployment. Because Opportunity remains Shadow, log only aggregate
workflow state/CTA counts and projection errors. Do not log notes, evidence
values, wallet cohort IDs, or URLs with query parameters. Outcome records feed
the existing offline calibration loader; no online recalibration occurs.
