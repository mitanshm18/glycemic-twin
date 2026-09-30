"""Data contracts: the exact shape we accept from CGMacros, checked before any cleaning.

A contract failure stops the run (ContractError). Silent schema drift, such as a renamed column that
becomes all-NaN, is the most common way data pipelines quietly produce wrong numbers.

Column sets come from the data dictionary plus the Phase 0A audit of all 44 files, which found
spelling variants ("Image path") and extra columns in some files (Intensity, Steps, Sugar,
RecordIndex, an unnamed index). Extra columns are known and ignored; any other column fails.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

# canonical -> accepted source names (compared after strip + lowercase)
PARTICIPANT_COLUMNS: dict[str, tuple[str, ...]] = {
    "ts": ("timestamp",),
    "libre_raw": ("libre gl",),
    "dexcom_raw": ("dexcom gl",),
    "hr_raw": ("hr",),
    "activity_kcal_raw": ("calories (activity)",),
    "mets_raw": ("mets",),
    "meal_type_raw": ("meal type",),
    "calories_kcal": ("calories",),
    "carbs_g": ("carbs",),
    "protein_g": ("protein",),
    "fat_g": ("fat",),
    "fiber_g": ("fiber",),
    "amount_consumed_raw": ("amount consumed",),
    "image_path": ("image path",),
}
REQUIRED_PARTICIPANT = frozenset(
    {
        "ts",
        "libre_raw",
        "dexcom_raw",
        "hr_raw",
        "meal_type_raw",
        "calories_kcal",
        "carbs_g",
        "protein_g",
        "fat_g",
        "fiber_g",
        "image_path",
    }
)
OPTIONAL_PARTICIPANT = frozenset({"activity_kcal_raw", "mets_raw", "amount_consumed_raw"})
IGNORED_PARTICIPANT = re.compile(r"^(intensity|steps|sugar|recordindex|unnamed: \d+)$")
PARTICIPANT_NUMERIC = (
    "libre_raw",
    "dexcom_raw",
    "hr_raw",
    "activity_kcal_raw",
    "mets_raw",
    "calories_kcal",
    "carbs_g",
    "protein_g",
    "fat_g",
    "fiber_g",
    "amount_consumed_raw",
)

BIO_COLUMNS: dict[str, str] = {
    "subject": "subject_id",
    "age": "age_years",
    "gender": "sex",
    "bmi": "bmi",
    "body weight": "body_weight_lb",
    "height": "height_in",
    "self-identify": "ethnicity",
    "a1c pdl (lab)": "hba1c_pct",
    "fasting glu - pdl (lab)": "fasting_glucose_mgdl",
    "insulin": "fasting_insulin_uu_ml",
    "triglycerides": "triglycerides_mgdl",
    "cholesterol": "cholesterol_mgdl",
    "hdl": "hdl_mgdl",
    "non hdl": "non_hdl_mgdl",
    "ldl (cal)": "ldl_mgdl",
    "vldl (cal)": "vldl_mgdl",
    "cho/hdl ratio": "chol_hdl_ratio",
    "collection time pdl (lab)": "lab_collection_time",
    "#1 contour fingerstick glu": "fingerstick_1_mgdl",
    "time (t)": "fingerstick_1_time",
    "#2 contour fingerstick glu": "fingerstick_2_mgdl",
    "time (t).1": "fingerstick_2_time",
    "#3 contour fingerstick glu": "fingerstick_3_mgdl",
    "time (t).2": "fingerstick_3_time",
}
BIO_TEXT = {
    "sex",
    "ethnicity",
    "lab_collection_time",
    "fingerstick_1_time",
    "fingerstick_2_time",
    "fingerstick_3_time",
}


class ContractError(RuntimeError):
    """The input does not match the contract. The run stops."""


@dataclass
class StageReport:
    source_file: str
    rows: int
    columns_present: dict[str, str] = field(default_factory=dict)  # canonical -> source name
    optional_missing: list[str] = field(default_factory=list)
    ignored_columns: list[str] = field(default_factory=list)
    non_numeric_values: dict[str, int] = field(default_factory=dict)
    timestamps_with_seconds: int = 0


def _norm(name: object) -> str:
    return str(name).strip().lower()


def stage_participant(
    raw: pd.DataFrame, participant_id: int, source_file: str
) -> tuple[pd.DataFrame, StageReport]:
    """Map source columns to canonical names, type them, and keep provenance (file + row)."""
    report = StageReport(source_file=source_file, rows=len(raw))
    lookup = {alias: canon for canon, aliases in PARTICIPANT_COLUMNS.items() for alias in aliases}
    rename: dict[str, str] = {}
    unknown: list[str] = []
    for col in raw.columns:
        key = _norm(col)
        if key in lookup:
            canon = lookup[key]
            if canon in rename.values():
                raise ContractError(f"{source_file}: two columns map to '{canon}'")
            rename[col] = canon
            report.columns_present[canon] = str(col)
        elif IGNORED_PARTICIPANT.match(key):
            report.ignored_columns.append(str(col))
        else:
            unknown.append(str(col))
    if unknown:
        raise ContractError(f"{source_file}: unknown columns {unknown}")
    missing = sorted(REQUIRED_PARTICIPANT - set(rename.values()))
    if missing:
        raise ContractError(f"{source_file}: required columns missing {missing}")

    df = raw.rename(columns=rename)[list(rename.values())].copy()
    for canon in sorted(OPTIONAL_PARTICIPANT - set(df.columns)):
        report.optional_missing.append(canon)
        df[canon] = np.nan  # absent column -> unknown, never zero

    ts = pd.to_datetime(df["ts"], format="mixed", errors="coerce")
    bad_ts = int(ts.isna().sum())
    if bad_ts:
        raise ContractError(f"{source_file}: {bad_ts} unparseable or missing timestamps")
    floored = ts.dt.floor("min")
    report.timestamps_with_seconds = int((floored != ts).sum())
    df["ts"] = floored

    for col in PARTICIPANT_NUMERIC:
        before = df[col].notna()
        num = pd.to_numeric(df[col], errors="coerce")
        lost = int((before & num.isna()).sum())
        if lost:
            report.non_numeric_values[col] = lost
        df[col] = num.astype(float)

    df["meal_type_raw"] = (
        df["meal_type_raw"].astype("object").where(df["meal_type_raw"].notna(), None)
    )
    df["image_path"] = df["image_path"].astype("object").where(df["image_path"].notna(), None)
    df.insert(0, "participant_id", participant_id)
    df["source_row"] = np.arange(len(df), dtype=np.int64)
    df["source_file"] = source_file
    return df, report


def stage_bio(raw: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, str]]:
    """Map bio.csv to canonical names. Returns (frame, canonical -> original column name)."""
    rename: dict[str, str] = {}
    unknown = []
    for col in raw.columns:
        key = _norm(col)
        if key in BIO_COLUMNS:
            rename[col] = BIO_COLUMNS[key]
        else:
            unknown.append(str(col))
    if unknown:
        raise ContractError(f"bio.csv: unknown columns {unknown}")
    missing = sorted(set(BIO_COLUMNS.values()) - set(rename.values()))
    if missing:
        raise ContractError(f"bio.csv: required columns missing {missing}")
    df = raw.rename(columns=rename).copy()
    ids = df["subject_id"].astype(str).str.extract(r"(\d+)", expand=False)
    if ids.isna().any():
        raise ContractError("bio.csv: subject values without a numeric ID")
    df["subject_id"] = ids.astype(int)
    if df["subject_id"].duplicated().any():
        raise ContractError("bio.csv: duplicate subject IDs")
    for col in BIO_COLUMNS.values():
        if col in BIO_TEXT or col == "subject_id":
            continue
        df[col] = pd.to_numeric(df[col], errors="coerce").astype(float)
    for col in BIO_TEXT:
        df[col] = df[col].astype("object").where(df[col].notna(), None)
        df[col] = df[col].map(lambda v: v.strip() if isinstance(v, str) else v)
    source_columns = {canon: str(orig) for orig, canon in rename.items()}
    return df, source_columns
