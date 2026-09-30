"""Property-based future invariance (runs where Hypothesis is installed, e.g. after `make setup`)."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

hypothesis = pytest.importorskip("hypothesis")
from hypothesis import given, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))
from history_factory import meal  # noqa: E402
from test_features import random_history  # noqa: E402
from twin_core.config import load_feature_config  # noqa: E402
from twin_core.features import meal_features  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
FCFG = load_feature_config(REPO / "data/configs/features.v1.yaml")[0]


@settings(max_examples=60, deadline=None)
@given(seed=st.integers(0, 10_000), pick=st.floats(0, 1))
def test_future_invariance_property(seed: int, pick: float) -> None:
    h, meals = random_history(np.random.default_rng(seed))
    minute, carbs, valid, _ = meals[int(pick * (len(meals) - 1))]
    m = meal(minute, carbs=carbs, valid=valid)
    full = meal_features(h, m, FCFG)[0]
    cut = meal_features(h.truncate(m.started_at), m, FCFG)[0]
    for k in full:
        assert (np.isnan(full[k]) and np.isnan(cut[k])) or np.isclose(full[k], cut[k]), k
