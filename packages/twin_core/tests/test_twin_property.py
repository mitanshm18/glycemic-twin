"""Property tests for the Digital Twin (Hypothesis; runs where hypothesis is installed).
SYNTHETIC records and a stub model only."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

hypothesis = pytest.importorskip("hypothesis")
from hypothesis import given, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))
from twin_core.twin import PatientRecord, build_state  # noqa: E402
from twin_factory import START, make_record, runtime, source  # noqa: E402

REC = make_record(days=4)
RT = runtime()
MINUTES = 4 * 1440


def perturb_after(rec: PatientRecord, t: pd.Timestamp, seed: int) -> PatientRecord:
    rng = np.random.default_rng(seed)
    cgm = rec.cgm.copy()
    later = cgm["ts"] > t
    cgm.loc[later, "dexcom_mgdl"] = rng.uniform(40, 400, int(later.sum())).round()
    wear = rec.wearable.copy()
    wl = wear["ts"] > t
    wear.loc[wl, "mets"] = rng.uniform(1, 12, int(wl.sum()))
    meals = rec.meals.copy()
    ml = meals["started_at"] > t
    meals.loc[ml, "carbs_g"] = rng.uniform(0, 300, int(ml.sum()))
    return PatientRecord(
        rec.patient_id, rec.clinical, cgm, wear, meals, rec.glycemic_group, rec.source
    )


@settings(max_examples=25, deadline=None)
@given(minute=st.integers(0, MINUTES - 1), seed=st.integers(0, 10_000))
def test_future_observations_never_change_the_state(minute: int, seed: int) -> None:
    t = START + pd.Timedelta(minutes=minute)
    a = build_state(7, t, source=source(REC), runtime=RT)
    b = build_state(7, t, source=source(perturb_after(REC, t, seed)), runtime=RT)
    assert a == b


@settings(max_examples=15, deadline=None)
@given(minute=st.integers(0, MINUTES - 1))
def test_state_is_deterministic_and_bounded_by_as_of(minute: int) -> None:
    t = START + pd.Timedelta(minutes=minute)
    a = build_state(7, t, source=source(REC), runtime=RT)
    assert a == build_state(7, t, source=source(REC), runtime=RT)
    assert a.provenance.max_source_ts is None or pd.Timestamp(a.provenance.max_source_ts) <= t
    if a.risk.probability is not None:
        assert 0.0 <= a.risk.probability <= 1.0


@settings(max_examples=15, deadline=None)
@given(m1=st.integers(0, MINUTES - 1), m2=st.integers(0, MINUTES - 1))
def test_closed_evidence_only_grows_with_time(m1: int, m2: int) -> None:
    t1, t2 = sorted((START + pd.Timedelta(minutes=m1), START + pd.Timedelta(minutes=m2)))
    a = build_state(7, t1, source=source(REC), runtime=RT)
    b = build_state(7, t2, source=source(REC), runtime=RT)
    assert set(a.provenance.closed_meal_ids_used) <= set(b.provenance.closed_meal_ids_used)
    assert a.lifecycle.closed_usable_meals <= b.lifecycle.closed_usable_meals
