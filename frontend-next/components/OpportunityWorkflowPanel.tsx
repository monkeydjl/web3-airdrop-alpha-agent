'use client';

import { apiFetch } from '@/lib/api';
import { labelZh } from '@/lib/format';
import type {
  EligibilityResult,
  InteractionStatus,
  OpportunityModelVersion,
  OpportunityProfileVersion,
  OpportunityWorkflowProjection,
  SurvivalResult,
  ValidationCurrent,
  WorkflowState,
} from '@/lib/types';
import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';

/**
 * Compile-time contract fixture: fails typecheck until workflow types exist
 * and remain aligned with the backend projection JSON shape.
 */
const WORKFLOW_STATES = [
  'NEEDS_EVALUATION',
  'REVIEW_REQUIRED',
  'ACTIONABLE',
  'MONITOR',
  'INSUFFICIENT_EVIDENCE',
  'BLOCKED',
  'NOT_FIT',
] as const satisfies readonly WorkflowState[];

const INTERACTION_STATUSES = [
  'planned',
  'active',
  'done',
  'abandoned',
] as const satisfies readonly InteractionStatus[];

const _OUTCOME_FIELDS = {
  actual_hard_cost_usd: 12.5 as number | null,
  actual_time_minutes: 45 as number | null,
  eligibility_result: 'eligible' as 'unknown' | 'eligible' | 'ineligible' | null,
  survival_result: 'passed' as 'unknown' | 'passed' | 'disqualified' | null,
  disqualification_reason: null as string | null,
  reward_received_usd: 0 as number | null,
  claim_cost_usd: null as number | null,
  outcome_observed_at: '2026-07-20T12:00:00+00:00' as string | null,
};

const _BASE_PROJECTION = {
  workflow_version: 'opportunity-action-workflow-v1' as const,
  project_id: 'proj-demo',
  legacy: {
    model_version: 'score-v1.4' as const,
    score: 72,
    label: 'WATCH',
    reason: ['demo'],
    authoritative: true as const,
  },
  opportunity: null as OpportunityWorkflowProjection['opportunity'],
  workflow: {
    state: 'NEEDS_EVALUATION' as WorkflowState,
    next_action: {
      key: 'evaluate',
      label: '运行 Opportunity 评估',
      can_start_validation: false,
    },
    action_plan: [] as OpportunityWorkflowProjection['workflow']['action_plan'],
    blockers: [] as OpportunityWorkflowProjection['workflow']['blockers'],
    upgrade_conditions: [] as OpportunityWorkflowProjection['workflow']['upgrade_conditions'],
  },
  evidence: {
    items: [
      {
        evidence_id: 'ev-1',
        factor_key: 'event_probability',
        value: true,
        value_type: 'bool',
        observation_type: 'observed',
        source_url: 'https://example.com/source',
        source_type: 'official',
        source_grade: 'A' as const,
        verification_status: 'verified',
        observed_at: '2026-07-01T00:00:00+00:00',
        effective_at: null,
        expires_at: null,
        freshness: 'CURRENT' as const,
        age_days: 0,
      },
    ],
    missing_factor_keys: ['hard_cost_usd'],
    counts_by_grade: { A: 1, B: 0, C: 0, D: 0, U: 0 },
  },
  validation: {
    current: {
      id: 1,
      project_id: 'proj-demo',
      status: 'active' as InteractionStatus,
      created_at: '2026-07-20T10:00:00+00:00',
      wallet_count: 1,
      opportunity_assessment_id: 'assess-1',
      opportunity_model_version: 'opportunity-v2.0' as const,
      opportunity_profile_version: 'low-cost-curated-multiwallet-v1' as const,
      ..._OUTCOME_FIELDS,
    },
    history_summary: {
      total: 1,
      by_status: {
        planned: 0,
        active: 1,
        done: 0,
        abandoned: 0,
      },
    },
    allowed_transitions: {
      planned: ['active', 'abandoned'] as InteractionStatus[],
      active: ['done', 'abandoned'] as InteractionStatus[],
      done: [] as InteractionStatus[],
      abandoned: [] as InteractionStatus[],
    },
    can_start_validation: false,
  },
  review_at: null as string | null,
  expires_at: null as string | null,
};

const _STATE_FIXTURES = {
  NEEDS_EVALUATION: {
    ..._BASE_PROJECTION,
    opportunity: null,
    workflow: {
      ..._BASE_PROJECTION.workflow,
      state: 'NEEDS_EVALUATION' as const,
      next_action: {
        key: 'evaluate',
        label: '运行 Opportunity 评估',
        can_start_validation: false,
      },
    },
    validation: { ..._BASE_PROJECTION.validation, can_start_validation: false, current: null },
  },
  REVIEW_REQUIRED: {
    ..._BASE_PROJECTION,
    opportunity: {
      shadow: true as const,
      assessment_id: 'assess-1',
      model_version: 'opportunity-v2.0' as const,
      profile_version: 'low-cost-curated-multiwallet-v1' as const,
      status: 'ACTIONABLE' as const,
      public_label: 'FARM' as const,
      recommended_action: '重新评估后继续',
      blocker_codes: [] as string[],
      watch_reason_codes: [] as string[],
      ignore_reason_codes: [] as string[],
      requires_remediation: false,
      confidence: {
        event: 0.5,
        eligibility: 0.5,
        reward: 0.5,
        cost: 0.5,
        risk: 0.5,
        quality: 0.5,
        overall: 0.5,
      },
      event_probability: { low: 0.2, base: 0.4, high: 0.6 },
      eligibility_probability: null,
      survival_probability: null,
      reward_probability: null,
      conditional_reward_usd: { low: 10, base: 50, high: 100 },
      hard_cost_usd: { low: 1, base: 5, high: 10 },
      economics: {
        gross_reward: { low: 10, base: 50, high: 100 },
        net_reward: { low: -5, base: 40, high: 90 },
        reward_to_cost_ratio: 8,
        decision_value: 1.2,
        capital_efficiency: 0.8,
        time_efficiency: 0.7,
      },
      risks: {
        capital_security: 'low' as const,
        eligibility: 'medium' as const,
        project_failure: null,
        reward_dilution: null,
        liquidity: null,
      },
      scored_at: '2026-06-01T00:00:00+00:00',
      review_at: '2026-07-01T00:00:00+00:00',
      expires_at: '2026-07-15T00:00:00+00:00',
    },
    workflow: {
      ..._BASE_PROJECTION.workflow,
      state: 'REVIEW_REQUIRED' as const,
      next_action: {
        key: 're_evaluate',
        label: '重新评估',
        can_start_validation: false,
      },
    },
    review_at: '2026-07-01T00:00:00+00:00',
    expires_at: '2026-07-15T00:00:00+00:00',
  },
  ACTIONABLE: {
    ..._BASE_PROJECTION,
    opportunity: {
      shadow: true as const,
      assessment_id: 'assess-1',
      model_version: 'opportunity-v2.0' as const,
      profile_version: 'low-cost-curated-multiwallet-v1' as const,
      status: 'ACTIONABLE' as const,
      public_label: 'FARM' as const,
      recommended_action: '1-2 钱包验证',
      blocker_codes: [] as string[],
      watch_reason_codes: [] as string[],
      ignore_reason_codes: [] as string[],
      requires_remediation: false,
      confidence: {
        event: 0.6,
        eligibility: 0.6,
        reward: 0.5,
        cost: 0.7,
        risk: 0.5,
        quality: 0.6,
        overall: 0.6,
      },
      event_probability: { low: 0.3, base: 0.5, high: 0.7 },
      eligibility_probability: { low: 0.4, base: 0.6, high: 0.8 },
      survival_probability: { low: 0.5, base: 0.7, high: 0.9 },
      reward_probability: { low: 0.2, base: 0.4, high: 0.6 },
      conditional_reward_usd: { low: 20, base: 80, high: 200 },
      hard_cost_usd: { low: 2, base: 8, high: 15 },
      economics: {
        gross_reward: { low: 20, base: 80, high: 200 },
        net_reward: { low: 5, base: 60, high: 180 },
        reward_to_cost_ratio: 10,
        decision_value: 2.1,
        capital_efficiency: 1.1,
        time_efficiency: 0.9,
      },
      risks: {
        capital_security: 'low' as const,
        eligibility: 'low' as const,
        project_failure: 'medium' as const,
        reward_dilution: 'medium' as const,
        liquidity: 'low' as const,
      },
      scored_at: '2026-07-18T00:00:00+00:00',
      review_at: '2026-08-01T00:00:00+00:00',
      expires_at: '2026-08-15T00:00:00+00:00',
    },
    workflow: {
      state: 'ACTIONABLE' as const,
      next_action: {
        key: 'start_validation',
        label: '开始验证',
        can_start_validation: true,
      },
      action_plan: [
        {
          id: 'validation-1-2-wallets',
          sequence: 1,
          kind: 'validation',
          phase: 'validation' as const,
          title: '1-2 钱包小样本验证',
          description: '用 1-2 个钱包记录真实成本与时间。',
          required: true,
          source: 'workflow',
          priority: 1,
          task_id: null,
          external_url: null,
        },
      ],
      blockers: [],
      upgrade_conditions: [],
    },
    validation: {
      ..._BASE_PROJECTION.validation,
      can_start_validation: true,
      current: null,
    },
    review_at: '2026-08-01T00:00:00+00:00',
    expires_at: '2026-08-15T00:00:00+00:00',
  },
  MONITOR: {
    ..._BASE_PROJECTION,
    opportunity: {
      shadow: true as const,
      assessment_id: 'assess-2',
      model_version: 'opportunity-v2.0' as const,
      profile_version: 'low-cost-curated-multiwallet-v1' as const,
      status: 'MONITOR' as const,
      public_label: 'WATCH' as const,
      recommended_action: '监控升级条件',
      blocker_codes: [] as string[],
      watch_reason_codes: ['LOW_CONFIDENCE'],
      ignore_reason_codes: [] as string[],
      requires_remediation: false,
      confidence: {
        event: 0.3,
        eligibility: 0.3,
        reward: 0.3,
        cost: 0.4,
        risk: 0.4,
        quality: 0.3,
        overall: 0.3,
      },
      event_probability: null,
      eligibility_probability: null,
      survival_probability: null,
      reward_probability: null,
      conditional_reward_usd: null,
      hard_cost_usd: null,
      economics: null,
      risks: {
        capital_security: null,
        eligibility: null,
        project_failure: null,
        reward_dilution: null,
        liquidity: null,
      },
      scored_at: '2026-07-18T00:00:00+00:00',
      review_at: '2026-08-01T00:00:00+00:00',
      expires_at: '2026-08-15T00:00:00+00:00',
    },
    workflow: {
      ..._BASE_PROJECTION.workflow,
      state: 'MONITOR' as const,
      next_action: {
        key: 'monitor',
        label: '监控升级条件',
        can_start_validation: false,
      },
      upgrade_conditions: [{ code: 'LOW_CONFIDENCE', message: '提高置信度' }],
    },
    validation: { ..._BASE_PROJECTION.validation, can_start_validation: false, current: null },
  },
  INSUFFICIENT_EVIDENCE: {
    ..._BASE_PROJECTION,
    opportunity: {
      shadow: true as const,
      assessment_id: 'assess-3',
      model_version: 'opportunity-v2.0' as const,
      profile_version: 'low-cost-curated-multiwallet-v1' as const,
      status: 'INSUFFICIENT_EVIDENCE' as const,
      public_label: 'WATCH' as const,
      recommended_action: '补齐关键证据',
      blocker_codes: [] as string[],
      watch_reason_codes: [] as string[],
      ignore_reason_codes: [] as string[],
      requires_remediation: false,
      confidence: {
        event: 0.2,
        eligibility: 0.2,
        reward: 0.2,
        cost: 0.2,
        risk: 0.2,
        quality: 0.2,
        overall: 0.2,
      },
      event_probability: null,
      eligibility_probability: null,
      survival_probability: null,
      reward_probability: null,
      conditional_reward_usd: null,
      hard_cost_usd: null,
      economics: null,
      risks: {
        capital_security: null,
        eligibility: null,
        project_failure: null,
        reward_dilution: null,
        liquidity: null,
      },
      scored_at: '2026-07-18T00:00:00+00:00',
      review_at: '2026-08-01T00:00:00+00:00',
      expires_at: '2026-08-15T00:00:00+00:00',
    },
    workflow: {
      ..._BASE_PROJECTION.workflow,
      state: 'INSUFFICIENT_EVIDENCE' as const,
      next_action: {
        key: 'collect_evidence',
        label: '补齐关键证据',
        can_start_validation: false,
      },
    },
    validation: { ..._BASE_PROJECTION.validation, can_start_validation: false, current: null },
  },
  BLOCKED: {
    ..._BASE_PROJECTION,
    opportunity: {
      shadow: true as const,
      assessment_id: 'assess-4',
      model_version: 'opportunity-v2.0' as const,
      profile_version: 'low-cost-curated-multiwallet-v1' as const,
      status: 'BLOCKED' as const,
      public_label: 'IGNORE' as const,
      recommended_action: '整改前不要交互',
      blocker_codes: ['SAFETY_BLOCK'],
      watch_reason_codes: [] as string[],
      ignore_reason_codes: [] as string[],
      requires_remediation: true,
      confidence: {
        event: 0.1,
        eligibility: 0.1,
        reward: 0.1,
        cost: 0.1,
        risk: 0.9,
        quality: 0.1,
        overall: 0.1,
      },
      event_probability: null,
      eligibility_probability: null,
      survival_probability: null,
      reward_probability: null,
      conditional_reward_usd: null,
      hard_cost_usd: null,
      economics: null,
      risks: {
        capital_security: 'critical' as const,
        eligibility: null,
        project_failure: null,
        reward_dilution: null,
        liquidity: null,
      },
      scored_at: '2026-07-18T00:00:00+00:00',
      review_at: '2026-08-01T00:00:00+00:00',
      expires_at: '2026-08-15T00:00:00+00:00',
    },
    workflow: {
      ..._BASE_PROJECTION.workflow,
      state: 'BLOCKED' as const,
      next_action: {
        key: 'remediate',
        label: '整改前不要交互',
        can_start_validation: false,
      },
      blockers: [
        {
          code: 'SAFETY_BLOCK',
          severity: 'critical',
          message: '安全风险未解除',
        },
      ],
    },
    validation: { ..._BASE_PROJECTION.validation, can_start_validation: false, current: null },
  },
  NOT_FIT: {
    ..._BASE_PROJECTION,
    opportunity: {
      shadow: true as const,
      assessment_id: 'assess-5',
      model_version: 'opportunity-v2.0' as const,
      profile_version: 'low-cost-curated-multiwallet-v1' as const,
      status: 'NOT_FIT' as const,
      public_label: 'IGNORE' as const,
      recommended_action: '当前画像不分配时间或资金',
      blocker_codes: [] as string[],
      watch_reason_codes: [] as string[],
      ignore_reason_codes: ['PROFILE_MISMATCH'],
      requires_remediation: false,
      confidence: {
        event: 0.4,
        eligibility: 0.4,
        reward: 0.2,
        cost: 0.8,
        risk: 0.5,
        quality: 0.4,
        overall: 0.3,
      },
      event_probability: null,
      eligibility_probability: null,
      survival_probability: null,
      reward_probability: null,
      conditional_reward_usd: null,
      hard_cost_usd: null,
      economics: null,
      risks: {
        capital_security: null,
        eligibility: null,
        project_failure: null,
        reward_dilution: null,
        liquidity: null,
      },
      scored_at: '2026-07-18T00:00:00+00:00',
      review_at: '2026-08-01T00:00:00+00:00',
      expires_at: '2026-08-15T00:00:00+00:00',
    },
    workflow: {
      ..._BASE_PROJECTION.workflow,
      state: 'NOT_FIT' as const,
      next_action: {
        key: 'not_fit',
        label: '当前画像不分配时间或资金',
        can_start_validation: false,
      },
    },
    validation: { ..._BASE_PROJECTION.validation, can_start_validation: false, current: null },
  },
} as const satisfies Record<WorkflowState, OpportunityWorkflowProjection>;

// Keep compile fixtures referenced so tsc always evaluates them.
void WORKFLOW_STATES;
void INTERACTION_STATUSES;
void _STATE_FIXTURES;

const FIXED_MODEL: OpportunityModelVersion = 'opportunity-v2.0';
const FIXED_PROFILE: OpportunityProfileVersion = 'low-cost-curated-multiwallet-v1';

const STATE_ZH: Record<WorkflowState, string> = {
  NEEDS_EVALUATION: '待评估',
  REVIEW_REQUIRED: '需复评',
  ACTIONABLE: '可行动',
  MONITOR: '监控中',
  INSUFFICIENT_EVIDENCE: '证据不足',
  BLOCKED: '已阻断',
  NOT_FIT: '不匹配',
};

const STATUS_ZH: Record<InteractionStatus, string> = {
  planned: '计划中',
  active: '进行中',
  done: '已完成',
  abandoned: '已放弃',
};

const ELIGIBILITY_OPTS: { id: EligibilityResult | ''; label: string }[] = [
  { id: '', label: '—' },
  { id: 'unknown', label: '未知' },
  { id: 'eligible', label: '有资格' },
  { id: 'ineligible', label: '无资格' },
];

const SURVIVAL_OPTS: { id: SurvivalResult | ''; label: string }[] = [
  { id: '', label: '—' },
  { id: 'unknown', label: '未知' },
  { id: 'passed', label: '通过' },
  { id: 'disqualified', label: '被淘汰' },
];

const DEFAULT_TRANSITIONS: Record<InteractionStatus, InteractionStatus[]> = {
  planned: ['active', 'abandoned'],
  active: ['done', 'abandoned'],
  done: [],
  abandoned: [],
};

function isInteractionStatus(value: string): value is InteractionStatus {
  return value === 'planned' || value === 'active' || value === 'done' || value === 'abandoned';
}

function formatRange(
  range: { low: number; base: number; high: number } | null | undefined,
  prefix = '',
): string {
  if (!range) return '—';
  return `${prefix}${range.low} / ${range.base} / ${range.high}`;
}

function formatTs(value?: string | null): string {
  if (!value) return '—';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleString();
}

function parseOptionalNumber(raw: string): number | null {
  const t = raw.trim();
  if (t === '') return null;
  const n = Number(t);
  return Number.isFinite(n) ? n : null;
}

function parseOptionalInt(raw: string): number | null {
  const n = parseOptionalNumber(raw);
  if (n == null) return null;
  return Math.trunc(n);
}

function allowedTargets(
  current: ValidationCurrent | null,
  allowed: Record<string, string[]>,
): InteractionStatus[] {
  if (!current || !isInteractionStatus(String(current.status))) return [];
  const status = current.status as InteractionStatus;
  const fromApi = allowed[status];
  const raw = Array.isArray(fromApi) ? fromApi : DEFAULT_TRANSITIONS[status];
  return raw.filter(isInteractionStatus);
}

function hasOpenValidation(current: ValidationCurrent | null): boolean {
  if (!current) return false;
  const s = String(current.status);
  return s === 'planned' || s === 'active';
}

/* ── Subcomponents ─────────────────────────────────────────────── */

function LegacyDecisionBadge({ legacy }: { legacy: OpportunityWorkflowProjection['legacy'] }) {
  return (
    <div className="rounded-xl border border-line/80 bg-surface-2/50 px-3 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="badge bg-brand-50 text-brand-700 dark:bg-brand-500/20 dark:text-brand-200">
          权威决策
        </span>
        <span className="text-[11px] text-ink-faint">{legacy.model_version}</span>
        {legacy.authoritative ? (
          <span className="badge bg-farm-soft text-farm-dark dark:bg-farm/15 dark:text-farm">
            authoritative
          </span>
        ) : null}
      </div>
      <div className="mt-2 flex flex-wrap items-baseline gap-2">
        <span className="text-lg font-bold text-ink">
          {legacy.label ? labelZh(legacy.label) : '—'}
        </span>
        <span className="tabular-nums text-sm text-ink-muted">
          {legacy.score != null ? `${legacy.score} 分` : '未评分'}
        </span>
      </div>
      {legacy.reason?.length ? (
        <ul className="mt-2 list-inside list-disc text-xs text-ink-muted">
          {legacy.reason.slice(0, 4).map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function OpportunityAssessmentSummary({
  opportunity,
  state,
}: {
  opportunity: OpportunityWorkflowProjection['opportunity'];
  state: WorkflowState;
}) {
  return (
    <div className="rounded-xl border border-dashed border-watch/40 bg-watch-soft/30 px-3 py-3 dark:bg-watch/10">
      <div className="flex flex-wrap items-center gap-2">
        <span className="badge bg-watch-soft text-watch-dark dark:bg-watch/20 dark:text-watch">
          Opportunity Shadow · 实验性
        </span>
        <span className="badge bg-surface-3 text-ink-muted">{STATE_ZH[state]}</span>
      </div>
      {!opportunity ? (
        <p className="mt-2 text-sm text-ink-muted">尚无 Opportunity 评估。请先运行评估。</p>
      ) : (
        <div className="mt-2 space-y-1.5 text-sm">
          <div className="flex flex-wrap items-baseline gap-2">
            <span className="font-semibold text-ink">{labelZh(opportunity.public_label)}</span>
            <span className="text-xs text-ink-faint">{opportunity.status}</span>
          </div>
          <p className="text-ink-muted">{opportunity.recommended_action}</p>
          <p className="text-xs text-ink-faint">
            置信度 overall{' '}
            <span className="tabular-nums">
              {(opportunity.confidence.overall * 100).toFixed(0)}%
            </span>
            {' · '}
            评估于 {formatTs(opportunity.scored_at)}
          </p>
          <p className="text-xs text-ink-faint">
            硬成本 {formatRange(opportunity.hard_cost_usd, '$')} · 条件奖励{' '}
            {formatRange(opportunity.conditional_reward_usd, '$')}
          </p>
          <p className="text-[11px] text-ink-faint">
            {opportunity.model_version} / {opportunity.profile_version}
            {opportunity.assessment_id ? ` · id ${opportunity.assessment_id}` : ''}
          </p>
        </div>
      )}
    </div>
  );
}

function NextActionCard({
  label,
  busy,
  disabled,
  onClick,
  guidanceOnly,
}: {
  label: string;
  busy: boolean;
  disabled: boolean;
  onClick?: () => void;
  guidanceOnly: boolean;
}) {
  return (
    <div className="rounded-xl border border-brand-200/60 bg-gradient-to-r from-brand-500/10 via-transparent to-farm/10 px-4 py-3 dark:border-brand-500/25">
      <div className="text-[11px] font-semibold uppercase tracking-wider text-ink-muted">
        下一步
      </div>
      <p className="mt-1 text-sm font-semibold text-ink">{label}</p>
      {guidanceOnly ? (
        <p className="mt-2 text-xs text-ink-muted">当前状态仅提供指引，不启动验证。</p>
      ) : (
        <button
          type="button"
          className="btn-primary mt-3"
          disabled={disabled || busy}
          onClick={onClick}
          aria-busy={busy}
        >
          {busy ? '处理中…' : label}
        </button>
      )}
    </div>
  );
}

function ActionPlanAccordion({
  items,
}: {
  items: OpportunityWorkflowProjection['workflow']['action_plan'];
}) {
  const sorted = useMemo(
    () => [...items].sort((a, b) => a.sequence - b.sequence || a.priority - b.priority),
    [items],
  );
  if (!sorted.length) {
    return (
      <p className="text-xs text-ink-faint">暂无行动计划条目。</p>
    );
  }
  return (
    <div className="space-y-2">
      {sorted.map((item) => (
        <details
          key={item.id}
          className="group rounded-xl border border-line/80 bg-surface-2/30 open:bg-surface-2/50"
        >
          <summary className="cursor-pointer list-none px-3 py-2.5 marker:content-none">
            <div className="flex flex-wrap items-center gap-2">
              <span className="badge bg-surface-3 text-ink-muted">#{item.sequence}</span>
              <span className="text-sm font-medium text-ink">{item.title}</span>
              {item.required ? (
                <span className="badge bg-brand-50 text-brand-700 dark:bg-brand-500/15 dark:text-brand-200">
                  必要
                </span>
              ) : null}
              <span className="text-[11px] text-ink-faint">{item.phase}</span>
            </div>
          </summary>
          <div className="border-t border-line/60 px-3 py-2 text-xs text-ink-muted">
            <p>{item.description}</p>
            {item.external_url && /^https?:\/\//i.test(item.external_url) ? (
              <a
                href={item.external_url}
                target="_blank"
                rel="noopener noreferrer"
                className="mt-1 inline-block text-brand-600 underline dark:text-brand-300"
              >
                打开链接
              </a>
            ) : null}
          </div>
        </details>
      ))}
    </div>
  );
}

function BlockerAndUpgradeConditions({
  blockers,
  upgrades,
}: {
  blockers: OpportunityWorkflowProjection['workflow']['blockers'];
  upgrades: OpportunityWorkflowProjection['workflow']['upgrade_conditions'];
}) {
  if (!blockers.length && !upgrades.length) return null;
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {blockers.length ? (
        <div className="rounded-xl border border-red-200/70 bg-red-50/60 px-3 py-2.5 dark:border-red-500/30 dark:bg-red-500/10">
          <div className="text-xs font-semibold text-red-700 dark:text-red-300">阻断项</div>
          <ul className="mt-1.5 space-y-1 text-xs text-red-700/90 dark:text-red-200/90">
            {blockers.map((b) => (
              <li key={`${b.code}-${b.message}`}>
                <span className="font-medium">{b.code}</span>
                {b.severity ? ` (${b.severity})` : ''}: {b.message}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {upgrades.length ? (
        <div className="rounded-xl border border-watch/40 bg-watch-soft/40 px-3 py-2.5 dark:bg-watch/10">
          <div className="text-xs font-semibold text-watch-dark dark:text-watch">升级条件</div>
          <ul className="mt-1.5 space-y-1 text-xs text-ink-muted">
            {upgrades.map((u) => (
              <li key={`${u.code}-${u.message}`}>
                <span className="font-medium text-ink">{u.code}</span>: {u.message}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

function EvidenceSummary({
  evidence,
}: {
  evidence: OpportunityWorkflowProjection['evidence'];
}) {
  const grades = evidence.counts_by_grade || {};
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-2 text-xs text-ink-muted">
        {(['A', 'B', 'C', 'D', 'U'] as const).map((g) => (
          <span key={g} className="badge bg-surface-3">
            {g}: {Number((grades as Record<string, number>)[g] ?? 0)}
          </span>
        ))}
        <span className="badge bg-surface-3">条目 {evidence.items.length}</span>
      </div>
      {evidence.missing_factor_keys?.length ? (
        <p className="text-xs text-ink-muted">
          缺失因子：{evidence.missing_factor_keys.join(', ')}
        </p>
      ) : null}
      {evidence.items.length === 0 ? (
        <p className="text-xs text-ink-faint">暂无证据条目。</p>
      ) : (
        <ul className="max-h-48 space-y-1.5 overflow-y-auto text-xs">
          {evidence.items.map((item, idx) => (
            <li
              key={item.evidence_id || `${item.factor_key}-${idx}`}
              className="rounded-lg border border-line/60 bg-surface-2/30 px-2.5 py-2"
            >
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium text-ink">{item.factor_key}</span>
                <span className="badge bg-surface-3">{item.source_grade}</span>
                <span className="badge bg-surface-3">{item.freshness}</span>
                <span className="text-ink-faint">{item.verification_status}</span>
              </div>
              <p className="mt-0.5 text-ink-muted">
                {item.source_type}
                {item.source_url && /^https?:\/\//i.test(item.source_url) ? (
                  <>
                    {' · '}
                    <a
                      href={item.source_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-brand-600 underline dark:text-brand-300"
                    >
                      来源
                    </a>
                  </>
                ) : null}
                {' · '}
                {formatTs(item.observed_at)}
              </p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function ValidationPanel({
  projectId,
  projection,
  busy,
  onStart,
  onTransition,
  onSaveOutcome,
}: {
  projectId: string;
  projection: OpportunityWorkflowProjection;
  busy: boolean;
  onStart: (walletCount: 1 | 2) => void;
  onTransition: (status: InteractionStatus) => void;
  onSaveOutcome: (payload: Record<string, unknown>) => void;
}) {
  const { validation, opportunity, workflow } = projection;
  const current = validation.current;
  const open = hasOpenValidation(current);
  const canStart =
    workflow.state === 'ACTIONABLE' &&
    validation.can_start_validation &&
    workflow.next_action.can_start_validation &&
    !open &&
    Boolean(opportunity?.assessment_id);

  const [walletCount, setWalletCount] = useState<1 | 2>(1);
  const [hardCost, setHardCost] = useState('');
  const [timeMinutes, setTimeMinutes] = useState('');
  const [eligibility, setEligibility] = useState<EligibilityResult | ''>('');
  const [survival, setSurvival] = useState<SurvivalResult | ''>('');
  const [dqReason, setDqReason] = useState('');
  const [reward, setReward] = useState('');
  const [claimCost, setClaimCost] = useState('');
  const [localError, setLocalError] = useState('');

  useEffect(() => {
    if (!current || String(current.status) !== 'active') return;
    setHardCost(current.actual_hard_cost_usd != null ? String(current.actual_hard_cost_usd) : '');
    setTimeMinutes(current.actual_time_minutes != null ? String(current.actual_time_minutes) : '');
    setEligibility((current.eligibility_result as EligibilityResult | null) || '');
    setSurvival((current.survival_result as SurvivalResult | null) || '');
    setDqReason(current.disqualification_reason || '');
    setReward(current.reward_received_usd != null ? String(current.reward_received_usd) : '');
    setClaimCost(current.claim_cost_usd != null ? String(current.claim_cost_usd) : '');
  }, [current]);

  const transitions = allowedTargets(current, validation.allowed_transitions);
  const isActive = current != null && String(current.status) === 'active';

  const saveOutcome = () => {
    setLocalError('');
    if (survival === 'disqualified' && !dqReason.trim()) {
      setLocalError('被淘汰时必须填写淘汰原因');
      return;
    }
    const payload: Record<string, unknown> = {
      actual_hard_cost_usd: parseOptionalNumber(hardCost),
      actual_time_minutes: parseOptionalInt(timeMinutes),
      eligibility_result: eligibility || null,
      survival_result: survival || null,
      disqualification_reason: dqReason.trim() ? dqReason.trim() : null,
      reward_received_usd: parseOptionalNumber(reward),
      claim_cost_usd: parseOptionalNumber(claimCost),
    };
    onSaveOutcome(payload);
  };

  return (
    <div className="space-y-3" data-project-id={projectId}>
      <div className="flex flex-wrap gap-2 text-xs text-ink-muted">
        <span className="badge bg-surface-3">
          历史 {validation.history_summary.total} 条
        </span>
        {(Object.entries(validation.history_summary.by_status) as [string, number][]).map(
          ([k, v]) => (
            <span key={k} className="badge bg-surface-3">
              {STATUS_ZH[k as InteractionStatus] || k}: {v}
            </span>
          ),
        )}
      </div>

      {current ? (
        <div className="rounded-xl border border-line/80 bg-surface-2/40 px-3 py-3 text-sm">
          <div className="flex flex-wrap items-center gap-2">
            <span className="badge bg-brand-50 text-brand-700 dark:bg-brand-500/15 dark:text-brand-200">
              {STATUS_ZH[String(current.status) as InteractionStatus] || current.status}
            </span>
            <span className="text-xs text-ink-muted">
              钱包数 {current.wallet_count ?? '—'}
            </span>
            <span className="text-xs text-ink-faint">创建于 {formatTs(current.created_at)}</span>
          </div>
          {current.opportunity_assessment_id ? (
            <p className="mt-1 text-xs text-ink-faint">
              关联评估 {current.opportunity_assessment_id}
              {current.opportunity_model_version
                ? ` · ${current.opportunity_model_version}`
                : ''}
              {current.opportunity_profile_version
                ? ` / ${current.opportunity_profile_version}`
                : ''}
            </p>
          ) : null}
          {current.outcome_observed_at ? (
            <p className="mt-0.5 text-xs text-ink-faint">
              结果观察于 {formatTs(current.outcome_observed_at)}
            </p>
          ) : null}
        </div>
      ) : (
        <p className="text-xs text-ink-faint">当前无进行中的验证交互。</p>
      )}

      {canStart ? (
        <div className="flex flex-wrap items-end gap-2 rounded-xl border border-line/70 px-3 py-3">
          <label className="text-xs text-ink-muted">
            验证钱包数
            <select
              className="select mt-1 w-28"
              value={walletCount}
              onChange={(e) => setWalletCount(Number(e.target.value) === 2 ? 2 : 1)}
              disabled={busy}
            >
              <option value={1}>1</option>
              <option value={2}>2</option>
            </select>
          </label>
          <button
            type="button"
            className="btn-secondary"
            disabled={busy}
            onClick={() => onStart(walletCount)}
          >
            开始验证（planned）
          </button>
        </div>
      ) : null}

      {current && transitions.length ? (
        <div className="flex flex-wrap gap-2">
          {transitions.map((t) => (
            <button
              key={t}
              type="button"
              className="btn-secondary !py-1.5 text-xs"
              disabled={busy}
              onClick={() => onTransition(t)}
            >
              标记为 {STATUS_ZH[t]}
            </button>
          ))}
        </div>
      ) : null}

      {isActive ? (
        <div className="space-y-2 rounded-xl border border-line/80 px-3 py-3">
          <div className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
            验证结果（7 字段）
          </div>
          <div className="grid gap-2 sm:grid-cols-2">
            <label className="text-xs text-ink-muted">
              实际硬成本 USD
              <input
                type="number"
                min={0}
                step="0.01"
                className="input mt-1"
                value={hardCost}
                onChange={(e) => setHardCost(e.target.value)}
                disabled={busy}
              />
            </label>
            <label className="text-xs text-ink-muted">
              实际耗时（分钟）
              <input
                type="number"
                min={0}
                step={1}
                className="input mt-1"
                value={timeMinutes}
                onChange={(e) => setTimeMinutes(e.target.value)}
                disabled={busy}
              />
            </label>
            <label className="text-xs text-ink-muted">
              资格结果
              <select
                className="select mt-1"
                value={eligibility}
                onChange={(e) => setEligibility(e.target.value as EligibilityResult | '')}
                disabled={busy}
              >
                {ELIGIBILITY_OPTS.map((o) => (
                  <option key={o.id || 'empty'} value={o.id}>
                    {o.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-xs text-ink-muted">
              存活结果
              <select
                className="select mt-1"
                value={survival}
                onChange={(e) => setSurvival(e.target.value as SurvivalResult | '')}
                disabled={busy}
              >
                {SURVIVAL_OPTS.map((o) => (
                  <option key={o.id || 'empty'} value={o.id}>
                    {o.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-xs text-ink-muted sm:col-span-2">
              淘汰原因
              <input
                className="input mt-1"
                value={dqReason}
                onChange={(e) => setDqReason(e.target.value)}
                disabled={busy}
                required={survival === 'disqualified'}
                aria-required={survival === 'disqualified'}
                placeholder="survival=disqualified 时必填；勿填写钱包或密钥"
              />
            </label>
            <label className="text-xs text-ink-muted">
              已获奖励 USD
              <input
                type="number"
                min={0}
                step="0.01"
                className="input mt-1"
                value={reward}
                onChange={(e) => setReward(e.target.value)}
                disabled={busy}
              />
            </label>
            <label className="text-xs text-ink-muted">
              领取成本 USD
              <input
                type="number"
                min={0}
                step="0.01"
                className="input mt-1"
                value={claimCost}
                onChange={(e) => setClaimCost(e.target.value)}
                disabled={busy}
              />
            </label>
          </div>
          {localError ? (
            <p className="text-xs text-red-600 dark:text-red-300" role="alert">
              {localError}
            </p>
          ) : null}
          <button type="button" className="btn-primary" disabled={busy} onClick={saveOutcome}>
            {busy ? '保存中…' : '保存结果'}
          </button>
        </div>
      ) : null}
    </div>
  );
}

/* ── Main panel ────────────────────────────────────────────────── */

export function OpportunityWorkflowPanel({ projectId }: { projectId: string }) {
  const headingId = useId();
  const statusId = useId();
  const validationRef = useRef<HTMLDivElement | null>(null);

  const [data, setData] = useState<OpportunityWorkflowProjection | null>(null);
  const [loading, setLoading] = useState(true);
  const [mutating, setMutating] = useState(false);
  const [error, setError] = useState('');
  const [msg, setMsg] = useState('');

  const load = useCallback(async () => {
    if (!projectId) return;
    setLoading(true);
    setError('');
    try {
      const res = await apiFetch<OpportunityWorkflowProjection>(
        `/projects/${projectId}/opportunity/workflow`,
      );
      setData(res);
    } catch (e: unknown) {
      setData(null);
      setError(e instanceof Error ? e.message : '加载工作流失败');
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    load();
  }, [load]);

  const runEvaluate = useCallback(async () => {
    setMutating(true);
    setError('');
    setMsg('');
    try {
      await apiFetch(`/projects/${projectId}/opportunity/evaluate`, {
        method: 'POST',
        body: '{}',
      });
      setMsg('评估已完成');
      await load();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '评估失败');
    } finally {
      setMutating(false);
      setTimeout(() => setMsg(''), 3000);
    }
  }, [projectId, load]);

  const startValidation = useCallback(
    async (walletCount: 1 | 2) => {
      if (!data?.opportunity?.assessment_id) {
        setError('缺少 assessment_id，无法开始验证');
        return;
      }
      if (data.workflow.state !== 'ACTIONABLE') {
        setError('仅 ACTIONABLE 状态可开始验证');
        return;
      }
      setMutating(true);
      setError('');
      setMsg('');
      try {
        await apiFetch('/interactions', {
          method: 'POST',
          body: JSON.stringify({
            project_id: projectId,
            status: 'planned' as const,
            wallet_count: walletCount,
            opportunity_assessment_id: data.opportunity.assessment_id,
            opportunity_model_version: FIXED_MODEL,
            opportunity_profile_version: FIXED_PROFILE,
          }),
        });
        setMsg('已创建 planned 验证');
        await load();
      } catch (e: unknown) {
        setError(e instanceof Error ? e.message : '创建验证失败');
      } finally {
        setMutating(false);
        setTimeout(() => setMsg(''), 3000);
      }
    },
    [data, projectId, load],
  );

  const patchLifecycle = useCallback(
    async (status: InteractionStatus) => {
      if (!data?.validation.current) {
        setError('无当前验证可更新');
        return;
      }
      const id = data.validation.current.id;
      if (id == null) {
        setError('无当前验证可更新');
        return;
      }
      const allowed = allowedTargets(
        data.validation.current,
        data.validation.allowed_transitions,
      );
      if (!allowed.includes(status)) {
        setError(`不允许转换到 ${status}`);
        return;
      }
      setMutating(true);
      setError('');
      setMsg('');
      try {
        await apiFetch(`/interactions/${id}`, {
          method: 'PATCH',
          body: JSON.stringify({ status }),
        });
        setMsg(`状态已更新为 ${STATUS_ZH[status]}`);
        await load();
      } catch (e: unknown) {
        setError(e instanceof Error ? e.message : '状态更新失败');
      } finally {
        setMutating(false);
        setTimeout(() => setMsg(''), 3000);
      }
    },
    [data, load],
  );

  const saveOutcome = useCallback(
    async (payload: Record<string, unknown>) => {
      const id = data?.validation.current?.id;
      if (id == null) {
        setError('无当前验证可保存结果');
        return;
      }
      setMutating(true);
      setError('');
      setMsg('');
      try {
        await apiFetch(`/interactions/${id}`, {
          method: 'PATCH',
          body: JSON.stringify(payload),
        });
        setMsg('验证结果已保存');
        await load();
      } catch (e: unknown) {
        setError(e instanceof Error ? e.message : '保存结果失败');
      } finally {
        setMutating(false);
        setTimeout(() => setMsg(''), 3000);
      }
    },
    [data, load],
  );

  const primary = useMemo(() => {
    if (!data) {
      return {
        label: '加载中',
        guidanceOnly: true as const,
        onClick: undefined as (() => void) | undefined,
      };
    }
    const state = data.workflow.state;
    const next = data.workflow.next_action;
    const open = hasOpenValidation(data.validation.current);

    if (state === 'NEEDS_EVALUATION' || next.key === 'evaluate') {
      return { label: next.label || '运行 Opportunity 评估', guidanceOnly: false, onClick: runEvaluate };
    }
    if (state === 'REVIEW_REQUIRED' || next.key === 're_evaluate') {
      return { label: next.label || '重新评估', guidanceOnly: false, onClick: runEvaluate };
    }
    if (state === 'ACTIONABLE') {
      if (open) {
        return {
          label: '继续验证',
          guidanceOnly: false,
          onClick: () => {
            validationRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
            validationRef.current?.focus();
          },
        };
      }
      if (data.validation.can_start_validation && next.can_start_validation) {
        return {
          label: next.label || '开始验证',
          guidanceOnly: false,
          onClick: () => void startValidation(1),
        };
      }
    }
    return {
      label: next.label || STATE_ZH[state] || '查看指引',
      guidanceOnly: true,
      onClick: undefined,
    };
  }, [data, runEvaluate, startValidation]);

  const busy = loading || mutating;

  return (
    <section
      className="card overflow-hidden"
      aria-labelledby={headingId}
      aria-busy={busy}
      aria-describedby={statusId}
    >
      <div className="border-b border-line bg-gradient-to-r from-brand-500/10 via-transparent to-watch/10 px-5 py-4 sm:px-6">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 id={headingId} className="text-base font-bold text-ink">
              Opportunity 工作流
            </h2>
            <p className="mt-0.5 text-xs text-ink-muted">
              权威标签仍为 score-v1.4；Opportunity 为 Shadow 实验路径
            </p>
          </div>
          <button
            type="button"
            className="btn-secondary !py-1.5 text-xs"
            onClick={() => void load()}
            disabled={busy}
          >
            {loading ? '刷新中…' : '刷新'}
          </button>
        </div>
      </div>

      <div className="space-y-5 px-5 py-5 sm:px-6" id={statusId}>
        {loading && !data ? (
          <div className="space-y-3" role="status" aria-live="polite">
            <span className="sr-only">正在加载 Opportunity 工作流</span>
            <div className="skeleton h-16" />
            <div className="skeleton h-16" />
            <div className="skeleton h-24" />
          </div>
        ) : null}

        {error ? (
          <div
            className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300"
            role="alert"
          >
            {error}
            <button type="button" className="ml-3 underline" onClick={() => void load()}>
              重试
            </button>
          </div>
        ) : null}

        {msg ? (
          <p className="text-xs text-farm-dark dark:text-farm" role="status" aria-live="polite">
            {msg}
          </p>
        ) : null}

        {data ? (
          <>
            <div className="grid gap-3 sm:grid-cols-2">
              <LegacyDecisionBadge legacy={data.legacy} />
              <OpportunityAssessmentSummary
                opportunity={data.opportunity}
                state={data.workflow.state}
              />
            </div>

            <NextActionCard
              label={primary.label}
              busy={mutating}
              disabled={busy}
              onClick={primary.onClick}
              guidanceOnly={primary.guidanceOnly}
            />

            <div>
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-ink-muted">
                行动计划
              </h3>
              <ActionPlanAccordion items={data.workflow.action_plan} />
            </div>

            <BlockerAndUpgradeConditions
              blockers={data.workflow.blockers}
              upgrades={data.workflow.upgrade_conditions}
            />

            <div>
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-ink-muted">
                证据摘要
              </h3>
              <EvidenceSummary evidence={data.evidence} />
            </div>

            <div
              ref={validationRef}
              tabIndex={-1}
              className="outline-none"
              aria-label="验证面板"
            >
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-ink-muted">
                验证
              </h3>
              <ValidationPanel
                projectId={projectId}
                projection={data}
                busy={busy}
                onStart={(wc) => void startValidation(wc)}
                onTransition={(s) => void patchLifecycle(s)}
                onSaveOutcome={(p) => void saveOutcome(p)}
              />
            </div>

            {(data.review_at || data.expires_at) && (
              <p className="text-[11px] text-ink-faint">
                复评 {formatTs(data.review_at)} · 过期 {formatTs(data.expires_at)}
              </p>
            )}
          </>
        ) : null}

        {!loading && !data && !error ? (
          <p className="text-sm text-ink-faint" role="status">
            暂无工作流数据。
          </p>
        ) : null}
      </div>
    </section>
  );
}
