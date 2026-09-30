# Target population reconciliation: 923 frozen-usable → 785 training meals

Measured on the real CGMacros v1.0.0 data (preflight, 29 Sep 2026), prediabetes + T2D only.
No rule was changed; this note only accounts for every row.

| Stage | Rows | Positives | Rate | Participants | Removed | Reason |
| --- | --- | --- | --- | --- | --- | --- |
| Target-group meals logged (M1) | 1,072 | – | – | 30 | – | – |
| Frozen usable (Phase 0A rule; = Phase 0A audit) | 923 | 481 | 52.1% | 30 | 149 | overlap with next meal < 120 min, or window coverage < 80% (frozen rule) |
| − already high before the meal | 835 | 394 | 47.2% | 30 | 88 (87 positive) | last native Dexcom reading in [t0 − 15, t0] > 180 mg/dL (incl. 7 meals also macro-excluded) |
| − macros cannot describe the meal | 785 | 377 | 48.0% | 30 | 50 (17 positive) | macro validity empty 24, inconsistent 19, invalid 14 (57 flagged; 7 already removed above) |
| − no native reading in [t0 − 15, t0] | 785 | 377 | 48.0% | 30 | 0 | – |
| **Eligible (M1 `eligible`)** | **785** | **377** | **48.0%** | **30** | | |
| M2 dataset (features) | 785 | 377 | 48.0% | 30 | 0 | M2 keeps every meal; labels identical to M1 |
| M3 training / evaluation rows | 785 | 377 | 48.0% | 30 | 0 | M3 uses `eligible == True`; missing features are imputed in-fold (LR) or handled natively (XGBoost), never dropped |

Healthy group (reported separately): 411 eligible meals, 90 positive, 14 participants.

## The rules that remove the 138 meals

They are the three data-quality exclusions frozen in `data/configs/labels.v1.yaml` (keys
`pre_meal_lookback_min`, `already_high_threshold_mgdl`, `exclude_macro_validity`), decided in
Phase 0A/0B before any model, and implemented in `twin_core.labels.meal_outcomes`:

```
eligible = frozen_usable AND NOT (no_pre_meal_native OR already_high OR macro_excluded)
```

- **Already high (88 meals, 87 positive).** Glucose was already above 180 when the meal started, so
  "will it exceed 180 in the next 2 hours" is answered before the meal is eaten (98.9% of these are
  positive). Keeping them would inflate every metric with trivial predictions. The Phase 0A audit
  flagged this (90 such positives across all groups).
- **Macro validity (50 meals).** The meal's macros are empty, inconsistent (e.g. fiber > carbs,
  energy mismatch) or invalid, so the model's main meal inputs would be meaningless.
- **No native pre-meal reading (0 meals).** The rule exists so that no meal is scored without a
  real pre-meal glucose; on this data it removes nothing.

## What does NOT remove any meal

Missing native CGM features, missing wearable features (e.g. hr_30 missing on 4.3% of target meals),
missing clinical features, feature-window coverage, personalization history, labels, duplicates:
0 rows each. The frozen label itself is unchanged: all 923 frozen-usable meals keep their Phase 0A
label, and the frozen viability rule is reported on both populations (923 / 481 and 785 / 377; both
pass).
