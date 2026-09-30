"""Frozen outcome rules: window boundaries, coverage, overlap, native-only pre-meal value."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from twin_core.config import LabelConfig
from twin_core.labels import WATERFALL, meal_outcomes

T0 = pd.Timestamp("2021-06-01 08:00")


def cgm_frame(
    values: dict[int, float],
    start: int = -60,
    end: int = 180,
    native_every: int = 5,
    default: float = 120.0,
) -> pd.DataFrame:
    """Minute rows from T0+start to T0+end; native readings on multiples of native_every."""
    offsets = np.arange(start, end + 1)
    vals = np.array([values.get(int(o), default) for o in offsets], dtype=float)
    return pd.DataFrame(
        {
            "ts": T0 + pd.to_timedelta(offsets, unit="min"),
            "dexcom_mgdl": vals,
            "dexcom_is_native": (offsets % native_every == 0),
        }
    )


def one_meal(offset: int = 0, validity: str = "valid", mid: str = "m1") -> pd.DataFrame:
    return pd.DataFrame(
        {
            "meal_id": [mid],
            "started_at": [T0 + pd.Timedelta(minutes=offset)],
            "macro_validity": [validity],
        }
    )


def run(cgm: pd.DataFrame, meals: pd.DataFrame, lcfg: LabelConfig) -> pd.DataFrame:
    return meal_outcomes(meals, cgm, lcfg).set_index("meal_id")


@pytest.mark.parametrize(("minute", "label"), [(0, 0), (1, 1), (120, 1), (121, 0)])
def test_window_is_open_at_t0_and_closed_at_horizon(
    minute: int, label: int, lcfg: LabelConfig
) -> None:
    out = run(cgm_frame({minute: 181.0}), one_meal(), lcfg)
    assert out.loc["m1", "label"] == label


def test_exactly_threshold_is_not_positive(lcfg: LabelConfig) -> None:
    assert run(cgm_frame({60: 180.0}), one_meal(), lcfg).loc["m1", "label"] == 0


def test_coverage_rule_uses_minute_rows(lcfg: LabelConfig) -> None:
    missing_24 = {m: np.nan for m in range(1, 25)}  # 96/120 = 0.80 -> usable
    missing_25 = {m: np.nan for m in range(1, 26)}  # 95/120 < 0.80 -> not usable
    a = run(cgm_frame(missing_24), one_meal(), lcfg).loc["m1"]
    b = run(cgm_frame(missing_25), one_meal(), lcfg).loc["m1"]
    assert a["window_coverage"] == pytest.approx(0.8) and a["frozen_usable"]
    assert b["low_cgm_coverage"] and not b["frozen_usable"] and pd.isna(b["label"])


def test_overlap_is_strictly_less_than_horizon(lcfg: LabelConfig) -> None:
    meals = pd.DataFrame(
        {
            "meal_id": ["a", "b", "c"],
            "started_at": [T0, T0 + pd.Timedelta(minutes=119), T0 + pd.Timedelta(minutes=239)],
            "macro_validity": ["valid"] * 3,
        }
    )
    out = run(cgm_frame({}, end=400), meals, lcfg)
    assert out.loc["a", "overlap_next_meal"]  # next meal 119 min later
    assert not out.loc["b", "overlap_next_meal"]  # next meal exactly 120 min later
    assert not out.loc["c", "overlap_next_meal"]  # last meal


def test_pre_meal_value_uses_native_readings_only(lcfg: LabelConfig) -> None:
    # t0 = 0 is a native minute; make it the only high value -> already high
    high_native = run(cgm_frame({0: 190.0}), one_meal(), lcfg).loc["m1"]
    assert high_native["already_high"] and high_native["pre_meal_native_mgdl"] == 190.0
    # meal at minute 2: minutes 1-2 are interpolated (and high); the last native (minute 0) is normal
    interp_high = run(cgm_frame({1: 190.0, 2: 190.0}), one_meal(offset=2), lcfg).loc["m1"]
    assert not interp_high["already_high"]
    assert (
        interp_high["pre_meal_native_mgdl"] == 120.0 and interp_high["pre_meal_native_age_min"] == 2
    )


def test_no_native_reading_within_lookback(lcfg: LabelConfig) -> None:
    cgm = cgm_frame({})
    cgm.loc[(cgm["ts"] > T0 - pd.Timedelta(minutes=20)) & (cgm["ts"] <= T0), "dexcom_is_native"] = (
        False
    )
    out = run(cgm, one_meal(), lcfg).loc["m1"]
    assert out["no_pre_meal_native"] and out["frozen_usable"] and not out["eligible"]


def test_eligibility_and_waterfall_order(lcfg: LabelConfig) -> None:
    out = run(cgm_frame({0: 200.0}), one_meal(validity="invalid"), lcfg).loc["m1"]
    assert out["frozen_usable"] and not out["eligible"]
    assert out["exclusion_reasons"] == "already_high;macro_excluded"
    assert out["waterfall_reason"] == "already_high"
    assert set(out["exclusion_reasons"].split(";")) <= set(WATERFALL)


def test_label_missing_for_unusable_meals_and_integer_otherwise(lcfg: LabelConfig) -> None:
    meals = pd.DataFrame(
        {
            "meal_id": ["a", "b"],
            "started_at": [T0, T0 + pd.Timedelta(minutes=30)],
            "macro_validity": ["valid", "valid"],
        }
    )
    out = run(cgm_frame({100: 200.0}, end=300), meals, lcfg)
    assert pd.isna(out.loc["a", "label"]) and out.loc["b", "label"] == 1
    assert str(out["label"].dtype) == "Int64"
