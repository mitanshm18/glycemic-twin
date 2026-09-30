"""The model the twin serves, described by a Protocol so twin_core never imports the ML stack.

The M3 ``ModelBundle`` (twin_ml.training.bundle) already satisfies ``RiskModel``: it carries the
fitted preprocessing + model, the calibrator, the decision threshold, the PopulationPrior and the
contract identity. Serving calls only ``predict_proba``: no statistic is re-estimated at serving
time, so preprocessing, calibration and the prior are exactly the ones fitted in training.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict

from twin_core.config import FeatureConfig, ModelFeatureContract
from twin_core.personalization import PopulationPrior


class ModelContractError(RuntimeError):
    """The model does not match the frozen model feature contract the twin runs under."""


@runtime_checkable
class RiskModel(Protocol):
    model_name: str
    feature_set: str
    columns: tuple[str, ...]
    contract_version: int
    contract_sha256: str
    features_sha256: str
    labels_sha256: str
    threshold: float
    prior: PopulationPrior | None

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray: ...


class ModelIdentity(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    model_version: str
    model_name: str
    feature_set: str
    n_columns: int
    contract_version: int
    contract_sha256: str
    features_sha256: str
    labels_sha256: str
    training_config_sha256: str | None
    dataset_content_sha256: str | None
    dataset_label: str | None
    created_utc: str | None
    threshold: float
    params: dict[str, Any]


def identity(model: RiskModel) -> ModelIdentity:
    dataset = getattr(model, "dataset_content_sha256", None)
    created = getattr(model, "created_utc", None)
    version = (
        f"{model.model_name}__{model.feature_set}"
        f"@contract-v{model.contract_version}-{model.contract_sha256[:12]}"
        f"/data-{(dataset or 'unknown')[:12]}/{created or 'unknown'}"
    )
    return ModelIdentity(
        model_version=version,
        model_name=model.model_name,
        feature_set=model.feature_set,
        n_columns=len(model.columns),
        contract_version=model.contract_version,
        contract_sha256=model.contract_sha256,
        features_sha256=model.features_sha256,
        labels_sha256=model.labels_sha256,
        training_config_sha256=getattr(model, "training_config_sha256", None),
        dataset_content_sha256=dataset,
        dataset_label=getattr(model, "dataset_label", None),
        created_utc=created,
        threshold=float(model.threshold),
        params=dict(getattr(model, "params", {}) or {}),
    )


def check_compatible(
    model: RiskModel,
    contract: ModelFeatureContract,
    fcfg: FeatureConfig,
    hashes: dict[str, str],
) -> None:
    """Refuse a model trained under any other contract, column order or upstream config."""
    problems = []
    if model.feature_set not in contract.feature_sets:
        problems.append(f"unknown feature set {model.feature_set!r}")
    elif tuple(model.columns) != contract.columns(fcfg, model.feature_set):
        problems.append("column list differs from the contract for its feature set")
    if model.contract_version != contract.version:
        problems.append(f"contract version {model.contract_version} != {contract.version}")
    if model.contract_sha256 != hashes["model_contract"]:
        problems.append("model_features contract hash differs")
    if model.features_sha256 != hashes["features"]:
        problems.append("features.v1.yaml hash differs")
    if model.labels_sha256 != hashes["labels"]:
        problems.append("labels.v1.yaml hash differs")
    personal = set(contract.personal.features)
    if personal & set(model.columns) and model.prior is None:
        problems.append("model uses personal features but carries no PopulationPrior")
    if problems:
        raise ModelContractError("; ".join(problems))
