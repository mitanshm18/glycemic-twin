"""Patient data (read-only views of what was ingested) and the Digital Twin endpoints."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from twin_core.twin import ScenarioResult, TwinState
from twin_core.twin.model import ModelIdentity

from twin_api import errors
from twin_api.auth import Principal, any_user, audit, get_db
from twin_api.models import (
    AuditOutcome,
    CgmReading,
    ClinicalObservation,
    Meal,
    MealLabel,
    Patient,
    TwinStateRow,
    WearableMinute,
)
from twin_api.repository import data_range, get_patient
from twin_api.schemas import (
    CgmPoint,
    ClinicalFieldOut,
    MealOut,
    MealOutcomeOut,
    PatientDetail,
    PatientSummary,
    PredictionIn,
    PredictionOut,
    WearablePoint,
    WhatIfIn,
)
from twin_api.service import TwinService

router = APIRouter(tags=["patients"])
DB = Annotated[Session, Depends(get_db)]
User = Annotated[Principal, Depends(any_user)]
MAX_CGM_WINDOW = timedelta(days=7)
MAX_WEAR_WINDOW = timedelta(days=2)


def _service(request: Request) -> TwinService:
    svc: TwinService = request.app.state.twin_service
    return svc


def _naive(name: str, v: datetime | None) -> datetime | None:
    if v is not None and v.tzinfo is not None:
        raise errors.invalid_timestamp(f"{name} must be a local timestamp without a time zone")
    return v


def _window(
    db: Session, pid: int, start: datetime | None, end: datetime | None, limit: timedelta
) -> tuple[datetime, datetime]:
    start, end = _naive("start", start), _naive("end", end)
    rng = data_range(db, pid)
    if rng.last is None:
        raise errors.data_out_of_range(f"patient {pid} has no observations")
    end = end or rng.last
    start = start or end - timedelta(days=1)
    if start > end:
        raise errors.invalid_timestamp("start must be before end")
    if end - start > limit:
        raise errors.invalid_timestamp(f"window may not exceed {limit.days} day(s)")
    return start, end


def _summary_rows(db: Session, pid: int | None = None) -> list[dict[str, Any]]:
    meals = (
        select(
            Meal.patient_id,
            func.count().label("meals"),
            func.count().filter(MealLabel.eligible).label("eligible"),
            func.min(Meal.started_at).label("first_meal"),
            func.max(Meal.started_at).label("last_meal"),
        )
        .join(MealLabel, MealLabel.meal_id == Meal.meal_id, isouter=True)
        .group_by(Meal.patient_id)
        .subquery()
    )
    cgm = (
        select(
            CgmReading.patient_id,
            func.min(CgmReading.ts).label("first"),
            func.max(CgmReading.ts).label("last"),
        )
        .group_by(CgmReading.patient_id)
        .subquery()
    )
    q = (
        select(Patient, meals.c.meals, meals.c.eligible, cgm.c.first, cgm.c.last)
        .join(meals, meals.c.patient_id == Patient.id, isouter=True)
        .join(cgm, cgm.c.patient_id == Patient.id, isouter=True)
        .order_by(Patient.id)
    )
    if pid is not None:
        q = q.where(Patient.id == pid)
    return [
        {
            "id": p.id,
            "external_ref": p.external_ref,
            "glycemic_group": p.glycemic_group.value,
            "data_from": first,
            "data_to": last,
            "meals": n or 0,
            "eligible_meals": e or 0,
            "_patient": p,
        }
        for p, n, e, first, last in cast(
            list[tuple[Patient, int | None, int | None, datetime | None, datetime | None]],
            db.execute(q).all(),
        )
    ]


@router.get("/patients", response_model=list[PatientSummary])
def list_patients(request: Request, db: DB, who: User) -> list[dict[str, Any]]:
    audit(request, "list_patients", AuditOutcome.success, user=who.user, status_code=200)
    return _summary_rows(db)


@router.get("/patients/{pid}", response_model=PatientDetail)
def patient_detail(pid: int, request: Request, db: DB, who: User) -> dict[str, Any]:
    get_patient(db, pid)
    row = _summary_rows(db, pid)[0]
    p: Patient = row.pop("_patient")
    counts = db.execute(
        select(func.count(), func.count().filter(CgmReading.dexcom_is_native)).where(
            CgmReading.patient_id == pid
        )
    ).one()
    wear = db.scalar(select(func.count()).where(WearableMinute.patient_id == pid))
    audit(
        request,
        "read_patient",
        AuditOutcome.success,
        user=who.user,
        status_code=200,
        resource_type="patient",
        resource_id=str(pid),
    )
    return {
        **row,
        "source_label": p.source_label,
        "ingestion_run_id": p.ingestion_run_id,
        "cgm_readings": counts[0],
        "cgm_native_readings": counts[1],
        "wearable_minutes": wear,
    }


@router.get("/patients/{pid}/clinical", response_model=list[ClinicalFieldOut])
def clinical(pid: int, request: Request, db: DB, who: User) -> list[ClinicalObservation]:
    get_patient(db, pid)
    audit(
        request,
        "read_clinical",
        AuditOutcome.success,
        user=who.user,
        status_code=200,
        resource_type="patient",
        resource_id=str(pid),
    )
    return list(
        db.scalars(
            select(ClinicalObservation)
            .where(ClinicalObservation.patient_id == pid)
            .order_by(ClinicalObservation.id)
        )
    )


@router.get("/patients/{pid}/cgm", response_model=list[CgmPoint])
def cgm(
    pid: int,
    request: Request,
    db: DB,
    who: User,
    start: datetime | None = None,
    end: datetime | None = None,
    native_only: bool = Query(default=False),  # noqa: B008
) -> list[CgmReading]:
    get_patient(db, pid)
    lo, hi = _window(db, pid, start, end, MAX_CGM_WINDOW)
    q = select(CgmReading).where(
        CgmReading.patient_id == pid, CgmReading.ts >= lo, CgmReading.ts <= hi
    )
    if native_only:
        q = q.where(CgmReading.dexcom_is_native)
    audit(
        request,
        "read_cgm",
        AuditOutcome.success,
        user=who.user,
        status_code=200,
        resource_type="patient",
        resource_id=str(pid),
    )
    return list(db.scalars(q.order_by(CgmReading.ts)))


@router.get("/patients/{pid}/wearable", response_model=list[WearablePoint])
def wearable(
    pid: int,
    request: Request,
    db: DB,
    who: User,
    start: datetime | None = None,
    end: datetime | None = None,
) -> list[WearableMinute]:
    get_patient(db, pid)
    lo, hi = _window(db, pid, start, end, MAX_WEAR_WINDOW)
    audit(
        request,
        "read_wearable",
        AuditOutcome.success,
        user=who.user,
        status_code=200,
        resource_type="patient",
        resource_id=str(pid),
    )
    return list(
        db.scalars(
            select(WearableMinute)
            .where(
                WearableMinute.patient_id == pid, WearableMinute.ts >= lo, WearableMinute.ts <= hi
            )
            .order_by(WearableMinute.ts)
        )
    )


@router.get("/patients/{pid}/meals", response_model=list[MealOut])
def meals(pid: int, request: Request, db: DB, who: User) -> list[Meal]:
    get_patient(db, pid)
    audit(
        request,
        "read_meals",
        AuditOutcome.success,
        user=who.user,
        status_code=200,
        resource_type="patient",
        resource_id=str(pid),
    )
    return list(
        db.scalars(
            select(Meal).where(Meal.patient_id == pid).order_by(Meal.started_at, Meal.meal_id)
        )
    )


@router.get("/patients/{pid}/meal-outcomes", response_model=list[MealOutcomeOut])
def meal_outcomes(pid: int, request: Request, db: DB, who: User) -> list[dict[str, Any]]:
    get_patient(db, pid)
    rows = db.execute(
        select(MealLabel, Meal.started_at)
        .join(Meal, Meal.meal_id == MealLabel.meal_id)
        .where(Meal.patient_id == pid)
        .order_by(Meal.started_at, Meal.meal_id)
    ).all()
    audit(
        request,
        "read_meal_outcomes",
        AuditOutcome.success,
        user=who.user,
        status_code=200,
        resource_type="patient",
        resource_id=str(pid),
    )
    return [
        {
            **{c: getattr(lab, c) for c in MealOutcomeOut.model_fields if hasattr(lab, c)},
            "started_at": started,
        }
        for lab, started in rows
    ]


@router.get("/patients/{pid}/twin", response_model=TwinState)
def twin_state(
    pid: int,
    request: Request,
    db: DB,
    who: User,
    as_of: datetime | None = None,
    meal_id: str | None = Query(default=None, max_length=32),  # noqa: B008
) -> TwinState:
    """The Digital Twin state (twin-state/1, ADR-017) at as_of (default: the latest observation).
    Stored as an immutable snapshot keyed by its content hash."""
    state, _, _ = _service(request).state(db, pid, _naive("as_of", as_of), meal_id, who.user.id)
    db.commit()
    audit(
        request,
        "twin_state",
        AuditOutcome.success,
        user=who.user,
        status_code=200,
        resource_type="twin_state",
        resource_id=state.state_id,
    )
    return state


@router.get("/twin-states/{state_id}", response_model=TwinState)
def stored_state(state_id: str, request: Request, db: DB, who: User) -> TwinState:
    row = db.scalar(select(TwinStateRow).where(TwinStateRow.state_id == state_id))
    if row is None:
        raise errors.not_found(f"twin state {state_id}")
    audit(
        request,
        "read_twin_state",
        AuditOutcome.success,
        user=who.user,
        status_code=200,
        resource_type="twin_state",
        resource_id=state_id,
    )
    return TwinState.model_validate(row.state)


@router.post("/patients/{pid}/predictions", response_model=PredictionOut)
def predict(pid: int, body: PredictionIn, request: Request, db: DB, who: User) -> PredictionOut:
    pred, state, active = _service(request).predict(db, pid, body.as_of, body.meal_id, who.user.id)
    db.commit()
    audit(
        request,
        "predict",
        AuditOutcome.success,
        user=who.user,
        status_code=200,
        resource_type="prediction",
        resource_id=str(pred.id),
    )
    r = state.risk
    model = state.provenance.model
    assert model is not None
    return PredictionOut(
        prediction_id=pred.id,
        patient_id=pid,
        as_of=pred.as_of,
        state_id=state.state_id,
        meal_id=state.provenance.current_meal_id,
        status=r.status,
        reason=r.reason,
        probability=r.probability,
        threshold=r.threshold,
        above_threshold=r.above_threshold,
        uncertainty=r.uncertainty,
        model_inputs=r.model_inputs,
        model=ModelIdentity.model_validate(model),
        provenance=state.provenance.model_dump(mode="json", exclude={"model"}),
    )


@router.post("/patients/{pid}/what-if", response_model=ScenarioResult)
def what_if(pid: int, body: WhatIfIn, request: Request, db: DB, who: User) -> ScenarioResult:
    try:
        result = _service(request).what_if(
            db, pid, body.as_of, body.meal_id, dict(body.changes), who.user.id
        )
    except errors.ApiError as err:
        db.commit()  # keep the record of a rejected scenario
        audit(
            request,
            "what_if",
            AuditOutcome.denied if err.status < 500 else AuditOutcome.failed,
            user=who.user,
            status_code=err.status,
            resource_type="patient",
            resource_id=str(pid),
            detail={"code": err.code},
        )
        raise
    db.commit()
    audit(
        request,
        "what_if",
        AuditOutcome.success,
        user=who.user,
        status_code=200,
        resource_type="what_if",
        resource_id=result.scenario_id,
        detail={"status": result.status},
    )
    return result
