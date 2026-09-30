# Pre-registered sensitivity analyses

Each analysis is written down before the model exists. Each one reports how a result changes under an
alternative choice. None of them replaces a frozen definition; a change to a definition goes through a
new versioned config and an ADR.

| ID | Priority | Question | Status |
| --- | --- | --- | --- |
| SA-1 | P2 | Does the frozen minute-row label agree with a native-reading-only label? | Registered, not run |
| SA-2 | P2 | How do results change if the energy-ratio band (0.5–2.0) is widened or removed? | Registered, not run |

## SA-1 — Label basis: 1-minute series vs native readings

**Background:** ADR-013. labels.v1 computes the peak and window coverage on the frozen 1-minute Dexcom
series, which includes interpolated values. Features use native readings only.

**Method (fixed now):**

1. For every frozen-usable meal, compute the native-only label: 1 if any native Dexcom reading in
   (t0, t0 + 120] exceeds 180 mg/dL (`peak_native_mgdl` > 180; M1 already stores this column).
2. Report the 2 × 2 agreement table (frozen label vs native-only label), Cohen's kappa, and the
   disagreement count by glycemic group and by participant.
3. For each disagreement, record whether it sits at the window edge: the minute-row peak falls within
   5 minutes of t0 + 120, or within 5 minutes after t0.
4. Also compute window coverage on native readings (expected 24 per 120 min) and report how many
   frozen-usable meals would fall below 80% under a native count.
5. Re-run the primary evaluation (M2 model vs best baseline, AUPRC, regime A) with the native-only
   label as the target, using the same folds and hyperparameters, and report both results side by
   side.

**Decision rule (fixed now):** if agreement is at least 98% and kappa is at least 0.95, the frozen label
is kept and SA-1 is reported as a robustness check. Otherwise the disagreement is reported
prominently in the model card, and labels.v2 (native basis) is proposed through a new ADR, with both
versions' results published. labels.v1 is never edited in place.

**Where it runs:** after M3, when a model exists to re-evaluate. It is a P2 item and must not delay the
hackathon P0 scope.

## SA-2 — Energy-ratio band

**Background:** ADR-012. The 0.5–2.0 band is a judgment threshold.

**Method:** repeat the primary evaluation with (a) no energy-ratio rule and (b) a 0.33–3.0 band;
report the change in the number of eligible meals and in the primary metric.
