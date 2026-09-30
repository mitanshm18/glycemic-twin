"""Apply cleaning.v1 and labels.v1 to one participant's staged data.

Order matters and is fixed:
1. Meals are taken from the staged rows before any de-duplication, so no meal can be lost.
2. Duplicate timestamps collapse (identical) or null the conflicting sensor values.
3. CGM range rule, then native-grid detection on the cleaned values.
4. Wearable rules (METs scale, ranges; missing columns stay unknown).
5. Meal rules (type, Amount Consumed validity, macro validity).
6. Frozen outcomes and exclusions from twin_core.labels.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import pandas as pd
from twin_core.cleaning.cgm import GridResult, detect_native_grid, out_of_range_mask
from twin_core.cleaning.meals import clean_amount_consumed, macro_validity, normalize_meal_type
from twin_core.cleaning.timeseries import collapse_duplicates, gap_steps
from twin_core.cleaning.wearable import clean_wearable
from twin_core.config import CleaningConfig, LabelConfig
from twin_core.labels import meal_outcomes

SENSOR_COLUMNS = ["dexcom_raw", "libre_raw", "hr_raw", "mets_raw", "activity_kcal_raw"]


@dataclass
class ParticipantResult:
    participant_id: int
    cgm: pd.DataFrame
    wearable: pd.DataFrame
    meals: pd.DataFrame
    outcomes: pd.DataFrame
    stats: dict[str, Any]


def grid_summary(grid: GridResult) -> dict[str, Any]:
    return {
        "decision": grid.decision,
        "period_min": grid.period_min,
        "n_values": grid.n_values,
        "n_native": grid.n_native,
        "native_share": round(grid.n_native / grid.n_values, 4) if grid.n_values else None,
        "linear_share": None if grid.linear_share is None else round(grid.linear_share, 4),
        "segments": [
            {
                **{k: v for k, v in asdict(s).items() if k != "integer_share_by_phase"},
                "integer_share_by_phase": [
                    None if v != v else round(v, 4) for v in s.integer_share_by_phase
                ],
            }
            for s in grid.segments
        ],
    }


def clean_participant(
    staged: pd.DataFrame,
    columns_present: set[str],
    ccfg: CleaningConfig,
    lcfg: LabelConfig,
) -> ParticipantResult:
    pid = int(staged["participant_id"].iloc[0])

    # 1. meals from staged rows (before de-duplication)
    m = staged.loc[staged["meal_type_raw"].notna()].copy()
    meals = pd.DataFrame(
        {
            "meal_id": [f"{pid}-{r}" for r in m["source_row"]],
            "participant_id": pid,
            "started_at": m["ts"].to_numpy(),
            "meal_type_raw": m["meal_type_raw"].to_numpy(),
            "meal_type": [normalize_meal_type(v, ccfg.meals) for v in m["meal_type_raw"]],
            "carbs_g": m["carbs_g"].to_numpy(),
            "protein_g": m["protein_g"].to_numpy(),
            "fat_g": m["fat_g"].to_numpy(),
            "fiber_g": m["fiber_g"].to_numpy(),
            "calories_kcal": m["calories_kcal"].to_numpy(),
            "amount_consumed_raw": m["amount_consumed_raw"].to_numpy(),
            "image_path": m["image_path"].to_numpy(),
            "source_file": m["source_file"].to_numpy(),
            "source_row": m["source_row"].to_numpy(),
        }
    )
    meals = meals[meals["meal_type"].notna()].reset_index(drop=True)  # whitespace-only labels
    amount_clean, amount_invalid = clean_amount_consumed(meals["amount_consumed_raw"], ccfg.meals)
    meals["amount_consumed_pct"] = amount_clean
    meals["amount_consumed_invalid"] = amount_invalid
    meals = pd.concat([meals, macro_validity(meals, ccfg.meals)], axis=1)
    meals["duplicate_start"] = meals.duplicated("started_at", keep=False)

    # 2. duplicate timestamps
    ts_frame, conflict, dup_stats = collapse_duplicates(staged, "ts", SENSOR_COLUMNS)
    gaps = gap_steps(ts_frame["ts"], ccfg.timeseries.gap_flag_min)

    # 3. CGM
    cgm = pd.DataFrame({"participant_id": pid, "ts": ts_frame["ts"]})
    grids: dict[str, GridResult] = {}
    for sensor, raw_col, period in (
        ("dexcom", "dexcom_raw", ccfg.cgm.native_grid.dexcom_period_min),
        ("libre", "libre_raw", ccfg.cgm.native_grid.libre_period_min),
    ):
        bad = out_of_range_mask(ts_frame[raw_col], ccfg.cgm.valid_range_mgdl)
        values = ts_frame[raw_col].mask(bad)
        grid, native = detect_native_grid(
            ts_frame["ts"], values, period, ccfg.cgm.native_grid, sensor
        )
        cgm[f"{sensor}_mgdl"] = values.to_numpy()
        cgm[f"{sensor}_is_native"] = native
        cgm[f"{sensor}_out_of_range"] = bad.to_numpy()
        grids[sensor] = grid
    cgm["duplicate_conflict"] = conflict.to_numpy()

    # 4. wearable
    wear, wstats = clean_wearable(
        ts_frame["hr_raw"],
        ts_frame["mets_raw"] if "mets_raw" in columns_present else None,
        ts_frame["activity_kcal_raw"] if "activity_kcal_raw" in columns_present else None,
        ccfg.wearable,
    )
    wearable = pd.concat(
        [pd.DataFrame({"participant_id": pid, "ts": ts_frame["ts"]}), wear], axis=1
    )

    # 6. outcomes
    outcomes = meal_outcomes(
        meals[["meal_id", "started_at", "macro_validity"]],
        cgm[["ts", "dexcom_mgdl", "dexcom_is_native"]],
        lcfg,
    )
    outcomes.insert(1, "participant_id", pid)

    span = ts_frame["ts"].max() - ts_frame["ts"].min()
    stats: dict[str, Any] = {
        "participant_id": pid,
        "rows_staged": len(staged),
        "rows_after_dedup": len(ts_frame),
        "first_ts": str(ts_frame["ts"].min()),
        "last_ts": str(ts_frame["ts"].max()),
        "span_days": round(span.total_seconds() / 86400, 3),
        "duplicates": asdict(dup_stats),
        "gaps_over_flag": int(len(gaps)),
        "longest_gap_min": float(gaps.max()) if len(gaps) else 0.0,
        "missing_share": {
            "dexcom": round(float(cgm["dexcom_mgdl"].isna().mean()), 4),
            "libre": round(float(cgm["libre_mgdl"].isna().mean()), 4),
            "hr": round(float(wearable["hr_bpm"].isna().mean()), 4),
            "mets": round(float(wearable["mets"].isna().mean()), 4),
            "activity_kcal": round(float(wearable["activity_kcal"].isna().mean()), 4),
        },
        "cgm_out_of_range": {
            "dexcom": int(cgm["dexcom_out_of_range"].sum()),
            "libre": int(cgm["libre_out_of_range"].sum()),
        },
        "wearable": asdict(wstats),
        "native_grid": {k: grid_summary(g) for k, g in grids.items()},
        "meals": int(len(meals)),
    }
    return ParticipantResult(pid, cgm, wearable, meals, outcomes, stats)
