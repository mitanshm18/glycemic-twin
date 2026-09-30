"""Request/response models. The twin state and scenario responses are twin_core's own models
(ADR-017) and are re-exported unchanged; the API never reshapes them."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, field_validator
from twin_core.twin import ScenarioResult, TwinState
from twin_core.twin.model import ModelIdentity
from twin_core.twin.state import DISCLAIMER, Uncertainty

__all__ = ["ScenarioResult", "TwinState"]


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


def _naive(v: datetime | None) -> datetime | None:
    if v is not None and v.tzinfo is not None:
        raise ValueError("timestamps are local CGMacros clock times: send them without a time zone")
    return v


# ------------------------------------------------------------------------------------------ auth


class LoginIn(_In):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.@-]+$")
    password: str = Field(min_length=1, max_length=256)


class UserOut(_Out):
    id: int
    username: str
    role: Literal["clinician", "admin"]
    is_active: bool


class LoginOut(BaseModel):
    user: UserOut
    csrf_token: str  # send back as X-CSRF-Token on every POST
    expires_at: datetime


class UserCreateIn(_In):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.@-]+$")
    password: str = Field(min_length=12, max_length=256)
    role: Literal["clinician", "admin"]


# ------------------------------------------------------------------------------------------ health


class HealthOut(BaseModel):
    status: Literal["ok"]


class ReadyOut(BaseModel):
    ready: bool
    database: bool
    migrations_at_head: bool
    active_model: str | None
    model_compatible: bool
    support_profile: bool
    problems: list[str]


# ------------------------------------------------------------------------------------------ patients


class PatientSummary(BaseModel):
    id: int
    external_ref: str
    glycemic_group: str
    data_from: datetime | None
    data_to: datetime | None
    meals: int
    eligible_meals: int


class PatientDetail(PatientSummary):
    source_label: str
    ingestion_run_id: int
    cgm_readings: int
    cgm_native_readings: int
    wearable_minutes: int


class ClinicalFieldOut(_Out):
    field: str
    value_num: float | None
    value_text: str | None
    unit: str | None
    provenance: Literal["observed", "derived"]
    derivation: str | None
    quality_flag: str | None
    source_file: str | None
    source_column: str | None


class CgmPoint(_Out):
    ts: datetime
    dexcom_mgdl: float | None
    dexcom_is_native: bool
    libre_mgdl: float | None


class WearablePoint(_Out):
    ts: datetime
    hr_bpm: float | None
    mets: float | None
    activity_kcal: float | None


class MealOut(_Out):
    meal_id: str
    started_at: datetime
    meal_type: str | None
    carbs_g: float | None
    protein_g: float | None
    fat_g: float | None
    fiber_g: float | None
    calories_kcal: float | None
    macro_validity: str
    macro_reasons: str | None
    image_path: str | None


class MealOutcomeOut(_Out):
    meal_id: str
    started_at: datetime
    labels_version: int
    label: int | None
    frozen_usable: bool
    eligible: bool
    waterfall_reason: str
    exclusion_reasons: str | None
    window_coverage: float
    peak_mgdl: float | None
    peak_native_mgdl: float | None
    pre_meal_native_mgdl: float | None
    note: str = "retrospective frozen labels.v1 outcome (1-minute Dexcom basis, ADR-013)"


# ------------------------------------------------------------------------------------------ twin


class PredictionIn(_In):
    as_of: datetime | None = None
    meal_id: str | None = Field(default=None, max_length=32)

    _v = field_validator("as_of")(_naive)


class PredictionOut(BaseModel):
    prediction_id: int
    patient_id: int
    as_of: datetime
    state_id: str
    meal_id: str | None
    status: Literal["scored", "not_applicable", "unavailable"]
    reason: str | None
    probability: float | None
    threshold: float | None
    above_threshold: bool | None
    uncertainty: Uncertainty | None
    model_inputs: dict[str, float | None] | None
    model: ModelIdentity
    provenance: dict[str, Any]
    outcome: str = "Dexcom glucose above 180 mg/dL within 120 minutes of the meal start"
    disclaimer: str = DISCLAIMER


class WhatIfIn(_In):
    as_of: datetime | None = None
    meal_id: str | None = Field(default=None, max_length=32)
    # strict numbers: "5" or true are rejected, never coerced
    changes: dict[str, StrictFloat | StrictInt] = Field(min_length=1, max_length=5)

    _v = field_validator("as_of")(_naive)


class ReplayIn(_In):
    patient_id: int = Field(gt=0)
    start_at: datetime
    end_at: datetime
    step_minutes: int = Field(default=15, ge=1, le=1440)

    _v1 = field_validator("start_at")(_naive)
    _v2 = field_validator("end_at")(_naive)


class ReplayOut(_Out):
    id: int
    patient_id: int
    start_at: datetime
    end_at: datetime
    cursor_at: datetime
    step_minutes: int
    last_state_id: str | None


class ReplayStepOut(BaseModel):
    replay: ReplayOut
    state: TwinState
    finished: bool


# ------------------------------------------------------------------------------------------ admin


class ModelVersionOut(_Out):
    id: int
    model_version: str
    model_type: str
    feature_set: str
    n_columns: int
    contract_version: int
    contract_sha256: str
    features_sha256: str
    labels_sha256: str
    training_config_sha256: str | None
    dataset_content_sha256: str
    dataset_label: str | None
    threshold: float
    artifact_path: str
    artifact_sha256: str
    bundle_created_utc: str | None
    support_profile_id: int | None
    is_active: bool
    registered_at: datetime


class AuditOut(_Out):
    id: int
    occurred_at: datetime
    username: str | None
    action: str
    resource_type: str | None
    resource_id: str | None
    outcome: str
    status_code: int | None
    detail: dict[str, Any]


class IngestionRunOut(_Out):
    id: int
    kind: str
    status: str
    source_label: str
    content_sha256: str
    m1_pipeline_version: str | None
    m1_manifest_sha256: str | None
    m2_dataset_sha256: str | None
    labels_sha256: str | None
    features_sha256: str | None
    counts: dict[str, Any]
    started_at: datetime
    finished_at: datetime | None
