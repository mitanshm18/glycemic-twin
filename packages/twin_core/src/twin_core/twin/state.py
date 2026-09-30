"""The Digital Twin state contract, twin-state/1 (ADR-017).

Every model is frozen (immutable) and rejects unknown fields. Missing values are ``None``, never NaN,
so a state serializes to canonical JSON and hashes to a stable ``state_id``.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from twin_core.twin.model import ModelIdentity

STATE_SCHEMA = "twin-state/1"
ENGINE_VERSION = "m4.1"
DISCLAIMER = (
    "Model-estimated association from observational data (CGMacros). Not a causal effect, not a "
    "diagnosis and not medical advice. The twin never simulates medication, insulin, diagnosis or "
    "treatment."
)


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Phase(StrEnum):
    COLD_START = "COLD_START"
    WARMING = "WARMING"
    PERSONALIZED = "PERSONALIZED"


class ClinicalField(_Frozen):
    name: str
    value: float | None
    provenance: Literal["observed", "derived"]
    source: str


class StaticClinical(_Frozen):
    glycemic_group: str | None
    fields: list[ClinicalField]


class PersonalBaselines(_Frozen):
    overnight_glucose_mgdl: float | None  # g_overnight_baseline, completed nights before as_of
    resting_hr_bpm: float | None  # hr_resting, days before as_of's day
    time_in_range_24h: float | None  # tir_24h, share of native readings 70-180 in the last 24 h


class CurrentPhysiology(_Frozen):
    glucose_mgdl: float | None  # last native Dexcom reading within 15 min of as_of
    glucose_age_min: float | None
    slope_15_mgdl_per_min: float | None
    slope_30_mgdl_per_min: float | None
    sd_60_mgdl: float | None
    glucose_vs_baseline_mgdl: float | None
    hr_30_bpm: float | None
    hr_delta_bpm: float | None
    mets_60: float | None
    active_min_3h: float | None
    activity_kcal_60: float | None


class ClosedMeal(_Frozen):
    meal_id: str
    started_at: str
    window_closed_at: str
    frozen_usable: bool
    label: int | None  # 1 = went above 180 within 120 min
    rise_native_mgdl: float | None


class RecentHistory(_Frozen):
    glucose_mean_180_mgdl: float | None
    glucose_min_180_mgdl: float | None
    glucose_max_180_mgdl: float | None
    carbs_prev_3h_g: float | None
    mins_since_previous_meal: float | None
    meals_logged_24h: int
    meals_logged_total: int
    recent_closed_meals: list[ClosedMeal]


class CurrentMeal(_Frozen):
    meal_id: str | None
    origin: Literal["logged", "proposed"]
    started_at: str
    prediction_window_closes_at: str
    minutes_since_start: float
    meal_type: str | None
    carbs_g: float | None
    protein_g: float | None
    fat_g: float | None
    fiber_g: float | None
    calories_kcal: float | None
    macros_valid: bool
    applicable: bool
    not_applicable_reasons: list[str]


class PersonalResponse(_Frozen):
    closed_usable_meals: int
    closed_positive_meals: int
    population_rate: float
    p_personal: float  # shrunk positive rate (beta-binomial)
    rise_offset_mgdl: float  # shrunk personal rise residual vs the population rise model
    personal_weight: float  # n / (n + k)
    prior_fitted_on_people: int
    prior_fitted_on_meals: int


class Lifecycle(_Frozen):
    phase: Phase
    reason: str
    closed_usable_meals: int
    personal_weight: float | None
    next_phase_requires: str | None


class Uncertainty(_Frozen):
    level: Literal["low", "moderate", "high"]
    reasons: list[str]
    outcome_entropy_bits: float | None
    distance_to_threshold: float | None
    personal_weight: float | None
    missing_inputs: list[str]
    out_of_support_inputs: list[str]
    support_checked: bool
    note: str = (
        "Qualitative reliability flags, not a confidence interval; the probability itself is "
        "calibrated on held-out participants (M3)."
    )


class RiskEstimate(_Frozen):
    status: Literal["scored", "not_applicable", "unavailable"]
    reason: str | None
    probability: float | None
    threshold: float | None
    above_threshold: bool | None
    features_at: str | None  # the meal start the inputs describe
    model_inputs: dict[str, float | None] | None  # the exact contract columns, in order
    uncertainty: Uncertainty | None


class Freshness(_Frozen):
    last_cgm_native_at: str | None
    cgm_age_min: float | None
    cgm_stale: bool
    last_wearable_at: str | None
    wearable_age_min: float | None
    wearable_stale: bool
    last_meal_at: str | None


class Provenance(_Frozen):
    source: str
    record_sha256: str  # hash of every observation <= as_of
    cgm_native_readings_used: int
    wearable_minutes_used: int
    meals_logged_used: int
    closed_meal_ids_used: list[str]  # the only outcomes personalization read
    current_meal_id: str | None
    max_source_ts: str | None  # latest observation any computed value used (always <= as_of)
    config_sha256: dict[str, str]
    engine_version: str
    model: ModelIdentity | None


class TwinState(_Frozen):
    schema_version: str
    state_id: str  # sha256 of this state's canonical JSON without state_id
    patient_id: int
    as_of: str
    lifecycle: Lifecycle
    static_clinical: StaticClinical
    personal_baselines: PersonalBaselines
    current_physiology: CurrentPhysiology
    recent_history: RecentHistory
    current_meal: CurrentMeal | None
    personal_response: PersonalResponse | None
    risk: RiskEstimate
    freshness: Freshness
    provenance: Provenance
    disclaimer: str

    def canonical(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"state_id"})
