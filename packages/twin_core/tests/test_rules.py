"""Cleaning rules: duplicates, wearable, meals, clinical."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from twin_core.cleaning.clinical import CLINICAL_FIELDS, clean_clinical, glycemic_group
from twin_core.cleaning.meals import clean_amount_consumed, macro_validity, normalize_meal_type
from twin_core.cleaning.timeseries import collapse_duplicates, gap_steps
from twin_core.cleaning.wearable import clean_wearable
from twin_core.config import CleaningConfig

T = pd.Timestamp("2021-06-01 08:00")


# --- duplicates and gaps -----------------------------------------------------------------------
def test_identical_duplicates_collapse_and_conflicts_are_nulled() -> None:
    f = pd.DataFrame(
        {
            "ts": [
                T,
                T,
                T + pd.Timedelta(minutes=1),
                T + pd.Timedelta(minutes=1),
                T + pd.Timedelta(minutes=2),
            ],
            "dexcom": [100.0, 100.0, 110.0, 117.0, 120.0],
            "hr": [70.0, 70.0, 71.0, 71.0, np.nan],
        }
    )
    out, conflict, stats = collapse_duplicates(f, "ts", ["dexcom", "hr"])
    assert len(out) == 3
    assert out["dexcom"].tolist()[:2] == [100.0, pytest.approx(np.nan, nan_ok=True)]
    assert out["hr"].iloc[1] == 71.0  # only the disagreeing column is nulled
    assert conflict.tolist() == [False, True, False]
    assert (
        stats.duplicated_timestamps,
        stats.identical_groups,
        stats.conflicting_groups,
        stats.rows_removed,
    ) == (2, 1, 1, 2)


def test_nan_equals_nan_when_comparing_duplicates() -> None:
    f = pd.DataFrame({"ts": [T, T], "dexcom": [np.nan, np.nan]})
    _, conflict, stats = collapse_duplicates(f, "ts", ["dexcom"])
    assert stats.identical_groups == 1 and not conflict.any()


def test_gaps_are_reported_not_filled() -> None:
    ts = pd.Series([T, T + pd.Timedelta(minutes=1), T + pd.Timedelta(minutes=20)])
    assert gap_steps(ts, 5).tolist() == [19.0]


# --- wearable -----------------------------------------------------------------------------------
def test_mets_are_rescaled_and_missing_column_stays_unknown(ccfg: CleaningConfig) -> None:
    hr = pd.Series([70.0, 250.0, 25.0, np.nan])
    out, stats = clean_wearable(hr, pd.Series([10.0, 35.0, 500.0, np.nan]), None, ccfg.wearable)
    assert out["mets"].iloc[:2].tolist() == [1.0, 3.5]
    assert np.isnan(out["mets"].iloc[2])  # 50 METs after scaling is impossible
    assert out["hr_bpm"].isna().tolist() == [False, True, True, True]
    assert out["activity_kcal"].isna().all() and not (out["activity_kcal"] == 0).any()
    assert stats.hr_out_of_range == 2 and not stats.activity_kcal_available

    out2, stats2 = clean_wearable(hr, None, pd.Series([1.0, -1.0, 0.0, 2.0]), ccfg.wearable)
    assert out2["mets"].isna().all() and not stats2.mets_available
    assert stats2.activity_kcal_negative == 1


# --- meals --------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Breakfast", "breakfast"),
        (" lunch ", "lunch"),
        ("DINNER", "dinner"),
        ("snack", "snack"),
        ("Snacks", "snack"),
        ("snack 1", "snack"),
        ("Snack2", "snack"),
        ("brunch", "other"),
        ("", None),
        (None, None),
        (np.nan, None),
    ],
)
def test_meal_type_normalization(raw: object, expected: str | None, ccfg: CleaningConfig) -> None:
    assert normalize_meal_type(raw, ccfg.meals) == expected


def test_amount_consumed_outside_0_100_is_invalid(ccfg: CleaningConfig) -> None:
    clean, invalid = clean_amount_consumed(
        pd.Series([0.0, 50.0, 100.0, 900.0, -5.0, np.nan]), ccfg.meals
    )
    assert invalid.tolist() == [False, False, False, True, True, False]
    assert clean.isna().tolist() == [False, False, False, True, True, True]


def _meal(carbs: float, protein: float, fat: float, fiber: float, kcal: float) -> dict[str, float]:
    return {
        "carbs_g": carbs,
        "protein_g": protein,
        "fat_g": fat,
        "fiber_g": fiber,
        "calories_kcal": kcal,
    }


def test_macro_validity_classes_and_precedence(ccfg: CleaningConfig) -> None:
    meals = pd.DataFrame(
        [
            _meal(60, 20, 10, 5, 410),  # valid: Atwater 410 / 410
            _meal(60, 20, 10, 5, 100),  # inconsistent: ratio 4.1
            _meal(10, 5, 5, 20, 105),  # invalid: fiber > carbs
            _meal(-1, 5, 5, 0, 60),  # invalid: negative
            _meal(30, 0, 0, 0, 0),  # invalid: zero calories with macros
            _meal(0, 0, 0, 0, 0),  # empty
            _meal(np.nan, 1, 1, 1, 10),  # missing
            _meal(10, 5, 5, 20, 1000),  # invalid wins over inconsistent (fiber > carbs AND ratio)
        ]
    )
    out = macro_validity(meals, ccfg.meals)
    assert out["macro_validity"].tolist() == [
        "valid",
        "inconsistent",
        "invalid",
        "invalid",
        "invalid",
        "empty",
        "missing",
        "invalid",
    ]
    assert "energy_ratio_out_of_band" in out["macro_reasons"].iloc[7]
    assert "fiber_exceeds_carbs" in out["macro_reasons"].iloc[7]
    assert out["energy_ratio"].iloc[0] == pytest.approx(1.0)


def test_energy_ratio_band_edges_are_valid(ccfg: CleaningConfig) -> None:
    meals = pd.DataFrame([_meal(25, 0, 0, 0, 200), _meal(50, 0, 0, 0, 100)])  # ratio 0.5 and 2.0
    assert macro_validity(meals, ccfg.meals)["macro_validity"].tolist() == ["valid", "valid"]


# --- clinical -----------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("a1c", "group"),
    [
        (5.69, "healthy"),
        (5.7, "prediabetes"),
        (6.4, "prediabetes"),
        (6.41, "T2D"),
        (np.nan, "unknown"),
    ],
)
def test_glycemic_group_thresholds(a1c: float, group: str, ccfg: CleaningConfig) -> None:
    assert glycemic_group(a1c, ccfg.clinical) == group


def test_clinical_sentinels_nulled_flagged_and_provenance_kept(ccfg: CleaningConfig) -> None:
    row: dict[str, object] = {f: 1.0 for f in CLINICAL_FIELDS}
    row.update(
        {
            "subject_id": 7,
            "sex": "F",
            "ethnicity": "White",
            "lab_collection_time": "08:00",
            "fingerstick_1_time": "08:30",
            "fingerstick_2_time": "09:30",
            "fingerstick_3_time": "10:30",
            "hba1c_pct": 6.1,
            "ldl_mgdl": 800.0,
            "vldl_mgdl": 30.0,
            "chol_hdl_ratio": 400.0,
        }
    )
    wide, long = clean_clinical(pd.DataFrame([row]), ccfg.clinical, {"hba1c_pct": "A1c PDL (Lab)"})
    assert np.isnan(wide.loc[0, "ldl_mgdl"]) and np.isnan(wide.loc[0, "chol_hdl_ratio"])
    assert wide.loc[0, "vldl_mgdl"] == 30.0
    assert wide.loc[0, "glycemic_group"] == "prediabetes"
    flags = long.set_index("field")["quality_flag"]
    assert flags["ldl_mgdl"] == "sentinel_error_code" and pd.isna(flags["vldl_mgdl"])
    derived = long[long["provenance"] == "derived"]
    assert derived["field"].tolist() == ["glycemic_group"]  # the only derived field
    assert long.loc[long["field"] == "hba1c_pct", "source_column"].item() == "A1c PDL (Lab)"
    assert not long["field"].str.contains("medication|diagnosis").any()  # nothing invented
