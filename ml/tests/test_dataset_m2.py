"""M2 dataset: end to end on the synthetic fixture, and every leakage check must actually fire."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from twin_core.config import load_feature_config, load_label_config
from twin_ml.dataset.folds import FoldError, assign_folds, verify_or_pin_folds
from twin_ml.dataset.leakage import (
    LeakageError,
    auroc,
    check_feature_names,
    check_folds,
    check_overlap,
    check_source_times,
    raise_on_failures,
)
from twin_ml.dataset.run import run_m2
from twin_ml.pipeline.run import run_m1

REPO = Path(__file__).resolve().parents[2]
FCFG = load_feature_config(REPO / "data/configs/features.v1.yaml")[0]
LCFG = load_label_config(REPO / "data/configs/labels.v1.yaml")[0]


@pytest.fixture
def m1_tables(dataset: Path, repo_root: Path) -> dict[str, pd.DataFrame]:
    return run_m1(dataset, repo_root, write_outputs=False).tables


@pytest.fixture
def m2(m1_tables: dict[str, pd.DataFrame], repo_root: Path):  # type: ignore[no-untyped-def]
    return run_m2(m1_tables, repo_root, write_outputs=False)


def test_dataset_shape_and_column_contract(m2) -> None:  # type: ignore[no-untyped-def]
    d = m2.dataset
    assert len(d) == 40
    feats = list(FCFG.features.all())
    start = list(d.columns).index(feats[0])
    assert list(d.columns[start : start + len(feats)]) == feats
    assert not any("amount" in c for c in d.columns)
    assert (d.groupby("participant_id")["fold"].nunique() == 1).all()


def test_hard_checks_pass_and_review_flag_is_raised(m2) -> None:  # type: ignore[no-untyped-def]
    checks = {c["check"][:2]: c for c in m2.report["leakage_checks"]}
    assert all(checks[k]["passed"] for k in ("L1", "L2", "L3", "L4", "L5"))
    # In the 4-person fixture, one target participant has no positives and the other two only
    # positives, so person-level features separate perfectly: L6 must flag them for review.
    assert not checks["L6"]["passed"]
    assert "hba1c_pct" in checks["L6"]["detail"]
    assert m2.report["issues"][0]["level"] == "review"


def test_every_feature_reads_only_the_past(m2) -> None:  # type: ignore[no-untyped-def]
    d = m2.dataset
    assert (d["max_source_ts"].isna() | (d["max_source_ts"] <= d["started_at"])).all()


def test_eligible_counts_match_m1(m2, m1_tables) -> None:  # type: ignore[no-untyped-def]
    assert int(m2.dataset["eligible"].sum()) == int(m1_tables["meal_outcomes"]["eligible"].sum())
    assert m2.report["eligible_target_meals"] == 23 and m2.report["eligible_target_positives"] == 14


def test_folds_pinned_then_verified_and_change_detected(m1_tables, repo_root: Path) -> None:  # type: ignore[no-untyped-def]
    assert run_m2(m1_tables, repo_root, write_outputs=False).report["folds"]["status"] == "pinned"
    assert run_m2(m1_tables, repo_root, write_outputs=False).report["folds"]["status"] == "verified"
    path = repo_root / "data/manifests/folds.v1.csv"
    pinned = pd.read_csv(path)
    pinned.loc[0, "fold"] = (pinned.loc[0, "fold"] + 1) % 5
    pinned.to_csv(path, index=False)
    with pytest.raises(FoldError):
        run_m2(m1_tables, repo_root, write_outputs=False)


def test_rerun_is_deterministic(m1_tables, repo_root: Path, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    other = tmp_path / "other"
    shutil.copytree(repo_root, other)
    a = run_m2(m1_tables, repo_root, write_outputs=False)
    b = run_m2(m1_tables, other, write_outputs=False)
    assert a.run_manifest["dataset_content_sha256"] == b.run_manifest["dataset_content_sha256"]


def test_write_path(m1_tables, repo_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(pd.DataFrame, "to_parquet", lambda self, path, **_: None)
    run_m2(m1_tables, repo_root, write_outputs=True)
    report = json.loads((repo_root / "data/reports/m2_dataset.json").read_text())
    assert report["meals"] == 40
    md = (repo_root / "data/reports/m2_dataset.md").read_text()
    assert "## Leakage checks" in md and "## Folds" in md


# --- the checks must fail when leakage is planted ------------------------------------------------
def test_l1_rejects_outcome_and_deny_listed_names() -> None:
    names = list(FCFG.features.all())
    bad = check_feature_names([*names, "peak_mgdl", "label"], FCFG)
    assert not bad["passed"] and "peak_mgdl" in str(bad["detail"])
    renamed = check_feature_names([*names[:-1], "amount_consumed_pct"], FCFG)
    assert not renamed["passed"]


def test_l2_detects_future_source(m2) -> None:  # type: ignore[no-untyped-def]
    d = m2.dataset.copy()
    d.loc[3, "max_source_ts"] = d.loc[3, "started_at"] + pd.Timedelta(minutes=1)
    assert not check_source_times(d)["passed"]


def test_l3_detects_a_feature_that_does_not_match_its_past(
    m1_tables, repo_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """Plant a leaky feature: g_last computed from the reading 5 minutes AFTER t0."""
    import twin_ml.dataset.build as build
    from twin_core import features as F

    real = F.meal_features

    def leaky(h, meal, cfg):  # type: ignore[no-untyped-def]
        f, src = real(h, meal, cfg)
        j = np.searchsorted(h.cgm_ts, meal.started_at + np.timedelta64(5, "m"), side="right") - 1
        f["g_last"] = float(h.cgm_val[j]) if j >= 0 else np.nan
        return f, src

    monkeypatch.setattr(build, "meal_features", leaky)
    with pytest.raises(LeakageError, match="L3"):
        run_m2(m1_tables, repo_root, write_outputs=False)


def test_l4_and_l5_detect_violations(m2) -> None:  # type: ignore[no-untyped-def]
    d = m2.dataset.copy()
    d.loc[d["participant_id"] == 2, "fold"] = [0, 1] * int((d["participant_id"] == 2).sum() / 2)
    assert not check_folds(d)["passed"]
    d2 = m2.dataset.copy()
    idx = d2.index[d2["frozen_usable"]][0]
    d2.loc[idx, "next_meal_gap_min"] = 30.0
    assert not check_overlap(d2, LCFG)["passed"]


def test_raise_on_failures_ignores_only_the_review_check() -> None:
    raise_on_failures([{"check": "L6 x", "passed": False, "detail": "d"}])
    with pytest.raises(LeakageError):
        raise_on_failures([{"check": "L2 x", "passed": False, "detail": "d"}])


# --- helpers ---------------------------------------------------------------------------------------
def test_auroc_reference_values() -> None:
    y = np.array([0, 0, 1, 1])
    assert auroc(np.array([1.0, 2, 3, 4]), y) == 1.0
    assert auroc(np.array([4.0, 3, 2, 1]), y) == 0.0
    assert auroc(np.array([1.0, 1, 1, 1]), y) == 0.5
    assert auroc(np.array([1.0, 3, 2, 4]), y) == 0.75
    assert np.isnan(auroc(np.array([1.0, 2]), np.array([1, 1])))


def test_folds_are_stratified_and_balanced() -> None:
    people = pd.DataFrame(
        {
            "participant_id": range(1, 45),
            "glycemic_group": ["healthy"] * 14 + ["prediabetes"] * 16 + ["T2D"] * 14,
        }
    )
    folds = assign_folds(people, 5, 20261001)
    sizes = folds["fold"].value_counts()
    assert sizes.max() - sizes.min() <= 1
    per_group = pd.crosstab(folds["glycemic_group"], folds["fold"])
    assert (per_group.max(axis=1) - per_group.min(axis=1) <= 1).all()
    assert folds.equals(assign_folds(people.sample(frac=1, random_state=3), 5, 20261001))


def test_verify_or_pin_folds(tmp_path: Path) -> None:
    people = pd.DataFrame({"participant_id": [1, 2, 3], "glycemic_group": ["T2D"] * 3})
    folds = assign_folds(people, 2, 1)
    assert verify_or_pin_folds(folds, tmp_path / "f.csv") == "pinned"
    assert verify_or_pin_folds(folds, tmp_path / "f.csv") == "verified"
    with pytest.raises(FoldError):
        verify_or_pin_folds(assign_folds(people, 2, 2), tmp_path / "f.csv")
