/**
 * API contract, mirrored by hand from the FastAPI schemas (api/src/twin_api/schemas.py,
 * routers/insights.py) and the twin-state/1 and twin-scenario/1 JSON schemas in docs/schemas/.
 * Timestamps of observations are naive ISO strings (dataset clock); `created_at`/`registered_at`
 * are real UTC timestamps.
 */

export type Naive = string;
export type Iso = string;

export type Role = "clinician" | "admin";

export interface User {
  id: number;
  username: string;
  role: Role;
  is_active: boolean;
}

export interface Providers {
  password: boolean;
  google: boolean;
}

export interface LoginOut {
  user: User;
  csrf_token: string;
  expires_at: Iso;
}

export interface Ready {
  ready: boolean;
  database: boolean;
  migrations_at_head: boolean;
  active_model: string | null;
  model_compatible: boolean;
  support_profile: boolean;
  problems: string[];
}

// ------------------------------------------------------------------ patients

export type GlycemicGroup = "healthy" | "prediabetes" | "T2D" | "unknown";

export interface TwinStateSummary {
  state_id: string;
  as_of: Naive;
  lifecycle_phase: Phase;
  risk_status: RiskStatus;
  probability: number | null;
  current_meal_id: string | null;
  model_version: string | null;
  created_at: Iso;
}

export interface PatientOverview {
  id: number;
  external_ref: string;
  glycemic_group: GlycemicGroup;
  data_from: Naive | null;
  data_to: Naive | null;
  meals: number;
  eligible_meals: number;
  latest_state: TwinStateSummary | null;
}

export interface PatientDetail {
  id: number;
  external_ref: string;
  glycemic_group: GlycemicGroup;
  data_from: Naive | null;
  data_to: Naive | null;
  meals: number;
  eligible_meals: number;
  source_label: string;
  ingestion_run_id: number;
  cgm_readings: number;
  cgm_native_readings: number;
  wearable_minutes: number;
}

export interface ClinicalField {
  field: string;
  value_num: number | null;
  value_text: string | null;
  unit: string | null;
  provenance: "observed" | "derived";
  derivation: string | null;
  quality_flag: string | null;
  source_file: string | null;
  source_column: string | null;
}

export interface CgmPoint {
  ts: Naive;
  dexcom_mgdl: number | null;
  dexcom_is_native: boolean;
  libre_mgdl: number | null;
}

export interface WearablePoint {
  ts: Naive;
  hr_bpm: number | null;
  mets: number | null;
  activity_kcal: number | null;
}

export interface Meal {
  meal_id: string;
  started_at: Naive;
  meal_type: string | null;
  carbs_g: number | null;
  protein_g: number | null;
  fat_g: number | null;
  fiber_g: number | null;
  calories_kcal: number | null;
  macro_validity: string;
  macro_reasons: string | null;
  image_path: string | null;
}

export interface MealOutcome {
  meal_id: string;
  started_at: Naive;
  labels_version: number;
  label: 0 | 1 | null;
  frozen_usable: boolean;
  eligible: boolean;
  waterfall_reason: string;
  exclusion_reasons: string | null;
  window_coverage: number;
  peak_mgdl: number | null;
  peak_native_mgdl: number | null;
  pre_meal_native_mgdl: number | null;
  note: string;
}

// ------------------------------------------------------------------ twin-state/1 (ADR-017)

export type Phase = "COLD_START" | "WARMING" | "PERSONALIZED";
export type RiskStatus = "scored" | "not_applicable" | "unavailable";
export type UncertaintyLevel = "low" | "moderate" | "high";

export interface ModelIdentity {
  model_version: string;
  model_name: string;
  feature_set: string;
  n_columns: number;
  contract_version: number;
  contract_sha256: string;
  features_sha256: string;
  labels_sha256: string;
  training_config_sha256: string | null;
  dataset_content_sha256: string | null;
  dataset_label: string | null;
  created_utc: string | null;
  threshold: number;
  params: Record<string, unknown>;
}

export interface Uncertainty {
  level: UncertaintyLevel;
  reasons: string[];
  outcome_entropy_bits: number | null;
  distance_to_threshold: number | null;
  personal_weight: number | null;
  missing_inputs: string[];
  out_of_support_inputs: string[];
  support_checked: boolean;
  note: string;
}

export interface RiskEstimate {
  status: RiskStatus;
  reason: string | null;
  probability: number | null;
  threshold: number | null;
  above_threshold: boolean | null;
  features_at: Naive | null;
  model_inputs: Record<string, number | null> | null;
  uncertainty: Uncertainty | null;
}

export interface ClinicalStateField {
  name: string;
  value: number | null;
  provenance: "observed" | "derived";
  source: string;
}

export interface ClosedMeal {
  meal_id: string;
  started_at: Naive;
  window_closed_at: Naive;
  frozen_usable: boolean;
  label: 0 | 1 | null;
  rise_native_mgdl: number | null;
}

export interface CurrentMeal {
  meal_id: string | null;
  origin: "logged" | "proposed";
  started_at: Naive;
  prediction_window_closes_at: Naive;
  minutes_since_start: number;
  meal_type: string | null;
  carbs_g: number | null;
  protein_g: number | null;
  fat_g: number | null;
  fiber_g: number | null;
  calories_kcal: number | null;
  macros_valid: boolean;
  applicable: boolean;
  not_applicable_reasons: string[];
}

export interface PersonalResponse {
  closed_usable_meals: number;
  closed_positive_meals: number;
  population_rate: number;
  p_personal: number;
  rise_offset_mgdl: number;
  personal_weight: number;
  prior_fitted_on_people: number;
  prior_fitted_on_meals: number;
}

export interface TwinState {
  schema_version: string;
  state_id: string;
  patient_id: number;
  as_of: Naive;
  lifecycle: {
    phase: Phase;
    reason: string;
    closed_usable_meals: number;
    personal_weight: number | null;
    next_phase_requires: string | null;
  };
  static_clinical: { glycemic_group: string | null; fields: ClinicalStateField[] };
  personal_baselines: {
    overnight_glucose_mgdl: number | null;
    resting_hr_bpm: number | null;
    time_in_range_24h: number | null;
  };
  current_physiology: {
    glucose_mgdl: number | null;
    glucose_age_min: number | null;
    slope_15_mgdl_per_min: number | null;
    slope_30_mgdl_per_min: number | null;
    sd_60_mgdl: number | null;
    glucose_vs_baseline_mgdl: number | null;
    hr_30_bpm: number | null;
    hr_delta_bpm: number | null;
    mets_60: number | null;
    active_min_3h: number | null;
    activity_kcal_60: number | null;
  };
  recent_history: {
    glucose_mean_180_mgdl: number | null;
    glucose_min_180_mgdl: number | null;
    glucose_max_180_mgdl: number | null;
    carbs_prev_3h_g: number | null;
    mins_since_previous_meal: number | null;
    meals_logged_24h: number;
    meals_logged_total: number;
    recent_closed_meals: ClosedMeal[];
  };
  current_meal: CurrentMeal | null;
  personal_response: PersonalResponse | null;
  risk: RiskEstimate;
  freshness: {
    last_cgm_native_at: Naive | null;
    cgm_age_min: number | null;
    cgm_stale: boolean;
    last_wearable_at: Naive | null;
    wearable_age_min: number | null;
    wearable_stale: boolean;
    last_meal_at: Naive | null;
  };
  provenance: {
    source: string;
    record_sha256: string;
    cgm_native_readings_used: number;
    wearable_minutes_used: number;
    meals_logged_used: number;
    closed_meal_ids_used: string[];
    current_meal_id: string | null;
    max_source_ts: Naive | null;
    config_sha256: Record<string, string>;
    engine_version: string;
    model: ModelIdentity | null;
  };
  disclaimer: string;
}

export interface StateDiff {
  from_state_id: string;
  to_state_id: string;
  from_as_of: Naive;
  to_as_of: Naive;
  explanations: string[];
  changes: Array<{ path: string; before: unknown; after: unknown }>;
}

export interface Explanation {
  state_id: string;
  model_version: string;
  method: "tree_shap" | "linear_exact";
  scale: string;
  base_value: number;
  raw_score: number;
  probability: number | null;
  contributions: Array<{ feature: string; value: number | null; contribution: number }>;
  note: string;
}

// ------------------------------------------------------------------ what-if (twin-scenario/1)

export type Lever = "carbs_g" | "fiber_g" | "protein_g" | "fat_g" | "active_min_3h";

export interface ChangedInput {
  feature: string;
  before: number | null;
  after: number | null;
  support_lo: number | null;
  support_hi: number | null;
  in_support: boolean;
}

export interface ScenarioResult {
  scenario_id: string;
  status: "ok" | "out_of_support";
  patient_id: number;
  as_of: Naive;
  base_state_id: string;
  meal_id: string | null;
  changes: Partial<Record<Lever, number>>;
  baseline_probability: number;
  scenario_probability: number | null;
  risk_delta: number | null;
  changed_inputs: ChangedInput[];
  held_fixed: string;
  uncertainty: Uncertainty | null;
  model: ModelIdentity;
  disclaimer: string;
  kind: string;
}

// ------------------------------------------------------------------ models

export interface ModelVersion {
  id: number;
  model_version: string;
  model_type: string;
  feature_set: string;
  n_columns: number;
  contract_version: number;
  contract_sha256: string;
  features_sha256: string;
  labels_sha256: string;
  training_config_sha256: string | null;
  dataset_content_sha256: string;
  dataset_label: string | null;
  threshold: number;
  artifact_path: string;
  artifact_sha256: string;
  bundle_created_utc: string | null;
  support_profile_id: number | null;
  is_active: boolean;
  registered_at: Iso;
}

export interface Interval {
  lo: number | null;
  hi: number | null;
}

export interface PopulationMetrics {
  meals: number;
  positives: number | null;
  participants: number | null;
  prevalence: number | null;
  auroc: number | null;
  pr_auc: number | null;
  brier: number | null;
  brier_skill: number | null;
  calibration_slope: number | null;
  calibration_intercept: number | null;
  ece: number | null;
  ci: Record<string, Interval>;
}

export interface Evaluation {
  report: string;
  dataset_label: string;
  dataset_content_sha256: string;
  active_run: string;
  primary_run: string;
  counts: Record<string, number>;
  runs: Array<{
    run: string;
    model: string;
    feature_set: string;
    n_columns: number;
    target: PopulationMetrics;
    healthy: PopulationMetrics;
  }>;
  active_per_fold: Array<{
    fold: number;
    participants: number;
    meals: number;
    positives: number;
    auroc: number | null;
    pr_auc: number | null;
    brier: number | null;
    threshold: number | null;
  }>;
  active_calibration_curve: Array<{
    bin: number;
    n: number;
    mean_predicted: number;
    observed_rate: number;
  }>;
  active_at_threshold: Record<string, number | null>;
  comparisons: Array<{
    comparison: string;
    a: string;
    b: string;
    ran: boolean;
    pr_auc_difference: number | null;
    pr_auc_lo: number | null;
    pr_auc_hi: number | null;
    auroc_difference: number | null;
    auroc_lo: number | null;
    auroc_hi: number | null;
  }>;
  shap_global_importance: Array<{ feature: string; mean_abs_shap: number }>;
  limitations: string[];
}

// ------------------------------------------------------------------ errors

export interface ApiErrorBody {
  error: { code: string; message: string; details?: unknown };
}

// ------------------------------------------------------------------ replay (historical, ADR-018)

export interface Replay {
  id: number;
  patient_id: number;
  start_at: Naive;
  end_at: Naive;
  cursor_at: Naive;
  step_minutes: number;
  last_state_id: string | null;
}

export interface ReplayStep {
  replay: Replay;
  /** the twin at the cursor before this step moved it (recorded data only, up to state.as_of) */
  state: TwinState;
  finished: boolean;
}
