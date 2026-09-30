"""Model artifacts are found by file name wherever this deployment keeps them (no database needed).

The registry stores the path where a bundle was registered (e.g. a developer's laptop). Serving on
another machine must still find the file, and must still refuse a file whose bytes changed.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from twin_api.registry import DEFAULT_MODELS_DIR, ArtifactSearch, locate_artifact
from twin_api.settings import Settings
from twin_core.twin import ModelContractError

FOREIGN = "/Users/someone-else/digital-twin-healthcare/data/processed/m3/models/xgboost__full_personal.joblib"


def _file(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"bundle")
    return path


def test_a_path_from_another_machine_resolves_to_the_repo_models_dir(tmp_path: Path) -> None:
    here = _file(tmp_path / DEFAULT_MODELS_DIR / "xgboost__full_personal.joblib")
    assert locate_artifact(FOREIGN, ArtifactSearch(repo_root=tmp_path)) == here


def test_a_configured_models_dir_wins(tmp_path: Path) -> None:
    _file(tmp_path / DEFAULT_MODELS_DIR / "xgboost__full_personal.joblib")
    mounted = _file(tmp_path / "models" / "xgboost__full_personal.joblib")
    search = ArtifactSearch(repo_root=tmp_path, models_dir=tmp_path / "models")
    assert locate_artifact(FOREIGN, search) == mounted


def test_a_valid_stored_path_is_used_when_nothing_is_configured(tmp_path: Path) -> None:
    stored = _file(tmp_path / "elsewhere" / "m.joblib")
    assert locate_artifact(str(stored), ArtifactSearch(repo_root=tmp_path / "repo")) == stored


def test_a_relative_stored_path_is_read_against_the_repo_root(tmp_path: Path) -> None:
    here = _file(tmp_path / "models-v2" / "m.joblib")
    assert locate_artifact("models-v2/m.joblib", ArtifactSearch(repo_root=tmp_path)) == here


def test_a_missing_artifact_names_every_place_that_was_searched(tmp_path: Path) -> None:
    search = ArtifactSearch(repo_root=tmp_path, models_dir=tmp_path / "models")
    with pytest.raises(
        ModelContractError, match="model artifact missing: xgboost__full_personal.joblib"
    ) as err:
        locate_artifact(FOREIGN, search)
    assert str(tmp_path / "models") in str(err.value)
    assert str(tmp_path / DEFAULT_MODELS_DIR) in str(err.value)


def test_without_a_search_only_the_stored_path_counts(tmp_path: Path) -> None:
    _file(tmp_path / DEFAULT_MODELS_DIR / "xgboost__full_personal.joblib")
    with pytest.raises(ModelContractError, match="missing"):
        locate_artifact(FOREIGN, None)


def test_settings_expose_the_search(tmp_path: Path) -> None:
    s = Settings(
        database_url="postgresql+psycopg://u:p@h/d", repo_root=tmp_path, models_dir=tmp_path / "m"
    )
    assert s.artifact_search == ArtifactSearch(repo_root=tmp_path, models_dir=tmp_path / "m")
