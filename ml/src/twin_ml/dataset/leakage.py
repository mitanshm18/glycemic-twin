"""Runtime leakage checks on the M2 dataset. A failed hard check raises LeakageError: no dataset is
written, and training cannot start. The single-feature AUROC check is a review flag, because a very
predictive feature is suspicious but not proof of leakage.

Checks here (M2 scope):
  L1 feature list equals the configured list; no deny-listed names; no outcome column is a feature
  L2 every meal's latest source timestamp <= meal start
  L3 recomputing features from a history cut at t0 gives identical values (sampled meals)
  L4 folds are participant-disjoint and every meal has a fold
  L5 usable meals have no other meal inside their 120-minute window
  L6 single-feature AUROC on eligible target-group meals (review flag)
Model-time checks (model inputs per fit, fitting boundaries) live in check_model_inputs and
twin_ml.training.cv.verify_boundaries (M3).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
import pandas as pd
from twin_core.config import FeatureConfig, LabelConfig, ModelFeatureContract
from twin_core.features import ParticipantHistory, as_ns, meal_features, meal_input

OUTCOME_COLUMNS = (
    "label",
    "frozen_usable",
    "eligible",
    "exclusion_reasons",
    "waterfall_reason",
    "peak_mgdl",
    "peak_native_mgdl",
    "pre_meal_native_mgdl",
    "rise_native_mgdl",
    "next_meal_gap_min",
    "window_coverage",
    "already_high",
    "amount_consumed_pct",
)


class LeakageError(RuntimeError):
    """A hard leakage check failed."""


def auroc(x: np.ndarray, y: np.ndarray) -> float:
    """Rank-based AUROC (Mann-Whitney U), ignoring rows where x is NaN."""
    ok = ~np.isnan(x)
    x, y = x[ok], y[ok].astype(int)
    n1 = int(y.sum())
    n0 = len(y) - n1
    if n1 == 0 or n0 == 0:
        return float("nan")
    ranks = pd.Series(x).rank(method="average").to_numpy()
    return float((ranks[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def check_feature_names(feature_cols: Sequence[str], fcfg: FeatureConfig) -> dict[str, Any]:
    expected = list(fcfg.features.all())
    problems = []
    if list(feature_cols) != expected:
        problems.append(
            f"feature list differs from features.v{fcfg.version}.yaml: "
            f"extra {sorted(set(feature_cols) - set(expected))}, "
            f"missing {sorted(set(expected) - set(feature_cols))}"
        )
    denied = [c for c in feature_cols for p in fcfg.leakage.deny_patterns if p in c.lower()]
    if denied:
        problems.append(f"deny-listed feature names: {sorted(set(denied))}")
    outcome = sorted(set(feature_cols) & set(OUTCOME_COLUMNS))
    if outcome:
        problems.append(f"outcome columns used as features: {outcome}")
    return {"check": "L1 feature names", "passed": not problems, "detail": problems or "ok"}


def check_model_inputs(
    columns: Sequence[str], contract: ModelFeatureContract, fcfg: FeatureConfig
) -> dict[str, Any]:
    """M3 check: a model input list is one contract feature set (or, for a baseline, an ordered
    subset of the primary set), and contains no outcome, audit-only or deny-listed column."""
    cols = list(columns)
    problems = []
    sets = {name: list(contract.columns(fcfg, name)) for name in contract.feature_sets}
    primary = sets[contract.primary_feature_set]
    ordered_subset = set(cols) <= set(primary) and cols == [c for c in primary if c in cols]
    if cols not in sets.values() and not ordered_subset:
        problems.append(f"columns are not a contract feature set or ordered subset: {cols}")
    outcome = sorted(set(cols) & set(OUTCOME_COLUMNS))
    if outcome:
        problems.append(f"outcome columns in model input: {outcome}")
    audit_only = sorted(set(cols) & set(contract.not_model_inputs))
    if audit_only:
        problems.append(f"audit-only columns in model input: {audit_only}")
    denied = sorted({c for c in cols for p in fcfg.leakage.deny_patterns if p in c.lower()})
    if denied:
        problems.append(f"deny-listed names in model input: {denied}")
    if len(set(cols)) != len(cols):
        problems.append("duplicate columns")
    return {"check": "M3 model inputs", "passed": not problems, "detail": problems or "ok"}


def check_source_times(dataset: pd.DataFrame) -> dict[str, Any]:
    late = dataset["max_source_ts"].notna() & (dataset["max_source_ts"] > dataset["started_at"])
    return {
        "check": "L2 latest source <= meal start",
        "passed": not late.any(),
        "detail": f"{int(late.sum())} meals read data after their start",
    }


def check_truncation(
    dataset: pd.DataFrame,
    histories: Mapping[int, ParticipantHistory],
    meals: pd.DataFrame,
    fcfg: FeatureConfig,
    n: int,
    seed: int,
) -> dict[str, Any]:
    feature_cols = list(fcfg.features.all())
    sample = dataset.sample(n=min(n, len(dataset)), random_state=seed)
    by_id = meals.set_index("meal_id")
    mismatches = []
    for _, row in sample.iterrows():
        h = histories[int(row["participant_id"])]
        t0 = as_ns(pd.Timestamp(row["started_at"]).to_datetime64())
        meal = meal_input(by_id.loc[row["meal_id"]].to_dict() | {"started_at": row["started_at"]})
        cut, _ = meal_features(h.truncate(t0), meal, fcfg)
        for col in feature_cols:
            a, b = row[col], cut[col]
            if not ((pd.isna(a) and pd.isna(b)) or np.isclose(a, b, rtol=0, atol=1e-9)):
                mismatches.append((row["meal_id"], col, a, b))
    return {
        "check": "L3 features from history cut at t0 are identical",
        "passed": not mismatches,
        "detail": f"{len(sample)} meals re-checked; mismatches {mismatches[:5]}",
    }


def check_folds(dataset: pd.DataFrame) -> dict[str, Any]:
    per_person = dataset.groupby("participant_id")["fold"].nunique()
    problems = []
    if dataset["fold"].isna().any():
        problems.append("meals without a fold")
    if (per_person > 1).any():
        problems.append(
            f"participants in several folds: {per_person[per_person > 1].index.tolist()}"
        )
    return {
        "check": "L4 folds are participant-disjoint",
        "passed": not problems,
        "detail": problems or "ok",
    }


def check_overlap(dataset: pd.DataFrame, lcfg: LabelConfig) -> dict[str, Any]:
    u = dataset[dataset["frozen_usable"]]
    bad = u["next_meal_gap_min"].notna() & (u["next_meal_gap_min"] < lcfg.horizon_min)
    return {
        "check": "L5 no meal inside a usable meal's window",
        "passed": not bad.any(),
        "detail": f"{int(bad.sum())} violations",
    }


def single_feature_aurocs(
    dataset: pd.DataFrame, fcfg: FeatureConfig, lcfg: LabelConfig
) -> tuple[dict[str, Any], dict[str, float | None]]:
    t = dataset[dataset["eligible"] & dataset["glycemic_group"].isin(lcfg.target_groups)]
    y = t["label"].astype(int).to_numpy()
    scores = {c: auroc(t[c].to_numpy(dtype=float), y) for c in fcfg.features.all()}
    lim = fcfg.leakage.single_feature_auroc_max
    flagged = {
        c: round(v, 4) for c, v in scores.items() if not np.isnan(v) and (v > lim or v < 1 - lim)
    }
    return (
        {
            "check": f"L6 single-feature AUROC within [{1 - lim:.2f}, {lim:.2f}] (review)",
            "passed": not flagged,
            "detail": flagged or "ok",
        },
        {c: (None if np.isnan(v) else round(v, 4)) for c, v in scores.items()},
    )


def raise_on_failures(results: Sequence[Mapping[str, Any]]) -> None:
    failed = [r for r in results if not r["passed"] and not str(r["check"]).startswith("L6")]
    if failed:
        raise LeakageError("; ".join(f"{r['check']}: {r['detail']}" for r in failed))
