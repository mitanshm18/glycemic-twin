# ADR-015: Model feature contract v1 — 42 base features + 3 derived personal features

- Status: accepted (recorded after M2 review, before M3)
- Date: 2026-09-29
- Contract file: `data/configs/model_features.v1.yaml` (loaded by `twin_core.config.load_model_contract`)
- Related: ADR-013 (label basis vs feature basis), ADR-014 (priors per fold)

## Decision

**1. Exactly which columns a model receives.** The primary model (feature set `full_personal`)
receives **45 columns, in this order:**

| Part | Columns | Count |
| --- | --- | --- |
| Base: glucose | g_last, g_age_min, slope_15, slope_30, sd_60, mean_180, min_180, max_180, tir_24h, g_overnight_baseline, g_vs_baseline | 11 |
| Base: meal | carbs_g, protein_g, fat_g, fiber_g, calories_kcal, meal_breakfast, meal_lunch, meal_dinner, meal_snack, hour_sin, hour_cos | 11 |
| Base: context | carbs_prev_3h, invalid_meal_prev_3h, mins_since_meal | 3 |
| Base: wearable | hr_30, hr_resting, hr_delta, mets_available, mets_60, active_min_3h, activity_kcal_60, hr_age_min | 8 |
| Base: clinical | hba1c_pct, fasting_glucose_mgdl, fasting_insulin_uu_ml, homa_ir, bmi, age_years, sex_female, triglycerides_mgdl, hdl_mgdl | 9 |
| Personal (derived) | p_personal, rise_offset_mgdl, personal_weight | 3 |

The base features come unchanged from features.v1 (M2 is not redesigned). `contract.columns(fcfg)`
returns this tuple, and it is the only way any code obtains model columns.

**2. The raw counts `n_closed_meals` and `n_closed_positive` are NOT model features.** They stay in
the M2 dataset as audit columns, and a test checks that they agree with the personalization module's
own count. The derived features **replace** them as model inputs.

**3. `p_personal`, `rise_offset_mgdl` and `personal_weight` ARE added**, computed by
`twin_core.personalization.personal_features` from the person's meals whose 120-minute window closed
at or before t0.

**4. Priors are fitted on training participants only, in every fit.** Each time a model is fitted
(every outer fold, every inner tuning fold, and the final full model), a `PopulationPrior` is fitted
on that fit's training participants' frozen-usable meals only. Personal features for both the
training rows and the held-out rows are then computed with that prior. Test participants never
contribute to the prior that is used to predict them.

**5. The primary model is `full_personal`.** The ablations are named feature sets in the same file:
glucose_only, glucose_meal, glucose_wearable, glucose_clinical, full_multimodal (the 42 base
features), and full_personal (all 45). "Does personalization help?" is answered by comparing
full_personal with full_multimodal. "Does fusion help?" is answered by comparing full_multimodal with
glucose_only.

## Why derived features instead of raw counts

- **Raw counts are not scale-free.** `n_closed_positive = 6` means one thing after 7 meals and another
  after 30. A model would have to learn the division itself, from about 1,300 meals, and would confuse
  "has been observed longer" with "has more risk".
- **The derived features are what the twin actually believes.** p_personal is the person's shrunk
  positive rate; rise_offset_mgdl is how much more (or less) their glucose rises than the population
  model predicts for similar meals; personal_weight (w = n / (n + k)) says how much of that belief
  comes from the person's own data. That weight lets the model learn to trust personal estimates more
  as evidence accumulates, and it makes a separate raw count redundant.
- **Cold start is explicit and consistent.** For someone with no closed meals: p_personal = population
  rate, rise_offset_mgdl = 0, personal_weight = 0. The same values appear in training (early meals),
  in evaluation and at serving. None of the three is ever NaN.

## Keeping the contract identical across the four places it is used

| Place | How the contract is applied |
| --- | --- |
| Offline training | `columns(fcfg, set)`; prior fitted on the training participants of that fit |
| Cross-validation / evaluation | Same, per outer fold; inner tuning folds refit their own prior |
| Out-of-fold prediction | The fold-k model scores fold-k participants, using the prior fitted with that model |
| API serving (M5) | Base features from `meal_features`; personal features from `personal_features` with the **prior stored in the model bundle**; the API refuses a bundle whose contract version, column list or feature-config hash differs from its own |

Each model bundle (from M3) stores: the model, its calibrator, its `PopulationPrior`, the contract
version and SHA-256, the ordered column list, and the feature-set name. Serving and evaluation
compare the stored list with `contract.columns(...)` and fail on any difference.

The personal-feature inputs are also identical in both paths: macros are the feature-cleaned values
(NaN when macro validity is not "valid"), and pre-meal and peak glucose use native readings only.
So the rise model is trained and applied on the same quantities.

## Unchanged, restated

- labels.v1 is untouched. The label and its coverage use the frozen 1-minute Dexcom series; every
  model feature, including the rise history behind rise_offset_mgdl, uses native readings only
  (ADR-013). Sensitivity analysis SA-1 remains registered as P2.
- M2's dataset, features.v1 and its leakage checks are unchanged. `load_model_contract` refuses to
  load if features.v1.yaml or labels.v1.yaml no longer match the hashes pinned in the contract.

## Alternatives considered

- **Raw counts only.** No prior needed, but not scale-free, and the model has to rediscover shrinkage
  from little data. Rejected.
- **Raw counts plus derived features.** Redundant with personal_weight, and it adds two
  non-stationary columns for a small dataset. Rejected.
- **Derived features computed once with a global prior.** Leaks test participants' outcomes into their
  own prior (ADR-014). Rejected.

## Consequences

- M3 must fit the prior inside every model fit. A test will assert that no test-fold participant
  appears in the rows passed to `fit_population_prior`.
- Baseline B3 (personal historical rate) is p_personal alone, with its fold's prior, which makes it a
  fair version of "the person's own past rate".
- A change to any column, order or feature set means model_features.v2.yaml and a new ADR. v1 is
  never edited in place.
