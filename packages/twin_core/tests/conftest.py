from __future__ import annotations

from pathlib import Path

import pytest
from twin_core.config import CleaningConfig, LabelConfig, load_cleaning_config, load_label_config

REPO = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="session")
def ccfg() -> CleaningConfig:
    return load_cleaning_config(REPO / "data/configs/cleaning.v1.yaml")[0]


@pytest.fixture(scope="session")
def lcfg() -> LabelConfig:
    return load_label_config(REPO / "data/configs/labels.v1.yaml")[0]
