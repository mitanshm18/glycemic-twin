"""CGM cleaning: sensor-range validity and native-reading detection.

Why native detection exists
---------------------------
CGMacros stores Dexcom (native every 5 min) and Libre (native every 15 min) at one row per minute.
The minutes between native readings are interpolated. An interpolated value just before a meal is
partly built from a reading taken *after* the meal started, so using it as a feature would leak the
future. We therefore identify which minute rows hold real device readings.

How it is decided (data-driven, per sensor and per segment)
-----------------------------------------------------------
Devices log whole numbers; interpolation mostly produces fractions. Split the series into segments at
gaps longer than ``segment_gap_min`` (a sensor change always leaves a gap, and the phase may change).
In each segment, group values by ``minute mod period`` (the *phase*). The native lattice is the phase
whose values are almost all integers (>= ``min_integer_share``) while no other phase comes close
(<= ``max_other_phase_integer_share``). Integer values on that phase are marked native.

Independent check: if interpolation is linear, every minute between two native readings lies on the
straight line joining them. The share of native-to-native intervals that pass this is reported; it is
evidence about the interpolation method, not an input to the decision.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

from twin_core.config import NativeGridConfig

Decision = Literal["native_lattice", "partial", "undetermined", "no_data"]

_INT_TOL = 1e-6


def out_of_range_mask(values: pd.Series, valid_range: tuple[float, float]) -> pd.Series:
    """True where a present value lies outside the valid range. Missing values are not flagged."""
    lo, hi = valid_range
    return values.notna() & ((values < lo) | (values > hi))


@dataclass(frozen=True)
class SegmentGrid:
    start_minute: int
    end_minute: int
    n_values: int
    integer_share_by_phase: tuple[float, ...]
    phase: int | None
    status: Literal["accepted", "ambiguous", "no_integer_phase", "too_short"]
    n_native: int
    n_lattice_non_integer: (
        int  # lattice positions holding a fractional value (missing native, bridged)
    )
    n_intervals_checked: int
    n_intervals_linear: int


@dataclass(frozen=True)
class GridResult:
    sensor: str
    period_min: int
    decision: Decision
    segments: tuple[SegmentGrid, ...]
    n_values: int
    n_native: int

    @property
    def linear_share(self) -> float | None:
        checked = sum(s.n_intervals_checked for s in self.segments)
        if checked == 0:
            return None
        return sum(s.n_intervals_linear for s in self.segments) / checked

    @property
    def phases(self) -> tuple[int | None, ...]:
        return tuple(s.phase for s in self.segments if s.status == "accepted")


def _to_minutes(ts: pd.Series) -> np.ndarray:
    return ts.to_numpy(dtype="datetime64[ns]").astype("datetime64[m]").astype(np.int64)


def _linearity(
    minutes: np.ndarray,
    values: np.ndarray,
    native_minutes: np.ndarray,
    native_values: np.ndarray,
    period: int,
    tol: float,
) -> tuple[int, int]:
    """Count native-to-native intervals (exactly one period apart, all minutes present) that are linear.

    ``minutes`` is sorted and unique with no missing values (present readings only), so an inner
    minute is present exactly when searchsorted finds it.
    """
    if len(native_minutes) < 2 or period < 2:
        return 0, 0
    pairs = np.flatnonzero(np.diff(native_minutes) == period)
    if len(pairs) == 0:
        return 0, 0
    k = np.arange(1, period)
    targets = native_minutes[pairs][:, None] + k[None, :]  # (pairs, period - 1)
    pos = np.clip(np.searchsorted(minutes, targets), 0, len(minutes) - 1)
    present = (minutes[pos] == targets).all(axis=1)
    v0 = native_values[pairs][:, None]
    v1 = native_values[pairs + 1][:, None]
    expected = v0 + (v1 - v0) * k[None, :] / period
    within = (np.abs(values[pos] - expected) <= tol).all(axis=1)
    return int(present.sum()), int((present & within).sum())


def detect_native_grid(
    ts: pd.Series,
    values: pd.Series,
    period_min: int,
    cfg: NativeGridConfig,
    sensor: str,
) -> tuple[GridResult, np.ndarray]:
    """Return the grid decision and a boolean mask (aligned to ``values``) of native readings.

    ``ts`` must be sorted ascending with unique timestamps.
    """
    if not ts.is_monotonic_increasing or ts.duplicated().any():
        raise ValueError("timestamps must be sorted and unique before native-grid detection")

    mask = np.zeros(len(values), dtype=bool)
    vals = values.to_numpy(dtype=float)
    present = ~np.isnan(vals)
    if not present.any():
        return GridResult(sensor, period_min, "no_data", (), 0, 0), mask

    minutes_all = _to_minutes(ts)
    pos = np.flatnonzero(present)
    minutes = minutes_all[pos]
    v = vals[pos]
    is_int = np.abs(v - np.round(v)) <= _INT_TOL

    breaks = np.flatnonzero(np.diff(minutes) > cfg.segment_gap_min) + 1
    bounds = np.split(np.arange(len(minutes)), breaks)

    segments: list[SegmentGrid] = []
    for idx in bounds:
        seg_min, seg_v, seg_int = minutes[idx], v[idx], is_int[idx]
        phases = seg_min % period_min
        shares = tuple(
            float(seg_int[phases == p].mean()) if (phases == p).any() else float("nan")
            for p in range(period_min)
        )
        n = len(idx)
        if n < cfg.min_points:
            segments.append(
                SegmentGrid(
                    int(seg_min[0]), int(seg_min[-1]), n, shares, None, "too_short", 0, 0, 0, 0
                )
            )
            continue
        finite = np.array([s if not np.isnan(s) else -1.0 for s in shares])
        best = int(np.argmax(finite))
        others = np.delete(finite, best)
        if finite[best] < cfg.min_integer_share:
            segments.append(
                SegmentGrid(
                    int(seg_min[0]),
                    int(seg_min[-1]),
                    n,
                    shares,
                    None,
                    "no_integer_phase",
                    0,
                    0,
                    0,
                    0,
                )
            )
            continue
        if (others > cfg.max_other_phase_integer_share).any():
            segments.append(
                SegmentGrid(
                    int(seg_min[0]), int(seg_min[-1]), n, shares, None, "ambiguous", 0, 0, 0, 0
                )
            )
            continue

        on_phase = phases == best
        native_local = on_phase & seg_int
        mask[pos[idx[native_local]]] = True
        checked, linear = _linearity(
            seg_min,
            seg_v,
            seg_min[native_local],
            seg_v[native_local],
            period_min,
            cfg.linearity_tolerance_mgdl,
        )
        segments.append(
            SegmentGrid(
                start_minute=int(seg_min[0]),
                end_minute=int(seg_min[-1]),
                n_values=n,
                integer_share_by_phase=shares,
                phase=best,
                status="accepted",
                n_native=int(native_local.sum()),
                n_lattice_non_integer=int((on_phase & ~seg_int).sum()),
                n_intervals_checked=checked,
                n_intervals_linear=linear,
            )
        )

    decided = [s for s in segments if s.status != "too_short"]
    accepted = [s for s in decided if s.status == "accepted"]
    decision: Decision
    if decided and len(accepted) == len(decided):
        decision = "native_lattice"
    elif accepted:
        decision = "partial"
    else:
        decision = "undetermined"
    result = GridResult(
        sensor=sensor,
        period_min=period_min,
        decision=decision,
        segments=tuple(segments),
        n_values=int(present.sum()),
        n_native=int(mask.sum()),
    )
    return result, mask
