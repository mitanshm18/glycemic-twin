"""M6 frontend adapter endpoints (ADR-019): CSRF rotation, state history, state diff, per-state
explanations, clinician-readable registry and the active model's evaluation report.
Disposable PostgreSQL; SYNTHETIC data and a SYNTHETIC bundle only."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest
from api_support import REPO, SOURCE_LABEL, login

API = "/api/v1"


def eligible(m1: Any, i: int = 0) -> pd.Series:
    t = m1["tables"]
    ok = (
        t["meal_outcomes"]
        .query("eligible")
        .merge(t["meals"][["meal_id", "started_at"]], on="meal_id")
    )
    return ok.iloc[i]


def scored_state(c: Any, m1: Any, minutes: int = 10) -> dict[str, Any]:
    m = eligible(m1)
    as_of = (m["started_at"] + pd.Timedelta(minutes=minutes)).isoformat()
    r = c.get(
        f"{API}/patients/{int(m['participant_id'])}/twin",
        params={"as_of": as_of, "meal_id": m["meal_id"]},
    )
    assert r.status_code == 200, r.text
    state: dict[str, Any] = r.json()
    assert state["risk"]["status"] == "scored"
    return state


def test_csrf_rotation_replaces_the_previous_token(clinician: Any) -> None:
    c, old = clinician
    r = c.get(f"{API}/auth/csrf")
    assert r.status_code == 200
    new = {"X-CSRF-Token": r.json()["csrf_token"]}
    assert new != old
    body = {"patient_id": 1, "start_at": "2020-01-01T00:00:00", "end_at": "2020-01-01T01:00:00"}
    assert c.post(f"{API}/replays", json=body, headers=old).json()["error"]["code"] == "CSRF_FAILED"
    assert c.post(f"{API}/replays", json=body, headers=new).status_code in (201, 404, 422)


def test_csrf_rotation_needs_a_session(client: Any) -> None:
    assert client.get(f"{API}/auth/csrf").json()["error"]["code"] == "UNAUTHENTICATED"


def test_state_history_and_diff_explain_what_changed(clinician: Any, m1: Any) -> None:
    c, _ = clinician
    m = eligible(m1)
    pid = int(m["participant_id"])
    a = c.get(f"{API}/patients/{pid}/twin", params={"as_of": m["started_at"].isoformat()}).json()
    later = (m["started_at"] + pd.Timedelta(minutes=121)).isoformat()
    b = c.get(f"{API}/patients/{pid}/twin", params={"as_of": later}).json()
    hist = c.get(f"{API}/patients/{pid}/twin-states").json()
    ids = [h["state_id"] for h in hist]
    assert a["state_id"] in ids and b["state_id"] in ids
    assert hist == sorted(hist, key=lambda h: h["as_of"], reverse=True)
    d = c.get(f"{API}/twin-states/{a['state_id']}/diff/{b['state_id']}")
    assert d.status_code == 200
    diff = d.json()
    assert diff["from_state_id"] == a["state_id"] and diff["to_state_id"] == b["state_id"]
    assert any("closed" in e for e in diff["explanations"])  # the meal's window closed in between
    assert c.get(f"{API}/twin-states/{'0' * 64}/diff/{b['state_id']}").status_code == 404


def test_explanation_sums_exactly_to_the_models_raw_score(
    clinician: Any, m1: Any, bundle: Any
) -> None:
    c, _ = clinician
    state = scored_state(c, m1)
    r = c.get(f"{API}/twin-states/{state['state_id']}/explanation")
    assert r.status_code == 200, r.text
    e = r.json()
    assert e["method"] == "linear_exact" and e["scale"].startswith("log-odds")
    contribs = e["contributions"]
    assert [x["feature"] for x in contribs] != [] and len(contribs) == 45
    assert {x["feature"] for x in contribs} == set(state["risk"]["model_inputs"])
    mags = [abs(x["contribution"]) for x in contribs]
    assert mags == sorted(mags, reverse=True)
    assert e["base_value"] + sum(x["contribution"] for x in contribs) == pytest.approx(
        e["raw_score"]
    )
    b = bundle["bundle"]
    X = pd.DataFrame(
        [[np.nan if v is None else v for v in state["risk"]["model_inputs"].values()]],
        columns=list(b.columns),
    )
    assert e["raw_score"] == pytest.approx(float(b.pipeline.decision_function(X)[0]), abs=1e-9)
    assert e["probability"] == state["risk"]["probability"]
    assert "not causes" in e["note"]


def test_unscored_states_are_not_explained(clinician: Any, m1: Any) -> None:
    c, _ = clinician
    pid = int(eligible(m1)["participant_id"])
    state = c.get(f"{API}/patients/{pid}/twin").json()  # latest observation: no open meal
    assert state["risk"]["status"] != "scored"
    r = c.get(f"{API}/twin-states/{state['state_id']}/explanation")
    assert r.status_code == 409 and r.json()["error"]["code"] == "NOT_EXPLAINABLE"


def test_clinicians_can_read_the_registry(clinician: Any, loaded: Any) -> None:
    c, _ = clinician
    rows = c.get(f"{API}/models").json()
    assert [m["id"] for m in rows if m["is_active"]] == [loaded["model_version_id"]]
    assert rows[0]["n_columns"] == 45


def _report(sha: str) -> dict[str, Any]:
    pop = {
        "pooled": {"meals": 10, "positives": 4, "auroc": 0.7, "pr_auc": 0.6, "brier": 0.2},
        "bootstrap_ci": {"auroc": {"lo": 0.6, "hi": 0.8, "valid_resamples": 10}},
        "per_fold": [
            {
                "fold": 0,
                "participants": 2,
                "meals": 5,
                "positives": 2,
                "auroc": 0.7,
                "pr_auc": 0.6,
                "brier": 0.2,
                "threshold": 0.4,
            }
        ],
        "calibration_curve": [{"bin": 0, "n": 5, "mean_predicted": 0.3, "observed_rate": 0.2}],
        "at_threshold": {"sensitivity": 0.5, "tp": 2},
    }
    return {
        "dataset_label": "SYNTHETIC TEST REPORT",
        "dataset_content_sha256": sha,
        "primary": {"run": "xgboost__full_personal"},
        "counts": {"eligible_target_meals": 10},
        "runs": {
            "logistic__full_personal": {
                "model": "logistic",
                "feature_set": "full_personal",
                "n_columns": 45,
                "target": pop,
                "healthy": {"pooled": {"meals": 0}},
            }
        },
        "comparisons": [{"comparison": "primary", "a": "x", "b": "y", "ran": False}],
        "shap": None,
    }


@pytest.fixture
def report_client(db_url: str, loaded: Any, tmp_path: Path) -> Any:
    from fastapi.testclient import TestClient
    from twin_api.app import create_app
    from twin_api.settings import Settings

    shutil.copytree(REPO / "data/configs", tmp_path / "data/configs")
    (tmp_path / "data/reports").mkdir(parents=True)
    app = create_app(
        Settings(
            database_url=db_url,
            environment="test",
            cookie_secure=False,
            source_label=SOURCE_LABEL,
            repo_root=tmp_path,
        )
    )
    with TestClient(app) as c:
        login(c, "clinician")
        yield c, tmp_path / "data/reports/m3_evaluation.json"


def test_evaluation_is_served_only_for_the_active_models_training_data(
    report_client: Any, bundle: Any
) -> None:
    c, path = report_client
    assert c.get(f"{API}/models/active/evaluation").json()["error"]["code"] == "NOT_FOUND"
    path.write_text(json.dumps(_report("0" * 64)))
    assert c.get(f"{API}/models/active/evaluation").json()["error"]["code"] == "MODEL_INCOMPATIBLE"
    path.write_text(json.dumps(_report(bundle["train_sha"])))
    r = c.get(f"{API}/models/active/evaluation")
    assert r.status_code == 200, r.text
    ev = r.json()
    assert ev["active_run"] == "logistic__full_personal"
    assert ev["runs"][0]["target"]["auroc"] == 0.7
    assert ev["runs"][0]["target"]["ci"]["auroc"] == {"lo": 0.6, "hi": 0.8}
    assert ev["active_per_fold"][0]["threshold"] == 0.4
    assert ev["active_calibration_curve"][0]["observed_rate"] == 0.2
    assert ev["limitations"] and ev["dataset_label"] == "SYNTHETIC TEST REPORT"


def test_overview_reports_each_patients_latest_stored_state(clinician: Any, m1: Any) -> None:
    c, _ = clinician
    before = {p["id"]: p for p in c.get(f"{API}/overview/patients").json()}
    listed = c.get(f"{API}/patients").json()
    assert sorted(before) == sorted(p["id"] for p in listed)  # same patients as the M5 list
    state = scored_state(c, m1, minutes=20)
    after = {p["id"]: p for p in c.get(f"{API}/overview/patients").json()}
    latest = after[state["patient_id"]]["latest_state"]
    assert latest["state_id"] == state["state_id"]
    assert latest["probability"] == state["risk"]["probability"]
    assert latest["lifecycle_phase"] == state["lifecycle"]["phase"]
    others = [p for pid, p in after.items() if pid != state["patient_id"]]
    assert all(p == before[p["id"]] for p in others)  # nothing computed for anyone else


def test_overview_needs_a_session(client: Any) -> None:
    assert client.get(f"{API}/overview/patients").status_code == 401
