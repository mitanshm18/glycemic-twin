"""Aggregate per-participant results into the M1 audit: every number is computed from the source here.

The output is a plain dict (JSON-serializable, deterministic ordering) consumed by report.py.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

import pandas as pd
from twin_core.config import CleaningConfig, LabelConfig
from twin_core.labels import WATERFALL

from twin_ml.pipeline.clean import ParticipantResult
from twin_ml.pipeline.contracts import StageReport

GROUP_ORDER = ("healthy", "prediabetes", "T2D", "unknown")


def _rate(pos: int, n: int) -> float | None:
    return round(pos / n, 4) if n else None


def group_table(frame: pd.DataFrame, usable_col: str) -> dict[str, dict[str, Any]]:
    """Per glycemic group: participants, usable meals, positives, rate, participants with >= 1 positive."""
    out: dict[str, dict[str, Any]] = {}
    for group in GROUP_ORDER:
        g = frame[frame["glycemic_group"] == group]
        if g.empty:
            continue
        u = g[g[usable_col]]
        per_person = u.groupby("participant_id")["label"].sum()
        out[group] = {
            "participants": int(g["participant_id"].nunique()),
            "usable_meals": int(len(u)),
            "positives": int(u["label"].sum()),
            "positive_rate": _rate(int(u["label"].sum()), len(u)),
            "participants_with_positive": int((per_person > 0).sum()),
        }
    return out


def target_summary(frame: pd.DataFrame, usable_col: str, lcfg: LabelConfig) -> dict[str, Any]:
    t = frame[frame["glycemic_group"].isin(lcfg.target_groups)]
    u = t[t[usable_col]]
    per_person = u.groupby("participant_id")["label"].sum()
    n, pos = len(u), int(u["label"].sum())
    with_pos = int((per_person > 0).sum())
    v = lcfg.viability
    lo, hi = v.positive_rate_range
    rate = pos / n if n else 0.0
    checks: dict[str, dict[str, Any]] = {
        "min_positives": {
            "required": v.min_positives,
            "measured": pos,
            "pass": pos >= v.min_positives,
        },
        "positive_rate": {
            "required": [lo, hi],
            "measured": _rate(pos, n),
            "pass": lo <= rate <= hi,
        },
        "participants_with_positive": {
            "required": v.min_participants_with_positive,
            "measured": with_pos,
            "pass": with_pos >= v.min_participants_with_positive,
        },
    }
    return {
        "groups": list(lcfg.target_groups),
        "participants": int(t["participant_id"].nunique()),
        "usable_meals": n,
        "positives": pos,
        "positive_rate": _rate(pos, n),
        "participants_with_positive": with_pos,
        "participants_without_positive": sorted(
            int(p) for p in t["participant_id"].unique() if per_person.get(p, 0) == 0
        ),
        "viability": checks,
        "viability_pass": all(c["pass"] for c in checks.values()),
    }


def build_audit(
    results: list[ParticipantResult],
    stage_reports: dict[int, StageReport],
    clinical_wide: pd.DataFrame,
    ccfg: CleaningConfig,
    lcfg: LabelConfig,
) -> dict[str, Any]:
    ids = [r.participant_id for r in results]
    bio_ids = sorted(int(x) for x in clinical_wide["subject_id"])
    group_of = dict(
        zip(clinical_wide["subject_id"].astype(int), clinical_wide["glycemic_group"], strict=True)
    )
    issues: list[dict[str, str]] = []

    # --- participants ---------------------------------------------------------------------------
    no_bio = sorted(set(ids) - set(bio_ids))
    if no_bio:
        issues.append(
            {"level": "blocking", "issue": f"time series without a bio.csv row: {no_bio}"}
        )
    groups_all = Counter(clinical_wide["glycemic_group"])
    groups_ts = Counter(group_of.get(i, "unknown") for i in ids)
    participants = {
        "timeseries_files": len(ids),
        "timeseries_ids": ids,
        "ids_absent_between_1_and_max": sorted(set(range(1, max(ids) + 1)) - set(ids)),
        "bio_rows": len(bio_ids),
        "bio_without_timeseries": sorted(set(bio_ids) - set(ids)),
        "timeseries_without_bio": no_bio,
        "groups_bio": {g: groups_all.get(g, 0) for g in GROUP_ORDER if groups_all.get(g)},
        "groups_with_timeseries": {g: groups_ts.get(g, 0) for g in GROUP_ORDER if groups_ts.get(g)},
        "bio_without_timeseries_groups": {
            str(i): group_of[i] for i in sorted(set(bio_ids) - set(ids))
        },
    }

    # --- schema -----------------------------------------------------------------------------------
    present = Counter(c for rep in stage_reports.values() for c in rep.columns_present)
    missing_optional: dict[str, list[int]] = {}
    for pid, rep in stage_reports.items():
        for c in rep.optional_missing:
            missing_optional.setdefault(c, []).append(pid)
    ignored: dict[str, list[int]] = {}
    for pid, rep in stage_reports.items():
        for c in rep.ignored_columns:
            ignored.setdefault(c.strip().lower(), []).append(pid)
    non_numeric = {
        str(pid): rep.non_numeric_values
        for pid, rep in stage_reports.items()
        if rep.non_numeric_values
    }
    if non_numeric:
        issues.append(
            {"level": "warning", "issue": f"non-numeric sensor/meal values nulled: {non_numeric}"}
        )
    schema = {
        "canonical_columns_present": dict(sorted(present.items())),
        "optional_columns_missing": {k: sorted(v) for k, v in sorted(missing_optional.items())},
        "ignored_columns": {k: sorted(v) for k, v in sorted(ignored.items())},
        "non_numeric_values_nulled": non_numeric,
        "timestamps_with_seconds": sum(r.timestamps_with_seconds for r in stage_reports.values()),
    }

    # --- per-participant coverage and native grid ---------------------------------------------------
    per_participant = []
    for r in results:
        s = dict(r.stats)
        s["glycemic_group"] = group_of.get(r.participant_id, "unknown")
        per_participant.append(s)

    meals = pd.concat([r.meals for r in results], ignore_index=True)
    outcomes = pd.concat([r.outcomes for r in results], ignore_index=True)
    outcomes["glycemic_group"] = outcomes["participant_id"].map(group_of).fillna("unknown")

    native: dict[str, Any] = {}
    for sensor in ("dexcom", "libre"):
        decisions = Counter(p["native_grid"][sensor]["decision"] for p in per_participant)
        checked = linear = 0
        for r in results:
            for seg in r.stats["native_grid"][sensor]["segments"]:
                checked += seg["n_intervals_checked"]
                linear += seg["n_intervals_linear"]
        native[sensor] = {
            "decisions": dict(sorted(decisions.items())),
            "not_lattice": sorted(
                p["participant_id"]
                for p in per_participant
                if p["native_grid"][sensor]["decision"] != "native_lattice"
            ),
            "native_readings": sum(p["native_grid"][sensor]["n_native"] for p in per_participant),
            "values": sum(p["native_grid"][sensor]["n_values"] for p in per_participant),
            "intervals_checked": checked,
            "intervals_linear": linear,
            "linear_share": _rate(linear, checked),
        }
    with_meals = set(outcomes["participant_id"])
    bad_dexcom = [p for p in native["dexcom"]["not_lattice"] if p in with_meals]
    if bad_dexcom:
        issues.append(
            {
                "level": "blocking",
                "issue": f"Dexcom native grid not established for participants with meals: {bad_dexcom}. "
                "M2 features cannot use CGM for them until this is resolved.",
            }
        )
    ls = native["dexcom"]["linear_share"]
    if ls is not None and ls < ccfg.cgm.native_grid.min_linear_share:
        issues.append(
            {
                "level": "warning",
                "issue": f"Dexcom interpolation is not confirmed linear (share {ls}); "
                "labels on minute rows may differ from labels on native readings.",
            }
        )

    # --- wearable -----------------------------------------------------------------------------------
    no_mets = set(missing_optional.get("mets_raw", []))
    intensity = set(ignored.get("intensity", []))
    wearable = {
        "mets_column_missing": sorted(no_mets),
        "activity_kcal_column_missing": sorted(missing_optional.get("activity_kcal_raw", [])),
        "intensity_files": sorted(intensity),
        "intensity_files_equal_mets_missing": intensity == no_mets,
        "hr_out_of_range": sum(p["wearable"]["hr_out_of_range"] for p in per_participant),
        "mets_out_of_range": sum(p["wearable"]["mets_out_of_range"] for p in per_participant),
        "activity_kcal_negative": sum(
            p["wearable"]["activity_kcal_negative"] for p in per_participant
        ),
        "target_group_without_mets": sorted(
            p for p in no_mets if group_of.get(p) in lcfg.target_groups
        ),
    }

    # --- meals --------------------------------------------------------------------------------------
    rule_counts: Counter[str] = Counter()
    for reasons in meals["macro_reasons"]:
        rule_counts.update(r for r in str(reasons).split(";") if r)
    amount = meals["amount_consumed_raw"]
    meal_summary: dict[str, Any] = {
        "meal_rows": int(len(meals)),
        "by_type": dict(sorted(Counter(meals["meal_type"]).items())),
        "raw_type_spellings": dict(sorted(Counter(map(str, meals["meal_type_raw"])).items())),
        "duplicate_start_meals": int(meals["duplicate_start"].sum()),
        "amount_consumed": {
            "files_without_column": sorted(missing_optional.get("amount_consumed_raw", [])),
            "present": int(amount.notna().sum()),
            "missing": int(amount.isna().sum()),
            "below_100": int((amount < 100).sum()),
            "above_100_invalid": int((amount > 100).sum()),
            "negative_invalid": int((amount < 0).sum()),
            "max": None if amount.dropna().empty else float(amount.max()),
            "used_as_feature": False,
        },
        "macro_validity": dict(sorted(Counter(meals["macro_validity"]).items())),
        "macro_rule_counts": dict(sorted(rule_counts.items())),
        "macro_ranges_valid_meals": {
            c: [
                float(meals.loc[meals["macro_validity"] == "valid", c].min()),
                float(meals.loc[meals["macro_validity"] == "valid", c].max()),
            ]
            for c in ("carbs_g", "protein_g", "fat_g", "fiber_g", "calories_kcal")
        }
        if (meals["macro_validity"] == "valid").any()
        else {},
    }
    if meal_summary["by_type"].get("other"):
        issues.append(
            {
                "level": "warning",
                "issue": "meal types mapped to 'other': "
                + str(sorted(set(meals.loc[meals["meal_type"] == "other", "meal_type_raw"]))),
            }
        )

    # --- outcomes -------------------------------------------------------------------------------------
    usable = outcomes[outcomes["frozen_usable"]]
    already = outcomes[outcomes["frozen_usable"] & outcomes["already_high"]]
    waterfall = Counter(outcomes["waterfall_reason"])
    outcome_summary: dict[str, Any] = {
        "meals": int(len(outcomes)),
        "frozen_usable": int(len(usable)),
        "frozen_positives": int(usable["label"].sum()),
        "frozen_positive_rate": _rate(int(usable["label"].sum()), len(usable)),
        "exclusion_counts_any": {r: int(outcomes[r].sum()) for r in WATERFALL},
        "exclusion_waterfall": {r: int(waterfall.get(r, 0)) for r in (*WATERFALL, "eligible")},
        "already_high_among_frozen_usable": {
            "total": int(len(already)),
            "positives": int(already["label"].sum()),
            "negatives": int(len(already) - already["label"].sum()),
            "by_group": {
                g: int((already["glycemic_group"] == g).sum())
                for g in GROUP_ORDER
                if (already["glycemic_group"] == g).any()
            },
        },
        "frozen_by_group": group_table(outcomes, "frozen_usable"),
        "eligible_by_group": group_table(outcomes, "eligible"),
        "target_frozen": target_summary(outcomes, "frozen_usable", lcfg),
        "target_eligible": target_summary(outcomes, "eligible", lcfg),
        "by_participant": [
            {
                "participant_id": int(pid),
                "glycemic_group": group_of.get(int(pid), "unknown"),
                "meals": int(len(g)),
                "frozen_usable": int(g["frozen_usable"].sum()),
                "frozen_positives": int(g.loc[g["frozen_usable"], "label"].sum()),
                "eligible": int(g["eligible"].sum()),
                "eligible_positives": int(g.loc[g["eligible"], "label"].sum()),
                "already_high": int((g["frozen_usable"] & g["already_high"]).sum()),
            }
            for pid, g in outcomes.groupby("participant_id", sort=True)
        ],
    }
    for key in ("target_frozen", "target_eligible"):
        if not outcome_summary[key]["viability_pass"]:
            issues.append({"level": "blocking", "issue": f"viability rule fails on {key}"})

    return {
        "participants": participants,
        "schema": schema,
        "per_participant": per_participant,
        "native_cgm": native,
        "wearable": wearable,
        "meals": meal_summary,
        "outcomes": outcome_summary,
        "issues": issues,
    }


def reconcile_phase0a(audit: dict[str, Any], ref: dict[str, Any]) -> list[dict[str, Any]]:
    """Compare with the exploratory Phase 0A audit. Frozen quantities should match exactly;
    quantities whose definition changed (native pre-meal reading) are expected to differ."""
    o = audit["outcomes"]
    m = ref["meals"]
    rows: list[dict[str, Any]] = []

    def add(name: str, phase0a: Any, m1: Any, expected_equal: bool, note: str = "") -> None:
        rows.append(
            {
                "quantity": name,
                "phase0a": phase0a,
                "m1": m1,
                "expected_equal": expected_equal,
                "match": phase0a == m1,
                "note": note,
            }
        )

    add(
        "participant files",
        ref["participant_file_count"],
        audit["participants"]["timeseries_files"],
        True,
    )
    add("participant IDs", ref["participant_ids"], audit["participants"]["timeseries_ids"], True)
    add("meal rows", m["meal_rows_total"], audit["meals"]["meal_rows"], True)
    add("usable meals (frozen)", m["usable_meals"], o["frozen_usable"], True)
    add("positives (frozen)", m["positives"], o["frozen_positives"], True)
    add(
        "excluded: next meal < 120 min",
        m["exclusions"]["overlapping_next_meal_within_horizon"],
        o["exclusion_counts_any"]["overlap_next_meal"],
        True,
    )
    add(
        "excluded: coverage < 80%",
        m["exclusions"]["coverage_below_min"],
        o["exclusion_counts_any"]["low_cgm_coverage"],
        True,
    )
    for group, v in m["by_group"].items():
        f = o["frozen_by_group"].get(group, {})
        add(f"{group}: usable", v["usable"], f.get("usable_meals"), True)
        add(f"{group}: positives", v["positives"], f.get("positives"), True)
        add(
            f"{group}: participants with positive",
            v["participants_with_any_positive"],
            f.get("participants_with_positive"),
            True,
        )
    add(
        "already-high positives",
        m["positives_already_above_threshold_pre_meal"],
        o["already_high_among_frozen_usable"]["positives"],
        False,
        "Phase 0A used the interpolated minute value; M1 uses the last native reading",
    )
    return rows
