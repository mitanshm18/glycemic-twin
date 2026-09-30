from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError
from twin_core.config import load_cleaning_config, load_label_config

REPO = Path(__file__).resolve().parents[3]


def test_repo_configs_load_with_expected_frozen_values() -> None:
    ccfg, csha = load_cleaning_config(REPO / "data/configs/cleaning.v1.yaml")
    lcfg, lsha = load_label_config(REPO / "data/configs/labels.v1.yaml")
    assert ccfg.version == 1 and lcfg.version == 1
    assert (lcfg.threshold_mgdl, lcfg.horizon_min, lcfg.min_window_coverage) == (180, 120, 0.8)
    assert ccfg.cgm.native_grid.dexcom_period_min == 5
    assert len(csha) == len(lsha) == 64


def test_unknown_key_is_rejected(tmp_path: Path) -> None:
    text = (REPO / "data/configs/labels.v1.yaml").read_text() + "\nthreshhold_typo: 1\n"
    bad = tmp_path / "labels.yaml"
    bad.write_text(text)
    with pytest.raises(ValidationError):
        load_label_config(bad)


def test_hash_changes_when_config_changes(tmp_path: Path) -> None:
    src = (REPO / "data/configs/labels.v1.yaml").read_text()
    a, b = tmp_path / "a.yaml", tmp_path / "b.yaml"
    a.write_text(src)
    b.write_text(src.replace("horizon_min: 120", "horizon_min: 90"))
    assert load_label_config(a)[1] != load_label_config(b)[1]
