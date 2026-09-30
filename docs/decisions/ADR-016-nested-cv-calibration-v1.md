# ADR-016: Nested participant-level CV, calibration and thresholds (training.v1)

- Status: accepted (M3)
- Date: 2026-09-29
- Config: `data/configs/training.v1.yaml` (loaded by `twin_ml.training.config.load_training_config`)
- Related: ADR-014 (priors per fold), ADR-015 (model feature contract)

## Decision

1. **Outer loop = the pinned folds.** The 5 participant folds in `data/manifests/folds.v1.csv`. M3
   refuses to run if the dataset's folds differ from the file or the file is missing.
2. **Inner loop = 4 participant folds drawn only from the outer-training participants**, stratified by
   glycemic group, seed `20261001 + outer fold + 1`. Hyper-parameters, the calibrator and the
   threshold are all chosen from inner out-of-fold (OOF) predictions.
3. **Every fit is self-contained.** Each inner fit and each refit fits its own PopulationPrior (on
   its own training participants), its own preprocessing (inside an sklearn Pipeline) and its own
   model. Nothing is fitted once globally.
4. **Training rows:** eligible meals of all glycemic groups. **Primary evaluation:** eligible meals of
   the labels.v1 target groups (prediabetes + T2D). Healthy participants are reported separately.
5. **Selection:** the grid candidate with the highest inner-OOF PR-AUC on target-group meals (first
   on ties).
6. **Calibration:** Platt (logistic) recalibration of the raw score, fitted on the inner-OOF scores of
   the selected candidate, target-group meals only. The calibrator records the participants it was
   fitted on; a test asserts none are in the outer-test fold.
7. **Threshold:** F1-max on the calibrated inner-OOF probabilities (same rows). It is stored with the
   fold model before the test fold is scored.
8. **Models:** L2 logistic regression (median imputation + missing indicators + standardization inside
   the pipeline) and XGBoost (native NaN handling, monotone +1 on g_last and carbs_g, −1 on fiber_g).
   Baselines B1 (g_last + a·carbs), B2 (HbA1c-only LR), B3 (p_personal, the fold prior's personal
   rate), B4 (LR on g_last + carbs). Baseline columns are named in training.v1 but must be an ordered
   subset of the ADR-015 primary columns; the loader refuses anything else.
9. **Ablations:** logistic and XGBoost on each of the six contract feature sets.
10. **Serving model:** the same procedure on all participants, with the pinned folds as inner folds.
    Its performance is the nested estimate; it is never scored on its own training data.
11. **Explanations:** XGBoost TreeSHAP (`pred_contribs`) computed by each outer-fold model on its own
    held-out fold only, in log-odds before calibration, on the contract columns.

## Why calibrate on target-group meals only

The twin's users are the target group, and the healthy group has a very different base rate. Fitting
one calibrator to both would trade target-group calibration for a compromise that fits neither. The
cost is that healthy-group probabilities may be miscalibrated; that is visible in the separate
healthy-group table and is accepted.

## Alternatives considered

- **Non-nested CV (tune on the same folds that are reported).** Optimistic. Rejected.
- **Isotonic calibration.** Needs more data than ~700 target meals per outer fold. Rejected for v1.
- **Calibrate on a held-out slice of the training participants.** Wastes participants; inner OOF uses
  all of them without overlap. Rejected.
- **Choose the threshold on the test fold.** Leaks the outcome. Rejected.

## Consequences

- About 5 × (4 × grid + 1) fits per model and feature set: minutes, not hours, at CGMacros size.
- The audit log of every fit is checked by `verify_boundaries`; a violation raises and nothing is
  written.
- A change to any of the above is training.v2.yaml with a new ADR.
