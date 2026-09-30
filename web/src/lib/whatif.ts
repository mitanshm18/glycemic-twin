/**
 * Pure helpers for the what-if comparison (unit-tested). They describe how the model's scenario
 * estimate sits relative to the alert threshold, in neutral words: a position, never advice.
 */

export type ThresholdMove = "crosses-above" | "falls-below" | "closer" | "further" | "same";

export interface ThresholdRelation {
  move: ThresholdMove;
  /** scenario side of the threshold */
  above: boolean;
  /** percentage points from the threshold, now and before */
  gapPp: number;
  wasPp: number;
  text: string;
}

const pp = (v: number) => Math.round(Math.abs(v) * 1000) / 10; // one decimal of a percentage point

export function thresholdRelation(baseline: number, scenario: number, threshold: number): ThresholdRelation {
  const before = baseline >= threshold;
  const after = scenario >= threshold;
  const gapPp = pp(scenario - threshold);
  const wasPp = pp(baseline - threshold);
  if (!before && after) return { move: "crosses-above", above: true, gapPp, wasPp, text: "Crosses above the alert threshold" };
  if (before && !after) return { move: "falls-below", above: false, gapPp, wasPp, text: "Falls below the alert threshold" };
  const side = after ? "above" : "below";
  if (gapPp === wasPp) return { move: "same", above: after, gapPp, wasPp, text: `Stays ${side} the alert threshold` };
  // "closer" / "further" is geometry on the probability scale, not a judgement of the scenario
  const move: ThresholdMove = gapPp < wasPp ? "closer" : "further";
  return { move, above: after, gapPp, wasPp, text: `Stays ${side} the alert threshold, ${move} to it` };
}

/** What the screen reader hears once a scenario result has arrived (never on every frame). */
export function scenarioSummary(baseline: number, scenario: number, threshold: number): string {
  const d = (scenario - baseline) * 100;
  const dir = Math.abs(d) < 0.05 ? "the same as" : `${Math.abs(d).toFixed(1)} percentage points ${d > 0 ? "higher than" : "lower than"}`;
  return `Scenario estimate ${Math.round(scenario * 100)}%, ${dir} as logged (${Math.round(baseline * 100)}%). ${thresholdRelation(baseline, scenario, threshold).text}.`;
}

export interface QuickScenario {
  lever: "carbs_g" | "fiber_g" | "active_min_3h";
  delta: number;
  label: string;
}

/** A few one-step scenarios on levers the model supports; nothing about treatment. */
export const QUICK: QuickScenario[] = [
  { lever: "carbs_g", delta: -20, label: "−20 g carbs" },
  { lever: "fiber_g", delta: 10, label: "+10 g fiber" },
  { lever: "active_min_3h", delta: 30, label: "+30 active min" },
];
