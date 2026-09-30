"""Typed loader for training.v1.yaml, checked against the model feature contract (ADR-015/016)."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict
from twin_core.config import FeatureConfig, ModelFeatureContract


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ModelSpec(_Frozen):
    grid: dict[str, tuple[Any, ...]]
    fixed: dict[str, Any] = {}
    monotone: dict[str, int] = {}


class BaselineSpec(_Frozen):
    kind: Literal["rule", "logistic", "score"]
    columns: tuple[str, ...]
    a_grid: tuple[float, ...] = ()


class EvaluationSpec(_Frozen):
    bootstrap_resamples: int
    ci: float
    calibration_bins: int


class TrainingConfig(_Frozen):
    version: int
    model_contract: str
    seed: int
    inner_folds: int
    min_meals_per_person_prior: int
    selection_metric: Literal["average_precision"]
    calibration: Literal["platt"]
    threshold_rule: Literal["f1_max"]
    primary_model: str
    ablation_models: tuple[str, ...]
    models: dict[str, ModelSpec]
    baselines: dict[str, BaselineSpec]
    evaluation: EvaluationSpec


def load_training_config(
    path: Path, contract: ModelFeatureContract, fcfg: FeatureConfig
) -> tuple[TrainingConfig, str]:
    raw = path.read_bytes()
    cfg = TrainingConfig.model_validate(yaml.safe_load(raw))
    if cfg.primary_model not in cfg.models:
        raise ValueError(f"primary_model {cfg.primary_model!r} is not in models")
    unknown_models = set(cfg.ablation_models) - set(cfg.models)
    if unknown_models:
        raise ValueError(f"ablation_models not in models: {sorted(unknown_models)}")
    primary_cols = contract.columns(fcfg)
    for name, b in cfg.baselines.items():
        outside = [c for c in b.columns if c not in primary_cols]
        if outside:
            raise ValueError(f"baseline {name} uses columns outside the contract: {outside}")
        if b.kind == "rule" and (len(b.columns) != 2 or not b.a_grid):
            raise ValueError(f"rule baseline {name} needs two columns and an a_grid")
        if b.kind == "score" and len(b.columns) != 1:
            raise ValueError(f"score baseline {name} needs exactly one column")
    for name, m in cfg.models.items():
        bad = [c for c in m.monotone if c not in primary_cols]
        if bad:
            raise ValueError(f"model {name}: monotone constraints on unknown columns {bad}")
    return cfg, hashlib.sha256(raw).hexdigest()


def baseline_columns(
    spec: BaselineSpec, contract: ModelFeatureContract, fcfg: FeatureConfig
) -> tuple[str, ...]:
    """A baseline's columns, re-ordered to contract order (the contract decides ordering)."""
    return tuple(c for c in contract.columns(fcfg) if c in spec.columns)
