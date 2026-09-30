"""Frozen meal outcome (labels.v1.yaml) and the exclusions applied on top of it.

Label (frozen in Phase 0A): 1 if Dexcom > threshold at any minute row in (t0, t0 + horizon].
Usability (frozen): no other meal starts < horizon after t0, and >= min_window_coverage of the
window's minute rows have a Dexcom value. Peak and coverage deliberately use minute rows, exactly as
in the frozen audit, so the frozen numbers are reproducible.

Added exclusions (decided in Phase 0A/0B, before any model):
- no native Dexcom reading in [t0 - lookback, t0]      -> pre-meal state unknown
- that native reading > already_high_threshold          -> excursion already under way
- meal macro validity in exclude_macro_validity         -> meal cannot be described
Only NATIVE readings define the pre-meal value, because interpolated minutes before t0 are partly
built from readings after t0.

Label basis vs feature basis (ADR-013): the label deliberately stays on the frozen 1-minute series
for reproducibility with Phase 0A, while every model feature uses native readings only. Because the
1-minute series contains interpolated values, the frozen label can differ from a native-only label
(mainly near the window edges). ``peak_native_mgdl`` is kept alongside ``peak_mgdl`` so that
sensitivity analysis SA-1 (P2, docs/sensitivity-analyses.md) can measure the difference. Do not
change the label basis here; a change is labels.v2 with its own ADR.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from twin_core.config import LabelConfig

WATERFALL = (
    "overlap_next_meal",
    "low_cgm_coverage",
    "no_pre_meal_native",
    "already_high",
    "macro_excluded",
)


def meal_outcomes(meals: pd.DataFrame, cgm: pd.DataFrame, cfg: LabelConfig) -> pd.DataFrame:
    """Outcomes for one participant.

    meals: columns meal_id, started_at, macro_validity (any order; sorted here).
    cgm:   columns ts, dexcom_mgdl (cleaned, NaN when missing), dexcom_is_native (bool); unique ts.
    """
    m = meals.sort_values(["started_at", "meal_id"], kind="stable").reset_index(drop=True)
    c = cgm.sort_values("ts", kind="stable")
    have = c["dexcom_mgdl"].notna().to_numpy()
    ts_all = c["ts"].to_numpy(dtype="datetime64[ns]")
    ts = ts_all[have]
    val = c["dexcom_mgdl"].to_numpy(dtype=float)[have]
    native = c["dexcom_is_native"].to_numpy(dtype=bool)[have]
    ts_nat, val_nat = ts[native], val[native]

    horizon = np.timedelta64(cfg.horizon_min, "m")
    lookback = np.timedelta64(cfg.pre_meal_lookback_min, "m")
    starts = m["started_at"].to_numpy(dtype="datetime64[ns]")
    next_gap = np.full(len(m), np.nan)
    if len(m) > 1:
        next_gap[:-1] = (starts[1:] - starts[:-1]) / np.timedelta64(1, "m")

    rows = []
    for t0 in starts:
        lo = np.searchsorted(ts, t0, side="right")  # first reading strictly after t0
        hi = np.searchsorted(ts, t0 + horizon, side="right")  # readings <= t0 + horizon
        window = val[lo:hi]
        coverage = min(1.0, len(window) / cfg.horizon_min)
        peak = float(window.max()) if len(window) else np.nan

        nlo = np.searchsorted(ts_nat, t0, side="right")
        nhi = np.searchsorted(ts_nat, t0 + horizon, side="right")
        peak_native = float(val_nat[nlo:nhi].max()) if nhi > nlo else np.nan

        j = np.searchsorted(ts_nat, t0, side="right") - 1  # last native at or before t0
        if j >= 0 and ts_nat[j] >= t0 - lookback:
            pre = float(val_nat[j])
            pre_age = float((t0 - ts_nat[j]) / np.timedelta64(1, "m"))
        else:
            pre, pre_age = np.nan, np.nan
        rows.append((coverage, peak, peak_native, pre, pre_age))

    out = pd.DataFrame(
        rows,
        columns=[
            "window_coverage",
            "peak_mgdl",
            "peak_native_mgdl",
            "pre_meal_native_mgdl",
            "pre_meal_native_age_min",
        ],
    )
    out.insert(0, "meal_id", m["meal_id"].to_numpy())
    out["next_meal_gap_min"] = next_gap
    out["overlap_next_meal"] = ~np.isnan(next_gap) & (next_gap < cfg.horizon_min)
    out["low_cgm_coverage"] = out["window_coverage"] < cfg.min_window_coverage
    out["no_pre_meal_native"] = out["pre_meal_native_mgdl"].isna()
    out["already_high"] = out["pre_meal_native_mgdl"] > cfg.already_high_threshold_mgdl
    out["macro_excluded"] = m["macro_validity"].isin(cfg.exclude_macro_validity).to_numpy()
    out["frozen_usable"] = ~out["overlap_next_meal"] & ~out["low_cgm_coverage"]
    out["eligible"] = out["frozen_usable"] & ~out[list(WATERFALL[2:])].any(axis=1)

    exceeded = out["peak_mgdl"] > cfg.threshold_mgdl
    out["label"] = pd.array(
        np.where(out["frozen_usable"], exceeded.astype(int), pd.NA), dtype="Int64"
    )
    out["exclusion_reasons"] = [
        ";".join(r for r in WATERFALL if bool(out.at[i, r])) for i in range(len(out))
    ]
    out["waterfall_reason"] = [
        next((r for r in WATERFALL if bool(out.at[i, r])), "eligible") for i in range(len(out))
    ]
    return out
