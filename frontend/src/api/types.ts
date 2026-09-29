export type UserRole = "admin" | "user";

export interface AuthUser {
  id: string;
  username: string;
  role: UserRole;
  must_change_password: boolean;
}

export interface ApiErrorPayload {
  error: {
    code: string;
    message: string;
    fields?: Record<string, string[]>;
  };
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface PoolDocument {
  format_version: 2;
  id: string;
  name: string;
  original_author: string | null;
  rule_name: "rule1";
  rarity_labels: Record<"4" | "5" | "6", string>;
  pool_config: {
    up_share: number;
    five_star: { base_probability: number; pity_enabled: boolean; hard_pity: number };
    six_star_characters: Array<{ name: string; is_up: boolean; is_limited: boolean; up_weight: number | null }>;
    four_star_characters: Array<{ name: string; weight: number }>;
    five_star_characters: Array<{ name: string; weight: number }>;
    rewards: Array<{ name: string; four_star: number; five_star: number; six_star: number }>;
  };
}

export interface Pool extends Omit<PoolDocument, "format_version"> {
  kind: "public" | "private";
  visibility: "public" | "hidden";
  owner_id: string | null;
  owner_name: string | null;
  revision: number;
  updated_at: string;
}

export interface ExperimentParameters {
  draws: string;
  trials: string;
  initial_pity: string;
  initial_five_star_pity: string;
  seed: string | null;
  trace: boolean;
}

export interface ExperimentConfig {
  id: string;
  owner_id: string;
  owner_name: string;
  owner_is_admin: boolean;
  name: string;
  pool_ref: { id: string | null; name: string; available: boolean };
  parameters: ExperimentParameters;
  revision: number;
  created_at: string;
  updated_at: string;
}

export interface JobSummary {
  job_id: string;
  accepted_at: string;
  status: string;
  phase: string;
  draws: string;
  trials: string;
  trace: boolean;
  pool_name_snapshot: string;
  run_id: string | null;
}

export interface JobDetail extends JobSummary {
  owner_id: string;
  completed_units: string;
  total_units: string;
  phase_completed: string | null;
  phase_total: string | null;
  error: string | null;
  persistence_error: string | null;
  history_saved: boolean;
  cancel_requested: boolean;
  duration_seconds: number | null;
  parameters: ExperimentParameters;
  pool_source: { id: string; revision: number; name: string; original_author: string };
}

export interface RunSummary {
  id: string;
  owner_id: string;
  created_at: string;
  rule_name: string;
  pool_name_snapshot: string;
  original_author_snapshot: string;
  pool_id_snapshot: string;
  pool_revision_snapshot: number;
  draws: string;
  trials: string;
  seed: string;
  trace: boolean;
  record_count: string;
}

export interface RunResult {
  id?: string;
  run_id?: string;
  rule_name: string;
  rule_version: string;
  main_draws: number;
  bonus_draws: number;
  total_draws: number;
  trials: number;
  seed: string;
  initial_pity: number;
  initial_five_star_pity: number;
  trace_enabled: boolean;
  record_count: number;
  duration_seconds: number | null;
  mean_six_stars: number;
  theoretical_expected_count: number;
  mean_count_relative_error: number | null;
  pool_id_snapshot?: string;
  pool_revision_snapshot?: number;
  pool_name_snapshot?: string;
  pool_config: PoolDocument["pool_config"] & { rarity_labels?: Record<"4" | "5" | "6", string> };
}

export interface TraceRecord {
  trial_index: number;
  draw_index: number;
  source: "main" | "bonus";
  source_index: number;
  main_draws_completed: number;
  bonus_event: string | null;
  main_state_before: { misses_since_six_star: number; misses_since_five_or_higher: number };
  main_state_after: { misses_since_six_star: number; misses_since_five_or_higher: number };
  draw_result: { outcome: {
    rarity: 4 | 5 | 6;
    character_name: string | null;
    is_up: boolean;
    is_limited: boolean;
    rewards: Record<string, number>;
    five_star_pity_triggered: boolean;
    six_star_hard_pity_triggered: boolean;
  }; probabilities: { four_star: number; five_star: number; six_star: number };
    state_before: { misses_since_six_star: number; misses_since_five_or_higher: number };
    state_after: { misses_since_six_star: number; misses_since_five_or_higher: number } };
}

export interface Account {
  id: string;
  username: string;
  role: UserRole;
  enabled: boolean;
  deleting: boolean;
  must_change_password: boolean;
  delete_impact?: Record<string, string>;
}
