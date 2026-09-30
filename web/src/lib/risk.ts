/**
 * Shared language for risk, lifecycle and uncertainty. Every status has a text label and a glyph,
 * so meaning never depends on color alone.
 */

import type { Phase, RiskStatus, UncertaintyLevel } from "./api/types";

export type Tone = "risk" | "success" | "warning" | "accent" | "model" | "neutral";

export interface RiskView {
  tone: Tone;
  label: string;
  short: string;
  glyph: "up" | "down" | "dash";
}

/** Probability vs the model's alert threshold. */
export function riskView(status: RiskStatus, p: number | null, threshold: number | null): RiskView {
  if (status === "not_applicable") {
    return { tone: "neutral", label: "Outside the model's population", short: "Not scored", glyph: "dash" };
  }
  if (status !== "scored" || p === null || threshold === null) {
    return { tone: "neutral", label: "No prediction at this moment", short: "No prediction", glyph: "dash" };
  }
  return p >= threshold
    ? { tone: "risk", label: "At or above the alert threshold", short: "Above threshold", glyph: "up" }
    : { tone: "success", label: "Below the alert threshold", short: "Below threshold", glyph: "down" };
}

export const PHASES: Phase[] = ["COLD_START", "WARMING", "PERSONALIZED"];

export const PHASE_LABEL: Record<Phase, string> = {
  COLD_START: "Cold start",
  WARMING: "Warming up",
  PERSONALIZED: "Personalized",
};

export const PHASE_TONE: Record<Phase, Tone> = {
  COLD_START: "neutral",
  WARMING: "warning",
  PERSONALIZED: "accent",
};

export const PHASE_HELP: Record<Phase, string> = {
  COLD_START: "No meal window has closed yet: estimates use the population prior only.",
  WARMING: "Some closed meals, but the person's own evidence does not yet outweigh the population.",
  PERSONALIZED: "The person's own closed meals now dominate the personal estimates.",
};

export const UNCERTAINTY_TONE: Record<UncertaintyLevel, Tone> = {
  low: "success",
  moderate: "warning",
  high: "risk",
};

export const UNCERTAINTY_LABEL: Record<UncertaintyLevel, string> = {
  low: "Low uncertainty",
  moderate: "Moderate uncertainty",
  high: "High uncertainty",
};

export const GROUP_LABEL: Record<string, string> = {
  healthy: "Normoglycemic",
  prediabetes: "Prediabetes",
  T2D: "Type 2 diabetes",
  unknown: "Unknown",
};

/** The outcome the model predicts, stated once and reused verbatim. */
export const OUTCOME = "Dexcom glucose above 180 mg/dL within 120 min of the meal";
export const THRESHOLD_MGDL = 180;
export const HORIZON_MIN = 120;
