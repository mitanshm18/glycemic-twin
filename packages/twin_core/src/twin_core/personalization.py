"""Personal response estimates with shrinkage toward the population (empirical Bayes).

Two estimates per person, both built only from that person's CLOSED past meals (start + 120 <= t0,
frozen-usable, label known):

1. Personal positive rate, beta-binomial:  p = (s + alpha) / (n + alpha + beta).
   alpha and beta come from the population (method of moments on per-person rates), so with no
   meals p equals the population rate; with many meals it approaches the person's own rate.
2. Personal rise offset: a population linear model predicts each meal's glucose rise
   (native peak - native pre-meal) from carbs, fiber and pre-meal glucose. The person's mean
   residual is shrunk:  offset = w * mean_residual,  w = n / (n + k),  k = sigma2_within / tau2_between.

The population parameters MUST be fitted on training participants only. That is why the M2 dataset
stores only raw counts, and M3 calls ``fit_population_prior`` inside each training fold.
These are associations learned from data, not causal effects.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

REQUIRED = (
    "participant_id",
    "started_at",
    "frozen_usable",
    "label",
    "rise_native_mgdl",
    "carbs_g",
    "fiber_g",
    "pre_meal_native_mgdl",
)


@dataclass(frozen=True)
class PopulationPrior:
    alpha: float
    beta: float
    rise_coef: tuple[float, float, float, float]  # intercept, carbs, fiber, pre-meal glucose
    k: float
    n_people: int
    n_meals: int

    @property
    def population_rate(self) -> float:
        return self.alpha / (self.alpha + self.beta)


def _design(df: pd.DataFrame) -> np.ndarray:
    return np.column_stack(
        [
            np.ones(len(df)),
            df["carbs_g"].to_numpy(float),
            df["fiber_g"].to_numpy(float),
            df["pre_meal_native_mgdl"].to_numpy(float),
        ]
    )


def _usable(df: pd.DataFrame) -> pd.DataFrame:
    return df[df["frozen_usable"].astype(bool) & df["label"].notna()]


def _rise_rows(df: pd.DataFrame) -> pd.DataFrame:
    cols = ["rise_native_mgdl", "carbs_g", "fiber_g", "pre_meal_native_mgdl"]
    return df[df[cols].notna().all(axis=1)]


def fit_population_prior(train: pd.DataFrame, min_meals_per_person: int = 3) -> PopulationPrior:
    """Fit on TRAINING participants only. ``train`` needs the REQUIRED columns."""
    missing = [c for c in REQUIRED if c not in train.columns]
    if missing:
        raise ValueError(f"missing columns: {missing}")
    u = _usable(train)
    per = u.groupby("participant_id")["label"].agg(["sum", "count"])
    per = per[per["count"] >= min_meals_per_person]
    if len(per) < 2:
        raise ValueError("need at least two training participants with enough meals")
    rates = per["sum"] / per["count"]
    mu = float(np.clip(rates.mean(), 1e-3, 1 - 1e-3))
    var = float(rates.var(ddof=1))
    phi = mu * (1 - mu) / var - 1 if var > 0 else 1000.0
    phi = float(np.clip(phi, 1.0, 1000.0))

    r = _rise_rows(u)
    coef, *_ = np.linalg.lstsq(_design(r), r["rise_native_mgdl"].to_numpy(float), rcond=None)
    resid = r["rise_native_mgdl"].to_numpy(float) - _design(r) @ coef
    res = pd.DataFrame({"pid": r["participant_id"].to_numpy(), "e": resid})
    g = res.groupby("pid")["e"].agg(["mean", "var", "count"])
    g = g[g["count"] >= min_meals_per_person]
    sigma2_within = float(np.average(g["var"], weights=g["count"] - 1))
    tau2 = float(g["mean"].var(ddof=1) - (sigma2_within / g["count"]).mean())
    tau2 = max(tau2, 1e-6)
    k = float(np.clip(sigma2_within / tau2, 1.0, 200.0))
    return PopulationPrior(
        alpha=mu * phi,
        beta=(1 - mu) * phi,
        rise_coef=(float(coef[0]), float(coef[1]), float(coef[2]), float(coef[3])),
        k=k,
        n_people=int(len(per)),
        n_meals=int(len(u)),
    )


def personal_features(
    person: pd.DataFrame, prior: PopulationPrior, horizon_min: int
) -> pd.DataFrame:
    """Past-only personal features for every meal of ONE person.

    For the meal at t0, only meals with start + horizon <= t0 contribute. Returns a frame aligned to
    ``person.index`` with p_personal, rise_offset_mgdl, personal_weight, n_closed_meals.
    """
    if person["participant_id"].nunique() > 1:
        raise ValueError("personal_features expects one participant")
    p = person.sort_values("started_at", kind="stable")
    starts = p["started_at"].to_numpy(dtype="datetime64[ns]")
    ends = starts + np.timedelta64(horizon_min, "m")
    usable = (p["frozen_usable"].astype(bool) & p["label"].notna()).to_numpy()
    labels = p["label"].astype("Float64").to_numpy(dtype=float, na_value=np.nan)
    rise_ok = (
        usable
        & p[["rise_native_mgdl", "carbs_g", "fiber_g", "pre_meal_native_mgdl"]]
        .notna()
        .all(axis=1)
        .to_numpy()
    )
    resid = np.full(len(p), np.nan)
    if rise_ok.any():
        resid[rise_ok] = p.loc[rise_ok, "rise_native_mgdl"].to_numpy(float) - _design(
            p.loc[rise_ok]
        ) @ np.array(prior.rise_coef)

    out = np.zeros((len(p), 4))
    for i, t0 in enumerate(starts):
        closed = ends <= t0
        c_lab = closed & usable
        n, s = int(c_lab.sum()), float(labels[c_lab].sum()) if c_lab.any() else 0.0
        c_res = closed & rise_ok
        n_r = int(c_res.sum())
        w = n_r / (n_r + prior.k)
        offset = w * float(resid[c_res].mean()) if n_r else 0.0
        out[i] = ((s + prior.alpha) / (n + prior.alpha + prior.beta), offset, w, n)
    frame = pd.DataFrame(
        out,
        index=p.index,
        columns=["p_personal", "rise_offset_mgdl", "personal_weight", "n_closed_meals"],
    )
    return frame.loc[person.index]
