"""Build the M2 meal-level dataset from the M1 clean tables.

One row per logged meal (all meals, so later meals can use earlier ones as history). Columns:
  identifiers   meal_id, participant_id, started_at, glycemic_group, meal_type, macro_validity, fold
  features      exactly the features.v1.yaml list, from twin_core.features (native CGM only)
  outcomes      label and exclusion columns from M1 (never features; see leakage.OUTCOME_COLUMNS)
  provenance    max_source_ts (latest timestamp any feature read; must be <= started_at)
Training and evaluation later use rows with eligible == True.
"""

from __future__ import annotations

import pandas as pd
from twin_core.config import FeatureConfig, LabelConfig
from twin_core.features import ParticipantHistory, history_from_tables, meal_features, meal_input

CLINICAL_KEYS = (
    "hba1c_pct",
    "fasting_glucose_mgdl",
    "fasting_insulin_uu_ml",
    "bmi",
    "age_years",
    "triglycerides_mgdl",
    "hdl_mgdl",
)
ID_COLUMNS = (
    "meal_id",
    "participant_id",
    "started_at",
    "glycemic_group",
    "meal_type",
    "macro_validity",
)
OUTCOME_KEEP = (
    "label",
    "frozen_usable",
    "eligible",
    "exclusion_reasons",
    "waterfall_reason",
    "peak_mgdl",
    "peak_native_mgdl",
    "pre_meal_native_mgdl",
    "next_meal_gap_min",
    "window_coverage",
    "already_high",
)


def clinical_for(row: pd.Series) -> dict[str, float]:
    out = {k: float(row[k]) for k in CLINICAL_KEYS}
    sex = str(row["sex"]).strip().upper() if pd.notna(row["sex"]) else ""
    out["sex_female"] = 1.0 if sex == "F" else 0.0 if sex == "M" else float("nan")
    return out


def build_dataset(
    tables: dict[str, pd.DataFrame], fcfg: FeatureConfig, lcfg: LabelConfig
) -> tuple[pd.DataFrame, dict[int, ParticipantHistory]]:
    meals = tables["meals"]
    outcomes = tables["meal_outcomes"]
    cgm, wear = tables["cgm"], tables["wearable"]
    clinical = tables["clinical_wide"].set_index("subject_id")

    rows: list[dict[str, object]] = []
    histories: dict[int, ParticipantHistory] = {}
    for pid, pm in meals.groupby("participant_id", sort=True):
        pid = int(pid)
        h = history_from_tables(
            pid,
            cgm[cgm["participant_id"] == pid],
            wear[wear["participant_id"] == pid],
            pm,
            outcomes[outcomes["participant_id"] == pid],
            clinical_for(clinical.loc[pid]),
            lcfg.horizon_min,
        )
        histories[pid] = h
        for rec in pm.sort_values(["started_at", "meal_id"], kind="stable").to_dict("records"):
            feats, src = meal_features(h, meal_input(rec), fcfg)
            rows.append({"meal_id": rec["meal_id"], **feats, "max_source_ts": src})

    feats_df = pd.DataFrame(rows)
    feature_cols = list(fcfg.features.all())
    out = (
        meals[["meal_id", "participant_id", "started_at", "meal_type", "macro_validity"]]
        .merge(outcomes[["meal_id", "glycemic_group", *OUTCOME_KEEP]], on="meal_id", how="left")
        .merge(feats_df, on="meal_id", how="left")
    )
    out["rise_native_mgdl"] = out["peak_native_mgdl"] - out["pre_meal_native_mgdl"]
    out["max_source_ts"] = pd.to_datetime(out["max_source_ts"])
    ordered = [*ID_COLUMNS, *feature_cols, *OUTCOME_KEEP, "rise_native_mgdl", "max_source_ts"]
    out = out[ordered].sort_values(["participant_id", "started_at", "meal_id"], kind="stable")
    return out.reset_index(drop=True), histories
