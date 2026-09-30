# ADR-013: Labels use the frozen 1-minute Dexcom series; features use native readings only

- Status: accepted (recorded after M1 review, before M2)
- Date: 2026-09-29
- Related: ADR-009 (native CGM readings), labels.v1.yaml (unchanged), SA-1 in `docs/sensitivity-analyses.md`

## Decision

Two different bases are used on purpose, and each is fixed:

| Use | Glucose basis | Why |
| --- | --- | --- |
| **Label** (labels.v1): peak > 180 mg/dL in (t0, t0 + 120], and the 80% window coverage | The frozen **1-minute** Dexcom series, including interpolated minutes | Reproduces the Phase 0A audit exactly (1,663 meals, 1,368 usable, 580 positives), on which the target was frozen and the viability rule was checked |
| **Features**, pre-meal glucose, the already-high exclusion, and personal response history | **Native** Dexcom readings only (`is_native`) | An interpolated minute before t0 is partly built from a reading after t0; using it would leak the future |

The frozen label definition is **not** changed.

## The scientific limitation

Interpolated minute values are not measurements. Consequently, the frozen label can in principle
differ from a label computed only from native readings:

- **Inside the window**, if the interpolation is linear, an interpolated minute can never exceed the
  higher of the two real readings on either side of it. The minute-row peak then equals the native peak
  whenever both of those readings fall inside the window.
- **At the window's end** (t0 + 120), the last minutes can be interpolated toward a native reading
  taken after the window closes. If that later reading is above 180 mg/dL, a minute inside the window
  can cross 180 even though no native reading inside the window did. The frozen label then says 1 where
  a native-only label would say 0. The reverse can happen at the window's start.
- **If the interpolation is not linear** (for example, a spline), minute values can overshoot the real
  readings anywhere in the window, and disagreements are no longer limited to the edges. M1 reports
  the share of native-to-native intervals that are exactly linear, per participant and overall.
- **Coverage** is counted on minute rows. Interpolation fills minutes between real readings, so the
  80% coverage rule may be looser than the same rule counted on native readings.

The size of this effect is **unknown until measured**. It is expected to be small, since it needs a
threshold crossing within about 5 minutes of the window edge, but that is an expectation, not a
result.

## Future work (P2, pre-registered)

Sensitivity analysis **SA-1**, registered in `docs/sensitivity-analyses.md`, computes the native-only
label for every frozen-usable meal and reports the agreement. It does not replace the frozen label.

## Alternatives considered

- **Switch the label to native readings now.** Scientifically cleaner, but it would change the target
  after it was frozen on the Phase 0A numbers, and the viability check would have to be redone.
  Rejected for now; SA-1 measures whether it matters.
- **Use minute rows for features too.** Rejected: that is leakage (ADR-009).

## Consequences

- The model card must state which basis each number uses.
- Every M1 outcome row already carries both `peak_mgdl` (minute basis) and `peak_native_mgdl`
  (native basis), so SA-1 needs no new data processing.
- If SA-1 finds material disagreement, the response is a new labels.v2 with the full pipeline rerun,
  and both results reported. labels.v1 is never edited in place.
