"""Feature definitions and the past-only guarantees."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent))
from history_factory import T0, history, meal, ts  # noqa: E402
from twin_core.config import FeatureConfig, load_feature_config  # noqa: E402
from twin_core.features import meal_features  # noqa: E402

REPO = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def fcfg() -> FeatureConfig:
    return load_feature_config(REPO / "data/configs/features.v1.yaml")[0]


def feats(h, m, fcfg):  # type: ignore[no-untyped-def]
    f, src = meal_features(h, m, fcfg)
    assert np.isnat(src) or src <= m.started_at  # L2 holds for every call in this file
    return f


def test_feature_names_match_config(fcfg: FeatureConfig) -> None:
    f = feats(history(), meal(), fcfg)
    assert list(f) == list(fcfg.features.all())


def test_g_last_lookback_and_reading_at_t0(fcfg: FeatureConfig) -> None:
    at_t0 = feats(history(cgm={-30: 100.0, 0: 150.0, 5: 999.0}), meal(0), fcfg)
    assert at_t0["g_last"] == 150.0 and at_t0["g_age_min"] == 0.0  # 5 min AFTER t0 is never read
    stale = feats(history(cgm={-16: 100.0}), meal(0), fcfg)
    assert np.isnan(stale["g_last"]) and stale["g_age_min"] == 16.0


def test_slopes_use_native_readings_in_window(fcfg: FeatureConfig) -> None:
    cgm = {m: 100.0 + 2.0 * (m + 60) / 5 for m in range(-60, 1, 5)}  # rises 0.4 mg/dL per minute
    cgm[5] = 500.0  # a future reading must not change the slope
    f = feats(history(cgm=cgm), meal(0), fcfg)
    assert f["slope_15"] == pytest.approx(0.4) and f["slope_30"] == pytest.approx(0.4)
    too_few = feats(history(cgm={-5: 100.0, 0: 101.0}), meal(0), fcfg)
    assert np.isnan(too_few["slope_15"])


def test_180_min_stats_need_half_the_expected_readings(fcfg: FeatureConfig) -> None:
    seventeen = {m: 120.0 for m in range(-170, 1, 10)}  # 18 readings
    assert not np.isnan(feats(history(cgm=seventeen), meal(0), fcfg)["mean_180"])
    fewer = {m: 120.0 for m in range(-160, 1, 10)}  # 17 readings < 18
    assert np.isnan(feats(history(cgm=fewer), meal(0), fcfg)["mean_180"])


def test_overnight_baseline_uses_completed_nights_only(fcfg: FeatureConfig) -> None:
    # readings only in tonight's 02:00-06:00 window (T0 is 12:00, so "tonight" is day T0 at 02-06)
    night = {m: 90.0 for m in range(-600, -360, 5)}  # 02:00-06:00 on the meal's day
    early = feats(history(cgm=night), meal(-420), fcfg)  # meal at 05:00: night not finished
    after = feats(history(cgm=night), meal(-360), fcfg)  # meal at 06:00: night complete
    assert np.isnan(early["g_overnight_baseline"])
    assert after["g_overnight_baseline"] == 90.0


def test_wearable_windows_end_before_t0(fcfg: FeatureConfig) -> None:
    hr = np.full(len(np.arange(-3 * 1440, 61)), 70.0)
    hr[3 * 1440] = 200.0  # the minute AT t0
    f = feats(history(hr=hr), meal(0), fcfg)
    assert f["hr_30"] == 70.0


def test_resting_hr_uses_previous_days_and_missing_mets_is_unknown(fcfg: FeatureConfig) -> None:
    with_mets = feats(history(hr=70.0, mets=1.2), meal(0), fcfg)
    assert with_mets["hr_resting"] == 70.0 and with_mets["mets_60"] == pytest.approx(1.2)
    no_mets = feats(history(mets=None), meal(0), fcfg)
    assert no_mets["mets_available"] == 0.0
    assert np.isnan(no_mets["mets_60"]) and np.isnan(no_mets["active_min_3h"])  # unknown, not 0
    assert no_mets["hr_resting"] == 70.0  # falls back to overnight minutes of previous days
    first_day = feats(history(wear_minutes=(-600, 60)), meal(0), fcfg)
    assert np.isnan(first_day["hr_resting"])


def test_previous_meals_window_and_invalid_macros(fcfg: FeatureConfig) -> None:
    h = history(
        meals=[
            (-200, 50.0, True, 1),
            (-150, 40.0, True, 0),
            (-60, 999.0, False, 1),
            (0, 70.0, True, 0),
        ]
    )
    f = feats(h, meal(0), fcfg)
    assert f["carbs_prev_3h"] == 40.0  # -200 is outside 3 h; invalid meal is not summed
    assert f["invalid_meal_prev_3h"] == 1.0
    assert f["mins_since_meal"] == 60.0  # the meal at t0 itself is not "previous"
    assert np.isnan(feats(h, meal(0, valid=False), fcfg)["carbs_g"])


def test_personal_counts_only_closed_windows(fcfg: FeatureConfig) -> None:
    h = history(meals=[(-240, 50.0, True, 1), (-120, 50.0, True, 0), (-119, 50.0, True, 1)])
    f = feats(h, meal(0), fcfg)
    # -240 and -120 have closed (end <= t0); -119 closes 1 minute after t0
    assert f["n_closed_meals"] == 2.0 and f["n_closed_positive"] == 1.0


def test_meal_type_and_time_encoding(fcfg: FeatureConfig) -> None:
    f = feats(history(), meal(0, meal_type="snack"), fcfg)
    assert (f["meal_snack"], f["meal_lunch"]) == (1.0, 0.0)
    assert f["hour_sin"] == pytest.approx(0.0, abs=1e-12) and f["hour_cos"] == pytest.approx(-1.0)
    other = feats(history(), meal(0, meal_type="other"), fcfg)
    assert sum(other[f"meal_{t}"] for t in ("breakfast", "lunch", "dinner", "snack")) == 0.0


def test_homa_ir(fcfg: FeatureConfig) -> None:
    assert feats(history(), meal(0), fcfg)["homa_ir"] == pytest.approx(100 * 8.1 / 405)


# --- future invariance ------------------------------------------------------------------------
def random_history(rng: np.random.Generator):  # type: ignore[no-untyped-def]
    cgm_minutes = np.arange(-3 * 1440, 1440, 5)
    keep = rng.random(len(cgm_minutes)) > 0.1  # 10% of readings missing
    cgm = {
        int(m): float(v)
        for m, v in zip(
            cgm_minutes[keep], np.round(130 + rng.normal(0, 25, keep.sum())), strict=True
        )
    }
    n = len(np.arange(-3 * 1440, 1441))
    hr = 70 + rng.normal(0, 5, n)
    hr[rng.random(n) < 0.1] = np.nan
    mets = rng.choice([np.nan, 1.0, 1.2, 3.5], n) if rng.random() > 0.3 else None
    meal_minutes = np.sort(rng.choice(np.arange(-3 * 1440, 1440, 15), 20, replace=False))
    meals = [
        (
            int(m),
            float(rng.integers(0, 120)),
            bool(rng.random() > 0.1),
            float(rng.integers(0, 2)) if rng.random() > 0.2 else np.nan,
        )
        for m in meal_minutes
    ]
    return history(cgm=cgm, wear_minutes=(-3 * 1440, 1440), hr=hr, mets=mets, meals=meals), meals


def test_future_invariance_randomized(fcfg: FeatureConfig) -> None:
    """Features at t0 are identical whether the history ends at t0 or continues for a day."""
    rng = np.random.default_rng(7)
    checked = 0
    for _ in range(40):
        h, meals = random_history(rng)
        for minute, carbs, valid, _label in meals[::3]:
            m = meal(minute, carbs=carbs, valid=valid)
            full = feats(h, m, fcfg)
            cut = feats(h.truncate(m.started_at), m, fcfg)
            assert full.keys() == cut.keys()
            for k in full:
                assert (np.isnan(full[k]) and np.isnan(cut[k])) or full[k] == pytest.approx(
                    cut[k]
                ), k
            checked += 1
    assert checked > 100


def test_truncate_hides_unclosed_outcomes() -> None:
    h = history(meals=[(-60, 50.0, True, 1.0), (-200, 50.0, True, 0.0)])
    cut = h.truncate(ts([0])[0])
    assert np.isnan(cut.outcome_label[1])  # meal at -60 closes at +60: unknown at t0
    assert cut.outcome_label[0] == 0.0  # meal at -200 closed at -80


_ = T0
