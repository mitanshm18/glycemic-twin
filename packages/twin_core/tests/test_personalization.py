"""Shrinkage personalization: cold start, past-only, and convergence to the person's own rate."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from twin_core.personalization import PopulationPrior, fit_population_prior, personal_features

T = pd.Timestamp("2021-06-01 08:00")


def person(
    pid: int, labels: list[float], gap_min: int = 240, rise: float = 40.0, start: pd.Timestamp = T
) -> pd.DataFrame:
    n = len(labels)
    return pd.DataFrame(
        {
            "participant_id": pid,
            "started_at": [start + pd.Timedelta(minutes=gap_min * i) for i in range(n)],
            "frozen_usable": True,
            "label": pd.array(labels, dtype="Float64"),
            "rise_native_mgdl": rise + np.arange(n) % 3,
            "carbs_g": 50.0 + 10 * (np.arange(n) % 4),
            "fiber_g": 5.0,
            "pre_meal_native_mgdl": 110.0 + np.arange(n) % 5,
        }
    )


def population() -> pd.DataFrame:
    rng = np.random.default_rng(0)
    frames = []
    for pid, rate in enumerate([0.1, 0.3, 0.5, 0.7, 0.9, 0.2, 0.6, 0.4]):
        labels = (rng.random(30) < rate).astype(float).tolist()
        frames.append(person(pid, labels, rise=30 + 40 * rate))
    return pd.concat(frames, ignore_index=True)


PRIOR = PopulationPrior(
    alpha=2.0, beta=2.0, rise_coef=(40.0, 0.0, 0.0, 0.0), k=4.0, n_people=8, n_meals=240
)


def test_prior_mean_matches_population_rate() -> None:
    train = population()
    prior = fit_population_prior(train)
    per_person = train.groupby("participant_id")["label"].mean()
    assert prior.population_rate == pytest.approx(per_person.mean(), abs=1e-6)
    assert 1.0 <= prior.alpha + prior.beta <= 1000.0
    assert 1.0 <= prior.k <= 200.0 and prior.n_people == 8


def test_prior_needs_two_people() -> None:
    with pytest.raises(ValueError):
        fit_population_prior(person(1, [1, 0, 1, 0]))


def test_cold_start_is_the_population() -> None:
    out = personal_features(person(9, [1.0]), PRIOR, 120)
    row = out.iloc[0]
    assert row["p_personal"] == pytest.approx(0.5)  # alpha / (alpha + beta)
    assert (row["rise_offset_mgdl"], row["personal_weight"], row["n_closed_meals"]) == (0, 0, 0)


def test_only_closed_windows_count() -> None:
    # meals 119 minutes apart: the previous meal's window is still open at the next meal's start
    out = personal_features(person(9, [1.0, 1.0, 1.0], gap_min=119), PRIOR, 120)
    assert out["n_closed_meals"].tolist() == [0, 0, 1]
    exact = personal_features(person(9, [1.0, 1.0], gap_min=120), PRIOR, 120)
    assert exact["n_closed_meals"].tolist() == [0, 1]


def test_estimates_move_toward_the_person_with_more_meals() -> None:
    out = personal_features(person(9, [1.0] * 40, rise=60.0), PRIOR, 120)
    p = out["p_personal"].to_numpy()
    assert p[0] == pytest.approx(0.5) and p[-1] > 0.9 and np.all(np.diff(p) >= -1e-12)
    n = out["n_closed_meals"].iloc[-1]
    assert out["personal_weight"].iloc[-1] == pytest.approx(n / (n + PRIOR.k))
    assert out["rise_offset_mgdl"].iloc[-1] > 15  # rises ~21 above the prior's 40 on average


def test_future_meals_do_not_change_past_estimates() -> None:
    early = person(9, [1.0, 0.0, 1.0, 1.0])
    later = pd.concat(
        [early, person(9, [0.0] * 10, start=T + pd.Timedelta(days=5))], ignore_index=True
    )
    a = personal_features(early, PRIOR, 120)
    b = personal_features(later, PRIOR, 120).iloc[: len(early)]
    pd.testing.assert_frame_equal(a, b)


def test_unusable_meals_are_ignored_and_one_person_only() -> None:
    p = person(9, [1.0, 1.0, 1.0])
    p.loc[0, "frozen_usable"] = False
    assert personal_features(p, PRIOR, 120)["n_closed_meals"].tolist() == [0, 0, 1]
    with pytest.raises(ValueError):
        personal_features(pd.concat([person(1, [1.0]), person(2, [0.0])]), PRIOR, 120)
