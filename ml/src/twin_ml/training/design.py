"""Fold-aware model input matrices (ADR-015).

``DesignBuilder.matrix(columns, prior_participants)`` is the only way training code gets a model
input matrix. It

1. fits a ``PopulationPrior`` on the frozen-usable meals of ``prior_participants`` ONLY (the training
   participants of the current fit), when the columns include personal features;
2. computes personal features for every meal of every participant with that prior, each row using
   only that person's meals whose 120-minute window closed at or before the row's meal start;
3. returns exactly the requested contract columns, in contract order, indexed by meal_id.

Outcome columns never reach the matrix: the base features are copied from the M2 feature columns by
name, and the personal features come from ``personal_features``, which reads past labels only.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import numpy as np
import pandas as pd
from twin_core.config import FeatureConfig, LabelConfig, ModelFeatureContract
from twin_core.personalization import (
    REQUIRED as PRIOR_INPUTS,
)
from twin_core.personalization import (
    PopulationPrior,
    fit_population_prior,
    personal_features,
)

from twin_ml.dataset.leakage import LeakageError, check_model_inputs

ID_COLUMNS = ("meal_id", "participant_id", "started_at", "glycemic_group", "fold")


class DesignBuilder:
    def __init__(
        self,
        dataset: pd.DataFrame,
        contract: ModelFeatureContract,
        fcfg: FeatureConfig,
        lcfg: LabelConfig,
        min_meals_per_person: int = 3,
    ) -> None:
        base = [c for c in contract.columns(fcfg, "full_multimodal")]
        needed = {*ID_COLUMNS, *PRIOR_INPUTS, *base, "eligible"}
        missing = sorted(needed - set(dataset.columns))
        if missing:
            raise ValueError(f"dataset is missing columns: {missing}")
        if dataset["meal_id"].duplicated().any():
            raise ValueError("meal_id must be unique")
        self.dataset = dataset.set_index("meal_id", drop=False)
        self.contract, self.fcfg, self.lcfg = contract, fcfg, lcfg
        self.min_meals = min_meals_per_person
        self.personal_cols = tuple(contract.personal.features)
        self._base = self.dataset[base].astype(float)
        self._cache: dict[frozenset[int], tuple[PopulationPrior, pd.DataFrame]] = {}
        self.prior_fits: list[frozenset[int]] = []  # audit: participants of every prior fit

    def personal(self, prior_participants: Iterable[int]) -> tuple[PopulationPrior, pd.DataFrame]:
        key = frozenset(int(p) for p in prior_participants)
        if key not in self._cache:
            train = self.dataset[self.dataset["participant_id"].isin(key)]
            prior = fit_population_prior(
                train[list(PRIOR_INPUTS)].reset_index(drop=True), self.min_meals
            )
            self.prior_fits.append(key)
            frames = [
                personal_features(g[list(PRIOR_INPUTS)], prior, self.lcfg.horizon_min)
                for _, g in self.dataset.groupby("participant_id", sort=True)
            ]
            pf = pd.concat(frames).loc[self.dataset.index, list(self.personal_cols)]
            self._cache[key] = (prior, pf)
        return self._cache[key]

    def matrix(
        self, columns: tuple[str, ...], prior_participants: Iterable[int] | None
    ) -> tuple[pd.DataFrame, PopulationPrior | None]:
        """All meals' inputs for ``columns``; personal columns use a prior fitted on
        ``prior_participants`` (required whenever the columns include a personal feature)."""
        cols = list(columns)
        prior = None
        parts: list[pd.DataFrame] = [self._base[[c for c in cols if c in self._base.columns]]]
        if any(c in self.personal_cols for c in cols):
            if prior_participants is None:
                raise ValueError("personal features need the training participants of this fit")
            prior, pf = self.personal(prior_participants)
            parts.append(pf)
        X = pd.concat(parts, axis=1)
        unknown = [c for c in cols if c not in X.columns]
        if unknown:
            raise LeakageError(f"columns not produced by the contract sources: {unknown}")
        X = X[cols]
        assert_inputs(tuple(X.columns), self.contract, self.fcfg)
        return X, prior


def assert_inputs(
    columns: tuple[str, ...], contract: ModelFeatureContract, fcfg: FeatureConfig
) -> None:
    result = check_model_inputs(columns, contract, fcfg)
    if not result["passed"]:
        raise LeakageError(str(result["detail"]))


def eligible_rows(dataset: pd.DataFrame, target_groups: tuple[str, ...]) -> pd.DataFrame:
    """Rows a model is fitted and evaluated on: eligible meals, all glycemic groups."""
    rows = dataset.loc[
        dataset["eligible"].astype(bool),
        ["meal_id", "participant_id", "glycemic_group", "fold", "started_at", "label"],
    ].copy()
    if rows["label"].isna().any():
        raise ValueError("eligible meals must all have a label")
    rows["label"] = rows["label"].astype(int)
    rows["participant_id"] = rows["participant_id"].astype(int)
    rows["fold"] = rows["fold"].astype(int)
    rows["target"] = rows["glycemic_group"].isin(target_groups)
    return rows.set_index("meal_id", drop=False)


def describe_prior(prior: PopulationPrior | None) -> dict[str, Any] | None:
    if prior is None:
        return None
    return {
        "alpha": prior.alpha,
        "beta": prior.beta,
        "population_rate": prior.population_rate,
        "rise_coef": list(prior.rise_coef),
        "k": prior.k,
        "n_people": prior.n_people,
        "n_meals": prior.n_meals,
    }


def finite_personal(X: pd.DataFrame, personal_cols: tuple[str, ...]) -> bool:
    cols = [c for c in personal_cols if c in X.columns]
    return bool(np.isfinite(X[cols].to_numpy(float)).all()) if cols else True
