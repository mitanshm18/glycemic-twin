"""SYNTHETIC test fixture shaped like CGMacros. For tests only: never used for training or results.

Four participants (2 healthy, 3 prediabetes, 4 and 5 T2D) over 3 days, plus subject 6 who is in
bio.csv but has no time-series file. Glucose is built from a known curve, sampled as integer native
readings (Dexcom every 5 min at a chosen phase, Libre every 15 min) and linearly interpolated to one
row per minute, reproducing the structure found in the real audit. Quirks are planted on purpose:

P2  ISO timestamps, "Image path", Amount Consumed 900 at dinner day 0, energy-inconsistent lunch day 2,
    a "snack 1" on day 1
P3  M/D/YYYY timestamps, no METs column but an Intensity column, sensor change on day 1
    (Dexcom gap 10:00-13:00 and the native phase moves 1 -> 3), one identical and one conflicting
    duplicate timestamp
P4  "Unnamed: 0" column, snack 60 min after lunch day 1 (overlap), unlogged excursion so breakfast
    day 2 is already high, fiber > carbs at dinner day 2, an all-zero snack day 2, HR 250,
    Dexcom 30 (out of range)
P5  no Amount Consumed column; Dexcom missing 12:31-14:30 on day 1 (lunch has low coverage)
"""

from __future__ import annotations

import csv
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

START = pd.Timestamp("2021-06-01 00:00")
DAYS = 3
MEAL_TIMES = {"breakfast": "08:00", "lunch": "12:30", "dinner": "18:30"}


@dataclass
class PlannedMeal:
    day: int
    hhmm: str
    label: str  # raw Meal Type text
    carbs: float = 60.0
    protein: float = 20.0
    fat: float = 10.0
    fiber: float = 5.0
    calories: float | None = None  # default: Atwater-consistent
    amount: float | None = 100.0
    amplitude: float = 40.0  # glucose rise (mg/dL) at +45 min

    @property
    def t0(self) -> pd.Timestamp:
        return START + pd.Timedelta(days=self.day) + pd.Timedelta(self.hhmm + ":00")


@dataclass
class Participant:
    pid: int
    base: float
    phase: int
    libre_phase: int
    meals: list[PlannedMeal]
    iso_ts: bool = True
    image_col: str = "Image Path"
    mets: bool = True
    amount_col: bool = True
    extra_cols: dict[str, object] = field(default_factory=dict)
    dexcom_nan: list[tuple[str, str]] = field(default_factory=list)  # (start, end) inclusive
    phase_after: tuple[str, int] | None = None  # (from timestamp, new phase)
    extra_bumps: list[tuple[str, float]] = field(default_factory=list)  # unlogged (t, amplitude)


def _bump(minutes_since: np.ndarray) -> np.ndarray:
    up = np.clip(minutes_since / 45.0, 0, 1)
    down = np.clip((150.0 - minutes_since) / 105.0, 0, 1)
    shape = np.where(minutes_since < 45, up, down)
    return np.where((minutes_since > 0) & (minutes_since < 150), shape, 0.0)


def _standard_meals(amplitude: float) -> list[PlannedMeal]:
    labels = {"breakfast": "Breakfast", "lunch": "lunch", "dinner": "Dinner"}
    return [
        PlannedMeal(d, t, labels[k], amplitude=amplitude)
        for d in range(DAYS)
        for k, t in MEAL_TIMES.items()
    ]


def participants() -> list[Participant]:
    p2 = Participant(2, base=100, phase=2, libre_phase=7, meals=_standard_meals(40))
    p2.meals[2].amount = 900  # dinner day 0: invalid Amount Consumed
    p2.meals.append(
        PlannedMeal(1, "15:30", "snack 1", carbs=15, protein=3, fat=4, fiber=2, amplitude=10)
    )
    p2.meals[7].calories = 100.0  # lunch day 2: Atwater 400 kcal vs 100 logged -> inconsistent
    p2.image_col = "Image path"

    p3 = Participant(
        3,
        base=120,
        phase=1,
        libre_phase=4,
        meals=_standard_meals(40),
        iso_ts=False,
        mets=False,
        extra_cols={"Intensity": 0},
        dexcom_nan=[("2021-06-02 10:00", "2021-06-02 13:00")],
        phase_after=("2021-06-02 13:00", 3),
    )
    p3.meals.append(
        PlannedMeal(0, "15:00", "Snacks", carbs=20, protein=2, fat=5, fiber=1, amplitude=10)
    )

    p4 = Participant(
        4,
        base=150,
        phase=4,
        libre_phase=0,
        meals=_standard_meals(80),
        extra_cols={"Unnamed: 0": 0},
        extra_bumps=[("2021-06-03 07:05", 80)],
    )
    p4.meals.append(
        PlannedMeal(1, "13:30", "snack", carbs=15, protein=1, fat=1, fiber=1, amplitude=5)
    )
    p4.meals[8].fiber = 90.0  # dinner day 2: fiber > carbs (60) -> invalid
    p4.meals.append(PlannedMeal(2, "15:00", "Snacks", 0, 0, 0, 0, calories=0.0, amplitude=0))

    p5 = Participant(
        5,
        base=140,
        phase=0,
        libre_phase=10,
        meals=_standard_meals(70),
        amount_col=False,
        dexcom_nan=[("2021-06-02 12:31", "2021-06-02 14:30")],
    )
    return [p2, p3, p4, p5]


def _curve(p: Participant, minutes: pd.DatetimeIndex) -> np.ndarray:
    t = (minutes - START).total_seconds().to_numpy() / 60
    g = np.full(len(t), p.base, dtype=float)
    for meal in p.meals:
        g += meal.amplitude * _bump(t - (meal.t0 - START).total_seconds() / 60)
    for when, amp in p.extra_bumps:
        g += amp * _bump(t - (pd.Timestamp(when) - START).total_seconds() / 60)
    return g


def _sampled(
    minutes: pd.DatetimeIndex,
    curve: np.ndarray,
    phase_of: np.ndarray,
    period: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """Integer native readings on the lattice, linear interpolation between them."""
    idx = np.arange(len(minutes))
    on = (idx % period) == phase_of
    native_idx = idx[on]
    native_vals = np.round(curve[on] + rng.normal(0, 4, on.sum()))
    return np.interp(idx, native_idx, native_vals, left=np.nan, right=np.nan)


def build_participant_frame(p: Participant) -> pd.DataFrame:
    rng = np.random.default_rng(p.pid)
    minutes = pd.date_range(START, periods=DAYS * 1440, freq="min")
    curve = _curve(p, minutes)
    phase = np.full(len(minutes), p.phase)
    if p.phase_after:
        phase[minutes >= pd.Timestamp(p.phase_after[0])] = p.phase_after[1]
    idx = np.arange(len(minutes))
    dexcom = np.full(len(minutes), np.nan)
    # sample each constant-phase block separately so interpolation never crosses a phase change
    for ph in np.unique(phase):
        block = phase == ph
        sub = _sampled(minutes[block], curve[block], (ph - idx[block][0]) % 5, 5, rng)
        dexcom[block] = sub
    libre = _sampled(minutes, curve, p.libre_phase, 15, rng)
    for a, b in p.dexcom_nan:
        dexcom[(minutes >= pd.Timestamp(a)) & (minutes <= pd.Timestamp(b))] = np.nan

    df = pd.DataFrame(
        {
            "Timestamp": minutes.strftime("%Y-%m-%d %H:%M:%S")
            if p.iso_ts
            else [f"{t.month}/{t.day}/{t.year} {t.hour:02d}:{t.minute:02d}" for t in minutes],
            "Libre GL": libre,
            "Dexcom GL": dexcom,
            "HR": np.round(70 + rng.normal(0, 3, len(minutes))),
            "Calories (Activity)": 1.2,
        }
    )
    if p.mets:
        df["METs"] = 10 + (idx % 7)
    for col in ("Meal Type", "Calories", "Carbs", "Protein", "Fat", "Fiber"):
        df[col] = np.nan
    df["Meal Type"] = df["Meal Type"].astype(object)
    if p.amount_col:
        df["Amount Consumed"] = np.nan
    df[p.image_col] = None
    for meal in p.meals:
        i = int((meal.t0 - START).total_seconds() // 60)
        kcal = (
            meal.calories
            if meal.calories is not None
            else 4 * meal.carbs + 4 * meal.protein + 9 * meal.fat
        )
        df.loc[i, ["Meal Type", "Calories", "Carbs", "Protein", "Fat", "Fiber"]] = [
            meal.label,
            kcal,
            meal.carbs,
            meal.protein,
            meal.fat,
            meal.fiber,
        ]
        if p.amount_col:
            df.loc[i, "Amount Consumed"] = meal.amount
        df.loc[i, p.image_col] = f"photos/{meal.day}_{meal.hhmm}_before.jpg"
        df.loc[i + 20, p.image_col] = f"photos/{meal.day}_{meal.hhmm}_after.jpg"
    for col, val in p.extra_cols.items():
        df[col] = val
    if p.pid == 4:
        df.loc[300, "HR"] = 250
        df.loc[400, "Dexcom GL"] = 30
    if p.pid == 3:
        dup_same = df.iloc[[300]]
        dup_diff = df.iloc[[360]].copy()
        dup_diff["Dexcom GL"] = dup_diff["Dexcom GL"] + 7.5
        df = pd.concat([df, dup_same, dup_diff], ignore_index=True)
    return df


BIO_HEADER = [
    "subject",
    "Age",
    "Gender",
    "BMI",
    "Body weight ",
    "Height ",
    "Self-identify ",
    "A1c PDL (Lab)",
    "Fasting GLU - PDL (Lab)",
    "Insulin ",
    "Triglycerides",
    "Cholesterol",
    "HDL",
    "Non HDL ",
    "LDL (Cal)",
    "VLDL (Cal)",
    "Cho/HDL Ratio",
    "Collection time PDL (Lab)",
    "#1 Contour Fingerstick GLU",
    "Time (t)",
    " #2 Contour Fingerstick GLU",
    "Time (t)",
    "#3 Contour Fingerstick GLU",
    "Time (t)",
]
BIO_ROWS = {  # subject: (HbA1c, LDL)
    2: (5.4, 100),
    3: (6.0, 110),
    4: (7.2, 800),
    5: (6.9, 120),
    6: (5.0, 90),
}


def write_fixture(root: Path) -> Path:
    """Write the synthetic dataset under ``root/CGMacros`` and return that folder."""
    ds = root / "CGMacros"
    ds.mkdir(parents=True, exist_ok=True)
    with (ds / "bio.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(BIO_HEADER)
        for sid, (a1c, ldl) in BIO_ROWS.items():
            w.writerow(
                [
                    sid,
                    40 + sid,
                    "F" if sid % 2 else "M",
                    27.5,
                    170.0,
                    66.0,
                    "White",
                    a1c,
                    95 + sid,
                    8.5,
                    120,
                    190,
                    50,
                    140,
                    ldl,
                    25,
                    3.8,
                    "08:15",
                    110,
                    "08:30",
                    150,
                    "09:30",
                    130,
                    "10:30",
                ]
            )
    (ds / "microbes.csv").write_text("subject,bacteria_a\n2,1\n")
    (ds / "gut_health_test.csv").write_text("subject,score\n2,Good\n")
    for p in participants():
        folder = ds / f"CGMacros-{p.pid:03d}"
        folder.mkdir(exist_ok=True)
        build_participant_frame(p).to_csv(folder / f"CGMacros-{p.pid:03d}.csv", index=False)
        (folder / "photos").mkdir(exist_ok=True)
        (folder / "photos" / "0_08:00_before.jpg").write_bytes(b"\xff\xd8synthetic")
    return ds


def zip_fixture(folder: Path, zip_path: Path) -> Path:
    """Zip the fixture with a top-level directory, like a typical download."""
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(folder.rglob("*")):
            if f.is_file():
                zf.write(f, f"CGMacros_dateshifted365/{f.relative_to(folder).as_posix()}")
    return zip_path
