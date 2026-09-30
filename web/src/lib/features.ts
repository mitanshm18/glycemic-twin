/**
 * Plain-language names for the 45 model inputs of the frozen contract (ADR-015). Descriptions say
 * what each input IS (from docs/features.md), never what it does to a person: contributions are
 * model associations, not causes.
 */

import { fmtNum } from "./format";

export type FeatureGroup = "glucose" | "meal" | "context" | "wearable" | "clinical" | "personal";

export interface FeatureInfo {
  label: string;
  group: FeatureGroup;
  unit?: string;
  digits?: number;
  /** what the input is, one short clause */
  what: string;
  format?: (v: number) => string;
}

const yesNo = (v: number) => (v >= 0.5 ? "yes" : "no");
const pct = (v: number) => `${Math.round(v * 100)}%`;

export const FEATURES: Record<string, FeatureInfo> = {
  g_last: { label: "Glucose at meal start", group: "glucose", unit: "mg/dL", what: "last native Dexcom reading within 15 min before the meal" },
  g_age_min: { label: "Age of that reading", group: "glucose", unit: "min", what: "minutes since the last native reading" },
  slope_15: { label: "Glucose trend, 15 min", group: "glucose", unit: "mg/dL/min", digits: 2, what: "least-squares slope over the 15 min before the meal" },
  slope_30: { label: "Glucose trend, 30 min", group: "glucose", unit: "mg/dL/min", digits: 2, what: "least-squares slope over the 30 min before the meal" },
  sd_60: { label: "Glucose variability, 1 h", group: "glucose", unit: "mg/dL", digits: 1, what: "standard deviation of readings in the last hour" },
  mean_180: { label: "Mean glucose, 3 h", group: "glucose", unit: "mg/dL", what: "mean of readings in the last 3 hours" },
  min_180: { label: "Lowest glucose, 3 h", group: "glucose", unit: "mg/dL", what: "minimum reading in the last 3 hours" },
  max_180: { label: "Highest glucose, 3 h", group: "glucose", unit: "mg/dL", what: "maximum reading in the last 3 hours" },
  tir_24h: { label: "Time in range, 24 h", group: "glucose", what: "share of readings within 70–180 mg/dL in the last day", format: pct },
  g_overnight_baseline: { label: "Overnight baseline", group: "glucose", unit: "mg/dL", what: "median glucose 02:00–06:00 on completed nights" },
  g_vs_baseline: { label: "Glucose vs overnight baseline", group: "glucose", unit: "mg/dL", what: "meal-start glucose minus the overnight baseline" },
  carbs_g: { label: "Carbohydrate", group: "meal", unit: "g", what: "logged carbohydrate of this meal" },
  protein_g: { label: "Protein", group: "meal", unit: "g", what: "logged protein of this meal" },
  fat_g: { label: "Fat", group: "meal", unit: "g", what: "logged fat of this meal" },
  fiber_g: { label: "Fiber", group: "meal", unit: "g", what: "logged fiber of this meal" },
  calories_kcal: { label: "Energy", group: "meal", unit: "kcal", what: "logged energy of this meal" },
  meal_breakfast: { label: "Logged as breakfast", group: "meal", what: "whether this meal was logged as breakfast", format: yesNo },
  meal_lunch: { label: "Logged as lunch", group: "meal", what: "whether this meal was logged as lunch", format: yesNo },
  meal_dinner: { label: "Logged as dinner", group: "meal", what: "whether this meal was logged as dinner", format: yesNo },
  meal_snack: { label: "Logged as snack", group: "meal", what: "whether this meal was logged as a snack", format: yesNo },
  hour_sin: { label: "Time of day (sine)", group: "meal", digits: 2, what: "meal time on a 24-hour circle" },
  hour_cos: { label: "Time of day (cosine)", group: "meal", digits: 2, what: "meal time on a 24-hour circle" },
  carbs_prev_3h: { label: "Carbohydrate, previous 3 h", group: "context", unit: "g", what: "carbohydrate logged in the 3 hours before this meal" },
  invalid_meal_prev_3h: { label: "Unusable meal log, previous 3 h", group: "context", what: "an earlier meal in the last 3 h had unusable macros", format: yesNo },
  mins_since_meal: { label: "Time since previous meal", group: "context", unit: "min", what: "minutes since the previous logged meal" },
  hr_30: { label: "Heart rate, 30 min", group: "wearable", unit: "bpm", what: "mean heart rate in the 30 min before the meal" },
  hr_resting: { label: "Resting heart rate", group: "wearable", unit: "bpm", what: "10th percentile of sedentary heart rate on earlier days" },
  hr_delta: { label: "Heart rate above resting", group: "wearable", unit: "bpm", what: "30-minute heart rate minus resting" },
  mets_available: { label: "Wearable reports METs", group: "wearable", what: "whether activity intensity is recorded at all", format: yesNo },
  mets_60: { label: "Activity intensity, 1 h", group: "wearable", unit: "METs", digits: 1, what: "mean METs in the hour before the meal" },
  active_min_3h: { label: "Active minutes, 3 h", group: "wearable", unit: "min", what: "minutes at ≥ 3 METs in the 3 hours before the meal" },
  activity_kcal_60: { label: "Activity energy, 1 h", group: "wearable", unit: "kcal/min", digits: 2, what: "mean activity calories per minute in the last hour" },
  hr_age_min: { label: "Age of heart-rate data", group: "wearable", unit: "min", what: "minutes since the last heart-rate value" },
  hba1c_pct: { label: "HbA1c", group: "clinical", unit: "%", digits: 1, what: "baseline HbA1c (bio.csv)" },
  fasting_glucose_mgdl: { label: "Fasting glucose", group: "clinical", unit: "mg/dL", what: "baseline fasting plasma glucose" },
  fasting_insulin_uu_ml: { label: "Fasting insulin", group: "clinical", unit: "µU/mL", digits: 1, what: "baseline fasting insulin" },
  homa_ir: { label: "HOMA-IR", group: "clinical", digits: 2, what: "fasting glucose × fasting insulin / 405 (derived)" },
  bmi: { label: "BMI", group: "clinical", unit: "kg/m²", digits: 1, what: "baseline body-mass index" },
  age_years: { label: "Age", group: "clinical", unit: "y", what: "age at the start of the study" },
  sex_female: { label: "Recorded sex female", group: "clinical", what: "bio.csv Gender (F=1, M=0)", format: yesNo },
  triglycerides_mgdl: { label: "Triglycerides", group: "clinical", unit: "mg/dL", what: "baseline fasting triglycerides" },
  hdl_mgdl: { label: "HDL cholesterol", group: "clinical", unit: "mg/dL", what: "baseline HDL cholesterol" },
  p_personal: { label: "Personal response rate", group: "personal", what: "this person's shrunk rate of meals above 180, from closed past windows", format: pct },
  rise_offset_mgdl: { label: "Personal rise offset", group: "personal", unit: "mg/dL", digits: 1, what: "how much more (or less) this person's glucose rose than the population model expects" },
  personal_weight: { label: "Personal evidence weight", group: "personal", what: "how much of the personal estimate comes from the person's own meals", format: pct },
};

export const GROUP_LABEL: Record<FeatureGroup, string> = {
  glucose: "Glucose",
  meal: "This meal",
  context: "Earlier meals",
  wearable: "Wearable",
  clinical: "Clinical baseline",
  personal: "Personal response",
};

export function featureInfo(name: string): FeatureInfo {
  return FEATURES[name] ?? { label: name, group: "context", what: "model input" };
}

/** Value with unit, e.g. "142 mg/dL", "38%", "yes", "—" when missing. */
export function fmtFeature(name: string, v: number | null | undefined): string {
  const f = featureInfo(name);
  if (v === null || v === undefined || !Number.isFinite(v)) return "missing";
  if (f.format) return f.format(v);
  const n = fmtNum(v, f.digits ?? 0);
  return f.unit ? `${n} ${f.unit}` : n;
}
