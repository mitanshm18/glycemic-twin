"""Read-only endpoints the M6 frontend needs (ADR-019). They reuse twin_core and the registry and
never change an existing contract:

  GET /auth/csrf                              rotate and return the session's CSRF token (after reload)
  GET /patients/{pid}/twin-states             stored snapshot history (twin evolution)
  GET /twin-states/{a}/diff/{b}               twin_core.diff_states between two stored snapshots
  GET /twin-states/{state_id}/explanation     per-input contributions to the served model's score
  GET /models                                 registry, readable by clinicians
  GET /models/active/evaluation               the M3 report for the active model's training data
  GET /overview/patients                      patient list + each one's most recent stored twin state
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from twin_core.twin import StateDiff, TwinState, diff_states

from twin_api import errors
from twin_api.auth import Principal, any_user, get_db
from twin_api.explain import NotExplainable, explain_inputs
from twin_api.models import ModelVersion, TwinStateRow
from twin_api.registry import active_version
from twin_api.repository import get_patient
from twin_api.routers.patients import _summary_rows
from twin_api.schemas import ModelVersionOut
from twin_api.security import new_token, sha256_hex
from twin_api.service import TwinService

router = APIRouter(tags=["insights"])
DB = Annotated[Session, Depends(get_db)]
User = Annotated[Principal, Depends(any_user)]


class CsrfOut(BaseModel):
    csrf_token: str


class TwinStateSummary(BaseModel):
    state_id: str
    as_of: datetime
    lifecycle_phase: str
    risk_status: str
    probability: float | None
    current_meal_id: str | None
    model_version: str | None
    created_at: datetime


class PatientOverview(BaseModel):
    id: int
    external_ref: str
    glycemic_group: str
    data_from: datetime | None
    data_to: datetime | None
    meals: int
    eligible_meals: int
    latest_state: TwinStateSummary | None  # most recently computed stored snapshot, if any


class Contribution(BaseModel):
    feature: str
    value: float | None
    contribution: float


class ExplanationOut(BaseModel):
    state_id: str
    model_version: str
    method: str  # tree_shap | linear_exact
    scale: str = "log-odds, before calibration"
    base_value: float
    raw_score: float
    probability: float | None  # the calibrated probability shown in the state
    contributions: list[Contribution]  # largest absolute contribution first
    note: str


class Interval(BaseModel):
    lo: float | None = None
    hi: float | None = None


class PopulationMetrics(BaseModel):
    meals: int = 0
    positives: int | None = None
    participants: int | None = None
    prevalence: float | None = None
    auroc: float | None = None
    pr_auc: float | None = None
    brier: float | None = None
    brier_skill: float | None = None
    calibration_slope: float | None = None
    calibration_intercept: float | None = None
    ece: float | None = None
    ci: dict[str, Interval] = {}


class RunMetrics(BaseModel):
    run: str
    model: str
    feature_set: str
    n_columns: int
    target: PopulationMetrics
    healthy: PopulationMetrics


class CalibrationBin(BaseModel):
    bin: int
    n: int
    mean_predicted: float
    observed_rate: float


class FoldMetrics(BaseModel):
    fold: int
    participants: int
    meals: int
    positives: int
    auroc: float | None
    pr_auc: float | None
    brier: float | None
    threshold: float | None


class ComparisonOut(BaseModel):
    comparison: str
    a: str
    b: str
    ran: bool
    pr_auc_difference: float | None = None
    pr_auc_lo: float | None = None
    pr_auc_hi: float | None = None
    auroc_difference: float | None = None
    auroc_lo: float | None = None
    auroc_hi: float | None = None


class Importance(BaseModel):
    feature: str
    mean_abs_shap: float


class EvaluationOut(BaseModel):
    report: str = "data/reports/m3_evaluation.json"
    dataset_label: str
    dataset_content_sha256: str
    active_run: str
    primary_run: str
    counts: dict[str, int]
    runs: list[RunMetrics]
    active_per_fold: list[FoldMetrics]
    active_calibration_curve: list[CalibrationBin]
    active_at_threshold: dict[str, float | int | None]
    comparisons: list[ComparisonOut]
    shap_global_importance: list[Importance]
    limitations: list[str]


LIMITATIONS = [
    "44 participants in total (30 prediabetes/T2D): confidence intervals are wide.",
    "Evaluated on new participants only (grouped cross-validation); no temporal hold-out yet.",
    "Labels use the frozen 1-minute Dexcom series; features use native readings only (ADR-013).",
    "Meals already above 180 mg/dL at the start, or with unusable macros, are outside the model's "
    "population and are never scored.",
    "Associations from observational data: no output is a causal effect or medical advice.",
]


def _service(request: Request) -> TwinService:
    svc: TwinService = request.app.state.twin_service
    return svc


def _stored(db: Session, state_id: str) -> TwinState:
    row = db.scalar(select(TwinStateRow).where(TwinStateRow.state_id == state_id))
    if row is None:
        raise errors.not_found(f"twin state {state_id}")
    return TwinState.model_validate(row.state)


@router.get("/auth/csrf", response_model=CsrfOut, tags=["auth"])
def rotate_csrf(db: DB, who: User) -> CsrfOut:
    """A fresh CSRF token for the current session (e.g. after a page reload). The previous one
    stops working. The response is readable only by the same origin (no CORS)."""
    token = new_token()
    who.session.csrf_sha256 = sha256_hex(token)
    db.flush()
    return CsrfOut(csrf_token=token)


@router.get("/patients/{pid}/twin-states", response_model=list[TwinStateSummary])
def state_history(
    pid: int,
    db: DB,
    who: User,
    limit: int = Query(default=50, ge=1, le=500),  # noqa: B008
) -> list[TwinStateSummary]:
    get_patient(db, pid)
    rows = db.scalars(
        select(TwinStateRow)
        .where(TwinStateRow.patient_id == pid)
        .order_by(TwinStateRow.as_of.desc(), TwinStateRow.id.desc())
        .limit(limit)
    )
    return [_summary(r) for r in rows]


def _summary(r: TwinStateRow) -> TwinStateSummary:
    model = (r.state.get("provenance") or {}).get("model") or {}
    return TwinStateSummary(
        state_id=r.state_id,
        as_of=r.as_of,
        lifecycle_phase=str(r.lifecycle_phase.value),
        risk_status=str(r.risk_status.value),
        probability=(r.state.get("risk") or {}).get("probability"),
        current_meal_id=r.current_meal_id,
        model_version=model.get("model_version"),
        created_at=r.created_at,
    )


@router.get("/overview/patients", response_model=list[PatientOverview])
def patients_overview(db: DB, who: User) -> list[PatientOverview]:
    """The patient list plus each patient's most recently computed twin snapshot. Nothing is
    computed here: patients without a stored snapshot report ``latest_state = null``."""
    rank = (
        func.row_number()
        .over(
            partition_by=TwinStateRow.patient_id,
            order_by=(TwinStateRow.created_at.desc(), TwinStateRow.id.desc()),
        )
        .label("rank")
    )
    ranked = select(TwinStateRow.id, rank).subquery()
    latest = {
        r.patient_id: r
        for r in db.scalars(
            select(TwinStateRow)
            .join(ranked, ranked.c.id == TwinStateRow.id)
            .where(ranked.c.rank == 1)
        )
    }
    out = []
    for row in _summary_rows(db):
        row = {k: v for k, v in row.items() if not k.startswith("_")}
        snap = latest.get(row["id"])
        out.append(PatientOverview(**row, latest_state=None if snap is None else _summary(snap)))
    return out


@router.get("/twin-states/{a}/diff/{b}", response_model=StateDiff)
def state_diff(a: str, b: str, db: DB, who: User) -> StateDiff:
    sa, sb = _stored(db, a), _stored(db, b)
    if sa.patient_id != sb.patient_id:
        raise errors.ApiError(422, "INVALID_REQUEST", "the two states belong to different patients")
    return diff_states(sa, sb)


@router.get("/twin-states/{state_id}/explanation", response_model=ExplanationOut)
def explanation(state_id: str, request: Request, db: DB, who: User) -> ExplanationOut:
    state = _stored(db, state_id)
    if state.risk.status != "scored" or state.risk.model_inputs is None:
        raise errors.ApiError(
            409, "NOT_EXPLAINABLE", f"this state has no scored prediction ({state.risk.status})"
        )
    active = _service(request).holder.get(db)
    produced_by = state.provenance.model.model_version if state.provenance.model else None
    served = active.runtime.model
    assert served is not None
    from twin_core.twin.model import identity

    if produced_by != identity(served).model_version:
        raise errors.model_incompatible(
            "this state was produced by a different model version than the one now active"
        )
    try:
        body = explain_inputs(served, state.risk.model_inputs)
    except NotExplainable as err:
        raise errors.ApiError(409, "NOT_EXPLAINABLE", str(err)) from err
    return ExplanationOut(
        state_id=state_id,
        model_version=produced_by,
        probability=state.risk.probability,
        **body,
    )


@router.get("/models", response_model=list[ModelVersionOut])
def models(db: DB, who: User) -> list[ModelVersion]:
    return list(db.scalars(select(ModelVersion).order_by(ModelVersion.id)))


def _pop(p: dict[str, Any]) -> PopulationMetrics:
    pooled = p.get("pooled") or {}
    ci = p.get("bootstrap_ci") or {}
    fields = {k: pooled[k] for k in PopulationMetrics.model_fields if k != "ci" and k in pooled}
    fields["ci"] = {k: {"lo": v.get("lo"), "hi": v.get("hi")} for k, v in ci.items()}
    return PopulationMetrics.model_validate(fields)


@router.get("/models/active/evaluation", response_model=EvaluationOut)
def active_evaluation(request: Request, db: DB, who: User) -> EvaluationOut:
    """The M3 evaluation report, served only if it was computed on the active model's training
    data (dataset content hash must match)."""
    _service(request).holder.get(db)  # refuses a missing or incompatible active model
    version = active_version(db)  # this request's own row (the holder's cached row is detached)
    assert version is not None
    path = request.app.state.settings.repo_root / "data/reports/m3_evaluation.json"
    if not path.exists():
        raise errors.not_found("the M3 evaluation report (run `make m3`)")
    report = json.loads(path.read_text())
    if report.get("dataset_content_sha256") != version.dataset_content_sha256:
        raise errors.model_incompatible(
            "the evaluation report was computed on different training data than the active model"
        )
    runs_raw: dict[str, Any] = report.get("runs") or {}
    active_run = f"{version.model_type.value}__{version.feature_set}"
    if active_run not in runs_raw:
        raise errors.not_found(f"evaluation of {active_run} in the M3 report")
    runs = [
        RunMetrics(
            run=rid,
            model=str(r.get("model")),
            feature_set=str(r.get("feature_set")),
            n_columns=int(r.get("n_columns") or 0),
            target=_pop(r.get("target") or {}),
            healthy=_pop(r.get("healthy") or {}),
        )
        for rid, r in runs_raw.items()
    ]
    act = runs_raw[active_run].get("target") or {}
    comparisons = []
    for c in report.get("comparisons") or []:
        pr, au = c.get("pr_auc") or {}, c.get("auroc") or {}
        comparisons.append(
            ComparisonOut(
                comparison=c.get("comparison", ""),
                a=c.get("a", ""),
                b=c.get("b", ""),
                ran=bool(c.get("ran")),
                pr_auc_difference=pr.get("difference"),
                pr_auc_lo=pr.get("lo"),
                pr_auc_hi=pr.get("hi"),
                auroc_difference=au.get("difference"),
                auroc_lo=au.get("lo"),
                auroc_hi=au.get("hi"),
            )
        )
    shap = (report.get("shap") or {}).get("global_importance_target") or []
    return EvaluationOut(
        dataset_label=str(report.get("dataset_label")),
        dataset_content_sha256=str(report.get("dataset_content_sha256")),
        active_run=active_run,
        primary_run=str((report.get("primary") or {}).get("run")),
        counts={k: int(v) for k, v in (report.get("counts") or {}).items()},
        runs=runs,
        active_per_fold=[
            FoldMetrics(**{k: f.get(k) for k in FoldMetrics.model_fields})
            for f in act.get("per_fold") or []
        ],
        active_calibration_curve=[CalibrationBin(**b) for b in act.get("calibration_curve") or []],
        active_at_threshold=act.get("at_threshold") or {},
        comparisons=comparisons,
        shap_global_importance=[Importance(**i) for i in shap[:20]],
        limitations=LIMITATIONS,
    )
