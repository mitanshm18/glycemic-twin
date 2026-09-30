# ADR-017: Digital Twin state contract v1 (twin-state/1) and engine rules

- Status: accepted (M4)
- Date: 2026-09-29
- Code: `packages/twin_core/src/twin_core/twin/`; config `data/configs/twin.v1.yaml`
- Exact schemas: `docs/schemas/twin-state.v1.schema.json`, `docs/schemas/twin-scenario.v1.schema.json`
  (a test fails if the code and the published schema differ)
- Related: ADR-013 (label vs feature basis), ADR-014/015 (priors, model contract), ADR-016 (M3)

## Decision

1. **One pure entry point.** `build_state(patient_id, as_of, *, source, runtime, current_meal=None,
   current_meal_id=None) -> TwinState`. `source` supplies the person's raw observations
   (`PatientRecord`, M1 table shapes); `runtime` holds the frozen configs, the served model bundle and
   its training-support profile. No clock, randomness, network or database is involved.
2. **The cut comes first.** The record is cut at `as_of` before anything is computed. Meal outcomes
   are recomputed from the cut with the frozen labels.v1 function and kept only for meals whose
   120-minute window closed at or before `as_of`. Personal features read only those closed windows,
   so the current meal's own outcome can never shape its state.
3. **Reuse, never reimplement.** Base features come from `features.meal_features`, personal
   features from `personalization.personal_features` with the **PopulationPrior stored in the model
   bundle**, and the model applies its own fitted preprocessing and calibrator. Nothing is fitted or
   re-estimated at serving time. A test checks the twin's 45 inputs equal the M2/M3 inputs for every
   fixture meal.
4. **The model must match the contract.** `TwinRuntime` refuses a model whose feature set, ordered
   columns, contract version or hash, features.v1 or labels.v1 hash differ from the running configs,
   or which uses personal features without a prior; and a support profile built from a dataset other
   than the bundle's training dataset.
5. **Scope of risk.** The model was trained on eligible meals only. A meal with no native pre-meal
   reading, glucose already above 180, or unusable macros gets `risk.status = "not_applicable"` with
   the reason, never a probability.
6. **Lifecycle** (n = closed frozen-usable meals, w = personal_weight):
   `COLD_START` if n = 0; `PERSONALIZED` if w >= 0.5 and n >= 3; otherwise `WARMING`. It can only move
   forward as `as_of` moves forward, because closed evidence only accumulates.
7. **Identity and immutability.** States are frozen pydantic models that reject unknown fields. The
   `state_id` is the SHA-256 of the state's canonical JSON (without `state_id`), so identical inputs
   give identical ids and any change gives a new one. `diff_states` explains changes between two states.
8. **What-if.** `simulate(patient_id, as_of, changes, ...)` changes carbs, fiber, protein or fat of the
   current meal (calories follow via Atwater factors), or pre-meal active minutes when METs are
   recorded. Bounds: configured maximum change per lever, no negative macros, fiber <= carbs, and
   every changed model input inside the training [1%, 99%] range, else `out_of_support` with no
   estimate. Levers mentioning medication, insulin, diagnosis or treatment are refused. Results carry
   a non-causal, non-medical disclaimer.
9. **twin_core stays independent**: no web, database, UI or ML-library imports (a test scans the
   source).

## State sections (twin-state/1)

schema_version, state_id, patient_id, as_of, lifecycle, static_clinical, personal_baselines,
current_physiology, recent_history, current_meal, personal_response, risk (with uncertainty and the
exact model inputs), freshness, provenance (record hash, rows used, closed meal ids used, current
meal id, max source timestamp, config hashes, engine version, model identity), disclaimer.

## Alternatives considered

- **Precomputed outcomes from M1 tables.** Faster, but a state could then depend on data after
  `as_of`. Rejected: outcomes are recomputed from the cut (a test shows they equal full-data outcomes
  for closed windows).
- **A confidence interval for risk.** The bundle holds one final model, so there is no honest
  interval without retraining. Uncertainty is reported as explicit flags (support, missing inputs,
  personal evidence, closeness to the threshold) plus outcome entropy, never a fake interval.
- **Post-meal activity what-if.** The model has no post-meal inputs, so it cannot be simulated.
- **Importing the bundle class into twin_core.** Would tie the pure core to the ML stack. Rejected in
  favour of the `RiskModel` protocol, which the M3 bundle already satisfies.

## Consequences

- M5 (API) wraps `build_state`/`simulate`; it must load the bundle and the support profile and pass a
  `RecordSource` backed by its store. Any change to the state models means twin-state/2.
- The training-support profile for the real bundle is built once with `build_support_profile` from
  the real M2 dataset (content hash must equal the bundle's `dataset_content_sha256`).
