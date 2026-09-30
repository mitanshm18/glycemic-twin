"""Bounded, non-causal what-if scenarios on the current meal.

A scenario changes one or more levers of the CURRENT meal (carbs, fiber, protein, fat) or the
recorded pre-meal activity (active minutes in the 3 h before the meal, only when the person's
wearable reports METs). The twin rebuilds the model inputs with ``meal_features`` (so calories and
every derived input follow the change consistently), keeps everything else fixed, and asks the same
model for a new probability.

What it is: "for a meal like this one, with these macros instead, the model estimates risk X".
What it is not: a causal effect, a recommendation, or medical advice. The twin refuses any lever
about medication, insulin, diagnosis or treatment, any lever it does not know, any change larger
than the configured bound, and returns ``out_of_support`` when a changed input leaves the range
seen in training. Post-meal activity cannot be simulated: the model has no post-meal inputs.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import replace
from typing import Any, Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict

from twin_core.features import MealInput, meal_features
from twin_core.twin.engine import TwinRuntime, build, model_row, uncertainty
from twin_core.twin.model import ModelIdentity, identity
from twin_core.twin.record import RecordSource, finite_or_none
from twin_core.twin.state import DISCLAIMER, Uncertainty

MEAL_LEVERS = ("carbs_g", "fiber_g", "protein_g", "fat_g")
ACTIVITY_LEVERS = ("active_min_3h",)
LEVERS = (*MEAL_LEVERS, *ACTIVITY_LEVERS)


class ScenarioError(ValueError):
    """The scenario is invalid or not allowed (never silently adjusted)."""


class ChangedInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    feature: str
    before: float | None
    after: float | None
    support_lo: float | None
    support_hi: float | None
    in_support: bool


class ScenarioResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    scenario_id: str
    status: Literal["ok", "out_of_support"]
    patient_id: int
    as_of: str
    base_state_id: str
    meal_id: str | None
    changes: dict[str, float]
    baseline_probability: float
    scenario_probability: float | None
    risk_delta: float | None
    changed_inputs: list[ChangedInput]
    held_fixed: str
    uncertainty: Uncertainty | None
    model: ModelIdentity
    disclaimer: str
    kind: str = "model-estimated, non-causal, non-medical what-if"


def validate(changes: Mapping[str, Any], runtime: TwinRuntime) -> dict[str, float]:
    cfg = runtime.configs.twin.what_if
    if not changes:
        raise ScenarioError("a scenario needs at least one change")
    out: dict[str, float] = {}
    for key, value in changes.items():
        k = str(key).strip().lower()
        if any(term in k for term in cfg.blocked_terms):
            raise ScenarioError(
                f"{key!r}: the twin never simulates medication, insulin, diagnosis or treatment"
            )
        if k not in LEVERS:
            raise ScenarioError(f"{key!r} is not a supported lever; supported: {', '.join(LEVERS)}")
        if isinstance(value, bool):
            raise ScenarioError(f"{key!r}: change must be a number")
        try:
            v = float(value)
        except (TypeError, ValueError) as err:
            raise ScenarioError(f"{key!r}: change must be a number") from err
        if not np.isfinite(v):
            raise ScenarioError(f"{key!r}: change must be finite")
        bound = cfg.max_abs_delta[k]
        if abs(v) > bound:
            raise ScenarioError(f"{key!r}: |{v:g}| exceeds the allowed change of {bound:g}")
        out[k] = v
    return out


def simulate(
    patient_id: int,
    as_of: Any,
    changes: Mapping[str, Any],
    *,
    source: RecordSource,
    runtime: TwinRuntime,
    current_meal: MealInput | None = None,
    current_meal_id: str | None = None,
) -> ScenarioResult:
    deltas = validate(changes, runtime)
    if runtime.model is None:
        raise ScenarioError("what-if needs a loaded model")
    if runtime.support is None:
        raise ScenarioError("what-if needs the training-support profile of the served model")
    built = build(
        patient_id,
        as_of,
        source=source,
        runtime=runtime,
        current_meal=current_meal,
        current_meal_id=current_meal_id,
    )
    s, ctx = built.scored, built.meal
    if ctx is None or s is None:
        raise ScenarioError("no current meal at as_of: nothing to change")
    if s.risk.status != "scored" or s.risk.probability is None:
        raise ScenarioError(f"the current meal is not scorable: {s.risk.reason}")

    cfg = runtime.configs
    meal = ctx.meal
    new_macros = {c: float(getattr(meal, c)) + deltas.get(c, 0.0) for c in MEAL_LEVERS}
    for c, v in new_macros.items():
        if v < 0:
            raise ScenarioError(f"{c} would become negative ({v:g} g)")
    if new_macros["fiber_g"] > new_macros["carbs_g"]:
        raise ScenarioError("fiber cannot exceed carbohydrate (cleaning.v1 rule)")
    kcal = float(meal.calories_kcal) + sum(
        deltas.get(c, 0.0) * cfg.twin.what_if.kcal_per_g[c] for c in MEAL_LEVERS
    )
    if kcal < 0:
        raise ScenarioError("calories would become negative")
    new_meal = replace(
        meal,
        carbs_g=new_macros["carbs_g"],
        fiber_g=new_macros["fiber_g"],
        protein_g=new_macros["protein_g"],
        fat_g=new_macros["fat_g"],
        calories_kcal=kcal,
    )
    base2, _ = meal_features(built.prep.history, new_meal, cfg.features)

    if "active_min_3h" in deltas:
        before = s.base.get("active_min_3h", float("nan"))
        if not built.prep.history.mets_available or not np.isfinite(before):
            raise ScenarioError(
                "pre-meal activity cannot be simulated: this person's wearable has no METs "
                "(activity is unknown, never assumed to be zero)"
            )
        after = before + deltas["active_min_3h"]
        window = cfg.features.windows.prev_meal_window_min
        if not 0 <= after <= window:
            raise ScenarioError(f"active_min_3h must stay within [0, {window}] minutes")
        base2["active_min_3h"] = after

    X0 = model_row(runtime, s.base, s.personal)  # personal features depend on history only
    X1 = model_row(runtime, base2, s.personal)
    changed_cols = [c for c in X0.columns if not _same(X0.iloc[0][c], X1.iloc[0][c])]
    after_vals = {c: finite_or_none(X1.iloc[0][c]) for c in X1.columns}
    oos = runtime.support.check({c: after_vals[c] for c in changed_cols})
    changed = []
    for c in changed_cols:
        sup = runtime.support.features.get(c)
        changed.append(
            ChangedInput(
                feature=c,
                before=finite_or_none(X0.iloc[0][c]),
                after=after_vals[c],
                support_lo=None if sup is None else sup.lo,
                support_hi=None if sup is None else sup.hi,
                in_support=c not in oos,
            )
        )
    model = runtime.model
    p0 = float(s.risk.probability)
    status: Literal["ok", "out_of_support"] = "out_of_support" if oos else "ok"
    p1 = None if oos else float(np.asarray(model.predict_proba(X1), dtype=float).reshape(-1)[0])
    unc = None
    if p1 is not None:
        w = s.personal["personal_weight"] if s.personal else None
        unc = uncertainty(p1, float(model.threshold), after_vals, w, runtime)
    body = {
        "patient_id": built.state.patient_id,
        "as_of": built.state.as_of,
        "base_state_id": built.state.state_id,
        "changes": deltas,
        "model_version": identity(model).model_version,
    }
    sid = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
    return ScenarioResult(
        scenario_id=sid,
        status=status,
        patient_id=built.state.patient_id,
        as_of=built.state.as_of,
        base_state_id=built.state.state_id,
        meal_id=ctx.meal_id,
        changes=deltas,
        baseline_probability=p0,
        scenario_probability=p1,
        risk_delta=None if p1 is None else p1 - p0,
        changed_inputs=changed,
        held_fixed=(
            "every other input: glucose history, wearable, clinical values, meal time and type, and "
            "the personal features (they depend only on closed past meals)"
        ),
        uncertainty=unc,
        model=identity(model),
        disclaimer=DISCLAIMER,
    )


def _same(a: Any, b: Any) -> bool:
    fa, fb = float(a), float(b)
    return (np.isnan(fa) and np.isnan(fb)) or fa == fb


def scenario_table(results: list[ScenarioResult]) -> pd.DataFrame:
    """Convenience: one row per scenario (for notebooks and the M5 API)."""
    return pd.DataFrame(
        [
            {
                "changes": json.dumps(r.changes, sort_keys=True),
                "status": r.status,
                "baseline": r.baseline_probability,
                "scenario": r.scenario_probability,
                "delta": r.risk_delta,
            }
            for r in results
        ]
    )
