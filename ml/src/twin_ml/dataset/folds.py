"""Participant-level folds, stratified by glycemic group, fixed before any training.

Every meal of a participant lands in the same fold, so no person is ever in both training and test.
The assignment is written to data/manifests/folds.v1.csv on the first run and verified on every
later run; changing it requires deleting the file deliberately (and saying why).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


class FoldError(RuntimeError):
    """Fold assignment differs from the pinned one, or is not participant-disjoint."""


def assign_folds(participants: pd.DataFrame, n_folds: int, seed: int) -> pd.DataFrame:
    """``participants``: participant_id, glycemic_group. Deterministic for a given seed.

    Within each group (sorted by name), participants are shuffled and dealt round-robin; the dealing
    continues across groups so fold sizes stay balanced overall as well as within each group.
    """
    rng = np.random.default_rng(seed)
    rows = []
    offset = 0
    for group in sorted(participants["glycemic_group"].unique()):
        ids = sorted(
            int(i)
            for i in participants.loc[
                participants["glycemic_group"] == group, "participant_id"
            ].unique()
        )
        for i, pid in enumerate(rng.permutation(ids)):
            rows.append((int(pid), group, (offset + i) % n_folds))
        offset = (offset + len(ids)) % n_folds
    out = pd.DataFrame(rows, columns=["participant_id", "glycemic_group", "fold"])
    return out.sort_values("participant_id").reset_index(drop=True)


def verify_or_pin_folds(folds: pd.DataFrame, path: Path) -> str:
    if path.exists():
        pinned = pd.read_csv(path).sort_values("participant_id").reset_index(drop=True)
        current = folds[["participant_id", "glycemic_group", "fold"]].reset_index(drop=True)
        if not pinned.equals(current.astype(pinned.dtypes.to_dict())):
            raise FoldError(f"fold assignment differs from pinned {path}")
        return "verified"
    path.parent.mkdir(parents=True, exist_ok=True)
    folds.to_csv(path, index=False)
    return "pinned"
