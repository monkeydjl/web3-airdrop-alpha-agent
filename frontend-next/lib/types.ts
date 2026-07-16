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
    heat_score: number;
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

export interface CollectionSource {
  source_id: string;
  source_name?: string;
  enabled: boolean;
  last_sync?: string | null;
  sync_status?: string | null;
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
