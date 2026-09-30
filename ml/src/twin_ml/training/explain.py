"""Leakage-safe SHAP for the tree model.

Each outer-fold XGBoost model explains ONLY the meals of its own held-out fold, so every explanation
comes from a model that never saw that participant (the same rule as the OOF predictions). Values
are XGBoost's exact TreeSHAP (``pred_contribs=True``), in log-odds, BEFORE calibration. Columns are
the model's contract columns, in contract order, plus the bias term; each row sums to the raw score.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from twin_ml.training.cv import CVResult


def tree_shap(cv: CVResult, rows: pd.DataFrame) -> pd.DataFrame:
    if cv.spec.kind != "xgboost":
        raise ValueError("tree SHAP applies to the xgboost model only")
    import xgboost as xgb

    cols = list(cv.spec.columns)
    parts = []
    for k, trained in sorted(cv.folds.items()):
        Xt = cv.test_matrices[k]
        pipe = trained.pipeline
        if list(Xt.columns) != cols or list(pipe[0].columns) != cols:
            raise ValueError("SHAP input does not match the model's contract columns")
        arr = pipe[:-1].transform(Xt)
        booster = pipe[-1].get_booster()
        # the booster was fitted on a plain array (no names), so the DMatrix carries none either;
        # column identity is guaranteed by the ContractColumns check above
        dm = xgb.DMatrix(arr, missing=np.nan)
        contrib = booster.predict(dm, pred_contribs=True)
        if contrib.shape[1] != len(cols) + 1:
            raise ValueError("unexpected SHAP shape")
        margin = booster.predict(dm, output_margin=True)
        if not np.allclose(contrib.sum(axis=1), margin, atol=1e-3):
            raise ValueError("SHAP values do not add up to the model output")
        frame = pd.DataFrame(contrib, columns=[*cols, "bias"], index=Xt.index)
        meta = rows.loc[Xt.index, ["meal_id", "participant_id", "glycemic_group", "target", "fold"]]
        parts.append(pd.concat([meta, frame.add_prefix("shap__")], axis=1))
    return pd.concat(parts, ignore_index=True)


def global_importance(shap: pd.DataFrame, columns: tuple[str, ...]) -> list[dict[str, Any]]:
    """Mean |SHAP| per feature on target-group OOF meals, largest first."""
    t = shap[shap["target"]]
    imp = [{"feature": c, "mean_abs_shap": float(t[f"shap__{c}"].abs().mean())} for c in columns]
    return sorted(imp, key=lambda d: -d["mean_abs_shap"])


def logistic_coefficients(pipeline: Any) -> list[dict[str, Any]]:
    """Standardized LR coefficients (per 1 SD of the imputed feature), incl. missing indicators."""
    names = list(pipeline[:-1].get_feature_names_out())
    coef = pipeline[-1].coef_[0]
    rows = [
        {"feature": str(n), "coefficient_per_sd": float(c)}
        for n, c in zip(names, coef, strict=True)
    ]
    return sorted(rows, key=lambda d: -abs(d["coefficient_per_sd"]))
