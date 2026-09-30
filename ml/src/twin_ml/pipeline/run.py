"""Orchestrate M1: verify source -> stage -> clean -> outcomes -> audit -> write outputs.

Outputs (under the repo):
  data/manifests/cgmacros-1.0.0.lock.json   pinned CSV manifest (first run) / verified (later runs)
  data/processed/m1/*.parquet               clean layer + meal outcomes (gitignored)
  data/processed/m1/run_manifest.json       config hashes, source hash, table content hashes
  data/reports/m1_audit.json | .md          the audit
  docs/data-card.md                         AUTO block refreshed
The raw source is only ever read.
"""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from twin_core.cleaning.clinical import clean_clinical
from twin_core.config import load_cleaning_config, load_label_config

from twin_ml.pipeline.audit import build_audit, reconcile_phase0a
from twin_ml.pipeline.clean import ParticipantResult, clean_participant
from twin_ml.pipeline.contracts import ContractError, StageReport, stage_bio, stage_participant
from twin_ml.pipeline.manifest import build_manifest, verify_official, verify_or_pin
from twin_ml.pipeline.report import dumps, full_markdown, summary_markdown, update_data_card
from twin_ml.pipeline.source import RawSource

PIPELINE_VERSION = "m1.1"


@dataclass(frozen=True)
class Paths:
    root: Path

    @property
    def cleaning_config(self) -> Path:
        return self.root / "data/configs/cleaning.v1.yaml"

    @property
    def label_config(self) -> Path:
        return self.root / "data/configs/labels.v1.yaml"

    @property
    def lock(self) -> Path:
        return self.root / "data/manifests/cgmacros-1.0.0.lock.json"

    @property
    def processed(self) -> Path:
        return self.root / "data/processed/m1"

    @property
    def reports(self) -> Path:
        return self.root / "data/reports"

    @property
    def phase0a(self) -> Path:
        return self.root / "data/reference/phase0a_audit_results.json"

    @property
    def data_card(self) -> Path:
        return self.root / "docs/data-card.md"


def content_sha256(df: pd.DataFrame) -> str:
    """Hash of a table's content (columns, dtypes, values), independent of file format."""
    h = hashlib.sha256()
    h.update(json.dumps([[c, str(t)] for c, t in df.dtypes.items()]).encode())
    h.update(pd.util.hash_pandas_object(df, index=False).to_numpy().tobytes())
    return h.hexdigest()


def _git_sha(root: Path) -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
        return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


@dataclass
class M1Result:
    audit: dict[str, Any]
    reconciliation: list[dict[str, Any]] | None
    tables: dict[str, pd.DataFrame]
    run_manifest: dict[str, Any]


def run_m1(
    source_path: Path,
    root: Path,
    official_sums: Path | None = None,
    write_outputs: bool = True,
) -> M1Result:
    paths = Paths(root)
    ccfg, ccfg_sha = load_cleaning_config(paths.cleaning_config)
    lcfg, lcfg_sha = load_label_config(paths.label_config)

    source = RawSource.open(source_path)
    official = verify_official(source, official_sums)
    manifest = build_manifest(source)
    lock = verify_or_pin(manifest, paths.lock)

    supp = source.supplementary_files()
    if "bio.csv" not in supp:
        raise ContractError("bio.csv not found at the dataset root")
    bio_staged, bio_source_cols = stage_bio(source.read_csv(supp["bio.csv"]))
    clinical_wide, clinical_long = clean_clinical(bio_staged, ccfg.clinical, bio_source_cols)

    results: list[ParticipantResult] = []
    reports: dict[int, StageReport] = {}
    for pid, rel in source.participant_files().items():
        staged, rep = stage_participant(source.read_csv(rel), pid, rel)
        reports[pid] = rep
        results.append(clean_participant(staged, set(rep.columns_present), ccfg, lcfg))

    audit = build_audit(results, reports, clinical_wide, ccfg, lcfg)
    audit["provenance"] = {
        "pipeline_version": PIPELINE_VERSION,
        "source_kind": source.kind,
        "source_name": source.path.name,
        "manifest_sha256": manifest["manifest_sha256"],
        "csv_files": len(manifest["csv_files"]),  # type: ignore[arg-type]
        "non_csv_files": manifest["non_csv_file_count"],
        "official_check": asdict(official),
        "lock_check": {"status": lock.status, "lock": Path(lock.lock_path).name},
        "cleaning_config_version": ccfg.version,
        "cleaning_config_sha256": ccfg_sha,
        "label_config_version": lcfg.version,
        "label_config_sha256": lcfg_sha,
    }
    reconciliation = None
    if paths.phase0a.exists():
        reconciliation = reconcile_phase0a(audit, json.loads(paths.phase0a.read_text()))
        mismatched = [
            r["quantity"] for r in reconciliation if r["expected_equal"] and not r["match"]
        ]
        if mismatched:
            audit["issues"].append(
                {
                    "level": "warning",
                    "issue": f"differs from the Phase 0A audit where equality was expected: {mismatched}",
                }
            )

    group_of = dict(zip(clinical_wide["subject_id"], clinical_wide["glycemic_group"], strict=True))
    meals = pd.concat([r.meals for r in results], ignore_index=True)
    outcomes = pd.concat([r.outcomes for r in results], ignore_index=True)
    outcomes["glycemic_group"] = outcomes["participant_id"].map(group_of).fillna("unknown")
    tables = {
        "clinical_wide": clinical_wide,
        "clinical_long": clinical_long,
        "meals": meals,
        "meal_outcomes": outcomes,
        "cgm": pd.concat([r.cgm for r in results], ignore_index=True),
        "wearable": pd.concat([r.wearable for r in results], ignore_index=True),
    }
    run_manifest = {
        "pipeline_version": PIPELINE_VERSION,
        "manifest_sha256": manifest["manifest_sha256"],
        "cleaning_config_sha256": ccfg_sha,
        "label_config_sha256": lcfg_sha,
        "tables": {
            name: {"rows": len(df), "content_sha256": content_sha256(df)}
            for name, df in tables.items()
        },
        "environment": {
            "python": platform.python_version(),
            "pandas": pd.__version__,
            "numpy": np.__version__,
        },
        "git_sha": _git_sha(root),
    }

    if write_outputs:
        paths.processed.mkdir(parents=True, exist_ok=True)
        for name, df in tables.items():
            df.to_parquet(paths.processed / f"{name}.parquet", index=False)
        (paths.processed / "run_manifest.json").write_text(dumps(run_manifest))
        paths.reports.mkdir(parents=True, exist_ok=True)
        (paths.reports / "m1_audit.json").write_text(
            dumps({**audit, "reconciliation": reconciliation})
        )
        (paths.reports / "m1_audit.md").write_text(full_markdown(audit, reconciliation))
        if paths.data_card.exists():
            update_data_card(paths.data_card, summary_markdown(audit))
    return M1Result(audit, reconciliation, tables, run_manifest)
