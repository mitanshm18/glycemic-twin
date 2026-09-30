"""Read access to patients and their observations, including the twin's ``RecordSource``.

``DbRecordSource.record(pid)`` rebuilds exactly the ``PatientRecord`` that twin_core expects, from
the database rows ingested from M1 (same columns, same meaning). The twin then cuts it at ``as_of``
itself; the API never pre-filters or pre-computes anything the engine owns.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from twin_core.twin import PatientRecord
from twin_core.twin.record import CLINICAL_OBSERVED, clinical_from_row

from twin_api.errors import patient_not_found
from twin_api.models import CgmReading, ClinicalObservation, Meal, Patient, WearableMinute


@dataclass(frozen=True)
class DataRange:
    first: datetime | None
    last: datetime | None


def get_patient(session: Session, pid: int) -> Patient:
    p = session.get(Patient, pid)
    if p is None:
        raise patient_not_found(pid)
    return p


def data_range(session: Session, pid: int) -> DataRange:
    lo = [
        session.scalar(select(func.min(CgmReading.ts)).where(CgmReading.patient_id == pid)),
        session.scalar(select(func.min(WearableMinute.ts)).where(WearableMinute.patient_id == pid)),
        session.scalar(select(func.min(Meal.started_at)).where(Meal.patient_id == pid)),
    ]
    hi = [
        session.scalar(select(func.max(CgmReading.ts)).where(CgmReading.patient_id == pid)),
        session.scalar(select(func.max(WearableMinute.ts)).where(WearableMinute.patient_id == pid)),
        session.scalar(select(func.max(Meal.started_at)).where(Meal.patient_id == pid)),
    ]
    los = [x for x in lo if x is not None]
    his = [x for x in hi if x is not None]
    return DataRange(min(los) if los else None, max(his) if his else None)


def _frame(rows: Sequence[Any], cols: list[str]) -> pd.DataFrame:
    return pd.DataFrame.from_records([tuple(r) for r in rows], columns=cols)


class DbRecordSource:
    """twin_core ``RecordSource`` backed by PostgreSQL (one session, read-only)."""

    def __init__(self, session: Session, source_label: str) -> None:
        self.session = session
        self.source_label = source_label

    def record(self, patient_id: int) -> PatientRecord:
        s = self.session
        p = get_patient(s, patient_id)
        cgm = _frame(
            s.execute(
                select(CgmReading.ts, CgmReading.dexcom_mgdl, CgmReading.dexcom_is_native)
                .where(CgmReading.patient_id == patient_id)
                .order_by(CgmReading.ts)
            ).all(),
            ["ts", "dexcom_mgdl", "dexcom_is_native"],
        )
        wear = _frame(
            s.execute(
                select(
                    WearableMinute.ts,
                    WearableMinute.hr_bpm,
                    WearableMinute.mets,
                    WearableMinute.activity_kcal,
                )
                .where(WearableMinute.patient_id == patient_id)
                .order_by(WearableMinute.ts)
            ).all(),
            ["ts", "hr_bpm", "mets", "activity_kcal"],
        )
        meals = _frame(
            s.execute(
                select(
                    Meal.meal_id,
                    Meal.started_at,
                    Meal.meal_type,
                    Meal.carbs_g,
                    Meal.protein_g,
                    Meal.fat_g,
                    Meal.fiber_g,
                    Meal.calories_kcal,
                    Meal.macro_validity,
                )
                .where(Meal.patient_id == patient_id)
                .order_by(Meal.started_at, Meal.meal_id)
            ).all(),
            [
                "meal_id",
                "started_at",
                "meal_type",
                "carbs_g",
                "protein_g",
                "fat_g",
                "fiber_g",
                "calories_kcal",
                "macro_validity",
            ],
        )
        for df, cols in (
            (cgm, ["dexcom_mgdl"]),
            (wear, ["hr_bpm", "mets", "activity_kcal"]),
            (meals, ["carbs_g", "protein_g", "fat_g", "fiber_g", "calories_kcal"]),
        ):
            for c in cols:
                df[c] = pd.to_numeric(df[c], errors="coerce").astype(float)
        cgm["dexcom_is_native"] = cgm["dexcom_is_native"].astype(bool)
        meals["macro_validity"] = [getattr(v, "value", v) for v in meals["macro_validity"]]
        clin = dict(
            s.execute(
                select(ClinicalObservation.field, ClinicalObservation.value_num)
                .where(ClinicalObservation.patient_id == patient_id)
                .where(ClinicalObservation.field.in_(CLINICAL_OBSERVED))
            ).all()
        )
        sex = s.scalar(
            select(ClinicalObservation.value_text).where(
                ClinicalObservation.patient_id == patient_id, ClinicalObservation.field == "sex"
            )
        )
        row: dict[str, object] = {k: clin.get(k, np.nan) for k in CLINICAL_OBSERVED}
        row["sex"] = sex
        return PatientRecord(
            patient_id=patient_id,
            clinical=clinical_from_row({k: (np.nan if v is None else v) for k, v in row.items()}),
            cgm=cgm,
            wearable=wear,
            meals=meals,
            glycemic_group=p.glycemic_group.value,
            source=self.source_label,
        )
