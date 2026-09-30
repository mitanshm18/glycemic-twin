"""Deterministic ingestion of the processed M1/M2 artifacts into PostgreSQL.

Reads ``data/processed/m1/*.parquet`` (clean tables) and the M1/M2 run manifests. It never touches
the raw CGMacros folder (no photos, nothing re-cleaned) and never re-derives any value: rows are
copied as M1 produced them, with the ingestion run recorded on every row.

Determinism and idempotence:
- rows are sorted by their keys before loading; the run records a SHA-256 over every table's content;
- ingesting the same content twice is a no-op that returns the earlier run;
- different content refuses to overwrite existing data unless ``replace=True``.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import Connection, Engine, delete, insert, select, update

from twin_api.models import (
    ClinicalObservation,
    GlycemicGroup,
    IngestionRun,
    Patient,
    RunStatus,
)

M1_TABLES = ("clinical_wide", "clinical_long", "meals", "meal_outcomes", "cgm", "wearable")
KIND = "m1_m2_processed"


class IngestError(RuntimeError):
    """The artifacts are missing, inconsistent, or would overwrite different data."""


@dataclass(frozen=True)
class IngestResult:
    run_id: int
    status: str  # "ingested" | "already_ingested"
    content_sha256: str
    counts: dict[str, int]


def table_sha256(df: pd.DataFrame) -> str:
    h = hashlib.sha256()
    h.update(json.dumps([[str(c), str(t)] for c, t in df.dtypes.items()]).encode())
    h.update(pd.util.hash_pandas_object(df, index=False).to_numpy().tobytes())
    return h.hexdigest()


def load_processed(root: Path) -> tuple[dict[str, pd.DataFrame], dict[str, Any], dict[str, Any]]:
    m1 = root / "data/processed/m1"
    missing = [t for t in M1_TABLES if not (m1 / f"{t}.parquet").exists()]
    if missing:
        raise IngestError(f"M1 outputs missing in {m1}: {missing}. Run `make m1` first.")
    tables = {t: pd.read_parquet(m1 / f"{t}.parquet") for t in M1_TABLES}
    m1_manifest = json.loads((m1 / "run_manifest.json").read_text())
    m2_path = root / "data/processed/m2/run_manifest.json"
    if not m2_path.exists():
        raise IngestError(f"{m2_path} missing. Run `make m2` first.")
    return tables, m1_manifest, json.loads(m2_path.read_text())


def _sorted(tables: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    keys = {
        "clinical_wide": ["subject_id"],
        "clinical_long": ["subject_id", "field"],
        "meals": ["participant_id", "started_at", "meal_id"],
        "meal_outcomes": ["participant_id", "meal_id"],
        "cgm": ["participant_id", "ts"],
        "wearable": ["participant_id", "ts"],
    }
    return {
        t: tables[t].sort_values(keys[t], kind="stable").reset_index(drop=True) for t in M1_TABLES
    }


def content_sha256(tables: dict[str, pd.DataFrame]) -> tuple[str, dict[str, str]]:
    per = {t: table_sha256(tables[t]) for t in M1_TABLES}
    return hashlib.sha256(json.dumps(per, sort_keys=True).encode()).hexdigest(), per


def _py(v: Any) -> Any:
    """numpy/pandas scalar -> plain Python; NaN/NaT/NA -> None."""
    if v is None or v is pd.NA or v is pd.NaT:
        return None
    if isinstance(v, float | np.floating):
        return None if np.isnan(v) else float(v)
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, np.bool_):
        return bool(v)
    if isinstance(v, pd.Timestamp):
        return v.to_pydatetime()
    if isinstance(v, np.datetime64):
        return None if np.isnat(v) else pd.Timestamp(v).to_pydatetime()
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    return v


def _rows(df: pd.DataFrame, cols: list[str]) -> Iterator[tuple[Any, ...]]:
    for rec in df[cols].itertuples(index=False, name=None):
        yield tuple(_py(v) for v in rec)


def _copy(conn: Connection, table: str, cols: list[str], rows: Iterable[tuple[Any, ...]]) -> int:
    raw = conn.connection.driver_connection
    n = 0
    with raw.cursor() as cur, cur.copy(f"COPY {table} ({', '.join(cols)}) FROM STDIN") as cp:  # type: ignore[union-attr]
        for r in rows:
            cp.write_row(r)
            n += 1
    return n


def _check(tables: dict[str, pd.DataFrame]) -> list[int]:
    ts_people = sorted(set(tables["cgm"]["participant_id"].astype(int)))
    if not ts_people:
        raise IngestError("no participants with time series")
    bio = set(tables["clinical_wide"]["subject_id"].astype(int))
    if set(ts_people) - bio:
        raise IngestError(f"participants without clinical rows: {sorted(set(ts_people) - bio)}")
    if not set(tables["meal_outcomes"]["meal_id"]) <= set(tables["meals"]["meal_id"]):
        raise IngestError("meal_outcomes reference unknown meals")
    if set(tables["meals"]["participant_id"].astype(int)) - set(ts_people):
        raise IngestError("meals for participants without time series")
    return ts_people


def ingest_tables(
    engine: Engine,
    tables: dict[str, pd.DataFrame],
    *,
    source_dir: str,
    source_label: str,
    m1_manifest: dict[str, Any] | None,
    m2_manifest: dict[str, Any] | None,
    features_sha256: str,
    labels_version: int,
    replace: bool = False,
) -> IngestResult:
    tables = _sorted(tables)
    people = _check(tables)
    digest, per_table = content_sha256(tables)
    m1_manifest, m2_manifest = m1_manifest or {}, m2_manifest or {}
    labels_sha = m1_manifest.get("label_config_sha256")

    with engine.begin() as conn:
        done = conn.execute(
            select(IngestionRun).where(
                IngestionRun.content_sha256 == digest, IngestionRun.status == RunStatus.succeeded
            )
        ).first()
        if done is not None:
            return IngestResult(done.id, "already_ingested", digest, dict(done.counts))
        existing = conn.execute(select(Patient.id).limit(1)).first()
        if existing is not None and not replace:
            raise IngestError(
                "the database already holds different patient data; re-run with --replace to "
                "delete it (and every twin state, prediction and replay derived from it)"
            )
        if replace:
            conn.execute(delete(Patient))
        run_id = conn.execute(
            insert(IngestionRun)
            .values(
                kind=KIND,
                status=RunStatus.running,
                source_label=source_label,
                source_dir=source_dir,
                content_sha256=digest,
                m1_pipeline_version=m1_manifest.get("pipeline_version"),
                m1_manifest_sha256=m1_manifest.get("manifest_sha256"),
                m2_dataset_sha256=m2_manifest.get("dataset_content_sha256"),
                cleaning_sha256=m1_manifest.get("cleaning_config_sha256"),
                labels_sha256=labels_sha,
                features_sha256=features_sha256,
                counts={"table_sha256": per_table},
            )
            .returning(IngestionRun.id)
        ).scalar_one()

        wide = tables["clinical_wide"]
        wide = wide[wide["subject_id"].astype(int).isin(people)]
        groups = {str(g.value) for g in GlycemicGroup}
        patients = [
            {
                "id": int(r["subject_id"]),
                "external_ref": f"CGMacros-{int(r['subject_id']):03d}",
                "glycemic_group": r["glycemic_group"]
                if r["glycemic_group"] in groups
                else "unknown",
                "source_label": source_label,
                "ingestion_run_id": run_id,
            }
            for _, r in wide.iterrows()
        ]
        conn.execute(insert(Patient), patients)

        cl = tables["clinical_long"]
        cl = cl[cl["subject_id"].astype(int).isin(people)]
        clin_cols = [
            "field",
            "value_num",
            "value_text",
            "unit",
            "provenance",
            "derivation",
            "quality_flag",
            "source_file",
            "source_column",
        ]
        conn.execute(
            insert(ClinicalObservation),
            [
                {
                    "patient_id": int(r[0]),
                    **dict(zip(clin_cols, r[1:], strict=True)),
                    "ingestion_run_id": run_id,
                }
                for r in _rows(
                    cl.assign(**{c: cl.get(c) for c in clin_cols}),
                    ["subject_id", *clin_cols],
                )
            ],
        )

        cgm_cols = [
            "participant_id",
            "ts",
            "dexcom_mgdl",
            "dexcom_is_native",
            "dexcom_out_of_range",
            "libre_mgdl",
            "libre_is_native",
            "libre_out_of_range",
            "duplicate_conflict",
        ]
        n_cgm = _copy(
            conn,
            "cgm_readings",
            ["patient_id", *cgm_cols[1:], "ingestion_run_id"],
            (r + (run_id,) for r in _rows(tables["cgm"], cgm_cols)),
        )
        wear_cols = [
            "participant_id",
            "ts",
            "hr_bpm",
            "mets",
            "activity_kcal",
            "hr_out_of_range",
            "mets_out_of_range",
        ]
        n_wear = _copy(
            conn,
            "wearable_minutes",
            ["patient_id", *wear_cols[1:], "ingestion_run_id"],
            (r + (run_id,) for r in _rows(tables["wearable"], wear_cols)),
        )

        meal_cols = [
            "meal_id",
            "participant_id",
            "started_at",
            "meal_type",
            "meal_type_raw",
            "carbs_g",
            "protein_g",
            "fat_g",
            "fiber_g",
            "calories_kcal",
            "amount_consumed_pct",
            "macro_validity",
            "macro_reasons",
            "energy_ratio",
            "duplicate_start",
            "image_path",
            "source_file",
            "source_row",
        ]
        n_meals = _copy(
            conn,
            "meals",
            ["meal_id", "patient_id", *meal_cols[2:], "ingestion_run_id"],
            (r + (run_id,) for r in _rows(tables["meals"], meal_cols)),
        )
        out_cols = [
            "meal_id",
            "window_coverage",
            "peak_mgdl",
            "peak_native_mgdl",
            "pre_meal_native_mgdl",
            "pre_meal_native_age_min",
            "next_meal_gap_min",
            "overlap_next_meal",
            "low_cgm_coverage",
            "no_pre_meal_native",
            "already_high",
            "macro_excluded",
            "frozen_usable",
            "eligible",
            "label",
            "exclusion_reasons",
            "waterfall_reason",
        ]
        n_labels = _copy(
            conn,
            "meal_labels",
            [out_cols[0], "labels_version", "labels_sha256", *out_cols[1:], "ingestion_run_id"],
            (
                (r[0], labels_version, labels_sha, *r[1:], run_id)
                for r in _rows(tables["meal_outcomes"], out_cols)
            ),
        )
        counts: dict[str, Any] = {
            "patients": len(patients),
            "clinical_observations": len(cl),
            "cgm_readings": n_cgm,
            "wearable_minutes": n_wear,
            "meals": n_meals,
            "meal_labels": n_labels,
            "bio_subjects_without_time_series": int(len(tables["clinical_wide"]) - len(wide)),
            "table_sha256": per_table,
        }
        conn.execute(
            update(IngestionRun)
            .where(IngestionRun.id == run_id)
            .values(status=RunStatus.succeeded, counts=counts, finished_at=datetime.now(UTC))
        )
    return IngestResult(
        run_id, "ingested", digest, {k: v for k, v in counts.items() if isinstance(v, int)}
    )


def record_failure(engine: Engine, source_dir: str, source_label: str, error: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            insert(IngestionRun).values(
                kind=KIND,
                status=RunStatus.failed,
                source_label=source_label,
                source_dir=source_dir,
                content_sha256="0" * 64,
                error=error[:2000],
                finished_at=datetime.now(UTC),
            )
        )
