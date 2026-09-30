"""Small hand-built histories for feature tests (synthetic; tests only)."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd
from twin_core.features import MealInput, ParticipantHistory

T0 = pd.Timestamp("2021-06-03 12:00")
NS = "datetime64[ns]"


def ts(minutes: Sequence[float] | np.ndarray, base: pd.Timestamp = T0) -> np.ndarray:
    return (base + pd.to_timedelta(np.asarray(minutes, dtype=float), unit="min")).to_numpy(dtype=NS)


def history(
    cgm: dict[int, float] | None = None,
    wear_minutes: tuple[int, int] = (-3 * 1440, 60),
    hr: float | np.ndarray = 70.0,
    mets: float | np.ndarray | None = 1.2,
    meals: Sequence[tuple[int, float, bool, float]] = (),  # (minute, carbs, valid, label)
    clinical: dict[str, float] | None = None,
    horizon: int = 120,
) -> ParticipantHistory:
    cgm = cgm if cgm is not None else {m: 120.0 for m in range(-3 * 1440, 61, 5)}
    cm = np.array(sorted(cgm), dtype=float)
    wm = np.arange(wear_minutes[0], wear_minutes[1] + 1, dtype=float)
    n = len(wm)
    hr_arr = np.broadcast_to(np.asarray(hr, dtype=float), (n,)).copy()
    mets_arr = (
        np.full(n, np.nan)
        if mets is None
        else np.broadcast_to(np.asarray(mets, dtype=float), (n,)).copy()
    )
    meals = sorted(meals)
    mm = np.array([m[0] for m in meals], dtype=float)
    return ParticipantHistory(
        participant_id=1,
        cgm_ts=ts(cm),
        cgm_val=np.array([cgm[int(m)] for m in cm], dtype=float),
        wear_ts=ts(wm),
        hr=hr_arr,
        mets=mets_arr,
        kcal=np.full(n, 1.2),
        mets_available=mets is not None,
        meal_ts=ts(mm),
        meal_carbs=np.array([m[1] if m[2] else np.nan for m in meals], dtype=float),
        meal_valid=np.array([m[2] for m in meals], dtype=bool),
        outcome_end_ts=ts(mm + horizon),
        outcome_label=np.array([m[3] for m in meals], dtype=float),
        clinical=clinical
        or {
            "hba1c_pct": 6.1,
            "fasting_glucose_mgdl": 100.0,
            "fasting_insulin_uu_ml": 8.1,
            "bmi": 27.0,
            "age_years": 50.0,
            "triglycerides_mgdl": 120.0,
            "hdl_mgdl": 50.0,
            "sex_female": 1.0,
        },
    )


def meal(
    minute: float = 0, meal_type: str = "lunch", carbs: float = 60.0, valid: bool = True
) -> MealInput:
    return MealInput(
        started_at=ts([minute])[0],
        meal_type=meal_type,
        carbs_g=carbs,
        protein_g=20.0,
        fat_g=10.0,
        fiber_g=5.0,
        calories_kcal=4 * carbs + 80 + 90,
        macros_valid=valid,
    )
