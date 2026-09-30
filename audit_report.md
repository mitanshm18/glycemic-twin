# CGMacros v1.0.0 audit

Source: `/Users/mitanshm_18/Downloads/CGMacros`

- Participant files: **44**
- IDs absent between 1 and max: [1, 24, 25, 37, 40]
- Supplementary files: ['bio.csv', 'gut_health_test.csv', 'microbes.csv']

## Participant-file columns (files containing each)

- `Amount Consumed`: 42
- `Calories`: 44
- `Calories (Activity)`: 43
- `Carbs`: 44
- `Dexcom GL`: 44
- `Fat`: 44
- `Fiber`: 44
- `HR`: 44
- `Image path`: 44
- `Intensity`: 11
- `Libre GL`: 44
- `METs`: 33
- `Meal Type`: 44
- `Protein`: 44
- `RecordIndex`: 1
- `Steps`: 1
- `Sugar`: 1
- `Timestamp`: 44
- `Unnamed: 0`: 8

## bio.csv

- Rows: 45
- Columns: ['subject', 'Age', 'Gender', 'BMI', 'Body weight ', 'Height ', 'Self-identify ', 'A1c PDL (Lab)', 'Fasting GLU - PDL (Lab)', 'Insulin ', 'Triglycerides', 'Cholesterol', 'HDL', 'Non HDL ', 'LDL (Cal)', 'VLDL (Cal)', 'Cho/HDL Ratio', 'Collection time PDL (Lab)', '#1 Contour Fingerstick GLU', 'Time (t)', ' #2 Contour Fingerstick GLU', 'Time (t).1', '#3 Contour Fingerstick GLU', 'Time (t).2']
- Medication-like columns: []
- Medication-like columns anywhere: {'participant_files': [], 'gut_health_test.csv': [], 'bio.csv': [], 'microbes.csv': []}
- Sentinel error counts: {'LDL (Cal)': 1, 'VLDL (Cal)': 1, 'Cho/HDL Ratio': 1}
- HbA1c min/max: [4.6, 8.5]

## Per participant

| ID | Group | Rows | Days | Row step (min) | Dexcom interval | Dexcom non-integer share | Missing Dexcom | Missing HR | Meals |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2 | healthy | 17025 | 11.82 | 1.0 | 1.0 | 0.5862396724427872 | 0.197 | 0.161 | 37 |
| 3 | T2D | 14565 | 10.12 | 1.0 | 1.0 | 0.5467040673211782 | 0.021 | 0.006 | 35 |
| 4 | healthy | 14275 | 9.91 | 1.0 | 1.0 | 0.5982486865148862 | 0.0 | 0.003 | 62 |
| 5 | T2D | 14460 | 10.04 | 1.0 | 1.0 | 0.6055341506129597 | 0.013 | 0.012 | 46 |
| 6 | healthy | 14460 | 10.04 | 1.0 | 1.0 | 0.5332399299474606 | 0.013 | 0.008 | 38 |
| 7 | prediabetes | 5655 | 7.23 | 1.0 | 1.0 | 0.5225177304964539 | 0.003 | 0.003 | 17 |
| 8 | prediabetes | 14760 | 10.25 | 1.0 | 1.0 | 0.6157524613220816 | 0.037 | 0.022 | 30 |
| 9 | prediabetes | 14370 | 9.98 | 1.0 | 1.0 | 0.5969351890903979 | 0.01 | 0.015 | 41 |
| 10 | prediabetes | 16155 | 11.22 | 1.0 | 1.0 | 0.6021716287215412 | 0.116 | 0.063 | 45 |
| 11 | prediabetes | 14805 | 10.28 | 1.0 | 1.0 | 0.6066549912434326 | 0.036 | 0.01 | 39 |
| 12 | T2D | 14655 | 10.19 | 1.0 | 1.0 | 0.6144358794674142 | 0.026 | 0.086 | 33 |
| 13 | prediabetes | 15840 | 11.0 | 1.0 | 1.0 | 0.5954465849387041 | 0.099 | 0.041 | 39 |
| 14 | T2D | 17250 | 11.98 | 1.0 | 1.0 | 0.6038528896672505 | 0.172 | 0.122 | 40 |
| 15 | healthy | 16875 | 11.97 | 1.0 | 1.0 | 0.5890218156228009 | 0.158 | 0.118 | 52 |
| 16 | prediabetes | 16290 | 11.31 | 1.0 | 1.0 | 0.6161821366024518 | 0.124 | 0.065 | 28 |
| 17 | healthy | 16185 | 11.24 | 1.0 | 1.0 | 0.6014044943820225 | 0.12 | 0.187 | 48 |
| 18 | healthy | 14085 | 19.15 | 1.0 | 1.0 | 0.6143964403617052 | 0.011 | 0.007 | 39 |
| 19 | healthy | 14430 | 10.03 | 1.0 | 1.0 | 0.5798036465638149 | 0.012 | 0.02 | 48 |
| 20 | prediabetes | 16260 | 11.29 | 1.0 | 1.0 | 0.612539404553415 | 0.122 | 0.117 | 41 |
| 21 | healthy | 16125 | 11.2 | 1.0 | 1.0 | 0.5856392294220666 | 0.115 | 0.063 | 39 |
| 22 | prediabetes | 17625 | 12.24 | 1.0 | 1.0 | 0.6122591943957969 | 0.19 | 0.177 | 42 |
| 23 | prediabetes | 16185 | 11.24 | 1.0 | 1.0 | 0.6286715737819839 | 0.119 | 0.065 | 42 |
| 26 | prediabetes | 16320 | 11.33 | 1.0 | 1.0 | 0.6313657407407407 | 0.153 | 0.068 | 36 |
| 27 | healthy | 14535 | 10.09 | 1.0 | 1.0 | 0.6049261083743842 | 0.022 | 0.003 | 36 |
| 28 | T2D | 18735 | 13.01 | 1.0 | 1.0 | 0.6063246661981728 | 0.24 | 0.237 | 34 |
| 29 | prediabetes | 17730 | 12.31 | 1.0 | 1.0 | 0.5878809106830123 | 0.195 | 0.15 | 30 |
| 30 | T2D | 15465 | 10.74 | 1.0 | 1.0 | 0.6232230823363828 | 0.081 | 0.2 | 28 |
| 31 | healthy | 13725 | 9.53 | 1.0 | 1.0 | 0.6172017845388722 | 0.004 | 0.014 | 54 |
| 32 | healthy | 13785 | 9.57 | 1.0 | 1.0 | 0.6228031634446397 | 0.009 | 0.524 | 20 |
| 33 | healthy | 15840 | 11.01 | 1.0 | 1.0 | 0.6386211748153359 | 0.103 | 0.315 | 33 |
| 34 | healthy | 14700 | 10.21 | 1.0 | 1.0 | 0.6237478108581436 | 0.029 | 0.459 | 49 |
| 35 | T2D | 14400 | 10.0 | 1.0 | 1.0 | 0.6315346881569727 | 0.009 | 0.163 | 27 |
| 36 | T2D | 17115 | 11.88 | 1.0 | 1.0 | 0.6285113835376532 | 0.166 | 0.158 | 30 |
| 38 | T2D | 14505 | 10.07 | 1.0 | 1.0 | 0.620322354590049 | 0.016 | 0.011 | 40 |
| 39 | T2D | 17205 | 11.95 | 1.0 | 1.0 | 0.6299124343257443 | 0.17 | 0.167 | 34 |
| 41 | prediabetes | 14310 | 9.94 | 1.0 | 1.0 | 0.6179341338389158 | 0.005 | 0.312 | 48 |
| 42 | T2D | 14520 | 10.08 | 1.0 | 1.0 | 0.6343957968476357 | 0.017 | 0.088 | 22 |
| 43 | prediabetes | 14520 | 10.09 | 1.0 | 1.0 | 0.600210378681627 | 0.018 | 0.035 | 64 |
| 44 | prediabetes | 14535 | 10.09 | 1.0 | 1.0 | 0.5896660808435852 | 0.021 | 0.159 | 43 |
| 45 | prediabetes | 15570 | 10.81 | 1.0 | 1.0 | 0.6405735606116029 | 0.122 | 0.062 | 32 |
| 46 | T2D | 14655 | 10.2 | 1.0 | 1.0 | 0.6219726219726219 | 0.028 | 0.07 | 29 |
| 47 | T2D | 15690 | 10.9 | 1.0 | 1.0 | 0.6473110720562391 | 0.093 | 0.082 | 29 |
| 48 | healthy | 17340 | 12.05 | 1.0 | 1.0 | 0.603015427769986 | 0.178 | 0.173 | 36 |
| 49 | T2D | 15315 | 10.63 | 1.0 | 1.0 | 0.6231873905429072 | 0.068 | 0.088 | 28 |

## Meals and label

- meal_rows_total: 1663
- by_meal_type: {'dinner': 418, 'snack': 300, 'lunch': 272, 'breakfast': 266, 'Breakfast': 160, 'Lunch': 153, 'Dinner': 60, 'Snacks': 29, 'Snack': 4, 'snack 1': 1}
- amount_consumed_non_null: 1599
- amount_consumed_lt_100: 391
- carbs_fractional_share_partial_meals: 0.0
- carbs_fractional_share_full_meals: 0.0018570102135561746
- breakfast_count: 426
- breakfast_distinct_macro_profiles: 6
- macro_ranges: {'carbs': [0.0, 761.0], 'protein': [0.0, 148.0], 'fat': [0.0, 508.0], 'fiber': [0.0, 2830.0]}
- exclusions: {'overlapping_next_meal_within_horizon': 244, 'coverage_below_min': 52, 'no_pre_meal_reading': 19}
- usable_meals: 1368
- usable_meals_with_pre_meal_reading: 1368
- positives: 580
- positive_rate: 0.424
- positives_already_above_threshold_pre_meal: 90
- participants_with_zero_positives: 2
- post_meal_mets_present_share_mean: 1.0

### By glycemic group

| Group | Participants | With ≥1 positive | Usable meals | Positives |
| --- | --- | --- | --- | --- |
| T2D | 14 | 14 | 412 | 277 |
| healthy | 14 | 13 | 445 | 99 |
| prediabetes | 16 | 15 | 511 | 204 |

### By participant

| ID | Group | Usable | Positives |
| --- | --- | --- | --- |
| 2 | healthy | 27 | 12 |
| 3 | T2D | 32 | 14 |
| 4 | healthy | 38 | 2 |
| 5 | T2D | 34 | 16 |
| 6 | healthy | 33 | 4 |
| 7 | prediabetes | 1 | 0 |
| 8 | prediabetes | 28 | 10 |
| 9 | prediabetes | 36 | 6 |
| 10 | prediabetes | 37 | 8 |
| 11 | prediabetes | 36 | 13 |
| 12 | T2D | 32 | 16 |
| 13 | prediabetes | 35 | 6 |
| 14 | T2D | 34 | 17 |
| 15 | healthy | 33 | 2 |
| 16 | prediabetes | 27 | 4 |
| 17 | healthy | 34 | 4 |
| 18 | healthy | 33 | 19 |
| 19 | healthy | 34 | 11 |
| 20 | prediabetes | 35 | 29 |
| 21 | healthy | 32 | 7 |
| 22 | prediabetes | 36 | 3 |
| 23 | prediabetes | 39 | 29 |
| 26 | prediabetes | 28 | 14 |
| 27 | healthy | 31 | 6 |
| 28 | T2D | 31 | 19 |
| 29 | prediabetes | 29 | 8 |
| 30 | T2D | 27 | 22 |
| 31 | healthy | 30 | 2 |
| 32 | healthy | 20 | 1 |
| 33 | healthy | 32 | 21 |
| 34 | healthy | 35 | 0 |
| 35 | T2D | 27 | 25 |
| 36 | T2D | 29 | 17 |
| 38 | T2D | 33 | 17 |
| 39 | T2D | 31 | 30 |
| 41 | prediabetes | 41 | 35 |
| 42 | T2D | 21 | 12 |
| 43 | prediabetes | 40 | 9 |
| 44 | prediabetes | 34 | 12 |
| 45 | prediabetes | 29 | 18 |
| 46 | T2D | 26 | 19 |
| 47 | T2D | 28 | 27 |
| 48 | healthy | 33 | 8 |
| 49 | T2D | 27 | 26 |

### Sensitivity grid

| Horizon (min) | Label | Usable | Positives | Rate | People with positive |
| --- | --- | --- | --- | --- | --- |
| 60 | 140 | 1457 | 986 | 0.6767 | 44 |
| 60 | 160 | 1457 | 705 | 0.4839 | 43 |
| 60 | 180 | 1457 | 476 | 0.3267 | 39 |
| 60 | 200 | 1457 | 313 | 0.2148 | 32 |
| 60 | rise>=30 | 1457 | 823 | 0.5649 | 43 |
| 60 | rise>=50 | 1457 | 511 | 0.3507 | 41 |
| 60 | rise>=70 | 1457 | 289 | 0.1984 | 39 |
| 90 | 140 | 1418 | 1039 | 0.7327 | 44 |
| 90 | 160 | 1418 | 771 | 0.5437 | 44 |
| 90 | 180 | 1418 | 551 | 0.3886 | 41 |
| 90 | 200 | 1418 | 380 | 0.268 | 35 |
| 90 | rise>=30 | 1418 | 904 | 0.6375 | 44 |
| 90 | rise>=50 | 1418 | 598 | 0.4217 | 44 |
| 90 | rise>=70 | 1418 | 382 | 0.2694 | 42 |
| 120 | 140 | 1368 | 1064 | 0.7778 | 43 |
| 120 | 160 | 1368 | 805 | 0.5885 | 42 |
| 120 | 180 | 1368 | 580 | 0.424 | 42 |
| 120 | 200 | 1368 | 402 | 0.2939 | 36 |
| 120 | rise>=30 | 1368 | 949 | 0.6937 | 44 |
| 120 | rise>=50 | 1368 | 649 | 0.4744 | 44 |
| 120 | rise>=70 | 1368 | 408 | 0.2982 | 42 |
| 180 | 140 | 1279 | 1033 | 0.8077 | 44 |
| 180 | 160 | 1279 | 802 | 0.6271 | 43 |
| 180 | 180 | 1279 | 582 | 0.455 | 42 |
| 180 | 200 | 1279 | 410 | 0.3206 | 37 |
| 180 | rise>=30 | 1279 | 948 | 0.7412 | 44 |
| 180 | rise>=50 | 1279 | 662 | 0.5176 | 44 |
| 180 | rise>=70 | 1279 | 416 | 0.3253 | 42 |
