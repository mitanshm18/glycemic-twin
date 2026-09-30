/**
 * Historical replay (pure, unit-tested). A replay walks recorded CGMacros data forward from a
 * moment; at every step the server rebuilds the twin at that time from data up to then only.
 * It is not live monitoring and not a held-out evaluation.
 */

import { HOUR, MINUTE, parseNaive, toNaiveIso, type Millis } from "./time";

export const REPLAY_SPAN_H = 24;
export const REPLAY_STEPS = [15, 30, 60] as const;
export type ReplayStepMinutes = (typeof REPLAY_STEPS)[number];
/** pause between steps while playing: long enough for the twin's values to finish morphing */
export const REPLAY_BEAT_MS = 1400;

/** The window to replay: from the twin's moment, up to 24 h on, never past the recording. */
export function replayWindow(asOf: Millis, dataEnd: Millis | null): { start: string; end: string } | null {
  const end = Math.min(asOf + REPLAY_SPAN_H * HOUR, dataEnd ?? asOf + REPLAY_SPAN_H * HOUR);
  if (end - asOf < 15 * MINUTE) return null; // nothing left to replay
  return { start: toNaiveIso(asOf), end: toNaiveIso(end) };
}

/** Steps in a window: the start itself, then one per step until the end (inclusive). */
export function replayTotal(start: string, end: string, stepMinutes: number): number {
  return Math.floor((parseNaive(end) - parseNaive(start)) / (stepMinutes * MINUTE)) + 1 + ((parseNaive(end) - parseNaive(start)) % (stepMinutes * MINUTE) ? 1 : 0);
}

/** Which step a state is (1-based), from its time. */
export function replayIndex(start: string, asOf: string, stepMinutes: number): number {
  return Math.round((parseNaive(asOf) - parseNaive(start)) / (stepMinutes * MINUTE)) + 1;
}

/**
 * Should a step's answer be shown? Only if it moves forward in time (the server cursor never goes
 * back, so an answer at or before the one on screen is a repeat or arrived out of order).
 */
export function acceptStep(asOf: string, lastShown: string | null): boolean {
  return lastShown === null || parseNaive(asOf) > parseNaive(lastShown);
}
