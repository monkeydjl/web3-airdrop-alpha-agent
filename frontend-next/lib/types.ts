export type Label = 'FARM' | 'WATCH' | 'IGNORE';

export interface FundingInfo {
  funding_total_usd?: number | null;
  funding_rounds?: number;
  funding_last_date?: string | null;
  funding_investors?: string[];
  funding_lead_investors?: string[];
  funding_tier?: string;
  funding_quality?: number;
  recent_funding?: boolean;
}

export interface Project {
  id: string;
  name: string;
  sector: string;
  stage: string;
  score: number;
  label: Label;
  confidence: number;
  url?: string | null;
  source?: string | null;
  reason?: string[];
  narrative?: Record<string, unknown> | null;
  team?: Record<string, unknown> | null;
  risk?: Record<string, unknown> | null;
  tokenomics?: Record<string, unknown> | null;
  funding?: FundingInfo | null;
  signals?: Record<string, unknown> | null;
  funding_note?: string | null;
  sub_scores?: Record<string, number> | null;
  weight_version?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface ProjectsResponse {
  projects: Project[];
  total: number;
  page?: number;
  page_size?: number;
}

export interface InsightsData {
  total_projects?: number;
  label_counts: Record<string, number>;
  sector_counts: Record<string, number> | Array<{ sector?: string; count?: number } | [string, number]>;
  hottest_narratives: {
    sector: string;
    avg_heat_score: number;
    project_count: number;
  }[];
  risky_teams: {
    id: string;
    name: string;
    sector: string;
    risk_level: string;
    team_score?: number;
    flags: string[];
  }[];
}

/**
 * 后端 /collections/sources 的真实返回形状。
 *
 * - `config_ready`: 环境/密钥侧是否具备采集能力（collector.is_enabled）
 * - `operator_enabled` / `status.enabled`: 运维台开关（data_sources.enabled）
 * - `is_enabled`: 二者同时为真时才可 trigger
 */
export interface CollectionSourceApi {
  source_id: string;
  source_name?: string;
  source_type?: string;
  is_enabled?: boolean;
  config_ready?: boolean;
  operator_enabled?: boolean;
  status?: {
    enabled?: boolean;
    sync_status?: string | null;
    last_sync?: string | null;
    api_calls_today?: number;
  } | null;
}

/** 归一化后供 UI 直接使用的形状。 */
export interface CollectionSource {
  source_id: string;
  source_name?: string;
  /** 可触发：配置就绪且运维开关打开 */
  enabled: boolean;
  /** 运维开关（PATCH 写入） */
  operatorEnabled: boolean;
  /** .env / key 是否具备采集能力 */
  configReady: boolean;
  last_sync?: string | null;
  sync_status?: string | null;
}

/** 把后端形状摊平成 UI 形状。 */
export function normalizeCollectionSource(raw: CollectionSourceApi): CollectionSource {
  const configReady =
    raw.config_ready !== undefined
      ? Boolean(raw.config_ready)
      : Boolean(raw.is_enabled ?? raw.status?.enabled ?? false);
  const operatorEnabled =
    raw.operator_enabled !== undefined
      ? Boolean(raw.operator_enabled)
      : raw.status?.enabled !== undefined
        ? Boolean(raw.status.enabled)
        : true;
  const enabled =
    raw.is_enabled !== undefined
      ? Boolean(raw.is_enabled)
      : configReady && operatorEnabled;
  return {
    source_id: raw.source_id,
    source_name: raw.source_name,
    enabled,
    operatorEnabled,
    configReady,
    last_sync: raw.status?.last_sync ?? null,
    sync_status: raw.status?.sync_status ?? null,
  };
}

export interface HealthData {
  ok: boolean;
  status: string;
  version?: string;
  db?: string;
  db_backend?: string;
  quarantined_raw?: number;
  auth_required?: boolean;
  feedback_enabled?: boolean;
}

/** Interaction lifecycle statuses — exact match to backend StatusType. */
export type InteractionStatus = 'planned' | 'active' | 'done' | 'abandoned';

/** Workflow projection states — exact match to backend WorkflowState. */
export type WorkflowState =
  | 'NEEDS_EVALUATION'
  | 'REVIEW_REQUIRED'
  | 'ACTIONABLE'
  | 'MONITOR'
  | 'INSUFFICIENT_EVIDENCE'
  | 'BLOCKED'
  | 'NOT_FIT';

export type DecisionStatus =
  | 'ACTIONABLE'
  | 'MONITOR'
  | 'INSUFFICIENT_EVIDENCE'
  | 'NOT_FIT'
  | 'BLOCKED';

export type ActionPhase = 'review' | 'evidence' | 'validation' | 'maintenance' | 'outcome';

export type EligibilityResult = 'unknown' | 'eligible' | 'ineligible';
export type SurvivalResult = 'unknown' | 'passed' | 'disqualified';

export type RiskLevel = 'low' | 'medium' | 'high' | 'critical';
export type SourceGrade = 'A' | 'B' | 'C' | 'D' | 'U';
export type EvidenceFreshness = 'CURRENT' | 'EXPIRED';

export type OpportunityModelVersion = 'opportunity-v2.0';
export type OpportunityProfileVersion = 'low-cost-curated-multiwallet-v1';
export type LegacyModelVersion = 'score-v1.4';
export type WorkflowVersion = 'opportunity-action-workflow-v1';

export interface ProbabilityRange {
  low: number;
  base: number;
  high: number;
}

export interface MoneyRange {
  low: number;
  base: number;
  high: number;
}

export interface SignedMoneyRange {
  low: number;
  base: number;
  high: number;
}

export interface ConfidenceSet {
  event: number;
  eligibility: number;
  reward: number;
  cost: number;
  risk: number;
  quality: number;
  overall: number;
}

export interface RiskSet {
  capital_security: RiskLevel | null;
  eligibility: RiskLevel | null;
  project_failure: RiskLevel | null;
  reward_dilution: RiskLevel | null;
  liquidity: RiskLevel | null;
}

export interface EconomicsResult {
  gross_reward: MoneyRange;
  net_reward: SignedMoneyRange;
  reward_to_cost_ratio: number;
  decision_value: number;
  capital_efficiency: number;
  time_efficiency: number;
}

export interface LegacyDecisionProjection {
  model_version: LegacyModelVersion;
  score: number | null;
  label: string | null;
  reason: string[];
  authoritative: true;
}

export interface OpportunitySummaryProjection {
  shadow: true;
  assessment_id: string | null;
  model_version: OpportunityModelVersion;
  profile_version: OpportunityProfileVersion;
  status: DecisionStatus;
  public_label: Label;
  recommended_action: string;
  blocker_codes: string[];
  watch_reason_codes: string[];
  ignore_reason_codes: string[];
  requires_remediation: boolean;
  confidence: ConfidenceSet;
  event_probability: ProbabilityRange | null;
  eligibility_probability: ProbabilityRange | null;
  survival_probability: ProbabilityRange | null;
  reward_probability: ProbabilityRange | null;
  conditional_reward_usd: MoneyRange | null;
  hard_cost_usd: MoneyRange | null;
  economics: EconomicsResult | null;
  risks: RiskSet;
  /** ISO-8601 datetime string from API JSON. */
  scored_at: string;
  review_at: string;
  expires_at: string;
}

export interface NextActionProjection {
  key: string;
  label: string;
  can_start_validation: boolean;
}

export interface ActionPlanItem {
  id: string;
  sequence: number;
  kind: string;
  phase: ActionPhase;
  title: string;
  description: string;
  required: boolean;
  source: string;
  priority: number;
  task_id: string | null;
  external_url: string | null;
}

export interface BlockerProjection {
  code: string;
  severity: string;
  message: string;
}

export interface UpgradeConditionProjection {
  code: string;
  message: string;
}

export interface WorkflowSection {
  state: WorkflowState;
  next_action: NextActionProjection;
  action_plan: ActionPlanItem[];
  blockers: BlockerProjection[];
  upgrade_conditions: UpgradeConditionProjection[];
}

export interface EvidenceItemProjection {
  evidence_id: string | null;
  factor_key: string;
  value: unknown;
  value_type: string;
  observation_type: string;
  source_url: string;
  source_type: string;
  source_grade: SourceGrade;
  verification_status: string;
  observed_at: string;
  effective_at: string | null;
  expires_at: string | null;
  freshness: EvidenceFreshness;
  age_days: number;
}

export interface EvidenceSection {
  items: EvidenceItemProjection[];
  missing_factor_keys: string[];
  counts_by_grade: Record<SourceGrade, number> | Record<string, number>;
}

/** Seven user-editable outcome fields + auto timestamp — backend _OUTCOME_FIELDS. */
export interface ValidationOutcomeFields {
  actual_hard_cost_usd: number | null;
  actual_time_minutes: number | null;
  eligibility_result: EligibilityResult | null;
  survival_result: SurvivalResult | null;
  disqualification_reason: string | null;
  reward_received_usd: number | null;
  claim_cost_usd: number | null;
  outcome_observed_at: string | null;
}

/** Safe validation.current projection — never includes wallet_cohort_id or addresses. */
export interface ValidationCurrent extends ValidationOutcomeFields {
  id?: number | string;
  project_id?: string;
  status: InteractionStatus | string;
  created_at?: string | null;
  wallet_count?: number | null;
  opportunity_assessment_id?: string | null;
  opportunity_model_version?: OpportunityModelVersion | string | null;
  opportunity_profile_version?: OpportunityProfileVersion | string | null;
}

export interface ValidationHistorySummary {
  total: number;
  by_status: Record<string, number>;
}

export interface ValidationSection {
  current: ValidationCurrent | null;
  history_summary: ValidationHistorySummary;
  allowed_transitions: Record<string, string[]>;
  can_start_validation: boolean;
}

/** Exact nested JSON shape from GET /projects/{id}/opportunity/workflow. */
export interface OpportunityWorkflowProjection {
  workflow_version: WorkflowVersion;
  project_id: string;
  legacy: LegacyDecisionProjection;
  opportunity: OpportunitySummaryProjection | null;
  workflow: WorkflowSection;
  evidence: EvidenceSection;
  validation: ValidationSection;
  review_at: string | null;
  expires_at: string | null;
}

export interface InteractionCreatePayload {
  project_id: string;
  status: InteractionStatus;
  wallet_count: 1 | 2;
  opportunity_assessment_id: string;
  opportunity_model_version: OpportunityModelVersion;
  opportunity_profile_version: OpportunityProfileVersion;
}

export interface InteractionLifecyclePatch {
  status: InteractionStatus;
}

export interface InteractionOutcomePatch extends Partial<ValidationOutcomeFields> {}

/** GET /discoveries 返回的单条原始发现。 */
export interface DiscoveryItem {
  raw_id: string;
  source_id: string;
  dedup_key: string;
  project_id: string | null;
  name: string;
  sector: string | null;
  stage: string | null;
  discovery_score: number;
  processed: boolean;
  discovered_at: string;
}

export interface DiscoveriesResponse {
  items: DiscoveryItem[];
  total: number;
  page: number;
  page_size: number;
}
