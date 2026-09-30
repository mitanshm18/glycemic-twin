"""Digital Twin state (M4): determinism, as_of cutoff, no future leakage, lifecycle, provenance,
model-contract compatibility. SYNTHETIC records and a stub model only (twin_factory.py)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import ast
import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError
from twin_core.features import MealInput, as_ns
from twin_core.labels import meal_outcomes
from twin_core.twin import (
    STATE_SCHEMA,
    ModelContractError,
    PatientRecord,
    Phase,
    TwinRuntime,
    TwinState,
    build_state,
    diff_states,
)
from twin_core.twin.engine import build, prepare
from twin_factory import (  # noqa: E402
    CONFIGS,
    StubModel,
    empty_record,
    make_record,
    runtime,
    source,
    wide_support,
)

T = pd.Timestamp
LUNCH_DAY4 = T("2021-06-05 13:00")


def state(rec: PatientRecord, as_of: object, **kw: object) -> TwinState:
    return build_state(
        rec.patient_id, as_of, source=source(rec), runtime=kw.pop("rt", runtime()), **kw
    )  # type: ignore[arg-type]


def with_future(rec: PatientRecord, as_of: pd.Timestamp, seed: int = 1) -> PatientRecord:
    """The same record, but everything after as_of replaced by very different data."""
    rng = np.random.default_rng(seed)
    cgm = rec.cgm.copy()
    later = cgm["ts"] > as_of
    cgm.loc[later, "dexcom_mgdl"] = rng.uniform(250, 400, int(later.sum())).round()
    wear = rec.wearable.copy()
    wl = wear["ts"] > as_of
    wear.loc[wl, "hr_bpm"] = 150.0
    meals = rec.meals.copy()
    extra = meals.iloc[[0]].assign(
        meal_id="future-meal", started_at=as_of + pd.Timedelta(minutes=1), carbs_g=200.0
    )
    meals = pd.concat([meals, extra], ignore_index=True)
    return PatientRecord(
        rec.patient_id, rec.clinical, cgm, wear, meals, rec.glycemic_group, rec.source
    )


# ---------------------------------------------------------------- determinism and schema


def test_same_inputs_give_the_same_state_and_id() -> None:
    a = state(make_record(), LUNCH_DAY4 + pd.Timedelta(minutes=20))
    b = state(make_record(), LUNCH_DAY4 + pd.Timedelta(minutes=20))
    assert a == b and a.state_id == b.state_id and len(a.state_id) == 64
    assert a.schema_version == STATE_SCHEMA == "twin-state/1"
    json.dumps(a.model_dump(mode="json"), allow_nan=False)  # valid JSON, no NaN


def test_state_is_immutable_and_rejects_unknown_fields() -> None:
    s = state(make_record(), LUNCH_DAY4)
    with pytest.raises(ValidationError):
        s.patient_id = 99  # type: ignore[misc]
    data = s.model_dump()
    data["unexpected"] = 1
    with pytest.raises(ValidationError):
        TwinState.model_validate(data)


def test_state_id_changes_when_anything_changes() -> None:
    a = state(make_record(), LUNCH_DAY4 + pd.Timedelta(minutes=20))
    b = state(make_record(), LUNCH_DAY4 + pd.Timedelta(minutes=25))
    c = state(make_record(seed=3), LUNCH_DAY4 + pd.Timedelta(minutes=20))
    assert len({a.state_id, b.state_id, c.state_id}) == 3


def test_schema_has_every_required_section() -> None:
    props = TwinState.model_json_schema()["properties"]
    for key in (
        "static_clinical",
        "personal_baselines",
        "current_physiology",
        "recent_history",
        "current_meal",
        "personal_response",
        "risk",
        "lifecycle",
        "freshness",
        "provenance",
        "schema_version",
        "state_id",
        "as_of",
        "disclaimer",
    ):
        assert key in props, key


# ---------------------------------------------------------------- as_of and leakage


@pytest.mark.parametrize("minutes_after_lunch", [0, 20, 119, 120, 300])
def test_future_data_never_changes_a_state(minutes_after_lunch: int) -> None:
    rec = make_record()
    t = LUNCH_DAY4 + pd.Timedelta(minutes=minutes_after_lunch)
    assert state(rec, t) == state(with_future(rec, t), t)


def test_every_source_timestamp_is_at_or_before_as_of() -> None:
    rec = make_record()
    for t in pd.date_range("2021-06-01 06:00", "2021-06-06 23:00", freq="7h13min"):
        s = state(rec, t)
        assert s.provenance.max_source_ts is None or T(s.provenance.max_source_ts) <= t
        assert s.provenance.meals_logged_used == int((rec.meals["started_at"] <= t).sum())
        nat = rec.cgm[rec.cgm["dexcom_is_native"] & (rec.cgm["ts"] <= t)]
        assert s.provenance.cgm_native_readings_used == len(nat)
        for mid in s.provenance.closed_meal_ids_used:
            start = rec.meals.set_index("meal_id").loc[mid, "started_at"]
            assert start + pd.Timedelta(minutes=120) <= t


def test_interpolated_minutes_are_never_read_as_glucose() -> None:
    rec = make_record()
    t = LUNCH_DAY4 + pd.Timedelta(minutes=17)  # between native readings (5-min grid)
    s = state(rec, t)
    last_native = rec.cgm[rec.cgm["dexcom_is_native"] & (rec.cgm["ts"] <= t)].iloc[-1]
    assert s.current_physiology.glucose_mgdl == last_native["dexcom_mgdl"]
    assert s.current_physiology.glucose_age_min == 2.0


def test_closed_outcomes_from_the_cut_equal_full_data_outcomes() -> None:
    """Outcomes recomputed from the as_of cut match the full-data outcomes for closed windows."""
    rec = make_record()
    t = T("2021-06-04 10:07")
    prep = prepare(rec, t, CONFIGS)
    full = meal_outcomes(rec.meals, rec.cgm, CONFIGS.labels).set_index("meal_id")
    closed = prep.outcomes[prep.outcomes["window_closed"]].set_index("meal_id")
    assert len(closed) > 5
    assert (closed["frozen_usable"] == full.loc[closed.index, "frozen_usable"]).all()
    lab = closed["label"].astype(float).fillna(-1)
    assert (lab == full.loc[closed.index, "label"].astype(float).fillna(-1)).all()
    open_ = prep.outcomes[~prep.outcomes["window_closed"]]
    assert open_["label"].isna().all() and not open_["frozen_usable"].any()


def test_the_current_meal_outcome_is_never_used_for_its_own_state() -> None:
    rec = make_record()
    at_start = state(rec, LUNCH_DAY4, current_meal_id="7-4-13")
    after_close = state(rec, LUNCH_DAY4 + pd.Timedelta(hours=5), current_meal_id="7-4-13")
    assert after_close.risk.model_inputs == at_start.risk.model_inputs
    assert after_close.risk.probability == at_start.risk.probability
    assert "7-4-13" not in at_start.provenance.closed_meal_ids_used
    assert "7-4-13" in after_close.provenance.closed_meal_ids_used  # known later, as a PAST meal


def test_a_meal_after_as_of_cannot_be_the_current_meal() -> None:
    rec = make_record()
    with pytest.raises(ValueError, match="not in the record"):
        state(rec, LUNCH_DAY4 - pd.Timedelta(minutes=1), current_meal_id="7-4-13")


# ---------------------------------------------------------------- lifecycle


def test_empty_history_is_cold_start_with_population_values() -> None:
    rec = empty_record()
    s = state(rec, T("2021-06-01 12:00"))
    prior = StubModel().prior
    assert prior is not None
    assert s.lifecycle.phase is Phase.COLD_START and s.lifecycle.closed_usable_meals == 0
    assert s.personal_response is not None
    assert s.personal_response.p_personal == pytest.approx(prior.population_rate)
    assert s.personal_response.personal_weight == 0 and s.personal_response.rise_offset_mgdl == 0
    assert s.risk.status == "unavailable" and s.current_meal is None
    assert s.freshness.cgm_stale and s.freshness.last_cgm_native_at is None
    proposed = MealInput(as_ns(T("2021-06-01 12:00")), "lunch", 60, 20, 10, 5, 410, True)
    p = state(rec, T("2021-06-01 12:00"), current_meal=proposed)
    assert p.risk.status == "not_applicable" and "no native Dexcom" in (p.risk.reason or "")


def test_lifecycle_moves_cold_warming_personalized_and_never_back() -> None:
    rec = make_record()
    phases = [
        state(rec, t).lifecycle.phase
        for t in pd.date_range("2021-06-01 07:00", "2021-06-06 22:00", freq="3h")
    ]
    order = [Phase.COLD_START, Phase.WARMING, Phase.PERSONALIZED]
    idx = [order.index(p) for p in phases]
    assert idx == sorted(idx) and set(phases) == set(order)
    assert state(rec, T("2021-06-01 09:59")).lifecycle.phase is Phase.COLD_START  # window open
    assert state(rec, T("2021-06-01 10:00")).lifecycle.phase is Phase.WARMING  # first window closed


def test_personalization_warms_up_monotonically() -> None:
    rec = make_record()
    ws = [
        state(rec, t).personal_response.personal_weight  # type: ignore[union-attr]
        for t in pd.date_range("2021-06-01 07:00", "2021-06-06 22:00", freq="5h")
    ]
    assert ws[0] == 0 and all(b >= a for a, b in zip(ws, ws[1:], strict=False)) and ws[-1] > 0.8


def test_personalized_state_moves_toward_the_persons_own_rate() -> None:
    rec = make_record(base_glucose=150)  # this person goes above 180 after most meals
    s = state(rec, T("2021-06-06 23:00"))
    assert s.lifecycle.phase is Phase.PERSONALIZED
    pr = s.personal_response
    assert pr is not None and pr.closed_positive_meals / pr.closed_usable_meals > 0.8
    assert pr.p_personal > pr.population_rate + 0.2


def test_diff_explains_a_closed_window_and_a_phase_change() -> None:
    rec = make_record()
    a, b = state(rec, T("2021-06-01 09:59")), state(rec, T("2021-06-01 10:00"))
    d = diff_states(a, b)
    text = " ".join(d.explanations)
    assert "7-0-8" in text and "COLD_START -> WARMING" in text
    assert any(c.path == "lifecycle.phase" for c in d.changes)


# ---------------------------------------------------------------- risk, applicability, freshness


def test_risk_uses_exact_contract_columns_in_order() -> None:
    model = StubModel()
    s = state(make_record(), LUNCH_DAY4 + pd.Timedelta(minutes=5), rt=runtime(model))
    assert s.risk.status == "scored" and s.risk.probability is not None
    assert model.seen[-1] == list(CONFIGS.contract.columns(CONFIGS.features))
    assert list(s.risk.model_inputs or {}) == model.seen[-1] and len(model.seen[-1]) == 45
    assert not {"n_closed_meals", "n_closed_positive"} & set(model.seen[-1])
    assert s.provenance.model is not None and s.provenance.model.n_columns == 45


def test_meals_outside_the_training_population_are_not_scored() -> None:
    invalid = state(make_record(), T("2021-06-02 13:10"))  # day-1 lunch has invalid macros
    assert invalid.risk.status == "not_applicable" and "macros" in (invalid.risk.reason or "")
    high = state(make_record(high_start_meal=(3, 13)), T("2021-06-04 13:05"))
    assert high.current_meal is not None and not high.current_meal.applicable
    assert high.risk.status == "not_applicable" and "already above 180" in (high.risk.reason or "")


def test_no_model_gives_state_without_risk() -> None:
    s = state(make_record(), LUNCH_DAY4, rt=TwinRuntime(CONFIGS, None))
    assert s.risk.status == "unavailable" and s.personal_response is None
    assert s.lifecycle.phase is Phase.WARMING  # personal weight unknown without a prior


def test_freshness_flags_stale_inputs() -> None:
    rec = make_record(days=2)
    s = state(rec, T("2021-06-04 12:00"))
    assert s.freshness.cgm_stale and s.freshness.wearable_stale
    assert s.freshness.cgm_age_min and s.freshness.cgm_age_min > 1000


def test_proposed_meal_must_start_at_as_of() -> None:
    rec = make_record()
    meal = MealInput(as_ns(T("2021-06-05 17:00")), "snack", 30, 5, 5, 2, 185, True)
    with pytest.raises(ValueError, match="exactly at as_of"):
        state(rec, T("2021-06-05 17:05"), current_meal=meal)
    s = state(rec, T("2021-06-05 17:00"), current_meal=meal)
    assert s.current_meal is not None and s.current_meal.origin == "proposed"
    with pytest.raises(ValueError, match="either"):
        state(rec, T("2021-06-05 17:00"), current_meal=meal, current_meal_id="7-4-13")


# ---------------------------------------------------------------- model contract compatibility


@pytest.mark.parametrize(
    "change,match",
    [
        ({"columns": tuple(reversed(CONFIGS.contract.columns(CONFIGS.features)))}, "column list"),
        ({"contract_sha256": "0" * 64}, "contract hash"),
        ({"labels_sha256": "0" * 64}, "labels"),
        ({"features_sha256": "0" * 64}, "features"),
        ({"contract_version": 2}, "contract version"),
        ({"prior": None}, "PopulationPrior"),
        ({"feature_set": "everything"}, "unknown feature set"),
    ],
)
def test_incompatible_models_are_refused(change: dict[str, object], match: str) -> None:
    with pytest.raises(ModelContractError, match=match):
        TwinRuntime(CONFIGS, replace(StubModel(), **change))  # type: ignore[arg-type]


def test_objects_without_the_model_interface_are_refused() -> None:
    with pytest.raises(ModelContractError):
        TwinRuntime(CONFIGS, object())  # type: ignore[arg-type]


def test_support_profile_must_come_from_the_models_training_data() -> None:
    m = StubModel()
    bad = wide_support(m).model_copy(update={"dataset_content_sha256": "other"})
    with pytest.raises(ModelContractError, match="different training dataset"):
        TwinRuntime(CONFIGS, m, bad)


def test_ablation_feature_sets_are_served_with_their_own_columns() -> None:
    cols = CONFIGS.contract.columns(CONFIGS.features, "glucose_meal")
    m = replace(StubModel(), columns=cols, feature_set="glucose_meal", prior=None)
    m.predict_proba = lambda X: np.full(len(X), 0.4)  # type: ignore[method-assign]
    s = state(make_record(), LUNCH_DAY4 + pd.Timedelta(minutes=5), rt=TwinRuntime(CONFIGS, m))
    assert s.risk.status == "scored" and list(s.risk.model_inputs or {}) == list(cols)


# ---------------------------------------------------------------- independence


def test_twin_core_has_no_web_database_ui_or_ml_imports() -> None:
    forbidden = (
        "fastapi",
        "sqlalchemy",
        "starlette",
        "flask",
        "django",
        "psycopg",
        "react",
        "twin_ml",
        "sklearn",
        "xgboost",
        "joblib",
    )
    src = Path(__file__).resolve().parents[1] / "src/twin_core"
    for f in src.rglob("*.py"):
        tree = ast.parse(f.read_text())
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for n in names:
                assert n.split(".")[0] not in forbidden, f"{f.name} imports {n}"


def test_build_exposes_prepared_inputs_for_audit() -> None:
    b = build(
        7, LUNCH_DAY4 + pd.Timedelta(minutes=10), source=source(make_record()), runtime=runtime()
    )
    assert b.meal is not None and b.meal.meal_id == "7-4-13"
    assert b.prep.record.cgm["ts"].max() <= LUNCH_DAY4 + pd.Timedelta(minutes=10)


def test_published_json_schemas_match_the_code() -> None:
    """docs/schemas/*.json is the exact contract; changing the models means a new schema version."""
    from twin_core.twin.whatif import ScenarioResult

    docs = Path(__file__).resolve().parents[3] / "docs/schemas"
    for name, model in (("twin-state.v1", TwinState), ("twin-scenario.v1", ScenarioResult)):
        published = json.loads((docs / f"{name}.schema.json").read_text())
        assert published == json.loads(json.dumps(model.model_json_schema(), sort_keys=True)), name
