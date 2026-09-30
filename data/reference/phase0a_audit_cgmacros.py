"""CGMacros v1.0.0 field-level audit.

Measures (does not estimate) the facts needed to freeze the Phase 0A target:
schema, timestamp resolution, CGM sampling, missingness, meal events, label
viability and positive counts by participant and glycemic group.

Usage:
    pip install pandas numpy
    python audit_cgmacros.py /path/to/CGMacros_dateshifted365.zip   # or an extracted folder
Outputs audit_report.md and audit_results.json next to this script.
"""

from __future__ import annotations

import io
import json
import re
import sys
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

# Proposed label definition (Phase 0A) and sensitivity grid.
THRESHOLD = 180  # mg/dL
HORIZON = 120  # minutes after meal start
MIN_COVERAGE = 0.80  # fraction of expected CGM samples in the label window
PRE_MEAL_LOOKBACK = 15  # minutes before meal start for a pre-meal reading
GRID_THRESHOLDS = [140, 160, 180, 200]
GRID_HORIZONS = [60, 90, 120, 180]
RISE_THRESHOLDS = [30, 50, 70]  # mg/dL rise over pre-meal, an alternative label

MED_PATTERN = r"\bmed(ication)?s?\b|\bdrugs?\b|metformin|statin|\brx\b"
PARTICIPANT_FILE = re.compile(r"CGMacros-0*(\d+)\.csv$", re.IGNORECASE)


# ---------------------------------------------------------------- loading


def load_tables(source: Path) -> tuple[dict[int, pd.DataFrame], dict[str, pd.DataFrame]]:
    """Return participant tables keyed by ID, plus supplementary CSVs by name."""
    participants: dict[int, pd.DataFrame] = {}
    extra: dict[str, pd.DataFrame] = {}

    def handle(name: str, read) -> None:
        base = Path(name).name
        if base.startswith("._") or "__MACOSX" in name:
            return
        match = PARTICIPANT_FILE.search(base)
        if match:
            participants[int(match.group(1))] = read()
        elif base.lower().endswith(".csv"):
            extra[base.lower()] = read()

    if source.is_file() and zipfile.is_zipfile(source):
        with zipfile.ZipFile(source) as zf:
            for name in zf.namelist():
                if name.lower().endswith(".csv"):
                    handle(
                        name, lambda n=name: pd.read_csv(io.BytesIO(zf.read(n)), low_memory=False)
                    )
    else:
        for path in source.rglob("*.csv"):
            handle(str(path), lambda p=path: pd.read_csv(p, low_memory=False))
    return participants, extra


def find_col(df: pd.DataFrame, *candidates: str) -> str | None:
    lowered = {c.lower().strip(): c for c in df.columns}
    for cand in candidates:
        if cand.lower() in lowered:
            return lowered[cand.lower()]
    for cand in candidates:
        for low, orig in lowered.items():
            if cand.lower() in low:
                return orig
    return None


# ---------------------------------------------------------------- helpers


def native_interval(ts: pd.Series, values: pd.Series) -> float | None:
    """Median minutes between consecutive non-null readings."""
    t = ts[values.notna()].sort_values()
    if len(t) < 3:
        return None
    return float(t.diff().dt.total_seconds().div(60).median())


def interpolation_signal(values: pd.Series) -> float | None:
    """Share of non-null CGM values that are non-integers (interpolation leaves fractions)."""
    v = values.dropna()
    if v.empty:
        return None
    return float((np.abs(v - np.round(v)) > 1e-6).mean())


def glycemic_group(a1c: float | None) -> str:
    # Thresholds as stated on the PhysioNet page (HbA1c in %).
    if a1c is None or pd.isna(a1c):
        return "unknown"
    if a1c < 5.7:
        return "healthy"
    if a1c <= 6.4:
        return "prediabetes"
    return "T2D"


def to_number(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


# ---------------------------------------------------------------- audit


def audit(source: Path) -> dict:
    participants, extra = load_tables(source)
    res: dict = {"source": str(source), "supplementary_files": sorted(extra)}

    ids = sorted(participants)
    res["participant_file_count"] = len(ids)
    res["participant_ids"] = ids
    res["ids_missing_in_1_to_max"] = sorted(set(range(1, max(ids) + 1)) - set(ids)) if ids else []

    # Schema across participant files
    col_sets = {pid: tuple(df.columns) for pid, df in participants.items()}
    all_cols = sorted({c for cols in col_sets.values() for c in cols})
    res["participant_columns_union"] = all_cols
    res["participant_column_presence"] = {
        c: sum(c in cols for cols in col_sets.values()) for c in all_cols
    }

    # ---- bio.csv
    bio = extra.get("bio.csv")
    bio_info: dict = {}
    a1c_by_pid: dict[int, float] = {}
    if bio is not None:
        bio_info["rows"] = len(bio)
        bio_info["columns"] = list(bio.columns)
        bio_info["null_counts"] = {c: int(bio[c].isna().sum()) for c in bio.columns}
        med_like = [c for c in bio.columns if re.search(MED_PATTERN, c, re.I)]
        bio_info["medication_like_columns"] = med_like
        id_col = find_col(bio, "subject", "participant", "id")
        a1c_col = find_col(bio, "A1c PDL (Lab)", "a1c")
        bio_info["id_column"] = id_col
        bio_info["a1c_column"] = a1c_col
        # Known sentinel/error values from the data dictionary
        sentinels = {}
        for name, bad in [("LDL", 800), ("VLDL", 400), ("Cho/HDL", 400)]:
            col = find_col(bio, name)
            if col is not None:
                sentinels[col] = int((to_number(bio[col]) == bad).sum())
        bio_info["sentinel_error_counts"] = sentinels
        if a1c_col is not None:
            a1c = to_number(bio[a1c_col])
            bio_info["a1c_min_max"] = [float(a1c.min()), float(a1c.max())]
            if id_col is not None:
                for raw_id, val in zip(bio[id_col], a1c):
                    digits = re.sub(r"\D", "", str(raw_id))
                    if digits:
                        a1c_by_pid[int(digits)] = float(val)
        # Are there any date/time columns other than lab collection and fingersticks?
        bio_info["time_like_columns"] = [c for c in bio.columns if re.search(r"time|date", c, re.I)]
    res["bio"] = bio_info

    # Other supplementary files: shapes only
    res["supplementary_shapes"] = {k: list(v.shape) for k, v in extra.items()}
    other_med = {
        k: [c for c in v.columns if re.search(MED_PATTERN, c, re.I)] for k, v in extra.items()
    }
    participants_med = sorted(
        {c for cols in col_sets.values() for c in cols if re.search(MED_PATTERN, c, re.I)}
    )
    res["medication_like_columns_anywhere"] = {"participant_files": participants_med, **other_med}

    # ---- per participant
    per_pid = []
    meals_all = []
    for pid in ids:
        df = participants[pid].copy()
        ts_col = find_col(df, "Timestamp")
        dex = find_col(df, "Dexcom GL")
        lib = find_col(df, "Libre GL")
        hr = find_col(df, "HR")
        mets = find_col(df, "METs", "Mets")
        cal_act = find_col(df, "Calories (Activity)")
        meal_type = find_col(df, "Meal Type")
        carbs = find_col(df, "Carbs")
        protein = find_col(df, "Protein")
        fat = find_col(df, "Fat")
        fiber = find_col(df, "Fiber")
        kcal = [c for c in df.columns if c.strip().lower() == "calories"]
        kcal = kcal[0] if kcal else None
        amount = find_col(df, "Amount Consumed")
        image = find_col(df, "Image Path")

        df[ts_col] = pd.to_datetime(df[ts_col], errors="coerce")
        df = df.sort_values(ts_col).reset_index(drop=True)
        for c in [dex, lib, hr, mets, cal_act, carbs, protein, fat, fiber, kcal, amount]:
            if c is not None:
                df[c] = to_number(df[c])

        step = df[ts_col].diff().dt.total_seconds().div(60)
        span_days = (df[ts_col].max() - df[ts_col].min()).total_seconds() / 86400
        info = {
            "pid": pid,
            "group": glycemic_group(a1c_by_pid.get(pid)),
            "a1c": a1c_by_pid.get(pid),
            "rows": len(df),
            "span_days": round(span_days, 2),
            "row_step_minutes_median": float(step.median()) if len(df) > 1 else None,
            "row_step_share_1min": float((step == 1).mean()) if len(df) > 1 else None,
            "row_gaps_over_5min": int((step > 5).sum()),
            "unparseable_timestamps": int(df[ts_col].isna().sum()),
            "missing_share": {
                c: float(df[c].isna().mean())
                for c in [dex, lib, hr, mets, cal_act]
                if c is not None
            },
            "dexcom_native_interval_min": native_interval(df[ts_col], df[dex]) if dex else None,
            "libre_native_interval_min": native_interval(df[ts_col], df[lib]) if lib else None,
            "dexcom_noninteger_share": interpolation_signal(df[dex]) if dex else None,
            "libre_noninteger_share": interpolation_signal(df[lib]) if lib else None,
        }

        # Meal rows = rows with a meal type
        meal_rows = df[df[meal_type].notna()] if meal_type else df.iloc[0:0]
        image_rows = df[df[image].notna()] if image else df.iloc[0:0]
        info["meal_rows"] = len(meal_rows)
        info["image_rows"] = len(image_rows)
        info["image_rows_without_meal_type"] = (
            int(image_rows[meal_type].isna().sum()) if meal_type else None
        )

        # Label generation per meal
        dex_ts = df.loc[df[dex].notna(), [ts_col, dex]] if dex else pd.DataFrame()
        dex_interval = info["dexcom_native_interval_min"] or 5.0
        meal_starts = meal_rows[ts_col].tolist()
        for i, (_, row) in enumerate(meal_rows.iterrows()):
            t0 = row[ts_col]
            nxt = meal_starts[i + 1] if i + 1 < len(meal_starts) else None
            rec = {
                "pid": pid,
                "group": info["group"],
                "meal_type": row[meal_type],
                "t0": t0,
                "minutes_to_next_meal": (nxt - t0).total_seconds() / 60
                if nxt is not None
                else None,
                "carbs": row[carbs] if carbs else np.nan,
                "protein": row[protein] if protein else np.nan,
                "fat": row[fat] if fat else np.nan,
                "fiber": row[fiber] if fiber else np.nan,
                "calories": row[kcal] if kcal else np.nan,
                "amount_consumed": row[amount] if amount else np.nan,
            }
            pre = dex_ts[
                (dex_ts[ts_col] <= t0)
                & (dex_ts[ts_col] > t0 - pd.Timedelta(minutes=PRE_MEAL_LOOKBACK))
            ]
            rec["pre_meal_glucose"] = float(pre[dex].iloc[-1]) if not pre.empty else np.nan
            for h in GRID_HORIZONS:
                win = dex_ts[
                    (dex_ts[ts_col] > t0) & (dex_ts[ts_col] <= t0 + pd.Timedelta(minutes=h))
                ]
                rec[f"coverage_{h}"] = min(1.0, len(win) / (h / dex_interval))
                rec[f"peak_{h}"] = float(win[dex].max()) if not win.empty else np.nan
            if mets:
                post = df[(df[ts_col] > t0) & (df[ts_col] <= t0 + pd.Timedelta(minutes=60))]
                rec["post_meal_mets_present_share"] = (
                    float(post[mets].notna().mean()) if len(post) else 0.0
                )
            meals_all.append(rec)
        per_pid.append(info)

    res["per_participant"] = per_pid
    meals = pd.DataFrame(meals_all)
    res["meals"] = summarize_meals(meals)
    return res


def summarize_meals(meals: pd.DataFrame) -> dict:
    out: dict = {"meal_rows_total": int(len(meals))}
    if meals.empty:
        return out
    out["by_meal_type"] = meals["meal_type"].value_counts().to_dict()

    # Macro fields: presence and consumption relationship
    amt = meals["amount_consumed"]
    out["amount_consumed_non_null"] = int(amt.notna().sum())
    out["amount_consumed_lt_100"] = int((amt < 100).sum())
    out["amount_consumed_distribution"] = amt.describe().round(2).to_dict()
    out["macro_null_counts"] = {
        c: int(meals[c].isna().sum()) for c in ["carbs", "protein", "fat", "fiber", "calories"]
    }
    # If macros were scaled by portion eaten, partial meals would show fractional macros more often.
    partial = meals[amt < 100]
    full = meals[amt == 100]
    frac = lambda s: float((np.abs(s - np.round(s)) > 1e-6).mean()) if s.notna().any() else None
    out["carbs_fractional_share_partial_meals"] = frac(partial["carbs"])
    out["carbs_fractional_share_full_meals"] = frac(full["carbs"])
    # Breakfast shakes were designed meals: count repeated identical macro profiles
    bk = meals[meals["meal_type"].astype(str).str.lower() == "breakfast"]
    out["breakfast_distinct_macro_profiles"] = int(
        bk[["carbs", "protein", "fat", "fiber"]].drop_duplicates().shape[0]
    )
    out["breakfast_count"] = int(len(bk))
    out["macro_ranges"] = {
        c: [float(meals[c].min()), float(meals[c].max())]
        for c in ["carbs", "protein", "fat", "fiber"]
    }

    # Exclusions for the proposed label
    base = meals.copy()
    base["overlap"] = base["minutes_to_next_meal"].notna() & (
        base["minutes_to_next_meal"] < HORIZON
    )
    base["low_coverage"] = base[f"coverage_{HORIZON}"] < MIN_COVERAGE
    base["no_pre_meal"] = base["pre_meal_glucose"].isna()
    out["exclusions"] = {
        "overlapping_next_meal_within_horizon": int(base["overlap"].sum()),
        "coverage_below_min": int(base["low_coverage"].sum()),
        "no_pre_meal_reading": int(base["no_pre_meal"].sum()),
    }
    usable = base[~base["overlap"] & ~base["low_coverage"]]
    usable = usable.assign(label=(usable[f"peak_{HORIZON}"] > THRESHOLD).astype(int))
    out["usable_meals"] = int(len(usable))
    out["usable_meals_with_pre_meal_reading"] = int((~usable["no_pre_meal"]).sum())
    out["positives"] = int(usable["label"].sum())
    out["positive_rate"] = round(float(usable["label"].mean()), 4) if len(usable) else None
    out["positives_already_above_threshold_pre_meal"] = int(
        ((usable["label"] == 1) & (usable["pre_meal_glucose"] > THRESHOLD)).sum()
    )
    by_pid = usable.groupby(["pid", "group"])["label"].agg(["count", "sum"]).reset_index()
    out["by_participant"] = by_pid.rename(columns={"count": "usable", "sum": "positives"}).to_dict(
        "records"
    )
    by_group = usable.groupby("group")["label"].agg(["count", "sum"])
    by_group["participants"] = usable.groupby("group")["pid"].nunique()
    by_group["participants_with_any_positive"] = (
        by_pid[by_pid["sum"] > 0].groupby("group")["pid"].nunique()
    )
    out["by_group"] = (
        by_group.fillna(0)
        .astype(int)
        .rename(columns={"count": "usable", "sum": "positives"})
        .to_dict("index")
    )
    out["participants_with_zero_positives"] = int((by_pid["sum"] == 0).sum())

    # Sensitivity grid: absolute threshold x horizon (overlap exclusion uses each horizon)
    grid = []
    for h in GRID_HORIZONS:
        ok = base[
            ~(base["minutes_to_next_meal"].notna() & (base["minutes_to_next_meal"] < h))
            & (base[f"coverage_{h}"] >= MIN_COVERAGE)
        ]
        for thr in GRID_THRESHOLDS:
            lab = ok[f"peak_{h}"] > thr
            grid.append(
                {
                    "horizon_min": h,
                    "threshold": thr,
                    "usable": int(len(ok)),
                    "positives": int(lab.sum()),
                    "rate": round(float(lab.mean()), 4) if len(ok) else None,
                    "participants_with_positive": int(ok.loc[lab, "pid"].nunique()),
                }
            )
        for rise in RISE_THRESHOLDS:
            okp = ok[ok["pre_meal_glucose"].notna()]
            lab = (okp[f"peak_{h}"] - okp["pre_meal_glucose"]) >= rise
            grid.append(
                {
                    "horizon_min": h,
                    "threshold": f"rise>={rise}",
                    "usable": int(len(okp)),
                    "positives": int(lab.sum()),
                    "rate": round(float(lab.mean()), 4) if len(okp) else None,
                    "participants_with_positive": int(okp.loc[lab, "pid"].nunique()),
                }
            )
    out["sensitivity_grid"] = grid
    if "post_meal_mets_present_share" in usable:
        out["post_meal_mets_present_share_mean"] = round(
            float(usable["post_meal_mets_present_share"].mean()), 4
        )
    return out


# ---------------------------------------------------------------- report


def to_markdown(res: dict) -> str:
    m = res["meals"]
    lines = ["# CGMacros v1.0.0 audit", "", f"Source: `{res['source']}`", ""]
    lines += [
        f"- Participant files: **{res['participant_file_count']}**",
        f"- IDs absent between 1 and max: {res['ids_missing_in_1_to_max']}",
        f"- Supplementary files: {res['supplementary_files']}",
        "",
    ]
    lines += ["## Participant-file columns (files containing each)", ""]
    lines += [f"- `{c}`: {n}" for c, n in res["participant_column_presence"].items()]
    b = res.get("bio", {})
    lines += [
        "",
        "## bio.csv",
        "",
        f"- Rows: {b.get('rows')}",
        f"- Columns: {b.get('columns')}",
        f"- Medication-like columns: {b.get('medication_like_columns')}",
        f"- Medication-like columns anywhere: {res['medication_like_columns_anywhere']}",
        f"- Sentinel error counts: {b.get('sentinel_error_counts')}",
        f"- HbA1c min/max: {b.get('a1c_min_max')}",
        "",
    ]
    lines += [
        "## Per participant",
        "",
        "| ID | Group | Rows | Days | Row step (min) | Dexcom interval | Dexcom non-integer share | Missing Dexcom | Missing HR | Meals |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for p in res["per_participant"]:
        ms = p["missing_share"]
        dexk = next((k for k in ms if "dexcom" in k.lower()), None)
        hrk = next((k for k in ms if k.strip().upper() == "HR"), None)
        lines.append(
            f"| {p['pid']} | {p['group']} | {p['rows']} | {p['span_days']} | {p['row_step_minutes_median']} | "
            f"{p['dexcom_native_interval_min']} | {p['dexcom_noninteger_share']} | "
            f"{round(ms.get(dexk, float('nan')), 3) if dexk else ''} | {round(ms.get(hrk, float('nan')), 3) if hrk else ''} | {p['meal_rows']} |"
        )
    lines += ["", "## Meals and label", ""]
    for k in [
        "meal_rows_total",
        "by_meal_type",
        "amount_consumed_non_null",
        "amount_consumed_lt_100",
        "carbs_fractional_share_partial_meals",
        "carbs_fractional_share_full_meals",
        "breakfast_count",
        "breakfast_distinct_macro_profiles",
        "macro_ranges",
        "exclusions",
        "usable_meals",
        "usable_meals_with_pre_meal_reading",
        "positives",
        "positive_rate",
        "positives_already_above_threshold_pre_meal",
        "participants_with_zero_positives",
        "post_meal_mets_present_share_mean",
    ]:
        if k in m:
            lines.append(f"- {k}: {m[k]}")
    lines += [
        "",
        "### By glycemic group",
        "",
        "| Group | Participants | With ≥1 positive | Usable meals | Positives |",
        "| --- | --- | --- | --- | --- |",
    ]
    for g, v in m.get("by_group", {}).items():
        lines.append(
            f"| {g} | {v['participants']} | {v['participants_with_any_positive']} | {v['usable']} | {v['positives']} |"
        )
    lines += [
        "",
        "### By participant",
        "",
        "| ID | Group | Usable | Positives |",
        "| --- | --- | --- | --- |",
    ]
    for r in m.get("by_participant", []):
        lines.append(f"| {r['pid']} | {r['group']} | {r['usable']} | {r['positives']} |")
    lines += [
        "",
        "### Sensitivity grid",
        "",
        "| Horizon (min) | Label | Usable | Positives | Rate | People with positive |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for r in m.get("sensitivity_grid", []):
        lines.append(
            f"| {r['horizon_min']} | {r['threshold']} | {r['usable']} | {r['positives']} | {r['rate']} | {r['participants_with_positive']} |"
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    source = Path(sys.argv[1]).expanduser()
    res = audit(source)
    here = Path(__file__).resolve().parent
    (here / "audit_results.json").write_text(json.dumps(res, indent=2, default=str))
    (here / "audit_report.md").write_text(to_markdown(res))
    print(to_markdown(res))


if __name__ == "__main__":
    main()
