"""Build a Digital Twin state: ``build_state(patient_id, as_of, source=..., runtime=...)``.

Pure and deterministic: the output depends only on the record's observations up to ``as_of``, the
frozen configs and the model bundle. No wall clock, randomness or I/O is involved, and the state's
``state_id`` is a hash of its canonical JSON, so the same inputs always give the same id.

How a state is built (every step reuses the M1-M3 code, so training and serving cannot drift):

1. ``record.as_of(as_of)``: drop every observation after ``as_of``.
2. Meal outcomes are recomputed from that cut with ``labels.meal_outcomes`` (the frozen labels.v1
   rules) and kept only for meals whose 120-minute window closed at or before ``as_of``.
3. ``features.meal_features`` gives the 42 base features, exactly as in M2.
4. ``personalization.personal_features`` with the PopulationPrior stored in the model bundle gives
   p_personal, rise_offset_mgdl and personal_weight from closed windows only, exactly as in M3.
5. The model receives the contract columns in contract order; it applies its own fitted
   preprocessing and calibrator. Nothing is re-estimated at serving time.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from twin_core.features import (
    MealInput,
    ParticipantHistory,
    as_ns,
    history_from_tables,
    meal_features,
    meal_input,
)
from twin_core.labels import meal_outcomes
from twin_core.personalization import PopulationPrior, personal_features
from twin_core.twin.config import TwinConfigs
from twin_core.twin.model import ModelContractError, RiskModel, check_compatible, identity
from twin_core.twin.record import (
    CLINICAL_OBSERVED,
    PatientRecord,
    RecordSource,
    finite_or_none,
    native_readings,
)
from twin_core.twin.state import (
    DISCLAIMER,
    ENGINE_VERSION,
    ClinicalField,
    ClosedMeal,
    CurrentMeal,
    CurrentPhysiology,
    Freshness,
    Lifecycle,
    PersonalBaselines,
    PersonalResponse,
    Phase,
    Provenance,
    RecentHistory,
    RiskEstimate,
    StaticClinical,
    TwinState,
    Uncertainty,
)
from twin_core.twin.support import SupportProfile

PROBE_ID = "__as_of_probe__"


class FutureDataError(RuntimeError):
    """A computed value used an observation later than as_of (must never happen)."""


@dataclass(frozen=True)
class TwinRuntime:
    """What a state is computed under: the frozen configs, the served model, its support profile."""

    configs: TwinConfigs
    model: RiskModel | None = None
    support: SupportProfile | None = None

    def __post_init__(self) -> None:
        if self.model is None:
            return
        if not isinstance(self.model, RiskModel):
            raise ModelContractError("the model does not provide the RiskModel interface")
        c = self.configs
        check_compatible(self.model, c.contract, c.features, c.hashes)
        data_sha = getattr(self.model, "dataset_content_sha256", None)
        if (
            self.support is not None
            and data_sha
            and data_sha != self.support.dataset_content_sha256
        ):
            raise ModelContractError("support profile was built from a different training dataset")

    @property
    def prior(self) -> PopulationPrior | None:
        return None if self.model is None else self.model.prior


# ------------------------------------------------------------------------------------ preparation


@dataclass(frozen=True)
class Prepared:
    record: PatientRecord  # already cut at as_of
    as_of: pd.Timestamp
    history: ParticipantHistory
    outcomes: pd.DataFrame  # one row per meal <= as_of; outcomes only for closed windows
    personal_frame: pd.DataFrame  # personalization inputs (REQUIRED columns), closed-only outcomes


def _ts(x: Any) -> str | None:
    return None if x is None or pd.isna(x) else pd.Timestamp(x).isoformat()


def prepare(full: PatientRecord, as_of: Any, configs: TwinConfigs) -> Prepared:
    t = pd.Timestamp(as_ns(as_of))
    if pd.isna(t):
        raise ValueError("as_of must be a timestamp")
    r = full.as_of(t)
    horizon = pd.Timedelta(minutes=configs.labels.horizon_min)
    meals = r.meals
    cols = [
        "meal_id",
        "frozen_usable",
        "label",
        "peak_native_mgdl",
        "pre_meal_native_mgdl",
    ]
    if len(meals):
        out = meal_outcomes(
            meals[["meal_id", "started_at", "macro_validity"]],
            r.cgm[["ts", "dexcom_mgdl", "dexcom_is_native"]],
            configs.labels,
        )[cols]
    else:
        out = pd.DataFrame({c: pd.Series(dtype=object if c == "meal_id" else float) for c in cols})
    out = meals[["meal_id", "started_at", "macro_validity", "carbs_g", "fiber_g"]].merge(
        out, on="meal_id", how="left"
    )
    closed = (out["started_at"] + horizon) <= t
    out["window_closed"] = closed.to_numpy()
    out["window_closed_at"] = out["started_at"] + horizon
    out["frozen_usable"] = out["frozen_usable"].fillna(False).astype(bool) & closed
    out["label"] = out["label"].astype("Float64").where(out["frozen_usable"], pd.NA)
    out["rise_native_mgdl"] = (out["peak_native_mgdl"] - out["pre_meal_native_mgdl"]).where(
        out["frozen_usable"]
    )
    history = history_from_tables(
        full.patient_id,
        r.cgm,
        r.wearable,
        meals,
        out[["meal_id", "frozen_usable", "label"]],
        full.clinical,
        configs.labels.horizon_min,
    )
    valid = out["macro_validity"] == "valid"
    personal = pd.DataFrame(
        {
            "meal_id": out["meal_id"],
            "participant_id": full.patient_id,
            "started_at": out["started_at"],
            "frozen_usable": out["frozen_usable"],
            "label": out["label"],
            "rise_native_mgdl": out["rise_native_mgdl"],
            "carbs_g": out["carbs_g"].where(valid),
            "fiber_g": out["fiber_g"].where(valid),
            "pre_meal_native_mgdl": out["pre_meal_native_mgdl"],
        }
    )
    return Prepared(r, t, history, out, personal)


def personal_at(
    prep: Prepared, t: pd.Timestamp, prior: PopulationPrior, horizon: int
) -> dict[str, float]:
    """Personal features for a meal starting at ``t`` (only windows closed at ``t`` count)."""
    probe = pd.DataFrame(
        {
            "meal_id": [PROBE_ID],
            "participant_id": [prep.record.patient_id],
            "started_at": [t],
            "frozen_usable": [False],
            "label": pd.array([pd.NA], dtype="Float64"),
            "rise_native_mgdl": [np.nan],
            "carbs_g": [np.nan],
            "fiber_g": [np.nan],
            "pre_meal_native_mgdl": [np.nan],
        }
    )
    frame = pd.concat([prep.personal_frame, probe], ignore_index=True)
    pf = personal_features(frame.drop(columns="meal_id"), prior, horizon)
    row = pf.iloc[-1]  # aligned to frame's index: the probe is the last row
    closed = prep.outcomes[
        prep.outcomes["frozen_usable"] & (prep.outcomes["window_closed_at"] <= t)
    ]
    return {
        "p_personal": float(row["p_personal"]),
        "rise_offset_mgdl": float(row["rise_offset_mgdl"]),
        "personal_weight": float(row["personal_weight"]),
        "n_closed_meals": float(row["n_closed_meals"]),
        "n_closed_positive": float(closed["label"].astype(float).sum()),
    }


def _probe_meal(t: pd.Timestamp) -> MealInput:
    nan = float("nan")
    return MealInput(as_ns(t), None, nan, nan, nan, nan, nan, False)


# ------------------------------------------------------------------------------------ current meal


@dataclass(frozen=True)
class MealContext:
    meal: MealInput
    meal_id: str | None
    origin: str


def resolve_meal(
    prep: Prepared,
    horizon: int,
    current_meal: MealInput | None,
    current_meal_id: str | None,
) -> MealContext | None:
    if current_meal is not None and current_meal_id is not None:
        raise ValueError("give either current_meal or current_meal_id, not both")
    meals = prep.record.meals
    if current_meal_id is not None:
        hit = meals[meals["meal_id"] == current_meal_id]
        if hit.empty:
            raise ValueError(f"meal {current_meal_id!r} is not in the record at or before as_of")
        return MealContext(meal_input(hit.iloc[0].to_dict()), current_meal_id, "logged")
    if current_meal is not None:
        if pd.Timestamp(current_meal.started_at) != prep.as_of:
            raise ValueError("a proposed meal must start exactly at as_of")
        return MealContext(current_meal, None, "proposed")
    open_ = meals[meals["started_at"] + pd.Timedelta(minutes=horizon) > prep.as_of]
    if open_.empty:
        return None
    last = open_.iloc[-1]  # the most recent meal whose prediction window is still open
    return MealContext(meal_input(last.to_dict()), str(last["meal_id"]), "logged")


def applicability(base: dict[str, float], meal: MealInput, configs: TwinConfigs) -> list[str]:
    """The model was trained on eligible meals only; say why a meal is outside that population."""
    lab = configs.labels
    g = base.get("g_last", float("nan"))
    reasons = []
    if not np.isfinite(g):
        reasons.append(
            f"no native Dexcom reading in the {lab.pre_meal_lookback_min} min before the meal"
        )
    elif g > lab.already_high_threshold_mgdl:
        reasons.append(
            f"glucose already above {lab.already_high_threshold_mgdl:g} mg/dL at meal start "
            "(the model was not trained on such meals)"
        )
    if not meal.macros_valid:
        reasons.append("meal macros are missing, empty, inconsistent or invalid")
    return reasons


# ------------------------------------------------------------------------------------ scoring


def model_row(
    runtime: TwinRuntime, base: dict[str, float], personal: dict[str, float] | None
) -> pd.DataFrame:
    assert runtime.model is not None
    values = {**base, **(personal or {})}
    missing = [c for c in runtime.model.columns if c not in values]
    if missing:
        raise ModelContractError(f"the twin produced no value for {missing}")
    return pd.DataFrame(
        [[values[c] for c in runtime.model.columns]], columns=list(runtime.model.columns)
    )


def uncertainty(
    p: float,
    threshold: float,
    inputs: dict[str, float | None],
    weight: float | None,
    runtime: TwinRuntime,
) -> Uncertainty:
    missing = [k for k, v in inputs.items() if v is None]
    oos = runtime.support.check(inputs) if runtime.support else []
    soft, reasons = 0, []
    if oos:
        reasons.append(f"inputs outside the training range: {', '.join(oos)}")
    if missing:
        soft += 1
        reasons.append(f"{len(missing)} inputs missing (handled as in training)")
    if weight is not None and weight < runtime.configs.twin.lifecycle.personalized_min_weight:
        soft += 1
        reasons.append("personal evidence still weak: estimate leans on the population")
    dist = abs(p - threshold)
    if dist < runtime.configs.twin.uncertainty.near_threshold_band:
        soft += 1
        reasons.append("probability close to the decision threshold")
    if runtime.support is None:
        reasons.append("no training-support profile loaded: support not checked")
    level = "high" if oos or soft >= 2 else "moderate" if soft == 1 else "low"
    pc = min(max(p, 1e-12), 1 - 1e-12)
    entropy = -(pc * math.log2(pc) + (1 - pc) * math.log2(1 - pc))
    return Uncertainty(
        level=level,  # type: ignore[arg-type]
        reasons=reasons,
        outcome_entropy_bits=round(entropy, 6),
        distance_to_threshold=dist,
        personal_weight=weight,
        missing_inputs=missing,
        out_of_support_inputs=oos,
        support_checked=runtime.support is not None,
    )


@dataclass(frozen=True)
class Scored:
    risk: RiskEstimate
    base: dict[str, float]
    personal: dict[str, float] | None
    max_src: pd.Timestamp | None


def score(prep: Prepared, ctx: MealContext, runtime: TwinRuntime) -> Scored:
    cfg = runtime.configs
    base, src = meal_features(prep.history, ctx.meal, cfg.features)
    t0 = pd.Timestamp(ctx.meal.started_at)
    reasons = applicability(base, ctx.meal, cfg)
    max_src = None if np.isnat(src) else pd.Timestamp(src)
    if runtime.model is None:
        return Scored(
            RiskEstimate(
                status="unavailable",
                reason="no model loaded",
                probability=None,
                threshold=None,
                above_threshold=None,
                features_at=_ts(t0),
                model_inputs=None,
                uncertainty=None,
            ),
            base,
            None,
            max_src,
        )
    model = runtime.model
    personal = None
    if runtime.prior is not None:
        personal = personal_at(prep, t0, runtime.prior, cfg.labels.horizon_min)
    X = model_row(runtime, base, personal)
    inputs = {c: finite_or_none(X.iloc[0][c]) for c in X.columns}
    if reasons:
        return Scored(
            RiskEstimate(
                status="not_applicable",
                reason="; ".join(reasons),
                probability=None,
                threshold=float(model.threshold),
                above_threshold=None,
                features_at=_ts(t0),
                model_inputs=inputs,
                uncertainty=None,
            ),
            base,
            personal,
            max_src,
        )
    p = float(np.asarray(model.predict_proba(X), dtype=float).reshape(-1)[0])
    w = personal["personal_weight"] if personal else None
    return Scored(
        RiskEstimate(
            status="scored",
            reason=None,
            probability=p,
            threshold=float(model.threshold),
            above_threshold=bool(p >= model.threshold),
            features_at=_ts(t0),
            model_inputs=inputs,
            uncertainty=uncertainty(p, float(model.threshold), inputs, w, runtime),
        ),
        base,
        personal,
        max_src,
    )


# ------------------------------------------------------------------------------------ the state


def lifecycle(
    n: int, weight: float | None, prior: PopulationPrior | None, runtime: TwinRuntime
) -> Lifecycle:
    lc = runtime.configs.twin.lifecycle
    need_w = lc.personalized_min_weight
    if n == 0:
        return Lifecycle(
            phase=Phase.COLD_START,
            reason="no closed meal window yet: the twin uses the population prior only",
            closed_usable_meals=0,
            personal_weight=weight,
            next_phase_requires="one meal whose 120-minute window has closed (frozen-usable)",
        )
    if weight is None or weight < need_w or n < lc.personalized_min_closed_meals:
        k = prior.k if prior else float("nan")
        return Lifecycle(
            phase=Phase.WARMING,
            reason=(
                f"{n} closed usable meal(s); personal weight "
                f"{'unknown' if weight is None else f'{weight:.2f}'} "
                f"(needs >= {need_w:.2f} and >= {lc.personalized_min_closed_meals} meals)"
            ),
            closed_usable_meals=n,
            personal_weight=weight,
            next_phase_requires=(
                f"about {math.ceil(k * need_w / (1 - need_w)) if np.isfinite(k) else '?'} closed "
                f"meals with rise data (k = {k:.2f}) and >= {lc.personalized_min_closed_meals} "
                "usable meals"
            ),
        )
    return Lifecycle(
        phase=Phase.PERSONALIZED,
        reason=f"{n} closed usable meals; personal weight {weight:.2f} >= {need_w:.2f}",
        closed_usable_meals=n,
        personal_weight=weight,
        next_phase_requires=None,
    )


def _state_id(canonical: dict[str, Any]) -> str:
    blob = json.dumps(canonical, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(blob.encode()).hexdigest()


@dataclass(frozen=True)
class Built:
    state: TwinState
    prep: Prepared
    meal: MealContext | None
    scored: Scored | None


def build(
    patient_id: int,
    as_of: Any,
    *,
    source: RecordSource,
    runtime: TwinRuntime,
    current_meal: MealInput | None = None,
    current_meal_id: str | None = None,
) -> Built:
    cfg = runtime.configs
    horizon = cfg.labels.horizon_min
    prep = prepare(source.record(patient_id), as_of, cfg)
    t = prep.as_of
    r = prep.record

    now, now_src = meal_features(prep.history, _probe_meal(t), cfg.features)
    prior = runtime.prior
    personal_now = personal_at(prep, t, prior, horizon) if prior is not None else None
    closed = prep.outcomes[prep.outcomes["window_closed"]]
    n_closed = int(closed["frozen_usable"].sum())

    ctx = resolve_meal(prep, horizon, current_meal, current_meal_id)
    scored = score(prep, ctx, runtime) if ctx is not None else None

    f = {k: finite_or_none(v) for k, v in now.items()}
    clinical = [
        ClinicalField(
            name=k, value=finite_or_none(r.clinical[k]), provenance="observed", source="bio.csv"
        )
        for k in CLINICAL_OBSERVED
    ] + [
        ClinicalField(
            name="sex_female",
            value=finite_or_none(r.clinical["sex_female"]),
            provenance="derived",
            source="bio.csv Gender (F=1, M=0)",
        ),
        ClinicalField(
            name="homa_ir",
            value=f["homa_ir"],
            provenance="derived",
            source="fasting glucose x fasting insulin / 405",
        ),
    ]
    listed = closed.sort_values("started_at", ascending=False).head(cfg.twin.recent_meals_listed)
    recent = [
        ClosedMeal(
            meal_id=str(m["meal_id"]),
            started_at=_ts(m["started_at"]) or "",
            window_closed_at=_ts(m["window_closed_at"]) or "",
            frozen_usable=bool(m["frozen_usable"]),
            label=None if pd.isna(m["label"]) else int(m["label"]),
            rise_native_mgdl=finite_or_none(m["rise_native_mgdl"]),
        )
        for _, m in listed.iterrows()
    ]
    day = r.meals[r.meals["started_at"] > t - pd.Timedelta(hours=24)]

    native = native_readings(r.cgm)
    last_cgm = None if native.empty else pd.Timestamp(native["ts"].iloc[-1])
    wear = r.wearable[r.wearable["hr_bpm"].notna()]
    last_wear = None if wear.empty else pd.Timestamp(wear["ts"].iloc[-1])

    def age(x: pd.Timestamp | None) -> float | None:
        return None if x is None else (t - x).total_seconds() / 60

    fr = cfg.twin.freshness
    cgm_age, wear_age = age(last_cgm), age(last_wear)

    current = None
    if ctx is not None and scored is not None:
        m = ctx.meal
        t0 = pd.Timestamp(m.started_at)
        reasons = applicability(scored.base, m, cfg)
        current = CurrentMeal(
            meal_id=ctx.meal_id,
            origin=ctx.origin,  # type: ignore[arg-type]
            started_at=_ts(t0) or "",
            prediction_window_closes_at=_ts(t0 + pd.Timedelta(minutes=horizon)) or "",
            minutes_since_start=(t - t0).total_seconds() / 60,
            meal_type=m.meal_type,
            carbs_g=finite_or_none(m.carbs_g),
            protein_g=finite_or_none(m.protein_g),
            fat_g=finite_or_none(m.fat_g),
            fiber_g=finite_or_none(m.fiber_g),
            calories_kcal=finite_or_none(m.calories_kcal),
            macros_valid=m.macros_valid,
            applicable=not reasons,
            not_applicable_reasons=reasons,
        )

    personal_resp = None
    if personal_now is not None and prior is not None:
        personal_resp = PersonalResponse(
            closed_usable_meals=int(personal_now["n_closed_meals"]),
            closed_positive_meals=int(personal_now["n_closed_positive"]),
            population_rate=prior.population_rate,
            p_personal=personal_now["p_personal"],
            rise_offset_mgdl=personal_now["rise_offset_mgdl"],
            personal_weight=personal_now["personal_weight"],
            prior_fitted_on_people=prior.n_people,
            prior_fitted_on_meals=prior.n_meals,
        )

    risk = (
        scored.risk
        if scored is not None
        else RiskEstimate(
            status="unavailable",
            reason="no current meal: nothing to predict",
            probability=None,
            threshold=None,
            above_threshold=None,
            features_at=None,
            model_inputs=None,
            uncertainty=None,
        )
    )

    used_ts = [
        x for x in (now_src, scored.max_src if scored else None) if x is not None and not pd.isna(x)
    ]
    closed_used = closed[closed["frozen_usable"]]
    if not closed_used.empty:
        used_ts.append(closed_used["window_closed_at"].max())
    max_src = max(pd.Timestamp(x) for x in used_ts) if used_ts else None
    if max_src is not None and max_src > t:
        raise FutureDataError(f"a value used data from {max_src}, after as_of {t}")

    body: dict[str, Any] = dict(
        schema_version=cfg.twin.state_schema,
        patient_id=r.patient_id,
        as_of=t.isoformat(),
        lifecycle=lifecycle(
            n_closed, personal_now["personal_weight"] if personal_now else None, prior, runtime
        ),
        static_clinical=StaticClinical(glycemic_group=r.glycemic_group, fields=clinical),
        personal_baselines=PersonalBaselines(
            overnight_glucose_mgdl=f["g_overnight_baseline"],
            resting_hr_bpm=f["hr_resting"],
            time_in_range_24h=f["tir_24h"],
        ),
        current_physiology=CurrentPhysiology(
            glucose_mgdl=f["g_last"],
            glucose_age_min=f["g_age_min"],
            slope_15_mgdl_per_min=f["slope_15"],
            slope_30_mgdl_per_min=f["slope_30"],
            sd_60_mgdl=f["sd_60"],
            glucose_vs_baseline_mgdl=f["g_vs_baseline"],
            hr_30_bpm=f["hr_30"],
            hr_delta_bpm=f["hr_delta"],
            mets_60=f["mets_60"],
            active_min_3h=f["active_min_3h"],
            activity_kcal_60=f["activity_kcal_60"],
        ),
        recent_history=RecentHistory(
            glucose_mean_180_mgdl=f["mean_180"],
            glucose_min_180_mgdl=f["min_180"],
            glucose_max_180_mgdl=f["max_180"],
            carbs_prev_3h_g=f["carbs_prev_3h"],
            mins_since_previous_meal=f["mins_since_meal"],
            meals_logged_24h=int(len(day)),
            meals_logged_total=int(len(r.meals)),
            recent_closed_meals=recent,
        ),
        current_meal=current,
        personal_response=personal_resp,
        risk=risk,
        freshness=Freshness(
            last_cgm_native_at=_ts(last_cgm),
            cgm_age_min=cgm_age,
            cgm_stale=cgm_age is None or cgm_age > fr.cgm_stale_after_min,
            last_wearable_at=_ts(last_wear),
            wearable_age_min=wear_age,
            wearable_stale=wear_age is None or wear_age > fr.wearable_stale_after_min,
            last_meal_at=_ts(r.meals["started_at"].max()) if len(r.meals) else None,
        ),
        provenance=Provenance(
            source=r.source,
            record_sha256=r.content_sha256(),
            cgm_native_readings_used=int(len(native)),
            wearable_minutes_used=int(len(r.wearable)),
            meals_logged_used=int(len(r.meals)),
            closed_meal_ids_used=[str(x) for x in closed_used["meal_id"]],
            current_meal_id=None if ctx is None else ctx.meal_id,
            max_source_ts=_ts(max_src),
            config_sha256=dict(cfg.hashes),
            engine_version=ENGINE_VERSION,
            model=None if runtime.model is None else identity(runtime.model),
        ),
        disclaimer=DISCLAIMER,
    )
    draft = TwinState(state_id="", **body)
    state = draft.model_copy(update={"state_id": _state_id(draft.canonical())})
    return Built(state, prep, ctx, scored)


def build_state(
    patient_id: int,
    as_of: Any,
    *,
    source: RecordSource,
    runtime: TwinRuntime,
    current_meal: MealInput | None = None,
    current_meal_id: str | None = None,
) -> TwinState:
    """The twin's state for ``patient_id`` at ``as_of`` (pure; see the module docstring)."""
    return build(
        patient_id,
        as_of,
        source=source,
        runtime=runtime,
        current_meal=current_meal,
        current_meal_id=current_meal_id,
    ).state
