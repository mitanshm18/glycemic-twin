"""SYNTHETIC test records and a stub model for the Digital Twin tests (tests only, not real data).

The stub model is NOT the M3 model: it is a fixed logistic formula over contract columns so the
twin's plumbing can be tested without the ML stack. Real-bundle tests live in ml/tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
from twin_core.personalization import PopulationPrior
from twin_core.twin import InMemorySource, PatientRecord, SupportProfile, TwinConfigs, TwinRuntime
from twin_core.twin.support import FeatureSupport

REPO = Path(__file__).resolve().parents[3]
CONFIGS = TwinConfigs.load(REPO / "data/configs")
START = pd.Timestamp("2021-06-01 00:00")
CLINICAL = {
    "hba1c_pct": 6.1,
    "fasting_glucose_mgdl": 105.0,
    "fasting_insulin_uu_ml": 12.0,
    "bmi": 29.0,
    "age_years": 52.0,
    "triglycerides_mgdl": 150.0,
    "hdl_mgdl": 45.0,
    "sex_female": 1.0,
}


def _response(minutes: np.ndarray) -> np.ndarray:
    """Glucose response shape to a meal: 0 before, peaks at 45 min, gone by ~180 min."""
    m = np.clip(minutes, 0, None)
    return np.where(minutes < 0, 0.0, (m / 45.0) * np.exp(1 - m / 45.0))


def make_record(
    days: int = 6,
    pid: int = 7,
    seed: int = 0,
    with_mets: bool = True,
    base_glucose: float = 110.0,
    invalid_meal_day: int | None = 1,
    high_start_meal: tuple[int, int] | None = None,
) -> PatientRecord:
    rng = np.random.default_rng(seed)
    meals = []
    for d in range(days):
        for h, mt in ((8, "breakfast"), (13, "lunch"), (19, "dinner")):
            carbs = float(rng.uniform(20, 110))
            protein, fat, fiber = (
                float(rng.uniform(5, 40)),
                float(rng.uniform(5, 40)),
                float(rng.uniform(1, 10)),
            )
            meals.append(
                {
                    "meal_id": f"{pid}-{d}-{h}",
                    "started_at": START + pd.Timedelta(days=d, hours=h),
                    "meal_type": mt,
                    "carbs_g": carbs,
                    "protein_g": protein,
                    "fat_g": fat,
                    "fiber_g": fiber,
                    "calories_kcal": 4 * carbs + 4 * protein + 9 * fat,
                    "macro_validity": "invalid" if (invalid_meal_day == d and h == 13) else "valid",
                }
            )
    meal_df = pd.DataFrame(meals)
    end = START + pd.Timedelta(days=days)
    native_ts = pd.date_range(START, end, freq="5min")
    minutes = (native_ts - START) / pd.Timedelta(minutes=1)
    g = np.full(len(native_ts), base_glucose) + rng.normal(0, 3, len(native_ts))
    for _, m in meal_df.iterrows():
        t = (m["started_at"] - START) / pd.Timedelta(minutes=1)
        g += 1.3 * m["carbs_g"] * _response(minutes.to_numpy() - t)
    if high_start_meal is not None:  # push glucose above 180 before one meal starts
        d, h = high_start_meal
        t = (pd.Timedelta(days=d, hours=h) - pd.Timedelta(minutes=40)) / pd.Timedelta(minutes=1)
        g += 120 * _response(minutes.to_numpy() - t)
    g = np.round(g)  # native Dexcom readings are integers
    native = pd.DataFrame({"ts": native_ts, "dexcom_mgdl": g, "dexcom_is_native": True})
    # interpolated minute rows between native readings (must never be used as native)
    minute_ts = pd.date_range(START, end, freq="1min")
    interp = np.interp((minute_ts - START) / pd.Timedelta(minutes=1), minutes.to_numpy(), g)
    inter = pd.DataFrame({"ts": minute_ts, "dexcom_mgdl": interp + 0.37, "dexcom_is_native": False})
    cgm = pd.concat([native, inter[~inter["ts"].isin(native_ts)]]).sort_values("ts")
    wear = pd.DataFrame(
        {
            "ts": minute_ts,
            "hr_bpm": 68 + rng.normal(0, 4, len(minute_ts)),
            "mets": (1.0 + rng.uniform(0, 2, len(minute_ts))) if with_mets else np.nan,
            "activity_kcal": rng.uniform(0.8, 2.0, len(minute_ts)),
        }
    )
    return PatientRecord(
        patient_id=pid,
        clinical=CLINICAL,
        cgm=cgm,
        wearable=wear,
        meals=meal_df,
        glycemic_group="prediabetes",
        source="SYNTHETIC TEST FIXTURE",
    )


def empty_record(pid: int = 9) -> PatientRecord:
    return PatientRecord(
        patient_id=pid,
        clinical=CLINICAL,
        cgm=pd.DataFrame({"ts": pd.to_datetime([]), "dexcom_mgdl": [], "dexcom_is_native": []}),
        wearable=pd.DataFrame(
            {"ts": pd.to_datetime([]), "hr_bpm": [], "mets": [], "activity_kcal": []}
        ),
        meals=pd.DataFrame(
            {
                "meal_id": pd.Series(dtype=object),
                "started_at": pd.to_datetime([]),
                "meal_type": pd.Series(dtype=object),
                **{
                    c: pd.Series(dtype=float)
                    for c in ("carbs_g", "protein_g", "fat_g", "fiber_g", "calories_kcal")
                },
                "macro_validity": pd.Series(dtype=object),
            }
        ),
        source="SYNTHETIC TEST FIXTURE",
    )


@dataclass
class StubModel:
    """Implements the RiskModel protocol with a fixed formula (SYNTHETIC; not the M3 model)."""

    columns: tuple[str, ...] = CONFIGS.contract.columns(CONFIGS.features)
    feature_set: str = "full_personal"
    model_name: str = "stub"
    contract_version: int = CONFIGS.contract.version
    contract_sha256: str = CONFIGS.hashes["model_contract"]
    features_sha256: str = CONFIGS.hashes["features"]
    labels_sha256: str = CONFIGS.hashes["labels"]
    threshold: float = 0.5
    prior: PopulationPrior | None = field(
        default_factory=lambda: PopulationPrior(2.0, 2.0, (20.0, 1.2, -1.0, 0.0), 2.0, 20, 400)
    )
    dataset_content_sha256: str = "fixture"
    seen: list[list[str]] = field(default_factory=list)

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        self.seen.append(list(X.columns))
        z = (
            0.03 * (X["g_last"].fillna(120) - 120)
            + 0.03 * (X["carbs_g"].fillna(50) - 50)
            + 2.0 * (X["p_personal"] - 0.5)
            + (0.01 * X["active_min_3h"].fillna(0) if "active_min_3h" in X else 0)
        )
        return np.asarray(1 / (1 + np.exp(-z)), dtype=float)


def wide_support(model: StubModel, **narrow: tuple[float, float]) -> SupportProfile:
    feats = {c: FeatureSupport(lo=-1e9, hi=1e9, min=-1e9, max=1e9, n=100) for c in model.columns}
    for c, (lo, hi) in narrow.items():
        feats[c] = FeatureSupport(lo=lo, hi=hi, min=lo, max=hi, n=100)
    return SupportProfile(
        dataset_content_sha256=model.dataset_content_sha256,
        quantiles=(0.01, 0.99),
        rows=100,
        features=feats,
    )


def runtime(model: StubModel | None = None, support: SupportProfile | None = None) -> TwinRuntime:
    return TwinRuntime(CONFIGS, model if model is not None else StubModel(), support)


def source(*records: PatientRecord) -> InMemorySource:
    return InMemorySource({r.patient_id: r for r in records})
