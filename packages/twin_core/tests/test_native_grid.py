"""Native CGM grid detection: the rule that keeps interpolated (partly future) values out of features."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from twin_core.cleaning.cgm import detect_native_grid, out_of_range_mask
from twin_core.config import CleaningConfig

T0 = pd.Timestamp("2021-06-01 00:00")  # minute index 0 has phase 0 (1440 is divisible by 5)


def interpolated_series(
    n: int, phase: int, period: int = 5, seed: int = 0
) -> tuple[pd.Series, pd.Series, np.ndarray]:
    """Integer 'device' readings on minutes = phase (mod period), linear interpolation in between."""
    rng = np.random.default_rng(seed)
    idx = np.arange(n)
    native_idx = idx[idx % period == phase]
    native_vals = np.round(120 + np.cumsum(rng.normal(0, 3, len(native_idx))))
    vals = np.interp(idx, native_idx, native_vals, left=np.nan, right=np.nan)
    ts = pd.Series(T0 + pd.to_timedelta(idx, unit="min"))
    truth = np.isin(idx, native_idx)
    return ts, pd.Series(vals), truth


def test_detects_phase_and_marks_exactly_the_device_readings(ccfg: CleaningConfig) -> None:
    ts, vals, truth = interpolated_series(1440, phase=2)
    result, mask = detect_native_grid(ts, vals, 5, ccfg.cgm.native_grid, "dexcom")
    assert result.decision == "native_lattice"
    assert result.phases == (2,)
    assert np.array_equal(mask, truth & vals.notna().to_numpy())
    assert result.linear_share == pytest.approx(1.0)


def test_phase_can_change_across_a_sensor_gap(ccfg: CleaningConfig) -> None:
    ts1, v1, _ = interpolated_series(720, phase=1, seed=1)
    ts2, v2, _ = interpolated_series(720, phase=3, seed=2)
    ts2 = ts2 + pd.Timedelta(minutes=720 + 180)  # 3-hour gap, like a sensor warm-up
    ts = pd.concat([ts1, ts2], ignore_index=True)
    vals = pd.concat([v1, v2], ignore_index=True)
    result, _ = detect_native_grid(ts, vals, 5, ccfg.cgm.native_grid, "dexcom")
    assert result.decision == "native_lattice"
    # 720 + 180 = 900 minutes shift keeps absolute phase: (index + 900) % 5 == index % 5
    assert result.phases == (1, 3)


def test_non_linear_non_integer_data_is_undetermined(ccfg: CleaningConfig) -> None:
    rng = np.random.default_rng(3)
    ts = pd.Series(T0 + pd.to_timedelta(np.arange(600), unit="min"))
    vals = pd.Series(120 + rng.normal(0, 5, 600))  # smooth-ish fractions everywhere, no lattice
    result, mask = detect_native_grid(ts, vals, 5, ccfg.cgm.native_grid, "dexcom")
    assert result.decision == "undetermined"
    assert result.segments[0].status == "no_integer_phase"
    assert not mask.any()


def test_all_integer_minutes_are_ambiguous_not_native(ccfg: CleaningConfig) -> None:
    ts = pd.Series(T0 + pd.to_timedelta(np.arange(600), unit="min"))
    vals = pd.Series(np.round(120 + np.arange(600) % 17, 0))  # integers on every phase
    result, mask = detect_native_grid(ts, vals, 5, ccfg.cgm.native_grid, "dexcom")
    assert result.segments[0].status == "ambiguous"
    assert result.decision == "undetermined"
    assert not mask.any()


def test_short_segment_is_not_decided(ccfg: CleaningConfig) -> None:
    ts, vals, _ = interpolated_series(60, phase=0)
    result, mask = detect_native_grid(ts, vals, 5, ccfg.cgm.native_grid, "dexcom")
    assert result.segments[0].status == "too_short"
    assert not mask.any()


def test_missing_device_reading_bridged_by_interpolation_is_counted(ccfg: CleaningConfig) -> None:
    ts, vals, _ = interpolated_series(1440, phase=0)
    idx = np.arange(1440)
    native_idx = idx[idx % 5 == 0]
    native_vals = vals.to_numpy()[native_idx].copy()
    drop = native_idx[100]
    keep = native_idx != drop
    bridged = pd.Series(np.interp(idx, native_idx[keep], native_vals[keep]))
    bridged.iloc[drop] += 0.25  # midpoint is k or k+0.5, so +0.25 is always fractional
    result, mask = detect_native_grid(ts, bridged, 5, ccfg.cgm.native_grid, "dexcom")
    assert result.decision == "native_lattice"
    assert result.segments[0].n_lattice_non_integer >= 1
    assert not mask[drop]


def test_requires_sorted_unique_timestamps(ccfg: CleaningConfig) -> None:
    ts, vals, _ = interpolated_series(300, phase=0)
    with pytest.raises(ValueError):
        detect_native_grid(ts[::-1].reset_index(drop=True), vals, 5, ccfg.cgm.native_grid, "x")


def test_no_values_gives_no_data(ccfg: CleaningConfig) -> None:
    ts = pd.Series(T0 + pd.to_timedelta(np.arange(10), unit="min"))
    result, mask = detect_native_grid(ts, pd.Series([np.nan] * 10), 5, ccfg.cgm.native_grid, "x")
    assert result.decision == "no_data" and not mask.any()


def test_range_rule_is_inclusive_and_ignores_missing() -> None:
    s = pd.Series([39.0, 40.0, 400.0, 401.0, np.nan])
    assert out_of_range_mask(s, (40, 400)).tolist() == [True, False, False, True, False]
