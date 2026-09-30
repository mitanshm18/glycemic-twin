/**
 * Geometry for the sign-in signal (pure, unit-tested). The trace is a brand motif drawn from a
 * closed-form curve: a steady baseline with two meal responses, one staying in range and one
 * crossing 180. It carries no values or axes and is never presented as a reading.
 */

/** Motif "glucose" at position u in [0, 1] of the panel width. Units are nominal mg/dL. */
const MEALS = [
  { at: 0.1, amp: 48 },
  { at: 0.52, amp: 104 },
] as const;
const TAU = 0.092; // time to peak, as a fraction of the width
const BASE = 98;

function response(u: number, at: number, amp: number): number {
  const t = (u - at) / TAU;
  return t <= 0 ? 0 : amp * t * Math.exp(1 - t);
}

export function motif(u: number): number {
  let g = BASE + 2.4 * Math.sin(u * 37) + 1.6 * Math.sin(u * 83 + 1) + 0.9 * Math.sin(u * 151 + 2);
  for (const m of MEALS) g += response(u, m.at, m.amp);
  return g;
}

export const SIGNAL_DOMAIN: [number, number] = [58, 222];
export const WINDOW_U = 0.222; // two hours on the motif's time scale

export interface SignalAnchor {
  id: "meal" | "window" | "above";
  u: number;
  title: string;
  body: string;
}

/** The only clickable points: product vocabulary, sparse on purpose. */
export const ANCHORS: SignalAnchor[] = [
  { id: "meal", u: MEALS[1].at, title: "Meal logged", body: "The twin predicts from this moment, using only what came before." },
  { id: "window", u: MEALS[1].at + WINDOW_U * 0.74, title: "2-hour window", body: "The question: does glucose go above 180 mg/dL in this window?" },
  { id: "above", u: MEALS[1].at + TAU, title: "Above 180", body: "The outcome the model estimates, and later checks against the recording." },
];

export interface Frame {
  width: number;
  height: number;
  top: number;
  bottom: number;
}

export const xOf = (u: number, f: Frame) => u * f.width;
export function yOf(v: number, f: Frame): number {
  const [lo, hi] = SIGNAL_DOMAIN;
  const k = (v - lo) / (hi - lo);
  return f.height - f.bottom - k * (f.height - f.top - f.bottom);
}

export interface Pointer {
  x: number;
  y: number;
  /** 0..1: how strongly the pointer affects the trace (eased in and out by the caller) */
  strength: number;
}

const SIGMA = 42; // px: width of the pointer's influence
const PULL = 0.14; // fraction of the vertical distance the trace leans toward the pointer
const MAX_LEAN = 6; // px

/** Vertical offset of the trace at x caused by the pointer; never more than MAX_LEAN px. */
export function lean(x: number, baseY: number, p: Pointer | null): number {
  if (!p || p.strength <= 0) return 0;
  const w = Math.exp(-((x - p.x) ** 2) / (2 * SIGMA ** 2));
  const d = Math.max(-MAX_LEAN, Math.min(MAX_LEAN, (p.y - baseY) * PULL));
  return d * w * p.strength;
}

export function tracePoints(f: Frame, p: Pointer | null = null): Array<[number, number]> {
  const n = Math.max(40, Math.round(f.width / 4));
  const out: Array<[number, number]> = [];
  for (let i = 0; i <= n; i++) {
    const u = i / n;
    const x = xOf(u, f);
    const y0 = yOf(motif(u), f);
    out.push([x, y0 + lean(x, y0, p)]);
  }
  return out;
}

export function toPath(pts: Array<[number, number]>): string {
  return pts.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`).join("");
}

/** Point on the (leaned) trace at x, for the reading cursor. */
export function pointAt(x: number, f: Frame, p: Pointer | null): [number, number] {
  const u = Math.max(0, Math.min(1, x / f.width));
  const y0 = yOf(motif(u), f);
  return [xOf(u, f), y0 + lean(xOf(u, f), y0, p)];
}
