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
  /** 资格否决:no_participation_path = 分数够但缺参与路径（被从 FARM 压回 WATCH,
      需要人工验证官网/Twitter 找任务入口）。响应里仅在后端甄别过时出现。 */
  veto?: string | null;
  /** 用户自主「不参与」标记（veto 是系统判断，这个是自己点的）。
      与 label=IGNORE 刻意分开：模型结论与用户决定要能被分别撤掉。 */
  skipped?: boolean;
  url?: string | null;
  source?: string | null;
  reason?: string[];
  reason_zh?: string[];
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
  /** 今日 API 调用次数（后端真实统计，可能缺省） */
  apiCallsToday?: number | null;
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
    apiCallsToday: raw.status?.api_calls_today ?? null,
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
  recommended_action_zh?: string;
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
  code_zh?: string;
  severity: string;
  severity_zh?: string;
  message: string;
  message_zh?: string;
}

export interface UpgradeConditionProjection {
  code: string;
  message: string;
  message_zh?: string;
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
  factor_key_zh?: string;
  value: unknown;
  value_type: string;
  observation_type: string;
  source_url: string;
  source_type: string;
  source_type_zh?: string;
  source_grade: SourceGrade;
  verification_status: string;
  verification_status_zh?: string;
  observed_at: string;
  effective_at: string | null;
  expires_at: string | null;
  freshness: EvidenceFreshness;
  freshness_zh?: string;
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

/** 多钱包防女巫与资金分配建议 (US-019 / W12-01). */
export interface MultiWalletHygieneRule {
  rule_id: string;
  title: string;
  description: string;
  severity: 'critical' | 'warning' | 'tip';
}

export interface MultiWalletStrategy {
  project_id: string;
  project_name: string;
  status: 'recommended' | 'selective' | 'ineligible';
  recommended_wallets_min: number;
  recommended_wallets_max: number;
  recommended_wallets_optimal: number;
  tier: 'not_recommended' | 'single_curated' | 'small_cluster' | 'medium_scale';
  tier_zh: string;
  strategy_summary: string;
  capital_per_wallet_usd_min: number;
  capital_per_wallet_usd_max: number;
  total_capital_usd_min: number;
  total_capital_usd_max: number;
  capital_notes: string;
  weekly_hours_per_wallet: number;
  total_weekly_hours: number;
  hygiene_guidelines: MultiWalletHygieneRule[];
  risk_warnings: string[];
}

/** 项目演化时间轴与历史指标 (Roadmap §24.3 / W12-02). */
export interface TimelinePoint {
  snapshot_id: number;
  run_id: string;
  score: number | null;
  label: string | null;
  stage: string | null;
  weight_version: string | null;
  created_at: string;
  diff_from_previous_score?: number | null;
}

export interface StageTransition {
  from_stage: string;
  to_stage: string;
  timestamp: string;
}

export interface ProjectEvolution {
  project_id: string;
  project_name: string;
  score_trend: 'rising' | 'falling' | 'stable' | 'insufficient_data';
  score_volatility: number;
  stage_progression: string[];
  stage_transitions: StageTransition[];
  label_history: string[];
  timeline: TimelinePoint[];
  first_seen_at: string | null;
  latest_snapshot_at: string | null;
  snapshot_count: number;
  llm_context_summary: string;
}

/** 用户偏好画像与记忆向量 (Roadmap §24.3 / §25.5.3 / W12-02). */
export interface UserProfileData {
  user_id: string;
  sector_affinity: Record<string, number>;
  risk_tolerance: 'conservative' | 'moderate' | 'aggressive';
  favorite_sectors: string[];
  engagement_summary: {
    feedback_count?: number;
    interaction_count?: number;
    watchlist_count?: number;
    skip_count?: number;
    total_signals: number;
  };
  inferred_at: string;
  is_cleared: boolean;
}

/** 异常检测与质量告警 (W12-04 / DATA_QUALITY.md §4). */
export type AnomalySeverity = 'info' | 'warning' | 'critical';

export interface AnomalyItem {
  id: string;
  type: string;
  severity: AnomalySeverity;
  title: string;
  description: string;
  metric_name: string;
  metric_value: number | string;
  threshold: number | string;
  details?: Record<string, unknown>;
}

export interface ScoreDriftSummary {
  total_projects: number;
  mean_score: number;
  median_score: number;
  stddev_score: number;
  zero_score_count: number;
  zero_score_ratio: number;
  label_counts: Record<string, number>;
  label_ratios: Record<string, number>;
  baseline_mean: number;
  mean_drift: number;
  out_of_bounds_count: number;
}

export interface DataQualitySummary {
  p0_completeness: number;
  p1_completeness: number;
  p0_missing_count: number;
  p1_missing_count: number;
  quarantine_pending: number;
  stale_sources: string[];
  total_sources_monitored: number;
}

export interface AnomalyReport {
  overall_status: 'healthy' | 'warning' | 'critical';
  checked_at: string;
  total_anomalies: number;
  critical_count: number;
  warning_count: number;
  info_count: number;
  drift_summary: ScoreDriftSummary;
  quality_summary: DataQualitySummary;
  anomalies: AnomalyItem[];
}

export interface WatchedWallet {
  id: number;
  address: string;
  label: string;
  chain: string;
  active: boolean;
  created_at: string;
}

export interface WatchedWalletsResponse {
  wallets: WatchedWallet[];
  total: number;
  active_count: number;
}


