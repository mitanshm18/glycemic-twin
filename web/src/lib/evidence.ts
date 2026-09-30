/**
 * Which part of the patient's record a model input is computed from (pure, unit-tested).
 *
 * The mapping restates the feature definitions (docs/features.md, lib/features.ts): e.g. "Glucose
 * trend, 15 min" IS the slope of the native readings in the 15 minutes before the meal. It is a
 * statement about what an input is built from, never about cause and effect.
 */

import { featureInfo } from "./features";
import { MINUTE, type Millis } from "./time";

export type Evidence =
  /** glucose readings in the `minutes` before the meal start */
  | { kind: "lookback"; feature: string; minutes: number }
  /** earlier meals logged in the `minutes` before this one */
  | { kind: "prior-meals"; feature: string; minutes: number }
  /** the macros / type / time of the current meal */
  | { kind: "meal"; feature: string }
  /** the personal response learned from closed meals */
  | { kind: "personal"; feature: string };

const LOOKBACK: Record<string, number> = {
  g_last: 15,
  g_age_min: 15,
  g_vs_baseline: 15,
  slope_15: 15,
  slope_30: 30,
  sd_60: 60,
  mean_180: 180,
  min_180: 180,
  max_180: 180,
};
const PRIOR: Record<string, number> = {
  carbs_prev_3h: 180,
  invalid_meal_prev_3h: 180,
};

export function evidenceFor(feature: string): Evidence | null {
  if (feature in LOOKBACK) return { kind: "lookback", feature, minutes: LOOKBACK[feature] as number };
  if (feature in PRIOR) return { kind: "prior-meals", feature, minutes: PRIOR[feature] as number };
  const group = featureInfo(feature).group;
  if (group === "meal") return { kind: "meal", feature };
  if (group === "personal") return { kind: "personal", feature };
  return null; // clinical baseline, wearable, day-level context: nothing on this page to point at
}

/** The stretch of the timeline an input is computed from, ending at the meal start. */
export function evidenceRange(e: Evidence, mealStart: Millis): { from: Millis; to: Millis } | null {
  if (e.kind === "lookback" || e.kind === "prior-meals") return { from: mealStart - e.minutes * MINUTE, to: mealStart };
  return null;
}

/** One line for the driver row: where to look. */
export function evidenceText(e: Evidence): string {
  switch (e.kind) {
    case "lookback":
      return `Computed from the native glucose readings in the ${e.minutes} min before the meal.`;
    case "prior-meals":
      return `Computed from meals logged in the ${e.minutes / 60} h before this one.`;
    case "meal":
      return "Taken from this meal's log.";
    case "personal":
      return "Learned from this person's closed meal windows (Personal response).";
  }
}
