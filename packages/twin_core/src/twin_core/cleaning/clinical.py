"""Baseline clinical record (bio.csv) -> EHR-like, provenance-tagged observations.

Nothing is invented: every value comes from bio.csv, except two clearly labeled derivations
(glycemic group from HbA1c; nothing else in M1). There are no medication or diagnosis fields in the
source, so none are produced.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from twin_core.config import ClinicalConfig

# canonical name -> (unit, description). Units follow the CGMacros data dictionary,
# except HbA1c, whose dictionary unit (mmol/mol) contradicts its values (4.6-8.5 = percent).
CLINICAL_FIELDS: dict[str, tuple[str, str]] = {
    "age_years": ("years", "Age at start of study"),
    "sex": ("", "Gender as recorded (F/M)"),
    "bmi": ("kg/m2", "Body mass index at start of study"),
    "body_weight_lb": ("lb", "Body weight at start of study"),
    "height_in": ("in", "Height"),
    "ethnicity": ("", "Self-identified race/ethnicity"),
    "hba1c_pct": ("%", "HbA1c at start of study"),
    "fasting_glucose_mgdl": ("mg/dL", "Fasting plasma glucose at start of study"),
    "fasting_insulin_uu_ml": ("uU/mL", "Fasting insulin at start of study"),
    "triglycerides_mgdl": ("mg/dL", "Fasting triglycerides"),
    "cholesterol_mgdl": ("mg/dL", "Fasting total cholesterol"),
    "hdl_mgdl": ("mg/dL", "Fasting HDL cholesterol"),
    "non_hdl_mgdl": ("mg/dL", "Fasting non-HDL cholesterol"),
    "ldl_mgdl": ("mg/dL", "Fasting LDL cholesterol (calculated)"),
    "vldl_mgdl": ("mg/dL", "Fasting VLDL cholesterol (calculated)"),
    "chol_hdl_ratio": ("ratio", "Total cholesterol / HDL"),
    "lab_collection_time": ("HH:MM", "Time the fasting labs were collected"),
    "fingerstick_1_mgdl": ("mg/dL", "Contour fingerstick glucose #1"),
    "fingerstick_1_time": ("HH:MM", "Time of fingerstick #1"),
    "fingerstick_2_mgdl": ("mg/dL", "Contour fingerstick glucose #2"),
    "fingerstick_2_time": ("HH:MM", "Time of fingerstick #2"),
    "fingerstick_3_mgdl": ("mg/dL", "Contour fingerstick glucose #3"),
    "fingerstick_3_time": ("HH:MM", "Time of fingerstick #3"),
}
TEXT_FIELDS = {
    "sex",
    "ethnicity",
    "lab_collection_time",
    "fingerstick_1_time",
    "fingerstick_2_time",
    "fingerstick_3_time",
}


def glycemic_group(hba1c_pct: float | None, cfg: ClinicalConfig) -> str:
    if hba1c_pct is None or np.isnan(hba1c_pct):
        return "unknown"
    groups = cfg.glycemic_groups
    if hba1c_pct < groups.prediabetes_min:
        return "healthy"
    if hba1c_pct <= groups.t2d_min_exclusive:
        return "prediabetes"
    return "T2D"


def clean_clinical(
    bio: pd.DataFrame, cfg: ClinicalConfig, source_columns: dict[str, str]
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """``bio`` has canonical columns (see CLINICAL_FIELDS) plus ``subject_id``.

    ``source_columns`` maps each canonical field to its original bio.csv column name (provenance).

    Returns (wide, long). Wide: one row per subject with cleaned values and ``glycemic_group``.
    Long: one row per subject x field with value, unit, provenance, quality flag and source column.
    """
    wide = bio.copy()
    flags = pd.DataFrame(False, index=wide.index, columns=list(cfg.sentinels))
    for field, sentinel in cfg.sentinels.items():
        hit = wide[field].notna() & np.isclose(wide[field].astype(float), sentinel)
        flags[field] = hit
        wide.loc[hit, field] = np.nan
    wide["glycemic_group"] = [glycemic_group(v, cfg) for v in wide["hba1c_pct"].astype(float)]

    rows: list[dict[str, object]] = []
    for i, rec in wide.iterrows():
        sid = int(rec["subject_id"])
        for field, (unit, description) in CLINICAL_FIELDS.items():
            value = rec[field]
            sentinel_hit = bool(flags.at[i, field]) if field in flags.columns else False
            rows.append(
                {
                    "subject_id": sid,
                    "field": field,
                    "value_num": np.nan if field in TEXT_FIELDS else value,
                    "value_text": (None if pd.isna(value) else str(value))
                    if field in TEXT_FIELDS
                    else None,
                    "unit": unit,
                    "description": description,
                    "provenance": "observed",
                    "derivation": None,
                    "quality_flag": "sentinel_error_code" if sentinel_hit else None,
                    "source_file": "bio.csv",
                    "source_column": source_columns.get(field),
                }
            )
        rows.append(
            {
                "subject_id": sid,
                "field": "glycemic_group",
                "value_num": np.nan,
                "value_text": rec["glycemic_group"],
                "unit": "",
                "description": "Glycemic group from baseline HbA1c (derived, not a diagnosis)",
                "provenance": "derived",
                "derivation": (
                    f"HbA1c < {cfg.glycemic_groups.prediabetes_min}% healthy; "
                    f"{cfg.glycemic_groups.prediabetes_min}-{cfg.glycemic_groups.t2d_min_exclusive}% "
                    f"prediabetes; > {cfg.glycemic_groups.t2d_min_exclusive}% T2D"
                ),
                "quality_flag": None,
                "source_file": "bio.csv",
                "source_column": source_columns.get("hba1c_pct"),
            }
        )
    long = pd.DataFrame(rows)
    keep = ["subject_id", *CLINICAL_FIELDS.keys(), "glycemic_group"]
    return wide[keep].reset_index(drop=True), long
