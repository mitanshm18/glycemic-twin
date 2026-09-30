"""The raw observations the twin is allowed to see for one person, and how they are cut at as_of.

A ``PatientRecord`` holds cleaned observations in the M1 table shapes (never interpolated values as
native readings: the ``dexcom_is_native`` flag is kept and only native readings feed features).
``record.as_of(t)`` is the record as it existed at ``t``: every observation with a timestamp after
``t`` is removed. Everything the engine computes starts from that cut, so future data cannot leak.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol

import numpy as np
import pandas as pd

from twin_core.features import as_ns

CGM_COLUMNS = ("ts", "dexcom_mgdl", "dexcom_is_native")
WEARABLE_COLUMNS = ("ts", "hr_bpm", "mets", "activity_kcal")
MEAL_COLUMNS = (
    "meal_id",
    "started_at",
    "meal_type",
    "carbs_g",
    "protein_g",
    "fat_g",
    "fiber_g",
    "calories_kcal",
    "macro_validity",
)
# The same clinical inputs, in the same encoding, as twin_ml.dataset.build.clinical_for (a test in
# ml/tests asserts both give identical values).
CLINICAL_OBSERVED = (
    "hba1c_pct",
    "fasting_glucose_mgdl",
    "fasting_insulin_uu_ml",
    "bmi",
    "age_years",
    "triglycerides_mgdl",
    "hdl_mgdl",
)
CLINICAL_KEYS = (*CLINICAL_OBSERVED, "sex_female")


def clinical_from_row(row: Mapping[str, object]) -> dict[str, float]:
    """bio.csv-derived clinical values: observed fields as floats, sex encoded F=1, M=0."""
    out = {k: float(row[k]) if pd.notna(row[k]) else float("nan") for k in CLINICAL_OBSERVED}  # type: ignore[arg-type]
    sex = str(row["sex"]).strip().upper() if pd.notna(row.get("sex")) else ""
    out["sex_female"] = 1.0 if sex == "F" else 0.0 if sex == "M" else float("nan")
    return out


def _frame(df: pd.DataFrame, cols: tuple[str, ...], sort: list[str], name: str) -> pd.DataFrame:
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ValueError(f"{name} is missing columns {missing}")
    out = df.loc[:, list(cols)].copy()
    ts_col = sort[0]
    out[ts_col] = pd.to_datetime(out[ts_col])
    return out.sort_values(sort, kind="stable").reset_index(drop=True)


@dataclass(frozen=True, eq=False)
class PatientRecord:
    patient_id: int
    clinical: Mapping[str, float]
    cgm: pd.DataFrame
    wearable: pd.DataFrame
    meals: pd.DataFrame
    glycemic_group: str | None = None
    source: str = "unspecified"
    _checked: bool = field(default=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._checked:
            return
        object.__setattr__(self, "cgm", _frame(self.cgm, CGM_COLUMNS, ["ts"], "cgm"))
        object.__setattr__(
            self, "wearable", _frame(self.wearable, WEARABLE_COLUMNS, ["ts"], "wearable")
        )
        meals = _frame(self.meals, MEAL_COLUMNS, ["started_at", "meal_id"], "meals")
        if meals["meal_id"].duplicated().any():
            raise ValueError("meal_id must be unique within a record")
        object.__setattr__(self, "meals", meals)
        missing = [k for k in CLINICAL_KEYS if k not in self.clinical]
        if missing:
            raise ValueError(f"clinical values missing: {missing}")
        object.__setattr__(self, "clinical", {k: float(self.clinical[k]) for k in CLINICAL_KEYS})
        object.__setattr__(self, "_checked", True)

    def as_of(self, t: object) -> PatientRecord:
        """The record as it existed at ``t``: nothing timestamped after ``t`` survives."""
        c = pd.Timestamp(as_ns(t))
        return PatientRecord(
            patient_id=self.patient_id,
            clinical=self.clinical,
            cgm=self.cgm[self.cgm["ts"] <= c].reset_index(drop=True),
            wearable=self.wearable[self.wearable["ts"] <= c].reset_index(drop=True),
            meals=self.meals[self.meals["started_at"] <= c].reset_index(drop=True),
            glycemic_group=self.glycemic_group,
            source=self.source,
            _checked=True,
        )

    def content_sha256(self) -> str:
        """Hash of every observation in the record (identifies exactly what a state was built from)."""
        h = hashlib.sha256()
        h.update(
            json.dumps(
                {
                    "patient_id": self.patient_id,
                    "clinical": {k: repr(v) for k, v in self.clinical.items()},
                    "group": self.glycemic_group,
                    "source": self.source,
                },
                sort_keys=True,
            ).encode()
        )
        for df in (self.cgm, self.wearable, self.meals):
            h.update(json.dumps(list(df.columns)).encode())
            h.update(pd.util.hash_pandas_object(df, index=False).to_numpy().tobytes())
        return h.hexdigest()

    @classmethod
    def from_m1_tables(
        cls, tables: Mapping[str, pd.DataFrame], patient_id: int, source: str
    ) -> PatientRecord:
        """One person's record from the M1 clean tables (cgm, wearable, meals, clinical_wide)."""
        pid = int(patient_id)

        def mine(t: str) -> pd.DataFrame:
            df = tables[t]
            return df[df["participant_id"] == pid]

        clin = tables["clinical_wide"].set_index("subject_id").loc[pid]
        group = clin.get("glycemic_group") if hasattr(clin, "get") else None
        return cls(
            patient_id=pid,
            clinical=clinical_from_row(clin.to_dict()),
            cgm=mine("cgm"),
            wearable=mine("wearable"),
            meals=mine("meals"),
            glycemic_group=None if group is None or pd.isna(group) else str(group),
            source=source,
        )


class RecordSource(Protocol):
    """Where records come from (in memory now; a database adapter in M5)."""

    def record(self, patient_id: int) -> PatientRecord: ...


@dataclass(frozen=True)
class InMemorySource:
    records: Mapping[int, PatientRecord]

    def record(self, patient_id: int) -> PatientRecord:
        if patient_id not in self.records:
            raise KeyError(f"unknown patient {patient_id}")
        return self.records[patient_id]


def native_readings(cgm: pd.DataFrame) -> pd.DataFrame:
    return cgm[cgm["dexcom_is_native"].astype(bool) & cgm["dexcom_mgdl"].notna()]


def last_ts(values: pd.Series) -> pd.Timestamp | None:
    return None if values.empty else pd.Timestamp(values.max())


def finite_or_none(x: object) -> float | None:
    try:
        v = float(x)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return v if np.isfinite(v) else None
