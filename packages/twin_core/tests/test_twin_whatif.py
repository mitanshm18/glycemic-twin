"""What-if engine (M4): bounded, non-causal, support-checked, refuses medication/treatment levers.
SYNTHETIC records and a stub model only (twin_factory.py)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd
import pytest
from twin_core.twin import DISCLAIMER, ScenarioError, TwinRuntime, simulate
from twin_factory import (  # noqa: E402
    CONFIGS,
    StubModel,
    make_record,
    runtime,
    source,
    wide_support,
)

AS_OF = pd.Timestamp("2021-06-05 13:20")  # 20 min into the day-4 lunch


def run(changes: dict[str, object], rec=None, rt=None, **kw):  # type: ignore[no-untyped-def]
    rec = rec or make_record()
    rt = rt or runtime(support=wide_support(StubModel()))
    return simulate(
        rec.patient_id, kw.pop("as_of", AS_OF), changes, source=source(rec), runtime=rt, **kw
    )


def test_carb_change_returns_a_delta_with_consistent_inputs() -> None:
    r = run({"carbs_g": -30})
    assert r.status == "ok" and r.scenario_probability is not None and r.risk_delta is not None
    assert r.risk_delta < 0  # the stub model's risk rises with carbs
    assert r.risk_delta == pytest.approx(r.scenario_probability - r.baseline_probability)
    changed = {c.feature: c for c in r.changed_inputs}
    assert set(changed) == {"carbs_g", "calories_kcal"}
    assert changed["carbs_g"].after == pytest.approx(changed["carbs_g"].before - 30)
    assert changed["calories_kcal"].after == pytest.approx(changed["calories_kcal"].before - 120)
    assert r.disclaimer == DISCLAIMER and "non-causal" in r.kind
    assert r.uncertainty is not None and r.model.n_columns == 45


@pytest.mark.parametrize("lever,delta", [("fiber_g", 3), ("protein_g", 10), ("fat_g", -5)])
def test_each_macro_lever_is_supported(lever: str, delta: float) -> None:
    r = run({lever: delta})
    assert r.status == "ok" and lever in {c.feature for c in r.changed_inputs}


def test_scenarios_are_deterministic_and_tied_to_the_base_state() -> None:
    a, b = run({"carbs_g": 10}), run({"carbs_g": 10})
    assert a == b and a.scenario_id == b.scenario_id
    assert run({"carbs_g": 11}).scenario_id != a.scenario_id


@pytest.mark.parametrize(
    "changes,match",
    [
        ({"insulin_units": 4}, "never simulates"),
        ({"Metformin_dose": 500}, "never simulates"),
        ({"medication": 1}, "never simulates"),
        ({"diagnosis": 1}, "never simulates"),
        ({"sugar": 10}, "not a supported lever"),
        ({}, "at least one"),
        ({"carbs_g": 101}, "exceeds"),
        ({"carbs_g": float("nan")}, "finite"),
        ({"carbs_g": "lots"}, "number"),
        ({"carbs_g": True}, "number"),
        ({"carbs_g": -500 / 5}, "negative"),
        ({"fiber_g": 29, "carbs_g": -80}, "fiber cannot exceed"),
    ],
)
def test_invalid_or_forbidden_scenarios_are_rejected(
    changes: dict[str, object], match: str
) -> None:
    rec = make_record()
    with pytest.raises(ScenarioError, match=match):
        run(changes, rec=rec)


def test_out_of_support_inputs_give_no_estimate() -> None:
    m = StubModel()
    rt = runtime(m, wide_support(m, carbs_g=(10.0, 100.0)))
    r = run({"carbs_g": 60}, rt=rt)
    assert r.status == "out_of_support" and r.scenario_probability is None and r.risk_delta is None
    assert not {c.feature: c for c in r.changed_inputs}["carbs_g"].in_support


def test_what_if_needs_model_and_support_profile() -> None:
    with pytest.raises(ScenarioError, match="support profile"):
        run({"carbs_g": 5}, rt=runtime(StubModel(), None))
    with pytest.raises(ScenarioError, match="model"):
        run({"carbs_g": 5}, rt=TwinRuntime(CONFIGS, None))


def test_what_if_needs_a_scorable_current_meal() -> None:
    with pytest.raises(ScenarioError, match="no current meal"):
        run({"carbs_g": 5}, as_of=pd.Timestamp("2021-06-05 11:00"))
    with pytest.raises(ScenarioError, match="not scorable"):
        run({"carbs_g": 5}, as_of=pd.Timestamp("2021-06-02 13:10"))  # invalid-macro lunch


def test_pre_meal_activity_only_when_mets_are_recorded() -> None:
    r = run({"active_min_3h": 30})
    assert r.status == "ok" and {c.feature for c in r.changed_inputs} == {"active_min_3h"}
    with pytest.raises(ScenarioError, match="no METs"):
        run({"active_min_3h": 30}, rec=make_record(with_mets=False))
    with pytest.raises(ScenarioError, match="within"):
        run({"active_min_3h": -100})


def test_personal_features_and_history_are_held_fixed() -> None:
    r = run({"carbs_g": 20, "fat_g": 10})
    assert not {"p_personal", "rise_offset_mgdl", "personal_weight", "g_last"} & {
        c.feature for c in r.changed_inputs
    }
    assert "personal features" in r.held_fixed
