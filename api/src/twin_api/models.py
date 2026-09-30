"""PostgreSQL schema (ORM mapping). The migration in migrations/versions is the source of truth for
the database; a test checks this mapping and the migrated database agree exactly.

Time conventions:
- Observation times (CGM, wearable, meals, as_of) are ``timestamp without time zone``: CGMacros
  timestamps are date-shifted local clock times with no zone, and storing them as UTC would invent
  information.
- System times (created_at, expires_at, ...) are ``timestamptz``.

JSONB is used only for versioned documents whose schema is owned elsewhere (twin-state/1 and
twin-scenario/1 from ADR-017, the model's ordered columns/params/prior, the support profile) and for
free-form audit/ingestion detail. Every value that is queried or constrained is a real column.
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Identity,
    Index,
    Integer,
    MetaData,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


class UserRole(enum.StrEnum):
    clinician = "clinician"
    admin = "admin"


class GlycemicGroup(enum.StrEnum):
    healthy = "healthy"
    prediabetes = "prediabetes"
    T2D = "T2D"
    unknown = "unknown"


class FieldProvenance(enum.StrEnum):
    observed = "observed"
    derived = "derived"


class MacroValidity(enum.StrEnum):
    valid = "valid"
    missing = "missing"
    invalid = "invalid"
    empty = "empty"
    inconsistent = "inconsistent"


class ModelType(enum.StrEnum):
    logistic = "logistic"
    xgboost = "xgboost"


class RunStatus(enum.StrEnum):
    running = "running"
    succeeded = "succeeded"
    failed = "failed"


class RiskStatus(enum.StrEnum):
    scored = "scored"
    not_applicable = "not_applicable"
    unavailable = "unavailable"


class LifecyclePhase(enum.StrEnum):
    COLD_START = "COLD_START"
    WARMING = "WARMING"
    PERSONALIZED = "PERSONALIZED"


class WhatIfStatus(enum.StrEnum):
    ok = "ok"
    out_of_support = "out_of_support"
    rejected = "rejected"


class AuditOutcome(enum.StrEnum):
    success = "success"
    denied = "denied"
    failed = "failed"


def _enum(e: type[enum.Enum], name: str) -> Enum:
    return Enum(e, name=name, values_callable=lambda x: [m.value for m in x], validate_strings=True)


def _now() -> Any:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


# ------------------------------------------------------------------------------------------- users


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    username: Mapped[str] = mapped_column(String(64), nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)  # Argon2id PHC string
    role: Mapped[UserRole] = mapped_column(_enum(UserRole, "user_role"), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    failed_login_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _now()
    __table_args__ = (
        Index("uq_users_username_lower", func.lower(username), unique=True),
        CheckConstraint("left(password_hash, 10) = '$argon2id$'", name="argon2id_hash"),
        CheckConstraint("username ~ '^[A-Za-z0-9_.@-]{3,64}$'", name="username_format"),
        CheckConstraint("failed_login_count >= 0", name="failed_login_count_nonneg"),
    )


class UserSession(Base):
    __tablename__ = "sessions"
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    csrf_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = _now()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(256))
    __table_args__ = (
        Index("ix_sessions_user_id", "user_id"),
        CheckConstraint("expires_at > created_at", name="expires_after_created"),
        CheckConstraint("token_sha256 ~ '^[0-9a-f]{64}$'", name="token_sha256_hex"),
    )


class UserIdentity(Base):
    """An external sign-in identity (Google) that an admin linked to an existing user (M6).

    Provisioning is explicit: the admin records the Google account's email; the provider's stable
    subject (``sub``) is bound on the first successful sign-in and required to match afterwards.
    A Google account without a row here can never sign in, and no user is ever created from one.
    """

    __tablename__ = "user_identities"
    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    subject: Mapped[str | None] = mapped_column(String(255))
    created_by: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = _now()
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("provider", "email", name="uq_user_identities_provider_email"),
        Index(
            "uq_user_identities_provider_subject",
            "provider",
            "subject",
            unique=True,
            postgresql_where=text("subject IS NOT NULL"),
        ),
        Index("ix_user_identities_user_id", "user_id"),
        CheckConstraint("provider IN ('google')", name="known_provider"),
        CheckConstraint("email = lower(email) AND position('@' in email) > 1", name="email_format"),
    )


class OAuthFlow(Base):
    """One in-flight external sign-in: single use, short-lived, keyed by the SHA-256 of its state.

    The raw state lives only in the browser's HttpOnly flow cookie and the provider round trip, so a
    database read alone cannot complete a flow.
    """

    __tablename__ = "oauth_flows"
    state_sha256: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    nonce: Mapped[str] = mapped_column(String(128), nullable=False)
    code_verifier: Mapped[str] = mapped_column(String(128), nullable=False)
    next_path: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = _now()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        CheckConstraint("state_sha256 ~ '^[0-9a-f]{64}$'", name="state_sha256_hex"),
        CheckConstraint("provider IN ('google')", name="known_provider"),
        CheckConstraint("left(next_path, 1) = '/'", name="next_path_relative"),
        CheckConstraint("expires_at > created_at", name="expires_after_created"),
    )


# ------------------------------------------------------------------------------------ provenance


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"
    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)  # "m1_m2_processed"
    status: Mapped[RunStatus] = mapped_column(_enum(RunStatus, "run_status"), nullable=False)
    source_label: Mapped[str] = mapped_column(Text, nullable=False)
    source_dir: Mapped[str] = mapped_column(Text, nullable=False)
    content_sha256: Mapped[str] = mapped_column(
        String(64), nullable=False
    )  # of every ingested table
    m1_pipeline_version: Mapped[str | None] = mapped_column(String(32))
    m1_manifest_sha256: Mapped[str | None] = mapped_column(String(64))  # CGMacros source manifest
    m2_dataset_sha256: Mapped[str | None] = mapped_column(String(64))
    cleaning_sha256: Mapped[str | None] = mapped_column(String(64))
    labels_sha256: Mapped[str | None] = mapped_column(String(64))
    features_sha256: Mapped[str | None] = mapped_column(String(64))
    counts: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = _now()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        Index(
            "uq_ingestion_runs_succeeded_content",
            "content_sha256",
            unique=True,
            postgresql_where=text("status = 'succeeded'"),
        ),
    )


# ------------------------------------------------------------------------------------ observations


class Patient(Base):
    __tablename__ = "patients"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)  # CGMacros id
    external_ref: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    glycemic_group: Mapped[GlycemicGroup] = mapped_column(
        _enum(GlycemicGroup, "glycemic_group"), nullable=False
    )
    source_label: Mapped[str] = mapped_column(Text, nullable=False)
    ingestion_run_id: Mapped[int] = mapped_column(ForeignKey("ingestion_runs.id"), nullable=False)
    created_at: Mapped[datetime] = _now()
    __table_args__ = (CheckConstraint("id > 0", name="id_positive"),)


class ClinicalObservation(Base):
    """One bio.csv field per row, exactly as M1 cleaned it, with observed/derived provenance."""

    __tablename__ = "clinical_observations"
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    patient_id: Mapped[int] = mapped_column(
        ForeignKey("patients.id", ondelete="CASCADE"), nullable=False
    )
    field: Mapped[str] = mapped_column(String(64), nullable=False)
    value_num: Mapped[float | None] = mapped_column(Float)
    value_text: Mapped[str | None] = mapped_column(Text)
    unit: Mapped[str | None] = mapped_column(String(32))
    provenance: Mapped[FieldProvenance] = mapped_column(
        _enum(FieldProvenance, "field_provenance"), nullable=False
    )
    derivation: Mapped[str | None] = mapped_column(Text)
    quality_flag: Mapped[str | None] = mapped_column(Text)
    source_file: Mapped[str | None] = mapped_column(Text)
    source_column: Mapped[str | None] = mapped_column(Text)
    ingestion_run_id: Mapped[int] = mapped_column(ForeignKey("ingestion_runs.id"), nullable=False)
    __table_args__ = (
        UniqueConstraint("patient_id", "field", name="uq_clinical_observations_patient_field"),
        CheckConstraint(
            "provenance = 'observed' OR derivation IS NOT NULL", name="derived_has_derivation"
        ),
    )


class CgmReading(Base):
    """Every cleaned Dexcom/Libre minute row from M1. Only rows with dexcom_is_native feed features."""

    __tablename__ = "cgm_readings"
    patient_id: Mapped[int] = mapped_column(
        ForeignKey("patients.id", ondelete="CASCADE"), primary_key=True
    )
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=False), primary_key=True)
    dexcom_mgdl: Mapped[float | None] = mapped_column(Float)
    dexcom_is_native: Mapped[bool] = mapped_column(Boolean, nullable=False)
    dexcom_out_of_range: Mapped[bool] = mapped_column(Boolean, nullable=False)
    libre_mgdl: Mapped[float | None] = mapped_column(Float)
    libre_is_native: Mapped[bool] = mapped_column(Boolean, nullable=False)
    libre_out_of_range: Mapped[bool] = mapped_column(Boolean, nullable=False)
    duplicate_conflict: Mapped[bool] = mapped_column(Boolean, nullable=False)
    ingestion_run_id: Mapped[int] = mapped_column(ForeignKey("ingestion_runs.id"), nullable=False)
    __table_args__ = (
        CheckConstraint("dexcom_mgdl IS NULL OR dexcom_mgdl > 0", name="dexcom_positive"),
        CheckConstraint("libre_mgdl IS NULL OR libre_mgdl > 0", name="libre_positive"),
        CheckConstraint("NOT dexcom_is_native OR dexcom_mgdl IS NOT NULL", name="native_has_value"),
    )


class WearableMinute(Base):
    __tablename__ = "wearable_minutes"
    patient_id: Mapped[int] = mapped_column(
        ForeignKey("patients.id", ondelete="CASCADE"), primary_key=True
    )
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=False), primary_key=True)
    hr_bpm: Mapped[float | None] = mapped_column(Float)
    mets: Mapped[float | None] = mapped_column(Float)  # NULL = unknown, never zero
    activity_kcal: Mapped[float | None] = mapped_column(Float)
    hr_out_of_range: Mapped[bool] = mapped_column(Boolean, nullable=False)
    mets_out_of_range: Mapped[bool] = mapped_column(Boolean, nullable=False)
    ingestion_run_id: Mapped[int] = mapped_column(ForeignKey("ingestion_runs.id"), nullable=False)
    __table_args__ = (
        CheckConstraint("hr_bpm IS NULL OR hr_bpm > 0", name="hr_positive"),
        CheckConstraint("mets IS NULL OR mets >= 0", name="mets_nonneg"),
        CheckConstraint("activity_kcal IS NULL OR activity_kcal >= 0", name="kcal_nonneg"),
    )


class Meal(Base):
    """A logged meal as M1 cleaned it. amount_consumed_pct is stored as observed but is never a model
    input (ADR-015); image_path is a reference only (photos are not loaded)."""

    __tablename__ = "meals"
    meal_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    patient_id: Mapped[int] = mapped_column(
        ForeignKey("patients.id", ondelete="CASCADE"), nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    meal_type: Mapped[str | None] = mapped_column(String(32))
    meal_type_raw: Mapped[str | None] = mapped_column(Text)
    carbs_g: Mapped[float | None] = mapped_column(Float)
    protein_g: Mapped[float | None] = mapped_column(Float)
    fat_g: Mapped[float | None] = mapped_column(Float)
    fiber_g: Mapped[float | None] = mapped_column(Float)
    calories_kcal: Mapped[float | None] = mapped_column(Float)
    amount_consumed_pct: Mapped[float | None] = mapped_column(Float)
    macro_validity: Mapped[MacroValidity] = mapped_column(
        _enum(MacroValidity, "macro_validity"), nullable=False
    )
    macro_reasons: Mapped[str | None] = mapped_column(Text)
    energy_ratio: Mapped[float | None] = mapped_column(Float)
    duplicate_start: Mapped[bool] = mapped_column(Boolean, nullable=False)
    image_path: Mapped[str | None] = mapped_column(Text)
    source_file: Mapped[str] = mapped_column(Text, nullable=False)
    source_row: Mapped[int] = mapped_column(Integer, nullable=False)
    ingestion_run_id: Mapped[int] = mapped_column(ForeignKey("ingestion_runs.id"), nullable=False)
    __table_args__ = (
        Index("ix_meals_patient_started", "patient_id", "started_at"),
        CheckConstraint(
            "coalesce(carbs_g, 0) >= 0 AND coalesce(protein_g, 0) >= 0 AND coalesce(fat_g, 0) >= 0 "
            "AND coalesce(fiber_g, 0) >= 0 AND coalesce(calories_kcal, 0) >= 0",
            name="macros_nonneg",
        ),
    )


class MealLabel(Base):
    """The frozen labels.v1 outcome of a meal, as computed by M1 (1-minute label basis, ADR-013)."""

    __tablename__ = "meal_labels"
    meal_id: Mapped[str] = mapped_column(
        ForeignKey("meals.meal_id", ondelete="CASCADE"), primary_key=True
    )
    labels_version: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    labels_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    window_coverage: Mapped[float] = mapped_column(Float, nullable=False)
    peak_mgdl: Mapped[float | None] = mapped_column(Float)
    peak_native_mgdl: Mapped[float | None] = mapped_column(Float)
    pre_meal_native_mgdl: Mapped[float | None] = mapped_column(Float)
    pre_meal_native_age_min: Mapped[float | None] = mapped_column(Float)
    next_meal_gap_min: Mapped[float | None] = mapped_column(Float)
    overlap_next_meal: Mapped[bool] = mapped_column(Boolean, nullable=False)
    low_cgm_coverage: Mapped[bool] = mapped_column(Boolean, nullable=False)
    no_pre_meal_native: Mapped[bool] = mapped_column(Boolean, nullable=False)
    already_high: Mapped[bool] = mapped_column(Boolean, nullable=False)
    macro_excluded: Mapped[bool] = mapped_column(Boolean, nullable=False)
    frozen_usable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    eligible: Mapped[bool] = mapped_column(Boolean, nullable=False)
    label: Mapped[int | None] = mapped_column(SmallInteger)
    exclusion_reasons: Mapped[str | None] = mapped_column(Text)
    waterfall_reason: Mapped[str] = mapped_column(String(32), nullable=False)
    ingestion_run_id: Mapped[int] = mapped_column(ForeignKey("ingestion_runs.id"), nullable=False)
    __table_args__ = (
        CheckConstraint("label IS NULL OR label IN (0, 1)", name="label_binary"),
        CheckConstraint("(label IS NOT NULL) = frozen_usable", name="label_iff_usable"),
        CheckConstraint("NOT eligible OR frozen_usable", name="eligible_implies_usable"),
        CheckConstraint("window_coverage >= 0 AND window_coverage <= 1", name="coverage_unit"),
    )


# ------------------------------------------------------------------------------------ model registry


class SupportProfileRow(Base):
    __tablename__ = "support_profiles"
    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    profile_sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    dataset_content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    quantile_lo: Mapped[float] = mapped_column(Float, nullable=False)
    quantile_hi: Mapped[float] = mapped_column(Float, nullable=False)
    rows: Mapped[int] = mapped_column(Integer, nullable=False)
    profile: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)  # SupportProfile JSON
    artifact_path: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _now()
    __table_args__ = (
        CheckConstraint(
            "quantile_lo >= 0 AND quantile_lo < quantile_hi AND quantile_hi <= 1", name="quantiles"
        ),
        CheckConstraint("rows > 0", name="rows_positive"),
    )


class ModelVersion(Base):
    __tablename__ = "model_versions"
    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    model_version: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    model_type: Mapped[ModelType] = mapped_column(_enum(ModelType, "model_type"), nullable=False)
    feature_set: Mapped[str] = mapped_column(String(64), nullable=False)
    n_columns: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    columns: Mapped[list[str]] = mapped_column(JSONB, nullable=False)  # ordered contract columns
    contract_version: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    contract_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    features_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    labels_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    training_config_sha256: Mapped[str | None] = mapped_column(String(64))
    dataset_content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    dataset_label: Mapped[str | None] = mapped_column(Text)
    threshold: Mapped[float] = mapped_column(Float, nullable=False)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    prior: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    artifact_path: Mapped[str] = mapped_column(Text, nullable=False)
    artifact_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    bundle_created_utc: Mapped[str | None] = mapped_column(String(40))
    support_profile_id: Mapped[int | None] = mapped_column(ForeignKey("support_profiles.id"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    registered_at: Mapped[datetime] = _now()
    registered_by: Mapped[str | None] = mapped_column(String(64))
    __table_args__ = (
        Index(
            "uq_model_versions_one_active",
            "is_active",
            unique=True,
            postgresql_where=text("is_active"),
        ),
        CheckConstraint("threshold > 0 AND threshold < 1", name="threshold_unit"),
        CheckConstraint("n_columns = jsonb_array_length(columns)", name="n_columns_matches"),
    )


# ------------------------------------------------------------------------------------ twin outputs


class TwinStateRow(Base):
    """An immutable twin-state/1 snapshot. state_id is the engine's content hash, so rebuilding the
    same state never creates a second row."""

    __tablename__ = "twin_states"
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    state_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    patient_id: Mapped[int] = mapped_column(
        ForeignKey("patients.id", ondelete="CASCADE"), nullable=False
    )
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    engine_version: Mapped[str] = mapped_column(String(32), nullable=False)
    lifecycle_phase: Mapped[LifecyclePhase] = mapped_column(
        _enum(LifecyclePhase, "lifecycle_phase"), nullable=False
    )
    risk_status: Mapped[RiskStatus] = mapped_column(
        _enum(RiskStatus, "risk_status"), nullable=False
    )
    current_meal_id: Mapped[str | None] = mapped_column(
        ForeignKey("meals.meal_id", ondelete="SET NULL")
    )
    model_version_id: Mapped[int | None] = mapped_column(ForeignKey("model_versions.id"))
    record_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)  # exact twin-state/1 JSON
    created_at: Mapped[datetime] = _now()
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    __table_args__ = (
        Index("ix_twin_states_patient_as_of", "patient_id", "as_of"),
        CheckConstraint("state_id ~ '^[0-9a-f]{64}$'", name="state_id_hex"),
        CheckConstraint("state->>'state_id' = state_id", name="state_id_matches_document"),
    )


class Prediction(Base):
    __tablename__ = "predictions"
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    twin_state_id: Mapped[int] = mapped_column(
        ForeignKey("twin_states.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    patient_id: Mapped[int] = mapped_column(
        ForeignKey("patients.id", ondelete="CASCADE"), nullable=False
    )
    meal_id: Mapped[str | None] = mapped_column(ForeignKey("meals.meal_id", ondelete="SET NULL"))
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    model_version_id: Mapped[int] = mapped_column(ForeignKey("model_versions.id"), nullable=False)
    status: Mapped[RiskStatus] = mapped_column(_enum(RiskStatus, "risk_status"), nullable=False)
    probability: Mapped[float | None] = mapped_column(Float)
    threshold: Mapped[float | None] = mapped_column(Float)
    above_threshold: Mapped[bool | None] = mapped_column(Boolean)
    uncertainty_level: Mapped[str | None] = mapped_column(String(16))
    created_at: Mapped[datetime] = _now()
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    __table_args__ = (
        Index("ix_predictions_patient_as_of", "patient_id", "as_of"),
        CheckConstraint(
            "probability IS NULL OR (probability >= 0 AND probability <= 1)",
            name="probability_unit",
        ),
        CheckConstraint(
            "(status = 'scored') = (probability IS NOT NULL)", name="scored_has_probability"
        ),
    )


class WhatIfRun(Base):
    __tablename__ = "what_if_runs"
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    scenario_id: Mapped[str | None] = mapped_column(String(64))
    patient_id: Mapped[int] = mapped_column(
        ForeignKey("patients.id", ondelete="CASCADE"), nullable=False
    )
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    base_state_id: Mapped[str | None] = mapped_column(String(64))
    model_version_id: Mapped[int | None] = mapped_column(ForeignKey("model_versions.id"))
    changes: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[WhatIfStatus] = mapped_column(
        _enum(WhatIfStatus, "what_if_status"), nullable=False
    )
    baseline_probability: Mapped[float | None] = mapped_column(Float)
    scenario_probability: Mapped[float | None] = mapped_column(Float)
    risk_delta: Mapped[float | None] = mapped_column(Float)
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)  # exact twin-scenario/1 JSON
    created_at: Mapped[datetime] = _now()
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    __table_args__ = (
        Index("ix_what_if_runs_patient", "patient_id", "created_at"),
        CheckConstraint(
            "(status = 'rejected') = (rejection_reason IS NOT NULL)", name="rejected_has_reason"
        ),
        CheckConstraint(
            "status <> 'ok' OR scenario_probability IS NOT NULL", name="ok_has_estimate"
        ),
        CheckConstraint(
            "status <> 'out_of_support' OR scenario_probability IS NULL", name="oos_has_no_estimate"
        ),
    )


class ReplaySession(Base):
    __tablename__ = "replay_sessions"
    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    patient_id: Mapped[int] = mapped_column(
        ForeignKey("patients.id", ondelete="CASCADE"), nullable=False
    )
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    cursor_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    step_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    last_state_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _now()
    __table_args__ = (
        CheckConstraint("start_at <= cursor_at AND cursor_at <= end_at", name="cursor_in_range"),
        CheckConstraint("step_minutes BETWEEN 1 AND 1440", name="step_range"),
    )


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    occurred_at: Mapped[datetime] = _now()
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    username: Mapped[str | None] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_type: Mapped[str | None] = mapped_column(String(32))
    resource_id: Mapped[str | None] = mapped_column(String(128))
    outcome: Mapped[AuditOutcome] = mapped_column(
        _enum(AuditOutcome, "audit_outcome"), nullable=False
    )
    status_code: Mapped[int | None] = mapped_column(SmallInteger)
    ip: Mapped[str | None] = mapped_column(String(64))
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    __table_args__ = (
        Index("ix_audit_log_occurred_at", "occurred_at"),
        Index("ix_audit_log_user_id", "user_id"),
    )
