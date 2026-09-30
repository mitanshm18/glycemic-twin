"""End-to-end M1 on the synthetic fixture: planted quirks must be found and counted exactly."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest
from test_source_and_manifest import tree_digest
from twin_ml.pipeline.audit import reconcile_phase0a
from twin_ml.pipeline.report import AUTO_END, AUTO_START, full_markdown, summary_markdown
from twin_ml.pipeline.run import run_m1


@pytest.fixture
def result(dataset: Path, repo_root: Path):  # type: ignore[no-untyped-def]
    return run_m1(dataset, repo_root, write_outputs=False)


def meal(result, pid: int, day: int, hhmm: str) -> pd.Series:  # type: ignore[no-untyped-def]
    t = pd.Timestamp("2021-06-01") + pd.Timedelta(days=day) + pd.Timedelta(hhmm + ":00")
    meals = result.tables["meals"]
    out = result.tables["meal_outcomes"]
    mid = meals.loc[(meals["participant_id"] == pid) & (meals["started_at"] == t), "meal_id"].item()
    row = out.set_index("meal_id").loc[mid]
    return pd.concat([row, meals.set_index("meal_id").loc[mid]])


def test_participants_groups_and_missing_ids(result) -> None:  # type: ignore[no-untyped-def]
    p = result.audit["participants"]
    assert p["timeseries_ids"] == [2, 3, 4, 5]
    assert p["ids_absent_between_1_and_max"] == [1]
    assert p["bio_without_timeseries"] == [6]
    assert p["bio_without_timeseries_groups"] == {"6": "healthy"}
    assert p["groups_with_timeseries"] == {"healthy": 1, "prediabetes": 1, "T2D": 2}


def test_schema_quirks_are_reported(result) -> None:  # type: ignore[no-untyped-def]
    a = result.audit
    assert a["schema"]["optional_columns_missing"] == {"amount_consumed_raw": [5], "mets_raw": [3]}
    assert a["schema"]["ignored_columns"] == {"intensity": [3], "unnamed: 0": [4]}
    assert a["wearable"]["intensity_files_equal_mets_missing"] is True
    assert a["wearable"]["target_group_without_mets"] == [3]
    assert a["wearable"]["hr_out_of_range"] == 1


def test_native_grid_found_for_every_participant(result) -> None:  # type: ignore[no-untyped-def]
    per = {p["participant_id"]: p["native_grid"]["dexcom"] for p in result.audit["per_participant"]}
    assert all(v["decision"] == "native_lattice" for v in per.values())
    phases = {
        pid: [s["phase"] for s in v["segments"] if s["status"] == "accepted"]
        for pid, v in per.items()
    }
    assert phases == {2: [2], 3: [1, 3], 4: [4], 5: [0, 0]}
    assert result.audit["native_cgm"]["dexcom"]["linear_share"] == 1.0
    cgm = result.tables["cgm"]
    native = cgm[cgm["dexcom_is_native"]]
    assert ((native["dexcom_mgdl"] % 1) == 0).all()  # only whole-number device readings


def test_duplicates_and_out_of_range(result) -> None:  # type: ignore[no-untyped-def]
    per = {p["participant_id"]: p for p in result.audit["per_participant"]}
    assert per[3]["duplicates"] == {
        "duplicated_timestamps": 2,
        "identical_groups": 1,
        "conflicting_groups": 1,
        "rows_removed": 2,
    }
    assert per[4]["cgm_out_of_range"]["dexcom"] == 1


def test_meal_rules(result) -> None:  # type: ignore[no-untyped-def]
    m = result.audit["meals"]
    assert m["meal_rows"] == 40
    assert m["by_type"] == {"breakfast": 12, "dinner": 12, "lunch": 12, "snack": 4}
    assert m["macro_validity"] == {"empty": 1, "inconsistent": 1, "invalid": 1, "valid": 37}
    assert m["amount_consumed"]["above_100_invalid"] == 1
    assert m["amount_consumed"]["files_without_column"] == [5]
    assert m["amount_consumed"]["used_as_feature"] is False
    assert meal(result, 2, 0, "18:30")["amount_consumed_invalid"]
    assert meal(result, 2, 2, "12:30")["macro_validity"] == "inconsistent"
    assert meal(result, 4, 2, "18:30")["macro_validity"] == "invalid"
    assert meal(result, 4, 2, "15:00")["macro_validity"] == "empty"


def test_outcomes_and_exclusions(result) -> None:  # type: ignore[no-untyped-def]
    o = result.audit["outcomes"]
    assert (o["frozen_usable"], o["frozen_positives"]) == (37, 17)
    assert o["exclusion_counts_any"] == {
        "overlap_next_meal": 1,
        "low_cgm_coverage": 2,
        "no_pre_meal_native": 1,
        "already_high": 2,
        "macro_excluded": 3,
    }
    assert o["exclusion_waterfall"]["eligible"] == 32
    assert meal(result, 4, 1, "12:30")["overlap_next_meal"]
    assert meal(result, 5, 1, "12:30")["low_cgm_coverage"]
    sensor_change = meal(result, 3, 1, "12:30")
    assert sensor_change["low_cgm_coverage"] and sensor_change["no_pre_meal_native"]
    assert meal(result, 4, 2, "08:00")["already_high"]  # unlogged excursion before breakfast
    by_pid = {r["participant_id"]: r for r in o["by_participant"]}
    assert [by_pid[p]["frozen_positives"] for p in (2, 3, 4, 5)] == [0, 0, 9, 8]


def test_target_group_summary_and_viability(result) -> None:  # type: ignore[no-untyped-def]
    t = result.audit["outcomes"]["target_eligible"]
    assert (t["participants"], t["usable_meals"], t["positives"]) == (3, 23, 14)
    assert t["participants_without_positive"] == [3]
    assert t["viability_pass"] is False  # a 4-person fixture cannot pass; the check itself works
    assert {i["issue"] for i in result.audit["issues"]} >= {
        "viability rule fails on target_eligible"
    }


def test_amount_consumed_never_enters_outcomes(result) -> None:  # type: ignore[no-untyped-def]
    assert not any("amount" in c for c in result.tables["meal_outcomes"].columns)


def test_raw_source_is_never_modified(dataset: Path, repo_root: Path) -> None:
    before = tree_digest(dataset)
    run_m1(dataset, repo_root, write_outputs=False)
    assert tree_digest(dataset) == before


def test_rerun_is_deterministic(dataset: Path, dataset_zip: Path, repo_root: Path) -> None:
    a = run_m1(dataset, repo_root, write_outputs=False)
    b = run_m1(dataset_zip, repo_root, write_outputs=False)  # same data via the ZIP
    assert a.run_manifest["tables"] == b.run_manifest["tables"]
    assert json.dumps(a.audit["outcomes"], sort_keys=True, default=str) == json.dumps(
        b.audit["outcomes"], sort_keys=True, default=str
    )


def test_reports_render_and_data_card_block_is_replaced(result, repo_root: Path) -> None:  # type: ignore[no-untyped-def]
    md = full_markdown(result.audit, None)
    for heading in (
        "## Provenance",
        "## By participant",
        "## Time series and native CGM grid",
        "## Issues",
    ):
        assert heading in md
    from twin_ml.pipeline.report import update_data_card

    card = repo_root / "docs/data-card.md"
    update_data_card(card, summary_markdown(result.audit))
    text = card.read_text()
    assert "old" not in text and "intro" in text and "outro" in text
    assert text.count(AUTO_START) == 1 and text.count(AUTO_END) == 1
    update_data_card(card, summary_markdown(result.audit))  # idempotent
    assert card.read_text() == text


def test_reconciliation_flags_expected_and_unexpected_differences(result) -> None:  # type: ignore[no-untyped-def]
    o = result.audit["outcomes"]
    ref = {
        "participant_file_count": 4,
        "participant_ids": [2, 3, 4, 5],
        "meals": {
            "meal_rows_total": 40,
            "usable_meals": o["frozen_usable"],
            "positives": 999,
            "exclusions": {"overlapping_next_meal_within_horizon": 1, "coverage_below_min": 2},
            "by_group": {},
            "positives_already_above_threshold_pre_meal": 0,
        },
    }
    rows = {r["quantity"]: r for r in reconcile_phase0a(result.audit, ref)}
    assert rows["usable meals (frozen)"]["match"]
    assert not rows["positives (frozen)"]["match"] and rows["positives (frozen)"]["expected_equal"]
    assert not rows["already-high positives"]["expected_equal"]


def test_outputs_written_to_repo_not_source(dataset: Path, repo_root: Path) -> None:
    pytest.importorskip("pyarrow")
    run_m1(dataset, repo_root, write_outputs=True)
    processed = repo_root / "data/processed/m1"
    assert {p.name for p in processed.glob("*.parquet")} == {
        "clinical_wide.parquet",
        "clinical_long.parquet",
        "meals.parquet",
        "meal_outcomes.parquet",
        "cgm.parquet",
        "wearable.parquet",
    }
    back = pd.read_parquet(processed / "meal_outcomes.parquet")
    assert len(back) == 40
    assert (repo_root / "data/reports/m1_audit.md").exists()
    assert (repo_root / "data/manifests/cgmacros-1.0.0.lock.json").exists()


def test_reports_and_card_written_even_without_parquet_engine(
    dataset: Path, repo_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exercise the write path here; the real Parquet engine is covered by the test above."""
    written: list[str] = []
    monkeypatch.setattr(
        pd.DataFrame, "to_parquet", lambda self, path, **_: written.append(Path(path).name)
    )
    run_m1(dataset, repo_root, write_outputs=True)
    assert len(written) == 6
    audit = json.loads((repo_root / "data/reports/m1_audit.json").read_text())
    assert audit["outcomes"]["frozen_usable"] == 37
    assert audit["provenance"]["lock_check"]["status"] == "pinned"
    card = (repo_root / "docs/data-card.md").read_text()
    assert "Time-series files: **4**" in card
    manifest = json.loads((repo_root / "data/processed/m1/run_manifest.json").read_text())
    assert set(manifest["tables"]) == {
        "clinical_wide",
        "clinical_long",
        "meals",
        "meal_outcomes",
        "cgm",
        "wearable",
    }
    # second run verifies against the pinned lock instead of re-pinning
    again = run_m1(dataset, repo_root, write_outputs=False)
    assert again.audit["provenance"]["lock_check"]["status"] == "verified"
