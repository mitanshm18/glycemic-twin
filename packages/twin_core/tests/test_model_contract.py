"""The v1 model feature contract (ADR-015) is consistent with features.v1 and personalization."""

from __future__ import annotations

import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from twin_core.config import load_feature_config, load_model_contract
from twin_core.personalization import PopulationPrior, personal_features

REPO = Path(__file__).resolve().parents[3]
CONFIGS = REPO / "data/configs"


def test_primary_columns_are_base_plus_personal_without_raw_counts() -> None:
    contract, _ = load_model_contract(CONFIGS / "model_features.v1.yaml")
    fcfg, _ = load_feature_config(CONFIGS / "features.v1.yaml")
    cols = contract.columns(fcfg)
    base = [c for c in fcfg.features.all() if c not in fcfg.features.personal_raw]
    assert list(cols) == [*base, "p_personal", "rise_offset_mgdl", "personal_weight"]
    assert len(cols) == len(set(cols)) == 45
    assert not set(cols) & set(contract.not_model_inputs)
    assert set(contract.not_model_inputs) == set(fcfg.features.personal_raw)


def test_ablation_sets_are_nested_and_ordered() -> None:
    contract, _ = load_model_contract(CONFIGS / "model_features.v1.yaml")
    fcfg, _ = load_feature_config(CONFIGS / "features.v1.yaml")
    full = contract.columns(fcfg, "full_multimodal")
    assert contract.columns(fcfg, "full_personal")[: len(full)] == full
    assert contract.columns(fcfg, "glucose_only") == fcfg.features.glucose
    assert set(contract.columns(fcfg, "glucose_clinical")) == {
        *fcfg.features.glucose,
        *fcfg.features.clinical,
    }
    with pytest.raises(KeyError):
        contract.columns(fcfg, "everything")


def test_personal_feature_names_match_what_personalization_produces() -> None:
    contract, _ = load_model_contract(CONFIGS / "model_features.v1.yaml")
    person = pd.DataFrame(
        {
            "participant_id": 1,
            "started_at": [pd.Timestamp("2021-06-01 08:00")],
            "frozen_usable": True,
            "label": pd.array([1.0], dtype="Float64"),
            "rise_native_mgdl": 40.0,
            "carbs_g": 50.0,
            "fiber_g": 5.0,
            "pre_meal_native_mgdl": 110.0,
        }
    )
    prior = PopulationPrior(1.0, 1.0, (40.0, 0.0, 0.0, 0.0), 4.0, 2, 10)
    out = personal_features(person, prior, 120)
    assert set(contract.personal.features) <= set(out.columns)
    assert np.isfinite(out[list(contract.personal.features)].to_numpy()).all()  # never NaN


def test_contract_refuses_changed_upstream_configs(tmp_path: Path) -> None:
    shutil.copytree(CONFIGS, tmp_path / "configs")
    f = tmp_path / "configs/features.v1.yaml"
    f.write_text(f.read_text() + "\n# edited\n")
    with pytest.raises(ValueError, match="features.v1.yaml changed"):
        load_model_contract(tmp_path / "configs/model_features.v1.yaml")
