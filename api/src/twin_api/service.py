"""The API's only bridge to the Digital Twin engine.

Every state, prediction and scenario comes from twin_core (``build_state`` / ``simulate``) running
on a ``DbRecordSource`` and the active registered model. This module adds only: input validation,
choosing the default ``as_of``, persistence of the engine's outputs, and error mapping.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session
from twin_core.twin import (
    ModelContractError,
    ScenarioError,
    ScenarioResult,
    TwinConfigs,
    TwinRuntime,
    TwinState,
    build_state,
    simulate,
)

from twin_api import errors
from twin_api.models import (
    Meal,
    ModelVersion,
    Prediction,
    TwinStateRow,
    WhatIfRun,
    WhatIfStatus,
)
from twin_api.registry import ArtifactSearch, active_version, runtime_for
from twin_api.repository import DbRecordSource, data_range, get_patient

AS_OF_GRACE = timedelta(days=1)


@dataclass(frozen=True)
class Active:
    runtime: TwinRuntime
    version: ModelVersion


class RuntimeHolder:
    """Loads the active model once and reloads only when the registry's active entry changes."""

    def __init__(self, configs: TwinConfigs, search: ArtifactSearch | None = None) -> None:
        self.configs = configs
        self.search = search
        self._lock = threading.Lock()
        self._key: tuple[int, str, int | None] | None = None
        self._active: Active | None = None

    def get(self, session: Session, require_support: bool = False) -> Active:
        row = active_version(session)
        if row is None:
            raise errors.model_unavailable("no active model version is registered")
        key = (row.id, row.artifact_sha256, row.support_profile_id)
        with self._lock:
            if key != self._key or self._active is None:
                try:
                    runtime = runtime_for(row, self.configs, session, self.search)
                except ModelContractError as err:
                    self._key, self._active = None, None
                    raise errors.model_incompatible(str(err)) from err
                self._key, self._active = key, Active(runtime, row)
            active = self._active
        if require_support and active.runtime.support is None:
            raise errors.model_unavailable(
                "what-if is disabled: no training-support profile is stored for the active model"
            )
        return active


def resolve_as_of(session: Session, pid: int, as_of: datetime | None) -> datetime:
    if as_of is not None and as_of.tzinfo is not None:
        raise errors.invalid_timestamp("as_of must be a local timestamp without a time zone")
    rng = data_range(session, pid)
    if rng.first is None or rng.last is None:
        raise errors.data_out_of_range(f"patient {pid} has no observations")
    if as_of is None:
        return rng.last
    if as_of < rng.first or as_of > rng.last + AS_OF_GRACE:
        raise errors.data_out_of_range(
            "as_of is outside this patient's observed data",
            {"data_from": rng.first.isoformat(), "data_to": rng.last.isoformat()},
        )
    return as_of


def _check_meal(session: Session, pid: int, meal_id: str | None) -> None:
    if meal_id is None:
        return
    meal = session.get(Meal, meal_id)
    if meal is None or meal.patient_id != pid:
        raise errors.not_found(f"meal {meal_id} of patient {pid}")


def persist_state(
    session: Session, state: TwinState, version_id: int, user_id: int | None
) -> TwinStateRow:
    doc = state.model_dump(mode="json")
    session.execute(
        pg_insert(TwinStateRow)
        .values(
            state_id=state.state_id,
            patient_id=state.patient_id,
            as_of=datetime.fromisoformat(state.as_of),
            schema_version=state.schema_version,
            engine_version=state.provenance.engine_version,
            lifecycle_phase=state.lifecycle.phase.value,
            risk_status=state.risk.status,
            current_meal_id=state.provenance.current_meal_id,
            model_version_id=version_id,
            record_sha256=state.provenance.record_sha256,
            state=doc,
            created_by=user_id,
        )
        .on_conflict_do_nothing(index_elements=["state_id"])
    )
    row = session.scalar(select(TwinStateRow).where(TwinStateRow.state_id == state.state_id))
    assert row is not None
    return row


class TwinService:
    def __init__(self, configs: TwinConfigs, holder: RuntimeHolder, source_label: str) -> None:
        self.configs, self.holder, self.source_label = configs, holder, source_label

    def state(
        self,
        session: Session,
        pid: int,
        as_of: datetime | None,
        meal_id: str | None,
        user_id: int | None,
    ) -> tuple[TwinState, TwinStateRow, Active]:
        get_patient(session, pid)
        t = resolve_as_of(session, pid, as_of)
        _check_meal(session, pid, meal_id)
        active = self.holder.get(session)
        try:
            state = build_state(
                pid,
                t,
                source=DbRecordSource(session, self.source_label),
                runtime=active.runtime,
                current_meal_id=meal_id,
            )
        except ValueError as err:  # e.g. the requested meal starts after as_of
            raise errors.ApiError(422, "INVALID_REQUEST", str(err)) from err
        return state, persist_state(session, state, active.version.id, user_id), active

    def predict(
        self,
        session: Session,
        pid: int,
        as_of: datetime | None,
        meal_id: str | None,
        user_id: int | None,
    ) -> tuple[Prediction, TwinState, Active]:
        state, row, active = self.state(session, pid, as_of, meal_id, user_id)
        if state.current_meal is None:
            raise errors.no_current_meal(
                "no meal is in progress at as_of (a meal is current for 120 minutes after it "
                "starts); pass meal_id or a later as_of"
            )
        r = state.risk
        session.execute(
            pg_insert(Prediction)
            .values(
                twin_state_id=row.id,
                patient_id=pid,
                meal_id=state.provenance.current_meal_id,
                as_of=row.as_of,
                model_version_id=active.version.id,
                status=r.status,
                probability=r.probability,
                threshold=r.threshold,
                above_threshold=r.above_threshold,
                uncertainty_level=None if r.uncertainty is None else r.uncertainty.level,
                created_by=user_id,
            )
            .on_conflict_do_nothing(index_elements=["twin_state_id"])
        )
        pred = session.scalar(select(Prediction).where(Prediction.twin_state_id == row.id))
        assert pred is not None
        return pred, state, active

    def what_if(
        self,
        session: Session,
        pid: int,
        as_of: datetime | None,
        meal_id: str | None,
        changes: dict[str, Any],
        user_id: int | None,
    ) -> ScenarioResult:
        get_patient(session, pid)
        t = resolve_as_of(session, pid, as_of)
        _check_meal(session, pid, meal_id)
        active = self.holder.get(session, require_support=True)
        try:
            result = simulate(
                pid,
                t,
                changes,
                source=DbRecordSource(session, self.source_label),
                runtime=active.runtime,
                current_meal_id=meal_id,
            )
        except ScenarioError as err:
            session.add(
                WhatIfRun(
                    patient_id=pid,
                    as_of=t,
                    model_version_id=active.version.id,
                    changes={str(k): v for k, v in changes.items()},
                    status=WhatIfStatus.rejected,
                    rejection_reason=str(err),
                    created_by=user_id,
                )
            )
            session.flush()
            raise errors.what_if_unsupported(str(err)) from err
        session.add(
            WhatIfRun(
                scenario_id=result.scenario_id,
                patient_id=pid,
                as_of=t,
                base_state_id=result.base_state_id,
                model_version_id=active.version.id,
                changes=result.changes,
                status=WhatIfStatus(result.status),
                baseline_probability=result.baseline_probability,
                scenario_probability=result.scenario_probability,
                risk_delta=result.risk_delta,
                result=result.model_dump(mode="json"),
                created_by=user_id,
            )
        )
        session.flush()
        return result
