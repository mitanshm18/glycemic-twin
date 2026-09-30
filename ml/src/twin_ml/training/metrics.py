"""Evaluation metrics on out-of-fold predictions, with participant-level bootstrap intervals.

The bootstrap resamples PARTICIPANTS (with replacement), not meals: meals of one person are
correlated, so resampling meals would give intervals that are too narrow.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np
import pandas as pd
from scipy.optimize import brentq
from scipy.stats import rankdata
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score

EPS = 1e-6
Metric = Callable[[np.ndarray, np.ndarray], float]


def auroc(y: np.ndarray, p: np.ndarray) -> float:
    y = np.asarray(y, int)
    n1 = int(y.sum())
    n0 = len(y) - n1
    if n1 == 0 or n0 == 0:
        return float("nan")
    r = rankdata(p)
    return float((r[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def pr_auc(y: np.ndarray, p: np.ndarray) -> float:
    y = np.asarray(y, int)
    if y.sum() == 0 or y.sum() == len(y):
        return float("nan")
    return float(average_precision_score(y, p))


def brier(y: np.ndarray, p: np.ndarray) -> float:
    return (
        float(np.mean((np.asarray(p, float) - np.asarray(y, float)) ** 2))
        if len(y)
        else float("nan")
    )


METRICS: dict[str, Metric] = {"auroc": auroc, "pr_auc": pr_auc, "brier": brier}


def _logit(p: np.ndarray) -> np.ndarray:
    p = np.clip(np.asarray(p, float), EPS, 1 - EPS)
    return np.asarray(np.log(p / (1 - p)))


def calibration_stats(y: np.ndarray, p: np.ndarray) -> dict[str, float | None]:
    """Calibration-in-the-large (ideal 0) and calibration slope (ideal 1) on the logit scale."""
    y = np.asarray(y, int)
    if len(np.unique(y)) < 2:
        return {"calibration_intercept": None, "calibration_slope": None}
    lp = _logit(p)

    def gap(a: float) -> float:
        return float(np.mean(1 / (1 + np.exp(-(a + lp)))) - y.mean())

    intercept = brentq(gap, -20, 20)
    lr = LogisticRegression(C=1e6, max_iter=1000).fit(lp.reshape(-1, 1), y)
    return {"calibration_intercept": float(intercept), "calibration_slope": float(lr.coef_[0, 0])}


def calibration_curve(y: np.ndarray, p: np.ndarray, bins: int) -> list[dict[str, float]]:
    """Quantile bins of predicted probability: mean prediction vs observed rate."""
    if len(y) == 0:
        return []
    order = np.argsort(p, kind="stable")
    out = []
    for i, idx in enumerate(np.array_split(order, min(bins, len(y)))):
        if len(idx):
            out.append(
                {
                    "bin": i,
                    "n": int(len(idx)),
                    "mean_predicted": float(np.mean(p[idx])),
                    "observed_rate": float(np.mean(y[idx])),
                }
            )
    return out


def ece(curve: list[dict[str, float]]) -> float | None:
    n = sum(b["n"] for b in curve)
    if not n:
        return None
    return float(sum(b["n"] * abs(b["mean_predicted"] - b["observed_rate"]) for b in curve) / n)


def threshold_metrics(y: np.ndarray, pred: np.ndarray) -> dict[str, float | None]:
    y, pred = np.asarray(y, int), np.asarray(pred, int)
    tp = int(((pred == 1) & (y == 1)).sum())
    fp = int(((pred == 1) & (y == 0)).sum())
    fn = int(((pred == 0) & (y == 1)).sum())
    tn = int(((pred == 0) & (y == 0)).sum())

    def div(a: int, b: int) -> float | None:
        return a / b if b else None

    sens, ppv = div(tp, tp + fn), div(tp, tp + fp)
    f1 = 2 * sens * ppv / (sens + ppv) if sens and ppv else None
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "sensitivity": sens,
        "specificity": div(tn, tn + fp),
        "ppv": ppv,
        "npv": div(tn, tn + fn),
        "f1": f1,
        "flagged_share": div(tp + fp, len(y)),
    }


def point_metrics(y: np.ndarray, p: np.ndarray) -> dict[str, Any]:
    y = np.asarray(y, int)
    prev = float(y.mean()) if len(y) else float("nan")
    ref = prev * (1 - prev)
    b = brier(y, p)
    out: dict[str, Any] = {
        "meals": int(len(y)),
        "positives": int(y.sum()),
        "prevalence": prev,
        **{k: f(y, p) for k, f in METRICS.items()},
        "brier_reference": ref,
        "brier_skill": 1 - b / ref if ref > 0 else None,
    }
    out.update(calibration_stats(y, p))
    return out


def _participant_index(df: pd.DataFrame) -> tuple[np.ndarray, list[np.ndarray]]:
    pids = np.sort(df["participant_id"].unique())
    pos = {p: i for i, p in enumerate(pids)}
    codes = df["participant_id"].map(pos).to_numpy()
    return pids, [np.flatnonzero(codes == i) for i in range(len(pids))]


def bootstrap_ci(
    df: pd.DataFrame, prob_col: str, n: int, ci: float, seed: int
) -> dict[str, dict[str, float | int | None]]:
    """Participant bootstrap percentile intervals for AUROC, PR-AUC and Brier."""
    y = df["label"].to_numpy(int)
    p = df[prob_col].to_numpy(float)
    _, groups = _participant_index(df)
    rng = np.random.default_rng(seed)
    draws: dict[str, list[float]] = {k: [] for k in METRICS}
    for _ in range(n):
        idx = np.concatenate([groups[i] for i in rng.integers(0, len(groups), len(groups))])
        for k, f in METRICS.items():
            v = f(y[idx], p[idx])
            if np.isfinite(v):
                draws[k].append(v)
    lo, hi = (1 - ci) / 2 * 100, (1 + ci) / 2 * 100
    return {
        k: {
            "lo": float(np.percentile(v, lo)) if v else None,
            "hi": float(np.percentile(v, hi)) if v else None,
            "valid_resamples": len(v),
        }
        for k, v in draws.items()
    }


def paired_bootstrap(
    a: pd.DataFrame, b: pd.DataFrame, metric: str, n: int, ci: float, seed: int
) -> dict[str, Any]:
    """metric(a) - metric(b) on the SAME meals and the same participant resamples."""
    m = a[["meal_id", "participant_id", "label", "prob"]].merge(
        b[["meal_id", "prob"]], on="meal_id", suffixes=("_a", "_b"), validate="one_to_one"
    )
    if len(m) != len(a) or len(m) != len(b):
        raise ValueError("paired comparison needs predictions for the same meals")
    f = METRICS[metric]
    y = m["label"].to_numpy(int)
    pa, pb = m["prob_a"].to_numpy(float), m["prob_b"].to_numpy(float)
    _, groups = _participant_index(m)
    rng = np.random.default_rng(seed)
    diffs = []
    for _ in range(n):
        idx = np.concatenate([groups[i] for i in rng.integers(0, len(groups), len(groups))])
        d = f(y[idx], pa[idx]) - f(y[idx], pb[idx])
        if np.isfinite(d):
            diffs.append(d)
    lo, hi = (1 - ci) / 2 * 100, (1 + ci) / 2 * 100
    return {
        "metric": metric,
        "difference": f(y, pa) - f(y, pb),
        "lo": float(np.percentile(diffs, lo)) if diffs else None,
        "hi": float(np.percentile(diffs, hi)) if diffs else None,
        "share_resamples_a_not_better": float(np.mean(np.array(diffs) <= 0)) if diffs else None,
        "valid_resamples": len(diffs),
        "meals": int(len(m)),
        "participants": int(m["participant_id"].nunique()),
    }


def evaluate_population(
    oof: pd.DataFrame, bins: int, n_boot: int, ci: float, seed: int
) -> dict[str, Any]:
    """Pooled OOF metrics with bootstrap CIs, calibration, threshold metrics and per-fold metrics."""
    if oof.empty:
        return {"meals": 0}
    y, p = oof["label"].to_numpy(int), oof["prob"].to_numpy(float)
    curve = calibration_curve(y, p, bins)
    pooled = point_metrics(y, p)
    pooled["ece"] = ece(curve)
    pooled["participants"] = int(oof["participant_id"].nunique())
    unc = oof["prob_uncalibrated"].to_numpy(float)
    per_fold = []
    for k, g in oof.groupby("fold", sort=True):
        pm = point_metrics(g["label"].to_numpy(int), g["prob"].to_numpy(float))
        pm["fold"] = int(k)
        pm["participants"] = int(g["participant_id"].nunique())
        pm["threshold"] = float(g["threshold"].iloc[0])
        per_fold.append(pm)
    return {
        "pooled": pooled,
        "bootstrap_ci": bootstrap_ci(oof, "prob", n_boot, ci, seed),
        "uncalibrated": (
            {"brier": brier(y, unc), **calibration_stats(y, unc)}
            if np.isfinite(unc).all()
            else None
        ),
        "at_threshold": threshold_metrics(y, oof["pred"].to_numpy(int)),
        "calibration_curve": curve,
        "per_fold": per_fold,
    }
