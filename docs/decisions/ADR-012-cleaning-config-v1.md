# ADR-012: Cleaning rules live in a versioned config, fixed before any model is trained

- Status: accepted (M1)
- Date: 2026-09-29

## Decision

All cleaning thresholds live in `data/configs/cleaning.v1.yaml`, and the frozen label and exclusions
in `data/configs/labels.v1.yaml`. Each threshold is labeled hard, structural or judgment, with its
source. Values are nulled or flagged, never silently dropped, and the audit counts how many rows each
rule touched. The SHA-256 of both configs is recorded in every output. Changing a rule means creating
v2 and rerunning everything; results under both versions are kept.

The judgment thresholds in v1, all chosen before any model exists:

| Threshold | Value | Why |
| --- | --- | --- |
| Native phase integer share | ≥ 0.99, other phases ≤ 0.90 | Device values are integers; interpolated ones mostly are not |
| Segment gap | 30 min | A sensor change leaves a gap (G6 warm-up is 2 h), so the phase may change after it |
| Heart-rate upper bound | 220 bpm | Conventional adult maximum; the dictionary's observed range is 30–176 |
| Energy ratio band | 0.5–2.0 | Atwater energy vs logged calories; catches gross logging errors while tolerating label rounding |
| Empty meal | all macros and calories 0 | A log with no content cannot describe a meal |
| Pre-meal lookback | 15 min | Three native Dexcom intervals; older readings no longer describe "now" |

## Context

A threshold chosen after seeing model results, even with good intentions, tunes the evaluation.
Writing thresholds down first, with their counts reported, prevents that and lets a reviewer check
each one.

## Alternatives

- Thresholds hard-coded in Python: hidden, and easy to change without a trace.
- Statistical outlier removal (for example, dropping the top 1% of carbs): removes real large meals and
  makes the dataset depend on its own distribution. Rejected; percentiles are used only to bound the
  what-if engine later.

## Reason

Reproducibility and auditability: any number can be traced to a config version and a rule count.

## Consequences

- Judgment thresholds will be questioned. The answer is their stated reason, their measured effect in
  the audit, and (P2) a sensitivity analysis.
- `pandera` was planned for data contracts. The contracts are implemented directly in
  `ml/src/twin_ml/pipeline/contracts.py` instead: the checks are simple (names, required columns,
  timestamp parsing, numeric coercion counts), and one fewer dependency keeps the environment smaller.
