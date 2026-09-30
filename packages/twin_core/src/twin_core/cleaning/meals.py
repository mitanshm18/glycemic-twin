"""Meal rules: type normalization, Amount Consumed validity, macro validity.

Amount Consumed is recorded after the meal (from the after-meal photo). It is cleaned here only so the
data card can describe it; it must never become a model feature (enforced by leakage tests in M2).
"""

from __future__ import annotations

import re

import numpy as np
import pandas as pd

from twin_core.config import MealConfig

MACRO_COLUMNS = ("carbs_g", "protein_g", "fat_g", "fiber_g", "calories_kcal")
VALIDITY_ORDER = ("missing", "invalid", "empty", "inconsistent", "valid")


def normalize_meal_type(raw: object, cfg: MealConfig) -> str | None:
    """Lowercase and trim; snack variants -> 'snack'; unknown labels -> 'other'; blank -> None."""
    if raw is None or (isinstance(raw, float) and np.isnan(raw)):
        return None
    text = str(raw).strip().lower()
    if not text:
        return None
    if text in cfg.known_types:
        return text
    if re.fullmatch(cfg.snack_pattern, text):
        return "snack"
    return "other"


def clean_amount_consumed(values: pd.Series, cfg: MealConfig) -> tuple[pd.Series, pd.Series]:
    """Null values outside the documented 0-100 % range. Returns (clean values, invalid flag)."""
    lo, hi = cfg.amount_consumed_valid_pct
    invalid = values.notna() & ((values < lo) | (values > hi))
    return values.mask(invalid), invalid


def macro_validity(meals: pd.DataFrame, cfg: MealConfig) -> pd.DataFrame:
    """Classify each meal's logged macros. Returns columns macro_validity, macro_reasons, energy_ratio.

    Precedence: missing > invalid > empty > inconsistent > valid. ``macro_reasons`` lists every rule
    that fired, so the audit can count rules independently of precedence.
    """
    carbs = meals["carbs_g"]
    protein = meals["protein_g"]
    fat = meals["fat_g"]
    fiber = meals["fiber_g"]
    kcal = meals["calories_kcal"]
    a = cfg.atwater_kcal_per_g
    atwater = a["carbs"] * carbs + a["protein"] * protein + a["fat"] * fat
    ratio = atwater / kcal.where(kcal > 0)

    missing = meals[list(MACRO_COLUMNS)].isna().any(axis=1)
    negative = (meals[list(MACRO_COLUMNS)] < 0).any(axis=1)
    kcal_zero_with_content = (kcal <= 0) & ((carbs > 0) | (protein > 0) | (fat > 0))
    fiber_gt_carbs = (
        (fiber > carbs) if cfg.fiber_must_not_exceed_carbs else pd.Series(False, index=meals.index)
    )
    all_zero = (meals[list(MACRO_COLUMNS)] == 0).all(axis=1)
    empty = all_zero if cfg.flag_empty_meals else pd.Series(False, index=meals.index)
    lo, hi = cfg.energy_ratio_valid
    energy_bad = ratio.notna() & ((ratio < lo) | (ratio > hi))

    rules = {
        "missing_value": missing,
        "negative_value": negative & ~missing,
        "zero_calories_with_macros": kcal_zero_with_content & ~missing,
        "fiber_exceeds_carbs": fiber_gt_carbs & ~missing,
        "empty_meal": empty & ~missing,
        "energy_ratio_out_of_band": energy_bad & ~missing,
    }
    reasons = [
        ";".join(name for name, fired in rules.items() if bool(fired.iloc[i]))
        for i in range(len(meals))
    ]
    invalid = (
        rules["negative_value"] | rules["zero_calories_with_macros"] | rules["fiber_exceeds_carbs"]
    )
    validity = np.select(
        [missing, invalid, rules["empty_meal"], rules["energy_ratio_out_of_band"]],
        ["missing", "invalid", "empty", "inconsistent"],
        default="valid",
    )
    return pd.DataFrame(
        {"macro_validity": validity, "macro_reasons": reasons, "energy_ratio": ratio},
        index=meals.index,
    )
