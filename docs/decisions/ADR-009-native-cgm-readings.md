# ADR-009: Identify native CGM readings from the data, and use only them for pre-meal values

- Status: accepted (M1)
- Date: 2026-09-29

## Decision

For each participant, sensor and continuous segment, find the minute phase (minute mod 5 for Dexcom,
mod 15 for Libre) whose values are whole numbers at least 99% of the time, while no other phase exceeds
90%. Integer values on that phase are marked `is_native`. Pre-meal glucose, the already-high exclusion
and (from M2) every CGM feature use native readings only. If a segment has no such phase, nothing in it
is marked native, and the audit raises a blocking issue for any participant with meals.

## Context

The Phase 0A audit found a Dexcom value at every minute in all 44 files, with 52–65% of values
fractional, although the device records whole numbers every 5 minutes. The minute rows are therefore
interpolated. An interpolated value just before a meal is partly computed from a reading taken after
the meal started, so using it leaks the future into the prediction.

## Alternatives

1. **Use minute values anyway.** Simple, but it leaks future information.
2. **Use minute values lagged by 5 minutes.** Safe only if the interpolation is linear and never
   bridges missing readings, which cannot be assumed without checking.
3. **Resample to 5 minutes by taking every fifth row.** Assumes the phase is 0 and constant, which is
   not guaranteed (sensor changes can shift it).
4. **Detect the lattice from the data (chosen).** No assumption about phase; the phase can differ after
   a sensor change; the decision is visible in the audit for every segment.

## Reason

It is the only option that makes no untested assumption, and it fails loudly instead of silently when
the assumption behind it (integer device values on a fixed lattice) does not hold.

## Consequences

- The label keeps using minute rows, exactly as frozen in Phase 0A, so the frozen numbers stay
  reproducible. This split (minute-row label, native-only features) and its limitation are recorded
  in ADR-013, with sensitivity analysis SA-1 (P2) to measure it. The audit also reports the share of native-to-native intervals that are exactly linear;
  if that share is high, the minute-row label equals a label on native readings except at the window
  edge.
- If real timestamps turn out not to sit on whole minutes, detection returns "undetermined" and M2 is
  blocked until a different method (for example, locating interpolation kinks) is added and documented.
