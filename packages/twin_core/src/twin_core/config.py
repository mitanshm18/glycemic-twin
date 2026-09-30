"""Typed, validated loaders for the versioned YAML configs.

Unknown keys are rejected so a typo in a config fails loudly instead of being ignored.
Each loader also returns the SHA-256 of the file bytes, recorded in every output for provenance.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class NativeGridConfig(_Frozen):
    dexcom_period_min: int
    libre_period_min: int
    min_integer_share: float
    max_other_phase_integer_share: float
    min_points: int
    segment_gap_min: int
    linearity_tolerance_mgdl: float
    min_linear_share: float


class CgmConfig(_Frozen):
    valid_range_mgdl: tuple[float, float]
    native_grid: NativeGridConfig


class WearableConfig(_Frozen):
    hr_valid_range_bpm: tuple[float, float]
    mets_scale_divisor: float
    mets_valid_range: tuple[float, float]
    activity_kcal_min: float


class MealConfig(_Frozen):
    known_types: tuple[str, ...]
    snack_pattern: str
    amount_consumed_valid_pct: tuple[float, float]
    fiber_must_not_exceed_carbs: bool
    atwater_kcal_per_g: dict[str, float]
    energy_ratio_valid: tuple[float, float]
    flag_empty_meals: bool


class GlycemicGroups(_Frozen):
    prediabetes_min: float
    t2d_min_exclusive: float


class ClinicalConfig(_Frozen):
    sentinels: dict[str, float]
    hba1c_unit: Literal["percent"]
    glycemic_groups: GlycemicGroups


class TimeseriesConfig(_Frozen):
    gap_flag_min: int
    duplicate_policy: Literal["null_conflicting"]


class CleaningConfig(_Frozen):
    version: int
    cgm: CgmConfig
    wearable: WearableConfig
    meals: MealConfig
    clinical: ClinicalConfig
    timeseries: TimeseriesConfig


class ViabilityConfig(_Frozen):
    min_positives: int
    positive_rate_range: tuple[float, float]
    min_participants_with_positive: int


class LabelConfig(_Frozen):
    version: int
    threshold_mgdl: float
    horizon_min: int
    min_window_coverage: float
    window_basis: Literal["minute_rows"]
    overlap_rule: Literal["next_meal_start_lt_horizon"]
    pre_meal_lookback_min: int
    already_high_threshold_mgdl: float
    exclude_macro_validity: tuple[str, ...]
    target_groups: tuple[str, ...]
    viability: ViabilityConfig


class FeatureWindows(_Frozen):
    g_last_lookback_min: int
    slope_short_min: int
    slope_long_min: int
    min_slope_readings: int
    sd_window_min: int
    min_sd_readings: int
    stats_window_min: int
    tir_window_min: int
    min_native_coverage: float
    target_range_mgdl: tuple[float, float]
    overnight_hours: tuple[int, int]
    min_overnight_readings: int
    hr_window_min: int
    mets_window_min: int
    activity_window_min: int
    min_wearable_coverage: float
    sedentary_mets_max: float
    active_mets_min: float
    resting_hr_percentile: float
    min_resting_hr_minutes: int
    prev_meal_window_min: int
    mins_since_meal_cap: int


class FeatureGroups(_Frozen):
    glucose: tuple[str, ...]
    meal: tuple[str, ...]
    context: tuple[str, ...]
    wearable: tuple[str, ...]
    clinical: tuple[str, ...]
    personal_raw: tuple[str, ...]

    def all(self) -> tuple[str, ...]:
        return (
            *self.glucose,
            *self.meal,
            *self.context,
            *self.wearable,
            *self.clinical,
            *self.personal_raw,
        )


class PersonalConfig(_Frozen):
    closed_window_min: int


class FoldConfig(_Frozen):
    n_folds: int
    seed: int
    stratify_by: Literal["glycemic_group"]


class LeakageConfig(_Frozen):
    deny_patterns: tuple[str, ...]
    single_feature_auroc_max: float
    truncation_check_meals: int


class FeatureConfig(_Frozen):
    version: int
    windows: FeatureWindows
    features: FeatureGroups
    personal: PersonalConfig
    folds: FoldConfig
    leakage: LeakageConfig


def _read(path: Path) -> tuple[dict[str, object], str]:
    raw = path.read_bytes()
    data = yaml.safe_load(raw)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a mapping at the top level")
    return data, hashlib.sha256(raw).hexdigest()


def load_cleaning_config(path: Path) -> tuple[CleaningConfig, str]:
    data, digest = _read(path)
    return CleaningConfig.model_validate(data), digest


def load_label_config(path: Path) -> tuple[LabelConfig, str]:
    data, digest = _read(path)
    return LabelConfig.model_validate(data), digest


def load_feature_config(path: Path) -> tuple[FeatureConfig, str]:
    data, digest = _read(path)
    return FeatureConfig.model_validate(data), digest


class PersonalContract(_Frozen):
    features: tuple[str, ...]
    prior_fit_rows: str
    history_rows: str


class ModelFeatureContract(_Frozen):
    """The exact, ordered model input columns (model_features.v1.yaml, ADR-015)."""

    version: int
    features_config: str
    features_sha256: str
    labels_config: str
    labels_sha256: str
    base_groups: tuple[str, ...]
    not_model_inputs: tuple[str, ...]
    personal: PersonalContract
    primary_feature_set: str
    feature_sets: dict[str, tuple[str, ...]]

    def columns(self, fcfg: FeatureConfig, feature_set: str | None = None) -> tuple[str, ...]:
        """Ordered model columns for a named feature set (default: the primary set)."""
        name = feature_set or self.primary_feature_set
        if name not in self.feature_sets:
            raise KeyError(f"unknown feature set {name!r}; known: {sorted(self.feature_sets)}")
        groups = self.feature_sets[name]
        cols: list[str] = []
        for group in self.base_groups:  # fixed group order, whatever order the set lists them in
            if group in groups:
                cols.extend(getattr(fcfg.features, group))
        if "personal" in groups:
            cols.extend(self.personal.features)
        return tuple(cols)


def load_model_contract(path: Path) -> tuple[ModelFeatureContract, str]:
    """Load the contract and verify the upstream configs it pins, which live beside it."""
    data, digest = _read(path)
    contract = ModelFeatureContract.model_validate(data)
    for name, expected in (
        (contract.features_config, contract.features_sha256),
        (contract.labels_config, contract.labels_sha256),
    ):
        actual = hashlib.sha256((path.parent / name).read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError(
                f"{name} changed since model_features.v{contract.version} pinned it "
                f"({actual[:12]} != {expected[:12]}); write a new contract version"
            )
    unknown = {g for s in contract.feature_sets.values() for g in s} - {
        *contract.base_groups,
        "personal",
    }
    if unknown:
        raise ValueError(f"feature sets use unknown groups: {sorted(unknown)}")
    return contract, digest
