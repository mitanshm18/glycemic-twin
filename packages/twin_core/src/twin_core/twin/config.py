"""Typed loader for twin.v1.yaml and the bundle of frozen configs the twin runs under."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

from twin_core.config import (
    FeatureConfig,
    LabelConfig,
    ModelFeatureContract,
    load_feature_config,
    load_label_config,
    load_model_contract,
)


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class LifecycleConfig(_Frozen):
    personalized_min_weight: float
    personalized_min_closed_meals: int


class FreshnessConfig(_Frozen):
    cgm_stale_after_min: float
    wearable_stale_after_min: float


class WhatIfConfig(_Frozen):
    support_quantiles: tuple[float, float]
    max_abs_delta: dict[str, float]
    kcal_per_g: dict[str, float]
    blocked_terms: tuple[str, ...]


class UncertaintyConfig(_Frozen):
    near_threshold_band: float


class TwinConfig(_Frozen):
    version: int
    state_schema: str
    lifecycle: LifecycleConfig
    freshness: FreshnessConfig
    recent_meals_listed: int
    what_if: WhatIfConfig
    uncertainty: UncertaintyConfig


def load_twin_config(path: Path) -> tuple[TwinConfig, str]:
    raw = path.read_bytes()
    cfg = TwinConfig.model_validate(yaml.safe_load(raw))
    if set(cfg.what_if.max_abs_delta) - {
        "carbs_g",
        "fiber_g",
        "protein_g",
        "fat_g",
        "active_min_3h",
    }:
        raise ValueError("what_if.max_abs_delta names a lever the twin does not support")
    return cfg, hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class TwinConfigs:
    """Every frozen config the twin depends on, with the hashes recorded in each state."""

    features: FeatureConfig
    labels: LabelConfig
    contract: ModelFeatureContract
    twin: TwinConfig
    hashes: dict[str, str]

    @classmethod
    def load(cls, config_dir: Path) -> TwinConfigs:
        fcfg, fsha = load_feature_config(config_dir / "features.v1.yaml")
        lcfg, lsha = load_label_config(config_dir / "labels.v1.yaml")
        contract, csha = load_model_contract(config_dir / "model_features.v1.yaml")
        tcfg, tsha = load_twin_config(config_dir / "twin.v1.yaml")
        return cls(
            fcfg,
            lcfg,
            contract,
            tcfg,
            {"features": fsha, "labels": lsha, "model_contract": csha, "twin": tsha},
        )
