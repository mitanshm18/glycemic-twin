"""Contracts fail loudly on schema drift and keep provenance."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from twin_ml.pipeline.contracts import ContractError, stage_bio, stage_participant


def minimal(**overrides: object) -> pd.DataFrame:
    base: dict[str, object] = {
        "Timestamp": ["2021-06-01 08:00:00", "2021-06-01 08:01:00"],
        "Libre GL": [100, np.nan],
        "Dexcom GL": [101.4, 102],
        "HR": [70, 71],
        "Meal Type": ["Breakfast", None],
        "Calories": [410, np.nan],
        "Carbs": [60, np.nan],
        "Protein": [20, np.nan],
        "Fat": [10, np.nan],
        "Fiber": [5, np.nan],
        "Image Path": ["a.jpg", None],
    }
    base.update(overrides)
    return pd.DataFrame(base)


def test_aliases_optional_columns_and_provenance() -> None:
    raw = minimal().rename(columns={"Image Path": "Image path"})
    raw["Mets"] = [10, 12]
    raw["Intensity"] = [0, 1]
    staged, rep = stage_participant(raw, 7, "CGMacros-007/CGMacros-007.csv")
    assert rep.columns_present["image_path"] == "Image path"
    assert rep.columns_present["mets_raw"] == "Mets"
    assert rep.ignored_columns == ["Intensity"]
    assert sorted(rep.optional_missing) == ["activity_kcal_raw", "amount_consumed_raw"]
    assert staged["activity_kcal_raw"].isna().all()  # absent column -> unknown, not 0
    assert staged["source_row"].tolist() == [0, 1]
    assert (staged["participant_id"] == 7).all()


def test_unknown_column_fails() -> None:
    raw = minimal()
    raw["Blood Pressure"] = 1
    with pytest.raises(ContractError, match="unknown columns"):
        stage_participant(raw, 1, "f.csv")


def test_missing_required_column_fails() -> None:
    with pytest.raises(ContractError, match="required columns missing"):
        stage_participant(minimal().drop(columns=["Dexcom GL"]), 1, "f.csv")


def test_bad_timestamp_fails() -> None:
    with pytest.raises(ContractError, match="timestamps"):
        stage_participant(minimal(Timestamp=["2021-06-01 08:00:00", "not a time"]), 1, "f.csv")


def test_mixed_timestamp_formats_and_seconds_are_handled() -> None:
    staged, rep = stage_participant(
        minimal(Timestamp=["6/1/2021 08:00", "2021-06-01 08:01:30"]), 1, "f.csv"
    )
    assert staged["ts"].tolist() == [
        pd.Timestamp("2021-06-01 08:00"),
        pd.Timestamp("2021-06-01 08:01"),
    ]
    assert rep.timestamps_with_seconds == 1


def test_non_numeric_values_are_counted_not_hidden() -> None:
    _, rep = stage_participant(minimal(HR=["70", "n/a"]), 1, "f.csv")
    assert rep.non_numeric_values == {"hr_raw": 1}


def test_bio_contract_maps_duplicate_time_columns() -> None:
    cols = [
        "subject",
        "Age",
        "Gender",
        "BMI",
        "Body weight ",
        "Height ",
        "Self-identify ",
        "A1c PDL (Lab)",
        "Fasting GLU - PDL (Lab)",
        "Insulin ",
        "Triglycerides",
        "Cholesterol",
        "HDL",
        "Non HDL ",
        "LDL (Cal)",
        "VLDL (Cal)",
        "Cho/HDL Ratio",
        "Collection time PDL (Lab)",
        "#1 Contour Fingerstick GLU",
        "Time (t)",
        " #2 Contour Fingerstick GLU",
        "Time (t).1",
        "#3 Contour Fingerstick GLU",
        "Time (t).2",
    ]
    raw = pd.DataFrame(
        [[f"CGMacros-00{i}" if c == "subject" else 1 for c in cols] for i in (2, 3)], columns=cols
    )
    staged, source_cols = stage_bio(raw)
    assert staged["subject_id"].tolist() == [2, 3]
    assert source_cols["fingerstick_2_time"] == "Time (t).1"
    assert source_cols["hba1c_pct"] == "A1c PDL (Lab)"
    with pytest.raises(ContractError, match="unknown"):
        stage_bio(raw.assign(Medication="metformin"))
