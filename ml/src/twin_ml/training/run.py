"""Orchestrate M3: M2 dataset -> nested participant CV for every model, baseline and ablation ->
OOF predictions -> metrics with participant-bootstrap CIs -> SHAP -> final model bundles -> report.

Outputs (write_outputs=True):
  data/processed/m3/oof_predictions.parquet   one row per (eligible meal, run); participant-disjoint
  data/processed/m3/shap_oof.parquet          per-meal TreeSHAP of the outer-fold XGBoost models
  data/processed/m3/models/<run>.joblib/.json final serving bundles (primary feature set)
  data/processed/m3/run_manifest.json         hashes, seeds, package versions
  data/reports/m3_evaluation.{json,md}        the evaluation report
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
from twin_core.config import (
    FeatureConfig,
    LabelConfig,
    ModelFeatureContract,
    load_feature_config,
    load_label_config,
    load_model_contract,
)

from twin_ml.dataset.folds import FoldError
from twin_ml.dataset.leakage import LeakageError
from twin_ml.pipeline.report import dumps
from twin_ml.pipeline.run import content_sha256
from twin_ml.training.bundle import ModelBundle, package_versions, save_bundle
from twin_ml.training.config import TrainingConfig, load_training_config
from twin_ml.training.cv import (
    CVResult,
    Spec,
    baseline_spec,
    model_spec,
    run_cv,
    train_final,
    verify_boundaries,
)
from twin_ml.training.design import DesignBuilder, describe_prior, eligible_rows
from twin_ml.training.explain import global_importance, logistic_coefficients, tree_shap
from twin_ml.training.metrics import evaluate_population, paired_bootstrap
from twin_ml.training.models import xgboost_available
from twin_ml.training.report import clean, report_markdown

REAL_DATA_LABEL = "CGMacros v1.0.0 (real data, processed by M1/M2)"


@dataclass
class M3Result:
    report: dict[str, Any]
    oof: pd.DataFrame
    shap: pd.DataFrame | None
    bundles: dict[str, ModelBundle]
    cv: dict[str, CVResult]


@dataclass
class Configs:
    fcfg: FeatureConfig
    lcfg: LabelConfig
    contract: ModelFeatureContract
    tcfg: TrainingConfig
    hashes: dict[str, str]


def load_configs(root: Path, overrides: dict[str, Any] | None = None) -> Configs:
    cdir = root / "data/configs"
    fcfg, fsha = load_feature_config(cdir / "features.v1.yaml")
    lcfg, lsha = load_label_config(cdir / "labels.v1.yaml")
    contract, csha = load_model_contract(cdir / "model_features.v1.yaml")
    tcfg, tsha = load_training_config(cdir / "training.v1.yaml", contract, fcfg)
    if overrides:
        tcfg = TrainingConfig.model_validate({**tcfg.model_dump(), **overrides})
    hashes = {"features": fsha, "labels": lsha, "model_contract": csha, "training": tsha}
    return Configs(fcfg, lcfg, contract, tcfg, hashes)


def load_m2_dataset(root: Path) -> pd.DataFrame:
    path = root / "data/processed/m2/dataset.parquet"
    if not path.exists():
        raise FileNotFoundError(f"{path} not found. Run `make m1 SOURCE=...` and `make m2` first.")
    return pd.read_parquet(path)


def verify_pinned_folds(dataset: pd.DataFrame, root: Path) -> None:
    path = root / "data/manifests/folds.v1.csv"
    if not path.exists():
        raise FoldError(f"{path} missing: M3 only trains on folds pinned by M2")
    pinned = pd.read_csv(path).set_index("participant_id")["fold"]
    current = dataset.drop_duplicates("participant_id").set_index("participant_id")["fold"]
    if not current.astype(int).sort_index().equals(pinned.astype(int).sort_index()):
        raise FoldError("dataset folds differ from data/manifests/folds.v1.csv")


def _run_id(spec: Spec) -> str:
    return spec.name if spec.name.startswith("B") else f"{spec.name}__{spec.feature_set}"


def plan_runs(cfg: Configs, with_xgboost: bool) -> list[Spec]:
    c, f, t = cfg.contract, cfg.fcfg, cfg.tcfg
    primary = c.primary_feature_set
    families = [m for m in t.models if m != "xgboost" or with_xgboost]
    specs = [model_spec(m, primary, t, c, f) for m in families]
    specs += [baseline_spec(b, t, c, f) for b in t.baselines]
    for m in t.ablation_models:
        if m not in families:
            continue
        for s in c.feature_sets:
            if s != primary:
                specs.append(model_spec(m, s, t, c, f))
    return specs


def _fold_meta(cv: CVResult) -> dict[str, Any]:
    return {
        str(k): {
            "train_participants": sorted(t.fit_participants),
            "selected_params": t.candidate.as_dict(),
            "inner_selection": t.inner_table,
            "threshold": t.threshold,
            "calibrator": {
                "slope": t.calibrator.slope,
                "intercept": t.calibrator.intercept,
                "fit_rows": t.calibrator.n_fit_rows,
            },
            "prior": describe_prior(t.prior),
        }
        for k, t in sorted(cv.folds.items())
    }


def run_m3(
    dataset: pd.DataFrame,
    root: Path,
    write_outputs: bool = True,
    dataset_label: str = REAL_DATA_LABEL,
    overrides: dict[str, Any] | None = None,
    require_xgboost: bool = True,
) -> M3Result:
    t_start = time.time()
    cfg = load_configs(root, overrides)
    t, c, f = cfg.tcfg, cfg.contract, cfg.fcfg
    has_xgb = xgboost_available()
    if require_xgboost and not has_xgb:
        raise RuntimeError(
            "xgboost is not installed; run `make setup` (it is a twin-ml dependency)"
        )
    verify_pinned_folds(dataset, root)

    design = DesignBuilder(dataset, c, f, cfg.lcfg, t.min_meals_per_person_prior)
    rows = eligible_rows(dataset, cfg.lcfg.target_groups)
    target_meals = set(rows.loc[rows["target"], "meal_id"])

    cvs: dict[str, CVResult] = {}
    boundary: dict[str, Any] = {}
    for spec in plan_runs(cfg, has_xgb):
        cv = run_cv(design, rows, spec, t)
        boundary[_run_id(spec)] = verify_boundaries(cv.audit, cv.oof)["detail"]
        covered = set(cv.oof.loc[cv.oof["target"], "meal_id"])
        if covered != target_meals:
            raise LeakageError(
                f"{_run_id(spec)}: OOF misses {len(target_meals - covered)} target meals"
            )
        cvs[_run_id(spec)] = cv
    oof = pd.concat([cv.oof.assign(run=rid) for rid, cv in cvs.items()], ignore_index=True)

    ev = t.evaluation
    evaluation = {}
    for rid, cv in cvs.items():
        o = cv.oof
        evaluation[rid] = {
            "model": cv.spec.name,
            "kind": cv.spec.kind,
            "feature_set": cv.spec.feature_set,
            "n_columns": len(cv.spec.columns),
            "target": evaluate_population(
                o[o["target"]], ev.calibration_bins, ev.bootstrap_resamples, ev.ci, t.seed
            ),
            "healthy": evaluate_population(
                o[~o["target"]], ev.calibration_bins, ev.bootstrap_resamples, ev.ci, t.seed
            ),
            "folds": _fold_meta(cv),
        }

    comparisons = compare(cvs, cfg, has_xgb)

    shap_df = None
    shap_summary = None
    primary_run = f"{t.primary_model}__{c.primary_feature_set}"
    xgb_run = f"xgboost__{c.primary_feature_set}"
    if xgb_run in cvs:
        shap_df = tree_shap(cvs[xgb_run], rows)
        shap_summary = {
            "run": xgb_run,
            "scale": "log-odds, before calibration",
            "rows": int(len(shap_df)),
            "global_importance_target": global_importance(shap_df, cvs[xgb_run].spec.columns),
        }

    dataset_sha = content_sha256(dataset)
    seeds = {
        "global": t.seed,
        "outer_folds": f.folds.seed,
        "inner_split_seed": "seed + outer_fold + 1",
        "model_random_state": t.seed,
        "bootstrap": t.seed,
    }
    bundles: dict[str, ModelBundle] = {}
    final_boundary = {}
    lr_coefficients = None
    for spec in plan_runs(cfg, has_xgb):
        if spec.feature_set != c.primary_feature_set or spec.name not in t.models:
            continue
        trained, audit = train_final(design, rows, spec, t)
        final_boundary[spec.name] = verify_boundaries(audit)["detail"]
        rid = _run_id(spec)
        bundles[rid] = ModelBundle(
            model_name=spec.name,
            kind=spec.kind,
            feature_set=spec.feature_set,
            columns=spec.columns,
            params=trained.candidate.as_dict(),
            pipeline=trained.pipeline,
            calibrator=trained.calibrator,
            threshold=trained.threshold,
            prior=trained.prior,
            contract_version=c.version,
            contract_sha256=cfg.hashes["model_contract"],
            features_sha256=cfg.hashes["features"],
            labels_sha256=cfg.hashes["labels"],
            training_config_sha256=cfg.hashes["training"],
            dataset_content_sha256=dataset_sha,
            dataset_label=dataset_label,
            seeds=seeds,
            fold_metadata={
                "final_model_inner_folds": "pinned outer folds (folds.v1.csv)",
                "final_inner_selection": trained.inner_table,
                "participants": sorted(trained.fit_participants),
                "nested_cv_folds": _fold_meta(cvs[rid]),
            },
        )
        if spec.kind == "logistic":
            lr_coefficients = logistic_coefficients(trained.pipeline)

    report: dict[str, Any] = {
        "dataset_label": dataset_label,
        "dataset_content_sha256": dataset_sha,
        "xgboost_available": has_xgb,
        "primary": {
            "run": primary_run,
            "population": list(cfg.lcfg.target_groups),
            "metric": "PR-AUC (average precision), pooled OOF, regime A (unseen participants)",
            "ran": primary_run in cvs,
        },
        "counts": {
            "participants": int(dataset["participant_id"].nunique()),
            "eligible_meals": int(len(rows)),
            "eligible_target_meals": int(rows["target"].sum()),
            "eligible_target_positives": int(rows.loc[rows["target"], "label"].sum()),
            "eligible_healthy_meals": int((~rows["target"]).sum()),
            "eligible_healthy_positives": int(rows.loc[~rows["target"], "label"].sum()),
            "target_participants": int(rows.loc[rows["target"], "participant_id"].nunique()),
            "healthy_participants": int(rows.loc[~rows["target"], "participant_id"].nunique()),
        },
        "runs": evaluation,
        "comparisons": comparisons,
        "shap": shap_summary,
        "final_logistic_coefficients": lr_coefficients,
        "leakage": {
            "model_inputs": "every matrix checked against model_features.v1 (check_model_inputs)",
            "nested_cv_boundaries": boundary,
            "final_model_boundaries": final_boundary,
            "oof_coverage": "every eligible target-group meal has exactly one OOF prediction per run",
        },
        "config": {**cfg.hashes, "training_version": t.version, "contract_version": c.version},
        "seeds": seeds,
        "package_versions": package_versions(),
        "runtime_seconds": round(time.time() - t_start, 1),
    }
    report = clean(report)
    if write_outputs:
        write_m3(root, report, oof, shap_df, bundles)
    return M3Result(report, oof, shap_df, bundles, cvs)


def compare(cvs: dict[str, CVResult], cfg: Configs, has_xgb: bool) -> list[dict[str, Any]]:
    t, c = cfg.tcfg, cfg.contract
    ev = t.evaluation
    p = c.primary_feature_set

    def tgt(rid: str) -> pd.DataFrame:
        o = cvs[rid].oof
        return o[o["target"]]

    from twin_ml.training.metrics import pr_auc

    baselines = [rid for rid in cvs if rid.startswith("B")]
    best = max(
        baselines, key=lambda r: pr_auc(tgt(r)["label"].to_numpy(), tgt(r)["prob"].to_numpy())
    )
    wanted = [
        ("primary: model vs best baseline", f"{t.primary_model}__{p}", best),
        ("logistic vs best baseline", f"logistic__{p}", best),
        ("xgboost vs logistic", f"xgboost__{p}", f"logistic__{p}"),
        ("personalization helps", f"{t.primary_model}__{p}", f"{t.primary_model}__full_multimodal"),
        ("fusion helps", f"{t.primary_model}__full_multimodal", f"{t.primary_model}__glucose_only"),
    ]
    out = []
    for name, a, b in wanted:
        if a not in cvs or b not in cvs or a == b:
            out.append({"comparison": name, "a": a, "b": b, "ran": False})
            continue
        res = paired_bootstrap(tgt(a), tgt(b), "pr_auc", ev.bootstrap_resamples, ev.ci, t.seed)
        auc = paired_bootstrap(tgt(a), tgt(b), "auroc", ev.bootstrap_resamples, ev.ci, t.seed)
        out.append({"comparison": name, "a": a, "b": b, "ran": True, "pr_auc": res, "auroc": auc})
    return out


def write_m3(
    root: Path,
    report: dict[str, Any],
    oof: pd.DataFrame,
    shap: pd.DataFrame | None,
    bundles: dict[str, ModelBundle],
) -> None:
    out = root / "data/processed/m3"
    out.mkdir(parents=True, exist_ok=True)
    oof.to_parquet(out / "oof_predictions.parquet", index=False)
    if shap is not None:
        shap.to_parquet(out / "shap_oof.parquet", index=False)
    for rid, b in bundles.items():
        save_bundle(b, out / "models" / f"{rid}.joblib")
    manifest = {
        "dataset_label": report["dataset_label"],
        "dataset_content_sha256": report["dataset_content_sha256"],
        "oof_content_sha256": content_sha256(oof),
        "config": report["config"],
        "seeds": report["seeds"],
        "package_versions": report["package_versions"],
        "bundles": sorted(f"models/{r}.joblib" for r in bundles),
    }
    (out / "run_manifest.json").write_text(dumps(manifest))
    reports = root / "data/reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "m3_evaluation.json").write_text(dumps(report))
    (reports / "m3_evaluation.md").write_text(report_markdown(report))
