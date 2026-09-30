"""SYNTHETIC TEST FIXTURE for M3 — NOT real data, and no result computed from it is a finding.

An M2-shaped meal table (same columns as twin_ml.dataset.build) for 20 invented participants, with a
simple planted signal so the training code has something to learn. It exists only to exercise the
M3 machinery and its leakage guards. Real metrics come only from `make m3` on the processed CGMacros
dataset.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from twin_core.config import load_feature_config
from twin_ml.dataset.build import ID_COLUMNS, OUTCOME_KEEP
from twin_ml.dataset.folds import assign_folds

FIXTURE_LABEL = "SYNTHETIC TEST FIXTURE (not real data; metrics are meaningless)"
REPO = Path(__file__).resolve().parents[2]
FCFG = load_feature_config(REPO / "data/configs/features.v1.yaml")[0]
GROUPS = {"healthy": (5.2, 6), "prediabetes": (6.0, 7), "T2D": (7.4, 7)}


def make_m2_like(seed: int = 7, meals_per_day: int = 3, days: int = 12) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows: list[dict[str, object]] = []
    pid = 100
    for group, (hba1c_mu, n_people) in GROUPS.items():
        for _ in range(n_people):
            pid += 1
            hba1c = hba1c_mu + rng.normal(0, 0.3)
            offset = rng.normal(0, 15)  # the person's own tendency: what personalization can learn
            base_g = 90 + 12 * (hba1c - 5.2) + rng.normal(0, 5)
            mets = bool(rng.random() > 0.3)
            clinical = {
                "hba1c_pct": hba1c,
                "fasting_glucose_mgdl": base_g + rng.normal(0, 5),
                "fasting_insulin_uu_ml": rng.uniform(4, 25),
                "bmi": rng.uniform(20, 38),
                "age_years": rng.uniform(25, 70),
                "sex_female": float(rng.integers(0, 2)),
                "triglycerides_mgdl": rng.uniform(60, 250),
                "hdl_mgdl": rng.uniform(35, 75),
            }
            clinical["homa_ir"] = (
                clinical["fasting_glucose_mgdl"] * clinical["fasting_insulin_uu_ml"] / 405
            )
            start = pd.Timestamp("2021-06-01")
            for d in range(days):
                for h, mt in zip(
                    (8, 13, 19)[:meals_per_day], ("breakfast", "lunch", "dinner"), strict=False
                ):
                    t0 = start + pd.Timedelta(days=d, hours=h, minutes=int(rng.integers(-20, 20)))
                    carbs = float(rng.uniform(10, 110))
                    g_last = float(base_g + rng.normal(0, 18))
                    rise = 0.9 * carbs + 20 * (hba1c - 5.5) + offset + rng.normal(0, 12)
                    rows.append(
                        {
                            "participant_id": pid,
                            "started_at": t0,
                            "glycemic_group": group,
                            "meal_type": mt,
                            "macro_validity": "valid",
                            "hba1c": hba1c,
                            "g_last": g_last,
                            "carbs_g": carbs,
                            "rise": rise,
                            "mets": mets,
                            **clinical,
                        }
                    )
                if rng.random() < 0.15:  # a snack 40 min after lunch makes lunch overlap
                    t0 = start + pd.Timedelta(days=d, hours=13, minutes=40)
                    rows.append(
                        {
                            "participant_id": pid,
                            "started_at": t0,
                            "glycemic_group": group,
                            "meal_type": "snack",
                            "macro_validity": "valid",
                            "hba1c": hba1c,
                            "g_last": float(base_g + 30),
                            "carbs_g": 15.0,
                            "rise": 20.0,
                            "mets": mets,
                            **clinical,
                        }
                    )
    raw = pd.DataFrame(rows).sort_values(["participant_id", "started_at"]).reset_index(drop=True)
    n = len(raw)
    out = pd.DataFrame(
        {
            "meal_id": [f"m{i:05d}" for i in range(n)],
            "participant_id": raw["participant_id"],
            "started_at": raw["started_at"],
            "glycemic_group": raw["glycemic_group"],
            "meal_type": raw["meal_type"],
            "macro_validity": raw["macro_validity"],
        }
    )
    hour = raw["started_at"].dt.hour + raw["started_at"].dt.minute / 60
    g = raw["g_last"]
    feats: dict[str, object] = {
        "g_last": g,
        "g_age_min": rng.uniform(0, 5, n),
        "slope_15": rng.normal(0, 0.5, n),
        "slope_30": rng.normal(0, 0.4, n),
        "sd_60": rng.uniform(2, 15, n),
        "mean_180": g + rng.normal(0, 8, n),
        "min_180": g - rng.uniform(5, 25, n),
        "max_180": g + rng.uniform(5, 40, n),
        "tir_24h": np.where(rng.random(n) < 0.1, np.nan, rng.uniform(0.5, 1, n)),
        "g_overnight_baseline": g - rng.uniform(0, 20, n),
        "carbs_g": raw["carbs_g"],
        "protein_g": rng.uniform(5, 50, n),
        "fat_g": rng.uniform(5, 50, n),
        "fiber_g": rng.uniform(0, 12, n),
        "calories_kcal": raw["carbs_g"] * 4 + rng.uniform(100, 400, n),
        **{
            f"meal_{m}": (raw["meal_type"] == m).astype(float)
            for m in ("breakfast", "lunch", "dinner", "snack")
        },
        "hour_sin": np.sin(2 * np.pi * hour / 24),
        "hour_cos": np.cos(2 * np.pi * hour / 24),
        "carbs_prev_3h": np.where(raw["meal_type"] == "snack", 50.0, 0.0),
        "invalid_meal_prev_3h": 0.0,
        "mins_since_meal": rng.uniform(40, 720, n),
        "hr_30": np.where(rng.random(n) < 0.2, np.nan, rng.uniform(60, 100, n)),
        "hr_resting": rng.uniform(55, 75, n),
        "mets_available": raw["mets"].astype(float),
        "mets_60": np.where(raw["mets"], rng.uniform(1, 3, n), np.nan),
        "active_min_3h": np.where(raw["mets"], rng.integers(0, 60, n).astype(float), np.nan),
        "activity_kcal_60": rng.uniform(1, 4, n),
        "hr_age_min": rng.uniform(0, 3, n),
        **{
            k: raw[k]
            for k in (
                "hba1c_pct",
                "fasting_glucose_mgdl",
                "fasting_insulin_uu_ml",
                "homa_ir",
                "bmi",
                "age_years",
                "sex_female",
                "triglycerides_mgdl",
                "hdl_mgdl",
            )
        },
    }
    feats["g_vs_baseline"] = g - feats["g_overnight_baseline"]  # type: ignore[operator]
    feats["hr_delta"] = feats["hr_30"] - feats["hr_resting"]  # type: ignore[operator]
    for k, v in feats.items():
        out[k] = np.asarray(v, dtype=float)

    # outcomes
    nxt = out.groupby("participant_id")["started_at"].shift(-1)
    gap = (nxt - out["started_at"]).dt.total_seconds() / 60
    overlap = gap < 120
    peak = g + raw["rise"]
    already_high = g > 180
    frozen = ~overlap
    out["label"] = pd.array(np.where(frozen, (peak > 180).astype(float), np.nan), dtype="Float64")
    out["frozen_usable"] = frozen
    out["eligible"] = frozen & ~already_high
    out["exclusion_reasons"] = np.where(
        overlap, "overlap", np.where(already_high, "already_high", "")
    )
    out["waterfall_reason"] = np.where(overlap, "overlap", "usable")
    out["peak_mgdl"] = peak
    out["peak_native_mgdl"] = peak - rng.uniform(0, 3, n)
    out["pre_meal_native_mgdl"] = g
    out["next_meal_gap_min"] = gap
    out["window_coverage"] = 1.0
    out["already_high"] = already_high
    out["rise_native_mgdl"] = out["peak_native_mgdl"] - out["pre_meal_native_mgdl"]
    out["max_source_ts"] = out["started_at"]

    # raw past-only counts (audit columns in M2)
    nc, npos = [], []
    for _, p in out.groupby("participant_id", sort=False):
        s = p["started_at"].to_numpy()
        ends = s + np.timedelta64(120, "m")
        ok = p["frozen_usable"].to_numpy()
        lab = p["label"].to_numpy(dtype=float, na_value=np.nan)
        for t0 in s:
            closed = (ends <= t0) & ok
            nc.append(float(closed.sum()))
            npos.append(float(np.nansum(lab[closed])))
    out["n_closed_meals"] = nc
    out["n_closed_positive"] = npos

    people = out[["participant_id", "glycemic_group"]].drop_duplicates()
    folds = assign_folds(people, FCFG.folds.n_folds, FCFG.folds.seed)
    out = out.merge(folds[["participant_id", "fold"]], on="participant_id")
    ordered = [
        *ID_COLUMNS,
        "fold",
        *FCFG.features.all(),
        *OUTCOME_KEEP,
        "rise_native_mgdl",
        "max_source_ts",
    ]
    ordered.remove("fold")
    ordered.insert(ordered.index("macro_validity") + 1, "fold")
    return out[ordered].reset_index(drop=True)


def pin_folds(dataset: pd.DataFrame, root: Path) -> None:
    path = root / "data/manifests/folds.v1.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    dataset[["participant_id", "glycemic_group", "fold"]].drop_duplicates().sort_values(
        "participant_id"
    ).to_csv(path, index=False)
