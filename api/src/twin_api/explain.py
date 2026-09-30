"""Per-state explanations of the served model's score (M6 frontend adapter; no new science).

For a scored twin state, the exact 45 model inputs stored in the state are passed through the
served bundle's own fitted preprocessing, and the model's raw score (log-odds, before calibration)
is split into one contribution per input:

- XGBoost: exact TreeSHAP (``pred_contribs``), as in M3's SHAP report.
- Logistic regression: exact linear attribution (coefficient x transformed value); the learned
  missing-value indicators are added to the feature they belong to.

Contributions sum exactly to the raw score. They describe what the model relied on for this
prediction; they are associations, not causes, and say nothing about what would happen if an input
changed (that is the bounded what-if engine's job).
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

METHOD_NOTE = (
    "Contributions to the model's raw score (log-odds, before calibration). They show what the "
    "model relied on for this prediction; they are associations, not causes."
)


class NotExplainable(ValueError):
    """The served model does not expose an exact attribution method."""


def explain_inputs(model: Any, inputs: dict[str, float | None]) -> dict[str, Any]:
    """Split the model's raw score for ``inputs`` into per-feature contributions."""
    columns = list(model.columns)
    # JSONB does not keep key order, so compare the sets and rebuild the row in contract order.
    if set(inputs) != set(columns) or len(inputs) != len(columns):
        raise NotExplainable("stored inputs do not match the served model's contract columns")
    pipeline = getattr(model, "pipeline", None)
    if pipeline is None:
        raise NotExplainable("the served model exposes no fitted pipeline")
    X = pd.DataFrame(
        [[np.nan if inputs[c] is None else inputs[c] for c in columns]], columns=columns
    )
    pre, final = pipeline[:-1], pipeline[-1]
    arr = pre.transform(X)
    if hasattr(final, "get_booster"):
        import xgboost as xgb

        contrib = final.get_booster().predict(xgb.DMatrix(arr, missing=np.nan), pred_contribs=True)[
            0
        ]
        per = {c: float(v) for c, v in zip(columns, contrib[:-1], strict=True)}
        base, method = float(contrib[-1]), "tree_shap"
    elif hasattr(final, "coef_"):
        names = [str(n) for n in pre.get_feature_names_out()]
        terms = np.asarray(final.coef_[0], dtype=float) * np.asarray(arr[0], dtype=float)
        per = dict.fromkeys(columns, 0.0)
        for name, term in zip(names, terms, strict=True):
            owner = name.removeprefix("missingindicator_")
            if owner not in per:
                raise NotExplainable(f"cannot map transformed feature {name!r} to an input")
            per[owner] += float(term)
        base, method = float(final.intercept_[0]), "linear_exact"
    else:
        raise NotExplainable("no exact attribution method for this model type")
    raw = base + sum(per.values())
    ranked = sorted(columns, key=lambda c: -abs(per[c]))
    return {
        "method": method,
        "base_value": base,
        "raw_score": raw,
        "contributions": [
            {"feature": c, "value": inputs[c], "contribution": per[c]} for c in ranked
        ],
        "note": METHOD_NOTE,
    }
