export type UserRole = "admin" | "user";

export interface AuthUser {
  id: string;
  username: string;
  role: UserRole;
  must_change_password: boolean;
}

export interface ApiErrorPayload {
  error: { code: string; message: string; fields?: Record<string, string[]> };
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface RuleRarityDocument {
  id: string;
  name: string;
  rank: number;
  base_probability: number;
  soft_enabled: boolean;
  soft_start: number;
  soft_step: number;
  hard_enabled: boolean;
  hard_pity: number;
}

export interface RuleDocument {
  format_version: 1;
  id: string;
  name: string;
  original_author: string | null;
  algorithm: "dynamic_probability";
  rarities: RuleRarityDocument[];
  big_pity: { enabled: boolean; hard_pity: number; target: "first_up"; after_obtain: "disable_after_obtain" | "reset_after_obtain" };
  bonus: { enabled: boolean; at_main_draw: number; draws: number; rarities: RuleRarityDocument[] };
  grant: { enabled: boolean; period: number; quantity: number; target: "first_up" | "pool_selected" };
}

export interface Rule {
  id: string;
  name: string;
  original_author: string;
  algorithm: "dynamic_probability";
  kind: "public" | "private";
  visibility: "public" | "hidden";
  owner_id: string | null;
  owner_name: string | null;
  revision: number;
  reference_count: number;
  structure_locked: boolean;
  document: RuleDocument;
}

export interface PoolDocument {
  format_version: 3;
  id: string;
  name: string;
  original_author: string | null;
  rule_ref: { id: string; name: string };
  rarity_pools: Array<{
    rarity_id: string;
    characters: Array<{ id: string; rarity_id: string; name: string; weight: number; is_up: boolean; is_limited: boolean }>;
    up_enabled: boolean;
    up_share: number;
  }>;
  rarity_labels: Record<string, string>;
  rewards: Array<{ id: string; name: string; amounts: Record<string, number> }>;
  mechanism_targets: Record<string, string>;
}

export interface Pool {
  id: string;
  name: string;
  kind: "public" | "private";
  visibility: "public" | "hidden";
  owner_id: string | null;
  owner_name: string | null;
  original_author: string;
  rule_ref: { id: string; name: string; revision: number };
  document: PoolDocument;
  revision: number;
  updated_at: string;
}

export interface ExperimentParameters {
  draws: string;
  trials: string;
  seed: string | null;
  trace: boolean;
  initial_main_draws: string;
  initial_small_pity: Record<string, string>;
  initial_big_pity: { target_obtained: boolean; misses: string };
}

export interface InitialContext {
  rule_id: string;
  rarity_ids: string[];
  big_mode: "disable_after_obtain" | "reset_after_obtain" | null;
  big_target_id: string | null;
}

export interface EventCounts {
  main_draws: string;
  bonus_draws: string;
  total_draws: string;
  grant_triggers: string;
  granted_characters: string;
  trace_events: string;
}

export interface SimulationPreview {
  parameters: ExperimentParameters;
  current_context: InitialContext;
  counts: { per_trial: EventCounts; total: EventCounts };
  next_triggers: { first_bonus_main_draw: string | null; periodic_grant_main_draw: string | null };
  pool_source: { id: string; name: string; revision: number };
  rule_source: { id: string; name: string; revision: number };
}

interface ProcessEventBase {
  event_format_version: 3;
  trial_index: string;
  event_index: string;
  main_draws_completed: string;
  mechanism_id: string | null;
}

export interface ProcessEventDrawRecord extends ProcessEventBase {
  event_type: "draw";
  draw_index: string;
  source: "main" | "bonus";
  source_index: string;
  grant?: never;
  draw_result: {
    outcome: {
      rarity_id: string;
      character_id: string | null;
      character_name: string | null;
      is_up: boolean;
      is_limited: boolean;
      rewards: Record<string, number>;
      pity_status: { soft_active: string[]; hard_active: string[]; big_forced: boolean };
    };
    probabilities: Record<string, number>;
    character_probability: number | null;
    state_before: { small_pity: Record<string, string>; big_misses: string; big_active: boolean };
    state_after: { small_pity: Record<string, string>; big_misses: string; big_active: boolean };
  };
  main_state_before: { small_pity: Record<string, string>; big_misses: string; big_active: boolean };
  main_state_after: { small_pity: Record<string, string>; big_misses: string; big_active: boolean };
}

export interface ProcessEventGrantRecord extends ProcessEventBase {
  event_type: "character_grant";
  draw_index: null;
  source: null;
  source_index: null;
  draw_result?: never;
  main_state_before?: never;
  main_state_after?: never;
  grant: {
    character_id: string;
    rarity_id: string;
    character_name: string;
    is_up: boolean;
    is_limited: boolean;
    quantity: string;
    trigger_main_draw: string;
  };
}

export type ProcessEventRecord = ProcessEventDrawRecord | ProcessEventGrantRecord;

export interface ExperimentConfig {
  id: string;
  owner_id: string;
  owner_name: string;
  owner_is_admin: boolean;
  name: string;
  pool_ref: { id: string | null; name: string; available: boolean };
  parameters: ExperimentParameters;
  initial_context: InitialContext | null;
  validation_errors: string[];
  current_context: InitialContext | null;
  needs_confirmation: boolean;
  revision: number;
  created_at: string;
  updated_at: string;
}

export interface JobSummary {
  job_id: string; accepted_at: string; status: string; phase: string | null; draws: string; trials: string;
  trace: boolean; pool_name_snapshot: string; rule_name_snapshot: string; run_id: string | null;
}

export interface JobDetail extends JobSummary {
  owner_id: string;
  parameters: ExperimentParameters;
  pool_source: { id: string; revision: number; name: string; original_author: string };
  rule_source: { id: string; revision: number; name: string; author: string };
  initial_context: InitialContext;
  completed_units: string; total_units: string; phase_completed: string | null;
  phase_total: string | null; error: string | null; persistence_error: string | null;
  history_saved: boolean; cancel_requested: boolean; duration_seconds: number | null;
  cleanup_error: string | null;
}

export interface RunSummary {
  id: string; owner_id: string; created_at: string; rule_name: string; pool_name_snapshot: string;
  original_author_snapshot: string; rule_id_snapshot: string; rule_revision_snapshot: number;
  pool_id_snapshot: string; pool_revision_snapshot: number;
  draws: string; trials: string; seed: string; trace: boolean; event_count: string;
}

export type RunEventCounts = EventCounts;

export interface SimulationSummary {
  rarity_counts: Record<string, number>;
  character_counts: Record<string, number>;
  category_counts: Record<string, Record<string, number>>;
  draw_count?: number;
  character_count?: number;
  trigger_count?: number;
  reward_totals?: Record<string, number>;
  pity_triggers?: { soft: Record<string, number>; hard: Record<string, number>; big: number };
  at_least_one?: Record<string, unknown>;
  distributions?: Record<string, unknown>;
}

export interface SimulationGroups {
  draws: { main: SimulationSummary; bonus: SimulationSummary; total: SimulationSummary };
  grants: SimulationSummary;
  acquisitions: SimulationSummary;
}

export interface RunResult {
  result_format_version: 4;
  event_format_version: 3;
  rule_version: string;
  sampling_version: number;
  rng_algorithm: string;
  python_implementation: string;
  python_version: string;
  duration_seconds: number;
  seed: string;
  parameters: ExperimentParameters;
  counts: RunEventCounts;
  trace_enabled: boolean;
  event_count: string;
  rule_snapshot: RuleDocument;
  pool_snapshot: PoolDocument;
  initial_context: InitialContext;
  targets: Record<string, string | null>;
  simulation: SimulationGroups;
  theoretical: SimulationGroups;
  owner_id?: string;
  accepted_at?: string;
  pool_source?: JobDetail["pool_source"];
  rule_source?: JobDetail["rule_source"];
  limit_policy?: Record<string, unknown>;
  id?: string;
  created_at?: string;
  pool_id_snapshot?: string;
  pool_revision_snapshot?: number;
  pool_name_snapshot?: string;
  pool_original_author_snapshot?: string;
  rule_id_snapshot?: string;
  rule_revision_snapshot?: number;
  rule_name_snapshot?: string;
  rule_original_author_snapshot?: string;
}

export interface TracePage<T> { items: T[]; total: string; page: number; page_size: number }

export interface Account {
  id: string; username: string; role: UserRole; enabled: boolean; deleting: boolean;
  must_change_password: boolean; delete_impact?: Record<string, string>;
}
