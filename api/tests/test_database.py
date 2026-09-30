"""Migrations, constraints, ingestion and the model registry (disposable PostgreSQL; SYNTHETIC data)."""

from __future__ import annotations

import shutil
from dataclasses import replace
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from api_support import SOURCE_LABEL, alembic_config
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.exc import DataError, IntegrityError
from twin_core.twin import ModelContractError, build_state
from twin_core.twin.record import InMemorySource, PatientRecord

REQUIRED_TABLES = {
    "users",
    "sessions",
    "user_identities",
    "oauth_flows",
    "patients",
    "clinical_observations",
    "cgm_readings",
    "wearable_minutes",
    "meals",
    "meal_labels",
    "model_versions",
    "twin_states",
    "predictions",
    "what_if_runs",
    "replay_sessions",
    "audit_log",
    "ingestion_runs",
    "support_profiles",
}


# ------------------------------------------------------------------------------------ migrations


def test_fresh_database_is_reproducible_from_migrations_alone(empty_db: str) -> None:
    from alembic import command
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from twin_api.models import Base

    cfg = alembic_config(empty_db)
    command.upgrade(cfg, "head")
    e = create_engine(empty_db)
    try:
        with e.connect() as c:
            assert set(inspect(c).get_table_names()) >= REQUIRED_TABLES
            diff = compare_metadata(
                MigrationContext.configure(c, opts={"compare_type": True}), Base.metadata
            )
            assert diff == [], diff
        command.downgrade(cfg, "base")
        with e.connect() as c:
            assert set(inspect(c).get_table_names()) <= {"alembic_version"}
            assert c.scalar(text("select count(*) from pg_type where typtype = 'e'")) == 0
        command.upgrade(cfg, "head")
        with e.connect() as c:
            assert set(inspect(c).get_table_names()) >= REQUIRED_TABLES
    finally:
        e.dispose()


# ------------------------------------------------------------------------------------ constraints


@pytest.mark.parametrize(
    "sql",
    [
        "insert into users (username, password_hash, role) values ('eve', 'plaintext', 'admin')",
        "insert into users (username, password_hash, role) values ('x', '$argon2id$v=19$', 'admin')",
        "insert into users (username, password_hash, role) values ('mallory', '$argon2id$v=19$', 'root')",
        "update meal_labels set label = 1, frozen_usable = false where meal_id = (select min(meal_id) from meal_labels)",
        "update meal_labels set eligible = true, frozen_usable = false, label = null where meal_id = (select min(meal_id) from meal_labels)",
        "update meal_labels set window_coverage = 1.5 where meal_id = (select min(meal_id) from meal_labels)",
        "update cgm_readings set dexcom_mgdl = -5 where ts = (select min(ts) from cgm_readings)",
        "update cgm_readings set dexcom_mgdl = null where dexcom_is_native and ts = (select min(ts) from cgm_readings where dexcom_is_native)",
        "update meals set carbs_g = -1 where meal_id = (select min(meal_id) from meals)",
        "update model_versions set threshold = 1.5",
        "insert into model_versions select * from model_versions",
        "insert into clinical_observations (patient_id, field, provenance, ingestion_run_id) select patient_id, 'x', 'derived', ingestion_run_id from clinical_observations limit 1",
        "insert into meals (meal_id, patient_id, started_at, macro_validity, duplicate_start, source_file, source_row, ingestion_run_id) values ('orphan', 999999, now(), 'valid', false, 'f', 1, 1)",
    ],
)
def test_database_constraints_reject_bad_rows(engine: Any, loaded: Any, sql: str) -> None:
    with engine.connect() as c, pytest.raises((IntegrityError, DataError)):
        c.execute(text(sql))
    # nothing committed: every attempt ran in a transaction that failed


def test_only_one_model_can_be_active(engine: Any, loaded: Any) -> None:
    with engine.connect() as c:
        assert c.scalar(text("select count(*) from model_versions where is_active")) == 1


def test_twin_state_document_must_match_its_id(engine: Any, loaded: Any) -> None:
    with engine.connect() as c, pytest.raises(IntegrityError):
        c.execute(
            text(
                "insert into twin_states (state_id, patient_id, as_of, schema_version, engine_version,"
                " lifecycle_phase, risk_status, record_sha256, state) select repeat('a', 64), id,"
                " now(), 'twin-state/1', 'm4.1', 'COLD_START', 'unavailable', repeat('b', 64),"
                ' \'{"state_id": "different"}\'::jsonb from patients limit 1'
            )
        )


# ------------------------------------------------------------------------------------ ingestion


def test_ingestion_loads_every_m1_row_with_provenance(engine: Any, loaded: Any, m1: Any) -> None:
    t = m1["tables"]
    res = loaded["ingest"]
    people = set(t["cgm"]["participant_id"])
    assert res.status == "ingested"
    assert res.counts["patients"] == len(people)
    assert res.counts["cgm_readings"] == len(t["cgm"])
    assert res.counts["wearable_minutes"] == len(t["wearable"])
    assert res.counts["meals"] == len(t["meals"]) == res.counts["meal_labels"]
    with engine.connect() as c:
        run = (
            c.execute(text("select * from ingestion_runs where id = :i"), {"i": res.run_id})
            .mappings()
            .one()
        )
        assert run["status"] == "succeeded" and run["content_sha256"] == res.content_sha256
        assert run["m1_manifest_sha256"] == m1["m1_manifest"]["manifest_sha256"]
        assert run["m2_dataset_sha256"] == m1["m2_manifest"]["dataset_content_sha256"]
        assert run["labels_sha256"] == m1["m1_manifest"]["label_config_sha256"]
        for table in (
            "patients",
            "cgm_readings",
            "wearable_minutes",
            "meals",
            "meal_labels",
            "clinical_observations",
        ):
            other = c.scalar(
                text(f"select count(*) from {table} where ingestion_run_id <> :i"),
                {"i": res.run_id},
            )
            assert other == 0, table
        assert c.scalar(text("select count(*) from cgm_readings where dexcom_is_native")) == int(
            t["cgm"]["dexcom_is_native"].sum()
        )
        derived = c.execute(
            text("select field, derivation from clinical_observations where provenance = 'derived'")
        ).all()
        assert derived and all(d for _, d in derived)  # derived fields say how


def test_reingesting_the_same_content_is_a_no_op(
    engine: Any, loaded: Any, m1: Any, configs: Any
) -> None:
    from twin_api.ingest import ingest_tables

    again = ingest_tables(
        engine,
        m1["tables"],
        source_dir="fixture",
        source_label=SOURCE_LABEL,
        m1_manifest=m1["m1_manifest"],
        m2_manifest=m1["m2_manifest"],
        features_sha256=configs.hashes["features"],
        labels_version=configs.labels.version,
    )
    assert again.status == "already_ingested" and again.run_id == loaded["ingest"].run_id


def test_different_content_is_refused_without_replace(
    engine: Any, loaded: Any, m1: Any, configs: Any
) -> None:
    from twin_api.ingest import IngestError, ingest_tables

    changed = dict(m1["tables"])
    changed["cgm"] = changed["cgm"].assign(dexcom_mgdl=changed["cgm"]["dexcom_mgdl"] + 1)
    with pytest.raises(IngestError, match="--replace"):
        ingest_tables(
            engine,
            changed,
            source_dir="fixture",
            source_label=SOURCE_LABEL,
            m1_manifest=m1["m1_manifest"],
            m2_manifest=m1["m2_manifest"],
            features_sha256=configs.hashes["features"],
            labels_version=configs.labels.version,
        )


def test_database_record_gives_the_same_twin_state_as_the_m1_tables(
    engine: Any, loaded: Any, m1: Any, bundle: Any, configs: Any
) -> None:
    """Provenance preserved end to end: the twin sees identical data through the database."""
    from twin_api.db import make_sessionmaker
    from twin_api.repository import DbRecordSource
    from twin_core.twin import TwinRuntime

    rt = TwinRuntime(configs, bundle["bundle"])
    t = m1["tables"]
    meal = t["meals"].iloc[5]
    pid = int(meal["participant_id"])
    as_of = pd.Timestamp(meal["started_at"]) + pd.Timedelta(minutes=10)
    with make_sessionmaker(engine)() as s:
        db_rec = DbRecordSource(s, SOURCE_LABEL).record(pid)
        via_db = build_state(pid, as_of, source=DbRecordSource(s, SOURCE_LABEL), runtime=rt)
    via_tables = build_state(
        pid,
        as_of,
        runtime=rt,
        source=InMemorySource({pid: PatientRecord.from_m1_tables(t, pid, SOURCE_LABEL)}),
    )
    a = via_db.model_dump(mode="json", exclude={"state_id"})
    b = via_tables.model_dump(mode="json", exclude={"state_id"})
    a["provenance"].pop("record_sha256"), b["provenance"].pop("record_sha256")
    assert a == b
    assert len(db_rec.meals) == int((t["meals"]["participant_id"] == pid).sum())


# ------------------------------------------------------------------------------------ registry


def test_registry_entry_carries_full_model_identity(engine: Any, loaded: Any, bundle: Any) -> None:
    b = bundle["bundle"]
    with engine.connect() as c:
        row = (
            c.execute(
                text("select * from model_versions where id = :i"),
                {"i": loaded["model_version_id"]},
            )
            .mappings()
            .one()
        )
    assert row["model_type"] == "logistic" and row["feature_set"] == "full_personal"
    assert row["n_columns"] == 45 and row["columns"] == list(b.columns)
    assert row["contract_sha256"] == b.contract_sha256
    assert row["features_sha256"] == b.features_sha256 and row["labels_sha256"] == b.labels_sha256
    assert row["dataset_content_sha256"] == b.dataset_content_sha256
    assert (
        row["artifact_path"] == str(Path(bundle["path"]).resolve())
        and len(row["artifact_sha256"]) == 64
    )
    assert row["is_active"] and row["support_profile_id"] == loaded["support_profile_id"]


def test_incompatible_bundles_are_refused(
    tmp_path: Path, engine: Any, loaded: Any, bundle: Any, configs: Any
) -> None:
    from twin_api.db import make_sessionmaker
    from twin_api.registry import register_bundle
    from twin_ml.training.bundle import save_bundle

    b = bundle["bundle"]
    cases = {
        "reordered": replace(b, columns=tuple(reversed(b.columns))),
        "other_contract": replace(b, contract_sha256="0" * 64),
        "other_labels": replace(b, labels_sha256="0" * 64),
        "no_prior": replace(b, prior=None),
    }
    with make_sessionmaker(engine)() as s:
        for name, bad in cases.items():
            p = tmp_path / f"{name}.joblib"
            save_bundle(bad, p)
            with pytest.raises(ModelContractError):
                register_bundle(s, p, configs)
        s.rollback()
        assert s.scalar(text("select count(*) from model_versions")) == 1


def test_support_profile_matches_the_bundle_training_data(
    engine: Any, loaded: Any, bundle: Any
) -> None:
    with engine.connect() as c:
        sp = (
            c.execute(
                text("select * from support_profiles where id = :i"),
                {"i": loaded["support_profile_id"]},
            )
            .mappings()
            .one()
        )
    assert sp["dataset_content_sha256"] == bundle["bundle"].dataset_content_sha256
    assert (sp["quantile_lo"], sp["quantile_hi"]) == (0.01, 0.99)
    assert "carbs_g" in sp["profile"]["features"] and "p_personal" not in sp["profile"]["features"]


def test_tampered_artifact_is_refused_at_serving_time(
    tmp_path: Path, engine: Any, loaded: Any, bundle: Any, configs: Any
) -> None:
    from twin_api.db import make_sessionmaker
    from twin_api.models import ModelVersion
    from twin_api.registry import register_bundle, runtime_for

    p = tmp_path / "copy.joblib"
    shutil.copy(bundle["path"], p)
    with make_sessionmaker(engine)() as s:
        mv = register_bundle(s, p, configs)  # same identity & bytes -> the existing entry
        assert mv.id == loaded["model_version_id"]
        row = s.scalar(select(ModelVersion).where(ModelVersion.id == mv.id))
        assert row is not None
        fake = ModelVersion(
            **{
                c.name: getattr(row, c.name)
                for c in ModelVersion.__table__.columns
                if c.name not in ("id",)
            }
        )
        fake.artifact_path = str(p)
        with p.open("ab") as f:
            f.write(b"tampered")
        with pytest.raises(ModelContractError, match="changed since it was registered"):
            runtime_for(fake, configs, s)
        s.rollback()
