"""Nested participant-level cross-validation (ADR-016).

For outer fold k (the pinned participant folds):

  outer-train participants  = everyone not in fold k        outer-test = fold k (never touched)
  1. inner folds: outer-train participants split into ``inner_folds`` participant groups
  2. for every hyper-parameter candidate and inner fold j:
       prior + preprocessing + model fitted on inner-train participants, scored on inner fold j
     -> inner out-of-fold (OOF) scores for every outer-train meal
  3. choose the candidate with the best inner-OOF PR-AUC on target-group meals
  4. fit the Platt calibrator on those inner-OOF scores (target-group meals, outer-train only)
  5. choose the F1-max threshold on the calibrated inner-OOF probabilities (same rows)
  6. refit prior + preprocessing + model on all outer-train participants
  7. score fold k once -> outer OOF predictions

Every fit appends a record to an audit log (who fitted the prior, the preprocessing/model, the
calibrator and the threshold, and who was scored). ``verify_boundaries`` fails if any record lets an
outer-test participant into any fit, or scores a participant a fit has seen.

The final (serving) model repeats steps 2-6 on all participants, using the pinned folds as the inner
folds. Its performance is the nested estimate above; it is never evaluated on its own training data.
"""

from __future__ import annotations

import itertools
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score
from sklearn.pipeline import Pipeline
from twin_core.config import FeatureConfig, ModelFeatureContract
from twin_core.personalization import PopulationPrior

from twin_ml.dataset.folds import assign_folds
from twin_ml.dataset.leakage import LeakageError
from twin_ml.training.config import TrainingConfig, baseline_columns
from twin_ml.training.design import DesignBuilder
from twin_ml.training.models import (
    PlattCalibrator,
    build_pipeline,
    f1_max_threshold,
    raw_scores,
    uncalibrated_probability,
)


@dataclass(frozen=True)
class Candidate:
    params: tuple[tuple[str, Any], ...]

    def as_dict(self) -> dict[str, Any]:
        return dict(self.params)


@dataclass(frozen=True)
class Spec:
    """One trainable thing: a model family or baseline on one set of contract columns."""

    name: str
    kind: str
    feature_set: str
    columns: tuple[str, ...]
    candidates: tuple[Candidate, ...]
    monotone: dict[str, int] = field(default_factory=dict)

    @property
    def uses_personal(self) -> bool:
        return any(c in ("p_personal", "rise_offset_mgdl", "personal_weight") for c in self.columns)


def model_spec(
    name: str,
    feature_set: str,
    tcfg: TrainingConfig,
    contract: ModelFeatureContract,
    fcfg: FeatureConfig,
) -> Spec:
    m = tcfg.models[name]
    keys = sorted(m.grid)
    cands = tuple(
        Candidate(tuple(sorted({**m.fixed, **dict(zip(keys, values, strict=True))}.items())))
        for values in itertools.product(*(m.grid[k] for k in keys))
    )
    return Spec(
        name, name, feature_set, contract.columns(fcfg, feature_set), cands, dict(m.monotone)
    )


def baseline_spec(
    name: str, tcfg: TrainingConfig, contract: ModelFeatureContract, fcfg: FeatureConfig
) -> Spec:
    b = tcfg.baselines[name]
    cols = baseline_columns(b, contract, fcfg)
    if b.kind == "rule":
        cands = tuple(Candidate((("a", float(a)),)) for a in b.a_grid)
    elif b.kind == "logistic":
        cands = (Candidate((("C", 1.0), ("max_iter", 5000))),)
    else:
        cands = (Candidate(()),)
    return Spec(name, b.kind, f"{contract.primary_feature_set}[{','.join(cols)}]", cols, cands)


@dataclass
class Trained:
    spec: Spec
    candidate: Candidate
    pipeline: Pipeline
    prior: PopulationPrior | None
    calibrator: PlattCalibrator
    threshold: float
    threshold_f1: float
    fit_participants: frozenset[int]
    inner_table: list[dict[str, Any]]
    inner_assignment: dict[int, int]

    def predict(self, X: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        raw = raw_scores(self.pipeline, X)
        return raw, uncalibrated_probability(self.spec.kind, raw), self.calibrator.predict(raw)


@dataclass
class CVResult:
    spec: Spec
    oof: pd.DataFrame
    folds: dict[int, Trained]
    test_matrices: dict[int, pd.DataFrame]
    audit: list[dict[str, Any]]


def _pids(values: Iterable[Any]) -> list[int]:
    return sorted({int(v) for v in values})


def _record(audit: list[dict[str, Any]], **kw: Any) -> None:
    audit.append({k: (_pids(v) if isinstance(v, (set, frozenset)) else v) for k, v in kw.items()})


def _select_rows(rows: pd.DataFrame) -> pd.DataFrame:
    t = rows[rows["target"]]
    return t if t["label"].nunique() == 2 else rows


def train(
    design: DesignBuilder,
    rows: pd.DataFrame,
    spec: Spec,
    train_pids: frozenset[int],
    inner_assignment: dict[int, int],
    tcfg: TrainingConfig,
    audit: list[dict[str, Any]],
    outer_fold: int | None,
    outer_test: frozenset[int],
) -> tuple[Trained, pd.DataFrame | None]:
    """Steps 2-6 above. Returns the trained model and its full-train design matrix (all meals)."""
    if train_pids & outer_test:
        raise LeakageError("training and test participants overlap")
    tr_rows = rows[rows["participant_id"].isin(train_pids)]
    inner_scores = {c: pd.Series(np.nan, index=tr_rows.index) for c in spec.candidates}
    for j in sorted(set(inner_assignment.values())):
        fit_p = frozenset(p for p in train_pids if inner_assignment[p] != j)
        val_p = frozenset(p for p in train_pids if inner_assignment[p] == j)
        X, prior = design.matrix(spec.columns, fit_p)
        fit_r = tr_rows[tr_rows["participant_id"].isin(fit_p)]
        val_r = tr_rows[tr_rows["participant_id"].isin(val_p)]
        if val_r.empty:
            continue
        for c in spec.candidates:
            pipe = build_pipeline(spec.kind, spec.columns, c.as_dict(), tcfg.seed, spec.monotone)
            pipe.fit(X.loc[fit_r.index], fit_r["label"].to_numpy())
            inner_scores[c].loc[val_r.index] = raw_scores(pipe, X.loc[val_r.index])
        _record(
            audit,
            stage="inner_fit",
            model=spec.name,
            feature_set=spec.feature_set,
            outer_fold=outer_fold,
            inner_fold=j,
            outer_test=outer_test,
            prior_fit=set(fit_p) if prior is not None else set(),
            preprocess_model_fit=set(fit_r["participant_id"]),
            scored=set(val_r["participant_id"]),
        )

    sel_rows = _select_rows(tr_rows)
    table: list[dict[str, Any]] = []
    for c in spec.candidates:
        s = inner_scores[c].loc[sel_rows.index]
        ok = s.notna()
        ap = (
            float(average_precision_score(sel_rows.loc[ok, "label"], s[ok])) if ok.any() else np.nan
        )
        table.append({"params": c.as_dict(), "inner_oof_pr_auc": ap})
    aps = [float(t["inner_oof_pr_auc"]) for t in table]
    best = int(np.nanargmax(aps))  # first on ties
    chosen = spec.candidates[best]

    s = inner_scores[chosen].loc[sel_rows.index]
    ok = s.notna().to_numpy()
    cal_rows = sel_rows[ok]
    calibrator = PlattCalibrator().fit(
        s[ok].to_numpy(), cal_rows["label"].to_numpy(), cal_rows["participant_id"].to_numpy()
    )
    _record(
        audit,
        stage="calibration",
        model=spec.name,
        feature_set=spec.feature_set,
        outer_fold=outer_fold,
        outer_test=outer_test,
        fit=set(cal_rows["participant_id"]),
    )
    threshold, f1 = f1_max_threshold(
        calibrator.predict(s[ok].to_numpy()), cal_rows["label"].to_numpy()
    )
    _record(
        audit,
        stage="threshold",
        model=spec.name,
        feature_set=spec.feature_set,
        outer_fold=outer_fold,
        outer_test=outer_test,
        fit=set(cal_rows["participant_id"]),
    )

    X_full, prior = design.matrix(spec.columns, train_pids)
    pipe = build_pipeline(spec.kind, spec.columns, chosen.as_dict(), tcfg.seed, spec.monotone)
    pipe.fit(X_full.loc[tr_rows.index], tr_rows["label"].to_numpy())
    _record(
        audit,
        stage="refit",
        model=spec.name,
        feature_set=spec.feature_set,
        outer_fold=outer_fold,
        outer_test=outer_test,
        prior_fit=set(train_pids) if prior is not None else set(),
        preprocess_model_fit=set(tr_rows["participant_id"]),
    )
    trained = Trained(
        spec,
        chosen,
        pipe,
        prior,
        calibrator,
        threshold,
        f1,
        train_pids,
        table,
        dict(inner_assignment),
    )
    return trained, X_full


def inner_assignment(
    people: pd.DataFrame, pids: frozenset[int], n: int, seed: int
) -> dict[int, int]:
    sub = people[people["participant_id"].isin(pids)]
    folds = assign_folds(sub, n, seed)
    return dict(zip(folds["participant_id"].astype(int), folds["fold"].astype(int), strict=True))


def people_table(design: DesignBuilder) -> pd.DataFrame:
    d = design.dataset
    return (
        d[["participant_id", "glycemic_group", "fold"]]
        .drop_duplicates("participant_id")
        .astype({"participant_id": int, "fold": int})
        .reset_index(drop=True)
    )


def run_cv(design: DesignBuilder, rows: pd.DataFrame, spec: Spec, tcfg: TrainingConfig) -> CVResult:
    people = people_table(design)
    audit: list[dict[str, Any]] = []
    folds: dict[int, Trained] = {}
    mats: dict[int, pd.DataFrame] = {}
    parts = []
    for k in sorted(people["fold"].unique()):
        test = frozenset(people.loc[people["fold"] == k, "participant_id"].astype(int))
        train_p = frozenset(people.loc[people["fold"] != k, "participant_id"].astype(int))
        assign = inner_assignment(people, train_p, tcfg.inner_folds, tcfg.seed + int(k) + 1)
        trained, X_full = train(design, rows, spec, train_p, assign, tcfg, audit, int(k), test)
        te = rows[rows["participant_id"].isin(test)]
        if te.empty:
            continue
        assert X_full is not None
        Xt = X_full.loc[te.index]
        raw, unc, prob = trained.predict(Xt)
        _record(
            audit,
            stage="score",
            model=spec.name,
            feature_set=spec.feature_set,
            outer_fold=int(k),
            outer_test=test,
            fit=set(trained.fit_participants),
            scored=set(te["participant_id"]),
        )
        part = te[["meal_id", "participant_id", "glycemic_group", "target", "fold", "label"]].copy()
        part["model"], part["feature_set"], part["model_fold"] = spec.name, spec.feature_set, int(k)
        part["raw_score"], part["prob_uncalibrated"], part["prob"] = raw, unc, prob
        part["threshold"] = trained.threshold
        part["pred"] = (prob >= trained.threshold).astype(int)
        parts.append(part)
        folds[int(k)], mats[int(k)] = trained, Xt
    oof = pd.concat(parts, ignore_index=True)
    return CVResult(spec, oof, folds, mats, audit)


def train_final(
    design: DesignBuilder, rows: pd.DataFrame, spec: Spec, tcfg: TrainingConfig
) -> tuple[Trained, list[dict[str, Any]]]:
    """The serving model: all participants; the pinned folds are its inner folds."""
    people = people_table(design)
    everyone = frozenset(people["participant_id"].astype(int))
    assign = dict(zip(people["participant_id"], people["fold"], strict=True))
    audit: list[dict[str, Any]] = []
    trained, _ = train(design, rows, spec, everyone, assign, tcfg, audit, None, frozenset())
    return trained, audit


def verify_boundaries(
    audit: list[dict[str, Any]], oof: pd.DataFrame | None = None
) -> dict[str, Any]:
    """Every fitting boundary, checked from the audit log. Raises LeakageError on any violation."""
    problems = []
    for r in audit:
        test = set(r.get("outer_test", []))
        for key in ("prior_fit", "preprocess_model_fit", "fit"):
            if set(r.get(key, [])) & test:
                problems.append(
                    f"{r['stage']} {r['model']} fold {r['outer_fold']}: {key} uses test participants"
                )
        if r["stage"] == "inner_fit":
            seen = set(r["prior_fit"]) | set(r["preprocess_model_fit"])
            if set(r["scored"]) & seen:
                problems.append(
                    f"inner fold {r['inner_fold']} scores participants it was fitted on"
                )
        if r["stage"] == "score" and (
            set(r["scored"]) & set(r["fit"]) or not set(r["scored"]) <= test
        ):
            problems.append(f"fold {r['outer_fold']} scored participants outside its test fold")
    if oof is not None:
        dup = oof.duplicated(["meal_id", "model", "feature_set"])
        if dup.any():
            problems.append(f"{int(dup.sum())} meals have more than one OOF prediction")
        if (oof["fold"] != oof["model_fold"]).any():
            problems.append("an OOF prediction came from a model of another fold")
    if problems:
        raise LeakageError("; ".join(problems[:5]))
    stages: dict[str, int] = {}
    for r in audit:
        stages[r["stage"]] = stages.get(r["stage"], 0) + 1
    return {"check": "M3 fitting boundaries", "passed": True, "detail": stages}
