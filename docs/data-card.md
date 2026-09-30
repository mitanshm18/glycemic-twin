# Data card — CGMacros v1.0.0

## What the data is

| Item | Value |
| --- | --- |
| Name | CGMacros: a scientific dataset for personalized nutrition and diet monitoring, v1.0.0 |
| Publisher | PhysioNet, 28 Jan 2025 — https://physionet.org/content/cgmacros/1.0.0/ |
| License | Creative Commons Attribution-NonCommercial-ShareAlike 4.0 |
| Access | Open download, no credentialing |
| Collected | 2021–2024, Sansum Diabetes Research Institute, Santa Barbara, CA (IRB Pro00049227; NCT04991142) |
| Design | Free-living, about 10 days per participant; designed breakfasts (protein shakes with varied macros) and lunches (fast-casual restaurant), free-choice dinners |
| Devices | Dexcom G6 Pro (native every 5 min) and FreeStyle Libre Pro (native every 15 min), both blinded; Fitbit Sense |
| Dates | Shifted by 365–720 days for de-identification; time of day is real |

**Citation:** Gutierrez-Osuna, R., Kerr, D., Mortazavi, B., & Das, A. (2025). CGMacros: a scientific
dataset for personalized nutrition and diet monitoring (version 1.0.0). PhysioNet.
https://doi.org/10.13026/3z8q-x658 — plus the standard PhysioNet citation.

## How this project uses it

- **Prediction target (frozen, labels.v1):** Dexcom glucose > 180 mg/dL at any minute row in
  (meal start, meal start + 120 min], for meals with no other meal starting within 120 min and at least
  80% Dexcom coverage in the window.
- **Training and evaluation set:** frozen-usable meals minus meals with no native Dexcom reading in the
  15 min before the meal, meals already above 180 mg/dL before the meal, and meals whose macros are
  missing, invalid, empty or inconsistent (cleaning.v1).
- **Label basis vs feature basis (ADR-013):** the label and its window coverage are computed on the
  frozen **1-minute** Dexcom series, exactly as in the Phase 0A audit, so the frozen numbers are
  reproducible. **Model features, pre-meal glucose and the already-high exclusion use native Dexcom
  readings only.** Limitation: the 1-minute series contains interpolated values, so the frozen label
  can differ from a label computed from native readings alone, mainly for meals whose glucose crosses
  180 mg/dL near the end of the 120-minute window, or anywhere if the interpolation is not linear.
  The size of this effect is unmeasured; it is registered as sensitivity analysis SA-1 (P2) in
  `docs/sensitivity-analyses.md`. The frozen definition is not changed.
- **Primary population:** prediabetes + T2D, groups **derived** from baseline HbA1c
  (< 5.7% healthy, 5.7–6.4% prediabetes, > 6.4% T2D; thresholds from the PhysioNet page). They are not
  diagnoses; the dataset has no diagnosis field.
- **Clinical layer:** the real bio.csv values, each tagged observed or derived with its source column.
  Nothing is invented: there are **no medication, diagnosis or history fields** in the source, and none
  are created.

## Fields

| Source | Fields | Notes |
| --- | --- | --- |
| Participant files (1-minute rows) | Timestamp, Dexcom GL, Libre GL, HR, Calories (Activity), METs, Meal Type, Calories, Carbs, Protein, Fat, Fiber, Amount Consumed, Image path | CGM minute values are interpolated between native readings; METs stored ×10 |
| bio.csv (one row per subject) | Age, gender, BMI, weight (lb), height (in), self-identified ethnicity, HbA1c, fasting glucose, fasting insulin, triglycerides, cholesterol, HDL, non-HDL, LDL, VLDL, cholesterol/HDL ratio, lab collection time, three fingerstick glucose readings with times | Baseline only; HbA1c is in % despite the dictionary saying mmol/mol |
| microbes.csv, gut_health_test.csv | Microbiome presence and gut-health scores | Not used |

## Known issues and how they are handled

| Issue | Handling (cleaning.v1 / labels.v1) |
| --- | --- |
| CGM minute values are interpolated | Native readings detected per participant and segment; only native readings define pre-meal glucose and (from M2) CGM features |
| Amount Consumed is recorded after the meal and has values above 100% | Values outside 0–100 nulled and flagged; never a model feature |
| Implausible macros (e.g. fiber in the thousands of grams) | Hard rules (negative, fiber > carbs, zero calories with macros) and a judgment rule (Atwater energy / logged calories outside 0.5–2.0); flagged meals excluded from training and evaluation |
| Meal type spellings; snacks not in the dictionary | Normalized to breakfast, lunch, dinner, snack |
| METs column absent in some files | Treated as unknown, never 0 |
| Lipid error codes (LDL 800, VLDL 400, ratio 400) | Set to missing and flagged |
| Duplicate timestamps | Identical rows collapsed; conflicting sensor values nulled |
| One bio.csv subject has no time series | Clinical record only |

## Measured facts (generated)

The block below is written by `make m1` from the source files. Until the pipeline has run on the real
data, it holds no numbers. For comparison, the Phase 0A exploratory audit is kept unchanged in
`data/reference/phase0a_audit_results.json`, and `make m1` reconciles against it.

<!-- AUTO:M1-AUDIT START (generated by `make m1`; do not edit by hand) -->

- Source check: not_applicable (official), pinned (pinned manifest `b9956fc7535a`)
- Time-series files: **44**; bio.csv rows: 45; absent IDs in 1–49: [1, 24, 25, 37, 40]; clinical record without time series: [1]
- Groups with time series: {'healthy': 14, 'prediabetes': 16, 'T2D': 14}
- Meal rows: 1663 ({'breakfast': 426, 'dinner': 478, 'lunch': 425, 'snack': 334}); macro validity {'empty': 43, 'inconsistent': 48, 'invalid': 34, 'valid': 1538}
- Dexcom native grid: {'native_lattice': 44}; 123161 native readings of 615560 minute values; linear interpolation share 100.0%
- METs column missing in 11 files ([11, 26, 27, 31, 32, 33, 34, 35, 38, 42, 46])

| Target group (prediabetes + T2D) | Participants | Usable meals | Positives | Rate | With ≥ 1 positive | Viability rule |
| --- | --- | --- | --- | --- | --- | --- |
| Frozen definition | 30 | 923 | 481 | 52.1% | 29 | pass |
| After added exclusions (training/evaluation set) | 30 | 785 | 377 | 48.0% | 29 | pass |

| Exclusion (first reason, in order) | Meals |
| --- | --- |
| overlap_next_meal | 244 |
| low_cgm_coverage | 51 |
| no_pre_meal_native | 0 |
| already_high | 91 |
| macro_excluded | 81 |
| eligible | 1196 |

<!-- AUTO:M1-AUDIT END -->

## Limitations

- Small: 44 participants with time series, about 10 days each, and 30 in the target groups (Phase 0A audit; confirmed or corrected by the generated block above).
- Mostly one site in California; demographics are not representative.
- The clinical record is one baseline visit: no medications, diagnoses, history or repeat labs.
- Macros are participant-logged estimates; dinners are free-choice and less reliable.
- CGM is a research-blinded wear period, not routine care; interstitial glucose lags blood glucose.
- Any result from this data is a research proof of concept, not clinical evidence.
