"""initial schema: the P0 backend (ADR-018)

Users/sessions, patients and their observations (clinical, CGM, wearable, meals, frozen labels),
the model registry and support profiles, twin snapshots, predictions, what-if runs, replay sessions,
the audit log and ingestion runs. Generated from twin_api.models, then reviewed.

Revision ID: 0001
Revises:
Create Date: 2026-09-29 16:14:07.176381+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "ingestion_runs",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column(
            "status", sa.Enum("running", "succeeded", "failed", name="run_status"), nullable=False
        ),
        sa.Column("source_label", sa.Text(), nullable=False),
        sa.Column("source_dir", sa.Text(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("m1_pipeline_version", sa.String(length=32), nullable=True),
        sa.Column("m1_manifest_sha256", sa.String(length=64), nullable=True),
        sa.Column("m2_dataset_sha256", sa.String(length=64), nullable=True),
        sa.Column("cleaning_sha256", sa.String(length=64), nullable=True),
        sa.Column("labels_sha256", sa.String(length=64), nullable=True),
        sa.Column("features_sha256", sa.String(length=64), nullable=True),
        sa.Column(
            "counts", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ingestion_runs")),
    )
    op.create_index(
        "uq_ingestion_runs_succeeded_content",
        "ingestion_runs",
        ["content_sha256"],
        unique=True,
        postgresql_where=sa.text("status = 'succeeded'"),
    )
    op.create_table(
        "support_profiles",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("profile_sha256", sa.String(length=64), nullable=False),
        sa.Column("dataset_content_sha256", sa.String(length=64), nullable=False),
        sa.Column("quantile_lo", sa.Float(), nullable=False),
        sa.Column("quantile_hi", sa.Float(), nullable=False),
        sa.Column("rows", sa.Integer(), nullable=False),
        sa.Column("profile", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("artifact_path", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "quantile_lo >= 0 AND quantile_lo < quantile_hi AND quantile_hi <= 1",
            name=op.f("ck_support_profiles_quantiles"),
        ),
        sa.CheckConstraint("rows > 0", name=op.f("ck_support_profiles_rows_positive")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_support_profiles")),
        sa.UniqueConstraint("profile_sha256", name=op.f("uq_support_profiles_profile_sha256")),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.Enum("clinician", "admin", name="user_role"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("failed_login_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "left(password_hash, 10) = '$argon2id$'", name=op.f("ck_users_argon2id_hash")
        ),
        sa.CheckConstraint(
            "username ~ '^[A-Za-z0-9_.@-]{3,64}$'", name=op.f("ck_users_username_format")
        ),
        sa.CheckConstraint(
            "failed_login_count >= 0", name=op.f("ck_users_failed_login_count_nonneg")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
    )
    op.create_index(
        "uq_users_username_lower", "users", [sa.literal_column("lower(username)")], unique=True
    )
    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("username", sa.String(length=64), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("resource_type", sa.String(length=32), nullable=True),
        sa.Column("resource_id", sa.String(length=128), nullable=True),
        sa.Column(
            "outcome", sa.Enum("success", "denied", "failed", name="audit_outcome"), nullable=False
        ),
        sa.Column("status_code", sa.SmallInteger(), nullable=True),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column(
            "detail", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_audit_log_user_id_users"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_log")),
    )
    op.create_index("ix_audit_log_occurred_at", "audit_log", ["occurred_at"], unique=False)
    op.create_index("ix_audit_log_user_id", "audit_log", ["user_id"], unique=False)
    op.create_table(
        "model_versions",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("model_version", sa.Text(), nullable=False),
        sa.Column("model_type", sa.Enum("logistic", "xgboost", name="model_type"), nullable=False),
        sa.Column("feature_set", sa.String(length=64), nullable=False),
        sa.Column("n_columns", sa.SmallInteger(), nullable=False),
        sa.Column("columns", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("contract_version", sa.SmallInteger(), nullable=False),
        sa.Column("contract_sha256", sa.String(length=64), nullable=False),
        sa.Column("features_sha256", sa.String(length=64), nullable=False),
        sa.Column("labels_sha256", sa.String(length=64), nullable=False),
        sa.Column("training_config_sha256", sa.String(length=64), nullable=True),
        sa.Column("dataset_content_sha256", sa.String(length=64), nullable=False),
        sa.Column("dataset_label", sa.Text(), nullable=True),
        sa.Column("threshold", sa.Float(), nullable=False),
        sa.Column("params", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("prior", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("artifact_path", sa.Text(), nullable=False),
        sa.Column("artifact_sha256", sa.String(length=64), nullable=False),
        sa.Column("bundle_created_utc", sa.String(length=40), nullable=True),
        sa.Column("support_profile_id", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "registered_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("registered_by", sa.String(length=64), nullable=True),
        sa.CheckConstraint(
            "n_columns = jsonb_array_length(columns)",
            name=op.f("ck_model_versions_n_columns_matches"),
        ),
        sa.CheckConstraint(
            "threshold > 0 AND threshold < 1", name=op.f("ck_model_versions_threshold_unit")
        ),
        sa.ForeignKeyConstraint(
            ["support_profile_id"],
            ["support_profiles.id"],
            name=op.f("fk_model_versions_support_profile_id_support_profiles"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_model_versions")),
        sa.UniqueConstraint("model_version", name=op.f("uq_model_versions_model_version")),
    )
    op.create_index(
        "uq_model_versions_one_active",
        "model_versions",
        ["is_active"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )
    op.create_table(
        "patients",
        sa.Column("id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("external_ref", sa.String(length=32), nullable=False),
        sa.Column(
            "glycemic_group",
            sa.Enum("healthy", "prediabetes", "T2D", "unknown", name="glycemic_group"),
            nullable=False,
        ),
        sa.Column("source_label", sa.Text(), nullable=False),
        sa.Column("ingestion_run_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("id > 0", name=op.f("ck_patients_id_positive")),
        sa.ForeignKeyConstraint(
            ["ingestion_run_id"],
            ["ingestion_runs.id"],
            name=op.f("fk_patients_ingestion_run_id_ingestion_runs"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_patients")),
        sa.UniqueConstraint("external_ref", name=op.f("uq_patients_external_ref")),
    )
    op.create_table(
        "sessions",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("token_sha256", sa.String(length=64), nullable=False),
        sa.Column("csrf_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=256), nullable=True),
        sa.CheckConstraint(
            "token_sha256 ~ '^[0-9a-f]{64}$'", name=op.f("ck_sessions_token_sha256_hex")
        ),
        sa.CheckConstraint(
            "expires_at > created_at", name=op.f("ck_sessions_expires_after_created")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_sessions_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sessions")),
        sa.UniqueConstraint("token_sha256", name=op.f("uq_sessions_token_sha256")),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"], unique=False)
    op.create_table(
        "cgm_readings",
        sa.Column("patient_id", sa.Integer(), nullable=False),
        sa.Column("ts", sa.DateTime(), nullable=False),
        sa.Column("dexcom_mgdl", sa.Float(), nullable=True),
        sa.Column("dexcom_is_native", sa.Boolean(), nullable=False),
        sa.Column("dexcom_out_of_range", sa.Boolean(), nullable=False),
        sa.Column("libre_mgdl", sa.Float(), nullable=True),
        sa.Column("libre_is_native", sa.Boolean(), nullable=False),
        sa.Column("libre_out_of_range", sa.Boolean(), nullable=False),
        sa.Column("duplicate_conflict", sa.Boolean(), nullable=False),
        sa.Column("ingestion_run_id", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "NOT dexcom_is_native OR dexcom_mgdl IS NOT NULL",
            name=op.f("ck_cgm_readings_native_has_value"),
        ),
        sa.CheckConstraint(
            "dexcom_mgdl IS NULL OR dexcom_mgdl > 0", name=op.f("ck_cgm_readings_dexcom_positive")
        ),
        sa.CheckConstraint(
            "libre_mgdl IS NULL OR libre_mgdl > 0", name=op.f("ck_cgm_readings_libre_positive")
        ),
        sa.ForeignKeyConstraint(
            ["ingestion_run_id"],
            ["ingestion_runs.id"],
            name=op.f("fk_cgm_readings_ingestion_run_id_ingestion_runs"),
        ),
        sa.ForeignKeyConstraint(
            ["patient_id"],
            ["patients.id"],
            name=op.f("fk_cgm_readings_patient_id_patients"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("patient_id", "ts", name=op.f("pk_cgm_readings")),
    )
    op.create_table(
        "clinical_observations",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("patient_id", sa.Integer(), nullable=False),
        sa.Column("field", sa.String(length=64), nullable=False),
        sa.Column("value_num", sa.Float(), nullable=True),
        sa.Column("value_text", sa.Text(), nullable=True),
        sa.Column("unit", sa.String(length=32), nullable=True),
        sa.Column(
            "provenance", sa.Enum("observed", "derived", name="field_provenance"), nullable=False
        ),
        sa.Column("derivation", sa.Text(), nullable=True),
        sa.Column("quality_flag", sa.Text(), nullable=True),
        sa.Column("source_file", sa.Text(), nullable=True),
        sa.Column("source_column", sa.Text(), nullable=True),
        sa.Column("ingestion_run_id", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "provenance = 'observed' OR derivation IS NOT NULL",
            name=op.f("ck_clinical_observations_derived_has_derivation"),
        ),
        sa.ForeignKeyConstraint(
            ["ingestion_run_id"],
            ["ingestion_runs.id"],
            name=op.f("fk_clinical_observations_ingestion_run_id_ingestion_runs"),
        ),
        sa.ForeignKeyConstraint(
            ["patient_id"],
            ["patients.id"],
            name=op.f("fk_clinical_observations_patient_id_patients"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_clinical_observations")),
        sa.UniqueConstraint("patient_id", "field", name="uq_clinical_observations_patient_field"),
    )
    op.create_table(
        "meals",
        sa.Column("meal_id", sa.String(length=32), nullable=False),
        sa.Column("patient_id", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("meal_type", sa.String(length=32), nullable=True),
        sa.Column("meal_type_raw", sa.Text(), nullable=True),
        sa.Column("carbs_g", sa.Float(), nullable=True),
        sa.Column("protein_g", sa.Float(), nullable=True),
        sa.Column("fat_g", sa.Float(), nullable=True),
        sa.Column("fiber_g", sa.Float(), nullable=True),
        sa.Column("calories_kcal", sa.Float(), nullable=True),
        sa.Column("amount_consumed_pct", sa.Float(), nullable=True),
        sa.Column(
            "macro_validity",
            sa.Enum("valid", "missing", "invalid", "empty", "inconsistent", name="macro_validity"),
            nullable=False,
        ),
        sa.Column("macro_reasons", sa.Text(), nullable=True),
        sa.Column("energy_ratio", sa.Float(), nullable=True),
        sa.Column("duplicate_start", sa.Boolean(), nullable=False),
        sa.Column("image_path", sa.Text(), nullable=True),
        sa.Column("source_file", sa.Text(), nullable=False),
        sa.Column("source_row", sa.Integer(), nullable=False),
        sa.Column("ingestion_run_id", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "coalesce(carbs_g, 0) >= 0 AND coalesce(protein_g, 0) >= 0 AND coalesce(fat_g, 0) >= 0 AND coalesce(fiber_g, 0) >= 0 AND coalesce(calories_kcal, 0) >= 0",
            name=op.f("ck_meals_macros_nonneg"),
        ),
        sa.ForeignKeyConstraint(
            ["ingestion_run_id"],
            ["ingestion_runs.id"],
            name=op.f("fk_meals_ingestion_run_id_ingestion_runs"),
        ),
        sa.ForeignKeyConstraint(
            ["patient_id"],
            ["patients.id"],
            name=op.f("fk_meals_patient_id_patients"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("meal_id", name=op.f("pk_meals")),
    )
    op.create_index("ix_meals_patient_started", "meals", ["patient_id", "started_at"], unique=False)
    op.create_table(
        "replay_sessions",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("patient_id", sa.Integer(), nullable=False),
        sa.Column("start_at", sa.DateTime(), nullable=False),
        sa.Column("end_at", sa.DateTime(), nullable=False),
        sa.Column("cursor_at", sa.DateTime(), nullable=False),
        sa.Column("step_minutes", sa.Integer(), nullable=False),
        sa.Column("last_state_id", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "start_at <= cursor_at AND cursor_at <= end_at",
            name=op.f("ck_replay_sessions_cursor_in_range"),
        ),
        sa.CheckConstraint(
            "step_minutes BETWEEN 1 AND 1440", name=op.f("ck_replay_sessions_step_range")
        ),
        sa.ForeignKeyConstraint(
            ["patient_id"],
            ["patients.id"],
            name=op.f("fk_replay_sessions_patient_id_patients"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_replay_sessions_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_replay_sessions")),
    )
    op.create_table(
        "wearable_minutes",
        sa.Column("patient_id", sa.Integer(), nullable=False),
        sa.Column("ts", sa.DateTime(), nullable=False),
        sa.Column("hr_bpm", sa.Float(), nullable=True),
        sa.Column("mets", sa.Float(), nullable=True),
        sa.Column("activity_kcal", sa.Float(), nullable=True),
        sa.Column("hr_out_of_range", sa.Boolean(), nullable=False),
        sa.Column("mets_out_of_range", sa.Boolean(), nullable=False),
        sa.Column("ingestion_run_id", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "activity_kcal IS NULL OR activity_kcal >= 0",
            name=op.f("ck_wearable_minutes_kcal_nonneg"),
        ),
        sa.CheckConstraint(
            "hr_bpm IS NULL OR hr_bpm > 0", name=op.f("ck_wearable_minutes_hr_positive")
        ),
        sa.CheckConstraint(
            "mets IS NULL OR mets >= 0", name=op.f("ck_wearable_minutes_mets_nonneg")
        ),
        sa.ForeignKeyConstraint(
            ["ingestion_run_id"],
            ["ingestion_runs.id"],
            name=op.f("fk_wearable_minutes_ingestion_run_id_ingestion_runs"),
        ),
        sa.ForeignKeyConstraint(
            ["patient_id"],
            ["patients.id"],
            name=op.f("fk_wearable_minutes_patient_id_patients"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("patient_id", "ts", name=op.f("pk_wearable_minutes")),
    )
    op.create_table(
        "what_if_runs",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("scenario_id", sa.String(length=64), nullable=True),
        sa.Column("patient_id", sa.Integer(), nullable=False),
        sa.Column("as_of", sa.DateTime(), nullable=False),
        sa.Column("base_state_id", sa.String(length=64), nullable=True),
        sa.Column("model_version_id", sa.Integer(), nullable=True),
        sa.Column("changes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "status",
            sa.Enum("ok", "out_of_support", "rejected", name="what_if_status"),
            nullable=False,
        ),
        sa.Column("baseline_probability", sa.Float(), nullable=True),
        sa.Column("scenario_probability", sa.Float(), nullable=True),
        sa.Column("risk_delta", sa.Float(), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "(status = 'rejected') = (rejection_reason IS NOT NULL)",
            name=op.f("ck_what_if_runs_rejected_has_reason"),
        ),
        sa.CheckConstraint(
            "status <> 'ok' OR scenario_probability IS NOT NULL",
            name=op.f("ck_what_if_runs_ok_has_estimate"),
        ),
        sa.CheckConstraint(
            "status <> 'out_of_support' OR scenario_probability IS NULL",
            name=op.f("ck_what_if_runs_oos_has_no_estimate"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_what_if_runs_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["model_version_id"],
            ["model_versions.id"],
            name=op.f("fk_what_if_runs_model_version_id_model_versions"),
        ),
        sa.ForeignKeyConstraint(
            ["patient_id"],
            ["patients.id"],
            name=op.f("fk_what_if_runs_patient_id_patients"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_what_if_runs")),
    )
    op.create_index(
        "ix_what_if_runs_patient", "what_if_runs", ["patient_id", "created_at"], unique=False
    )
    op.create_table(
        "meal_labels",
        sa.Column("meal_id", sa.String(length=32), nullable=False),
        sa.Column("labels_version", sa.SmallInteger(), nullable=False),
        sa.Column("labels_sha256", sa.String(length=64), nullable=False),
        sa.Column("window_coverage", sa.Float(), nullable=False),
        sa.Column("peak_mgdl", sa.Float(), nullable=True),
        sa.Column("peak_native_mgdl", sa.Float(), nullable=True),
        sa.Column("pre_meal_native_mgdl", sa.Float(), nullable=True),
        sa.Column("pre_meal_native_age_min", sa.Float(), nullable=True),
        sa.Column("next_meal_gap_min", sa.Float(), nullable=True),
        sa.Column("overlap_next_meal", sa.Boolean(), nullable=False),
        sa.Column("low_cgm_coverage", sa.Boolean(), nullable=False),
        sa.Column("no_pre_meal_native", sa.Boolean(), nullable=False),
        sa.Column("already_high", sa.Boolean(), nullable=False),
        sa.Column("macro_excluded", sa.Boolean(), nullable=False),
        sa.Column("frozen_usable", sa.Boolean(), nullable=False),
        sa.Column("eligible", sa.Boolean(), nullable=False),
        sa.Column("label", sa.SmallInteger(), nullable=True),
        sa.Column("exclusion_reasons", sa.Text(), nullable=True),
        sa.Column("waterfall_reason", sa.String(length=32), nullable=False),
        sa.Column("ingestion_run_id", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "(label IS NOT NULL) = frozen_usable", name=op.f("ck_meal_labels_label_iff_usable")
        ),
        sa.CheckConstraint(
            "NOT eligible OR frozen_usable", name=op.f("ck_meal_labels_eligible_implies_usable")
        ),
        sa.CheckConstraint(
            "label IS NULL OR label IN (0, 1)", name=op.f("ck_meal_labels_label_binary")
        ),
        sa.CheckConstraint(
            "window_coverage >= 0 AND window_coverage <= 1",
            name=op.f("ck_meal_labels_coverage_unit"),
        ),
        sa.ForeignKeyConstraint(
            ["ingestion_run_id"],
            ["ingestion_runs.id"],
            name=op.f("fk_meal_labels_ingestion_run_id_ingestion_runs"),
        ),
        sa.ForeignKeyConstraint(
            ["meal_id"],
            ["meals.meal_id"],
            name=op.f("fk_meal_labels_meal_id_meals"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("meal_id", name=op.f("pk_meal_labels")),
    )
    op.create_table(
        "twin_states",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("state_id", sa.String(length=64), nullable=False),
        sa.Column("patient_id", sa.Integer(), nullable=False),
        sa.Column("as_of", sa.DateTime(), nullable=False),
        sa.Column("schema_version", sa.String(length=32), nullable=False),
        sa.Column("engine_version", sa.String(length=32), nullable=False),
        sa.Column(
            "lifecycle_phase",
            sa.Enum("COLD_START", "WARMING", "PERSONALIZED", name="lifecycle_phase"),
            nullable=False,
        ),
        sa.Column(
            "risk_status",
            sa.Enum("scored", "not_applicable", "unavailable", name="risk_status"),
            nullable=False,
        ),
        sa.Column("current_meal_id", sa.String(length=32), nullable=True),
        sa.Column("model_version_id", sa.Integer(), nullable=True),
        sa.Column("record_sha256", sa.String(length=64), nullable=False),
        sa.Column("state", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "state->>'state_id' = state_id", name=op.f("ck_twin_states_state_id_matches_document")
        ),
        sa.CheckConstraint("state_id ~ '^[0-9a-f]{64}$'", name=op.f("ck_twin_states_state_id_hex")),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_twin_states_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["current_meal_id"],
            ["meals.meal_id"],
            name=op.f("fk_twin_states_current_meal_id_meals"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["model_version_id"],
            ["model_versions.id"],
            name=op.f("fk_twin_states_model_version_id_model_versions"),
        ),
        sa.ForeignKeyConstraint(
            ["patient_id"],
            ["patients.id"],
            name=op.f("fk_twin_states_patient_id_patients"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_twin_states")),
        sa.UniqueConstraint("state_id", name=op.f("uq_twin_states_state_id")),
    )
    op.create_index(
        "ix_twin_states_patient_as_of", "twin_states", ["patient_id", "as_of"], unique=False
    )
    op.create_table(
        "predictions",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("twin_state_id", sa.BigInteger(), nullable=False),
        sa.Column("patient_id", sa.Integer(), nullable=False),
        sa.Column("meal_id", sa.String(length=32), nullable=True),
        sa.Column("as_of", sa.DateTime(), nullable=False),
        sa.Column("model_version_id", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("scored", "not_applicable", "unavailable", name="risk_status"),
            nullable=False,
        ),
        sa.Column("probability", sa.Float(), nullable=True),
        sa.Column("threshold", sa.Float(), nullable=True),
        sa.Column("above_threshold", sa.Boolean(), nullable=True),
        sa.Column("uncertainty_level", sa.String(length=16), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "(status = 'scored') = (probability IS NOT NULL)",
            name=op.f("ck_predictions_scored_has_probability"),
        ),
        sa.CheckConstraint(
            "probability IS NULL OR (probability >= 0 AND probability <= 1)",
            name=op.f("ck_predictions_probability_unit"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_predictions_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["meal_id"],
            ["meals.meal_id"],
            name=op.f("fk_predictions_meal_id_meals"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["model_version_id"],
            ["model_versions.id"],
            name=op.f("fk_predictions_model_version_id_model_versions"),
        ),
        sa.ForeignKeyConstraint(
            ["patient_id"],
            ["patients.id"],
            name=op.f("fk_predictions_patient_id_patients"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["twin_state_id"],
            ["twin_states.id"],
            name=op.f("fk_predictions_twin_state_id_twin_states"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_predictions")),
        sa.UniqueConstraint("twin_state_id", name=op.f("uq_predictions_twin_state_id")),
    )
    op.create_index(
        "ix_predictions_patient_as_of", "predictions", ["patient_id", "as_of"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_predictions_patient_as_of", table_name="predictions")
    op.drop_table("predictions")
    op.drop_index("ix_twin_states_patient_as_of", table_name="twin_states")
    op.drop_table("twin_states")
    op.drop_table("meal_labels")
    op.drop_index("ix_what_if_runs_patient", table_name="what_if_runs")
    op.drop_table("what_if_runs")
    op.drop_table("wearable_minutes")
    op.drop_table("replay_sessions")
    op.drop_index("ix_meals_patient_started", table_name="meals")
    op.drop_table("meals")
    op.drop_table("clinical_observations")
    op.drop_table("cgm_readings")
    op.drop_index("ix_sessions_user_id", table_name="sessions")
    op.drop_table("sessions")
    op.drop_table("patients")
    op.drop_index(
        "uq_model_versions_one_active",
        table_name="model_versions",
        postgresql_where=sa.text("is_active"),
    )
    op.drop_table("model_versions")
    op.drop_index("ix_audit_log_user_id", table_name="audit_log")
    op.drop_index("ix_audit_log_occurred_at", table_name="audit_log")
    op.drop_table("audit_log")
    op.drop_index("uq_users_username_lower", table_name="users")
    op.drop_table("users")
    op.drop_table("support_profiles")
    op.drop_index(
        "uq_ingestion_runs_succeeded_content",
        table_name="ingestion_runs",
        postgresql_where=sa.text("status = 'succeeded'"),
    )
    op.drop_table("ingestion_runs")
    # PostgreSQL enum types are not dropped with their tables
    sa.Enum(name="run_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="user_role").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="audit_outcome").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="model_type").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="glycemic_group").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="field_provenance").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="macro_validity").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="what_if_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="lifecycle_phase").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="risk_status").drop(op.get_bind(), checkfirst=True)
