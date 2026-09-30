"""Training-support profile: the range of each model input seen in training.

Built once, offline, from the same M2 dataset the model bundle was trained on (its content hash
must equal the bundle's ``dataset_content_sha256``). Serving only reads it; it never recomputes
anything from serving data. Used to flag out-of-support inputs and to bound what-if scenarios.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict


class FeatureSupport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    lo: float
    hi: float
    min: float
    max: float
    n: int


class SupportProfile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    dataset_content_sha256: str
    quantiles: tuple[float, float]
    rows: int
    features: dict[str, FeatureSupport]

    def check(self, values: dict[str, float | None]) -> list[str]:
        """Names of features whose (non-missing) value lies outside [lo, hi]."""
        out = []
        for name, v in values.items():
            s = self.features.get(name)
            if s is None or v is None or not np.isfinite(v):
                continue
            if v < s.lo or v > s.hi:
                out.append(name)
        return out

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(self.model_dump(), indent=2, sort_keys=True) + "\n")

    @classmethod
    def load(cls, path: Path) -> SupportProfile:
        return cls.model_validate_json(path.read_text())


def build_support_profile(
    dataset: pd.DataFrame,
    columns: tuple[str, ...],
    quantiles: tuple[float, float],
    dataset_content_sha256: str,
) -> SupportProfile:
    """Per-feature [q_lo, q_hi] over the eligible (training) meals of the M2 dataset."""
    rows = dataset[dataset["eligible"].astype(bool)]
    feats = {}
    for c in columns:
        if c not in rows.columns:
            continue  # personal features are computed per fit, not stored in M2
        v = rows[c].to_numpy(dtype=float)
        v = v[np.isfinite(v)]
        if len(v) == 0:
            continue
        feats[c] = FeatureSupport(
            lo=float(np.quantile(v, quantiles[0])),
            hi=float(np.quantile(v, quantiles[1])),
            min=float(v.min()),
            max=float(v.max()),
            n=int(len(v)),
        )
    return SupportProfile(
        dataset_content_sha256=dataset_content_sha256,
        quantiles=quantiles,
        rows=int(len(rows)),
        features=feats,
    )
