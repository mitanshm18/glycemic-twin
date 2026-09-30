"""Orchestrate M2: M1 tables -> features -> folds -> leakage checks -> dataset + report.

Outputs:
  data/manifests/folds.v1.csv            participant folds (pinned on first run, then verified)
  data/processed/m2/dataset.parquet      meal-level dataset (gitignored)
  data/processed/m2/run_manifest.json    config hashes and content hash
  data/reports/m2_dataset.{json,md}      feature availability, fold balance, leakage checks
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from twin_core.config import load_feature_config, load_label_config

from twin_ml.dataset.build import build_dataset
from twin_ml.dataset.folds import assign_folds, verify_or_pin_folds
from twin_ml.dataset.leakage import (
    check_feature_names,
    check_folds,
    check_overlap,
    check_source_times,
    check_truncation,
    raise_on_failures,
    single_feature_aurocs,
)
from twin_ml.pipeline.report import dumps
from twin_ml.pipeline.run import content_sha256

M1_TABLES = ("clinical_wide", "meals", "meal_outcomes", "cgm", "wearable")


@dataclass
class M2Result:
    dataset: pd.DataFrame
    report: dict[str, Any]
    run_manifest: dict[str, Any]


def load_m1_tables(root: Path) -> dict[str, pd.DataFrame]:
    folder = root / "data/processed/m1"
    missing = [t for t in M1_TABLES if not (folder / f"{t}.parquet").exists()]
    if missing:
        raise FileNotFoundError(f"M1 outputs missing in {folder}: {missing}. Run `make m1` first.")
    return {t: pd.read_parquet(folder / f"{t}.parquet") for t in M1_TABLES}


def _fold_table(dataset: pd.DataFrame, target_groups: tuple[str, ...]) -> list[dict[str, Any]]:
    rows = []
    for fold, g in dataset.groupby("fold", sort=True):
        t = g[g["eligible"] & g["glycemic_group"].isin(target_groups)]
        rows.append(
            {
                "fold": int(fold),
                "participants": int(g["participant_id"].nunique()),
                "target_participants": int(
                    g.loc[g["glycemic_group"].isin(target_groups), "participant_id"].nunique()
                ),
                "eligible_target_meals": int(len(t)),
                "positives": int(t["label"].sum()),
                "positive_rate": round(float(t["label"].mean()), 4) if len(t) else None,
                "groups": {
                    k: int(v)
                    for k, v in g.drop_duplicates("participant_id")["glycemic_group"]
                    .value_counts()
                    .sort_index()
                    .items()
                },
            }
        )
    return rows


def run_m2(tables: dict[str, pd.DataFrame], root: Path, write_outputs: bool = True) -> M2Result:
    fcfg, fsha = load_feature_config(root / "data/configs/features.v1.yaml")
    lcfg, lsha = load_label_config(root / "data/configs/labels.v1.yaml")

    dataset, histories = build_dataset(tables, fcfg, lcfg)
    people = dataset[["participant_id", "glycemic_group"]].drop_duplicates()
    folds = assign_folds(people, fcfg.folds.n_folds, fcfg.folds.seed)
    fold_status = verify_or_pin_folds(folds, root / "data/manifests/folds.v1.csv")
    dataset = dataset.merge(folds[["participant_id", "fold"]], on="participant_id", how="left")
    cols = list(dataset.columns)
    cols.insert(cols.index("macro_validity") + 1, cols.pop(cols.index("fold")))
    dataset = dataset[cols]

    feature_cols = list(fcfg.features.all())
    checks = [
        check_feature_names([c for c in feature_cols if c in dataset.columns], fcfg),
        check_source_times(dataset),
        check_truncation(
            dataset,
            histories,
            tables["meals"],
            fcfg,
            fcfg.leakage.truncation_check_meals,
            fcfg.folds.seed,
        ),
        check_folds(dataset),
        check_overlap(dataset, lcfg),
    ]
    raise_on_failures(checks)  # stops here if any hard check failed
    auc_check, aucs = single_feature_aurocs(dataset, fcfg, lcfg)
    checks.append(auc_check)

    target = dataset[dataset["eligible"] & dataset["glycemic_group"].isin(lcfg.target_groups)]
    availability = {
        c: round(float(target[c].notna().mean()), 4) if len(target) else None for c in feature_cols
    }
    issues = []
    if not auc_check["passed"]:
        issues.append(
            {
                "level": "review",
                "issue": f"features with extreme single-feature AUROC: {auc_check['detail']}. "
                "Confirm each is legitimate before M3.",
            }
        )
    report: dict[str, Any] = {
        "meals": int(len(dataset)),
        "eligible_meals": int(dataset["eligible"].sum()),
        "eligible_target_meals": int(len(target)),
        "eligible_target_positives": int(target["label"].sum()),
        "features": len(feature_cols) - len(fcfg.features.personal_raw),
        "folds": {
            "status": fold_status,
            "n_folds": fcfg.folds.n_folds,
            "seed": fcfg.folds.seed,
            "by_fold": _fold_table(dataset, lcfg.target_groups),
        },
        "feature_availability_eligible_target": availability,
        "single_feature_auroc_eligible_target": aucs,
        "leakage_checks": checks,
        "issues": issues,
        "config": {
            "features_version": fcfg.version,
            "features_sha256": fsha,
            "labels_version": lcfg.version,
            "labels_sha256": lsha,
        },
    }
    manifest = {
        "features_sha256": fsha,
        "labels_sha256": lsha,
        "dataset_rows": int(len(dataset)),
        "dataset_content_sha256": content_sha256(dataset),
        "folds_status": fold_status,
    }
    if write_outputs:
        out = root / "data/processed/m2"
        out.mkdir(parents=True, exist_ok=True)
        dataset.to_parquet(out / "dataset.parquet", index=False)
        (out / "run_manifest.json").write_text(dumps(manifest))
        reports = root / "data/reports"
        reports.mkdir(parents=True, exist_ok=True)
        (reports / "m2_dataset.json").write_text(dumps(report))
        (reports / "m2_dataset.md").write_text(report_markdown(report))
    return M2Result(dataset, report, manifest)


def _fmt(v: Any) -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return ""
    return f"{v * 100:.1f}%" if isinstance(v, float) and 0 <= v <= 1 else str(v)


def report_markdown(r: dict[str, Any]) -> str:
    lines = [
        "# M2 dataset report",
        "",
        "Generated by `make m2`. Features use native CGM readings only; labels are the frozen labels.v1.",
        "",
        f"- Meals: {r['meals']}; eligible: {r['eligible_meals']}; eligible target-group meals: "
        f"{r['eligible_target_meals']} ({r['eligible_target_positives']} positive)",
        f"- Features: {r['features']} (+ 2 raw personal counts); folds {r['folds']['status']}, "
        f"seed {r['folds']['seed']}",
        "",
        "## Leakage checks",
        "",
        "| Check | Passed | Detail |",
        "| --- | --- | --- |",
        *[
            f"| {c['check']} | {'yes' if c['passed'] else 'NO'} | {c['detail']} |"
            for c in r["leakage_checks"]
        ],
        "",
        "## Folds (participant-disjoint)",
        "",
        "| Fold | Participants | Target participants | Eligible target meals | Positives | Rate | Groups |",
        "| --- | --- | --- | --- | --- | --- | --- |",
        *[
            f"| {f['fold']} | {f['participants']} | {f['target_participants']} | "
            f"{f['eligible_target_meals']} | {f['positives']} | {_fmt(f['positive_rate'])} | "
            f"{f['groups']} |"
            for f in r["folds"]["by_fold"]
        ],
        "",
        "## Features (eligible target-group meals)",
        "",
        "| Feature | Available | Single-feature AUROC |",
        "| --- | --- | --- |",
        *[
            f"| {k} | {_fmt(v)} | {r['single_feature_auroc_eligible_target'].get(k) or ''} |"
            for k, v in r["feature_availability_eligible_target"].items()
        ],
        "",
        "Single-feature AUROC is descriptive only (all meals pooled, no folds). It is a leakage "
        "screen, not a model result.",
        "",
        "## Issues",
        "",
        *([f"- **{i['level']}**: {i['issue']}" for i in r["issues"]] or ["- none"]),
    ]
    return "\n".join(lines) + "\n"


def summary_lines(r: dict[str, Any]) -> list[str]:
    return [
        f"meals: {r['meals']}; eligible target-group meals: {r['eligible_target_meals']} "
        f"({r['eligible_target_positives']} positive)",
        *[f"{c['check']}: {'PASS' if c['passed'] else 'FAIL'}" for c in r["leakage_checks"]],
        *[f"[{i['level']}] {i['issue']}" for i in r["issues"]],
        json.dumps(
            {f"fold {f['fold']}": f["eligible_target_meals"] for f in r["folds"]["by_fold"]}
        ),
    ]
