"""M3: leakage-safe training, calibration, grouped evaluation, OOF predictions.

All data here is the SYNTHETIC TEST FIXTURE from m3_fixture.py. The numbers it produces prove that
the machinery works and that leakage guards fire; they are not results.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest
from twin_core.config import load_feature_config, load_label_config, load_model_contract
from twin_core.personalization import personal_features

sys.path.insert(0, str(Path(__file__).parent))
from m3_fixture import FIXTURE_LABEL, make_m2_like, pin_folds  # noqa: E402
from twin_ml.dataset.folds import FoldError  # noqa: E402
from twin_ml.dataset.leakage import OUTCOME_COLUMNS, LeakageError, check_model_inputs  # noqa: E402
from twin_ml.training import design as design_mod  # noqa: E402
from twin_ml.training.bundle import load_bundle, save_bundle  # noqa: E402
from twin_ml.training.config import load_training_config  # noqa: E402
from twin_ml.training.cv import (  # noqa: E402
    baseline_spec,
    inner_assignment,
    model_spec,
    people_table,
    run_cv,
    train,
    verify_boundaries,
)
from twin_ml.training.design import DesignBuilder, eligible_rows  # noqa: E402
from twin_ml.training.metrics import (  # noqa: E402
    auroc,
    bootstrap_ci,
    brier,
    calibration_stats,
    paired_bootstrap,
    pr_auc,
)
from twin_ml.training.models import ContractColumns  # noqa: E402
from twin_ml.training.run import load_configs, run_m3  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
CONFIGS = REPO / "data/configs"
FCFG = load_feature_config(CONFIGS / "features.v1.yaml")[0]
LCFG = load_label_config(CONFIGS / "labels.v1.yaml")[0]
CONTRACT, CONTRACT_SHA = load_model_contract(CONFIGS / "model_features.v1.yaml")
FAST = {
    "primary_model": "logistic",
    "evaluation": {"bootstrap_resamples": 40, "ci": 0.95, "calibration_bins": 5},
}
TCFG = load_configs(REPO, FAST).tcfg

# ADR-015, table 1, written out by hand: the test fails if the contract drifts from the ADR.
ADR015_COLUMNS = [
    "g_last",
    "g_age_min",
    "slope_15",
    "slope_30",
    "sd_60",
    "mean_180",
    "min_180",
    "max_180",
    "tir_24h",
    "g_overnight_baseline",
    "g_vs_baseline",
    "carbs_g",
    "protein_g",
    "fat_g",
    "fiber_g",
    "calories_kcal",
    "meal_breakfast",
    "meal_lunch",
    "meal_dinner",
    "meal_snack",
    "hour_sin",
    "hour_cos",
    "carbs_prev_3h",
    "invalid_meal_prev_3h",
    "mins_since_meal",
    "hr_30",
    "hr_resting",
    "hr_delta",
    "mets_available",
    "mets_60",
    "active_min_3h",
    "activity_kcal_60",
    "hr_age_min",
    "hba1c_pct",
    "fasting_glucose_mgdl",
    "fasting_insulin_uu_ml",
    "homa_ir",
    "bmi",
    "age_years",
    "sex_female",
    "triglycerides_mgdl",
    "hdl_mgdl",
    "p_personal",
    "rise_offset_mgdl",
    "personal_weight",
]


@pytest.fixture(scope="module")
def data() -> pd.DataFrame:
    return make_m2_like()


@pytest.fixture(scope="module")
def rows(data: pd.DataFrame) -> pd.DataFrame:
    return eligible_rows(data, LCFG.target_groups)


def builder(data: pd.DataFrame) -> DesignBuilder:
    return DesignBuilder(data, CONTRACT, FCFG, LCFG, TCFG.min_meals_per_person_prior)


@pytest.fixture(scope="module")
def m3_root(data: pd.DataFrame, tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("m3repo")
    shutil.copytree(CONFIGS, root / "data/configs")
    pin_folds(data, root)
    return root


@pytest.fixture(scope="module")
def m3(data: pd.DataFrame, m3_root: Path) -> Any:
    return run_m3(
        data,
        m3_root,
        write_outputs=False,
        dataset_label=FIXTURE_LABEL,
        overrides=FAST,
        require_xgboost=False,
    )


def outer_split(
    data: pd.DataFrame, k: int
) -> tuple[frozenset[int], frozenset[int], dict[int, int]]:
    people = people_table(builder(data))
    test = frozenset(people.loc[people["fold"] == k, "participant_id"].astype(int))
    tr = frozenset(people.loc[people["fold"] != k, "participant_id"].astype(int))
    return tr, test, inner_assignment(people, tr, TCFG.inner_folds, TCFG.seed + k + 1)


# ---------------------------------------------------------------- model inputs (ADR-015)


def test_model_inputs_exactly_match_adr015(data: pd.DataFrame, m3: Any) -> None:
    b = builder(data)
    everyone = frozenset(data["participant_id"].astype(int))
    X, prior = b.matrix(CONTRACT.columns(FCFG), everyone)
    assert list(X.columns) == ADR015_COLUMNS and len(X.columns) == 45
    assert prior is not None
    for s in CONTRACT.feature_sets:
        Xs, _ = b.matrix(CONTRACT.columns(FCFG, s), everyone)
        assert tuple(Xs.columns) == CONTRACT.columns(FCFG, s)
    # every fitted pipeline, in every fold of every run, was built on exactly its contract columns
    for cv in m3.cv.values():
        for t in cv.folds.values():
            assert tuple(t.pipeline[0].columns) == cv.spec.columns
    assert {r["n_columns"] for rid, r in m3.report["runs"].items() if "full_personal__" not in rid}
    assert m3.report["runs"]["logistic__full_personal"]["n_columns"] == 45
    assert m3.bundles["logistic__full_personal"].columns == tuple(ADR015_COLUMNS)


def test_personal_features_are_finite_and_never_raw_counts(data: pd.DataFrame) -> None:
    X, _ = builder(data).matrix(CONTRACT.columns(FCFG), frozenset(data["participant_id"]))
    personal = X[list(CONTRACT.personal.features)].to_numpy()
    assert np.isfinite(personal).all()
    assert not {"n_closed_meals", "n_closed_positive"} & set(X.columns)


def test_contract_step_refuses_any_other_columns(data: pd.DataFrame) -> None:
    cols = CONTRACT.columns(FCFG, "glucose_only")
    X, _ = builder(data).matrix(cols, None)
    step = ContractColumns(cols).fit(X)
    with pytest.raises(LeakageError):
        step.transform(X[list(reversed(cols))])
    with pytest.raises(LeakageError):
        step.transform(X.assign(label=1.0))
    with pytest.raises(LeakageError):
        ContractColumns(cols).fit(X.to_numpy())  # type: ignore[arg-type]


def test_check_model_inputs_rejects_outcomes_audit_columns_and_reordering() -> None:
    assert check_model_inputs(CONTRACT.columns(FCFG), CONTRACT, FCFG)["passed"]
    assert check_model_inputs(("g_last", "carbs_g"), CONTRACT, FCFG)["passed"]  # baseline subset
    assert not check_model_inputs(("carbs_g", "g_last"), CONTRACT, FCFG)["passed"]  # wrong order
    for bad in ("label", "peak_mgdl", "rise_native_mgdl", "n_closed_meals", "window_coverage"):
        assert not check_model_inputs(("g_last", bad), CONTRACT, FCFG)["passed"], bad
    with pytest.raises(LeakageError):
        builder(make_m2_like(meals_per_day=2, days=4)).matrix(("g_last", "label"), None)


def test_outcome_columns_never_reach_model_input(data: pd.DataFrame) -> None:
    """Scramble every outcome column the model must not see: the full input matrix is unchanged.
    (label, frozen_usable, rise and pre-meal glucose feed the prior and personal history by design,
    and are covered by the prior tests below.)"""
    everyone = frozenset(data["participant_id"].astype(int))
    X0, _ = builder(data).matrix(CONTRACT.columns(FCFG), everyone)
    poisoned = data.copy()
    rng = np.random.default_rng(0)
    untouchable = {"label", "frozen_usable", "eligible", "rise_native_mgdl", "pre_meal_native_mgdl"}
    for c in [c for c in OUTCOME_COLUMNS if c in data.columns and c not in untouchable]:
        poisoned[c] = rng.permutation(poisoned[c].to_numpy())
    poisoned["n_closed_meals"] = 999.0
    poisoned["n_closed_positive"] = -1.0
    X1, _ = builder(poisoned).matrix(CONTRACT.columns(FCFG), everyone)
    pd.testing.assert_frame_equal(X0, X1)


# ---------------------------------------------------------------- personalization prior


def test_prior_fit_excludes_test_participants(
    data: pd.DataFrame, rows: pd.DataFrame, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[set[int]] = []
    real = design_mod.fit_population_prior

    def spy(train: pd.DataFrame, *a: Any, **kw: Any) -> Any:
        calls.append(set(train["participant_id"].astype(int)))
        return real(train, *a, **kw)

    monkeypatch.setattr(design_mod, "fit_population_prior", spy)
    spec = model_spec("logistic", "full_personal", TCFG, CONTRACT, FCFG)
    for k in range(FCFG.folds.n_folds):
        calls.clear()
        tr, test, assign = outer_split(data, k)
        train(builder(data), rows, spec, tr, assign, TCFG, [], k, test)
        assert len(calls) == TCFG.inner_folds + 1  # one per inner fit + the outer refit
        assert all(not (c & test) for c in calls), f"fold {k}: prior saw test participants"
        assert calls[-1] == set(tr)


def test_test_participants_outcomes_do_not_change_their_prior_or_training_inputs(
    data: pd.DataFrame,
) -> None:
    tr, test, _ = outer_split(data, 0)
    poisoned = data.copy()
    is_test = poisoned["participant_id"].isin(test)
    poisoned.loc[is_test, "label"] = 1 - poisoned.loc[is_test, "label"]
    poisoned.loc[is_test, "rise_native_mgdl"] = 500.0
    cols = CONTRACT.columns(FCFG)
    X0, p0 = builder(data).matrix(cols, tr)
    X1, p1 = builder(poisoned).matrix(cols, tr)
    assert p0 == p1
    train_ids = data.loc[data["participant_id"].isin(tr), "meal_id"]
    pd.testing.assert_frame_equal(X0.loc[train_ids], X1.loc[train_ids])


def test_personal_features_use_only_closed_history(data: pd.DataFrame) -> None:
    prior, pf = builder(data).personal(frozenset(data["participant_id"].astype(int)))
    cols = list(design_mod.PRIOR_INPUTS)
    for pid in data["participant_id"].unique()[:4]:
        person = data[data["participant_id"] == pid].set_index("meal_id", drop=False)
        for i in (3, len(person) // 2, len(person) - 1):
            t0 = person["started_at"].iloc[i]
            # drop everything after t0 AND blank the outcomes of meals whose window is still open
            past = person[person["started_at"] <= t0].copy()
            still_open = past["started_at"] + pd.Timedelta(minutes=LCFG.horizon_min) > t0
            past.loc[still_open, "label"] = pd.NA
            past.loc[still_open, "rise_native_mgdl"] = np.nan
            again = personal_features(past[cols], prior, LCFG.horizon_min)
            mid = person["meal_id"].iloc[i]
            np.testing.assert_allclose(
                again.loc[mid, list(CONTRACT.personal.features)].to_numpy(float),
                pf.loc[mid].to_numpy(float),
            )
    # the raw audit counts from the dataset agree with the personalization module's own count
    full = pd.concat(
        personal_features(g[cols], prior, LCFG.horizon_min)
        for _, g in data.groupby("participant_id")
    ).loc[data.index]
    np.testing.assert_array_equal(
        full["n_closed_meals"].to_numpy(), data["n_closed_meals"].to_numpy()
    )


# ---------------------------------------------------------------- preprocessing, calibration, threshold


def test_preprocessing_is_fit_only_on_training_rows(data: pd.DataFrame, rows: pd.DataFrame) -> None:
    tr, test, assign = outer_split(data, 1)
    spiked = data.copy()
    is_test = spiked["participant_id"].isin(test)
    spiked.loc[is_test, "g_last"] = 5000.0  # a test-fold value that would move any global statistic
    spiked.loc[is_test, "bmi"] = np.nan
    spec = model_spec("logistic", "full_personal", TCFG, CONTRACT, FCFG)
    trained, _ = train(builder(spiked), rows, spec, tr, assign, TCFG, [], 1, test)
    pipe = trained.pipeline
    train_rows = rows[rows["participant_id"].isin(tr)]
    tr_data = spiked.set_index("meal_id").loc[train_rows.index]
    cols = list(spec.columns)
    imputer, scaler = pipe.named_steps["impute"], pipe.named_steps["scale"]
    assert pipe.named_steps["contract"].n_fit_rows_ == len(train_rows)
    assert imputer.statistics_[cols.index("g_last")] == pytest.approx(tr_data["g_last"].median())
    assert imputer.statistics_[cols.index("bmi")] == pytest.approx(tr_data["bmi"].median())
    assert scaler.mean_[cols.index("g_last")] == pytest.approx(tr_data["g_last"].mean())
    assert scaler.mean_[cols.index("g_last")] < 1000  # the 5000s of the test fold never got in


def test_calibration_and_threshold_exclude_test_participants(
    m3: Any, data: pd.DataFrame, rows: pd.DataFrame
) -> None:
    people = people_table(builder(data))
    for cv in m3.cv.values():
        for k, t in cv.folds.items():
            test = set(people.loc[people["fold"] == k, "participant_id"])
            assert t.calibrator.fitted_participants
            assert not t.calibrator.fitted_participants & test
            assert t.calibrator.fitted_participants <= t.fit_participants
        for r in cv.audit:
            if r["stage"] in ("calibration", "threshold"):
                assert not set(r["fit"]) & set(r["outer_test"])
    # functional proof: flipping every label of the test fold changes nothing that was fitted
    tr, test, assign = outer_split(data, 2)
    flipped = rows.copy()
    is_test = flipped["participant_id"].isin(test)
    flipped.loc[is_test, "label"] = 1 - flipped.loc[is_test, "label"]
    fdata = data.copy()
    fdata.loc[fdata["participant_id"].isin(test), "label"] = (
        1 - fdata.loc[fdata["participant_id"].isin(test), "label"]
    )
    spec = model_spec("logistic", "full_personal", TCFG, CONTRACT, FCFG)
    a, _ = train(builder(data), rows, spec, tr, assign, TCFG, [], 2, test)
    b, _ = train(builder(fdata), flipped, spec, tr, assign, TCFG, [], 2, test)
    assert (a.calibrator.slope, a.calibrator.intercept) == (
        b.calibrator.slope,
        b.calibrator.intercept,
    )
    assert a.threshold == b.threshold
    np.testing.assert_array_equal(a.pipeline[-1].coef_, b.pipeline[-1].coef_)


def test_threshold_is_chosen_before_the_test_fold_is_seen(m3: Any) -> None:
    oof = m3.oof
    for _key, g in oof.groupby(["run", "fold"]):
        assert g["threshold"].nunique() == 1  # one threshold per fold model, fixed before scoring
    # thresholds are stored with the fold model, which was trained without the fold
    cv = m3.cv["logistic__full_personal"]
    for k, t in cv.folds.items():
        assert (
            oof.loc[(oof["run"] == "logistic__full_personal") & (oof["fold"] == k), "threshold"]
            == t.threshold
        ).all()


# ---------------------------------------------------------------- OOF predictions


def test_oof_predictions_are_participant_disjoint_and_complete(m3: Any, rows: pd.DataFrame) -> None:
    target_meals = set(rows.loc[rows["target"], "meal_id"])
    for rid, cv in m3.cv.items():
        o = cv.oof
        assert not o.duplicated("meal_id").any(), rid
        assert set(o.loc[o["target"], "meal_id"]) == target_meals, rid
        assert (o["fold"] == o["model_fold"]).all()
        for k, t in cv.folds.items():
            scored = set(o.loc[o["model_fold"] == k, "participant_id"])
            assert not scored & t.fit_participants, f"{rid} fold {k}"
        assert o["prob"].between(0, 1).all()
    assert (m3.oof.groupby("run")["target"].sum() == len(target_meals)).all()


def test_verify_boundaries_catches_each_kind_of_violation() -> None:
    base = {"model": "m", "feature_set": "s", "outer_fold": 0, "outer_test": [1, 2]}
    bad = [
        {
            **base,
            "stage": "inner_fit",
            "inner_fold": 0,
            "prior_fit": [1, 3],
            "preprocess_model_fit": [3],
            "scored": [4],
        },
        {
            **base,
            "stage": "inner_fit",
            "inner_fold": 0,
            "prior_fit": [3],
            "preprocess_model_fit": [2],
            "scored": [4],
        },
        {
            **base,
            "stage": "inner_fit",
            "inner_fold": 0,
            "prior_fit": [3],
            "preprocess_model_fit": [3],
            "scored": [3],
        },
        {**base, "stage": "calibration", "fit": [2, 5]},
        {**base, "stage": "threshold", "fit": [1]},
        {**base, "stage": "score", "fit": [3], "scored": [3]},
    ]
    for record in bad:
        with pytest.raises(LeakageError):
            verify_boundaries([record])
    ok = {**base, "stage": "score", "fit": [3, 4], "scored": [1, 2]}
    assert verify_boundaries([ok])["passed"]


def test_cv_is_deterministic(data: pd.DataFrame, rows: pd.DataFrame) -> None:
    spec = model_spec("logistic", "glucose_meal", TCFG, CONTRACT, FCFG)
    a = run_cv(builder(data), rows, spec, TCFG).oof
    b = run_cv(builder(data), rows, spec, TCFG).oof
    pd.testing.assert_frame_equal(a, b)


# ---------------------------------------------------------------- baselines, ablations, metrics


def test_all_baselines_and_ablations_run(m3: Any) -> None:
    runs = m3.report["runs"]
    assert {
        "B1_rule_glucose_carbs",
        "B2_hba1c_only",
        "B3_personal_rate",
        "B4_glucose_carbs_lr",
    } <= set(runs)
    for s in CONTRACT.feature_sets:
        assert f"logistic__{s}" in runs
    assert runs["B3_personal_rate"]["feature_set"].endswith("[p_personal]")
    spec = baseline_spec("B1_rule_glucose_carbs", TCFG, CONTRACT, FCFG)
    assert spec.columns == ("g_last", "carbs_g") and len(spec.candidates) == 5


def test_report_keeps_healthy_separate_and_is_valid_json(m3: Any) -> None:
    r = m3.report
    assert r["dataset_label"] == FIXTURE_LABEL
    json.dumps(r, allow_nan=False)
    c = r["counts"]
    for run in r["runs"].values():
        assert run["target"]["pooled"]["meals"] == c["eligible_target_meals"]
        assert run["healthy"]["pooled"]["meals"] == c["eligible_healthy_meals"]
        assert len(run["target"]["per_fold"]) == FCFG.folds.n_folds
        assert {"auroc", "pr_auc", "brier"} <= set(run["target"]["bootstrap_ci"])
        assert run["target"]["calibration_curve"]
    primary = [x for x in r["comparisons"] if x["comparison"].startswith("primary")][0]
    assert primary["ran"] and primary["pr_auc"]["valid_resamples"] > 0
    assert (
        r["leakage"]["nested_cv_boundaries"]["logistic__full_personal"]["inner_fit"]
        == FCFG.folds.n_folds * TCFG.inner_folds
    )


def test_metrics_known_values() -> None:
    y = np.array([0, 0, 1, 1])
    assert auroc(y, np.array([0.1, 0.2, 0.8, 0.9])) == 1.0
    assert auroc(y, np.array([0.9, 0.8, 0.2, 0.1])) == 0.0
    assert pr_auc(y, np.array([0.1, 0.2, 0.8, 0.9])) == 1.0
    assert brier(y, np.array([0.0, 0.0, 1.0, 1.0])) == 0.0
    assert np.isnan(auroc(np.array([1, 1]), np.array([0.2, 0.3])))
    rng = np.random.default_rng(1)
    p = rng.uniform(0.05, 0.95, 20000)
    stats = calibration_stats((rng.random(20000) < p).astype(int), p)
    assert stats["calibration_slope"] == pytest.approx(1, abs=0.08)
    assert stats["calibration_intercept"] == pytest.approx(0, abs=0.05)


def test_bootstrap_resamples_participants_not_meals() -> None:
    # one participant: every participant resample is the same data, so the interval has zero width
    df = pd.DataFrame(
        {
            "participant_id": 1,
            "meal_id": range(40),
            "label": [0, 1] * 20,
            "prob": np.linspace(0.1, 0.9, 40),
        }
    )
    ci = bootstrap_ci(df, "prob", 50, 0.95, 0)
    assert ci["auroc"]["lo"] == ci["auroc"]["hi"]
    diff = paired_bootstrap(df, df, "pr_auc", 20, 0.95, 0)
    assert diff["difference"] == 0 and diff["lo"] == diff["hi"] == 0
    with pytest.raises(ValueError):
        paired_bootstrap(df, df.iloc[:10], "auroc", 5, 0.95, 0)


# ---------------------------------------------------------------- artifacts and config


def test_bundle_has_everything_and_round_trips(m3: Any, data: pd.DataFrame, tmp_path: Path) -> None:
    b = m3.bundles["logistic__full_personal"]
    path = tmp_path / "models/logistic__full_personal.joblib"
    save_bundle(b, path)
    meta = json.loads(path.with_suffix(".json").read_text())
    for key in (
        "model_name",
        "feature_set",
        "columns",
        "params",
        "threshold",
        "prior",
        "calibrator",
        "contract_version",
        "contract_sha256",
        "features_sha256",
        "labels_sha256",
        "training_config_sha256",
        "dataset_content_sha256",
        "dataset_label",
        "seeds",
        "fold_metadata",
        "package_versions",
        "preprocessing_steps",
    ):
        assert key in meta, key
    assert meta["feature_set"] == "full_personal" and meta["contract_sha256"] == CONTRACT_SHA
    assert meta["preprocessing_steps"] == ["contract", "impute", "scale"]
    assert len(meta["fold_metadata"]["nested_cv_folds"]) == FCFG.folds.n_folds
    assert meta["dataset_label"] == FIXTURE_LABEL
    loaded = load_bundle(path, CONTRACT, CONTRACT_SHA, FCFG)
    X, _ = builder(data).matrix(loaded.columns, frozenset(data["participant_id"]))
    np.testing.assert_allclose(loaded.predict_proba(X.iloc[:20]), b.predict_proba(X.iloc[:20]))
    assert loaded.prior == b.prior and loaded.preprocessor is not None
    with pytest.raises(LeakageError):
        load_bundle(path, CONTRACT, "0" * 64, FCFG)
    with pytest.raises(LeakageError):
        loaded.predict_proba(X.iloc[:5, ::-1])


def test_training_config_only_accepts_contract_columns(tmp_path: Path) -> None:
    text = (CONFIGS / "training.v1.yaml").read_text()
    bad = tmp_path / "training.v1.yaml"
    bad.write_text(text.replace("columns: [hba1c_pct]", "columns: [peak_mgdl]"))
    with pytest.raises(ValueError, match="outside the contract"):
        load_training_config(bad, CONTRACT, FCFG)
    ok = load_training_config(CONFIGS / "training.v1.yaml", CONTRACT, FCFG)[0]
    assert ok.primary_model == "xgboost"


def test_m3_refuses_unpinned_or_changed_folds(data: pd.DataFrame, tmp_path: Path) -> None:
    shutil.copytree(CONFIGS, tmp_path / "data/configs")
    with pytest.raises(FoldError):
        run_m3(data, tmp_path, write_outputs=False, overrides=FAST, require_xgboost=False)
    pin_folds(data, tmp_path)
    moved = data.copy()
    first = moved["participant_id"] == moved["participant_id"].iloc[0]
    moved.loc[first, "fold"] = (moved.loc[first, "fold"] + 1) % 5
    with pytest.raises(FoldError):
        run_m3(moved, tmp_path, write_outputs=False, overrides=FAST, require_xgboost=False)


def test_labels_config_is_unchanged() -> None:
    import hashlib

    digest = hashlib.sha256((CONFIGS / "labels.v1.yaml").read_bytes()).hexdigest()
    assert digest == "6088a0ad14b19ffc3b7b4254dac09bb1664c19b17577fbe15fb3adbe01e8a9de"


def test_real_runs_require_xgboost(
    data: pd.DataFrame, m3_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A real run (require_xgboost=True, the default) refuses to start without xgboost. The missing
    package is simulated, so this runs on every machine, with or without xgboost installed."""
    import twin_ml.training.run as run_module

    monkeypatch.setattr(run_module, "xgboost_available", lambda: False)
    with pytest.raises(RuntimeError, match="xgboost is not installed"):
        run_m3(data, m3_root, write_outputs=False)


def test_m2_output_schema_is_accepted(dataset: Path, repo_root: Path) -> None:
    """The fixture above mirrors the real M2 dataset schema: check against an actual M2 run."""
    from twin_ml.dataset.run import run_m2
    from twin_ml.pipeline.run import run_m1

    m2 = run_m2(
        run_m1(dataset, repo_root, write_outputs=False).tables, repo_root, write_outputs=False
    )
    assert list(m2.dataset.columns) == list(make_m2_like(days=2).columns)
    b = DesignBuilder(m2.dataset, CONTRACT, FCFG, LCFG, 1)
    X, _ = b.matrix(CONTRACT.columns(FCFG), frozenset(m2.dataset["participant_id"].astype(int)))
    assert tuple(X.columns) == tuple(ADR015_COLUMNS) and len(X) == len(m2.dataset)


# ---------------------------------------------------------------- XGBoost (runs where installed)


@pytest.fixture(scope="module")
def xgb_cv(data: pd.DataFrame, rows: pd.DataFrame) -> Any:
    pytest.importorskip("xgboost")
    spec = model_spec("xgboost", "full_personal", TCFG, CONTRACT, FCFG)
    return run_cv(builder(data), rows, spec, TCFG)


def test_xgboost_monotone_constraints_follow_contract_order(xgb_cv: Any) -> None:
    model = xgb_cv.folds[0].pipeline[-1]
    cols = list(xgb_cv.spec.columns)
    mono = model.get_params()["monotone_constraints"]
    assert len(mono) == len(cols)
    assert mono[cols.index("g_last")] == 1 and mono[cols.index("fiber_g")] == -1
    assert verify_boundaries(xgb_cv.audit, xgb_cv.oof)["passed"]


def test_tree_shap_is_oof_only_and_uses_contract_columns(xgb_cv: Any, rows: pd.DataFrame) -> None:
    from twin_ml.training.explain import global_importance, tree_shap

    shap = tree_shap(xgb_cv, rows)
    shap_cols = [c for c in shap.columns if c.startswith("shap__")]
    assert shap_cols == [f"shap__{c}" for c in ADR015_COLUMNS] + ["shap__bias"]
    assert len(shap) == len(xgb_cv.oof) and set(shap["meal_id"]) == set(xgb_cv.oof["meal_id"])
    for k, t in xgb_cv.folds.items():
        assert not set(shap.loc[shap["fold"] == k, "participant_id"]) & t.fit_participants
    imp = global_importance(shap, xgb_cv.spec.columns)
    assert [d["feature"] for d in imp] != [] and len(imp) == 45


def test_full_m3_run_writes_every_artifact(data: pd.DataFrame, m3_root: Path) -> None:
    pytest.importorskip("xgboost")
    pytest.importorskip("pyarrow")
    fast = {"evaluation": FAST["evaluation"]}
    res = run_m3(data, m3_root, write_outputs=True, dataset_label=FIXTURE_LABEL, overrides=fast)
    out = m3_root / "data/processed/m3"
    for f in (
        "oof_predictions.parquet",
        "shap_oof.parquet",
        "run_manifest.json",
        "models/xgboost__full_personal.joblib",
        "models/logistic__full_personal.joblib",
    ):
        assert (out / f).exists(), f
    assert (
        (m3_root / "data/reports/m3_evaluation.md").read_text().startswith("# M3 evaluation report")
    )
    assert res.report["primary"]["ran"]
