"""Model bundles: everything needed to reproduce and serve one trained model.

A bundle holds the fitted pipeline (preprocessing + model), the calibrator, the decision threshold
and the PopulationPrior, plus provenance: contract version and hash, ordered columns, feature-set
name, training fold metadata, seeds and package versions. ``load_bundle`` refuses a bundle whose
contract version or column list differs from the current contract (ADR-015).
"""

from __future__ import annotations

import json
import platform
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.pipeline import Pipeline
from twin_core.config import FeatureConfig, ModelFeatureContract
from twin_core.personalization import PopulationPrior

from twin_ml.dataset.leakage import LeakageError
from twin_ml.training.models import PlattCalibrator, raw_scores

BUNDLE_FORMAT = 1
PACKAGES = ("numpy", "pandas", "scikit-learn", "scipy", "joblib", "xgboost", "twin-core", "twin-ml")


def package_versions() -> dict[str, str]:
    out = {"python": platform.python_version()}
    for p in PACKAGES:
        try:
            out[p] = metadata.version(p)
        except metadata.PackageNotFoundError:
            out[p] = "not installed"
    return out


@dataclass
class ModelBundle:
    model_name: str
    kind: str
    feature_set: str
    columns: tuple[str, ...]
    params: dict[str, Any]
    pipeline: Pipeline
    calibrator: PlattCalibrator
    threshold: float
    prior: PopulationPrior | None
    contract_version: int
    contract_sha256: str
    features_sha256: str
    labels_sha256: str
    training_config_sha256: str
    dataset_content_sha256: str
    dataset_label: str
    seeds: dict[str, Any]
    fold_metadata: dict[str, Any]
    package_versions: dict[str, str] = field(default_factory=package_versions)
    created_utc: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds")
    )
    bundle_format: int = BUNDLE_FORMAT

    @property
    def preprocessor(self) -> Pipeline:
        return self.pipeline[:-1]

    @property
    def model(self) -> Any:
        return self.pipeline[-1]

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        if tuple(X.columns) != self.columns:
            raise LeakageError("input columns differ from the bundle's contract columns")
        return self.calibrator.predict(raw_scores(self.pipeline, X))

    def metadata(self) -> dict[str, Any]:
        skip = {"pipeline", "calibrator", "prior"}
        meta = {k: v for k, v in asdict(self).items() if k not in skip}
        meta["columns"] = list(self.columns)
        meta["prior"] = asdict(self.prior) if self.prior else None
        meta["calibrator"] = {
            k: (sorted(v) if isinstance(v, frozenset) else v)
            for k, v in asdict(self.calibrator).items()
        }
        meta["preprocessing_steps"] = [name for name, _ in self.pipeline.steps[:-1]]
        return meta


def save_bundle(bundle: ModelBundle, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, path)
    path.with_suffix(".json").write_text(
        json.dumps(bundle.metadata(), indent=2, default=str) + "\n"
    )


def load_bundle(
    path: Path, contract: ModelFeatureContract, contract_sha256: str, fcfg: FeatureConfig
) -> ModelBundle:
    bundle = joblib.load(path)
    if not isinstance(bundle, ModelBundle):
        raise TypeError(f"{path} is not a ModelBundle")
    if bundle.contract_version != contract.version or bundle.contract_sha256 != contract_sha256:
        raise LeakageError("bundle was trained under a different model feature contract")
    sets = {contract.columns(fcfg, s) for s in contract.feature_sets}
    primary = contract.columns(fcfg)
    if bundle.columns not in sets and bundle.columns != tuple(
        c for c in primary if c in bundle.columns
    ):
        raise LeakageError("bundle columns are not a contract feature set")
    return bundle
