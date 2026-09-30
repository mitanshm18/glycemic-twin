"""Model and baseline pipelines, the Platt calibrator and threshold selection.

Every pipeline starts with ``ContractColumns``, which refuses any input whose columns differ (in
name or order) from the contract columns it was built with. All other preprocessing (imputation,
missing-value indicators, scaling) lives INSIDE the pipeline, so it is fitted only when the pipeline
is fitted, i.e. only on the training rows of the current fit.

Raw scores: LR/XGBoost use the log-odds of their probability; the rule baseline uses
g_last + a * carbs_g; the personal-rate baseline uses p_personal. The calibrator maps a raw score to a
probability and is fitted separately, on inner out-of-fold scores only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, ClassifierMixin, TransformerMixin
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import precision_recall_curve
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from twin_ml.dataset.leakage import LeakageError

EPS = 1e-6


class ContractColumns(TransformerMixin, BaseEstimator):
    """First pipeline step: input must have exactly ``columns``, in order. Outputs a float array."""

    def __init__(self, columns: tuple[str, ...] = ()) -> None:
        self.columns = columns

    def _check(self, X: pd.DataFrame) -> None:
        if not isinstance(X, pd.DataFrame) or tuple(X.columns) != tuple(self.columns):
            got = list(X.columns) if isinstance(X, pd.DataFrame) else type(X).__name__
            raise LeakageError(f"input columns {got} != contract columns {list(self.columns)}")

    def fit(self, X: pd.DataFrame, y: Any = None) -> ContractColumns:
        self._check(X)
        self.n_fit_rows_ = len(X)
        return self

    def transform(self, X: pd.DataFrame) -> np.ndarray:
        self._check(X)
        return X.to_numpy(dtype=float)

    def get_feature_names_out(self, input_features: Any = None) -> np.ndarray:
        return np.asarray(self.columns, dtype=object)


class RuleScore(ClassifierMixin, BaseEstimator):
    """B1: score = first column + a * second column (g_last + a * carbs_g). Nothing is learned."""

    def __init__(self, a: float = 1.0) -> None:
        self.a = a

    def fit(self, X: np.ndarray, y: np.ndarray) -> RuleScore:
        self.classes_ = np.array([0, 1])
        return self

    def score_values(self, X: np.ndarray) -> np.ndarray:
        return np.asarray(X[:, 0] + self.a * X[:, 1], dtype=float)


class IdentityScore(ClassifierMixin, BaseEstimator):
    """B3: the single input column is the score (p_personal, already a probability)."""

    def fit(self, X: np.ndarray, y: np.ndarray) -> IdentityScore:
        self.classes_ = np.array([0, 1])
        return self

    def score_values(self, X: np.ndarray) -> np.ndarray:
        return np.asarray(X[:, 0], dtype=float)


def xgboost_available() -> bool:
    try:
        import xgboost  # noqa: F401
    except ImportError:
        return False
    return True


def build_pipeline(
    kind: str,
    columns: tuple[str, ...],
    params: dict[str, Any],
    seed: int,
    monotone: dict[str, int] | None = None,
) -> Pipeline:
    contract = ("contract", ContractColumns(columns))
    if kind == "logistic":
        return Pipeline(
            [
                contract,
                (
                    "impute",
                    SimpleImputer(strategy="median", add_indicator=True, keep_empty_features=True),
                ),
                ("scale", StandardScaler()),
                ("model", LogisticRegression(random_state=seed, **params)),
            ]
        )
    if kind == "xgboost":
        from xgboost import XGBClassifier

        mono = tuple(int((monotone or {}).get(c, 0)) for c in columns)
        return Pipeline(
            [
                contract,  # XGBoost handles NaN natively: no imputation, no scaling
                (
                    "model",
                    XGBClassifier(
                        random_state=seed,
                        monotone_constraints=mono,
                        eval_metric="logloss",
                        **params,
                    ),
                ),
            ]
        )
    if kind == "rule":
        return Pipeline(
            [
                contract,
                ("impute", SimpleImputer(strategy="median", keep_empty_features=True)),
                ("model", RuleScore(**params)),
            ]
        )
    if kind == "score":
        return Pipeline(
            [
                contract,
                ("impute", SimpleImputer(strategy="median", keep_empty_features=True)),
                ("model", IdentityScore()),
            ]
        )
    raise ValueError(f"unknown model kind {kind!r}")


def raw_scores(pipe: Pipeline, X: pd.DataFrame) -> np.ndarray:
    model = pipe[-1]
    if hasattr(model, "score_values"):
        return np.asarray(model.score_values(pipe[:-1].transform(X)), dtype=float)
    p = np.clip(pipe.predict_proba(X)[:, 1], EPS, 1 - EPS)
    return np.asarray(np.log(p / (1 - p)), dtype=float)


def uncalibrated_probability(kind: str, scores: np.ndarray) -> np.ndarray:
    if kind in ("logistic", "xgboost"):
        return 1 / (1 + np.exp(-scores))
    if kind == "score":
        return scores
    return np.full(len(scores), np.nan)  # the rule score is in mg/dL, not a probability


@dataclass
class PlattCalibrator:
    """p = sigmoid(slope * z + intercept), z = standardized raw score. Records who it was fitted on."""

    center: float = 0.0
    scale: float = 1.0
    slope: float = 1.0
    intercept: float = 0.0
    fitted_participants: frozenset[int] = field(default_factory=frozenset)
    n_fit_rows: int = 0

    def fit(self, scores: np.ndarray, y: np.ndarray, participants: np.ndarray) -> PlattCalibrator:
        y = np.asarray(y, dtype=int)
        if len(np.unique(y)) < 2:
            raise ValueError("calibration data need both classes")
        s = np.asarray(scores, dtype=float)
        self.center = float(np.mean(s))
        self.scale = float(np.std(s)) or 1.0
        lr = LogisticRegression(C=1e6, max_iter=1000)
        lr.fit(((s - self.center) / self.scale).reshape(-1, 1), y)
        self.slope = float(lr.coef_[0, 0])
        self.intercept = float(lr.intercept_[0])
        self.fitted_participants = frozenset(int(p) for p in participants)
        self.n_fit_rows = int(len(s))
        return self

    def predict(self, scores: np.ndarray) -> np.ndarray:
        z = (np.asarray(scores, dtype=float) - self.center) / self.scale
        return np.asarray(1 / (1 + np.exp(-(self.slope * z + self.intercept))), dtype=float)


def f1_max_threshold(prob: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    """Threshold (on calibrated probability) that maximizes F1. Used on inner OOF data only."""
    precision, recall, thresholds = precision_recall_curve(np.asarray(y, int), np.asarray(prob))
    f1 = 2 * precision[:-1] * recall[:-1] / np.clip(precision[:-1] + recall[:-1], EPS, None)
    i = int(np.argmax(f1))
    return float(thresholds[i]), float(f1[i])
