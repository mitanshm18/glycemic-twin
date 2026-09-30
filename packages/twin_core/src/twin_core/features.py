"""Leakage-safe meal features (features.v1.yaml). Shared by offline training and, from M5, the API.

Guarantees, each enforced by construction and by tests:

1. **Native CGM only.** ``ParticipantHistory`` stores only native Dexcom readings, so interpolated
   minutes (partly built from readings after t0) cannot be read at all (ADR-009, ADR-013).
2. **Nothing after t0.** CGM readings with ts <= t0; wearable minutes with ts < t0; previous meals
   with start < t0; a past meal's outcome only once its window has closed (start + 120 <= t0).
   Every function reports the latest timestamp it used (``max_source_ts``); the pipeline asserts it
   is <= t0 for every meal.
3. **The current meal contributes only what is known when it is logged**: its logged macros, type
   and time. Amount Consumed, the peak and the label never enter.

Future invariance: for any cutoff >= t0, ``meal_features(history.truncate(cutoff), meal)`` equals
``meal_features(history, meal)``. Tests check this with random future data appended.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace

import numpy as np
import pandas as pd

from twin_core.config import FeatureConfig

MINUTE = np.timedelta64(1, "m")
NAT = np.datetime64("NaT", "ns")
MEAL_TYPES = ("breakfast", "lunch", "dinner", "snack")


def as_ns(value: object) -> np.datetime64:
    """Any timestamp-like scalar -> numpy datetime64[ns]."""
    out: np.datetime64 = np.asarray(value).astype("datetime64[ns]")[()]  # type: ignore[assignment]
    return out


@dataclass(frozen=True)
class ParticipantHistory:
    """Everything the twin may know about one person. Arrays are sorted by time."""

    participant_id: int
    cgm_ts: np.ndarray  # native Dexcom readings only
    cgm_val: np.ndarray
    wear_ts: np.ndarray  # one row per minute
    hr: np.ndarray
    mets: np.ndarray
    kcal: np.ndarray
    mets_available: bool
    meal_ts: np.ndarray  # every logged meal start
    meal_carbs: np.ndarray  # NaN where the meal's macros are not valid
    meal_valid: np.ndarray
    outcome_end_ts: np.ndarray  # meal start + horizon: when that meal's outcome becomes known
    outcome_label: np.ndarray  # frozen label, NaN when the meal is not frozen-usable
    clinical: Mapping[str, float]

    def truncate(self, cutoff: np.datetime64) -> ParticipantHistory:
        """The history as it existed at ``cutoff``: later observations and meals removed, and
        outcomes whose window had not closed by ``cutoff`` unknown."""
        c = as_ns(cutoff)
        keep_cgm = self.cgm_ts <= c
        keep_wear = self.wear_ts <= c
        keep_meal = self.meal_ts <= c
        label = np.where(self.outcome_end_ts[keep_meal] <= c, self.outcome_label[keep_meal], np.nan)
        return replace(
            self,
            cgm_ts=self.cgm_ts[keep_cgm],
            cgm_val=self.cgm_val[keep_cgm],
            wear_ts=self.wear_ts[keep_wear],
            hr=self.hr[keep_wear],
            mets=self.mets[keep_wear],
            kcal=self.kcal[keep_wear],
            meal_ts=self.meal_ts[keep_meal],
            meal_carbs=self.meal_carbs[keep_meal],
            meal_valid=self.meal_valid[keep_meal],
            outcome_end_ts=self.outcome_end_ts[keep_meal],
            outcome_label=label,
        )


@dataclass(frozen=True)
class MealInput:
    """What is known about a meal when it is logged."""

    started_at: np.datetime64
    meal_type: str | None
    carbs_g: float
    protein_g: float
    fat_g: float
    fiber_g: float
    calories_kcal: float
    macros_valid: bool


class _Sources:
    """Tracks the latest timestamp any feature read."""

    def __init__(self) -> None:
        self.max_ts: np.datetime64 = NAT

    def saw(self, ts: np.ndarray) -> None:
        if len(ts):
            last = ts.max()
            if np.isnat(self.max_ts) or last > self.max_ts:
                self.max_ts = last


def _window(ts: np.ndarray, start: np.datetime64, end: np.datetime64, *, closed_end: bool) -> slice:
    lo = np.searchsorted(ts, start, side="left")
    hi = np.searchsorted(ts, end, side="right" if closed_end else "left")
    return slice(lo, hi)


def _slope(ts: np.ndarray, vals: np.ndarray, t0: np.datetime64) -> float:
    x = (ts - t0) / MINUTE
    x = x - x.mean()
    denom = float((x * x).sum())
    return float((x * (vals - vals.mean())).sum() / denom) if denom > 0 else np.nan


def _day_start(t: np.datetime64) -> np.datetime64:
    return t.astype("datetime64[D]").astype("datetime64[ns]")


def meal_features(
    h: ParticipantHistory, meal: MealInput, cfg: FeatureConfig
) -> tuple[dict[str, float], np.datetime64]:
    """Features for one meal and the latest source timestamp used (always <= meal start)."""
    w = cfg.windows
    t0 = as_ns(meal.started_at)
    src = _Sources()
    f: dict[str, float] = {}

    # --- glucose: native readings with ts <= t0 ---------------------------------------------------
    past = slice(0, np.searchsorted(h.cgm_ts, t0, side="right"))
    cts, cval = h.cgm_ts[past], h.cgm_val[past]
    if len(cts):
        age = (t0 - cts[-1]) / MINUTE
        f["g_age_min"] = float(min(age, 1440))
        src.saw(cts[-1:])
        f["g_last"] = float(cval[-1]) if age <= w.g_last_lookback_min else np.nan
    else:
        f["g_age_min"] = np.nan
        f["g_last"] = np.nan

    for name, minutes in (("slope_15", w.slope_short_min), ("slope_30", w.slope_long_min)):
        s = _window(cts, t0 - minutes * MINUTE, t0, closed_end=True)
        f[name] = (
            _slope(cts[s], cval[s], t0) if s.stop - s.start >= w.min_slope_readings else np.nan
        )
        src.saw(cts[s])

    s = _window(cts, t0 - w.sd_window_min * MINUTE, t0, closed_end=True)
    f["sd_60"] = float(np.std(cval[s], ddof=1)) if s.stop - s.start >= w.min_sd_readings else np.nan
    src.saw(cts[s])

    s = _window(cts, t0 - w.stats_window_min * MINUTE, t0, closed_end=True)
    enough = s.stop - s.start >= w.min_native_coverage * w.stats_window_min / 5
    for name, fn in (("mean_180", np.mean), ("min_180", np.min), ("max_180", np.max)):
        f[name] = float(fn(cval[s])) if enough else np.nan
    src.saw(cts[s])

    s = _window(cts, t0 - w.tir_window_min * MINUTE, t0, closed_end=True)
    lo, hi = w.target_range_mgdl
    if s.stop - s.start >= w.min_native_coverage * w.tir_window_min / 5:
        v = cval[s]
        f["tir_24h"] = float(((v >= lo) & (v <= hi)).mean())
    else:
        f["tir_24h"] = np.nan
    src.saw(cts[s])

    # overnight baseline from completed nights only (night end <= t0)
    start_h, end_h = w.overnight_hours
    days = cts.astype("datetime64[D]").astype("datetime64[ns]")
    hour = (cts - days) / np.timedelta64(1, "h")
    night = (hour >= start_h) & (hour < end_h) & (days + np.timedelta64(end_h, "h") <= t0)
    if night.sum() >= w.min_overnight_readings:
        f["g_overnight_baseline"] = float(np.median(cval[night]))
        src.saw(cts[night])
    else:
        f["g_overnight_baseline"] = np.nan
    f["g_vs_baseline"] = f["g_last"] - f["g_overnight_baseline"]

    # --- the meal itself (known when logged) -----------------------------------------------------
    for col in ("carbs_g", "protein_g", "fat_g", "fiber_g", "calories_kcal"):
        f[col] = float(getattr(meal, col)) if meal.macros_valid else np.nan
    for mt in MEAL_TYPES:
        f[f"meal_{mt}"] = 1.0 if meal.meal_type == mt else 0.0
    ts0 = pd.Timestamp(t0)
    hour_of_day = ts0.hour + ts0.minute / 60
    f["hour_sin"] = float(np.sin(2 * np.pi * hour_of_day / 24))
    f["hour_cos"] = float(np.cos(2 * np.pi * hour_of_day / 24))

    # --- context: earlier meals (start < t0) -----------------------------------------------------
    s = _window(h.meal_ts, t0 - w.prev_meal_window_min * MINUTE, t0, closed_end=False)
    carbs = h.meal_carbs[s]
    f["carbs_prev_3h"] = float(np.nansum(carbs)) if len(carbs) else 0.0
    f["invalid_meal_prev_3h"] = float((~h.meal_valid[s]).any()) if len(carbs) else 0.0
    src.saw(h.meal_ts[s])
    earlier = np.searchsorted(h.meal_ts, t0, side="left")
    if earlier:
        gap = (t0 - h.meal_ts[earlier - 1]) / MINUTE
        f["mins_since_meal"] = float(min(gap, w.mins_since_meal_cap))
        src.saw(h.meal_ts[earlier - 1 : earlier])
    else:
        f["mins_since_meal"] = float(w.mins_since_meal_cap)

    # --- wearable: minutes with ts < t0 ------------------------------------------------------------
    def mean_if_covered(values: np.ndarray, minutes: int) -> float:
        ok = ~np.isnan(values)
        return float(values[ok].mean()) if ok.sum() >= w.min_wearable_coverage * minutes else np.nan

    s = _window(h.wear_ts, t0 - w.hr_window_min * MINUTE, t0, closed_end=False)
    f["hr_30"] = mean_if_covered(h.hr[s], w.hr_window_min)
    src.saw(h.wear_ts[s])

    before_today = slice(0, np.searchsorted(h.wear_ts, _day_start(t0), side="left"))
    hr_prev, mets_prev, ts_prev = h.hr[before_today], h.mets[before_today], h.wear_ts[before_today]
    if h.mets_available:
        rest = ~np.isnan(hr_prev) & (mets_prev <= w.sedentary_mets_max)
    else:
        day_prev = ts_prev.astype("datetime64[D]").astype("datetime64[ns]")
        hr_hour = (ts_prev - day_prev) / np.timedelta64(1, "h")
        rest = ~np.isnan(hr_prev) & (hr_hour >= start_h) & (hr_hour < end_h)
    if rest.sum() >= w.min_resting_hr_minutes:
        f["hr_resting"] = float(np.percentile(hr_prev[rest], w.resting_hr_percentile))
        src.saw(ts_prev[rest])
    else:
        f["hr_resting"] = np.nan
    f["hr_delta"] = f["hr_30"] - f["hr_resting"]

    f["mets_available"] = 1.0 if h.mets_available else 0.0
    s = _window(h.wear_ts, t0 - w.mets_window_min * MINUTE, t0, closed_end=False)
    f["mets_60"] = mean_if_covered(h.mets[s], w.mets_window_min) if h.mets_available else np.nan
    f["activity_kcal_60"] = mean_if_covered(h.kcal[s], w.mets_window_min)
    src.saw(h.wear_ts[s])
    s = _window(h.wear_ts, t0 - w.activity_window_min * MINUTE, t0, closed_end=False)
    m = h.mets[s]
    covered = (~np.isnan(m)).sum() >= w.min_wearable_coverage * w.activity_window_min
    f["active_min_3h"] = (
        float((m >= w.active_mets_min).sum()) if h.mets_available and covered else np.nan
    )
    src.saw(h.wear_ts[s])

    hr_before = slice(0, np.searchsorted(h.wear_ts, t0, side="left"))
    have_hr = np.flatnonzero(~np.isnan(h.hr[hr_before]))
    if len(have_hr):
        last = h.wear_ts[have_hr[-1]]
        f["hr_age_min"] = float(min((t0 - last) / MINUTE, 1440))
        src.saw(np.array([last]))
    else:
        f["hr_age_min"] = np.nan

    # --- clinical baseline (collected before the study) -------------------------------------------
    c = h.clinical
    for key in (
        "hba1c_pct",
        "fasting_glucose_mgdl",
        "fasting_insulin_uu_ml",
        "bmi",
        "age_years",
        "triglycerides_mgdl",
        "hdl_mgdl",
    ):
        f[key] = float(c.get(key, np.nan))
    f["homa_ir"] = f["fasting_glucose_mgdl"] * f["fasting_insulin_uu_ml"] / 405.0
    f["sex_female"] = float(c.get("sex_female", np.nan))

    # --- personal raw counts: past meals whose window has closed -----------------------------------
    closed = (h.outcome_end_ts <= t0) & ~np.isnan(h.outcome_label)
    f["n_closed_meals"] = float(closed.sum())
    f["n_closed_positive"] = float(np.nansum(h.outcome_label[closed]))
    src.saw(h.outcome_end_ts[closed])

    names = cfg.features.all()
    if set(f) != set(names):
        raise KeyError(
            f"feature set differs from config: extra {sorted(set(f) - set(names))}, "
            f"missing {sorted(set(names) - set(f))}"
        )
    return {k: f[k] for k in names}, src.max_ts


def history_from_tables(
    participant_id: int,
    cgm: pd.DataFrame,
    wearable: pd.DataFrame,
    meals: pd.DataFrame,
    outcomes: pd.DataFrame,
    clinical: Mapping[str, float],
    horizon_min: int,
) -> ParticipantHistory:
    """Build one person's history from the M1 clean tables (already filtered to that person)."""
    native = cgm[cgm["dexcom_is_native"] & cgm["dexcom_mgdl"].notna()].sort_values("ts")
    wear = wearable.sort_values("ts")
    m = meals.merge(outcomes[["meal_id", "frozen_usable", "label"]], on="meal_id", how="left")
    m = m.sort_values(["started_at", "meal_id"], kind="stable")
    valid = (m["macro_validity"] == "valid").to_numpy()
    start = m["started_at"].to_numpy(dtype="datetime64[ns]")
    label = np.where(
        m["frozen_usable"].fillna(False).to_numpy(dtype=bool),
        m["label"].astype("Float64").to_numpy(dtype=float, na_value=np.nan),
        np.nan,
    )
    return ParticipantHistory(
        participant_id=participant_id,
        cgm_ts=native["ts"].to_numpy(dtype="datetime64[ns]"),
        cgm_val=native["dexcom_mgdl"].to_numpy(dtype=float),
        wear_ts=wear["ts"].to_numpy(dtype="datetime64[ns]"),
        hr=wear["hr_bpm"].to_numpy(dtype=float),
        mets=wear["mets"].to_numpy(dtype=float),
        kcal=wear["activity_kcal"].to_numpy(dtype=float),
        mets_available=bool(wear["mets"].notna().any()),
        meal_ts=start,
        meal_carbs=np.where(valid, m["carbs_g"].to_numpy(dtype=float), np.nan),
        meal_valid=valid,
        outcome_end_ts=start + np.timedelta64(horizon_min, "m"),
        outcome_label=label,
        clinical=dict(clinical),
    )


def meal_input(row: Mapping[str, object]) -> MealInput:
    return MealInput(
        started_at=as_ns(row["started_at"]),
        meal_type=row.get("meal_type"),  # type: ignore[arg-type]
        carbs_g=float(row["carbs_g"]),  # type: ignore[arg-type]
        protein_g=float(row["protein_g"]),  # type: ignore[arg-type]
        fat_g=float(row["fat_g"]),  # type: ignore[arg-type]
        fiber_g=float(row["fiber_g"]),  # type: ignore[arg-type]
        calories_kcal=float(row["calories_kcal"]),  # type: ignore[arg-type]
        macros_valid=row.get("macro_validity") == "valid",
    )
