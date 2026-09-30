# Feature dictionary — features.v1

Every feature is computed by `twin_core.features.meal_features(history, meal, cfg)` at meal start
**t0**, with the windows in `data/configs/features.v1.yaml`. The same function will serve the API.

**Rules that apply to every row below:**

- **CGM:** native Dexcom readings only (`is_native`); interpolated minutes cannot even be loaded into
  the history (ADR-009, ADR-013).
- **Timestamps:** CGM ts ≤ t0; wearable minutes ts < t0; earlier meals start < t0; a past meal's
  outcome counts only once its window has closed (start + 120 ≤ t0).
- **Missing data:** a feature is NaN when its data is missing or too sparse. Nothing is imputed here:
  imputation, if any, is fitted inside training folds in M3.

## Glucose (native Dexcom)

| Feature | Definition | Window / rule | Leakage risk addressed | Available when |
| --- | --- | --- | --- | --- |
| g_last | Last native reading | ts ≤ t0, no older than 15 min | Interpolated minute before t0 contains the post-t0 reading | A native reading in [t0 − 15, t0] |
| g_age_min | t0 − time of last native reading, capped at 1,440 | ts ≤ t0 | — | Any earlier reading |
| slope_15, slope_30 | Least-squares slope, mg/dL per minute | [t0 − 15, t0], [t0 − 30, t0] | Same as g_last | ≥ 3 readings |
| sd_60 | Standard deviation | [t0 − 60, t0] | — | ≥ 6 readings |
| mean_180, min_180, max_180 | Mean, min, max | [t0 − 180, t0] | — | ≥ 50% of expected (18 of 36) |
| tir_24h | Share of readings in 70–180 mg/dL | [t0 − 24 h, t0] | — | ≥ 50% of expected (144 of 288) |
| g_overnight_baseline | Median of readings 02:00–06:00 | Completed nights only (night end ≤ t0) | A night still in progress | ≥ 24 readings |
| g_vs_baseline | g_last − g_overnight_baseline | As above | — | Both present |

## The meal (known when it is logged)

| Feature | Definition | Notes |
| --- | --- | --- |
| carbs_g, protein_g, fat_g, fiber_g, calories_kcal | Logged macros | NaN when macro validity is not "valid"; Amount Consumed is never used |
| meal_breakfast, meal_lunch, meal_dinner, meal_snack | One-hot meal type | All 0 for "other" |
| hour_sin, hour_cos | Time of day on a circle: sin/cos(2π · hour / 24) | So 23:00 and 01:00 are close |

## Context (earlier meals)

| Feature | Definition | Window |
| --- | --- | --- |
| carbs_prev_3h | Sum of carbs of earlier meals with valid macros | Start in [t0 − 180, t0) |
| invalid_meal_prev_3h | 1 if any earlier meal in that window has invalid macros | Same |
| mins_since_meal | Minutes since the previous meal, capped at 720 | Start < t0 |

## Wearable (Fitbit, minutes before t0)

| Feature | Definition | Window / rule | Available when |
| --- | --- | --- | --- |
| hr_30 | Mean heart rate | [t0 − 30, t0) | ≥ 50% of minutes |
| hr_resting | 10th percentile of HR in sedentary minutes (METs ≤ 1.5) | Calendar days before t0's day; without METs, minutes 02:00–06:00 of those days | ≥ 60 minutes |
| hr_delta | hr_30 − hr_resting | — | Both present |
| mets_available | 1 if the participant's file has METs | — | Always |
| mets_60 | Mean METs | [t0 − 60, t0) | METs present, ≥ 50% of minutes |
| active_min_3h | Minutes with METs ≥ 3.0 | [t0 − 180, t0) | METs present, ≥ 50% of minutes; otherwise NaN, never 0 |
| activity_kcal_60 | Mean activity calories per minute | [t0 − 60, t0) | ≥ 50% of minutes |
| hr_age_min | Minutes since the last HR value, capped at 1,440 | ts < t0 | Any earlier HR |

## Clinical baseline (bio.csv, collected before the study)

hba1c_pct, fasting_glucose_mgdl, fasting_insulin_uu_ml, bmi, age_years, triglycerides_mgdl, hdl_mgdl,
sex_female (F = 1, M = 0), and homa_ir = fasting glucose (mg/dL) × fasting insulin (µU/mL) ÷ 405
(derived). They are constant per person, so they can only explain differences between people, which
is exactly why the HbA1c-only baseline exists.

## Personal (computed per fold in M3)

The M2 dataset stores only `n_closed_meals` and `n_closed_positive`: counts of the person's earlier
frozen-usable meals whose windows have closed, and how many of those were positive. **These raw
counts are audit columns, not model inputs.** The model receives the derived p_personal,
rise_offset_mgdl and personal_weight instead. They need population parameters fitted on training
participants only, so M3 computes them inside every model fit with `twin_core.personalization`
(ADR-014).

## What the model actually receives

`data/configs/model_features.v1.yaml` (ADR-015) defines the exact ordered input: the 42 base features
above plus p_personal, rise_offset_mgdl and personal_weight, 45 columns in all, for the primary
feature set `full_personal`. Ablation sets are named in the same file.

## Not features (outcome columns, kept for labels and analysis only)

label, frozen_usable, eligible, exclusion_reasons, waterfall_reason, peak_mgdl, peak_native_mgdl,
pre_meal_native_mgdl, rise_native_mgdl, next_meal_gap_min, window_coverage, already_high.
The leakage check L1 fails if any of these, or any name containing a deny-listed word (amount, peak,
label, post, outcome, exclusion, usable, eligible, already_high, coverage, next_meal, waterfall),
appears among the features.
