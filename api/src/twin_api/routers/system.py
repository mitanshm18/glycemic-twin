"""Health/readiness, authentication, replay sessions and admin endpoints."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any

from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from twin_core.twin import ModelContractError

from twin_api import errors
from twin_api.auth import Principal, admin_only, any_user, audit, create_user, get_db, login, logout
from twin_api.models import AuditLog, AuditOutcome, IngestionRun, ModelVersion, ReplaySession, User
from twin_api.registry import activate, active_version, runtime_for
from twin_api.schemas import (
    AuditOut,
    HealthOut,
    IngestionRunOut,
    LoginIn,
    LoginOut,
    ModelVersionOut,
    ReadyOut,
    ReplayIn,
    ReplayOut,
    ReplayStepOut,
    UserCreateIn,
    UserOut,
)
from twin_api.service import TwinService, resolve_as_of

router = APIRouter()
DB = Annotated[Session, Depends(get_db)]
Anyone = Annotated[Principal, Depends(any_user)]
Admin = Annotated[Principal, Depends(admin_only)]
ALEMBIC_INI = Path(__file__).resolve().parents[3] / "alembic.ini"


def head_revision() -> str | None:
    return ScriptDirectory.from_config(Config(str(ALEMBIC_INI))).get_current_head()


# ------------------------------------------------------------------------------------ health


@router.get("/health", response_model=HealthOut, tags=["health"])
def health() -> dict[str, str]:
    """Liveness: the process is up. No database access."""
    return {"status": "ok"}


@router.get("/ready", response_model=ReadyOut, tags=["health"])
def ready(request: Request, response: Response, db: DB) -> dict[str, Any]:
    """Readiness: database reachable, migrations at head, active model loadable and compatible."""
    problems: list[str] = []
    out: dict[str, Any] = {
        "database": False,
        "migrations_at_head": False,
        "active_model": None,
        "model_compatible": False,
        "support_profile": False,
    }
    try:
        db.execute(text("select 1"))
        out["database"] = True
        current = db.scalar(text("select version_num from alembic_version"))
        out["migrations_at_head"] = current == head_revision()
        if not out["migrations_at_head"]:
            problems.append("database is not at the latest migration")
        row = active_version(db)
        if row is None:
            problems.append("no active model version")
        else:
            out["active_model"] = row.model_version
            try:
                rt = runtime_for(
                    row, request.app.state.configs, db, request.app.state.settings.artifact_search
                )
                out["model_compatible"] = True
                out["support_profile"] = rt.support is not None
                if rt.support is None:
                    problems.append("no training-support profile: what-if disabled")
            except ModelContractError as err:
                problems.append(f"active model incompatible: {err}")
    except Exception as err:  # noqa: BLE001 - readiness must report, not crash
        problems.append(f"database error: {type(err).__name__}")
    out["ready"] = out["database"] and out["migrations_at_head"] and out["model_compatible"]
    out["problems"] = problems
    if not out["ready"]:
        response.status_code = 503
    return out


# ------------------------------------------------------------------------------------ auth


@router.post("/auth/login", response_model=LoginOut, tags=["auth"])
def do_login(body: LoginIn, request: Request, response: Response, db: DB) -> dict[str, Any]:
    user, csrf, expires = login(
        db, request.app.state.settings, request, response, body.username, body.password
    )
    db.commit()
    return {"user": user, "csrf_token": csrf, "expires_at": expires}


@router.post("/auth/logout", status_code=204, tags=["auth"])
def do_logout(request: Request, response: Response, db: DB, who: Anyone) -> Response:
    logout(db, who, request.app.state.settings, response)
    db.commit()
    audit(request, "logout", AuditOutcome.success, user=who.user, status_code=204)
    response.status_code = 204
    return response


@router.get("/auth/me", response_model=UserOut, tags=["auth"])
def me(who: Anyone) -> User:
    return who.user


# ------------------------------------------------------------------------------------ replay


def _replay(db: Session, rid: int, who: Principal) -> ReplaySession:
    r = db.get(ReplaySession, rid)
    if r is None or (r.user_id != who.user.id and who.user.role.value != "admin"):
        raise errors.not_found(f"replay session {rid}")
    return r


@router.post("/replays", response_model=ReplayOut, status_code=201, tags=["replay"])
def create_replay(body: ReplayIn, request: Request, db: DB, who: Anyone) -> ReplaySession:
    if body.start_at >= body.end_at:
        raise errors.invalid_timestamp("start_at must be before end_at")
    resolve_as_of(db, body.patient_id, body.start_at)
    resolve_as_of(db, body.patient_id, body.end_at)
    r = ReplaySession(
        user_id=who.user.id,
        patient_id=body.patient_id,
        start_at=body.start_at,
        end_at=body.end_at,
        cursor_at=body.start_at,
        step_minutes=body.step_minutes,
    )
    db.add(r)
    db.commit()
    audit(
        request,
        "create_replay",
        AuditOutcome.success,
        user=who.user,
        status_code=201,
        resource_type="replay",
        resource_id=str(r.id),
    )
    return r


@router.get("/replays/{rid}", response_model=ReplayOut, tags=["replay"])
def get_replay(rid: int, db: DB, who: Anyone) -> ReplaySession:
    return _replay(db, rid, who)


@router.post("/replays/{rid}/step", response_model=ReplayStepOut, tags=["replay"])
def step_replay(rid: int, request: Request, db: DB, who: Anyone) -> dict[str, Any]:
    """Return the twin at the cursor, then move the cursor forward by step_minutes (capped at end)."""
    r = _replay(db, rid, who)
    svc: TwinService = request.app.state.twin_service
    state, _, _ = svc.state(db, r.patient_id, r.cursor_at, None, who.user.id)
    finished = r.cursor_at >= r.end_at
    r.last_state_id = state.state_id
    r.cursor_at = min(r.cursor_at + timedelta(minutes=r.step_minutes), r.end_at)
    r.updated_at = datetime.now(UTC)
    db.commit()
    return {"replay": r, "state": state, "finished": finished}


# ------------------------------------------------------------------------------------ admin


@router.get("/admin/models", response_model=list[ModelVersionOut], tags=["admin"])
def list_models(db: DB, who: Admin) -> list[ModelVersion]:
    return list(db.scalars(select(ModelVersion).order_by(ModelVersion.id)))


@router.post("/admin/models/{mid}/activate", response_model=ModelVersionOut, tags=["admin"])
def activate_model(mid: int, request: Request, db: DB, who: Admin) -> ModelVersion:
    try:
        row = activate(
            db, mid, request.app.state.configs, request.app.state.settings.artifact_search
        )
    except ModelContractError as err:
        audit(
            request,
            "activate_model",
            AuditOutcome.denied,
            user=who.user,
            status_code=409,
            resource_type="model_version",
            resource_id=str(mid),
            detail={"reason": str(err)},
        )
        raise errors.model_incompatible(str(err)) from err
    except RuntimeError as err:
        raise errors.not_found(str(err)) from err
    db.commit()
    audit(
        request,
        "activate_model",
        AuditOutcome.success,
        user=who.user,
        status_code=200,
        resource_type="model_version",
        resource_id=str(mid),
    )
    return row


@router.get("/admin/ingestion-runs", response_model=list[IngestionRunOut], tags=["admin"])
def ingestion_runs(db: DB, who: Admin) -> list[IngestionRun]:
    return list(db.scalars(select(IngestionRun).order_by(IngestionRun.id)))


@router.get("/admin/audit", response_model=list[AuditOut], tags=["admin"])
def audit_log(db: DB, who: Admin, limit: int = Query(default=100, ge=1, le=1000)) -> list[AuditLog]:  # noqa: B008
    return list(db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)))


@router.post("/admin/users", response_model=UserOut, status_code=201, tags=["admin"])
def add_user(body: UserCreateIn, request: Request, db: DB, who: Admin) -> User:
    user = create_user(db, body.username, body.password, body.role)
    db.commit()
    audit(
        request,
        "create_user",
        AuditOutcome.success,
        user=who.user,
        status_code=201,
        resource_type="user",
        resource_id=str(user.id),
        detail={"role": body.role},
    )
    return user
