"""Row-level time-series rules: duplicate timestamps and gap detection. Nothing is ever filled in."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class DuplicateStats:
    duplicated_timestamps: int  # timestamps appearing more than once
    identical_groups: int  # all value columns agree -> collapsed to one row
    conflicting_groups: int  # some value column disagrees -> that column nulled for the minute
    rows_removed: int


def collapse_duplicates(
    frame: pd.DataFrame, ts_col: str, value_cols: list[str]
) -> tuple[pd.DataFrame, pd.Series, DuplicateStats]:
    """Keep one row per timestamp.

    Returns the collapsed frame (sorted by time, index reset), a boolean Series marking minutes whose
    values conflicted, and counts. NaN compares equal to NaN when deciding whether rows are identical.
    """
    ordered = frame.sort_values(ts_col, kind="stable").reset_index(drop=True)
    dup_mask = ordered.duplicated(ts_col, keep=False)
    if not dup_mask.any():
        out = ordered.copy()
        return out, pd.Series(False, index=out.index), DuplicateStats(0, 0, 0, 0)

    dups = ordered.loc[dup_mask, [ts_col, *value_cols]]
    varying = dups.groupby(ts_col)[value_cols].nunique(dropna=False) > 1
    conflicting_ts = varying.index[varying.any(axis=1)]

    out = ordered.drop_duplicates(ts_col, keep="first").reset_index(drop=True)
    conflict = out[ts_col].isin(conflicting_ts)
    for col in value_cols:
        bad_ts = varying.index[varying[col]]
        if len(bad_ts):
            out.loc[out[ts_col].isin(bad_ts), col] = np.nan
    n_dup_ts = int(dups[ts_col].nunique())
    stats = DuplicateStats(
        duplicated_timestamps=n_dup_ts,
        identical_groups=n_dup_ts - len(conflicting_ts),
        conflicting_groups=len(conflicting_ts),
        rows_removed=len(ordered) - len(out),
    )
    return out, conflict.rename("duplicate_conflict"), stats


def gap_steps(ts: pd.Series, gap_flag_min: int) -> pd.Series:
    """Minutes between consecutive rows, for steps longer than ``gap_flag_min`` (sorted input)."""
    step = ts.diff().dt.total_seconds().div(60)
    return step[step > gap_flag_min]
