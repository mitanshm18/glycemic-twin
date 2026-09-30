/**
 * Pure geometry and outcome logic for the glucose timeline (no React, unit-tested).
 */

import type { CgmPoint, MealOutcome } from "./api/types";
import { THRESHOLD_MGDL } from "./risk";
import { HOUR, parseNaive, type Millis } from "./time";

export interface Pt {
  t: Millis;
  v: number;
}

export function toPoints(cgm: CgmPoint[]): Pt[] {
  return cgm
    .filter((p) => p.dexcom_is_native && p.dexcom_mgdl !== null)
    .map((p) => ({ t: parseNaive(p.ts), v: p.dexcom_mgdl as number }))
    .sort((a, b) => a.t - b.t);
}

export interface Scale {
  (v: number): number;
  domain: [number, number];
  range: [number, number];
  invert: (px: number) => number;
}

export function linear(domain: [number, number], range: [number, number]): Scale {
  const [d0, d1] = domain;
  const [r0, r1] = range;
  const k = d1 === d0 ? 0 : (r1 - r0) / (d1 - d0);
  const f = ((v: number) => r0 + (v - d0) * k) as Scale;
  f.domain = domain;
  f.range = range;
  f.invert = (px: number) => (k === 0 ? d0 : d0 + (px - r0) / k);
  return f;
}

/** Glucose axis: fixed clinical frame (40-300) so charts are comparable; extends if data exceeds it. */
export function glucoseDomain(points: Pt[]): [number, number] {
  let hi = 300;
  let lo = 40;
  for (const p of points) {
    if (p.v > hi) hi = Math.ceil((p.v + 10) / 20) * 20;
    if (p.v < lo) lo = Math.floor((p.v - 10) / 20) * 20;
  }
  return [lo, hi];
}

/** Hourly (or 2/3/6-hourly on narrow charts) ticks aligned to whole hours. */
export function timeTicks(t0: Millis, t1: Millis, maxTicks: number): Millis[] {
  const span = t1 - t0;
  const steps = [1, 2, 3, 6, 12, 24].map((h) => h * HOUR);
  const step = steps.find((s) => span / s <= maxTicks) ?? 24 * HOUR;
  const first = Math.ceil(t0 / step) * step;
  const out: Millis[] = [];
  for (let t = first; t <= t1; t += step) out.push(t);
  return out;
}

/** SVG path; breaks the line across gaps longer than `maxGap` (missing CGM is shown as missing). */
export function linePath(points: Pt[], x: Scale, y: Scale, maxGap = 20 * 60_000): string {
  let d = "";
  let prev: Pt | null = null;
  for (const p of points) {
    const cmd = prev && p.t - prev.t <= maxGap ? "L" : "M";
    d += `${cmd}${x(p.t).toFixed(1)},${y(p.v).toFixed(1)}`;
    prev = p;
  }
  return d;
}

/** Index of the point nearest to time t (binary search). */
export function nearest(points: Pt[], t: Millis): number {
  if (points.length === 0) return -1;
  let lo = 0;
  let hi = points.length - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if ((points[mid] as Pt).t < t) lo = mid;
    else hi = mid;
  }
  const a = points[lo] as Pt;
  const b = points[hi] as Pt;
  return Math.abs(a.t - t) <= Math.abs(b.t - t) ? lo : hi;
}

export interface WindowOutcome {
  /** first native reading above the threshold inside (t0, t0 + horizon], if any */
  firstAbove: Pt | null;
  /** highest native reading inside the window */
  peak: Pt | null;
  /** frozen labels.v1 outcome (authoritative; 1-minute Dexcom basis, ADR-013) */
  label: 0 | 1 | null;
}

export function windowOutcome(points: Pt[], t0: Millis, horizonMin: number, outcome: MealOutcome | undefined): WindowOutcome {
  const end = t0 + horizonMin * 60_000;
  let firstAbove: Pt | null = null;
  let peak: Pt | null = null;
  for (const p of points) {
    if (p.t <= t0 || p.t > end) continue;
    if (!peak || p.v > peak.v) peak = p;
    if (!firstAbove && p.v > THRESHOLD_MGDL) firstAbove = p;
  }
  return { firstAbove, peak, label: outcome?.frozen_usable ? outcome.label : null };
}

export type Verdict = "true_alert" | "false_alarm" | "missed" | "true_quiet";

export function verdict(probability: number, threshold: number, label: 0 | 1): Verdict {
  const flagged = probability >= threshold;
  if (flagged) return label === 1 ? "true_alert" : "false_alarm";
  return label === 1 ? "missed" : "true_quiet";
}

export const VERDICT_TEXT: Record<Verdict, { title: string; body: string; tone: "success" | "risk" | "warning" }> = {
  true_alert: {
    title: "Flagged, and glucose did exceed 180",
    body: "The estimate was at or above the alert threshold and the outcome occurred.",
    tone: "success",
  },
  true_quiet: {
    title: "Not flagged, and glucose stayed at or below 180",
    body: "The estimate was below the alert threshold and the outcome did not occur.",
    tone: "success",
  },
  false_alarm: {
    title: "Flagged, but glucose stayed at or below 180",
    body: "A false alarm: the estimate crossed the threshold but the outcome did not occur.",
    tone: "warning",
  },
  missed: {
    title: "Not flagged, but glucose exceeded 180",
    body: "A miss: the outcome occurred although the estimate was below the threshold.",
    tone: "risk",
  },
};

/** Change since the previous native reading, when that reading is recent enough to compare. */
export function deltaFromPrevious(points: Pt[], i: number, maxGap = 15 * 60_000): { dv: number; dtMin: number } | null {
  const cur = points[i];
  const prev = points[i - 1];
  if (!cur || !prev || cur.t - prev.t > maxGap) return null;
  return { dv: cur.v - prev.v, dtMin: Math.round((cur.t - prev.t) / 60_000) };
}

/** Readings the twin could see: at or before its moment. Never anything later. */
export function seenBy(points: Pt[], asOf: Millis): Pt[] {
  return points.filter((p) => p.t <= asOf);
}

/** Lowest and highest reading, or null for an empty list. */
export function extent(points: Pt[]): { min: Pt; max: Pt } | null {
  if (points.length === 0) return null;
  let min = points[0] as Pt;
  let max = min;
  for (const p of points) {
    if (p.v < min.v) min = p;
    if (p.v > max.v) max = p;
  }
  return { min, max };
}
