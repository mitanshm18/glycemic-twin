"""Fitbit minute rules. Missing is unknown: nothing becomes 0 because a column or value is absent."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from twin_core.config import WearableConfig


@dataclass(frozen=True)
class WearableCleanStats:
    hr_out_of_range: int
    mets_out_of_range: int
    activity_kcal_negative: int
    mets_available: bool
    activity_kcal_available: bool


def clean_wearable(
    hr: pd.Series,
    mets_stored: pd.Series | None,
    activity_kcal: pd.Series | None,
    cfg: WearableConfig,
) -> tuple[pd.DataFrame, WearableCleanStats]:
    """Return hr_bpm, mets (already divided by the storage factor) and activity_kcal, plus counts.

    ``mets_stored`` / ``activity_kcal`` are None when the participant's file lacks that column;
    the output column is then all-NaN, never zeros.
    """
    index = hr.index
    lo, hi = cfg.hr_valid_range_bpm
    hr_bad = hr.notna() & ((hr < lo) | (hr > hi))
    hr_clean = hr.mask(hr_bad)

    if mets_stored is None:
        mets = pd.Series(float("nan"), index=index)
        mets_bad = pd.Series(False, index=index)
    else:
        mets = mets_stored / cfg.mets_scale_divisor
        mlo, mhi = cfg.mets_valid_range
        mets_bad = mets.notna() & ((mets < mlo) | (mets > mhi))
        mets = mets.mask(mets_bad)

    if activity_kcal is None:
        kcal = pd.Series(float("nan"), index=index)
        kcal_bad = pd.Series(False, index=index)
    else:
        kcal_bad = activity_kcal.notna() & (activity_kcal < cfg.activity_kcal_min)
        kcal = activity_kcal.mask(kcal_bad)

    out = pd.DataFrame(
        {
            "hr_bpm": hr_clean.astype(float),
            "mets": mets.astype(float),
            "activity_kcal": kcal.astype(float),
            "hr_out_of_range": hr_bad,
            "mets_out_of_range": mets_bad,
        },
        index=index,
    )
    stats = WearableCleanStats(
        hr_out_of_range=int(hr_bad.sum()),
        mets_out_of_range=int(mets_bad.sum()),
        activity_kcal_negative=int(kcal_bad.sum()),
        mets_available=mets_stored is not None,
        activity_kcal_available=activity_kcal is not None,
    )
    return out, stats
