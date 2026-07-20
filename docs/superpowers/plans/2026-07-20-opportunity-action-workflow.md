# Opportunity Action Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a deterministic Opportunity Action Workflow Projection API and a project-detail validation panel while preserving `score-v1.4` as authoritative.

**Architecture:** Keep workflow derivation pure and read-only in `app.opportunity.workflow`, use a thin service to load project/assessment/evidence/tasks/interactions, expose one additive FastAPI endpoint, and render the projection through a focused Next.js panel. Validation writes continue through the existing interactions API and remain bound to an assessment snapshot.

**Tech Stack:** FastAPI, Pydantic, pytest, SQLite/PostgreSQL, Next.js, React, TypeScript, Tailwind CSS.

## Global Constraints

- `score-v1.4` and the existing project label remain authoritative; Opportunity v2 is explicitly Shadow and never overwrites legacy fields.
- Workflow projection is deterministic, read-only, idempotent, and must not call an LLM or create an assessment.
- Add `GET /api/v1/projects/{project_id}/opportunity/workflow`; do not add action/workflow/wallet tables.
- Reuse interaction statuses `planned`, `active`, `done`, `abandoned`; start validation with `planned` and bind the displayed assessment ID plus supported model/profile versions.
- The server generates anonymous canonical `cohort-UUID4` identifiers; never store, accept, return, or display wallet addresses, private keys, seed phrases, or sensitive identity.
- Evidence is read-only in the UI; do not add manual evidence entry, invalidation, superseding, or editing controls.
- Workflow states are `NEEDS_EVALUATION`, `REVIEW_REQUIRED`, `ACTIONABLE`, `MONITOR`, `INSUFFICIENT_EVIDENCE`, `BLOCKED`, and `NOT_FIT`. Apply no-assessment, review/expiry, then assessment-status precedence.
- Keep SQLite and PostgreSQL JSON field names, null semantics, ordering, and transition behavior identical.
- Git changes are local commits only; never push. Preserve unrelated user changes, especially `.workbuddy/memory/MEMORY.md` and `.claude/`.

---
## File Map

- Create `backend/app/opportunity/workflow.py`: immutable projection models and pure state/action/evidence/validation derivation.
- Create `backend/app/opportunity/workflow_service.py`: repository/DB orchestration that loads project, latest assessment, evidence, tasks, and interactions.
- Modify `backend/app/routers/v1/opportunity.py`: dependency wiring and the workflow GET route.
- Create `backend/tests/opportunity/test_workflow.py`: pure projection and state-matrix tests.
- Modify `backend/tests/api/test_opportunity.py`: endpoint, persistence, ordering, and privacy contract tests.
- Modify `backend/tests/test_interactions.py`: assessment linkage, transition, outcome-field, and cohort privacy coverage.
- Modify `backend/app/routers/v1/interactions.py`: only compatibility fixes required by the existing validation interaction contract.
- Modify `frontend-next/lib/types.ts`: projection and interaction request/response types.
- Create `frontend-next/components/OpportunityWorkflowPanel.tsx`: state badge, next action, plan, blockers, evidence, and validation controls.
- Modify `frontend-next/app/project/[id]/page.tsx`: load the panel after `AiBriefPanel` and before `ParticipationTasks`.
- Modify `frontend-next/package.json`: add `typecheck` script running `tsc --noEmit` if absent.
- Modify `frontend-next/README.md` only if the existing developer command list needs the new typecheck command documented.

Each task below ends with a focused test run and a local commit. Never stage `.workbuddy/memory/MEMORY.md` or `.claude/`.

## Task 1: Define the pure workflow projection contract

**Files:**
- Create: `backend/app/opportunity/workflow.py`
- Create: `backend/tests/opportunity/test_workflow.py`

**Interfaces:**
- `build_workflow_projection(*, project: Mapping[str, Any], assessment: OpportunityAssessment | None, evidence: Sequence[EvidenceRecord], participation_tasks: Sequence[Mapping[str, Any]], interactions: Sequence[Mapping[str, Any]], now: datetime) -> OpportunityWorkflowProjection`.
- `OpportunityWorkflowProjection` includes `workflow_version='opportunity-action-workflow-v1'`, `project_id`, `legacy`, `opportunity`, `workflow`, `evidence`, `validation`, `review_at`, and `expires_at`.
- `legacy` contains model version, score, label, reason fields, and `authoritative`; `opportunity` is the persisted assessment summary or null; `workflow` contains state, next action, action plan, blockers, and upgrade conditions; `evidence` contains items, missing factor keys, and all five grade counts.
- Use `DecisionStatus` and persisted `OpportunityAssessment` without recomputing scores. Keep `score-v1.4` explicit as the legacy model and `opportunity-v2.0` / `low-cost-curated-multiwallet-v1` explicit as the Shadow pair.
- Define `ALLOWED_TRANSITIONS = {'planned': ('active', 'abandoned'), 'active': ('done', 'abandoned'), 'done': (), 'abandoned': ()}` for later UI code.

- [ ] **Step 1: Write failing state and projection tests**

Create deterministic fixtures for a project, assessment, evidence, participation task, and interactions. Parameterize no assessment → `NEEDS_EVALUATION`; `now >= review_at` or `now >= expires_at` → `REVIEW_REQUIRED`; otherwise map each persisted `DecisionStatus` to the same workflow state. Assert legacy score/label remain untouched, `authoritative` is true, Opportunity is `shadow` true, and repeated calls with the same `now` serialize identically.

Add tests for `factor_snapshot['critical_unknowns']` becoming sorted `missing_factor_keys`, invalidated evidence remaining visible, deterministic `observed_at DESC, evidence_id DESC` ordering, `CURRENT`/`EXPIRED`, non-negative `age_days`, and grade counts containing `A/B/C/D/U` even when zero. Assert only `ACTIONABLE` exposes validation start.

Test that action plans sort by phase, task priority, required-first, and stable ID; blockers sort by code; upgrade conditions are stable; and exactly one next action exists. Test current validation selection as newest open interaction by `created_at DESC, id DESC`, falling back to newest terminal, with history counts covering all interactions linked to the current assessment.

- [ ] **Step 2: Run the focused tests and confirm failure**

Run: `cd backend; python -m pytest tests/opportunity/test_workflow.py -q`

Expected: FAIL because the projection module and builder do not exist yet.

- [ ] **Step 3: Implement the minimal pure models and builder**

Define frozen Pydantic models with explicit JSON-safe fields. Derive state in this exact order: no assessment; due review/expiry; persisted assessment status. Derive one next action and a stable ordered action plan from the assessment recommendation, `critical_unknowns`, and participation tasks. Do not call repositories, DB, LLMs, or assessment evaluation from this module.

Serialize evidence with ID, factor key, normalized value/type, observation type, safe source fields, grade, verification state, timestamps, freshness, and age. Never expose `raw_snapshot_ref` or arbitrary notes. Include validation transition metadata and the existing outcome field names without inventing a persistence model.

- [ ] **Step 4: Run the focused tests and confirm they pass**

Run: `cd backend; python -m pytest tests/opportunity/test_workflow.py -q`

Expected: PASS with all state, determinism, evidence, and validation-matrix tests green.

- [ ] **Step 5: Commit the pure projection unit**

Run: `git add backend/app/opportunity/workflow.py backend/tests/opportunity/test_workflow.py; git commit -m 'feat: add opportunity workflow projection'`

Expected: a new local commit containing only Task 1 files.

## Task 2: Add read-only service orchestration and API

**Files:**
- Create: `backend/app/opportunity/workflow_service.py`
- Modify: `backend/app/routers/v1/opportunity.py`
- Modify: `backend/tests/api/test_opportunity.py`

**Interfaces:**
- `OpportunityWorkflowService.get_project_workflow(project_id: str, now: datetime) -> OpportunityWorkflowProjection` loads `ProjectRepository.get_by_id`, `OpportunityRepository.latest_assessment(project_id, DEFAULT_PROFILE.profile_id)`, `list_evidence(project_id, include_invalid=True)`, `generate_participation_tasks(project)`, and project interactions.
- `get_opportunity_workflow_service()` is a FastAPI yield dependency that closes owned DB resources.
- `GET /projects/{project_id}/opportunity/workflow` returns the normal `{'ok': True, 'data': ...}` envelope and a structured `PROJECT_NOT_FOUND` 404.

- [ ] **Step 1: Write failing service/API contract tests**

Add endpoint tests for missing project, no assessment, latest-assessment ordering by `scored_at DESC, created_at DESC, assessment_id DESC`, review/expiry precedence with overridden `get_current_time`, inclusion of invalidated evidence, and selection of interactions linked to the current assessment only. Snapshot the response keys and assert it contains no `raw_snapshot_ref`, wallet address, private key, seed phrase, or unexpected identity fields.

Add malformed persisted-data coverage: return a structured 500 with stable code `OPPORTUNITY_WORKFLOW_PROJECTION_ERROR`, and use `caplog` to prove logs include only project/assessment identifiers plus aggregate state/CTA or error type. Logs must exclude evidence values, cohort IDs, notes, and source query strings. Assert projected evidence URLs obey the existing safe URL validator and participation links are absolute `http`/`https` URLs.

Record counts in `opportunity_assessments`, evidence, projects, and interactions before and after two identical GETs; assert counts and serialized data are unchanged. Monkeypatch evaluation/LLM entry points to raise if called.

Add a DB-adapter contract test using the repository’s existing SQLite/PostgreSQL fakes to prove identical field names, nulls, ordering, and interaction selection. Compare schema/table names before and after GET requests to prove no migration or workflow table is created.

- [ ] **Step 2: Run the API tests and confirm failure**

Run: `cd backend; python -m pytest tests/api/test_opportunity.py -q`

Expected: FAIL with the workflow route/service missing while existing opportunity tests remain green.

- [ ] **Step 3: Implement the thin orchestration layer and route**

Open one repository-owned connection per request, instantiate `ProjectRepository` and `OpportunityRepository` against it, and query interactions with parameterized SQL using the existing DB abstraction and `dict_from_row`. Order validation history deterministically by newest creation timestamp and ID, then pass plain mappings to `build_workflow_projection`. Extract the existing deterministic participation task list from `generate_participation_tasks(project)`.

The service raises `LookupError` for a missing project and never invokes `OpportunityService.evaluate`. The router translates that error to the existing structured 404 and returns `projection.model_dump(mode='json')`. Reuse `get_current_time` so tests can freeze time.

Catch malformed persisted projection inputs at the route boundary, emit bounded structured logging, and return `OPPORTUNITY_WORKFLOW_PROJECTION_ERROR` without raw values. On successful projections log/count only the workflow state and CTA key; do not log notes, evidence values, cohort IDs, or URLs with query parameters.

- [ ] **Step 4: Run focused and adjacent backend tests**

Run: `cd backend; python -m pytest tests/opportunity/test_workflow.py tests/api/test_opportunity.py -q`

Expected: PASS; repeated GET tests prove read-only/idempotent behavior and response privacy.

- [ ] **Step 5: Run backend static checks for the unit**

Run: `cd backend; python -m ruff check app/opportunity/workflow.py app/opportunity/workflow_service.py app/routers/v1/opportunity.py tests/opportunity/test_workflow.py tests/api/test_opportunity.py`

Expected: exit 0 with no Ruff diagnostics.

- [ ] **Step 6: Commit the service and API unit**

Run: `git add backend/app/opportunity/workflow_service.py backend/app/routers/v1/opportunity.py backend/tests/api/test_opportunity.py; git commit -m 'feat: expose opportunity workflow API'`

Expected: a local commit containing only Task 2 files.

## Task 3: Harden interaction snapshot, transition, and privacy contracts

**Files:**
- Modify: `backend/app/routers/v1/interactions.py` only where existing behavior does not satisfy the approved contract
- Modify: `backend/tests/test_interactions.py`

**Interfaces:**
- Keep `StatusType = Literal['planned', 'active', 'done', 'abandoned']`, `EligibilityResult`, `SurvivalResult`, `OpportunityModelVersion`, and `OpportunityProfileVersion` unchanged.
- `POST /interactions` accepts `status='planned'`, `opportunity_assessment_id`, `opportunity_model_version='opportunity-v2.0'`, and `opportunity_profile_version='low-cost-curated-multiwallet-v1'`; omitted `wallet_cohort_id` is generated server-side in canonical `cohort-UUID4` form.
- Preserve the existing outcome fields: `actual_hard_cost_usd`, `actual_time_minutes`, `eligibility_result`, `survival_result`, `reward_received_usd`, `claim_cost_usd`, and `outcome_observed_at`.

- [ ] **Step 1: Write failing lifecycle and privacy tests**

Test that a planned interaction linked to the current assessment is accepted and returns the linkage/model/profile, while a project/model/profile mismatch returns 422. Test allowed transitions `planned -> active|abandoned` and `active -> done|abandoned`, and reject every transition out of `done` or `abandoned`.

Test all outcome fields round-trip through POST/PATCH and that `survival_result='disqualified'` requires a reason. Assert omitted cohorts match `^cohort-[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$`; reject supplied wallet-shaped values and never return wallet addresses or secret material.

- [ ] **Step 2: Run interaction tests and confirm the red cases**

Run: `cd backend; python -m pytest tests/test_interactions.py -q`

Expected: existing tests pass and new lifecycle/privacy assertions fail only where the current implementation lacks the specified transition or snapshot behavior.

- [ ] **Step 3: Implement the smallest compatible contract fix**

Reuse the current Pydantic validators, `_canonical_assessment_linkage`, and generated cohort logic. Add only missing transition validation or response filtering; do not create tables, accept wallet addresses, change calibration field names, or alter legacy interaction semantics unrelated to this workflow.

- [ ] **Step 4: Run interaction and calibration regression tests**

Run: `cd backend; python -m pytest tests/test_interactions.py tests/opportunity/test_calibration_loader.py -q`

Expected: PASS with lifecycle, outcome, linkage, cohort, and calibration-loader tests green.

- [ ] **Step 5: Commit the interaction contract unit**

Run: `git add backend/app/routers/v1/interactions.py backend/tests/test_interactions.py; git commit -m 'fix: enforce opportunity validation interaction contract'`

Expected: a local commit containing only Task 3 files.

## Task 4: Build the project-detail workflow panel

**Files:**
- Modify: `frontend-next/lib/types.ts`
- Create: `frontend-next/components/OpportunityWorkflowPanel.tsx`
- Modify: `frontend-next/package.json`

**Interfaces:**
- Export TypeScript unions matching backend states and interaction statuses exactly.
- Export `OpportunityWorkflowProjection` with the exact nested backend JSON names: `legacy.authoritative`, nullable `opportunity.shadow`, `workflow`, `evidence`, `validation`, `review_at`, and `expires_at`.
- `OpportunityWorkflowPanel({ projectId }: { projectId: string })` loads `/projects/${projectId}/opportunity/workflow` using `apiFetch`, and after every interaction mutation re-fetches the projection.

- [ ] **Step 1: Add a compile-contract assertion and run it red**

In the new component file, first import the planned workflow type names from `lib/types` and add a `satisfies OpportunityWorkflowProjection` compile assertion covering every state, nullable opportunity assessment, evidence summary, validation transitions, and all outcome field names. Add the `typecheck` script to `frontend-next/package.json` but do not add the exports to `types.ts` yet.

Run: `cd frontend-next; npm run typecheck`

Expected: FAIL because the workflow type exports do not exist yet.

- [ ] **Step 2: Add the exact types and implement the panel against them**

Render, in order, `LegacyDecisionBadge`, `OpportunityAssessmentSummary`, `NextActionCard`, expandable `ActionPlanAccordion`, blockers/upgrade conditions, `EvidenceSummary`, and `ValidationPanel`. Always show the legacy label as authoritative and label Opportunity as Shadow/experimental. Show one primary action; only `ACTIONABLE` can start validation. If a current interaction is `planned` or `active`, show “继续验证”; otherwise show “开始验证”.

For `NEEDS_EVALUATION`, the primary action calls the existing Opportunity evaluate endpoint and then reloads the projection; `REVIEW_REQUIRED` uses the same existing re-evaluation flow. `MONITOR`, `INSUFFICIENT_EVIDENCE`, `BLOCKED`, and `NOT_FIT` show guidance only and never expose a validation-start control.

Starting validation posts a `planned` interaction with `project_id`, `wallet_count` selected as 1 or 2 with default 1, current `opportunity_assessment_id`, supported model/profile versions, and no wallet identity fields. Lifecycle buttons call the existing PATCH endpoint only for allowed transitions. Display wallet count and assessment timestamp, but never display `wallet_cohort_id`. Keep loading/error/empty states accessible, avoid wallet connection/signing/transactions, and do not render raw snapshot references or sensitive identity.

For an active validation, expose compact outcome inputs for the seven approved fields only. Send numbers as numbers, preserve nullable values, require a disqualification reason when applicable, and re-fetch the projection after save. Never ask for a wallet address or free-form secret-bearing identity.

- [ ] **Step 3: Run typecheck and build**

Run: `cd frontend-next; npm run typecheck; npm run build`

Expected: TypeScript exits 0 and Next.js production build completes without route or client-component errors.

- [ ] **Step 4: Commit the frontend panel unit**

Run: `git add frontend-next/lib/types.ts frontend-next/components/OpportunityWorkflowPanel.tsx frontend-next/package.json; git commit -m 'feat: add opportunity workflow panel'`

Expected: a local commit containing only Task 4 files.

## Task 5: Integrate the panel and run release verification

**Files:**
- Modify: `frontend-next/app/project/[id]/page.tsx`
- Modify: `frontend-next/README.md` only if needed for the new command

**Interfaces:**
- Import `OpportunityWorkflowPanel` and render `<OpportunityWorkflowPanel projectId={project.id} />` immediately after `<AiBriefPanel ... />` and immediately before `<ParticipationTasks ... />`.
- Do not add a route, dashboard, wallet provider, or global state store.

- [ ] **Step 1: Prove the placement check is red**

Run: `rg -n 'AiBriefPanel|OpportunityWorkflowPanel|ParticipationTasks' frontend-next/app/project/[id]/page.tsx`

Expected: FAIL because `OpportunityWorkflowPanel` is not yet imported/rendered.

- [ ] **Step 2: Add the page import and component placement**

Add one import beside the existing panel imports and one JSX element between `AiBriefPanel` and `ParticipationTasks`. Preserve all current project reload, scoring, funding, and interaction behavior.

- [ ] **Step 3: Re-run placement, type, and build checks**

Run the same placement assertion as Step 1.

Expected: exit 0.

Run: `cd frontend-next; npm run typecheck; npm run build`

Expected: both commands exit 0.

Open the built page at a desktop width and a narrow mobile width with fixtures for `NEEDS_EVALUATION`, `REVIEW_REQUIRED`, `ACTIONABLE` with and without an open validation, `MONITOR`, `INSUFFICIENT_EVIDENCE`, `BLOCKED`, and `NOT_FIT`. Confirm one deterministic CTA, stable accordion ordering, stacked mobile cards, projection refetch after create/update, no cohort ID, and no wallet/secret fields.

- [ ] **Step 4: Commit page integration**

Run: `git add frontend-next/app/project/[id]/page.tsx frontend-next/README.md; git commit -m 'feat: integrate opportunity workflow on project detail'`

Expected: a local commit with the page integration and README only when it actually changed.

## Final verification and handoff

- [ ] Run backend unit, API, interaction, and opportunity regression suites.

Run: `cd backend; python -m pytest -q`

Expected: exit 0 with zero failures and zero errors.

- [ ] Run backend lint and compile checks.

Run: `cd backend; python -m ruff check app tests; python -m compileall -q app`

Expected: both commands exit 0.

- [ ] Run frontend verification.

Run: `cd frontend-next; npm run typecheck; npm run build`

Expected: both commands exit 0.

- [ ] Run existing Opportunity release verifiers without changing persisted production data.

Run: `cd backend; python scripts/verify_opportunity_shadow.py; python scripts/verify_opportunity_calibration.py`

Expected: each script ends with `RESULT: PASS`; legacy score/label remain unchanged and calibration output stays privacy-safe and deterministic.

- [ ] Audit the implementation against the spec before declaring completion.

Run: `git diff --check -- backend frontend-next docs/superpowers`; `git status --short`

Expected: no feature-file whitespace errors, and only intended feature commits plus the pre-existing user files `.workbuddy/memory/MEMORY.md` and `.claude/` visible in status.

Review manually that every spec section is covered: legacy authority, Shadow labeling, state precedence, deterministic projection, evidence privacy, assessment linkage, cohort generation, transition matrix, outcome fields, UI placement, no wallet/LLM/assessment writes, and no new tables. Confirm all commits are local with `git log --oneline -6`; do not run `git push`.
